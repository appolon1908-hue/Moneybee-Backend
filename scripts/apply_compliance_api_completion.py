from __future__ import annotations

import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write(relative_path: str, content: str) -> None:
    target = ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def replace_once(path: Path, old: str, new: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if old not in source:
        return False
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return True


def complete_authenticated_acknowledgement() -> None:
    schemas_path = ROOT / "app" / "schemas.py"
    schemas = schemas_path.read_text(encoding="utf-8")
    schemas = re.sub(
        r"\nclass CommercialFinancingAcknowledgeInput\(BaseModel\):\n"
        r"    acknowledged_by: str = Field\(min_length=1, max_length=255\)\n",
        "",
        schemas,
        count=1,
    )
    schemas_path.write_text(schemas, encoding="utf-8")

    admin_path = ROOT / "app" / "admin_routes.py"
    admin = admin_path.read_text(encoding="utf-8")
    admin = admin.replace(
        "    payload: schemas.CommercialFinancingAcknowledgeInput,\n",
        "",
        1,
    )
    admin = admin.replace(
        "disclosure.acknowledged_by = payload.acknowledged_by",
        "disclosure.acknowledged_by = user.subject",
        1,
    )
    if "disclosure.acknowledged_by = user.subject" not in admin:
        raise RuntimeError(
            "The disclosure acknowledgement endpoint is not bound to user.subject."
        )
    admin_path.write_text(admin, encoding="utf-8")

    test_path = ROOT / "tests" / "test_commercial_financing_disclosure.py"
    test_source = test_path.read_text(encoding="utf-8")
    test_source = test_source.replace(
        'json={"acknowledged_by": "borrower-portal"}',
        'json={"acknowledged_by": "spoofed-client-value"}',
    )
    test_source = test_source.replace(
        'assert acknowledge.json()["acknowledged_by"] == "borrower-portal"',
        'assert acknowledge.json()["acknowledged_by"] == "local-admin"',
    )
    test_path.write_text(test_source, encoding="utf-8")


def write_compliance_router() -> None:
    write(
        "app/compliance_routes.py",
        '''
        from __future__ import annotations

        import uuid
        from typing import Annotated, Any

        from fastapi import APIRouter, Depends, HTTPException
        from pydantic import BaseModel
        from sqlalchemy import func, select

        from app import compliance_models, schemas
        from app.auth import Principal, require_permission
        from app.db import Db


        router = APIRouter()
        MAX_PAGE_SIZE = 200


        class ComplianceSummaryRead(BaseModel):
            adverse_action_notices_total: int
            adverse_action_notices_delivered: int
            commercial_financing_disclosures_total: int
            commercial_financing_disclosures_acknowledged: int
            commission_tax_records_total: int
            commission_tax_records_requiring_1099: int
            commission_tax_records_with_tin: int


        class AdverseActionNoticePage(BaseModel):
            items: list[schemas.AdverseActionNoticeRead]
            total: int
            limit: int
            offset: int
            has_more: bool


        class CommercialFinancingDisclosurePage(BaseModel):
            items: list[schemas.CommercialFinancingDisclosureRead]
            total: int
            limit: int
            offset: int
            has_more: bool


        class CommissionTaxRecordListItem(schemas.CommissionTaxRecordRead):
            has_tin: bool


        class CommissionTaxRecordPage(BaseModel):
            items: list[CommissionTaxRecordListItem]
            total: int
            limit: int
            offset: int
            has_more: bool


        def _validate_page(limit: int, offset: int) -> None:
            if limit < 1 or limit > MAX_PAGE_SIZE or offset < 0:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_PAGINATION",
                        "message": (
                            f"limit must be between 1 and {MAX_PAGE_SIZE}; "
                            "offset must be zero or greater."
                        ),
                    },
                )


        async def _count(db: Db, model: type[Any], *filters: Any) -> int:
            statement = select(func.count()).select_from(model)
            if filters:
                statement = statement.where(*filters)
            return int(await db.scalar(statement) or 0)


        @router.get(
            "/admin/compliance/summary",
            response_model=ComplianceSummaryRead,
            tags=["admin", "compliance"],
            operation_id="get_admin_compliance_summary",
        )
        async def get_admin_compliance_summary(
            db: Db,
            user: Annotated[
                Principal,
                Depends(require_permission("application.read")),
            ],
        ) -> ComplianceSummaryRead:
            adverse_total = await _count(db, compliance_models.AdverseActionNotice)
            adverse_delivered = await _count(
                db,
                compliance_models.AdverseActionNotice,
                compliance_models.AdverseActionNotice.delivered_at.is_not(None),
            )
            disclosure_total = await _count(
                db, compliance_models.CommercialFinancingDisclosure
            )
            disclosure_acknowledged = await _count(
                db,
                compliance_models.CommercialFinancingDisclosure,
                compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_not(
                    None
                ),
            )
            tax_total = await _count(db, compliance_models.CommissionTaxRecord)
            tax_required = await _count(
                db,
                compliance_models.CommissionTaxRecord,
                compliance_models.CommissionTaxRecord.requires_1099.is_(True),
            )
            tax_with_tin = await _count(
                db,
                compliance_models.CommissionTaxRecord,
                compliance_models.CommissionTaxRecord.tin_ciphertext.is_not(None),
            )
            return ComplianceSummaryRead(
                adverse_action_notices_total=adverse_total,
                adverse_action_notices_delivered=adverse_delivered,
                commercial_financing_disclosures_total=disclosure_total,
                commercial_financing_disclosures_acknowledged=(
                    disclosure_acknowledged
                ),
                commission_tax_records_total=tax_total,
                commission_tax_records_requiring_1099=tax_required,
                commission_tax_records_with_tin=tax_with_tin,
            )


        @router.get(
            "/admin/compliance/adverse-action-notices",
            response_model=AdverseActionNoticePage,
            tags=["admin", "compliance"],
            operation_id="list_admin_adverse_action_notices",
        )
        async def list_admin_adverse_action_notices(
            db: Db,
            user: Annotated[
                Principal,
                Depends(require_permission("application.read")),
            ],
            application_id: uuid.UUID | None = None,
            lender_id: uuid.UUID | None = None,
            status: str | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> AdverseActionNoticePage:
            _validate_page(limit, offset)
            filters = []
            if application_id is not None:
                filters.append(
                    compliance_models.AdverseActionNotice.application_id
                    == application_id
                )
            if lender_id is not None:
                filters.append(
                    compliance_models.AdverseActionNotice.lender_id == lender_id
                )
            if status:
                filters.append(compliance_models.AdverseActionNotice.status == status)
            total = await _count(
                db, compliance_models.AdverseActionNotice, *filters
            )
            statement = select(compliance_models.AdverseActionNotice)
            if filters:
                statement = statement.where(*filters)
            items = list(
                (
                    await db.scalars(
                        statement.order_by(
                            compliance_models.AdverseActionNotice.created_at.desc()
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return AdverseActionNoticePage(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + len(items) < total,
            )


        @router.get(
            "/admin/compliance/commercial-financing-disclosures",
            response_model=CommercialFinancingDisclosurePage,
            tags=["admin", "compliance"],
            operation_id="list_admin_commercial_financing_disclosures",
        )
        async def list_admin_commercial_financing_disclosures(
            db: Db,
            user: Annotated[
                Principal,
                Depends(require_permission("application.read")),
            ],
            application_id: uuid.UUID | None = None,
            jurisdiction: str | None = None,
            acknowledged: bool | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> CommercialFinancingDisclosurePage:
            _validate_page(limit, offset)
            filters = []
            if application_id is not None:
                filters.append(
                    compliance_models.CommercialFinancingDisclosure.application_id
                    == application_id
                )
            if jurisdiction:
                filters.append(
                    compliance_models.CommercialFinancingDisclosure.jurisdiction
                    == jurisdiction.upper()
                )
            if acknowledged is True:
                filters.append(
                    compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_not(
                        None
                    )
                )
            elif acknowledged is False:
                filters.append(
                    compliance_models.CommercialFinancingDisclosure.acknowledged_at.is_(
                        None
                    )
                )
            total = await _count(
                db, compliance_models.CommercialFinancingDisclosure, *filters
            )
            statement = select(
                compliance_models.CommercialFinancingDisclosure
            )
            if filters:
                statement = statement.where(*filters)
            items = list(
                (
                    await db.scalars(
                        statement.order_by(
                            compliance_models.CommercialFinancingDisclosure.created_at.desc()
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            return CommercialFinancingDisclosurePage(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + len(items) < total,
            )


        @router.get(
            "/admin/compliance/commission-tax-records",
            response_model=CommissionTaxRecordPage,
            tags=["admin", "compliance"],
            operation_id="list_admin_compliance_commission_tax_records",
        )
        async def list_admin_compliance_commission_tax_records(
            db: Db,
            user: Annotated[
                Principal,
                Depends(require_permission("commission.receipt.record")),
            ],
            tax_year: int | None = None,
            requires_1099: bool | None = None,
            has_tin: bool | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> CommissionTaxRecordPage:
            _validate_page(limit, offset)
            filters = []
            if tax_year is not None:
                filters.append(
                    compliance_models.CommissionTaxRecord.tax_year == tax_year
                )
            if requires_1099 is not None:
                filters.append(
                    compliance_models.CommissionTaxRecord.requires_1099.is_(
                        requires_1099
                    )
                )
            if has_tin is True:
                filters.append(
                    compliance_models.CommissionTaxRecord.tin_ciphertext.is_not(
                        None
                    )
                )
            elif has_tin is False:
                filters.append(
                    compliance_models.CommissionTaxRecord.tin_ciphertext.is_(None)
                )
            total = await _count(
                db, compliance_models.CommissionTaxRecord, *filters
            )
            statement = select(compliance_models.CommissionTaxRecord)
            if filters:
                statement = statement.where(*filters)
            records = list(
                (
                    await db.scalars(
                        statement.order_by(
                            compliance_models.CommissionTaxRecord.tax_year.desc(),
                            compliance_models.CommissionTaxRecord.total_amount.desc(),
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )
            items = [
                CommissionTaxRecordListItem(
                    **schemas.CommissionTaxRecordRead.model_validate(
                        record
                    ).model_dump(),
                    has_tin=record.tin_ciphertext is not None,
                )
                for record in records
            ]
            return CommissionTaxRecordPage(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=offset + len(items) < total,
            )
        ''',
    )


def wire_router() -> None:
    main_path = ROOT / "app" / "main.py"
    source = main_path.read_text(encoding="utf-8")
    import_line = "from app.compliance_routes import router as compliance_router\n"
    if import_line not in source:
        source = source.replace(
            "from app.banking_routes import router as banking_router\n",
            "from app.banking_routes import router as banking_router\n" + import_line,
            1,
        )
    if 'app.include_router(compliance_router, prefix="/api/v2")' not in source:
        source = source.replace(
            'app.include_router(admin_router, prefix="/api/v2")\n',
            'app.include_router(admin_router, prefix="/api/v2")\n'
            'app.include_router(compliance_router, prefix="/api/v2")\n',
            1,
        )
    hidden_alias = (
        'app.include_router(\n'
        '    compliance_router, prefix="/api/v1", include_in_schema=False\n'
        ')\n'
    )
    if hidden_alias not in source:
        source = source.replace(
            'app.include_router(admin_router, prefix="/api/v1", include_in_schema=False)\n',
            'app.include_router(admin_router, prefix="/api/v1", include_in_schema=False)\n'
            + hidden_alias,
            1,
        )
    main_path.write_text(source, encoding="utf-8")


def write_tests() -> None:
    write(
        "tests/test_compliance_operations.py",
        '''
        import os

        os.environ.setdefault("APP_ENV", "test")
        os.environ.setdefault(
            "DATABASE_URL", "sqlite+aiosqlite:///./test-moneybee.db"
        )
        os.environ.setdefault("LOCAL_AUTH_BYPASS", "true")

        from fastapi.testclient import TestClient

        from app.main import app


        def test_compliance_operations_expose_consistent_page_contracts():
            with TestClient(app) as client:
                summary = client.get("/api/v2/admin/compliance/summary")
                adverse = client.get(
                    "/api/v2/admin/compliance/adverse-action-notices",
                    params={"limit": 1, "offset": 0},
                )
                disclosures = client.get(
                    "/api/v2/admin/compliance/commercial-financing-disclosures",
                    params={"limit": 1, "offset": 0},
                )
                tax_records = client.get(
                    "/api/v2/admin/compliance/commission-tax-records",
                    params={"limit": 1, "offset": 0},
                )

            assert summary.status_code == 200
            assert set(summary.json()) == {
                "adverse_action_notices_total",
                "adverse_action_notices_delivered",
                "commercial_financing_disclosures_total",
                "commercial_financing_disclosures_acknowledged",
                "commission_tax_records_total",
                "commission_tax_records_requiring_1099",
                "commission_tax_records_with_tin",
            }
            for response in (adverse, disclosures, tax_records):
                assert response.status_code == 200
                payload = response.json()
                assert set(payload) == {
                    "items",
                    "total",
                    "limit",
                    "offset",
                    "has_more",
                }
                assert payload["limit"] == 1
                assert payload["offset"] == 0
                assert isinstance(payload["items"], list)


        def test_compliance_operations_reject_invalid_pagination():
            with TestClient(app) as client:
                response = client.get(
                    "/api/v2/admin/compliance/adverse-action-notices",
                    params={"limit": 0},
                )
            assert response.status_code == 422
            assert response.json()["code"] == "INVALID_PAGINATION"


        def test_compliance_openapi_operations_have_unique_ids():
            operation_ids = []
            for path_item in app.openapi()["paths"].values():
                for operation in path_item.values():
                    if isinstance(operation, dict) and operation.get("operationId"):
                        operation_ids.append(operation["operationId"])
            assert len(operation_ids) == len(set(operation_ids))
        ''',
    )


def write_manifest_sync() -> None:
    write(
        "scripts/sync_compliance_openapi_manifest.py",
        '''
        from __future__ import annotations

        import argparse
        import hashlib
        import json
        from pathlib import Path
        from typing import Any

        from app.main import app


        ROOT = Path(__file__).resolve().parents[1]
        MANIFEST = ROOT / "docs" / "openapi" / "compliance-records-manifest.json"

        PATHS = (
            "/api/v2/admin/applications/{application_id}/adverse-action-notices",
            "/api/v2/admin/offers/{offer_id}/commercial-financing-disclosure",
            "/api/v2/admin/offers/{offer_id}/commercial-financing-disclosure/acknowledge",
            "/api/v2/admin/commission-tax-records/generate",
            "/api/v2/admin/commission-tax-records",
            "/api/v2/admin/commission-tax-records/{record_id}/tin",
            "/api/v2/admin/compliance/summary",
            "/api/v2/admin/compliance/adverse-action-notices",
            "/api/v2/admin/compliance/commercial-financing-disclosures",
            "/api/v2/admin/compliance/commission-tax-records",
        )
        SCHEMAS = (
            "AdverseActionNoticeRead",
            "CommercialFinancingDisclosureRead",
            "CommissionTaxRecordRead",
            "CommissionTaxRecordTinInput",
            "ComplianceSummaryRead",
            "AdverseActionNoticePage",
            "CommercialFinancingDisclosurePage",
            "CommissionTaxRecordListItem",
            "CommissionTaxRecordPage",
        )


        def digest(value: Any) -> str:
            encoded = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            return hashlib.sha256(encoded).hexdigest()


        def render() -> str:
            schema = app.openapi()
            missing_paths = [path for path in PATHS if path not in schema["paths"]]
            component_schemas = schema.get("components", {}).get("schemas", {})
            missing_schemas = [name for name in SCHEMAS if name not in component_schemas]
            if missing_paths or missing_schemas:
                raise SystemExit(
                    "Compliance OpenAPI surface is incomplete: "
                    f"paths={missing_paths}, schemas={missing_schemas}"
                )
            payload = {
                "paths": {path: digest(schema["paths"][path]) for path in PATHS},
                "schemas": {
                    name: digest(component_schemas[name]) for name in SCHEMAS
                },
            }
            return json.dumps(payload, indent=2, sort_keys=True) + "\n"


        def main() -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("--check", action="store_true")
            args = parser.parse_args()
            expected = render()
            if args.check:
                actual = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
                if actual != expected:
                    print(f"OpenAPI manifest drift: {MANIFEST}")
                    return 1
                print("Compliance OpenAPI manifest is current.")
                return 0
            MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            MANIFEST.write_text(expected, encoding="utf-8")
            print(f"Wrote {MANIFEST.relative_to(ROOT)}")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        ''',
    )


def write_documentation() -> None:
    write(
        "docs/API_COMPLIANCE_OPERATIONS.md",
        '''
        # MoneyBee compliance operations API

        The canonical interface is `/api/v2`. Compatibility `/api/v1` aliases
        remain hidden from the canonical OpenAPI document.

        ## Aggregate operations

        - `GET /admin/compliance/summary`
        - `GET /admin/compliance/adverse-action-notices`
        - `GET /admin/compliance/commercial-financing-disclosures`
        - `GET /admin/compliance/commission-tax-records`

        List operations return one bounded page envelope:

        ```json
        {
          "items": [],
          "total": 0,
          "limit": 50,
          "offset": 0,
          "has_more": false
        }
        ```

        Page size is limited to 200. Invalid pagination fails through the
        platform problem-document error contract.

        ## Authority and privacy

        Disclosure acknowledgement attribution comes exclusively from the
        authenticated principal. A client cannot select or spoof the recorded
        actor. Taxpayer identification numbers remain write-only; aggregate tax
        records expose only `has_tin` and never return plaintext or ciphertext.

        Read-only compliance summaries and notice/disclosure lists require
        `application.read`. Tax-record listing and generation retain the narrower
        `commission.receipt.record` permission.

        These endpoints do not deliver notices, file tax forms, move money,
        activate providers, or enable production writes.
        ''',
    )


def order_secure_ci_gates() -> None:
    path = ROOT / ".github" / "workflows" / "secure-ci.yml"
    if not path.exists():
        return
    source = path.read_text(encoding="utf-8")
    source = re.sub(
        r"\n  authenticated-acknowledgment-hardening:.*?(?=\n  [a-zA-Z0-9_-]+:)",
        "\n",
        source,
        flags=re.DOTALL,
    )
    app_match = re.search(
        r"(?ms)^  application:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n)",
        source,
    )
    if not app_match:
        path.write_text(source, encoding="utf-8")
        return
    body = app_match.group("body")

    def find_step(name: str) -> str | None:
        match = re.search(
            rf"(?ms)^      - name: {re.escape(name)}\n"
            r".*?(?=^      - name: |^  [a-zA-Z0-9_-]+:\n|\Z)",
            body,
        )
        return match.group(0) if match else None

    upgrade = find_step("Upgrade application test database")
    tests = find_step("Application tests")
    migration = find_step("Migration and OpenAPI gates")
    if upgrade and tests and migration:
        first = min(body.index(upgrade), body.index(tests), body.index(migration))
        last = max(
            body.index(upgrade) + len(upgrade),
            body.index(tests) + len(tests),
            body.index(migration) + len(migration),
        )
        ordered = (
            upgrade.rstrip()
            + "\n"
            + migration.rstrip()
            + "\n"
            + tests.rstrip()
            + "\n"
        )
        body = body[:first] + ordered + body[last:]
        source = (
            source[: app_match.start("body")]
            + body
            + source[app_match.end("body") :]
        )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    complete_authenticated_acknowledgement()
    write_compliance_router()
    wire_router()
    write_tests()
    write_manifest_sync()
    write_documentation()
    order_secure_ci_gates()
    print("MoneyBee compliance API completion applied.")


if __name__ == "__main__":
    main()
