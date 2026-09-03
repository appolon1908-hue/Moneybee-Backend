from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "validate-source-authority.py"
SOURCE_LOCK = ROOT / "deploy" / "repository-source.lock.json"

V1_REQUIRED_FIELDS = (
    "backend_codex_environment_created",
    "frontend_codex_environment_created",
    "backend_main_contains_certified_release",
    "frontend_main_contains_certified_release",
    "backend_exact_head_ci_pass",
    "frontend_exact_head_ci_pass_against_backend_merge_sha",
    "open_review_findings_zero",
    "immutable_image_digests_recorded",
    "sbom_digests_recorded",
    "provenance_digests_recorded",
    "compose_checksums_recorded",
    "configuration_checksum_recorded",
    "backup_reference_recorded",
    "restore_evidence_recorded",
    "rollback_set_recorded",
)
V2_REQUIRED_FIELDS = (
    "backend_main_contains_certified_release",
    "frontend_main_contains_certified_release",
    "backend_exact_head_ci_pass",
    "frontend_exact_head_ci_pass_against_backend_merge_sha",
    "open_review_findings_zero",
    "immutable_image_digests_recorded",
    "sbom_digests_recorded",
    "provenance_digests_recorded",
    "signed_release_evidence_recorded",
    "compose_checksums_recorded",
    "configuration_checksum_recorded",
    "backup_reference_recorded",
    "restore_evidence_recorded",
    "rollback_set_recorded",
)


def run_validator(lock: Path, operation: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-lock",
            str(lock),
            "--operation",
            operation,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def authorized_v2_lock() -> dict[str, object]:
    backend_sha = "a" * 40
    return {
        "schema_version": 2,
        "server_contact_authorized": True,
        "deployment_authorized": True,
        "target": {"host": "49.12.145.107"},
        "backend": {
            "repository": "appolon1908-hue/Moneybee-Backend",
            "protected_source_head": "c" * 40,
            "protected_merge_sha": backend_sha,
            "exact_head_ci": {
                "backend_ci": {"run_id": 1, "result": "PASS"},
                "secure_scaffold_ci": {"run_id": 2, "result": "PASS"},
            },
            "review_threads_unresolved": 0,
        },
        "frontend": {
            "repository": "appolon1908-hue/Moneybee-frontend-",
            "protected_source_head": "d" * 40,
            "protected_merge_sha": "b" * 40,
            "protected_backend_contract_sha": backend_sha,
            "exact_head_ci": {"run_id": 3, "result": "PASS"},
            "review_threads_unresolved": 0,
        },
        "required_before_deployment": {key: True for key in V2_REQUIRED_FIELDS},
    }


def legacy_v1_lock() -> dict[str, object]:
    return {
        "schema_version": 1,
        "server_contact_authorized": False,
        "deployment_authorized": False,
        "target": {"host": "49.12.145.107"},
        "backend": {
            "repository": "appolon1908-hue/Moneybee-Backend",
            "required_final_merge_sha": None,
        },
        "frontend": {
            "repository": "appolon1908-hue/Moneybee-frontend-",
            "required_final_merge_sha": None,
            "required_final_backend_contract_sha": None,
        },
        "required_before_deployment": {key: False for key in V1_REQUIRED_FIELDS},
    }


def test_current_v2_lock_is_valid_but_denies_server_contact() -> None:
    schema = run_validator(SOURCE_LOCK, "schema")
    assert schema.returncode == 0, schema.stderr
    assert '"schema_version": 2' in schema.stdout

    contact = run_validator(SOURCE_LOCK, "server-contact")
    assert contact.returncode == 1
    assert "server_contact_authorized is not true" in contact.stderr

    deployment = run_validator(SOURCE_LOCK, "deployment")
    assert deployment.returncode == 1
    assert "server_contact_authorized is not true" in deployment.stderr


def test_fully_authorized_v2_lock_allows_contact_and_deployment(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(authorized_v2_lock()), encoding="utf-8")

    contact = run_validator(lock, "server-contact")
    assert contact.returncode == 0, contact.stderr

    deployment = run_validator(lock, "deployment")
    assert deployment.returncode == 0, deployment.stderr


def test_v2_contract_sha_must_match_backend_merge_sha(tmp_path: Path) -> None:
    value = authorized_v2_lock()
    frontend = value["frontend"]
    assert isinstance(frontend, dict)
    frontend["protected_backend_contract_sha"] = "e" * 40
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(value), encoding="utf-8")

    result = run_validator(lock, "server-contact")
    assert result.returncode == 1
    assert "must equal backend protected merge SHA" in result.stderr


def test_server_contact_requires_complete_phase_02_evidence(tmp_path: Path) -> None:
    value = authorized_v2_lock()
    value["deployment_authorized"] = False
    required = value["required_before_deployment"]
    assert isinstance(required, dict)
    required["immutable_image_digests_recorded"] = False
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(value), encoding="utf-8")

    result = run_validator(lock, "server-contact")
    assert result.returncode == 1
    assert "immutable_image_digests_recorded" in result.stderr


def test_legacy_v1_schema_remains_readable(tmp_path: Path) -> None:
    lock = tmp_path / "source-lock-v1.json"
    lock.write_text(json.dumps(legacy_v1_lock()), encoding="utf-8")

    result = run_validator(lock, "schema")
    assert result.returncode == 0, result.stderr
    assert '"schema_version": 1' in result.stdout
