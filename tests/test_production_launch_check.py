import importlib.util
import os
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_launch_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("production_launch_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def frontend_root() -> Path:
    configured = os.environ.get("MONEYBEE_FRONTEND_ROOT")
    if configured:
        return Path(configured)
    repository_root = Path(__file__).resolve().parents[1]
    embedded_checkout = repository_root / "Moneybee-frontend-"
    if embedded_checkout.exists():
        return embedded_checkout
    return repository_root.parent / "Moneybee-frontend-"


def test_launch_check_separates_repo_ready_from_external_blockers():
    checker = load_checker()
    frontend = frontend_root()
    evidence = checker.load_evidence(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "evidence"
        / "identity-email-activation-2026-08-29.json"
    )

    checks = [
        *checker.repo_marketing_checks(frontend / "apps" / "marketing"),
        *checker.identity_email_checks(evidence),
        *checker.external_approval_checks(evidence),
    ]
    statuses = {item.name: item.status for item in checks}

    assert statuses["marketing.landing_pages.count"] == "PASS"
    assert statuses["marketing.policy.privacy"] == "PASS"
    assert statuses["identity.dns.dkim"] == "PASS"
    assert statuses["identity.control.reset_tokens_external"] == "PASS"
    assert statuses["identity.live.keycloak_password_reset_test"] == "BLOCKED"
    assert statuses["google.ads_txt.publisher"] == "BLOCKED"
    assert statuses["external.google_search_console_verified"] == "BLOCKED"
