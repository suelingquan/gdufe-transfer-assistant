"""FastAPI entry point for the GDUFE transfer-major assistant."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import jwxt
from .comparator import compare, rank_programs
from .models import (
    CompareRequest,
    GpaEstimateRequest,
    Program,
    StudentProfile,
    SubstitutionRule,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
WEB_DIR = BASE_DIR / "web"
SESSION_TTL = 30 * 60  # 30 minutes

app = FastAPI(title="广财转专业助手 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# HTTP relay: the published sandbox cannot reach jwxt.gdufe.edu.cn, but the
# student's own computer can. A small agent on that computer polls these
# endpoints and executes each /api request against the local backend. The
# public app then returns the agent's response to the phone. Passwords and
# cookies stay in memory and are never written to disk by the relay.
# ---------------------------------------------------------------------------
RELAY_AGENT_ID = os.environ.get("RELAY_AGENT_ID", "local-pc")
# Only the published instance should forward API calls. The local backend that
# the agent talks to must keep handling requests directly, or it would recurse.
RELAY_ENABLED = os.environ.get("RELAY_MODE", "") == "public"
RELAY_SECRET = os.environ.get("RELAY_SECRET", "")
if RELAY_ENABLED and not RELAY_SECRET:
    raise RuntimeError("RELAY_SECRET is required when RELAY_MODE=public")
RELAY_TIMEOUT = 90
_tunnel_tasks: dict[str, dict] = {}
_agent_last_seen: dict[str, float] = {}


def _agent_online() -> bool:
    return time.time() - _agent_last_seen.get(RELAY_AGENT_ID, 0) < 45


def _check_relay(payload: dict) -> None:
    if not RELAY_SECRET or payload.get("secret") != RELAY_SECRET or payload.get("agent_id") != RELAY_AGENT_ID:
        raise HTTPException(403, "中继凭据无效")


def _cleanup_tunnel() -> None:
    for task_id, task in list(_tunnel_tasks.items()):
        if time.time() - task.get("created", 0) > RELAY_TIMEOUT + 30:
            _tunnel_tasks.pop(task_id, None)


@app.post("/api/tunnel/register")
def tunnel_register(payload: dict):
    _check_relay(payload)
    _agent_last_seen[RELAY_AGENT_ID] = time.time()
    return {"ok": True, "agent_id": RELAY_AGENT_ID}


@app.get("/api/tunnel/status")
def tunnel_status():
    return {"online": _agent_online()}


@app.post("/api/tunnel/poll")
def tunnel_poll(payload: dict):
    _check_relay(payload)
    _agent_last_seen[RELAY_AGENT_ID] = time.time()
    _cleanup_tunnel()
    for task in _tunnel_tasks.values():
        if task.get("status") == "pending":
            task["status"] = "processing"
            return {
                "id": task["id"],
                "method": task["method"],
                "path": task["path"],
                "headers": task["headers"],
                "body": task["body"],
            }
    return None


@app.post("/api/tunnel/result")
def tunnel_result(payload: dict):
    _check_relay(payload)
    _agent_last_seen[RELAY_AGENT_ID] = time.time()
    task = _tunnel_tasks.get(payload.get("task_id", ""))
    if not task:
        return {"ok": False}
    task["result"] = {
        "status": int(payload.get("status", 200)),
        "body": payload.get("body", ""),
        "content_type": payload.get("content_type") or "application/json",
    }
    task["status"] = "done"
    return {"ok": True}


@app.middleware("http")
async def relay_middleware(request: Request, call_next):
    path = request.url.path
    if (
        RELAY_ENABLED
        and path.startswith("/api/")
        and not path.startswith("/api/tunnel/")
        and path != "/api/health"
        and _agent_online()
    ):
        body = await request.body()
        task_id = uuid.uuid4().hex
        target = path + (f"?{request.url.query}" if request.url.query else "")
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in ("host", "content-length", "accept-encoding", "connection")
        }
        _tunnel_tasks[task_id] = {
            "id": task_id,
            "method": request.method,
            "path": target,
            "headers": headers,
            "body": base64.b64encode(body).decode("ascii"),
            "status": "pending",
            "created": time.time(),
        }
        deadline = time.time() + RELAY_TIMEOUT
        while time.time() < deadline:
            task = _tunnel_tasks.get(task_id)
            if task and task.get("status") == "done":
                result = task["result"]
                _tunnel_tasks.pop(task_id, None)
                return Response(
                    content=base64.b64decode(result.get("body", "")),
                    status_code=result.get("status", 200),
                    media_type=result.get("content_type"),
                )
            await asyncio.sleep(0.15)
        _tunnel_tasks.pop(task_id, None)
        return Response(
            content=json.dumps(
                {"detail": "本地中继响应超时，请确认电脑上的中继脚本正在运行"},
                ensure_ascii=False,
            ),
            status_code=504,
            media_type="application/json; charset=utf-8",
        )
    return await call_next(request)


@dataclass
class AuthState:
    session: requests.Session
    profile: StudentProfile
    created_at: float = field(default_factory=time.time)


_authed: dict[str, AuthState] = {}

SESSION_DIR = DATA_DIR / "sessions"


def _save_session(token: str, session: requests.Session, profile: StudentProfile) -> None:
    """Persist only cookies + profile (never the password) so restarts keep login."""
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookies": session.cookies.get_dict(),
            "profile": profile.model_dump(),
            "created_at": time.time(),
        }
        (SESSION_DIR / f"{token}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _restore_session(token: str) -> Optional[AuthState]:
    path = SESSION_DIR / f"{token}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("created_at", 0) > SESSION_TTL:
            path.unlink(missing_ok=True)
            return None
        session = jwxt.new_session()
        session.cookies.update(data.get("cookies", {}))
        profile = StudentProfile(**data["profile"])
        state = AuthState(session=session, profile=profile, created_at=data.get("created_at", time.time()))
        _authed[token] = state
        return state
    except (OSError, ValueError, KeyError):
        return None


def _load_json(name: str):
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _demo_programs() -> list[Program]:
    return [Program(**item) for item in _load_json("demo_programs.json")]


def _rules() -> list[SubstitutionRule]:
    return [SubstitutionRule(**item) for item in _load_json("substitution_rules.json")]


def _find_program(programs: list[Program], major: str, grade: int) -> Optional[Program]:
    for program in programs:
        if program.major == major and (not grade or program.grade == grade):
            return program
    for program in programs:
        if program.major == major:
            return program
    return None


@dataclass
class PendingSession:
    session: requests.Session
    created_at: float = field(default_factory=time.time)


_pending_sessions: dict[str, PendingSession] = {}


def _clean_expired() -> None:
    now = time.time()
    for key in [
        k for k, v in _pending_sessions.items() if now - v.created_at > SESSION_TTL
    ]:
        _pending_sessions.pop(key, None)
    for key in [k for k, v in _authed.items() if now - v.created_at > SESSION_TTL]:
        _authed.pop(key, None)



@app.get("/api/health")
def health():
    return {"ok": True, "service": "gdufe-transfer-assistant"}


@app.get("/api/demo/programs")
def demo_programs():
    return [program.summary() for program in _demo_programs()]


@app.get("/api/demo/programs/{major}")
def demo_program(major: str, grade: int = 0):
    program = _find_program(_demo_programs(), major, grade)
    if not program:
        raise HTTPException(404, f"演示数据中没有找到专业：{major}")
    return program


@app.get("/api/rules")
def rules():
    return _rules()


@app.get("/api/transfer-stats")
def transfer_stats():
    """Anonymised 2024 transfer-list data for GPA reference."""
    return _load_json("transfer_gpa_2024.json")


@app.post("/api/gpa-estimate")
def gpa_estimate(payload: GpaEstimateRequest):
    """Compare a student's GPA against the 2024 transfer list, per major.

    The result is a *percentile reference*, not an admission probability.
    """
    import bisect
    import statistics

    dataset = _load_json("transfer_gpa_2024.json")
    records = dataset["records"]
    by_major: dict[str, list[float]] = {}
    for record in records:
        by_major.setdefault(record["to_major"], []).append(record["gpa"])

    names = payload.target_majors or list(by_major)
    output = []
    for name in names:
        values = sorted(by_major.get(name, []))
        if not values:
            continue
        below = bisect.bisect_right(values, payload.gpa)
        percentile = round(below / len(values) * 100, 1)
        minimum, maximum = values[0], values[-1]
        median = statistics.median(values)
        if payload.gpa >= maximum:
            level = "很有优势"
        elif payload.gpa >= median:
            level = "较有把握"
        elif payload.gpa >= minimum:
            level = "有机会，接近往年区间下沿"
        else:
            level = "低于往年名单最低绩点"
        output.append(
            {
                "major": name,
                "count": len(values),
                "min": round(minimum, 4),
                "median": round(median, 4),
                "max": round(maximum, 4),
                "percentile": percentile,
                "rank": len(values) - below + 1,
                "gap_to_min": round(payload.gpa - minimum, 4),
                "level": level,
            }
        )
    output.sort(key=lambda item: (-item["percentile"], item["major"]))
    return {"gpa": payload.gpa, "note": dataset["note"], "items": output}


class CaptchaRequest(BaseModel):
    captcha_id: Optional[str] = None


@app.post("/api/auth/captcha")
def captcha(payload: CaptchaRequest = CaptchaRequest()):
    """Create a fresh session and return the CAPTCHA image as a data URL."""
    _clean_expired()
    if payload.captcha_id and payload.captcha_id in _pending_sessions:
        session = _pending_sessions[payload.captcha_id].session
        captcha_id = payload.captcha_id
    else:
        session = jwxt.new_session()
        captcha_id = uuid.uuid4().hex
        _pending_sessions[captcha_id] = PendingSession(session=session)
    try:
        image, mime = jwxt.fetch_captcha(session)
    except (jwxt.JwxtError, requests.RequestException) as exc:
        raise HTTPException(502, str(exc)) from exc
    encoded = base64.b64encode(image).decode("ascii")
    return {"captcha_id": captcha_id, "image": f"data:{mime};base64,{encoded}"}


class LoginRequest(BaseModel):
    captcha_id: str
    username: str
    password: str
    captcha: str


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    pending = _pending_sessions.pop(payload.captcha_id, None)
    if pending is None:
        raise HTTPException(400, "验证码会话已过期，请刷新后重试")
    ok, message = jwxt.login(
        pending.session, payload.username, payload.password, payload.captcha
    )
    if not ok:
        # Allow the student to retry with the same session and a new code.
        new_id = uuid.uuid4().hex
        _pending_sessions[new_id] = PendingSession(session=pending.session)
        return {"ok": False, "message": message, "captcha_id": new_id}

    try:
        profile = jwxt.fetch_profile(pending.session, payload.username.strip())
    except jwxt.JwxtError as exc:
        raise HTTPException(502, str(exc)) from exc
    token = uuid.uuid4().hex
    _authed[token] = AuthState(session=pending.session, profile=profile)
    _save_session(token, pending.session, profile)
    return {
        "ok": True,
        "message": message,
        "token": token,
        "profile": profile,
    }


def _auth_state(token: Optional[str]) -> AuthState:
    _clean_expired()
    state = _authed.get(token or "")
    if state is None and token:
        state = _restore_session(token)
    if state is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    return state


@app.get("/api/me")
def me(token: str):
    return _auth_state(token).profile


@app.get("/api/programs/options")
def program_options(token: str):
    state = _auth_state(token)
    try:
        groups = jwxt.fetch_program_form_options(state.session)
    except jwxt.JwxtError as exc:
        raise HTTPException(502, str(exc)) from exc
    # Provide a college view even when the query page has no college selector.
    for name, values in groups.items():
        if "专业" in name or "zy" in name.lower() or "major" in name.lower():
            groups["_college_groups"] = list(jwxt.infer_colleges(values).items())
            break
    return groups


@app.get("/api/programs/colleges")
def program_colleges(token: str):
    """The real 学院 options from the school's query page, with form values."""
    state = _auth_state(token)
    try:
        return {"colleges": jwxt.fetch_colleges(state.session)}
    except jwxt.JwxtError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/programs/majors")
