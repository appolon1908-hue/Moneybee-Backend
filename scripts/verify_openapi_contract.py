"""Verify the runtime OpenAPI document against the reviewed base and additive manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    baseline = _load(ROOT / "openapi.json")
    generated = app.openapi()

    baseline_paths = baseline.get("paths", {})
    generated_paths = generated.get("paths", {})
    baseline_schemas = baseline.get("components", {}).get("schemas", {})
    generated_schemas = generated.get("components", {}).get("schemas", {})

    for path, contract in baseline_paths.items():
        if generated_paths.get(path) != contract:
            raise SystemExit(f"OpenAPI breaking drift detected for existing path {path}")
    for name, contract in baseline_schemas.items():
        if generated_schemas.get(name) != contract:
            raise SystemExit(f"OpenAPI breaking drift detected for existing schema {name}")

    actual_paths = {
        path: _digest(contract)
        for path, contract in generated_paths.items()
        if path not in baseline_paths
    }
    actual_schemas = {
        name: _digest(contract)
        for name, contract in generated_schemas.items()
        if name not in baseline_schemas
    }

    expected_paths: dict[str, str] = {}
    expected_schemas: dict[str, str] = {}
    for manifest_path in sorted((ROOT / "docs" / "openapi").glob("*-manifest.json")):
        manifest = _load(manifest_path)
        for path, digest in manifest.get("paths", {}).items():
            if path in expected_paths:
                raise SystemExit(f"Duplicate additive OpenAPI path {path}")
            expected_paths[path] = digest
        for name, digest in manifest.get("schemas", {}).items():
            if name in expected_schemas:
                raise SystemExit(f"Duplicate additive OpenAPI schema {name}")
            expected_schemas[name] = digest

    if actual_paths != expected_paths:
        raise SystemExit(
            "Additive OpenAPI path drift detected: "
            f"expected={sorted(expected_paths)} actual={sorted(actual_paths)}"
        )
    if actual_schemas != expected_schemas:
        raise SystemExit(
            "Additive OpenAPI schema drift detected: "
            f"expected={sorted(expected_schemas)} actual={sorted(actual_schemas)}"
        )
    print(
        "OpenAPI contract verified: "
        f"{len(generated_paths)} paths, {len(actual_paths)} reviewed additions"
    )


if __name__ == "__main__":
    main()
