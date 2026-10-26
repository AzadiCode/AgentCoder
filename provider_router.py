# -*- coding: utf-8 -*-
"""OpenAI-compatible multi-provider routing with fast failover and health-aware ordering.

AI_PROVIDERS_JSON example:
[
  {"name":"backup-a", "base_url":"https://example.com/v1", "api_key":"...",
   "models":["coder-model", "strong-model"], "role_models":{"planner":"fast-model"},
   "roles":["main", "planner", "reviewer", "duo"]}
]
Legacy AI_BASE_URL / AI_API_KEY / AI_MODEL remain supported and are tried first.
Secrets are never included in status output or exception messages.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any, Iterable

import requests

TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}
DEFAULT_COOLDOWN = 12.0
MAX_ERROR_TEXT = 280


def _clean_base_url(value: Any) -> str:
    value = str(value or "").strip().rstrip("/")
    if value.endswith("/chat/completions"):
        value = value[:-len("/chat/completions")]
    return value


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def load_providers(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Load legacy and JSON-configured providers; JSON-only configuration is supported."""
    env = os.environ if env is None else env
    providers: list[dict[str, Any]] = []
    legacy_url = _clean_base_url(env.get("AI_BASE_URL", ""))
    legacy_key = env.get("AI_API_KEY", "").strip()
    legacy_model = env.get("AI_MODEL", "").strip()
    if legacy_url and legacy_key and legacy_model:
        legacy_models = [legacy_model] + [m for m in _strings(env.get("AI_FALLBACK_MODELS", "")) if m != legacy_model]
        providers.append({
            "name": "primary", "base_url": legacy_url, "api_key": legacy_key,
            "models": legacy_models, "role_models": {},
            "roles": ["main", "planner", "reviewer", "duo", "default"],
            "priority": 0, "timeout": max(5, min(600, int(env.get("AI_READ_TIMEOUT", "180")))) if str(env.get("AI_READ_TIMEOUT", "180")).isdigit() else 180,
            "connect_timeout": max(2, min(30, int(env.get("AI_CONNECT_TIMEOUT", "8")))) if str(env.get("AI_CONNECT_TIMEOUT", "8")).isdigit() else 8,
        })

    raw = env.get("AI_PROVIDERS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI_PROVIDERS_JSON is invalid JSON at position {exc.pos}") from None
        if not isinstance(parsed, list):
            raise ValueError("AI_PROVIDERS_JSON must be a JSON array")
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue
            url, key = _clean_base_url(item.get("base_url")), str(item.get("api_key", "")).strip()
            models = _strings(item.get("models"))
            if item.get("model"):
                models = [str(item["model"]).strip()] + [m for m in models if m != str(item["model"]).strip()]
            if not url or not key or not models:
                # Incomplete entries are ignored rather than making the whole app fail to boot.
                continue
            role_models = item.get("role_models") if isinstance(item.get("role_models"), dict) else {}
            role_models = {str(k): str(v).strip() for k, v in role_models.items() if str(v).strip()}
            roles = _strings(item.get("roles")) or ["main", "planner", "reviewer", "duo", "default"]
            providers.append({
                "name": str(item.get("name") or f"backup-{index + 1}")[:80],
                "base_url": url, "api_key": key, "models": list(dict.fromkeys(models)),
                "role_models": role_models, "roles": roles,
                "priority": int(item.get("priority", index + 1)) if str(item.get("priority", index + 1)).lstrip("-").isdigit() else index + 1,
                "timeout": max(5, min(600, int(item.get("timeout", env.get("AI_READ_TIMEOUT", 180))))) if str(item.get("timeout", env.get("AI_READ_TIMEOUT", 180))).isdigit() else 180,
                "connect_timeout": max(2, min(30, int(item.get("connect_timeout", env.get("AI_CONNECT_TIMEOUT", 8))))) if str(item.get("connect_timeout", env.get("AI_CONNECT_TIMEOUT", 8))).isdigit() else 8,
            })

    # Remove accidental duplicate endpoint/key/model combinations while preserving first priority.
    seen = set()
    unique = []
    for p in providers:
        signature = (p["base_url"], p["api_key"], tuple(p["models"]))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(p)
    if not unique:
        raise ValueError("No AI provider configured. Set AI_BASE_URL, AI_API_KEY, AI_MODEL or AI_PROVIDERS_JSON.")
    return unique


