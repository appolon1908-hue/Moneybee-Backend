from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one review-fix marker in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"Expected exactly one regex review-fix marker in {path}")
    target.write_text(updated, encoding="utf-8")


def patch_esign_contract() -> None:
    replace_once(
        "app/integrations/base.py",
        "    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:\n"
        "        ...\n",
        "    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:\n"
        "        ...\n\n"
        "    async def envelope_status(self, *, envelope_id: str) -> dict:\n"
        "        ...\n",
    )
    replace_once(
        "app/integrations/providers.py",
        "    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:\n"
        "        return await provider_request(\n"
        "            provider=\"docusign\",\n"
        "            method=\"PUT\",\n"
        "            url=self._envelope_url(envelope_id),\n"
        "            headers={**_bearer(settings.docusign_access_token, \"docusign\"), \"Content-Type\": \"application/json\"},\n"
        "            json={\"status\": \"voided\", \"voidedReason\": reason},\n"
        "            retries=1,\n"
        "        )\n",
        "    async def void_envelope(self, *, envelope_id: str, reason: str) -> dict:\n"
        "        return await provider_request(\n"
        "            provider=\"docusign\",\n"
        "            method=\"PUT\",\n"
        "            url=self._envelope_url(envelope_id),\n"
        "            headers={**_bearer(settings.docusign_access_token, \"docusign\"), \"Content-Type\": \"application/json\"},\n"
        "            json={\"status\": \"voided\", \"voidedReason\": reason},\n"
        "            retries=1,\n"
        "        )\n\n"
        "    async def envelope_status(self, *, envelope_id: str) -> dict:\n"
        "        return await provider_request(\n"
        "            provider=\"docusign\",\n"
        "            method=\"GET\",\n"
        "            url=self._envelope_url(envelope_id),\n"
        "            headers=_bearer(settings.docusign_access_token, \"docusign\"),\n"
        "            retries=0,\n"
        "        )\n",
    )
    replace_once(
        "app/admin_routes.py",
        "from app.db import get_db\n",
        "from app.contract_void_service import ensure_provider_void_confirmed\n"
        "from app.db import get_db\n",
    )
    replace_once(
        "app/admin_routes.py",
        "    if contract.status == \"SENT\" and contract.external_envelope_id:\n"
        "        try:\n"
        "            await esign_adapter().void_envelope(\n"
        "                envelope_id=contract.external_envelope_id,\n"
        "                reason=payload.reason,\n"
        "            )\n"
        "        except ProviderError as exc:\n"
        "            raise HTTPException(status_code=503, detail=\"E-sign void could not be confirmed\") from exc\n",
        "    if contract.status == \"SENT\" and contract.external_envelope_id:\n"
        "        await ensure_provider_void_confirmed(\n"
        "            db,\n"
        "            contract,\n"
        "            reason=payload.reason,\n"
        "            adapter=esign_adapter(),\n"
        "        )\n",
    )


