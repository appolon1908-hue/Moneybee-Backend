from __future__ import annotations

from collections import defaultdict
from threading import Lock


LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = Lock()
_requests: dict[tuple[str, str, str, str], int] = defaultdict(int)
_latency_buckets: dict[tuple[str, str, str, float], int] = defaultdict(int)
_latency_count: dict[tuple[str, str, str], int] = defaultdict(int)
_latency_sum: dict[tuple[str, str, str], float] = defaultdict(float)
_in_flight = 0


def request_started() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def request_finished(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
    rate_limit_bucket: str | None = None,
) -> None:
    global _in_flight
    status_class = f"{status_code // 100}xx"
    rate_scope = rate_limit_bucket or "none"
    with _lock:
        _in_flight = max(0, _in_flight - 1)
        _requests[(method, route, status_class, rate_scope)] += 1
        histogram_key = (method, route, status_class)
        _latency_count[histogram_key] += 1
        _latency_sum[histogram_key] += duration_seconds
        for bucket in LATENCY_BUCKETS:
            if duration_seconds <= bucket:
                _latency_buckets[(*histogram_key, bucket)] += 1


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _line(name: str, labels: dict[str, str], value: int | float) -> str:
    rendered_labels = ",".join(
        f'{key}="{_escape_label(label_value)}"'
        for key, label_value in labels.items()
    )
    return f"{name}{{{rendered_labels}}} {value}"


def render_prometheus() -> str:
    with _lock:
        in_flight = _in_flight
        requests = dict(_requests)
        latency_buckets = dict(_latency_buckets)
        latency_count = dict(_latency_count)
        latency_sum = dict(_latency_sum)

    lines = [
        "# HELP moneybee_http_requests_in_flight Current HTTP requests in flight.",
        "# TYPE moneybee_http_requests_in_flight gauge",
        f"moneybee_http_requests_in_flight {in_flight}",
        "# HELP moneybee_http_requests_total HTTP requests by method, route, status class, and rate scope.",
        "# TYPE moneybee_http_requests_total counter",
    ]
    for (method, route, status_class, rate_scope), value in sorted(requests.items()):
        lines.append(
            _line(
                "moneybee_http_requests_total",
                {
                    "method": method,
                    "route": route,
                    "status_class": status_class,
                    "rate_scope": rate_scope,
                },
                value,
            )
        )

    lines.extend(
        [
            "# HELP moneybee_http_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE moneybee_http_request_duration_seconds histogram",
        ]
    )
    for method, route, status_class in sorted(latency_count):
        cumulative = 0
        base_labels = {"method": method, "route": route, "status_class": status_class}
        for bucket in LATENCY_BUCKETS:
            cumulative = latency_buckets.get((method, route, status_class, bucket), cumulative)
            lines.append(
                _line(
                    "moneybee_http_request_duration_seconds_bucket",
                    {**base_labels, "le": str(bucket)},
                    cumulative,
                )
            )
        lines.append(
            _line(
                "moneybee_http_request_duration_seconds_bucket",
                {**base_labels, "le": "+Inf"},
                latency_count[(method, route, status_class)],
            )
        )
        lines.append(
            _line(
                "moneybee_http_request_duration_seconds_count",
                base_labels,
                latency_count[(method, route, status_class)],
            )
        )
        lines.append(
            _line(
                "moneybee_http_request_duration_seconds_sum",
                base_labels,
                round(latency_sum[(method, route, status_class)], 6),
            )
        )

    return "\n".join(lines) + "\n"
