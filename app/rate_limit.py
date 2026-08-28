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

_LIMITS_PER_MINUTE: dict[str, int] = {
    "public": settings.public_rate_limit_per_minute,
    "webhook": settings.webhook_rate_limit_per_minute,
}

WINDOW_SECONDS = 60.0


def _bucket_for_path(path: str) -> str | None:
    for prefix, bucket in RATE_LIMITED_PREFIXES.items():
        if path.startswith(prefix):
            return bucket
    return None


def _client_key(request: Request) -> str:
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
        self._limits = limits_per_minute or _LIMITS_PER_MINUTE
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        bucket = _bucket_for_path(request.url.path)
        if bucket is None:
            return await call_next(request)

        limit = self._limits.get(bucket)
        if not limit or limit <= 0:
            return await call_next(request)

        key = (bucket, _client_key(request))
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(1, int(WINDOW_SECONDS - (now - hits[0])))
            return JSONResponse(
                status_code=429,
                media_type="application/problem+json",
                content={
                    "type": "https://api.moneybeeloan.com/problems/rate-limited",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": "Rate limit exceeded for this endpoint.",
                    "instance": request.url.path,
                },
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)