def program_majors(token: str, college: str = "", grade: int = 0):
    """Majors for a selected college (the school's dropdown is cascading)."""
    state = _auth_state(token)
    try:
        if college:
            majors = jwxt.fetch_majors_by_college(state.session, college, grade)
            if majors:
                return {"majors": majors, "college": college}
        groups = jwxt.fetch_program_form_options(state.session)
        for name, values in groups.items():
            if "专业" in name or "zy" in name.lower():
                filtered = [v for v in values if "请选择" not in v]
                if filtered:
                    return {"majors": filtered, "college": college}
        return {"majors": [], "college": college}
    except jwxt.JwxtError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/debug/program-html")
def debug_program_html(token: str, major: str, grade: int, college: str = ""):
    """Development helper: capture the raw HTML from the training-program query.

    Used only to adapt the parser when the school changes its page structure.
    Saves snapshots under backend/data/debug and reports what was captured.
    """
    state = _auth_state(token)
    try:
        program = jwxt.fetch_program(state.session, major, grade, college_code=college)
    except jwxt.JwxtError as exc:
        raise HTTPException(502, str(exc)) from exc
    debug_dir = jwxt.DEBUG_DIR
    files = sorted(p.name for p in debug_dir.glob("*.html"))[-40:] if debug_dir.exists() else []
    return {
        "program": program,
        "snapshots": files,
    }


