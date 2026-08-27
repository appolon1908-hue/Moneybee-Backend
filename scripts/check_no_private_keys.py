from __future__ import annotations

import subprocess
from pathlib import Path


PRIVATE_KEY_MARKERS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN ENCRYPTED PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        Path(value.decode("utf-8"))
        for value in result.stdout.split(b"\0")
        if value
    ]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for marker in PRIVATE_KEY_MARKERS:
            if marker in content:
                findings.append(f"{path}: contains {marker}")

    if findings:
        print("Private-key material must never be committed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("No PEM/OpenSSH/PGP private-key blocks found in tracked text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
