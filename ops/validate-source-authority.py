#!/usr/bin/env python3
"""Validate MoneyBee repository authority before server contact or deployment."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGET_HOST = "49.12.145.107"
BACKEND_REPOSITORY = "appolon1908-hue/Moneybee-Backend"
FRONTEND_REPOSITORY = "appolon1908-hue/Moneybee-frontend-"
SHA40 = re.compile(r"^[0-9a-f]{40}$")

V1_REQUIRED_BEFORE_DEPLOYMENT = (
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
V1_SERVER_CONTACT_PREREQUISITES = V1_REQUIRED_BEFORE_DEPLOYMENT[:12]

V2_REQUIRED_BEFORE_DEPLOYMENT = (
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
V2_SERVER_CONTACT_PREREQUISITES = V2_REQUIRED_BEFORE_DEPLOYMENT[:11]


class AuthorityError(ValueError):
    """Raised when repository authority is missing or malformed."""


def load_lock(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuthorityError(f"{path}: top-level JSON value must be an object")
    return value


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorityError(f"{field} must be an object")
    return value


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise AuthorityError(f"{field} must be a boolean")
    return value


def require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuthorityError(f"{field} must be an integer")
    return value


def require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise AuthorityError(f"{field} must be an exact lowercase 40-character SHA")
    return value


def require_sha_or_null(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return require_sha(value, field)


def require_pass_result(value: Any, field: str) -> None:
    result = require_object(value, field)
    require_int(result.get("run_id"), f"{field}.run_id")
    if result.get("result") != "PASS":
        raise AuthorityError(f"{field}.result must be PASS")


def validate_required_flags(
    lock: dict[str, Any], required_fields: tuple[str, ...]
) -> dict[str, Any]:
    required = require_object(
        lock.get("required_before_deployment"), "required_before_deployment"
    )
    missing = [key for key in required_fields if key not in required]
    if missing:
        raise AuthorityError(
            "required_before_deployment is missing: " + ", ".join(sorted(missing))
        )
    for key in required_fields:
        require_bool(required[key], f"required_before_deployment.{key}")
    return required


def validate_v1_sources(
    backend: dict[str, Any], frontend: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    backend_merge_sha = require_sha_or_null(
        backend.get("required_final_merge_sha"), "backend.required_final_merge_sha"
    )
    frontend_merge_sha = require_sha_or_null(
        frontend.get("required_final_merge_sha"), "frontend.required_final_merge_sha"
    )
    frontend_contract_sha = require_sha_or_null(
        frontend.get("required_final_backend_contract_sha"),
        "frontend.required_final_backend_contract_sha",
    )
    return backend_merge_sha, frontend_merge_sha, frontend_contract_sha


def validate_v2_sources(
    backend: dict[str, Any], frontend: dict[str, Any]
) -> tuple[str, str, str]:
    require_sha(backend.get("protected_source_head"), "backend.protected_source_head")
    require_sha(frontend.get("protected_source_head"), "frontend.protected_source_head")
    backend_merge_sha = require_sha(
        backend.get("protected_merge_sha"), "backend.protected_merge_sha"
    )
    frontend_merge_sha = require_sha(
        frontend.get("protected_merge_sha"), "frontend.protected_merge_sha"
    )
    frontend_contract_sha = require_sha(
        frontend.get("protected_backend_contract_sha"),
        "frontend.protected_backend_contract_sha",
    )
    require_pass_result(backend.get("exact_head_ci", {}).get("backend_ci"), "backend.exact_head_ci.backend_ci")
    require_pass_result(
        backend.get("exact_head_ci", {}).get("secure_scaffold_ci"),
        "backend.exact_head_ci.secure_scaffold_ci",
    )
    require_pass_result(frontend.get("exact_head_ci"), "frontend.exact_head_ci")
    if backend.get("review_threads_unresolved") != 0:
        raise AuthorityError("backend.review_threads_unresolved must be 0")
    if frontend.get("review_threads_unresolved") != 0:
        raise AuthorityError("frontend.review_threads_unresolved must be 0")
    return backend_merge_sha, frontend_merge_sha, frontend_contract_sha


def validate_schema(lock: dict[str, Any]) -> dict[str, Any]:
    schema_version = lock.get("schema_version")
    if schema_version not in {1, 2}:
        raise AuthorityError("schema_version must be 1 or 2")

    target = require_object(lock.get("target"), "target")
    if target.get("host") != TARGET_HOST:
        raise AuthorityError(f"target.host must be {TARGET_HOST}")

    backend = require_object(lock.get("backend"), "backend")
    frontend = require_object(lock.get("frontend"), "frontend")
    if backend.get("repository") != BACKEND_REPOSITORY:
        raise AuthorityError(f"backend.repository must be {BACKEND_REPOSITORY}")
    if frontend.get("repository") != FRONTEND_REPOSITORY:
        raise AuthorityError(f"frontend.repository must be {FRONTEND_REPOSITORY}")

    server_contact_authorized = require_bool(
        lock.get("server_contact_authorized"), "server_contact_authorized"
    )
    deployment_authorized = require_bool(
        lock.get("deployment_authorized"), "deployment_authorized"
    )
    if deployment_authorized and not server_contact_authorized:
        raise AuthorityError(
            "deployment_authorized cannot be true while server_contact_authorized is false"
        )

    if schema_version == 1:
        required_fields = V1_REQUIRED_BEFORE_DEPLOYMENT
        contact_fields = V1_SERVER_CONTACT_PREREQUISITES
        source_shas = validate_v1_sources(backend, frontend)
    else:
        required_fields = V2_REQUIRED_BEFORE_DEPLOYMENT
        contact_fields = V2_SERVER_CONTACT_PREREQUISITES
        source_shas = validate_v2_sources(backend, frontend)

    required = validate_required_flags(lock, required_fields)
    backend_merge_sha, frontend_merge_sha, frontend_contract_sha = source_shas

    return {
        "schema_version": schema_version,
        "server_contact_authorized": server_contact_authorized,
        "deployment_authorized": deployment_authorized,
        "required": required,
        "required_fields": required_fields,
        "contact_fields": contact_fields,
        "backend_merge_sha": backend_merge_sha,
        "frontend_merge_sha": frontend_merge_sha,
        "frontend_contract_sha": frontend_contract_sha,
    }


def require_prerequisites(required: dict[str, Any], fields: tuple[str, ...]) -> None:
    blocked = [field for field in fields if required.get(field) is not True]
    if blocked:
        raise AuthorityError("prerequisites are not verified: " + ", ".join(blocked))


def validate_operation(lock: dict[str, Any], operation: str) -> dict[str, Any]:
    state = validate_schema(lock)
    if operation == "schema":
        return state

    if state["server_contact_authorized"] is not True:
        raise AuthorityError("server_contact_authorized is not true")
    require_prerequisites(state["required"], state["contact_fields"])

    backend_merge_sha = state["backend_merge_sha"]
    frontend_merge_sha = state["frontend_merge_sha"]
    frontend_contract_sha = state["frontend_contract_sha"]
    if backend_merge_sha is None:
        raise AuthorityError("backend protected merge SHA is not recorded")
    if frontend_merge_sha is None:
        raise AuthorityError("frontend protected merge SHA is not recorded")
    if frontend_contract_sha != backend_merge_sha:
        raise AuthorityError(
            "frontend protected backend contract SHA must equal backend protected merge SHA"
        )

    if operation == "deployment":
        if state["deployment_authorized"] is not True:
            raise AuthorityError("deployment_authorized is not true")
        require_prerequisites(state["required"], state["required_fields"])

    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument(
        "--operation",
        choices=("schema", "server-contact", "deployment"),
        required=True,
    )
    args = parser.parse_args()

    try:
        lock = load_lock(args.source_lock)
        state = validate_operation(lock, args.operation)
    except AuthorityError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    authority_permitted = args.operation == "schema" or (
        state["server_contact_authorized"]
        and (args.operation != "deployment" or state["deployment_authorized"])
    )
    print(
        json.dumps(
            {
                "schema_version": state["schema_version"],
                "operation": args.operation,
                "target_host": TARGET_HOST,
                "server_contact_authorized": state["server_contact_authorized"],
                "deployment_authorized": state["deployment_authorized"],
                "authority_permitted": authority_permitted,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
