# -*- coding: utf-8 -*-
"""Bounded, structured independent code-review helpers for AgentCoder."""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Mapping, Iterable

MAX_FINDINGS = 10
MAX_FIELD = 600


def build_diff(before: Mapping[str, str], after: Mapping[str, str], changed: Iterable[str], max_chars: int = 24000) -> str:
    """Create a bounded unified diff for changed files without executing project code."""
    chunks: list[str] = []
    used = 0
    for path in sorted({str(p) for p in changed if p}):
        old = str(before.get(path, "")).splitlines()
        new = str(after.get(path, "")).splitlines()
        diff = "\n".join(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm=""))
        if not diff:
            continue
        chunk = diff + "\n"
        if used + len(chunk) > max_chars:
            remain = max_chars - used
            if remain > 120:
                chunks.append(chunk[:remain] + "\n...[diff truncated]")
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n".join(chunks) or "No textual diff available; inspect changed file contents supplied by the caller."


def parse_review(raw: str) -> dict[str, Any]:
    """Parse reviewer JSON. Invalid output is explicitly unavailable, never a pass."""
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    try:
        obj = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
    except (ValueError, TypeError):
        obj = None
    if not isinstance(obj, dict):
        return {"status": "unavailable", "summary": "Reviewer returned invalid structured output.", "findings": [], "blocking": []}
    raw_findings = obj.get("findings", [])
    findings = []
    if isinstance(raw_findings, list):
        for item in raw_findings[:MAX_FINDINGS]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity", "medium")).lower().strip()
            if severity not in {"critical", "high", "medium", "low", "info"}:
                severity = "medium"
            finding = {
                "severity": severity,
                "file": _clean(item.get("file", ""), 180),
                "line": _clean(item.get("line", ""), 30),
                "issue": _clean(item.get("issue", ""), MAX_FIELD),
                "recommendation": _clean(item.get("recommendation", ""), MAX_FIELD),
            }
            if finding["issue"]:
                findings.append(finding)
    blocking = [f for f in findings if f["severity"] in {"critical", "high"}]
    summary = _clean(obj.get("summary", ""), MAX_FIELD) or ("No blocking findings reported." if not blocking else "Blocking findings require correction.")
    status = "revise" if blocking else "pass"
    return {"status": status, "summary": summary, "findings": findings, "blocking": blocking}


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def render_findings(review: Mapping[str, Any]) -> str:
    status = str(review.get("status", "unavailable"))
    lines = [f"Independent review status: {status}", str(review.get("summary", ""))[:MAX_FIELD]]
    for item in review.get("findings", [])[:MAX_FINDINGS]:
        where = str(item.get("file", "unknown file"))
        if item.get("line"):
            where += ":" + str(item["line"])
        lines.append(f"- [{item.get('severity', 'medium').upper()}] {where}: {item.get('issue', '')}")
        if item.get("recommendation"):
            lines.append("  Recommendation: " + str(item["recommendation"]))
    return "\n".join(x for x in lines if x)


PROGRESS_RE = re.compile(r'<task_progress\s+id="(\d+)"\s+status="(in_progress|completed|blocked)"(?:\s+note="([^"]*)")?\s*/>')


def parse_progress_updates(text: str) -> list[dict[str, Any]]:
    """Parse bounded model-reported subtask progress markers; notes are untrusted text."""
    out = []
    seen = set()
    for match in PROGRESS_RE.finditer(str(text or "")):
        task_id = int(match.group(1))
        if task_id in seen or task_id < 1 or task_id > 8:
            continue
        seen.add(task_id)
        out.append({"id": task_id, "status": match.group(2), "note": _clean(match.group(3) or "", 240)})
    return out


def apply_progress(plan_tasks: Any, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply model-reported progress while retaining plan tasks and bounded history."""
    tasks = [dict(t) for t in plan_tasks] if isinstance(plan_tasks, list) else []
    by_id = {int(t.get("id", i + 1)): t for i, t in enumerate(tasks) if isinstance(t, dict)}
    for update in updates:
        task = by_id.get(int(update.get("id", 0)))
        if not task:
            continue
        task["status"] = {"in_progress": "in_progress", "completed": "reported_complete", "blocked": "blocked"}.get(update.get("status"), "pending")
        if update.get("note"):
            task["progress_note"] = str(update["note"])[:240]
    return tasks
