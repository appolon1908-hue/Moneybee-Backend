#!/usr/bin/env python3
"""Compute the reviewed MoneyBee deployment configuration checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
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


def git_blob_digest(repo_root: Path, relative_path: str, ref: str = "HEAD") -> str:
    try:
        data = subprocess.check_output(
            ["git", "-C", str(repo_root), "show", f"{ref}:{relative_path}"],
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        message = detail.decode("utf-8", errors="replace").strip() if detail else str(exc)
        raise ChecksumError(f"{repo_root}:{ref}:{relative_path}: {message}") from exc
    return hashlib.sha256(data).hexdigest()


def configuration_manifest(frontend_root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for relative in BACKEND_FILES:
        entries.append(
            {
                "scope": "backend",
                "path": relative,
                "source": "git_blob",
                "ref": "HEAD",
                "sha256": git_blob_digest(BACKEND_ROOT, relative),
            }
        )
    for relative in FRONTEND_FILES:
        entries.append(
            {
                "scope": "frontend",
                "path": relative,
                "source": "git_blob",
                "ref": "HEAD",
                "sha256": git_blob_digest(frontend_root, relative),
            }
        )
    return entries


def configuration_checksum(entries: list[dict[str, str]]) -> str:
    return hashlib.sha256(canonical_lines(entries).encode("utf-8")).hexdigest()


def canonical_lines(entries: list[dict[str, str]]) -> str:
    return "\n".join(
        f"{entry['scope']}/{entry['path']}  {entry['sha256']}" for entry in entries
    )


def git_sha(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def git_dirty(path: Path) -> bool:
    try:
        status = subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(status.strip())


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
        "backend_sha": git_sha(BACKEND_ROOT),
        "frontend_sha": git_sha(args.frontend_root),
        "backend_dirty": git_dirty(BACKEND_ROOT),
        "frontend_dirty": git_dirty(args.frontend_root),
        "configuration_checksum": checksum,
        "canonical": canonical_lines(entries),
        "files": entries,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
