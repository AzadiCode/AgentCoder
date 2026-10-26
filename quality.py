# -*- coding: utf-8 -*-
"""Project-aware, conservative verification helpers for CodeWise.

This module intentionally does not install dependencies or execute package lifecycle
scripts. It selects repeatable checks from the files that already exist in a project.
"""
from __future__ import annotations

import shlex
from typing import Iterable, Mapping


def verification_plan(files: Iterable[Mapping[str, object]]) -> list[tuple[str, str]]:
    """Return safe, deterministic (label, command) checks for a project snapshot."""
    paths = sorted({str(f.get("path", "")) for f in files if f.get("path")})
    lower = [p.lower() for p in paths]
    plan: list[tuple[str, str]] = []

    py_files = [p for p in paths if p.lower().endswith(".py")]
    if py_files:
        # compileall checks syntax without importing project code or installing deps.
        plan.append(("Python syntax", "python -m compileall -q ."))

    js_files = [p for p in paths if p.lower().endswith((".js", ".mjs", ".cjs"))]
    for path in js_files[:40]:
        plan.append((f"JavaScript syntax: {path}", "node --check " + shlex.quote(path)))

    # Run tests only when the repository clearly contains a test suite.
    has_py_tests = any(
        p.startswith(("test_", "tests/", "test/"))
        or "/tests/" in p
        or "/test_" in p
        for p in lower
    )
    if has_py_tests and py_files:
        plan.append(("Python tests", "pytest"))

    # Avoid running npm/pnpm/yarn scripts: package lifecycle hooks can run arbitrary code.
    # The JSON is inspected only to tell the user that a JS test command may exist.
    if "package.json" in lower and not js_files:
        plan.append(("JavaScript checks", ""))

    return plan


def run_quality_gate(files: Iterable[Mapping[str, object]], run_command, health_check, pid: str,
                     changed: Iterable[str] = ()) -> dict:
    """Run selected checks and return a compact structured report.

    run_command(pid, command) and health_check(pid, paths, ...) are injected by app.py
    to keep this module independent from Flask and the database.
    """
    file_rows = list(files)
    plan = verification_plan(file_rows)
    results = []
    failures = []

    try:
        issues = health_check(pid, list(changed) or None, lint_files=True, cap=20)
    except Exception as exc:  # diagnostics must never crash the coding job
        issues = [f"Static project check could not complete: {type(exc).__name__}: {exc}"]
    for issue in issues:
        failures.append(str(issue))
    results.append({"label": "Cross-file and lint checks", "ok": not issues,
                    "output": "\n".join(map(str, issues)) if issues else "passed"})

    for label, command in plan:
        if not command:
            results.append({"label": label, "ok": True, "skipped": True,
                            "output": "No automatic test command was run; package scripts are intentionally not executed."})
            continue
        try:
            output = str(run_command(pid, command))
            # run_cmd always prefixes completed processes with exit=<code>.
            unavailable = ("node روی سرور نصب نیست" in output
                           or "No module named pytest" in output
                           or "No module named 'pytest'" in output)
            skipped = unavailable
            ok = output.splitlines()[:1] == ["exit=0"] or skipped
            if not ok:
                failures.append(f"{label}\n{output[:2500]}")
            results.append({"label": label, "ok": ok, "skipped": skipped, "output": output[:3000]})
        except Exception as exc:
            output = f"check failed to start: {type(exc).__name__}: {exc}"
            failures.append(f"{label}\n{output}")
            results.append({"label": label, "ok": False, "output": output})

    return {"ok": not failures, "results": results, "failures": failures}
