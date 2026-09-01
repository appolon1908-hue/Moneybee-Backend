from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings


RATE_LIMITED_PREFIXES: dict[str, str] = {
    "/api/v2/public/": "public",
    "/api/v1/public/": "public",
    "/api/v2/webhooks/": "webhook",
    "/api/v1/webhooks/": "webhook",
}


class RateLimitBackend(Protocol):
    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]: ...


class RedisRateLimitBackend:
    """Atomic fixed-window counters shared by every API process and replica."""

    _SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        count, ttl = await self.redis.eval(self._SCRIPT, 1, key, window_seconds)
        return int(count), max(1, int(ttl))


class InMemoryRateLimitBackend:
    """Deterministic test backend. Production never selects this backend."""

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        hits.append(now)
        ttl = max(1, int(window_seconds - (now - hits[0])))
        return len(hits), ttl

    def reset(self) -> None:
        self.hits.clear()


_test_backend = InMemoryRateLimitBackend()


def reset_rate_limit_state() -> None:
    _test_backend.reset()


def _bucket_for_path(path: str) -> str | None:
    for prefix, bucket in RATE_LIMITED_PREFIXES.items():
        if path.startswith(prefix):
            return bucket
    return None


def _limit_for_bucket(bucket: str, overrides: dict[str, int] | None) -> int:
    if overrides is not None:
        return overrides.get(bucket, 0)
    return {
        "public": settings.public_rate_limit_per_minute,
        "webhook": settings.webhook_rate_limit_per_minute,
    }[bucket]


def _ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value or "")
    except ValueError:
        return None


def _peer_is_trusted(request: Request) -> bool:
    peer = _ip(request.client.host if request.client else None)
    if peer is None or not settings.trust_forwarded_for:
        return False
    for value in settings.trusted_proxy_cidrs:
        try:
            if peer in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolved_client_ip(request: Request) -> str:
    """Accept forwarding data only from an approved immediate proxy."""
    peer = request.client.host if request.client else "unknown"
    if not _peer_is_trusted(request):
        return peer
    chain = [part.strip() for part in request.headers.get("X-Forwarded-For", "").split(",")]
    valid = [candidate for candidate in chain if _ip(candidate) is not None]
    return valid[-1] if valid else peer


class DistributedRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        limits_per_minute: dict[str, int] | None = None,
        backend: RateLimitBackend | None = None,
    ) -> None:
        super().__init__(app)
        self._limit_overrides = limits_per_minute
        self._backend = backend or (
            _test_backend if settings.app_env == "test" else RedisRateLimitBackend()
        )

    async def dispatch(self, request: Request, call_next):
        if self._limit_overrides is None and not settings.rate_limit_enabled:
            return await call_next(request)
        bucket = _bucket_for_path(request.url.path)
        if bucket is None:
            return await call_next(request)
        limit = _limit_for_bucket(bucket, self._limit_overrides)
        if limit <= 0:
            return await call_next(request)

        key = f"moneybee:rate-limit:{bucket}:{resolved_client_ip(request)}"
        try:
            count, retry_after = await self._backend.hit(
                key, settings.rate_limit_window_seconds
            )
        except RedisError:
            return JSONResponse(
                status_code=503,
                media_type="application/problem+json",
                content={
                    "type": "https://api.moneybeeloan.com/problems/rate-limit-unavailable",
                    "title": "Service temporarily unavailable",
                    "status": 503,
                    "detail": "Request protection is temporarily unavailable.",
                    "instance": request.url.path,
                },
                headers={"Retry-After": "1"},
            )

        if count > limit:
            return JSONResponse(
                status_code=429,
                media_type="application/problem+json",
                content={
                    "type": "https://api.moneybeeloan.com/problems/rate-limit",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": "Rate limit exceeded for this endpoint.",
                    "instance": request.url.path,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response


InMemoryRateLimitMiddleware = DistributedRateLimitMiddleware
