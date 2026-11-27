"""Adapter for the GDUFE 强智 (jsxsd) educational system.

Design notes
------------
* The password is only used for the single login POST. It is never written to
  disk, logged, or kept in the session store after the call returns.
* The 4-digit image CAPTCHA is shown to the student instead of being solved by
  OCR. This keeps the project robust and avoids automated bypass of the school's
  protection.
* The site mixes GBK and UTF-8, so every response is decoded defensively.
* Page structures vary between schools and years. Parsing is driven by table
  headers rather than fixed column indexes, and a manual HTML-import path is
  provided as a fallback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import Course, Program, StudentProfile

BASE = "http://jwxt.gdufe.edu.cn/jsxsd"
CAPTCHA_URL = f"{BASE}/verifycode.servlet"
LOGIN_URL = f"{BASE}/xk/LoginToXkLdap"
GRADES_URL = f"{BASE}/kscj/cjcx_list"
PROFILE_URL = f"{BASE}/grxx/xsxx"
OWN_PROGRAM_URL = f"{BASE}/pyfa/topyfamx"
OWN_PROGRAM_ALT_URL = f"{BASE}/pyfa/pyfa_query"
PROGRAM_FIND_URL = f"{BASE}/jspyfa/pyfa_find"
# The "查询" button on pyfa_find overrides the form action in JavaScript.
# Posting to pyfa_find only re-renders the filters; the course table is served
# by zypyfa_query.
PROGRAM_QUERY_URL = f"{BASE}/jspyfa/zypyfa_query"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
LOGIN_FAILURE_MARKERS = (
    "请先登录系统",
    "验证码错误",
    "验证码不正确",
    "用户名或密码错误",
    "密码错误",
    "用户名不存在",
    "登录失败",
)


class JwxtError(Exception):
    """Raised when the educational system cannot be reached or parsed."""


def decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    return session


def get_text(session: requests.Session, url: str, **kwargs) -> str:
    response = session.get(url, timeout=20, **kwargs)
    response.raise_for_status()
    return decode_bytes(response.content)


def fetch_captcha(session: requests.Session) -> tuple[bytes, str]:
    """Fetch the CAPTCHA image; the session keeps the matching JSESSIONID.

    The school server rejects direct requests to verifycode.servlet — the
    login page must be visited first to obtain a session cookie, and the image
    request must carry that page as its Referer.
    """
    try:
        session.get(f"{BASE}/framework/xsMain.jsp", timeout=20)
    except requests.RequestException as exc:
        raise JwxtError(f"无法连接教务系统：{exc}") from exc

    response = session.get(
        CAPTCHA_URL,
        headers={"Referer": f"{BASE}/framework/xsMain.jsp"},
        timeout=20,
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/"):
        raise JwxtError("验证码接口返回的不是图片，请稍后重试")
    return response.content, content_type


def is_logged_in(session: requests.Session) -> bool:
    try:
        html = get_text(session, f"{BASE}/framework/xsMain.jsp")
    except requests.RequestException:
        return False
    return "学生个人中心" in html or "请先登录系统" not in html and "用户登录" not in html


def login(
    session: requests.Session, username: str, password: str, captcha: str
) -> tuple[bool, str]:
    """Attempt login with credentials supplied by the student.

    Returns (success, human-readable message). The password is not retained.
    """
    if not username.strip() or not password or not captcha.strip():
        return False, "请填写学号、密码和验证码"

    payload = {
        "USERNAME": username.strip(),
        "PASSWORD": password,
        "RANDOMCODE": captcha.strip(),
    }
    try:
        response = session.post(
            LOGIN_URL,
            data=payload,
            headers={"Referer": f"{BASE}/framework/xsMain.jsp"},
            timeout=20,
            allow_redirects=True,
        )
        text = decode_bytes(response.content)
    except requests.RequestException as exc:
        return False, f"无法连接教务系统：{exc}"

    if any(marker in text for marker in LOGIN_FAILURE_MARKERS):
        return False, "登录失败：账号、密码或验证码不正确（请刷新验证码重试）"

    try:
        if is_logged_in(session):
            return True, "登录成功"
    except Exception:
        pass
    if "xsMain.jsp" in response.url:
        return True, "登录成功"
    return False, "登录状态未确认，请检查账号密码或稍后重试"


def _clean_text(value: str) -> str:
    """Strip leftover markup/entities from a scraped value."""
    value = re.sub(r"<[^>]+>", "", value or "")
    value = value.replace("&nbsp;", " ").replace("\u3000", " ")
    return value.strip()


def _field_text(label: str, html: str) -> str:
    """Read a value from a label/value pair in the 学籍卡片 page.

    The page renders fields as table cells (label cell + value cell). Earlier
    regex scraping captured raw markup like '金融科技</td>'; parsing the DOM
    avoids that. A plain-text fallback covers non-table layouts.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for cell in soup.find_all(["td", "th"]):
        text = cell.get_text(" ", strip=True)
        normalized = text.rstrip("：: ").strip()
        if normalized == label or text.strip().startswith(label + "：") or text.strip().startswith(label + ":"):
            if text.strip() in (label, label + "：", label + ":"):
                nxt = cell.find_next_sibling(["td", "th"])
                if nxt:
                    return _clean_text(nxt.get_text(" ", strip=True))
                continue
            inline = re.sub(rf"^\s*{re.escape(label)}\s*[：:]?\s*", "", text.strip())
            return _clean_text(inline)
    match = re.search(rf"{re.escape(label)}\s*[：:]\s*([^\s<\n]+)", html)
    return _clean_text(match.group(1)) if match else ""


