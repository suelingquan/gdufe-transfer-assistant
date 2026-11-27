"""Run this on the student's computer to relay public API calls to localhost.

The published sandbox cannot reach jwxt.gdufe.edu.cn. This agent keeps a
long-lived connection to the public app by polling /api/tunnel/poll, executes
each request against the local backend (http://127.0.0.1:8000), and posts the
response back. No password or cookie is written to disk by this script.
"""

from __future__ import annotations

import base64
import json
import os
import time

import requests

PUBLIC_URL = os.environ.get("RELAY_PUBLIC_URL", "").rstrip("/")
LOCAL_URL = os.environ.get("RELAY_LOCAL_URL", "http://127.0.0.1:8000").rstrip("/")
SECRET = os.environ.get("RELAY_SECRET", "")
AGENT_ID = os.environ.get("RELAY_AGENT_ID", "local-pc")
SHARE_CODE = os.environ.get("RELAY_SHARE_CODE", "")
POLL_INTERVAL = 0.6
REGISTER_INTERVAL = 20

session = requests.Session()
session.headers.update({"User-Agent": "gdufe-transfer-relay/1.0"})


def public_url(path: str) -> str:
    """The published app requires the share code on every request."""
    if not SHARE_CODE:
        return f"{PUBLIC_URL}{path}"
    separator = "&" if "?" in path else "?"
    return f"{PUBLIC_URL}{path}{separator}sharecode={SHARE_CODE}"


def register() -> bool:
    try:
        response = session.post(
            public_url("/api/tunnel/register"),
            json={"secret": SECRET, "agent_id": AGENT_ID},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def execute(task: dict) -> dict:
    headers = {
        key: value
        for key, value in (task.get("headers") or {}).items()
        if key.lower() not in ("host", "content-length", "accept-encoding", "connection")
    }
    body = base64.b64decode(task.get("body") or "")
    try:
        response = session.request(
            task.get("method", "GET"),
            f"{LOCAL_URL}{task.get('path', '/')}",
            headers=headers,
            data=body,
            timeout=120,
            allow_redirects=False,
        )
        return {
            "status": response.status_code,
            "body": base64.b64encode(response.content).decode("ascii"),
            "content_type": response.headers.get("Content-Type", "application/json"),
        }
    except Exception as exc:  # noqa: BLE001 - relay must never die on one task
        detail = json.dumps(
            {"detail": f"本地中继执行失败：{exc}"}, ensure_ascii=False
        ).encode("utf-8")
        return {
            "status": 502,
            "body": base64.b64encode(detail).decode("ascii"),
            "content_type": "application/json; charset=utf-8",
        }


def main() -> None:
    missing = [
        name
        for name, value in (
            ("RELAY_PUBLIC_URL", PUBLIC_URL),
            ("RELAY_SECRET", SECRET),
            ("RELAY_SHARE_CODE", SHARE_CODE),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少必需环境变量：{', '.join(missing)}")
    print(f"中继已启动：{PUBLIC_URL} -> {LOCAL_URL}", flush=True)
    next_register = 0.0
    handled = 0
    while True:
        now = time.time()
        if now >= next_register:
            if register():
                print("已连接公网服务，等待手机请求…", flush=True)
            else:
                print("连接公网服务失败，稍后重试…", flush=True)
            next_register = now + REGISTER_INTERVAL

        try:
            response = session.post(
                public_url("/api/tunnel/poll"),
                json={"secret": SECRET, "agent_id": AGENT_ID},
                timeout=20,
            )
            task = response.json() if response.ok else None
        except (requests.RequestException, ValueError):
            task = None

        if not task:
            time.sleep(POLL_INTERVAL)
            continue

        result = execute(task)
        try:
            session.post(
                public_url("/api/tunnel/result"),
                json={
                    "secret": SECRET,
                    "agent_id": AGENT_ID,
                    "task_id": task.get("id"),
                    **result,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            print(f"回传结果失败：{exc}", flush=True)
        handled += 1
        print(f"已转发请求 #{handled}: {task.get('method')} {task.get('path', '').split('?')[0]}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("中继已停止", flush=True)
