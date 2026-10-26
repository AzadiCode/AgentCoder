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


CONTEXT_HINTS = ("length of a", "too long", "context length", "context_length", "maximum context",
                 "shorten your", "too many tokens", "reduce the length", "token limit", "payload too large")


class ProviderError(RuntimeError):
    """All candidates failed. `context_too_long` means the prompt itself was rejected;
    `retryable` means at least one failure looked temporary (5xx, 429, network, broken stream)."""

    def __init__(self, message: str, context_too_long: bool = False, retryable: bool = False, errors: list[str] | None = None):
        super().__init__(message)
        self.context_too_long = context_too_long
        self.retryable = retryable
        self.errors = errors or []


class _CallFailed(Exception):
    def __init__(self, status: int | None, detail: str, kind: str):
        super().__init__(detail)
        self.status, self.detail, self.kind = status, detail, kind


def looks_like_context_error(status: int | None, text: str) -> bool:
    t = (text or "").lower()
    return (status in (400, 413, 422) or status is None) and any(h in t for h in CONTEXT_HINTS)


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

    # Simple numbered variables (easy to paste in hosting dashboards such as Render):
    #   AI_BASE_URL_2, AI_API_KEY_2, AI_MODELS_2="model-a,model-b"  (up to _6)
    for n in range(2, 7):
        url, key = _clean_base_url(env.get(f"AI_BASE_URL_{n}", "")), env.get(f"AI_API_KEY_{n}", "").strip()
        models = _strings(env.get(f"AI_MODELS_{n}", "") or env.get(f"AI_MODEL_{n}", ""))
        if url and key and models:
            providers.append({
                "name": (env.get(f"AI_NAME_{n}", "").strip() or f"extra-{n}")[:80],
                "base_url": url, "api_key": key, "models": list(dict.fromkeys(models)),
                "role_models": {}, "roles": ["main", "planner", "reviewer", "duo", "default"], "priority": n,
                "timeout": int(env.get("AI_READ_TIMEOUT", "180")) if str(env.get("AI_READ_TIMEOUT", "180")).isdigit() else 180,
                "connect_timeout": int(env.get("AI_CONNECT_TIMEOUT", "8")) if str(env.get("AI_CONNECT_TIMEOUT", "8")).isdigit() else 8,
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
                 cooldown: float = DEFAULT_COOLDOWN, clock=time.monotonic, max_attempts: int = 6,
                 same_retries: int = 2, sleep=time.sleep):
        self.providers = providers
        self.same_retries = max(0, min(5, int(same_retries)))
        self.sleep = sleep
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

    def _request(self, provider: dict[str, Any], model: str, payload: dict[str, Any]) -> str:
        """One HTTP call. Returns the full assistant text or raises _CallFailed(kind=...)."""
        body = dict(payload)
        body["model"] = model
        body["stream"] = True
        timeout = (int(provider.get("connect_timeout", 8)), int(provider.get("timeout", 180)))
        key = provider["api_key"]
        with self.session.post(
            provider["base_url"] + "/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json=body, timeout=timeout, stream=True,
        ) as response:
            status = int(response.status_code)
            if status >= 400:
                detail = " ".join((response.text or "").split()).replace(key, "[REDACTED]")[:MAX_ERROR_TEXT]
                if status in AUTH_STATUS:
                    kind = "auth"
                elif looks_like_context_error(status, detail):
                    kind = "context"
                elif status in TRANSIENT_STATUS:
                    kind = "transient"
                else:
                    kind = "other"
                raise _CallFailed(status, detail, kind)
            content_type = (response.headers.get("content-type") or "").lower()
            if "event-stream" not in content_type:
                obj = response.json()
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise _CallFailed(None, str(msg)[:MAX_ERROR_TEXT], "stream")
                content = (((obj.get("choices") or [{}])[0].get("message") or {}).get("content"))
                if not isinstance(content, str) or not content:
                    raise _CallFailed(None, "empty or malformed completion response", "stream")
                return content
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
                if obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    msg = str(msg or "provider returned a streaming error")[:MAX_ERROR_TEXT]
                    raise _CallFailed(None, msg, "context" if looks_like_context_error(None, msg) else "stream")
                piece = (((obj.get("choices") or [{}])[0]).get("delta") or {}).get("content")
                if isinstance(piece, str):
                    pieces.append(piece)
            content = "".join(pieces)
            if not content:
                raise _CallFailed(None, "provider returned an empty stream", "stream")
            return content

    def complete(self, payload: dict[str, Any], requested_model: str | None = None,
                 role: str | None = None) -> tuple[str, dict[str, Any]]:
        """Return a complete assistant message; the response is buffered so failed streams can safely fail over.

        With several providers a failing provider is skipped immediately. With a single provider
        (typical for free gateways) temporary errors are retried with backoff and the remaining
        models of that provider are still tried instead of giving up after the first failure.
        """
        candidate_model = requested_model if requested_model else (payload.get("model") if role in (None, "main", "default", "duo") else None)
        candidates = self._candidates(candidate_model, role)
        multi = len({p["name"] for p, _ in candidates}) > 1
        tries = 1 if multi else 1 + self.same_retries
        errors: list[str] = []
        attempted: set[tuple[str, str]] = set()
        unavailable: set[str] = set()
        context_hit = retryable = False
        for provider, model in candidates:
            if len(attempted) >= self.max_attempts:
                break
            if provider["name"] in unavailable:
                continue
            key = (provider["name"], model)
            if key in attempted:
                continue
            attempted.add(key)
            for n in range(tries):
                started = self.clock()
                try:
                    content = self._request(provider, model, payload)
                except _CallFailed as exc:
                    failure = exc
                except Exception as exc:  # transport errors: timeout, DNS, reset ...
                    failure = _CallFailed(None, str(exc).replace(provider["api_key"], "[REDACTED]")[:MAX_ERROR_TEXT], "network")
                else:
                    latency = int((self.clock() - started) * 1000)
                    self._mark_success(provider, latency)
                    return content, {"provider": provider["name"], "model": model, "latency_ms": latency,
                                     "attempts": len(attempted)}
                label = f"HTTP {failure.status} " if failure.status else ""
                errors.append(f"{provider['name']}/{model}: {label}{failure.detail}".strip())
                if failure.kind == "context":
                    context_hit = True      # the prompt is the problem, not the provider's health
                    break
                self._mark_failure(provider, failure.status, failure.detail)
                if failure.kind in ("transient", "stream", "network"):
                    retryable = True
                if failure.kind in ("transient", "stream") and n < tries - 1:
                    self.sleep(min(8.0, 1.5 * (2 ** n)) + random.uniform(0, 0.5))
                    continue
                break
            if failure.kind == "auth":
                with self._lock:
                    self._health[provider["name"]]["cooldown_until"] = self.clock() + 120
                unavailable.add(provider["name"])
            elif failure.kind == "network" or (multi and failure.kind in ("transient", "stream")):
                unavailable.add(provider["name"])
        summary = " | ".join(errors[-8:])[:1800]
        raise ProviderError(f"No AI provider/model succeeded within {len(attempted)} attempts. " + summary,
                            context_too_long=context_hit, retryable=retryable, errors=errors[-8:])

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