def _extract_grade(html: str, student_id: str) -> int:
    """Resolve the entering year from the 学籍卡片, then the student ID."""
    if html:
        soup = BeautifulSoup(html, "html.parser")
        preferred = ("入学年级", "年级", "入学年月", "入学时间", "学籍年级")
        for label in preferred:
            for cell in soup.find_all(["td", "th"]):
                text = cell.get_text(" ", strip=True)
                if label not in text:
                    continue
                match = re.search(r"(20\d{2})", text)
                if match:
                    return int(match.group(1))
                nxt = cell.find_next_sibling(["td", "th"])
                if nxt:
                    match = re.search(r"(20\d{2})", nxt.get_text(" ", strip=True))
                    if match:
                        return int(match.group(1))
    sid = (student_id or "").strip()
    match = re.match(r"^(20\d{2})", sid)
    if match:
        return int(match.group(1))
    match = re.match(r"^(\d{2})", sid)
    if match and 0 <= int(match.group(1)) <= 30:
        return 2000 + int(match.group(1))
    return 0


def fetch_profile(session: requests.Session, student_id: str) -> StudentProfile:
    """Fetch the student's 学籍卡片; fall back to sensible defaults."""
    html = ""
    try:
        html = get_text(session, PROFILE_URL)
    except requests.RequestException:
        pass

    name = _clean_text(_field_text("姓名", html))
    major = _clean_text(_field_text("专业", html))
    college = _clean_text(_field_text("院系", html) or _field_text("学院", html))
    grade = _extract_grade(html, student_id)

    return StudentProfile(
        student_id=student_id,
        name=name,
        major=major or "未识别专业（可在页面手动选择）",
        grade=grade,
        college=college,
        completed=fetch_grades(session),
    )


_GRADE_POINTS = {
    "优秀": 95.0,
    "良好": 85.0,
    "中等": 75.0,
    "及格": 65.0,
    "不及格": 0.0,
}


def _score_value(text: str) -> float:
    text = (text or "").strip()
    if text in _GRADE_POINTS:
        return _GRADE_POINTS[text]
    try:
        return float(text)
    except ValueError:
        return 0.0


def _cells(row) -> list[str]:
    return [
        cell.get_text(" ", strip=True)
        for cell in row.find_all(["td", "th"], recursive=False)
    ]


def _find_header_row(table, required_keywords: tuple[str, ...]):
    """Find a real table header, ignoring long merged cells that mention everything.

    The 培养方案 page contains a giant description cell that includes both
    "课程名称" and "学分" as prose.  Requiring each keyword to live in a
    different cell keeps that paragraph from being mistaken for a header.
    """
    for row in table.find_all("tr"):
        cells = _cells(row)
        if len(cells) < len(required_keywords):
            continue
        normalized = [re.sub(r"\s+", "", cell) for cell in cells]
        used: set[int] = set()
        matched = True
        for keyword in required_keywords:
            found = next(
                (i for i, cell in enumerate(normalized) if keyword in cell and i not in used),
                None,
            )
            if found is None:
                matched = False
                break
            used.add(found)
        if matched:
            return cells
    return None


def _column_index(header: list[str], *keywords: str) -> Optional[int]:
    for keyword in keywords:
        needle = re.sub(r"\s+", "", keyword)
        for idx, value in enumerate(header):
            if needle in re.sub(r"\s+", "", value):
                return idx
    return None


