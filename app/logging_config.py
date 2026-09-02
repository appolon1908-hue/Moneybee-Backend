import json
import logging
import sys
import time
from contextvars import ContextVar

from app.config import settings


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in payload or key in logging.LogRecord.__dict__ or key in {
                "args",
                "msg",
                "exc_info",
                "exc_text",
                "stack_info",
            }:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


_CONFIGURED_MARKER = "_moneybee_json_handler"


def configure_logging() -> None:
    """Attach a JSON stdout handler to the root logger, once per process.

    Idempotent and additive rather than clearing existing handlers: tests
    (and any other host process) may already have their own logging
    handlers attached to the root logger, and this function may run more
    than once per process (e.g. once per TestClient lifespan).
    """
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    if any(getattr(existing, _CONFIGURED_MARKER, False) for existing in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    setattr(handler, _CONFIGURED_MARKER, True)
    root.addHandler(handler)


def bind_request_id(request_id: str | None) -> None:
    _request_id.set(request_id)


def request_logger() -> logging.Logger:
    return logging.getLogger("moneybee.request")


class Timer:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 2)


logger = logging.getLogger("moneybee")
