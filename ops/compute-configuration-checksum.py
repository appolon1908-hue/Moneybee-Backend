#!/usr/bin/env python3
"""Compute the reviewed MoneyBee deployment configuration checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_ROOT = BACKEND_ROOT.parent / "Moneybee-frontend-"
BACKEND_FILES = (
    "deploy/Caddyfile.staging",
    "deploy/compose.backend.yml",
    "deploy/compose.data.yml",
    "deploy/compose.edge.yml",
)
FRONTEND_FILES = ("deploy/compose.frontend.yml",)


class ChecksumError(ValueError):
    pass


def file_digest(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ChecksumError(f"{path}: {exc}") from exc
    return hashlib.sha256(data).hexdigest()


def configuration_manifest(frontend_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for relative in BACKEND_FILES:
        path = BACKEND_ROOT / relative
        entries.append({"scope": "backend", "path": relative, "sha256": file_digest(path)})
    for relative in FRONTEND_FILES:
        path = frontend_root / relative
        entries.append({"scope": "frontend", "path": relative, "sha256": file_digest(path)})
    return entries


def configuration_checksum(entries: list[dict[str, str]]) -> str:
    canonical = "\n".join(
        f"{entry['scope']}/{entry['path']}  {entry['sha256']}" for entry in entries
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-root", type=Path, default=DEFAULT_FRONTEND_ROOT)
    parser.add_argument("--expect", help="Expected configuration checksum")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = configuration_manifest(args.frontend_root)
        checksum = configuration_checksum(entries)
        if args.expect and checksum != args.expect:
            raise ChecksumError(
                f"configuration checksum mismatch: expected={args.expect} actual={checksum}"
            )
    except ChecksumError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    payload = {
        "schema_version": 1,
        "configuration_checksum": checksum,
        "files": entries,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