def parse_grade_table(html: str) -> list[Course]:
    """Parse the transcript table returned by /kscj/cjcx_list."""
    soup = BeautifulSoup(html, "html.parser")
    courses: list[Course] = []
    seen: dict[tuple[str, str], Course] = {}

    for table in soup.find_all("table"):
        header = _find_header_row(table, ("课程名称", "学分"))
        if not header:
            continue
        i_code = _column_index(header, "课程编号", "课程代码", "课号")
        i_name = _column_index(header, "课程名称", "课程名")
        i_credit = _column_index(header, "学分")
        i_score = _column_index(header, "总评成绩", "成绩")
        i_category = _column_index(header, "课程性质", "课程属性")
        if i_name is None or i_credit is None:
            continue

        for row in table.find_all("tr"):
            cells = _cells(row)
            if len(cells) <= max(i_name, i_credit):
                continue
            name = cells[i_name].strip()
            if not name or name in header or "课程名称" in name:
                continue
            try:
                credits = float(re.search(r"\d+(?:\.\d+)?", cells[i_credit]).group())
            except (AttributeError, ValueError):
                continue
            code = cells[i_code].strip() if i_code is not None and len(cells) > i_code else ""
            score = cells[i_score].strip() if i_score is not None and len(cells) > i_score else ""
            category = (
                cells[i_category].strip()
                if i_category is not None and len(cells) > i_category
                else ""
            )
            passed = _score_value(score) >= 60 or score in _GRADE_POINTS and _score_value(score) > 0
            course = Course(
                code=code,
                name=name,
                credits=credits,
                category=category,
                score=score,
                passed=passed,
            )
            key = (code, name)
            previous = seen.get(key)
            if previous is None or _score_value(score) > _score_value(previous.score or ""):
                seen[key] = course

    courses = list(seen.values())
    return courses


def fetch_grades(session: requests.Session) -> list[Course]:
    payload = {"kksj": "", "kcxz": "", "kcmc": "", "fxkc": "0", "xsfs": "all"}
    try:
        response = session.post(GRADES_URL, data=payload, timeout=20)
        response.raise_for_status()
        return parse_grade_table(decode_bytes(response.content))
    except requests.RequestException as exc:
        raise JwxtError(f"获取成绩单失败：{exc}") from exc


