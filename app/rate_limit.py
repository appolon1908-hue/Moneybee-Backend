from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request

from app.config import settings


@dataclass(frozen=True)
class RateLimitDecision:
    limited: bool
    limit: int
    remaining: int
    reset_seconds: int
    bucket: str


_buckets: dict[str, tuple[int, float]] = {}


def reset_rate_limit_state() -> None:
    _buckets.clear()


def _client_key(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _route_scope(path: str) -> tuple[str, int] | None:
    if path.startswith(("/api/v1/public/", "/api/v2/public/")):
        return "public", settings.public_rate_limit_per_minute
    if path.startswith(("/api/v1/webhooks/", "/api/v2/webhooks/")):
        return "webhook", settings.webhook_rate_limit_per_minute
    return None


def check_request_rate_limit(request: Request) -> RateLimitDecision | None:
    if not settings.rate_limit_enabled:
        return None

    route_scope = _route_scope(request.url.path)
    if route_scope is None:
        return None

    scope, limit = route_scope
    window_seconds = max(1, settings.rate_limit_window_seconds)
    if limit <= 0:
        return None

    now = time.monotonic()
    bucket = f"{scope}:{_client_key(request)}"
    count, reset_at = _buckets.get(bucket, (0, now + window_seconds))
    if now >= reset_at:
        count = 0
        reset_at = now + window_seconds

    reset_seconds = max(1, int(reset_at - now + 0.999))
    if count >= limit:
        return RateLimitDecision(
            limited=True,
            limit=limit,
            remaining=0,
            reset_seconds=reset_seconds,
            bucket=scope,
        )

    count += 1
    _buckets[bucket] = (count, reset_at)
    return RateLimitDecision(
        limited=False,
        limit=limit,
        remaining=max(0, limit - count),
        reset_seconds=reset_seconds,
        bucket=scope,
    )
