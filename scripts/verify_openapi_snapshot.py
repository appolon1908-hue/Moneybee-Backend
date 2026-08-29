import hashlib
from pathlib import Path

SNAPSHOT_SHA256 = Path("contracts/openapi.snapshot.sha256")
GENERATED = Path("openapi.json")

expected_sha256 = SNAPSHOT_SHA256.read_text(encoding="utf-8").strip().lower()
actual = GENERATED.read_bytes()
actual_sha256 = hashlib.sha256(actual).hexdigest()

if len(expected_sha256) != 64 or any(char not in "0123456789abcdef" for char in expected_sha256):
    raise SystemExit("OpenAPI snapshot pin is not a valid SHA-256 digest.")

if actual_sha256 != expected_sha256:
    raise SystemExit(
        "OpenAPI snapshot mismatch: "
        f"generated={len(actual)} bytes sha256={actual_sha256} "
        f"expected_sha256={expected_sha256}. "
        "Regenerate and review the OpenAPI contract before updating the snapshot pin."
    )

print(
    "OPENAPI_SNAPSHOT=PASS "
    f"bytes={len(actual)} sha256={actual_sha256}"
)