class ProviderRouter:
    """Select compatible model/provider candidates, fail over quickly, and track provider health."""
    def __init__(self, providers: list[dict[str, Any]], session: requests.Session | None = None,
                 cooldown: float = DEFAULT_COOLDOWN, clock=time.monotonic, max_attempts: int = 6):
        self.providers = providers
        self.session = session or requests.Session()
        self.cooldown = max(1.0, cooldown)
        self.max_attempts = max(1, min(20, int(max_attempts)))
        self.clock = clock
        self._lock = threading.RLock()
        self._health: dict[str, dict[str, Any]] = {
            p["name"]: {"failures": 0, "successes": 0, "latency_ms": None, "cooldown_until": 0.0,
                        "last_error": "", "last_status": None}
            for p in providers
        }

    def _candidates(self, requested_model: str | None, role: str | None) -> list[tuple[dict[str, Any], str]]:
        now = self.clock()
        with self._lock:
            health = {k: dict(v) for k, v in self._health.items()}
        # Prefer healthy providers, but keep configured priority as the tie-breaker.
        ordered = sorted(self.providers, key=lambda p: (
            health[p["name"]]["cooldown_until"] > now,
            health[p["name"]]["failures"],
            0 if role and p["role_models"].get(role) else 1,
            p["priority"],
            health[p["name"]]["latency_ms"] if health[p["name"]]["latency_ms"] is not None else 10**9,
        ))
        candidates: list[tuple[dict[str, Any], str]] = []
        seen: set[tuple[str, str]] = set()
        # Route role-specific calls to their configured model first. This matters for
        # planner/reviewer roles: otherwise the global main model could be tried on every
        # gateway before the role's intended model is considered.
        for p in ordered:
            if role and role not in p["roles"] and role != "default":
                continue
            role_model = p["role_models"].get(role or "")
            model_order = ([role_model] if role_model else [])
            if requested_model:
                model_order.append(requested_model)
            model_order.extend(p["models"])
            for model in model_order:
                if not model:
                    continue
                key = (p["name"], model)
                if key not in seen:
                    candidates.append((p, model)); seen.add(key)
        # If a provider explicitly supports only selected roles, allow it as last-resort fallback
        # only when no role-compatible candidate exists.
        if not candidates and role:
            return self._candidates(requested_model, None)
        return candidates

    def complete(self, payload: dict[str, Any], requested_model: str | None = None,
                 role: str | None = None) -> tuple[str, dict[str, Any]]:
        """Return a complete assistant message; response is buffered so failed streams can safely fail over."""
        candidate_model = requested_model if requested_model else (payload.get("model") if role in (None, "main", "default", "duo") else None)
        candidates = self._candidates(candidate_model, role)
        errors: list[str] = []
        attempted: set[tuple[str, str]] = set()
        unavailable_providers: set[str] = set()
        for provider, model in candidates:
            if len(attempted) >= self.max_attempts:
                break
            if provider["name"] in unavailable_providers:
                continue
            key = (provider["name"], model)
            if key in attempted:
                continue
            attempted.add(key)
            started = self.clock()
            try:
                body = dict(payload)
                body["model"] = model
                body["stream"] = True
                timeout = (int(provider.get("connect_timeout", 8)), int(provider.get("timeout", 180)))
                with self.session.post(
                    provider["base_url"] + "/chat/completions",
                    headers={"Authorization": "Bearer " + provider["api_key"], "Content-Type": "application/json"},
                    json=body, timeout=timeout, stream=True,
                ) as response:
                    status = int(response.status_code)
                    if status >= 400:
                        # Bound and sanitize response text; never include credentials.
                        detail = " ".join((response.text or "").split()).replace(provider["api_key"], "[REDACTED]")[:MAX_ERROR_TEXT]
                        self._mark_failure(provider, status, f"HTTP {status}: {detail}")
                        errors.append(f"{provider['name']}/{model}: HTTP {status} {detail}".strip())
                        # Auth failure is unlikely to heal during this task; skip this provider.
                        if status in AUTH_STATUS or status in TRANSIENT_STATUS:
                            unavailable_providers.add(provider["name"])
                        if status in AUTH_STATUS:
                            with self._lock:
                                self._health[provider["name"]]["cooldown_until"] = self.clock() + 120
                        continue
                    content_type = (response.headers.get("content-type") or "").lower()
                    if "event-stream" not in content_type:
                        obj = response.json()
                        content = (((obj.get("choices") or [{}])[0].get("message") or {}).get("content"))
                        if not isinstance(content, str) or not content:
                            raise ValueError("empty or malformed completion response")
                    else:
                        pieces: list[str] = []
                        for raw in response.iter_lines():
                            if not raw:
                                continue
                            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                obj = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            choice = ((obj.get("choices") or [{}])[0])
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")
                            if isinstance(piece, str):
                                pieces.append(piece)
                            # Some compatible APIs signal stream errors inside an HTTP 200 body.
                            if obj.get("error"):
                                raise RuntimeError("provider returned a streaming error")
                        content = "".join(pieces)
                        if not content:
                            raise ValueError("provider returned an empty stream")
                latency = int((self.clock() - started) * 1000)
                self._mark_success(provider, latency)
                return content, {"provider": provider["name"], "model": model, "latency_ms": latency,
                                 "attempts": len(attempted)}
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                safe_error = str(exc).replace(provider["api_key"], "[REDACTED]")[:MAX_ERROR_TEXT]
                self._mark_failure(provider, status, safe_error)
                # Transport/stream failures should switch provider immediately rather than
                # spending time trying every model on the same unhealthy endpoint.
                unavailable_providers.add(provider["name"])
                errors.append(f"{provider['name']}/{model}: {safe_error}")
                continue
        summary = " | ".join(errors[-8:])[:1800]
        raise RuntimeError(f"No AI provider/model succeeded within {self.max_attempts} attempts. " + summary)

    def _mark_success(self, provider: dict[str, Any], latency: int) -> None:
        with self._lock:
            h = self._health[provider["name"]]
            h.update(failures=0, successes=h["successes"] + 1, latency_ms=latency,
                     cooldown_until=0.0, last_error="", last_status=None)

    def _mark_failure(self, provider: dict[str, Any], status: int | None, error: str) -> None:
        now = self.clock()
        with self._lock:
            h = self._health[provider["name"]]
            h["failures"] += 1
            h["last_status"] = status
            h["last_error"] = str(error).replace(provider["api_key"], "[REDACTED]")[:MAX_ERROR_TEXT]
            if status in AUTH_STATUS:
                cooldown = 120
            elif status in TRANSIENT_STATUS or status is None:
                cooldown = min(180, self.cooldown * (2 ** min(h["failures"] - 1, 4)))
            else:
                cooldown = self.cooldown
            h["cooldown_until"] = now + cooldown

    def status(self) -> list[dict[str, Any]]:
        """Sanitized operational status; never return API keys or full URLs."""
        now = self.clock()
        with self._lock:
            rows = []
            for p in self.providers:
                h = dict(self._health[p["name"]])
                rows.append({"name": p["name"], "models": list(dict.fromkeys(list(p["models"]) + list(p["role_models"].values()))),
                             "role_models": dict(p["role_models"]), "roles": list(p["roles"]),
                             "successes": h["successes"], "failures": h["failures"],
                             "latency_ms": h["latency_ms"], "last_status": h["last_status"],
                             "last_error": h["last_error"], "cooldown_seconds": max(0, int(h["cooldown_until"] - now)),
                             "read_timeout_seconds": int(p.get("timeout", 180)),
                             "connect_timeout_seconds": int(p.get("connect_timeout", 8))})
            return rows


def chunk_text(text: str, size: int = 256) -> Iterable[str]:
    """Yield completed response in small pieces for the existing UI event stream."""
    size = max(32, min(2048, int(size)))
    for start in range(0, len(text), size):
        yield text[start:start + size]
