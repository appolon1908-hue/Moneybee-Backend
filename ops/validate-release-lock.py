#!/usr/bin/env python3
"""Fail-closed validation for MoneyBee staging runtime and release locks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGET_HOST = "49.12.145.107"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GHCR_IMAGE = re.compile(
    r"^ghcr\.io/appolon1908-hue/[a-z0-9._-]+@sha256:[0-9a-f]{64}$"
)

REQUIRED_IMAGES = {
    "api": "moneybee-api",
    "worker": "moneybee-worker",
    "migrate": "moneybee-migrate",
    "marketing": "moneybee-marketing",
    "borrower": "moneybee-borrower",
    "lender": "moneybee-lender",
    "admin": "moneybee-admin",
}
INFRA_IMAGES = {"postgres", "redis", "caddy"}
REQUIRED_PATHS = {
    "release_root",
    "current_symlink",
    "backend_env_file",
    "caddy_data_path",
    "caddy_config_path",
    "backup_root",
}
COMPOSE_DATA_PATHS = {
    "postgres_data_path",
    "redis_data_path",
    "postgres_password_file",
    "redis_acl_file",
    "moneybee_migrator_password_file",
    "moneybee_app_password_file",
}


class ValidationError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: top-level JSON value must be an object")
    return value


def absolute_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        raise ValidationError(f"{field} must be an absolute path")
    if any(part in {".", ".."} for part in value.split("/")[1:]):
        raise ValidationError(f"{field} contains an unsafe path component")
    return value


def validate_runtime(lock: dict[str, Any], *, allow_unverified: bool) -> None:
    if lock.get("schema_version") != 1:
        raise ValidationError("runtime lock schema_version must be 1")
    if lock.get("target_host") != TARGET_HOST:
        raise ValidationError(f"runtime target_host must be {TARGET_HOST}")
    status = lock.get("status")
    if status not in {"UNVERIFIED", "VERIFIED"}:
        raise ValidationError("runtime status must be UNVERIFIED or VERIFIED")
    if not allow_unverified and status != "VERIFIED":
        raise ValidationError("runtime paths are not VERIFIED")
    data_mode = lock.get("data_mode")
    if status == "VERIFIED" and data_mode not in {"external", "compose"}:
        raise ValidationError("verified runtime data_mode must be external or compose")
    paths = lock.get("paths")
    if not isinstance(paths, dict):
        raise ValidationError("runtime paths must be an object")
    if status == "VERIFIED":
        hostname = lock.get("verified_hostname")
        if (
            not isinstance(hostname, str)
            or not hostname.strip()
            or len(hostname) > 253
            or any(char.isspace() for char in hostname)
        ):
            raise ValidationError("verified_hostname must be a reviewed DNS-style hostname")
        for key in REQUIRED_PATHS:
            absolute_path(paths.get(key), f"paths.{key}")
        if data_mode == "compose":
            for key in COMPOSE_DATA_PATHS:
                absolute_path(paths.get(key), f"paths.{key}")
        evidence = lock.get("evidence_sha256")
        if not isinstance(evidence, str) or not SHA256.fullmatch(evidence):
            raise ValidationError(
                "verified runtime evidence_sha256 must be 64 lowercase hex characters"
            )


def validate_release(lock: dict[str, Any], *, allow_unverified: bool) -> None:
    if lock.get("schema_version") != 1:
        raise ValidationError("release lock schema_version must be 1")
    if lock.get("target_environment") != "staging":
        raise ValidationError("only the staging target is supported")
    if lock.get("target_host") != TARGET_HOST:
        raise ValidationError(f"release target_host must be {TARGET_HOST}")
    status = lock.get("status")
    if status not in {"UNVERIFIED", "VERIFIED"}:
        raise ValidationError("release status must be UNVERIFIED or VERIFIED")
    if not allow_unverified and status != "VERIFIED":
        raise ValidationError("release lock is not VERIFIED")

    source = lock.get("source")
    if not isinstance(source, dict):
        raise ValidationError("release source must be an object")
    if source.get("backend_repository") != "appolon1908-hue/Moneybee-Backend":
        raise ValidationError("unexpected backend repository")
    if source.get("frontend_repository") != "appolon1908-hue/Moneybee-frontend-":
        raise ValidationError("unexpected frontend repository")

    images = lock.get("images")
    if not isinstance(images, dict):
        raise ValidationError("release images must be an object")

    capabilities = lock.get("capabilities")
    if not isinstance(capabilities, dict) or any(
        value is not False for value in capabilities.values()
    ):
        raise ValidationError("all staging capability-freeze values must be false")

    if status == "VERIFIED":
        for field in ("backend_sha", "frontend_sha"):
            value = source.get(field)
            if not isinstance(value, str) or not SHA40.fullmatch(value):
                raise ValidationError(f"source.{field} must be an exact 40-character SHA")

        for key, expected_name in REQUIRED_IMAGES.items():
            value = images.get(key)
            if not isinstance(value, str) or not GHCR_IMAGE.fullmatch(value):
                raise ValidationError(f"images.{key} must be an immutable GHCR digest")
            if f"/{expected_name}@sha256:" not in value:
                raise ValidationError(f"images.{key} must reference {expected_name}")

        for key in INFRA_IMAGES:
            value = images.get(key)
            if (
                not isinstance(value, str)
                or "@sha256:" not in value
                or not SHA256.fullmatch(value.rsplit("@sha256:", 1)[1])
            ):
                raise ValidationError(f"images.{key} must be digest pinned")

        acme_email = lock.get("caddy_acme_email")
        if (
            not isinstance(acme_email, str)
            or "@" not in acme_email
            or len(acme_email) > 320
        ):
            raise ValidationError("caddy_acme_email is required for a verified release")

        for key in ("runtime_paths_evidence_sha256", "configuration_checksum"):
            value = lock.get(key)
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ValidationError(f"{key} must be 64 lowercase hex characters")

        if not isinstance(lock.get("backup_reference"), str) or not lock["backup_reference"]:
            raise ValidationError("backup_reference is required for a verified release")
        if lock.get("backup_restore_tested") is not True:
            raise ValidationError("backup_restore_tested must be true for a verified release")
        if not isinstance(lock.get("migration_head"), str) or not lock["migration_head"]:
            raise ValidationError("migration_head is required for a verified release")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--release-lock", type=Path, required=True)
    parser.add_argument("--allow-unverified", action="store_true")
    args = parser.parse_args()

    try:
        runtime = load(args.runtime_lock)
        release = load(args.release_lock)
        validate_runtime(runtime, allow_unverified=args.allow_unverified)
        validate_release(release, allow_unverified=args.allow_unverified)
        if release.get("status") == "VERIFIED" and runtime.get("status") == "VERIFIED":
            if (
                release.get("runtime_paths_evidence_sha256")
                != runtime.get("evidence_sha256")
            ):
                raise ValidationError(
                    "release lock does not bind the reviewed runtime-path evidence"
                )
    except ValidationError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "runtime_status": runtime.get("status"),
                "release_status": release.get("status"),
                "target_host": TARGET_HOST,
                "deployment_permitted": (
                    runtime.get("status") == release.get("status") == "VERIFIED"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
