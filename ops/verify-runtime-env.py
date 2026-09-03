#!/usr/bin/env python3
"""Verify the reviewed MoneyBee staging environment before container startup."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path

KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
FALSE_VALUES = {"false", "0", "no", "off"}

REQUIRED_EXACT = {
    "APP_ENV": "staging",
    "AUTO_CREATE_SCHEMA": "false",
    "LOCAL_AUTH_BYPASS": "false",
    "LOCAL_IDENTITY_ENFORCEMENT": "true",
    "OIDC_ISSUER": "https://auth.codestra.co/realms/codestra",
    "OIDC_AUDIENCE": "moneybee-api",
    "OIDC_ALGORITHMS_CSV": "RS256",
    "MIDDLEWARE_PROVIDER": "disabled",
    "BANK_PROVIDER": "disabled",
    "CRM_PROVIDER": "disabled",
    "KYB_PROVIDER": "disabled",
    "CREDIT_PROVIDER": "disabled",
    "LENDER_PROVIDER": "disabled",
    "ESIGN_PROVIDER": "disabled",
    "EMAIL_PROVIDER": "disabled",
    "SMS_PROVIDER": "disabled",
    "OBJECT_STORAGE_MODE": "disabled",
    "PAYMENT_PROVIDER": "disabled",
    "MALWARE_SCAN_PROVIDER": "disabled",
}
OPTIONAL_FALSE = {
    "ENABLE_EXTERNAL_DELIVERY",
    "CODESTRA_SDK_ENABLED",
    "LIVE_WRITES",
    "ODOO_WRITE",
    "N8N_DELIVERY_ENABLED",
    "CREDIT_LIVE_PULL",
    "LENDERS_LIVE_SUBMISSION",
    "ESIGN_LIVE_SEND",
    "FUNDING_LIVE_CONFIRMATION",
    "PAYMENTS_ENABLED",
    "PAYOUTS_ENABLED",
    "COMMUNICATIONS_LIVE_EMAIL",
    "COMMUNICATIONS_LIVE_SMS",
}
EXPECTED_CORS = {
    "https://staging.moneybeeloan.com",
    "https://app-staging.moneybeeloan.com",
    "https://lenders-staging.moneybeeloan.com",
    "https://admin-staging.moneybeeloan.com",
}


class ValidationError(ValueError):
    pass


def parse_env(path: Path) -> dict[str, str]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ValidationError(f"{path}: {exc}") from exc
    if mode & 0o077:
        raise ValidationError(f"{path} must not be readable or writable by group/other")

    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            raise ValidationError(f"{path}:{number}: export syntax is forbidden")
        if "=" not in line:
            raise ValidationError(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not KEY.fullmatch(key):
            raise ValidationError(f"{path}:{number}: invalid key {key!r}")
        if key in values:
            raise ValidationError(f"{path}:{number}: duplicate key {key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValidationError(f"{path}:{number}: invalid control character")
        if "${" in value or "$(" in value or "`" in value:
            raise ValidationError(f"{path}:{number}: runtime expansion is forbidden")
        values[key] = value
    return values


def require_false(values: dict[str, str], key: str) -> None:
    value = values.get(key)
    if value is not None and value.lower() not in FALSE_VALUES:
        raise ValidationError(f"{key} must remain false/disabled in initial staging")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--release-lock", type=Path, required=True)
    args = parser.parse_args()

    try:
        values = parse_env(args.env_file)
        lock = json.loads(args.release_lock.read_text(encoding="utf-8"))

        for key, expected in REQUIRED_EXACT.items():
            actual = values.get(key)
            if actual != expected:
                raise ValidationError(f"{key} must equal {expected!r}, got {actual!r}")

        for key in OPTIONAL_FALSE:
            require_false(values, key)

        database_url = values.get("DATABASE_URL", "")
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValidationError("DATABASE_URL must use postgresql+asyncpg")
        if any(token in database_url for token in ("localhost", "127.0.0.1", "sqlite")):
            raise ValidationError("DATABASE_URL may not use localhost or SQLite in staging")

        redis_url = values.get("REDIS_URL", "")
        if not redis_url.startswith(("redis://", "rediss://")):
            raise ValidationError("REDIS_URL must use redis:// or rediss://")
        if any(token in redis_url for token in ("localhost", "127.0.0.1")):
            raise ValidationError("REDIS_URL may not use localhost in staging")

        cors = {
            item.strip()
            for item in values.get("CORS_ORIGINS_CSV", "").split(",")
            if item.strip()
        }
        if cors != EXPECTED_CORS:
            raise ValidationError(
                "CORS_ORIGINS_CSV must exactly match the reviewed staging origins"
            )

        source = lock.get("source", {})
        images = lock.get("images", {})
        evidence_pairs = {
            "SOURCE_SHA": source.get("backend_sha"),
            "API_IMAGE_DIGEST": images.get("api"),
            "MIGRATION_HEAD": lock.get("migration_head"),
            "CONFIGURATION_CHECKSUM": lock.get("configuration_checksum"),
            "BACKUP_REFERENCE": lock.get("backup_reference"),
        }
        for key, expected in evidence_pairs.items():
            if values.get(key) != expected:
                raise ValidationError(f"{key} does not match the reviewed release lock")

        if values.get("BACKUP_STATUS") != "PASS":
            raise ValidationError("BACKUP_STATUS must be PASS")
        if values.get("RESTORE_STATUS") != "PASS":
            raise ValidationError("RESTORE_STATUS must be PASS")
        if values.get("STAGING_STATUS") not in {"NOT_CONFIGURED", "FAIL"}:
            raise ValidationError("STAGING_STATUS must not claim PASS before deployment")

        if not values.get("FIELD_ENCRYPTION_KEYS_JSON") or values.get("FIELD_ENCRYPTION_KEYS_JSON") == "{}":
            raise ValidationError("FIELD_ENCRYPTION_KEYS_JSON must be configured outside Git")
        if values.get("FIELD_ENCRYPTION_KEYS_JSON", "").startswith(("CHANGE_", "example", "test")):
            raise ValidationError("FIELD_ENCRYPTION_KEYS_JSON appears to be a placeholder")
        if not values.get("FIELD_ENCRYPTION_ACTIVE_KEY_VERSION"):
            raise ValidationError("FIELD_ENCRYPTION_ACTIVE_KEY_VERSION must be configured outside Git")
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "environment": "staging",
                "authentication_fail_closed": True,
                "external_providers_disabled": True,
                "cors_origins_verified": True,
                "release_evidence_bound": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
