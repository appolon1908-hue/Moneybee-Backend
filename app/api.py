import hashlib
import hmac
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.config import get_settings
from app.database import get_session
from app.security import Principal, get_principal, require_roles

router = APIRouter()
settings = get_settings()


def _can_access_application(application: models.Application, principal: Principal) -> bool:
    return "admin" in principal.roles or "operations" in principal.roles or application.owner_subject == principal.subject


@router.get("/me", response_model=schemas.PrincipalRead)
async def me(principal: Annotated[Principal, Depends(get_principal)]) -> schemas.PrincipalRead:
    return schemas.PrincipalRead(subject=principal.subject, roles=sorted(principal.roles))


@router.post("/leads", response_model=schemas.LeadRead, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: schemas.LeadCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=180)],
) -> models.Lead:
    return await services.create_lead(session, payload, idempotency_key)


@router.post("/applications", response_model=schemas.ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: schemas.ApplicationCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=180)],
) -> models.Application:
    return await services.create_application(session, payload, idempotency_key, principal.subject)


@router.get("/applications", response_model=list[schemas.ApplicationRead])
async def list_applications(
    session: Annotated[AsyncSession, Depends(get_session)],
    _principal: Annotated[Principal, Depends(require_roles("admin", "operations"))],
    limit: int = 50,
    offset: int = 0,
) -> list[models.Application]:
    limit = min(max(limit, 1), 200)
    result = await session.scalars(
        select(models.Application).order_by(models.Application.created_at.desc()).limit(limit).offset(max(offset, 0))
    )
    return list(result)


@router.get("/applications/{application_id}", response_model=schemas.ApplicationRead)
async def get_application(
    application_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> models.Application:
    application = await session.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_access_application(application, principal):
        raise HTTPException(status_code=403, detail="Not authorized for this application")
    return application


@router.post("/applications/{application_id}/submit", response_model=schemas.ApplicationRead)
async def submit_application(
    application_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> models.Application:
    application = await session.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.owner_subject != principal.subject and "admin" not in principal.roles:
        raise HTTPException(status_code=403, detail="Not authorized for this application")
    try:
        application.status = services.transition_application(application.status, "submitted")
    except services.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        models.AuditEvent(
            actor_subject=principal.subject,
            action="application.submitted",
            resource_type="application",
            resource_id=str(application.id),
            correlation_id=request.state.correlation_id,
            details_json=services.audit_payload(status=application.status),
        )
    )
    await session.commit()
    await session.refresh(application)
    return application


@router.get("/applications/{application_id}/offers", response_model=list[schemas.OfferRead])
async def get_offers(
    application_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[models.Offer]:
    application = await session.get(models.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not _can_access_application(application, principal):
        raise HTTPException(status_code=403, detail="Not authorized for this application")
    result = await session.scalars(select(models.Offer).where(models.Offer.application_id == application_id))
    return list(result)


@router.post("/webhooks/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def provider_webhook(
    provider: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_moneybee_signature: Annotated[str, Header(alias="X-MoneyBee-Signature")],
    x_event_id: Annotated[str, Header(alias="X-Event-Id", min_length=1, max_length=180)],
) -> Response:
    body = await request.body()
    expected = hmac.new(settings.webhook_shared_secret.encode(), body, hashlib.sha256).hexdigest()
    if not settings.webhook_shared_secret or not hmac.compare_digest(expected, x_moneybee_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    existing = await session.scalar(
        select(models.WebhookEvent).where(
            models.WebhookEvent.provider == provider,
            models.WebhookEvent.external_event_id == x_event_id,
        )
    )
    if existing is None:
        session.add(
            models.WebhookEvent(
                provider=provider,
                external_event_id=x_event_id,
                payload_json=json.dumps(json.loads(body.decode("utf-8"))),
            )
        )
        await session.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)
