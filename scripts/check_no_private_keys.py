from __future__ import annotations

import subprocess
from pathlib import Path


PRIVATE_KEY_KINDS = (
    "PRIVATE KEY",
    "ENCRYPTED PRIVATE KEY",
    "RSA PRIVATE KEY",
    "EC PRIVATE KEY",
    "DSA PRIVATE KEY",
    "OPENSSH PRIVATE KEY",
    "PGP PRIVATE KEY BLOCK",
)


def private_key_markers() -> tuple[str, ...]:
    return tuple(f"-----BEGIN {kind}-----" for kind in PRIVATE_KEY_KINDS)


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
    markers = private_key_markers()
    for path in tracked_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for marker in markers:
            if marker in content:
                findings.append(f"{path}: contains a private-key block")

    if findings:
        print("Private-key material must never be committed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("No PEM/OpenSSH/PGP private-key blocks found in tracked text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
