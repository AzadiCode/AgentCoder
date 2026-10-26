# -*- coding: utf-8 -*-
"""Deterministic, source-grounded engineering memory for AgentCoder projects.

Generated facts are derived from current files. User-authored notes/decisions are
kept separately so refreshing the map never overwrites intentional knowledge.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable

MAX_FILES_IN_MAP = 200
MAX_SYMBOLS_PER_FILE = 18
MAX_NOTES = 6000
MAX_DECISIONS = 40


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def _file_path(row: dict) -> str:
    return _text(row.get("path", ""), 160).replace("\\", "/").lstrip("/")


def _symbols(path: str, content: str) -> list[str]:
    """Extract a small outline without executing or importing project code."""
    found: list[str] = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    prefix = "class" if isinstance(node, ast.ClassDef) else "def"
                    found.append(f"{prefix} {node.name} (L{node.lineno})")
        except (SyntaxError, ValueError, TypeError):
            return ["Python outline unavailable: syntax parse failed"]
    elif path.endswith(('.js', '.jsx', '.ts', '.tsx')):
        patterns = [
            r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([\w$]+)",
            r"(?m)^\s*(?:export\s+)?class\s+([\w$]+)",
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:\([^\n]*\)|[\w$]+)\s*=>",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                found.append(f"symbol {match.group(1)} (L{content.count(chr(10), 0, match.start()) + 1})")
    elif path.endswith((".go",)):
        found.extend(f"func {m.group(1)}" for m in re.finditer(r"(?m)^func\s+(?:\([^)]*\)\s*)?([\w]+)", content))
    return found[:MAX_SYMBOLS_PER_FILE]


def build_memory(files: Iterable[dict], previous: dict | None = None) -> dict[str, Any]:
    rows = []
    for f in files:
        path = _file_path(f)
        if not path or path.startswith("../") or "/../" in path:
            continue
        content = str(f.get("content", ""))
        rows.append((path, content))
    rows.sort(key=lambda x: x[0])
    languages = Counter()
    key_files = []
    test_files = []
    entry_files = []
    symbols = {}
    manifest_names = {"pyproject.toml", "requirements.txt", "package.json", "cargo.toml", "go.mod", "pom.xml", "build.gradle", "composer.json"}
    manifests = []
    signatures = []
    for path, content in rows:
        lower = path.lower()
        ext = lower.rsplit(".", 1)[-1] if "." in lower else ""
        lang = {"py": "Python", "js": "JavaScript", "jsx": "JavaScript/JSX", "ts": "TypeScript", "tsx": "TypeScript/JSX", "html": "HTML", "css": "CSS", "go": "Go", "rs": "Rust", "java": "Java", "php": "PHP", "rb": "Ruby", "sh": "Shell", "sql": "SQL"}.get(ext)
        if lang:
            languages[lang] += 1
        base = lower.rsplit("/", 1)[-1]
        if base in manifest_names:
            manifests.append(path)
        if base.startswith(("test_",)) or "/tests/" in f"/{lower}" or base.endswith(("_test.py", ".spec.js", ".test.js", ".spec.ts", ".test.ts")):
            test_files.append(path)
        if base in {"main.py", "app.py", "manage.py", "server.py", "index.js", "index.ts", "main.go", "main.rs"}:
            entry_files.append(path)
        if base in {"readme.md", "pyproject.toml", "requirements.txt", "package.json", "dockerfile", "compose.yaml", "docker-compose.yml", "go.mod", "cargo.toml"} or base.startswith(".github/workflows/"):
            key_files.append(path)
        outline = _symbols(path, content)
        if outline:
            symbols[path] = outline
        signatures.append({"path": path, "sha256": hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()[:16], "bytes": len(content)})
    previous = previous if isinstance(previous, dict) else {}
    return {
        "schema_version": 1,
        "source": "derived_from_project_files",
        "file_count": len(rows),
        "file_map": [{"path": p, "lines": c.count("\n") + 1, "bytes": len(c)} for p, c in rows[:MAX_FILES_IN_MAP]],
        "map_truncated": len(rows) > MAX_FILES_IN_MAP,
        "languages": dict(languages.most_common()),
        "key_files": key_files[:40],
        "entry_points": entry_files[:30],
        "test_files": test_files[:60],
        "dependency_manifests": manifests[:30],
        "symbol_outline": symbols,
        "file_signatures": signatures,
        "user_notes": _text(previous.get("user_notes", ""), MAX_NOTES),
        "decisions": _clean_decisions(previous.get("decisions", [])),
        "refreshed_at": None,
    }


def _clean_decisions(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items[-MAX_DECISIONS:]:
        if isinstance(item, str):
            decision = {"decision": _text(item, 500), "reason": ""}
        elif isinstance(item, dict):
            decision = {"decision": _text(item.get("decision", ""), 500), "reason": _text(item.get("reason", ""), 500)}
        else:
            continue
        if decision["decision"]:
            out.append(decision)
    return out


def render_memory(memory: dict[str, Any], max_chars: int = 9000) -> str:
    """Render compact, bounded context; explicitly distinguish facts from notes."""
    memory = memory if isinstance(memory, dict) else {}
    lines = ["ENGINEERING MEMORY (refreshable facts are derived from current files; user notes are guidance, not proof):"]
    lines.append(f"File count: {int(memory.get('file_count', 0) or 0)}")
    langs = memory.get("languages") or {}
    if langs:
        lines.append("Languages by file count: " + ", ".join(f"{k}={v}" for k, v in list(langs.items())[:10]))
    for label, key in (("Entry points", "entry_points"), ("Important project/config files", "key_files"), ("Test files", "test_files"), ("Dependency manifests", "dependency_manifests")):
        values = memory.get(key) or []
        if values:
            lines.append(label + ": " + ", ".join(str(x)[:160] for x in values[:30]))
    notes = _text(memory.get("user_notes", ""), MAX_NOTES)
    if notes:
        lines.extend(["USER-AUTHORED PROJECT NOTES (follow unless they conflict with the explicit request or safety):", notes])
    decisions = _clean_decisions(memory.get("decisions", []))
    if decisions:
        lines.append("RECORDED ENGINEERING DECISIONS:")
        for d in decisions[-20:]:
            lines.append("- " + d["decision"] + (" — reason: " + d["reason"] if d["reason"] else ""))
    outline = memory.get("symbol_outline") or {}
    if outline:
        lines.append("Source-grounded symbol outline (verify current source before editing):")
        for path, names in list(outline.items())[:24]:
            lines.append(f"- {path}: " + "; ".join(str(x) for x in names[:10]))
    result = "\n".join(lines)
    return result[:max(1000, int(max_chars))]


def merge_user_memory(previous: dict | None, notes: Any = None, decisions: Any = None) -> dict[str, Any]:
    """Update only user-authored fields; never let a refresh overwrite them."""
    previous = previous if isinstance(previous, dict) else {}
    out = dict(previous)
    if notes is not None:
        out["user_notes"] = _text(notes, MAX_NOTES)
    if decisions is not None:
        out["decisions"] = _clean_decisions(decisions)
    return out