def parse_program_table(
    html: str, major: str, grade: int, source: str = "live", college: str = ""
) -> Optional[Program]:
    """Parse a 培养方案 table by detecting its header columns.

    GDUFE's real zypyfa_query page merges category/nature/module cells across
    consecutive rows, so later rows begin directly with the course code.  We
    therefore locate each course by its code cell and remember the leading
    category/nature/module values from the first row of each merged block.
    """
    soup = BeautifulSoup(html, "html.parser")
    courses: list[Course] = []
    seen: dict[tuple[str, str], Course] = {}
    total_credits = 0.0

    page_text = soup.get_text(" ", strip=True)
    for pattern in (
        r"专业要求课程修读总学分\s*(\d+(?:\.\d+)?)\s*分",
        r"修满\s*(\d+(?:\.\d+)?)\s*学分",
        r"合计\s*(\d+(?:\.\d+)?)\s*学分",
    ):
        declared = re.search(pattern, page_text)
        if declared:
            total_credits = float(declared.group(1))
            break

    code_pattern = re.compile(r"[0-9A-Za-z][0-9A-Za-zX]{5,11}")
    for table in soup.find_all("table"):
        header = _find_header_row(table, ("课程名称", "学分"))
        if not header:
            continue
        i_code = _column_index(header, "课程代码", "课程编号", "课号")
        i_name = _column_index(header, "课程名称", "课程名")
        i_credit = _column_index(header, "学分")
        i_category = _column_index(header, "课程性质", "课程类别", "性质")
        i_group = _column_index(header, "课程模块", "模块", "课程属性")
        i_semester = _column_index(header, "开课学期", "建议修读学期", "学期")
        if i_name is None or i_credit is None:
            continue

        last_nature = ""
        last_group = ""
        last_module = ""
        rows = table.find_all("tr")
        header_index = next(
            (i for i, row in enumerate(rows) if _cells(row) == header), -1
        )
        # Rows before the header are the description/credit-summary/matrix
        # sections of the same outer table; they must not be read as courses.
        for row in rows[header_index + 1 :]:
            cells = _cells(row)
            joined = " ".join(cells)
            if "合计" in joined or "小计" in joined:
                numbers = re.findall(r"\d+(?:\.\d+)?", joined)
                if numbers:
                    total_credits = max(total_credits, max(float(n) for n in numbers))
                continue

            code_idx = None
            if (
                i_code is not None
                and len(cells) > i_code
                and code_pattern.fullmatch(cells[i_code].strip())
            ):
                code_idx = i_code
            else:
                code_idx = next(
                    (i for i, cell in enumerate(cells) if code_pattern.fullmatch(cell.strip())),
                    None,
                )

            if code_idx is not None and i_code is not None and code_idx != i_code:
                # Merged row: the leading category cells are missing.
                name_idx = code_idx + 1
                credit_idx = code_idx + 2
            else:
                name_idx = i_name if code_idx is None else i_name
                credit_idx = i_credit if code_idx is None else i_credit
            if name_idx is None or credit_idx is None:
                continue
            if len(cells) <= max(name_idx, credit_idx):
                continue
            name = cells[name_idx].strip()
            if not name or name in header or "课程名称" in name:
                continue
            match = re.search(r"\d+(?:\.\d+)?", cells[credit_idx])
            if not match:
                continue

            code = cells[code_idx].strip() if code_idx is not None else ""
            if code_idx is not None and i_code is not None and code_idx != i_code:
                # Merged row: the leading category/nature/module cells were
                # rendered by an earlier row, so reuse the remembered values.
                leading = cells[:code_idx]
                if leading and any(k in leading[0] for k in ("通识课", "学科基础课", "专业课", "实践")):
                    last_group = leading[0]
                if leading and any(k in leading[0] for k in ("必修", "限选", "选修")):
                    last_nature = leading[0]
                elif len(leading) > 1 and any(
                    k in leading[1] for k in ("必修", "限选", "选修")
                ):
                    last_nature = leading[1]
                if len(leading) > 2:
                    last_module = leading[2]
                elif len(leading) == 2 and not code_pattern.fullmatch(leading[1]):
                    last_module = leading[1]
                category = last_nature
                group = last_module or last_group
            else:
                # Normal row: the header columns describe this row directly.
                category = (
                    cells[i_category].strip()
                    if i_category is not None and len(cells) > i_category
                    else last_nature
                )
                group = (
                    cells[i_group].strip()
                    if i_group is not None and len(cells) > i_group
                    else last_group or last_module
                )
            if category:
                last_nature = category
            if group:
                last_module = group
                last_group = group

            semester = None
            if i_semester is not None and len(cells) > i_semester:
                numbers = re.findall(r"\d+", cells[i_semester])
                if numbers and 1 <= int(numbers[-1]) <= 12:
                    semester = int(numbers[-1])
            if semester is None and code_idx is not None:
                # Real zypyfa_query rows put the semester just before the
                # 辅修/考核 cells, after several hour columns.  Scan backwards
                # so 授课周数 (e.g. 8) is not mistaken for the semester.
                tail = cells[credit_idx + 1 :]
                for cell in reversed(tail):
                    value = cell.strip()
                    if value in ("是", "否", "考试", "考查"):
                        continue
                    if re.fullmatch(r"[1-8](?:\s*[,，]\s*[1-8])*", value):
                        semester = int(re.search(r"\d", value).group())
                        break

            course = Course(
                code=code,
                name=name,
                credits=float(match.group()),
                category=category,
                group=group,
                semester=semester,
            )
            key = (code, name)
            if key not in seen:
                seen[key] = course

    courses = list(seen.values())
    if not courses:
        return None
    if not total_credits:
        total_credits = round(sum(c.credits for c in courses), 2)
    return Program(
        major=major,
        grade=grade,
        college=college,
        total_credits=total_credits,
        required_credits=round(
            sum(c.credits for c in courses if c.is_required), 2
        ),
        courses=courses,
        source=source,  # type: ignore[arg-type]
    )


