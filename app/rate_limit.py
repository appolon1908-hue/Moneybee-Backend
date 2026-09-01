import time
from collections import defaultdict, deque

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

_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def reset_rate_limit_state() -> None:
    """Clears in-memory hit tracking. Tests call this between cases so one
    test's requests don't count against the next test's limit - the state
    is process-global (module-level, not per-middleware-instance) since the
    app builds a single InMemoryRateLimitMiddleware instance for its
    lifetime and tests reuse the same app across cases."""
    _hits.clear()


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


def _client_key(request: Request) -> str:
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-IP rate limiting for unauthenticated surfaces.

    This is a single-process stopgap: it does not coordinate across
    multiple API instances. At real scale, replace with an edge-level or
    Redis-backed limiter (see docs/codex/PRODUCTION_100_MISSION.md).
    """

    def __init__(self, app, limits_per_minute: dict[str, int] | None = None) -> None:
        super().__init__(app)
        self._limit_overrides = limits_per_minute

    async def dispatch(self, request: Request, call_next):
        if self._limit_overrides is None and not settings.rate_limit_enabled:
            return await call_next(request)

        bucket = _bucket_for_path(request.url.path)
        if bucket is None:
            return await call_next(request)

        limit = _limit_for_bucket(bucket, self._limit_overrides)
        if not limit or limit <= 0:
            return await call_next(request)

        window_seconds = settings.rate_limit_window_seconds
        key = (bucket, _client_key(request))
        now = time.monotonic()
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
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

        hits.append(now)
        return await call_next(request)