@app.get("/api/programs/live")
def live_program(token: str, major: str, grade: int):
    state = _auth_state(token)
    try:
        program = jwxt.fetch_program(state.session, major, grade)
    except (jwxt.JwxtError, requests.RequestException) as exc:
        raise HTTPException(502, str(exc)) from exc
    if program is None:
        raise HTTPException(404, "未能从教务系统解析出该专业的培养方案")
    return program


class ImportRequest(BaseModel):
    major: str
    grade: int
    html: str = ""
    program: Optional[Program] = None


@app.post("/api/programs/import")
def import_program(payload: ImportRequest):
    if payload.program:
        return payload.program
    if not payload.html.strip():
        raise HTTPException(400, "请粘贴培养方案 HTML 或提供 JSON")
    program = jwxt.parse_program_table(
        payload.html, payload.major, payload.grade, source="import"
    )
    if program is None:
        raise HTTPException(422, "未能识别出课程表，请确认粘贴内容包含“课程名称”“学分”表头")
    return program


@app.post("/api/compare")
def compare_programs(payload: CompareRequest):
    fetch_errors: list[str] = []
    if payload.source == "live":
        state = _auth_state(payload.token)
        profile = state.profile
        programs = []
        for major in payload.target_majors:
            try:
                program = jwxt.fetch_program(
                    state.session,
                    major,
                    payload.grade,
                    college_code=payload.major_colleges.get(major, ""),
                )
            except jwxt.JwxtError as exc:
                fetch_errors.append(str(exc))
                continue
            if program:
                programs.append(program)
            else:
                fetch_errors.append(f"未能解析「{major}」培养方案")
        all_programs = programs
        current = _find_program(programs, payload.current_major, payload.grade)
        if current is None:
            # The student's own program is shown on a display-only page.
            current = jwxt.fetch_own_program(
                state.session,
                payload.current_major,
                payload.grade,
                college=profile.college,
            )
            if current is None:
                fetch_errors.append(
                    f"未能解析你的专业「{payload.current_major}」执行计划"
                )
    else:
        profile = payload.profile
        if payload.source == "import":
            all_programs = payload.imported_programs
        else:
            all_programs = _demo_programs()
        current = _find_program(all_programs, payload.current_major, payload.grade)

    if current is None:
        current = Program(
            major=payload.current_major,
            grade=payload.grade,
            courses=[],
            source="demo" if payload.source == "demo" else "import",  # type: ignore[arg-type]
        )

    # Only compare programs from the selected entering grade. When a grade is
    # unavailable for a major, fall back to its nearest available year.
    by_major: dict[str, Program] = {}
    for program in all_programs:
        existing = by_major.get(program.major)
        if existing is None or (
            abs(program.grade - payload.grade) < abs(existing.grade - payload.grade)
        ):
            by_major[program.major] = program
    same_grade = list(by_major.values())

    targets = [
        program
        for program in same_grade
        if program.major in payload.target_majors or not payload.target_majors
    ]
    results = [
        compare(profile, current, program, payload.rules)
        for program in targets
        if program.major != current.major
    ]
    ranking = rank_programs(profile, current, same_grade, payload.rules)
    return {
        "profile": profile,
        "current": current,
        "results": results,
        "ranking": ranking,
        "fetch_errors": fetch_errors,
    }


# Serve the built React app from the same origin as the API. Registered last so
# every /api route above keeps precedence; unknown paths fall back to index.html
# for client-side navigation.
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    candidate = (WEB_DIR / full_path).resolve()
    if candidate.is_file() and WEB_DIR.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = WEB_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "前端未构建")