def _form_payload(soup: BeautifulSoup, major: str, grade: int) -> tuple[str, dict]:
    """Build the form submission for the major/grade query page.

    Selects are resolved to their option *value* (the school system uses codes),
    with the visible label only as a fallback.
    """
    form = soup.find("form")
    action = (form.get("action") if form else None) or PROGRAM_FIND_URL
    if action.startswith("/"):
        action = f"http://jwxt.gdufe.edu.cn{action}"
    elif action and not action.startswith("http"):
        action = f"{BASE}/{action.lstrip('/')}"
    data: dict[str, str] = {}
    scope = form if form else soup
    for element in scope.find_all(["input", "select", "textarea"]):
        name = element.get("name")
        if not name:
            continue
        tag = element.name.lower()
        if tag == "select":
            options = element.find_all("option")
            selected = next((o for o in options if o.has_attr("selected")), None)
            choice = selected or (options[0] if options else None)
            data[name] = (
                choice.get("value", choice.get_text(strip=True)) if choice else ""
            )
        elif tag == "textarea":
            data[name] = element.get_text(strip=True)
        else:
            input_type = (element.get("type") or "text").lower()
            if input_type in ("submit", "button", "reset", "image"):
                continue
            data[name] = element.get("value", "")
    # Overwrite the major/grade selects with the requested values, using each
    # option's value when possible.
    for element in scope.find_all("select"):
        name = element.get("name")
        if not name or name not in data:
            continue
        label = element.get("name", "")
        is_major = "专业" in label or "zy" in label.lower() or "major" in label.lower()
        is_grade = "年级" in label or "nj" in label.lower() or "grade" in label.lower()
        if is_major and major:
            data[name] = _option_value(element, major) or major
        elif is_grade and grade:
            data[name] = _option_value(element, str(grade)) or str(grade)
    return action, data


def _script_form_action(soup: BeautifulSoup, function_name: str, fallback: str) -> str:
    """Read a form action that the page sets inside a JavaScript function."""
    for script in soup.find_all("script"):
        text = script.get_text()
        for match in re.finditer(
            rf"function\s+{re.escape(function_name)}\s*\([^)]*\)\s*\{{(.*?)\}}",
            text,
            re.S,
        ):
            action = re.search(
                r"\.action\s*=\s*['\"]([^'\"]+)['\"]", match.group(1)
            )
            if action:
                value = action.group(1).replace("&amp;", "&")
                if value.startswith("/"):
                    return f"http://jwxt.gdufe.edu.cn{value}"
                return urljoin(PROGRAM_FIND_URL, value)
    return fallback


def fetch_program_form_options(session: requests.Session) -> dict:
    """Expose the major/grade/college selectors on the query page to the frontend."""
    try:
        html = get_text(session, PROGRAM_FIND_URL)
    except requests.RequestException as exc:
        raise JwxtError(f"无法打开培养方案查询页：{exc}") from exc
    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, list[str]] = {}
    for select in soup.find_all("select"):
        name = select.get("name") or select.get("id") or "未命名"
        options = [
            option.get_text(strip=True)
            for option in select.find_all("option")
            if option.get_text(strip=True)
        ]
        if options:
            groups[name] = options[:200]
    return groups


def _option_value(select, label: str) -> Optional[str]:
    """Resolve a human-readable option label to the value the form expects."""
    for option in select.find_all("option"):
        text = option.get_text(strip=True)
        if text == label or (label and (label in text or text in label)):
            return option.get("value", text) or text
    return None


# Fallback college grouping when the query page has no dedicated college
# selector. Keywords map a major name to its likely school; unmatched majors
# go to "其他". This is purely a convenience grouping, not official data.
_COLLEGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "会计学院": ("会计", "审计", "财务", "资产评估"),
    "金融学院": ("金融", "保险", "投资"),
    "法学院": ("法学", "知识产权", "法律"),
    "信息学院": ("计算机", "软件", "网络", "数据科学", "人工智能", "电子商务", "信息安全", "物联网", "数字媒体"),
    "工商管理学院": ("工商管理", "市场营销", "人力资源", "物流管理", "旅游管理", "酒店管理"),
    "经济学院": ("经济学", "国际经济与贸易", "贸易", "财政", "税收"),
    "统计与数学学院": ("统计", "数学", "信息与计算"),
    "外国语学院": ("英语", "日语", "法语", "商务英语", "翻译"),
    "人文与传播学院": ("汉语言", "新闻", "广告", "传播", "编辑出版"),
    "艺术学院": ("设计", "动画", "美术", "音乐", "视觉传达", "环境设计"),
    "公共管理学院": ("行政管理", "公共事业", "劳动与社会保障", "城市管理", "社会工作"),
    "旅游与酒店管理学院": ("旅游", "酒店", "会展"),
}


