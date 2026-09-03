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

REQUIRED_BEFORE_DEPLOYMENT = (
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
SERVER_CONTACT_PREREQUISITES = REQUIRED_BEFORE_DEPLOYMENT[:12]


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


def require_sha_or_null(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not SHA40.fullmatch(value):
        raise AuthorityError(f"{field} must be null or an exact lowercase 40-character SHA")
    return value


def validate_schema(lock: dict[str, Any]) -> dict[str, Any]:
    if lock.get("schema_version") != 1:
        raise AuthorityError("schema_version must be 1")

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

    required = require_object(
        lock.get("required_before_deployment"), "required_before_deployment"
    )
    missing = [key for key in REQUIRED_BEFORE_DEPLOYMENT if key not in required]
    if missing:
        raise AuthorityError(
            "required_before_deployment is missing: " + ", ".join(sorted(missing))
        )
    for key in REQUIRED_BEFORE_DEPLOYMENT:
        require_bool(required[key], f"required_before_deployment.{key}")

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

    return {
        "server_contact_authorized": server_contact_authorized,
        "deployment_authorized": deployment_authorized,
        "required": required,
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
    require_prerequisites(state["required"], SERVER_CONTACT_PREREQUISITES)

    backend_merge_sha = state["backend_merge_sha"]
    frontend_merge_sha = state["frontend_merge_sha"]
    frontend_contract_sha = state["frontend_contract_sha"]
    if backend_merge_sha is None:
        raise AuthorityError("backend.required_final_merge_sha is not recorded")
    if frontend_merge_sha is None:
        raise AuthorityError("frontend.required_final_merge_sha is not recorded")
    if frontend_contract_sha != backend_merge_sha:
        raise AuthorityError(
            "frontend.required_final_backend_contract_sha must equal "
            "backend.required_final_merge_sha"
        )

    if operation == "deployment":
        if state["deployment_authorized"] is not True:
            raise AuthorityError("deployment_authorized is not true")
        require_prerequisites(state["required"], REQUIRED_BEFORE_DEPLOYMENT)

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

    print(
        json.dumps(
            {
                "operation": args.operation,
                "target_host": TARGET_HOST,
                "server_contact_authorized": state["server_contact_authorized"],
                "deployment_authorized": state["deployment_authorized"],
                "authority_permitted": args.operation == "schema"
                or (
                    state["server_contact_authorized"]
                    and (
                        args.operation != "deployment"
                        or state["deployment_authorized"]
                    )
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
