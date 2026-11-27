"""Generate clearly-labelled sample programs for the demo mode.

The data is illustrative only — it is NOT the official GDUFE training program.
Contributors can replace it with real, sourced data via the import feature.
"""

import json
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "demo_programs.json"
# Cover every undergraduate cohort still likely to be on campus, including
# the incoming class of the current year.
CURRENT_YEAR = date.today().year
GRADES = tuple(range(CURRENT_YEAR - 5, CURRENT_YEAR + 1))

COMMON = [
    ("思想道德与法治", 3, "通识教育", "必修", 1),
    ("马克思主义基本原理", 3, "通识教育", "必修", 2),
    ("毛泽东思想和中国特色社会主义理论体系概论", 3, "通识教育", "必修", 3),
    ("中国近现代史纲要", 2, "通识教育", "必修", 1),
    ("形势与政策", 2, "通识教育", "必修", 4),
    ("大学英语（一）", 3, "通识教育", "必修", 1),
    ("大学英语（二）", 3, "通识教育", "必修", 2),
    ("大学体育（一）", 1, "通识教育", "必修", 1),
    ("大学体育（二）", 1, "通识教育", "必修", 2),
    ("大学语文", 2, "通识教育", "必修", 1),
    ("军事理论", 2, "通识教育", "必修", 1),
    ("心理健康教育", 1, "通识教育", "必修", 1),
]

STEM_COMMON = [
    ("高等数学（一）", 4, "学科基础", "必修", 1),
    ("高等数学（二）", 4, "学科基础", "必修", 2),
    ("线性代数", 2, "学科基础", "必修", 2),
    ("概率论与数理统计", 3, "学科基础", "必修", 3),
    ("计算机基础", 3, "学科基础", "必修", 1),
]

ECON_COMMON = [
    ("高等数学（一）", 4, "学科基础", "必修", 1),
    ("高等数学（二）", 4, "学科基础", "必修", 2),
    ("线性代数", 2, "学科基础", "必修", 2),
    ("概率论与数理统计", 3, "学科基础", "必修", 3),
    ("计算机基础", 3, "学科基础", "必修", 1),
]