def infer_colleges(majors: list[str]) -> dict[str, list[str]]:
    """Group major names into likely colleges for quick filtering."""
    groups: dict[str, list[str]] = {}
    for major in majors:
        college = "其他学院"
        for name, keywords in _COLLEGE_KEYWORDS.items():
            if any(k in major for k in keywords):
                college = name
                break
        groups.setdefault(college, []).append(major)
    return groups


def _select_field_names(soup: BeautifulSoup, keyword: str) -> list[str]:
    """Find select field names whose label or name matches a keyword."""
    names: list[str] = []
    for select in soup.find_all("select"):
        candidate = " ".join(
            [select.get("name") or "", select.get("id") or "", select.get("title") or ""]
        )
        label = ""
        parent = select.parent
        if parent:
            label = parent.get_text(" ", strip=True)[:40]
        if keyword in candidate or keyword in label:
            name = select.get("name")
            if name and name not in names:
                names.append(name)
    return names


def fetch_colleges(session: requests.Session) -> list[dict[str, str]]:
    """Read the real 学院 (xsyx) options from the training-program query page."""
    try:
        html = get_text(session, PROGRAM_FIND_URL)
    except requests.RequestException as exc:
        raise JwxtError(f"无法打开培养方案查询页：{exc}") from exc
    soup = BeautifulSoup(html, "html.parser")
    for name in ("xsyx", "xsxy", "xy", "学院", "院系") + tuple(_select_field_names(soup, "学院")):
        select = soup.find("select", attrs={"name": name})
        if not select:
            continue
        options = []
        for option in select.find_all("option"):
            value = option.get("value", "") or option.get_text(strip=True)
            label = option.get_text(strip=True)
            if not label or "请选择" in label:
                continue
            options.append({"value": value, "label": _clean_text(label)})
        if options:
            return options
    return []


def _major_options_from(html: str) -> list[str]:
    """Read populated 专业 (xszy) options from a rendered page."""
    soup = BeautifulSoup(html, "html.parser")
    names = ("xszy", "zy", "专业") + tuple(_select_field_names(soup, "专业"))
    for name in names:
        select = soup.find("select", attrs={"name": name})
        if not select:
            continue
        options = [
            _clean_text(option.get_text(strip=True))
            for option in select.find_all("option")
            if option.get_text(strip=True) and "请选择" not in option.get_text(strip=True)
        ]
        if options:
            return options[:300]
    return []


def _pyfa_diagnostic(soup: BeautifulSoup) -> str:
    """Summarise the cascade wiring so a failed lookup can be fixed precisely."""
    parts: list[str] = []
    for select in soup.find_all("select"):
        name = select.get("name") or ""
        parts.append(f"select[{name}] onchange={select.get('onchange', '')}")
    script_text = " ".join(s.get_text() for s in soup.find_all("script"))
    for line in script_text.splitlines():
        low = line.lower()
        if "xszy" in line or "xsyx" in line or "pyfa" in low or "ajax" in low:
            parts.append(line.strip()[:160])
    return " | ".join(parts)[:900]


def fetch_majors_by_college(
    session: requests.Session, college: str, grade: int = 0
) -> list[str]:
    """Query the majors that appear after selecting a college on pyfa_find.

    The 专业 dropdown is populated only after a 学院 is chosen, either by a
    server-rendered reload or by JavaScript. Try the common paths and, if all
    fail, surface a diagnostic of the page's cascade wiring.
    """
    try:
        html = get_text(session, PROGRAM_FIND_URL)
    except requests.RequestException as exc:
        raise JwxtError(f"无法打开培养方案查询页：{exc}") from exc
    soup = BeautifulSoup(html, "html.parser")

    college_code = college
    for name in ("xsyx", "xsxy", "xy", "学院", "院系") + tuple(_select_field_names(soup, "学院")):
        select = soup.find("select", attrs={"name": name})
        if not select:
            continue
        for option in select.find_all("option"):
            if option.get("value", "") == college or _clean_text(option.get_text(strip=True)) == college:
                college_code = option.get("value", "") or college
                break

    responses: list[str] = []
    # Path 1: GET with query parameters (many 强智 pages render on GET).
    try:
        response = session.get(
            PROGRAM_FIND_URL,
            params={"xsyx": college_code, "xsnj": str(grade) if grade else ""},
            timeout=20,
        )
        responses.append(decode_bytes(response.content))
    except requests.RequestException:
        pass
    # Path 2: POST the query form with the college selected.
    action, data = _form_payload(soup, "", grade)
    for name in ("xsyx", "xsxy", "xy", "学院", "院系") + tuple(_select_field_names(soup, "学院")):
        if soup.find("select", attrs={"name": name}):
            data[name] = college_code
    try:
        response = session.post(action, data=data, timeout=20)
        responses.append(decode_bytes(response.content))
    except requests.RequestException:
        pass

    for rendered in responses:
        majors = _major_options_from(rendered)
        if majors:
            return majors

    raise JwxtError("专业下拉未能自动加载；" + _pyfa_diagnostic(soup))


