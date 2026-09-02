"""Generate or verify the additive OpenAPI manifest for contract readbacks."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


TARGET = ROOT / "docs" / "openapi" / "contract-read-completion-manifest.json"
PATHS = (
    "/api/v2/me/permissions",
    "/api/v2/public/products",
    "/api/v2/applications/{application_id}/status",
    "/api/v2/offers/{offer_id}",
)
SCHEMAS = (
    "EffectivePermissionsRead",
    "PublicProductRead",
    "ApplicationStatusRead",
)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render() -> str:
    document = app.openapi()
    runtime_paths = document.get("paths", {})
    runtime_schemas = document.get("components", {}).get("schemas", {})

    missing_paths = [path for path in PATHS if path not in runtime_paths]
    missing_schemas = [name for name in SCHEMAS if name not in runtime_schemas]
    if missing_paths or missing_schemas:
        raise SystemExit(
            "Contract completion surface is incomplete: "
            f"paths={missing_paths}, schemas={missing_schemas}"
        )

    manifest = {
        "name": "contract-read-completion",
        "paths": {path: _digest(runtime_paths[path]) for path in PATHS},
        "schemas": {name: _digest(runtime_schemas[name]) for name in SCHEMAS},
        "version": 1,
    }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()

    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"Contract read manifest drift detected: {TARGET}")
        print("Contract read manifest verified")
        return

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
