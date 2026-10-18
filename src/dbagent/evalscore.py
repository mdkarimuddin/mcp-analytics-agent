"""Scoring helpers for execution-based evaluation: the expected answer comes from running SQL."""

from __future__ import annotations

import re

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    """Extract numbers, tolerating thousands separators like '1,234', '1 234' or '1 234'."""
    cleaned = re.sub(r"(?<=\d)[,   ](?=\d{3}\b)", "", text)
    return [float(m) for m in _NUM.findall(cleaned)]


def has_number(text: str, expected: float, rel_tol: float = 0.0, abs_tol: float = 0.0) -> bool:
    """True if any number in `text` is within tolerance of `expected`."""
    for n in numbers_in(text):
        if abs(n - expected) <= max(abs_tol, rel_tol * abs(expected)):
            return True
    return False


def score_case(case: dict, answer: str, tool_names: list[str], truth: object, stopped: bool) -> list[str]:
    """Return failure messages (empty list means pass)."""
    fails: list[str] = []
    low = answer.lower()
    used = set(tool_names)
    if case.get("expect_tools_any") and not used & set(case["expect_tools_any"]):
        fails.append(f"none of {case['expect_tools_any']} used")
    for t in case.get("forbid_tools", []):
        if t in used:
            fails.append(f"forbidden tool {t} used")
    if "truth_number" in case:
        tol = case.get("rel_tol", 0.0)
        if not has_number(answer, float(truth), rel_tol=tol, abs_tol=case.get("abs_tol", 0.0)):
            fails.append(f"expected number {truth} not found in answer")
    if "truth_text" in case and str(truth).lower() not in low:
        fails.append(f"expected '{truth}' not found in answer")
    if case.get("answer_contains_any") and not any(s.lower() in low for s in case["answer_contains_any"]):
        fails.append(f"answer has none of {case['answer_contains_any']}")
    for s in case.get("answer_not_contains", []):
        if s.lower() in low:
            fails.append(f"answer contains '{s}'")
    if stopped:
        fails.append("hit step/token limit")
    return fails
