import importlib.util
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


def test_launch_check_separates_repo_ready_from_external_blockers():
    checker = load_checker()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"
    evidence = checker.load_evidence(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "evidence"
        / "identity-email-activation-2026-08-29.json"
    )

    checks = [
        *checker.repo_marketing_checks(frontend_root / "apps" / "marketing"),
        *checker.identity_email_checks(evidence),
        *checker.external_approval_checks(evidence),
        *checker.release_gate_checks(evidence, frontend_root),
    ]
    statuses = {item.name: item.status for item in checks}

    assert statuses["marketing.landing_pages.count"] == "PASS"
    assert statuses["marketing.policy.privacy"] == "PASS"
    assert statuses["identity.dns.dkim"] == "PASS"
    assert statuses["identity.control.reset_tokens_external"] == "PASS"
    assert statuses["identity.live.keycloak_password_reset_test"] == "BLOCKED"
    assert statuses["google.ads_txt.publisher"] == "BLOCKED"
    assert statuses["external.google_search_console_verified"] == "BLOCKED"
    assert statuses["release.runtime_paths.verified"] == "BLOCKED"
    assert statuses["release.lock.verified"] == "BLOCKED"
    assert statuses["release.image.api"] == "BLOCKED"
    assert statuses["release.backup.restore_tested"] == "BLOCKED"
    assert statuses["release.evidence.human_launch_approval"] == "BLOCKED"


def test_launch_check_writes_blocked_evidence_file(tmp_path):
    checker = load_checker()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"
    report = {
        "generated_at": "2026-08-30T12:00:00+00:00",
        "final_status": "BLOCKED",
        "backend_full_sha": "a" * 40,
        "frontend_full_sha": "b" * 40,
        "totals": {"PASS": 1, "FAIL": 0, "BLOCKED": 1, "SKIP": 0},
        "checks": [
            {"name": "marketing.landing_pages.count", "status": "PASS", "detail": "20 landing pages found"},
            {"name": "release.lock.verified", "status": "BLOCKED", "detail": "release lock status=UNVERIFIED"},
        ],
    }
    output = tmp_path / "production-launch-evidence-2026-08-30.json"

    checker.write_evidence_file(output, report, "unit test", frontend_root)

    payload = checker.load_json(output)
    assert payload["status"] == "BLOCKED"
    assert payload["source_sha"] == "a" * 40
    assert payload["metadata"]["deployment_permitted"] is False
    assert payload["metadata"]["checks"]["RELEASE_LOCK_VERIFIED"] == "BLOCKED"
    assert payload["metadata"]["blockers"][0]["name"] == "release.lock.verified"
