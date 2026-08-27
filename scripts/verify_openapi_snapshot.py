import base64
import gzip
import hashlib
from pathlib import Path

SNAPSHOT = Path("contracts/openapi.snapshot.json.gz.b64")
GENERATED = Path("openapi.json")

expected = gzip.decompress(base64.b64decode(SNAPSHOT.read_text(encoding="utf-8").strip()))
actual = GENERATED.read_bytes()

expected_sha256 = hashlib.sha256(expected).hexdigest()
actual_sha256 = hashlib.sha256(actual).hexdigest()

if actual != expected:
    raise SystemExit(
        "OpenAPI snapshot mismatch: "
        f"generated={len(actual)} bytes sha256={actual_sha256} "
        f"expected={len(expected)} bytes sha256={expected_sha256}. "
        "Regenerate and review the OpenAPI contract before updating the snapshot."
    )

print(
    "OPENAPI_SNAPSHOT=PASS "
    f"bytes={len(actual)} sha256={actual_sha256}"
)
