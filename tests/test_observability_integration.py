from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
OBSERVABILITY = ROOT / "deploy" / "observability"


def test_observability_overlay_files_exist():
    expected = {
        "prometheus-moneybee.yml",
        "blackbox-moneybee.yml",
        "moneybee-alerts.yml",
        "otel-collector-moneybee.yml",
        "alloy-moneybee.river",
        "openbao-moneybee-policy.hcl",
    }

    assert expected <= {path.name for path in OBSERVABILITY.iterdir()}


def test_prometheus_overlay_scrapes_moneybee_internally():
    config = (OBSERVABILITY / "prometheus-moneybee.yml").read_text(encoding="utf-8")

    assert "job_name: moneybee-api" in config
    assert "metrics_path: /metrics" in config
    assert "moneybee-api:8000" in config
    assert "https://moneybeeloan.com" in config
    assert "job_name: moneybee-edge-security-headers" in config
    assert "postgres-exporter:9187" in config
    assert "redis-exporter:9121" in config


def test_blackbox_overlay_requires_security_headers():
    config = (OBSERVABILITY / "blackbox-moneybee.yml").read_text(encoding="utf-8")

    for header in (
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
    ):
        assert header in config
    assert "fail_if_not_ssl: true" in config


def test_openbao_policy_is_scoped_to_moneybee_paths():
    policy = (OBSERVABILITY / "openbao-moneybee-policy.hcl").read_text(encoding="utf-8")

    assert 'path "kv/data/moneybee/*"' in policy
    assert 'path "transit/encrypt/moneybee-field-encryption"' in policy
    assert "kv/data/beyvra" not in policy
    assert 'path "kv/data/*"' not in policy


def test_metrics_endpoint_records_health_request_without_sensitive_values():
    with TestClient(app) as client:
        client.get("/health/live")
        response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "moneybee_http_requests_total" in body
    assert 'route="/health/live"' in body
    assert "DATABASE_URL" not in body
    assert "FIELD_ENCRYPTION_KEY" not in body
