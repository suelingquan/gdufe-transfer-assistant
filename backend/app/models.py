"""Core data models shared by the API, the scraper and the comparison engine."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Course(BaseModel):
    """A single course, either required by a program or completed by a student."""

    code: str = ""
    name: str
    credits: float = 0.0
    category: str = ""          # 课程性质: 必修 / 限选 / 选修
    group: str = ""             # 课程模块: 通识教育 / 学科基础 / 专业核心 / 实践环节
    semester: Optional[int] = None
    score: Optional[str] = None
    passed: bool = True

    @property
    def is_required(self) -> bool:
        return "必修" in self.category or "限选" in self.category


class Program(BaseModel):
    """A training program (培养方案) for one major and one entering grade."""

    major: str
    grade: int
    college: str = ""
    total_credits: float = 0.0
    required_credits: float = 0.0
    courses: list[Course] = Field(default_factory=list)
    source: Literal["demo", "live", "import"] = "demo"
    updated_at: str = ""

    def summary(self) -> dict:
        return {
            "major": self.major,
            "grade": self.grade,
            "college": self.college,
            "total_credits": self.total_credits,
            "required_credits": self.required_credits,
            "course_count": len(self.courses),
            "source": self.source,
            "updated_at": self.updated_at,
        }


class StudentProfile(BaseModel):
    """The student's identity and completed courses."""

    student_id: str
    name: str = ""
    major: str
    grade: int
    college: str = ""
    gpa: float = 0.0
    completed: list[Course] = Field(default_factory=list)


class SubstitutionRule(BaseModel):
    """A rule that lets one completed course stand in for a required one."""

    id: str
    from_code: str = ""
    from_name: str = ""
    to_code: str = ""
    to_name: str = ""
    reason: str = ""
    max_credits: Optional[float] = None


class MatchInfo(BaseModel):
    """One target requirement that has been satisfied by a completed course."""

    target: Course
    completed: Course
    via: Literal["code", "name", "rule", "fuzzy"]
    rule: Optional[SubstitutionRule] = None


class ComparisonResult(BaseModel):
    """Full comparison between a student and one target program."""

    major: str
    grade: int
    total_credits: float
    required_credits: float
    earned_credits: float
    overlap_count: int
    satisfied_count: int
    missing_count: int
    missing_credits: float
    credit_gap: float
    transferable_credits: float
    overlap_courses: list[Course] = Field(default_factory=list)
    missing_courses: list[Course] = Field(default_factory=list)
    satisfied: list[MatchInfo] = Field(default_factory=list)
    substitutions: list[MatchInfo] = Field(default_factory=list)


class GpaEstimateRequest(BaseModel):
    gpa: float
    target_majors: list[str] = Field(default_factory=list)


class CompareRequest(BaseModel):
    profile: StudentProfile
    current_major: str
    target_majors: list[str]
    grade: int
    source: Literal["demo", "live", "import"] = "demo"
    token: Optional[str] = None
    # Map of major name -> school's college code, gathered from the cascade.
    major_colleges: dict[str, str] = Field(default_factory=dict)
    imported_programs: list[Program] = Field(default_factory=list)
    rules: list[SubstitutionRule] = Field(default_factory=list)
