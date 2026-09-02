import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repository_production_gate.py"


def _module():
    spec = importlib.util.spec_from_file_location("repository_production_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _passing_values(module) -> dict[str, str]:
    values = {
        "APP_ENV": "production",
        "DATABASE_RUNTIME_ROLE": "moneybee_runtime",
        "RATE_LIMIT_BACKEND": "redis",
        "TRUST_FORWARDED_FOR": "true",
        "TRUSTED_PROXY_CIDRS_CSV": "172.16.0.0/12",
        "MIGRATION_HEAD": "20260901_0026",
    }
    values.update({name: "PASS" for name in module.PASS_EVIDENCE})
    return values


def test_repository_production_gate_accepts_complete_controlled_evidence():
    module = _module()
    assert module.validate(_passing_values(module)) == []


def test_repository_production_gate_rejects_admin_memory_and_missing_evidence():
    module = _module()
    values = _passing_values(module)
    values.update(
        {
            "DATABASE_RUNTIME_ROLE": "moneybee_admin",
            "RATE_LIMIT_BACKEND": "memory",
            "TRUSTED_PROXY_CIDRS_CSV": "",
            "PITR_STATUS": "NOT_CONFIGURED",
        }
    )
    failures = module.validate(values)
    assert any("DATABASE_RUNTIME_ROLE" in failure for failure in failures)
    assert any("RATE_LIMIT_BACKEND" in failure for failure in failures)
    assert any("trusted proxy" in failure for failure in failures)
    assert any("PITR_STATUS" in failure for failure in failures)