def fetch_own_program(
    session: requests.Session, major: str, grade: int, college: str = ""
) -> Optional[Program]:
    """Fetch the logged-in student's own 培养方案 from the display-only page."""
    for url in (OWN_PROGRAM_URL, OWN_PROGRAM_ALT_URL):
        try:
            rendered = get_text(session, url)
        except requests.RequestException:
            continue
        program = parse_program_table(rendered, major, grade, source="live", college=college)
        if program:
            # The 执行计划 page labels courses by module (学科基础课/专业课/...)
            # rather than 必修/选修.  For overlap detection, everything that is
            # not explicitly an elective counts as a required course.
            for course in program.courses:
                label = f"{course.category} {course.group}"
                if "选修" in label:
                    course.category = "选修"
                else:
                    course.category = "必修"
            return program
    return None


DEBUG_DIR = Path(__file__).resolve().parent.parent / "data" / "debug"


def _dump_html(label: str, html: str) -> str:
    """Persist a page snapshot so a failed lookup can be diagnosed offline."""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", label)[:80]
        path = DEBUG_DIR / f"{safe}.html"
        path.write_text(html or "", encoding="utf-8")
        return str(path)
    except OSError:
        return ""


def _resolve_major_code(
    session: requests.Session,
    soup: BeautifulSoup,
    major: str,
    grade: int,
    college_field: str,
    college_code: str,
    given: str = "",
) -> str:
    """Find the option value for a major name under the chosen college."""
    if given:
        return given
    if not (college_field and college_code):
        return ""
    for params in (
        {college_field: college_code, "xsnj": str(grade)},
        {college_field: college_code},
    ):
        try:
            result = session.get(PROGRAM_FIND_URL, params=params, timeout=20)
            rendered = decode_bytes(result.content)
            option_soup = BeautifulSoup(rendered, "html.parser")
            for sel_name in ("xszy", "zy", "专业") + tuple(
                _select_field_names(option_soup, "专业")
            ):
                sel = option_soup.find("select", attrs={"name": sel_name})
                if not sel:
                    continue
                for option in sel.find_all("option"):
                    text = _clean_text(option.get_text(strip=True))
                    value = option.get("value", "") or text
                    if text == major or (major and (major in text or text in major)):
                        return value
        except requests.RequestException:
            continue
    return ""


def _candidate_detail_urls(session: requests.Session, rendered: str, base_url: str) -> list[str]:
    """Extract links/JS URLs that may open the actual 培养方案 detail page."""
    soup = BeautifulSoup(rendered, "html.parser")
    candidates: list[str] = []
    for anchor in soup.find_all("a"):
        href = anchor.get("href", "")
        onclick = " ".join(f"{k}={v}" for k, v in anchor.attrs.items() if k.startswith("on"))
        blob = f"{href} {onclick}"
        if not blob.strip() or blob.strip().startswith("#"):
            continue
        urls = re.findall(r"['\"]?([^'\"\s()]+(?:\.do|\.jsp|/[a-zA-Z0-9_]+)[^'\"\s()]*)['\"]?", blob)
        for url in urls:
            if "javascript:" in url and "(" not in url:
                continue
            full = urljoin(base_url, url.replace("&amp;", "&"))
            if urlparse(full).netloc == urlparse(base_url).netloc:
                candidates.append(full)
    # Result pages frequently embed the real program in an iframe.
    for frame in soup.find_all("iframe"):
        src = frame.get("src", "")
        if src and src.lower() not in ("about:blank", "javascript:void(0)"):
            candidates.append(urljoin(base_url, src.replace("&amp;", "&")))
    # Inline scripts sometimes build the URL via openWindow(...)/window.open().
    for script in soup.find_all("script"):
        text = script.get_text()
        for url in re.findall(r"['\"]([^'\"]*(?:pyfa|PyFa|topyfa)[^'\"]*)['\"]", text, re.I):
            candidates.append(urljoin(base_url, url.replace("&amp;", "&")))
        for match in re.findall(r"(?:openWindow|window\.open|location\.href\s*=)\s*\(\s*['\"]([^'\"]+)", text):
            candidates.append(urljoin(base_url, match.replace("&amp;", "&")))
    # Keep order, drop duplicates.
    seen: set[str] = set()
    result: list[str] = []
    for url in candidates:
        # The result page also links to unrelated modules (teacher info,
        # evaluation, ...).  Only培养方案 pages can contain the course table.
        if "pyfa" not in urlparse(url).path.lower() or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result[:40]


