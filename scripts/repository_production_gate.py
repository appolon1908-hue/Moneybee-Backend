#!/usr/bin/env python3
"""Fail-closed validation of the non-secret production release contract."""

from __future__ import annotations

import json
import os


PASS_EVIDENCE = (
    "BACKUP_STATUS",
    "PITR_STATUS",
    "OFFHOST_BACKUP_STATUS",
    "RESTORE_STATUS",
    "REDIS_RECOVERY_STATUS",
    "APPLICATION_RESTORE_STATUS",
    "DOCUMENT_SECURITY_STATUS",
    "PII_SECURITY_STATUS",
    "CONCURRENCY_STATUS",
)


def validate(values: dict[str, str]) -> list[str]:
    failures: list[str] = []
    if values.get("APP_ENV") != "production":
        failures.append("APP_ENV must be production")
    role = values.get("DATABASE_RUNTIME_ROLE", "")
    if role != "moneybee_runtime" or any(word in role.lower() for word in ("admin", "migrator")):
        failures.append("DATABASE_RUNTIME_ROLE must be moneybee_runtime")
    if values.get("RATE_LIMIT_BACKEND") != "redis":
        failures.append("RATE_LIMIT_BACKEND must be redis")
    if values.get("TRUST_FORWARDED_FOR", "").lower() == "true" and not values.get(
        "TRUSTED_PROXY_CIDRS_CSV"
    ):
        failures.append("trusted proxy CIDRs are required")
    if not values.get("MIGRATION_HEAD"):
        failures.append("MIGRATION_HEAD evidence is required")
    for name in PASS_EVIDENCE:
        if values.get(name) != "PASS":
            failures.append(f"{name} must be PASS")
    return failures


def main() -> int:
    failures = validate(dict(os.environ))
    print(json.dumps({"status": "PASS" if not failures else "FAIL", "failures": failures}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
