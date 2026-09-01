#!/usr/bin/env python3
"""Verify Compose, lock files, and the environment renderer share one contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = sorted((ROOT / "deploy").glob("compose.*.yml"))
VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
IMAGE_VARIABLES = {
    "MONEYBEE_API_IMAGE",
    "MONEYBEE_WORKER_IMAGE",
    "MONEYBEE_MIGRATE_IMAGE",
    "MONEYBEE_POSTGRES_IMAGE",
    "MONEYBEE_REDIS_IMAGE",
    "MONEYBEE_CADDY_IMAGE",
    "MONEYBEE_CLAMAV_IMAGE",
}


def main() -> int:
    release_dockerfile = (ROOT / "docker" / "Dockerfile.release").read_text(encoding="utf-8")
    if "--forwarded-allow-ips=*" in release_dockerfile or "--no-proxy-headers" not in release_dockerfile:
        raise SystemExit("Uvicorn must leave forwarded-header trust to the application proxy policy")
    consumed: set[str] = set()
    for path in COMPOSE_FILES:
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*build\s*:", text, re.MULTILINE):
            raise SystemExit(f"{path}: server-side source build is forbidden")
        consumed.update(VARIABLE.findall(text))

    zero = "0" * 64
    runtime = {
        "data_mode": "compose",
        "paths": {
            "migrator_env_file": "/fixture/migrator.env",
            "runtime_env_file": "/fixture/runtime.env",
            "postgres_data_path": "/fixture/postgres",
            "redis_data_path": "/fixture/redis",
            "postgres_admin_password_file": "/fixture/postgres-admin-password",
            "postgres_migrator_password_file": "/fixture/postgres-migrator-password",
            "postgres_runtime_password_file": "/fixture/postgres-runtime-password",
            "roles_sql_path": "/fixture/moneybee_roles.sql",
            "redis_acl_file": "/fixture/redis.acl",
            "clamav_database_path": "/fixture/clamav",
            "caddy_data_path": "/fixture/caddy-data",
            "caddy_config_path": "/fixture/caddy-config",
        },
        "networks": {"internal": "fixture-internal", "edge": "fixture-edge"},
    }
    image_keys = (
        "api", "worker", "migrate", "marketing", "borrower", "lender", "admin",
        "postgres", "redis", "caddy", "clamav",
    )
    release = {
        "images": {key: f"fixture/{key}@sha256:{zero}" for key in image_keys},
        "urls": {
            key: f"https://{key}.example.invalid"
            for key in ("marketing", "borrower", "lender", "admin", "api")
        },
        "caddy_acme_email": "ci@example.invalid",
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime_path = root / "runtime.json"
        release_path = root / "release.json"
        runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
        release_path.write_text(json.dumps(release), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "ops" / "render-compose-env.py"),
                "--runtime-lock", str(runtime_path),
                "--release-lock", str(release_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    emitted = {line.split("=", 1)[0] for line in result.stdout.splitlines() if "=" in line}
    stale = emitted - consumed
    missing = consumed - emitted
    if stale or missing:
        raise SystemExit(
            f"Compose environment contract mismatch: missing={sorted(missing)} stale={sorted(stale)}"
        )
    if not IMAGE_VARIABLES <= emitted:
        raise SystemExit("Not every release image is represented in the renderer")
    if runtime["paths"]["migrator_env_file"] == runtime["paths"]["runtime_env_file"]:
        raise SystemExit("Migration and runtime environments must be separate")
    print(json.dumps({"compose_files": len(COMPOSE_FILES), "variables": len(consumed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
