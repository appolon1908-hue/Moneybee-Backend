import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import User, get_current_user
from app.db import get_db
from app.portal_models import PortalConversation, PortalMessage, PortalNotification
from app.portal_schemas import (
    PortalConversationRead,
    PortalMessageCreate,
    PortalMessageRead,
)
from app.portal_security import require_moneybee_admin

router = APIRouter(prefix="/admin/conversations", tags=["admin-communications"])


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _audit(
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    details: dict,
) -> models.AuditEvent:
    return models.AuditEvent(
        actor_subject=user.principal.subject,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details={
            **details,
            "user_id": str(user.principal.user_id),
            "active_organization_id": str(
                user.principal.active_organization_id or ""
            ),
        },
    )


async def _locked_conversation(
    *, conversation_id: uuid.UUID, db: AsyncSession
) -> PortalConversation:
    result = await db.execute(
        select(PortalConversation)
        .where(PortalConversation.id == conversation_id)
        .with_for_update()
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise _problem(
            "PORTAL_CONVERSATION_NOT_FOUND",
            "Portal conversation was not found.",
            404,
        )
    return conversation


@router.get("", response_model=list[PortalConversationRead])
async def list_admin_conversations(
    tenant_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalConversation]:
    require_moneybee_admin(user.principal)
    query = select(PortalConversation)
    if tenant_id is not None:
        query = query.where(PortalConversation.tenant_id == tenant_id)
    if application_id is not None:
        query = query.where(PortalConversation.application_id == application_id)
    if status:
        query = query.where(PortalConversation.status == status.upper())
    result = await db.execute(
        query.order_by(PortalConversation.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get(
    "/{conversation_id}/messages",
    response_model=list[PortalMessageRead],
)
async def list_admin_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=500, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortalMessage]:
    require_moneybee_admin(user.principal)
    conversation = await db.get(PortalConversation, conversation_id)
    if conversation is None:
        raise _problem(
            "PORTAL_CONVERSATION_NOT_FOUND",
            "Portal conversation was not found.",
            404,
        )
    result = await db.execute(
        select(PortalMessage)
        .where(PortalMessage.conversation_id == conversation.id)
        .order_by(PortalMessage.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/{conversation_id}/messages",
    response_model=PortalMessageRead,
    status_code=201,
)
async def create_admin_message(
    conversation_id: uuid.UUID,
    payload: PortalMessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalMessage:
    require_moneybee_admin(user.principal)
    conversation = await _locked_conversation(
        conversation_id=conversation_id,
        db=db,
    )
    if conversation.status == "CLOSED":
        raise _problem(
            "PORTAL_CONVERSATION_CLOSED",
            "Reopen the conversation before adding a message.",
            409,
        )
    admin_subject = user.principal.subject
    conversation.participant_subjects = list(
        dict.fromkeys([*conversation.participant_subjects, admin_subject])
    )
    conversation.last_message_at = datetime.now(UTC)
    message = PortalMessage(
        conversation_id=conversation.id,
        sender_subject=admin_subject,
        body=payload.body.strip(),
        attachments=payload.attachments,
        metadata_payload=payload.metadata_payload,
    )
    db.add(message)
    await db.flush()
    for participant in conversation.participant_subjects:
        if participant == admin_subject:
            continue
        db.add(
            PortalNotification(
                tenant_id=conversation.tenant_id,
                recipient_subject=participant,
                notification_type="PORTAL_MESSAGE",
                title=conversation.topic,
                body="The MoneyBee team replied to your secure conversation.",
                href=f"/messages?conversation={conversation.id}",
                metadata_payload={"conversation_id": str(conversation.id)},
            )
        )
    db.add(
        _audit(
            user=user,
            action="admin_portal_message.created",
            entity_type="portal_message",
            entity_id=message.id,
            details={
                "conversation_id": str(conversation.id),
                "tenant_id": str(conversation.tenant_id),
            },
        )
    )
    await db.commit()
    await db.refresh(message)
    return message


@router.post("/{conversation_id}/close", response_model=PortalConversationRead)
async def close_admin_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalConversation:
    require_moneybee_admin(user.principal)
    conversation = await _locked_conversation(
        conversation_id=conversation_id,
        db=db,
    )
    previous_status = conversation.status
    conversation.status = "CLOSED"
    db.add(
        _audit(
            user=user,
            action="admin_portal_conversation.closed",
            entity_type="portal_conversation",
            entity_id=conversation.id,
            details={"previous_status": previous_status},
        )
    )
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.post("/{conversation_id}/reopen", response_model=PortalConversationRead)
async def reopen_admin_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalConversation:
    require_moneybee_admin(user.principal)
    conversation = await _locked_conversation(
        conversation_id=conversation_id,
        db=db,
    )
    previous_status = conversation.status
    conversation.status = "OPEN"
    conversation.last_message_at = datetime.now(UTC)
    db.add(
        _audit(
            user=user,
            action="admin_portal_conversation.reopened",
            entity_type="portal_conversation",
            entity_id=conversation.id,
            details={"previous_status": previous_status},
        )
    )
    await db.commit()
    await db.refresh(conversation)
    return conversation
