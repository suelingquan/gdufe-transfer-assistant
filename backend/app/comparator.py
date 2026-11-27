"""Transfer-major comparison engine.

All decisions are transparent: every satisfied requirement records *how* it was
matched (exact course code, exact name, a community rule, or a fuzzy hint that
must be confirmed by the student).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .models import (
    ComparisonResult,
    Course,
    MatchInfo,
    Program,
    StudentProfile,
    SubstitutionRule,
)

_PUNCT = re.compile(r"[\s\u3000\(\)（）\[\]【】·、，,。.:：;；\-—_/\\'\"“”]+")
_SUFFIX = re.compile(r"(（[^）]*）|\([^)]*\))$")


def norm(text: str) -> str:
    """Normalise Chinese course names/codes for comparison."""
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).strip().lower()
    return _PUNCT.sub("", value)


def fuzzy_name(name: str) -> str:
    """Name with a trailing parenthetical note removed, e.g. 高等数学（上）."""
    return norm(_SUFFIX.sub("", str(name or "").strip()))


def _rule_side_matches(
    side_code: str, side_name: str, course: Course
) -> bool:
    rc, rn = norm(side_code), norm(side_name)
    if rc and rc == norm(course.code):
        return True
    if rn and rn == norm(course.name):
        return True
    if rn and len(rn) >= 4 and (rn in norm(course.name) or norm(course.name) in rn):
        return True
    return False


def _find_match(
    target: Course,
    completed: list[Course],
    used: set[int],
    rules: Iterable[SubstitutionRule],
) -> MatchInfo | None:
    """Return the first acceptable match for a target requirement."""
    # 1. Exact course code — the strongest signal.
    if norm(target.code):
        for idx, course in enumerate(completed):
            if idx not in used and norm(course.code) == norm(target.code):
                used.add(idx)
                return MatchInfo(target=target, completed=course, via="code")

    # 2. Exact course name (program and transcript codes often differ).
    for idx, course in enumerate(completed):
        if idx not in used and norm(course.name) == norm(target.name):
            used.add(idx)
            return MatchInfo(target=target, completed=course, via="name")

    # 3. Community-maintained substitution rules.
    for rule in rules:
        if not _rule_side_matches(rule.to_code, rule.to_name, target):
            continue
        for idx, course in enumerate(completed):
            if idx not in used and _rule_side_matches(rule.from_code, rule.from_name, course):
                if rule.max_credits is None or course.credits <= rule.max_credits:
                    used.add(idx)
                    return MatchInfo(
                        target=target, completed=course, via="rule", rule=rule
                    )

    # 4. Fuzzy hint — shown to the user, never silently trusted.
    tn = fuzzy_name(target.name)
    for idx, course in enumerate(completed):
        if idx in used or not tn:
            continue
        cn = fuzzy_name(course.name)
        if not cn:
            continue
        contained = tn in cn or cn in tn
        similar = (
            len(tn) >= 4
            and len(cn) >= 4
            and abs(len(tn) - len(cn)) <= 3
            and len(set(tn) & set(cn)) / max(len(set(tn) | set(cn)), 1) >= 0.65
        )
        if (contained or similar) and abs(target.credits - course.credits) <= 1.5:
            used.add(idx)
            rule = SubstitutionRule(
                id="fuzzy-hint",
                from_name=course.name,
                to_name=target.name,
                reason="名称近似，请人工确认是否等同/可替代",
            )
            return MatchInfo(target=target, completed=course, via="fuzzy", rule=rule)

    return None


def compare(
    profile: StudentProfile,
    current: Program,
    target: Program,
    rules: Iterable[SubstitutionRule] = (),
) -> ComparisonResult:
    """Compare one student against one target program."""
    completed = [c for c in profile.completed if c.passed]
    rules = list(rules)

    current_required = [c for c in current.courses if c.is_required]
    target_required = [c for c in target.courses if c.is_required]

    current_keys = {(norm(c.code), norm(c.name)) for c in current_required}
    overlap = [
        c
        for c in target_required
        if (norm(c.code), norm(c.name)) in current_keys
        or any(norm(c.code) and norm(c.code) == norm(k[0]) for k in current_keys)
        or any(norm(c.name) and norm(c.name) == norm(k[1]) for k in current_keys)
    ]

    used: set[int] = set()
    satisfied: list[MatchInfo] = []
    missing: list[Course] = []
    for requirement in target_required:
        match = _find_match(requirement, completed, used, rules)
        if match:
            satisfied.append(match)
        else:
            missing.append(requirement)

    # Credits that count toward the target: matched required courses use the
    # target's credit value; unmatched completed electives carry their own.
    matched_credits = sum(m.target.credits for m in satisfied)
    matched_indices = {
        id(m.completed) for m in satisfied
    }
    elective_credits = sum(
        c.credits
        for c in completed
        if id(c) not in matched_indices and ("选修" in c.category or not c.category)
    )
    transferable = min(target.total_credits or 0.0, matched_credits + elective_credits)
    earned = sum(c.credits for c in completed)
    credit_gap = max(0.0, round((target.total_credits or 0.0) - transferable, 2))

    return ComparisonResult(
        major=target.major,
        grade=target.grade,
        total_credits=target.total_credits,
        required_credits=target.required_credits,
        earned_credits=round(earned, 2),
        overlap_count=len(overlap),
        satisfied_count=len(satisfied),
        missing_count=len(missing),
        missing_credits=round(sum(c.credits for c in missing), 2),
        credit_gap=credit_gap,
        transferable_credits=round(transferable, 2),
        overlap_courses=overlap,
        missing_courses=missing,
        satisfied=satisfied,
        substitutions=[m for m in satisfied if m.via in ("rule", "fuzzy")],
    )


def rank_programs(
    profile: StudentProfile,
    current: Program,
    programs: list[Program],
    rules: Iterable[SubstitutionRule] = (),
) -> list[ComparisonResult]:
    """Rank target majors by how many extra courses the student must take."""
    results = [
        compare(profile, current, program, rules)
        for program in programs
        if program.major != current.major
    ]
    results.sort(
        key=lambda r: (r.missing_count, r.missing_credits, r.credit_gap, r.major)
    )
    return results
