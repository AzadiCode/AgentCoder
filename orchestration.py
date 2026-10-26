# -*- coding: utf-8 -*-
"""Small, deterministic task-plan utilities for AgentCoder.

The LLM proposes a plan, but this module validates and bounds the structure so
malformed model output can never create unbounded work or executable commands.
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_TASKS = 8
MAX_TITLE = 180
MAX_CRITERIA = 8


def parse_plan(raw: str, goal: str) -> dict[str, Any]:
    """Parse a model-proposed JSON plan, with a safe fallback on malformed output."""
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    obj = None
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            obj = None

    if not isinstance(obj, dict):
        return fallback_plan(goal, "Planner response was not valid JSON; use a conservative plan.")

    raw_tasks = obj.get("tasks")
    tasks = []
    if isinstance(raw_tasks, list):
        for item in raw_tasks[:MAX_TASKS]:
            if isinstance(item, str):
                title, detail = item, ""
            elif isinstance(item, dict):
                title = item.get("title", "")
                detail = item.get("detail", "")
            else:
                continue
            title = _clean(title, MAX_TITLE)
            detail = _clean(detail, 500)
            if title:
                tasks.append({"id": len(tasks) + 1, "title": title, "detail": detail, "status": "pending"})

    criteria_raw = obj.get("acceptance_criteria", [])
    criteria = []
    if isinstance(criteria_raw, list):
        for value in criteria_raw[:MAX_CRITERIA]:
            value = _clean(value, 300)
            if value:
                criteria.append(value)

    risks_raw = obj.get("risks", [])
    risks = [_clean(x, 240) for x in risks_raw[:5] if _clean(x, 240)] if isinstance(risks_raw, list) else []
    if not tasks:
        return fallback_plan(goal, "Planner returned no usable tasks.")
    return {
        "version": 1,
        "objective": _clean(obj.get("objective") or goal, 600),
        "tasks": tasks,
        "acceptance_criteria": criteria,
        "risks": risks,
        "source": "model",
    }


def fallback_plan(goal: str, reason: str = "") -> dict[str, Any]:
    tasks = [
        {"id": 1, "title": "Inspect relevant files and existing behavior", "detail": "Read the project structure and identify constraints before editing.", "status": "pending"},
        {"id": 2, "title": "Implement the smallest coherent solution", "detail": "Preserve existing contracts and avoid unrelated changes.", "status": "pending"},
        {"id": 3, "title": "Run checks and fix verified failures", "detail": "Use available tests and static checks; report any unavailable checks honestly.", "status": "pending"},
    ]
    return {"version": 1, "objective": _clean(goal, 600), "tasks": tasks,
            "acceptance_criteria": ["Requested behavior is implemented", "Relevant checks are run and results reported"],
            "risks": [reason] if reason else [], "source": "fallback"}


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def render_plan(plan: dict[str, Any]) -> str:
    """Render bounded plan as instruction text, not as executable/tool syntax."""
    lines = ["TASK PLAN (validated; follow this order and update your own progress):", f"Objective: {plan['objective']}"]
    for task in plan["tasks"]:
        suffix = f" — {task['detail']}" if task.get("detail") else ""
        lines.append(f"{task['id']}. {task['title']}{suffix}")
    if plan.get("acceptance_criteria"):
        lines.append("Acceptance criteria:")
        lines.extend(f"- {item}" for item in plan["acceptance_criteria"])
    if plan.get("risks"):
        lines.append("Risks to watch:")
        lines.extend(f"- {item}" for item in plan["risks"])
    lines.append("Do not claim completion until the acceptance criteria and available verification checks have been addressed.")
    return "\n".join(lines)