def patch_compliance_idempotency() -> None:
    replace_once(
        "app/compliance_service.py",
        "from datetime import UTC, datetime\n",
        "import hashlib\nimport json\nfrom datetime import UTC, datetime\n",
    )
    replace_once(
        "app/compliance_service.py",
        "from sqlalchemy import select\n",
        "from fastapi import HTTPException\nfrom sqlalchemy import select\n",
    )
    replace_once(
        "app/compliance_service.py",
        "from app import identity_models, models\n",
        "from app import identity_models, models, schemas\n",
    )
    replace_once(
        "app/compliance_service.py",
        "from app.encryption import encrypt_secret\n",
        "from app.encryption import encrypt_secret\n"
        "from app.idempotency import acquire_idempotency_lock, get_idempotency_record\n",
    )
    replace_once(
        "app/compliance_service.py",
        "async def acknowledge_offer_disclosure(\n"
        "    db: AsyncSession, offer_id, *, actor: str\n"
        ") -> CommercialFinancingDisclosure | None:\n"
        "    disclosure = await get_offer_disclosure(db, offer_id, lock=True)\n"
        "    if disclosure is not None and disclosure.acknowledged_at is None:\n"
        "        disclosure.acknowledged_at = models.utcnow()\n"
        "        disclosure.acknowledged_by = actor\n"
        "        await db.flush()\n"
        "    return disclosure\n",
        "def _disclosure_request_hash(disclosure: CommercialFinancingDisclosure) -> str:\n"
        "    payload = {\n"
        "        \"offer_id\": str(disclosure.offer_id),\n"
        "        \"application_id\": str(disclosure.application_id),\n"
        "    }\n"
        "    return hashlib.sha256(\n"
        "        json.dumps(payload, sort_keys=True, separators=(\",\", \":\")).encode(\"utf-8\")\n"
        "    ).hexdigest()\n\n\n"
        "async def acknowledge_disclosure_idempotently(\n"
        "    db: AsyncSession,\n"
        "    disclosure: CommercialFinancingDisclosure,\n"
        "    *,\n"
        "    actor: str,\n"
        "    idempotency_key: str,\n"
        "    route: str,\n"
        ") -> schemas.CommercialFinancingDisclosureRead | dict:\n"
        "    request_hash = _disclosure_request_hash(disclosure)\n"
        "    await acquire_idempotency_lock(\n"
        "        db, actor_id=actor, route=route, key=idempotency_key\n"
        "    )\n"
        "    existing = await get_idempotency_record(\n"
        "        db, actor_id=actor, route=route, key=idempotency_key\n"
        "    )\n"
        "    if existing is not None:\n"
        "        if existing.request_hash != request_hash:\n"
        "            raise HTTPException(\n"
        "                status_code=409,\n"
        "                detail={\n"
        "                    \"code\": \"IDEMPOTENCY_CONFLICT\",\n"
        "                    \"message\": \"The idempotency key was already used for a different disclosure.\",\n"
        "                },\n"
        "            )\n"
        "        return existing.response_body\n\n"
        "    if disclosure.acknowledged_at is None:\n"
        "        disclosure.acknowledged_at = models.utcnow()\n"
        "        disclosure.acknowledged_by = actor\n"
        "        db.add(\n"
        "            models.AuditEvent(\n"
        "                actor_id=actor,\n"
        "                action=\"COMMERCIAL_FINANCING_DISCLOSURE_ACKNOWLEDGED\",\n"
        "                resource_type=\"commercial_financing_disclosure\",\n"
        "                resource_id=str(disclosure.id),\n"
        "                details={\n"
        "                    \"offer_id\": str(disclosure.offer_id),\n"
        "                    \"application_id\": str(disclosure.application_id),\n"
        "                },\n"
        "            )\n"
        "        )\n\n"
        "    response = schemas.CommercialFinancingDisclosureRead.model_validate(disclosure)\n"
        "    db.add(\n"
        "        models.IdempotencyRecord(\n"
        "            key=idempotency_key,\n"
        "            actor_id=actor,\n"
        "            route=route,\n"
        "            request_hash=request_hash,\n"
        "            response_status=200,\n"
        "            response_body=response.model_dump(mode=\"json\"),\n"
        "        )\n"
        "    )\n"
        "    await db.commit()\n"
        "    return response\n\n\n"
        "async def acknowledge_offer_disclosure(\n"
        "    db: AsyncSession, offer_id, *, actor: str\n"
        ") -> schemas.CommercialFinancingDisclosureRead | dict | None:\n"
        "    disclosure = await get_offer_disclosure(db, offer_id, lock=True)\n"
        "    if disclosure is None:\n"
        "        return None\n"
        "    return await acknowledge_disclosure_idempotently(\n"
        "        db,\n"
        "        disclosure,\n"
        "        actor=actor,\n"
        "        idempotency_key=f\"offer-disclosure-ack:{offer_id}\",\n"
        "        route=f\"/offers/{offer_id}/commercial-financing-disclosure/acknowledge\",\n"
        "    )\n",
    )
    replace_once(
        "app/applications_routes.py",
        "    disclosure = await compliance_service.acknowledge_offer_disclosure(\n"
        "        db, offer_id, actor=user.subject\n"
        "    )\n"
        "    if disclosure is None:\n"
        "        raise HTTPException(status_code=404, detail=\"Disclosure not found\")\n"
        "    await db.commit()\n"
        "    await db.refresh(disclosure)\n"
        "    return disclosure\n",
        "    disclosure = await compliance_service.acknowledge_offer_disclosure(\n"
        "        db, offer_id, actor=user.subject\n"
        "    )\n"
        "    if disclosure is None:\n"
        "        raise HTTPException(status_code=404, detail=\"Disclosure not found\")\n"
        "    return disclosure\n",
    )
    replace_once(
        "app/compliance_routes.py",
        "from app.compliance_service import generate_commission_tax_records, update_recipient_tin\n",
        "from app.compliance_service import (\n"
        "    acknowledge_disclosure_idempotently,\n"
        "    generate_commission_tax_records,\n"
        "    update_recipient_tin,\n"
        ")\n"
        "from app.idempotency import acquire_idempotency_lock, get_idempotency_record\n",
    )
    regex_once(
        "app/compliance_routes.py",
        r"async def _acknowledge_disclosure\(.*?\n\n\n@router\.get\(",
        "async def _acknowledge_disclosure(\n"
        "    *,\n"
        "    db: AsyncSession,\n"
        "    disclosure: compliance_models.CommercialFinancingDisclosure,\n"
        "    user: Principal,\n"
        "    idempotency_key: str,\n"
        "    route: str,\n"
        ") -> CommercialFinancingDisclosureRead | dict:\n"
        "    return await acknowledge_disclosure_idempotently(\n"
        "        db,\n"
        "        disclosure,\n"
        "        actor=user.subject,\n"
        "        idempotency_key=idempotency_key,\n"
        "        route=route,\n"
        "    )\n\n\n@router.get(",
    )
    replace_once(
        "app/compliance_routes.py",
        "    route = \"/admin/compliance/commission-tax-records/generate\"\n"
        "    request_hash = _request_hash({\"tax_year\": tax_year})\n"
        "    existing = await db.scalar(\n",
        "    route = \"/admin/compliance/commission-tax-records/generate\"\n"
        "    request_hash = _request_hash({\"tax_year\": tax_year})\n"
        "    await acquire_idempotency_lock(\n"
        "        db, actor_id=user.subject, route=route, key=idempotency_key\n"
        "    )\n"
        "    existing = await db.scalar(\n",
    )
    replace_once(
        "app/compliance_routes.py",
        "    route = f\"/admin/compliance/commission-tax-records/{record_id}/filing\"\n"
        "    request_hash = _request_hash(payload.model_dump(mode=\"json\"))\n"
        "    existing = await db.scalar(\n",
        "    route = f\"/admin/compliance/commission-tax-records/{record_id}/filing\"\n"
        "    request_hash = _request_hash(payload.model_dump(mode=\"json\"))\n"
        "    await acquire_idempotency_lock(\n"
        "        db, actor_id=user.subject, route=route, key=idempotency_key\n"
        "    )\n"
        "    existing = await db.scalar(\n",
    )
    replace_once(
        "app/compliance_routes.py",
        "    if record is None:\n"
        "        raise HTTPException(status_code=404, detail=\"Commission tax record not found\")\n"
        "    if (\n"
        "        record.filed_at is not None\n",
        "    if record is None:\n"
        "        raise HTTPException(status_code=404, detail=\"Commission tax record not found\")\n"
        "    existing_after_lock = await get_idempotency_record(\n"
        "        db, actor_id=user.subject, route=route, key=idempotency_key\n"
        "    )\n"
        "    if existing_after_lock is not None:\n"
        "        if existing_after_lock.request_hash != request_hash:\n"
        "            _problem(\n"
        "                \"IDEMPOTENCY_CONFLICT\",\n"
        "                \"The idempotency key was already used with different filing evidence.\",\n"
        "            )\n"
        "        return existing_after_lock.response_body\n"
        "    if (\n"
        "        record.filed_at is not None\n",
    )


def main() -> None:
    patch_esign_contract()
    patch_compliance_idempotency()
    print("Applied all five Codex review fixes")


if __name__ == "__main__":
    main()