def fetch_program(
    session: requests.Session,
    major: str,
    grade: int,
    college_code: str = "",
    major_code: str = "",
) -> Optional[Program]:
    """Fetch another major's program from /jspyfa/pyfa_find.

    The school first returns a result page; the course table lives on a detail
    page linked from it. We try several query paths, follow detail links, and
    save every HTML snapshot under data/debug for diagnosis.
    """
    try:
        html = get_text(session, PROGRAM_FIND_URL)
    except requests.RequestException as exc:
        raise JwxtError(f"无法打开培养方案查询页：{exc}") from exc
    soup = BeautifulSoup(html, "html.parser")
    _dump_html(f"00_form_{major}", html)

    college_field = ""
    for name in ("xsyx", "xsxy", "xy", "学院", "院系") + tuple(
        _select_field_names(soup, "学院")
    ):
        if soup.find("select", attrs={"name": name}):
            college_field = name
            break

    resolved_major_code = _resolve_major_code(
        session, soup, major, grade, college_field, college_code, major_code
    )

    _, data = _form_payload(soup, "", grade)
    if college_field:
        data[college_field] = college_code
    for name in ("xszy", "zy", "专业") + tuple(_select_field_names(soup, "专业")):
        if soup.find("select", attrs={"name": name}):
            data[name] = resolved_major_code or major

    # The page's queryKsap() overrides the empty form action with zypyfa_query.
    query_action = _script_form_action(soup, "queryKsap", PROGRAM_QUERY_URL)
    attempts: list[tuple[str, str, str]] = []
    try:
        response = session.post(
            query_action,
            data=data,
            headers={"Referer": PROGRAM_FIND_URL},
            timeout=20,
        )
        attempts.append(("01_query_post", decode_bytes(response.content), response.url))
    except requests.RequestException as exc:
        _dump_html(f"error_query_post_{major}", f"{exc}")
    try:
        response = session.get(
            query_action,
            params=dict(data),
            headers={"Referer": PROGRAM_FIND_URL},
            timeout=20,
        )
        attempts.append(("02_query_get", decode_bytes(response.content), response.url))
    except requests.RequestException as exc:
        _dump_html(f"error_query_get_{major}", f"{exc}")

    for label, rendered, page_url in attempts:
        _dump_html(f"{label}_{major}", rendered)
        program = parse_program_table(rendered, major, grade, source="live", college=college_code)
        if program:
            return program

        # Follow detail links from the result page.
        for index, detail_url in enumerate(_candidate_detail_urls(session, rendered, page_url)):
            try:
                detail_response = session.get(detail_url, timeout=20)
                detail_html = decode_bytes(detail_response.content)
            except requests.RequestException:
                continue
            _dump_html(f"{label}_detail{index}_{major}", detail_html)
            program = parse_program_table(
                detail_html, major, grade, source="live", college=college_code
            )
            if program:
                return program

    # Last resort: the student's own display-only page can sometimes be coaxed
    # with query params for a different major.
    for url in (
        f"{OWN_PROGRAM_URL}?xszy={resolved_major_code or major}&xsnj={grade}",
        f"{OWN_PROGRAM_URL}?zy={resolved_major_code or major}&nj={grade}",
    ):
        try:
            rendered = get_text(session, url)
        except requests.RequestException:
            continue
        _dump_html(f"03_ownparam_{major}", rendered)
        program = parse_program_table(rendered, major, grade, source="live", college=college_code)
        if program:
            return program

    probe = BeautifulSoup(attempts[0][1] if attempts else "", "html.parser")
    selects = [s.get("name") for s in probe.find_all("select")]
    raise JwxtError(
        f"未能解析「{major}」培养方案（提交 {college_field}={college_code}, "
        f"专业={resolved_major_code or major}；返回页下拉={selects[:6]}、"
        f"已保存页面快照到 data/debug 供诊断）"
    )
