#!/usr/bin/env python3
"""Render a shell-safe Compose environment from reviewed MoneyBee lock files."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def emit(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is missing")
    print(f"{name}={shlex.quote(value)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--release-lock", type=Path, required=True)
    args = parser.parse_args()

    runtime = load(args.runtime_lock)
    release = load(args.release_lock)
    images = release["images"]
    paths = runtime["paths"]
    urls = release["urls"]
    networks = runtime["networks"]

    emit(
        "MONEYBEE_POSTGRES_ADMIN_USER",
        runtime.get("postgres_admin_user", "moneybee_admin"),
    )

    for key, env_name in {
        "api": "MONEYBEE_API_IMAGE",
        "worker": "MONEYBEE_WORKER_IMAGE",
        "migrate": "MONEYBEE_MIGRATE_IMAGE",
        "marketing": "MONEYBEE_MARKETING_IMAGE",
        "borrower": "MONEYBEE_BORROWER_IMAGE",
        "lender": "MONEYBEE_LENDER_IMAGE",
        "admin": "MONEYBEE_ADMIN_IMAGE",
        "postgres": "MONEYBEE_POSTGRES_IMAGE",
        "redis": "MONEYBEE_REDIS_IMAGE",
        "caddy": "MONEYBEE_CADDY_IMAGE",
        "clamav": "MONEYBEE_CLAMAV_IMAGE",
    }.items():
        emit(env_name, images[key])

    for key, env_name in {
        "migrator_env_file": "MONEYBEE_MIGRATOR_ENV_FILE",
        "runtime_env_file": "MONEYBEE_RUNTIME_ENV_FILE",
        "postgres_data_path": "MONEYBEE_POSTGRES_DATA_PATH",
        "redis_data_path": "MONEYBEE_REDIS_DATA_PATH",
        "postgres_admin_password_file": "MONEYBEE_POSTGRES_ADMIN_PASSWORD_FILE",
        "postgres_migrator_password_file": "MONEYBEE_POSTGRES_MIGRATOR_PASSWORD_FILE",
        "postgres_runtime_password_file": "MONEYBEE_POSTGRES_RUNTIME_PASSWORD_FILE",
        "roles_sql_path": "MONEYBEE_ROLES_SQL_PATH",
        "redis_acl_file": "MONEYBEE_REDIS_ACL_FILE",
        "clamav_database_path": "MONEYBEE_CLAMAV_DATABASE_PATH",
        "caddy_data_path": "MONEYBEE_CADDY_DATA_PATH",
        "caddy_config_path": "MONEYBEE_CADDY_CONFIG_PATH",
    }.items():
        if runtime["data_mode"] == "external" and key in {
            "postgres_data_path",
            "redis_data_path",
            "postgres_admin_password_file",
            "postgres_migrator_password_file",
            "postgres_runtime_password_file",
            "roles_sql_path",
            "redis_acl_file",
        }:
            continue
        emit(env_name, paths[key])

    emit("MONEYBEE_INTERNAL_NETWORK", networks["internal"])
    emit("MONEYBEE_EDGE_NETWORK", networks["edge"])
    emit("CADDY_ACME_EMAIL", release["caddy_acme_email"])
    emit("MONEYBEE_TRUSTED_PROXY_CIDRS_CSV", release["trusted_proxy_cidrs_csv"])
    for key, env_name in {
        "marketing": "MONEYBEE_MARKETING_HOST",
        "borrower": "MONEYBEE_BORROWER_HOST",
        "lender": "MONEYBEE_LENDER_HOST",
        "admin": "MONEYBEE_ADMIN_HOST",
        "api": "MONEYBEE_API_HOST",
    }.items():
        emit(env_name, urls[key].split("://", 1)[-1].rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
