"""Generate or verify the additive OpenAPI manifest for compliance operations."""

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


TARGET = ROOT / "docs" / "openapi" / "compliance-operator-api-manifest.json"
PATHS = (
    "/api/v2/admin/compliance/overview",
    "/api/v2/admin/compliance/adverse-action-notices",
    "/api/v2/admin/compliance/commercial-financing-disclosures",
    "/api/v2/admin/compliance/commission-tax-records",
    "/api/v2/admin/compliance/commission-tax-records/generate",
    "/api/v2/admin/compliance/commission-tax-records/{record_id}/tin",
    "/api/v2/admin/compliance/commission-tax-records/{record_id}/filing",
    "/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure",
    "/api/v2/borrower/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
    "/api/v2/admin/compliance/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
)
SCHEMAS = (
    "ComplianceOverviewRead",
    "AdverseActionNoticePage",
    "CommercialFinancingDisclosurePage",
    "CommissionTaxRecordOperatorRead",
    "CommissionTaxRecordPage",
    "StrictCommissionTaxRecordTinInput",
    "CommissionTaxRecordFilingInput",
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
            "Compliance operator surface is incomplete: "
            f"paths={missing_paths}, schemas={missing_schemas}"
        )

    manifest = {
        "name": "compliance-operator-api",
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
            raise SystemExit(f"Compliance operator manifest drift detected: {TARGET}")
        print("Compliance operator manifest verified")
        return

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