MAJORS = {
    "会计学": {
        "college": "会计学院",
        "base": ECON_COMMON,
        "courses": [
            ("经济学原理", 3, "学科基础", "必修", 1),
            ("管理学", 3, "学科基础", "必修", 1),
            ("基础会计学", 3, "专业核心", "必修", 2),
            ("中级财务会计", 4, "专业核心", "必修", 3),
            ("高级财务会计", 3, "专业核心", "必修", 4),
            ("成本会计", 3, "专业核心", "必修", 3),
            ("管理会计", 3, "专业核心", "必修", 4),
            ("审计学", 3, "专业核心", "必修", 4),
            ("财务管理", 3, "专业核心", "必修", 3),
            ("税法", 3, "专业核心", "必修", 4),
            ("会计信息系统", 2, "专业核心", "限选", 5),
            ("统计学", 3, "学科基础", "必修", 3),
            ("毕业论文", 6, "实践环节", "必修", 8),
        ],
        "electives": [("会计专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
    "金融学": {
        "college": "金融学院",
        "base": ECON_COMMON,
        "courses": [
            ("经济学原理", 3, "学科基础", "必修", 1),
            ("金融学", 4, "专业核心", "必修", 2),
            ("国际金融", 3, "专业核心", "必修", 3),
            ("商业银行经营管理", 3, "专业核心", "必修", 3),
            ("证券投资学", 3, "专业核心", "必修", 4),
            ("保险学", 2, "专业核心", "必修", 4),
            ("公司金融", 3, "专业核心", "必修", 4),
            ("金融风险管理", 2, "专业核心", "限选", 5),
            ("计量经济学", 3, "专业核心", "必修", 5),
            ("会计学", 3, "学科基础", "必修", 2),
            ("统计学", 3, "学科基础", "必修", 3),
            ("财务管理", 3, "专业核心", "限选", 4),
            ("毕业论文", 6, "实践环节", "必修", 8),
        ],
        "electives": [("金融专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
    "法学": {
        "college": "法学院",
        "base": [],
        "courses": [
            ("法理学", 4, "专业核心", "必修", 1),
            ("宪法学", 3, "专业核心", "必修", 1),
            ("民法学", 4, "专业核心", "必修", 2),
            ("刑法学", 4, "专业核心", "必修", 2),
            ("行政法学", 3, "专业核心", "必修", 3),
            ("商法学", 3, "专业核心", "必修", 3),
            ("经济法学", 3, "专业核心", "必修", 3),
            ("诉讼法学", 3, "专业核心", "必修", 4),
            ("国际法学", 2, "专业核心", "限选", 5),
            ("法律文书写作", 2, "专业核心", "必修", 4),
            ("毕业论文", 6, "实践环节", "必修", 8),
        ],
        "electives": [("法学专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
    "计算机科学与技术": {
        "college": "信息学院",
        "base": STEM_COMMON,
        "courses": [
            ("离散数学", 3, "学科基础", "必修", 2),
            ("程序设计基础", 4, "专业核心", "必修", 1),
            ("数据结构", 4, "专业核心", "必修", 2),
            ("计算机组成原理", 4, "专业核心", "必修", 3),
            ("操作系统", 4, "专业核心", "必修", 3),
            ("计算机网络", 4, "专业核心", "必修", 4),
            ("数据库原理", 3, "专业核心", "必修", 3),
            ("软件工程", 3, "专业核心", "必修", 5),
            ("算法设计与分析", 3, "专业核心", "限选", 5),
            ("Java程序设计", 3, "专业核心", "限选", 4),
            ("Web开发技术", 3, "专业核心", "限选", 6),
            ("毕业设计", 6, "实践环节", "必修", 8),
        ],
        "electives": [("计算机专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
    "电子商务": {
        "college": "信息学院",
        "base": ECON_COMMON,
        "courses": [
            ("经济学原理", 3, "学科基础", "必修", 1),
            ("管理学", 3, "学科基础", "必修", 1),
            ("电子商务概论", 3, "专业核心", "必修", 2),
            ("网络营销", 3, "专业核心", "必修", 3),
            ("供应链管理", 3, "专业核心", "必修", 4),
            ("数据库原理", 3, "专业核心", "必修", 3),
            ("程序设计基础", 3, "专业核心", "必修", 2),
            ("物流管理", 2, "专业核心", "限选", 4),
            ("电子支付与结算", 2, "专业核心", "限选", 5),
            ("数据分析", 3, "专业核心", "必修", 5),
            ("毕业设计", 6, "实践环节", "必修", 8),
        ],
        "electives": [("电商专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
    "工商管理": {
        "college": "工商管理学院",
        "base": ECON_COMMON,
        "courses": [
            ("管理学", 3, "学科基础", "必修", 1),
            ("经济学原理", 3, "学科基础", "必修", 1),
            ("市场营销", 3, "专业核心", "必修", 2),
            ("人力资源管理", 3, "专业核心", "必修", 3),
            ("生产运营管理", 3, "专业核心", "必修", 4),
            ("财务管理", 3, "专业核心", "必修", 3),
            ("组织行为学", 2, "专业核心", "限选", 3),
            ("战略管理", 2, "专业核心", "必修", 5),
            ("统计学", 3, "学科基础", "必修", 3),
            ("会计学", 3, "学科基础", "必修", 2),
            ("毕业论文", 6, "实践环节", "必修", 8),
        ],
        "electives": [("管理专业选修课", 6, "专业选修", "选修", 6), ("通识选修课", 4, "通识教育", "选修", 5)],
    },
}


def make_course(name, credits, group, category, semester, index, major_code):
    return {
        "code": f"DEMO{major_code}{index:04d}",
        "name": name,
        "credits": credits,
        "category": category,
        "group": group,
        "semester": semester,
        "passed": True,
    }


def build():
    programs = []
    for grade in GRADES:
        for major_index, (major, config) in enumerate(MAJORS.items(), start=1):
            major_code = f"{major_index:02d}"
            rows = list(COMMON) + list(config["base"]) + list(config["courses"]) + list(config["electives"])
            if grade >= 2024 and major == "计算机科学与技术":
                rows.append(("人工智能导论", 2, "专业选修", "限选", 6))
            if grade < 2024 and major == "金融学":
                rows = [r for r in rows if r[0] != "金融风险管理"]
            courses = [make_course(*row, i + 1, major_code) for i, row in enumerate(rows)]
            total = round(sum(c["credits"] for c in courses), 2)
            required = round(sum(c["credits"] for c in courses if "必修" in c["category"] or "限选" in c["category"]), 2)
            programs.append(
                {
                    "major": major,
                    "grade": grade,
                    "college": config["college"],
                    "total_credits": total,
                    "required_credits": required,
                    "courses": courses,
                    "source": "demo",
                    "updated_at": date.today().isoformat(),
                }
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(programs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(programs)} demo programs to {OUT}")


if __name__ == "__main__":
    build()
