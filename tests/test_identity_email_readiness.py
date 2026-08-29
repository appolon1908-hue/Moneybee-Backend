import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_identity_email_readiness.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("identity_email_readiness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_moneybee_identity_email_evidence_maps_only_attested_checks(monkeypatch):
    checker = load_checker()
    monkeypatch.delenv("MONEYBEE_POSTAL_DKIM", raising=False)
    evidence = checker.load_evidence_file(
        "docs/evidence/identity-email-activation-2026-08-29.json"
    )

    results = checker.check_live_evidence(True, evidence)
    statuses = {item.name: item.status for item in results}

    assert statuses["evidence.MONEYBEE_POSTAL_DKIM"] == "PASS"
    assert statuses["evidence.MONEYBEE_POSTAL_RETURN_PATH"] == "PASS"
    assert statuses["evidence.DIRECT_APP_SMTP_ACCESS"] == "PASS"
    assert statuses["evidence.RESET_TOKEN_OUTSIDE_KEYCLOAK"] == "PASS"
    assert statuses["evidence.KEYCLOAK_PASSWORD_RESET_TEST"] == "FAIL"
    assert statuses["evidence.MONEYBEE_POSTAL_DKIM_ROTATED"] == "FAIL"
