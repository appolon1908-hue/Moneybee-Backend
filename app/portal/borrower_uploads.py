from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.auth import Principal, current_principal
from app.db import get_db
from app.portal import models as portal_models
from app.portal.schemas import UploadSessionRead


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


@router.get(
    "/borrower/applications/{application_id}/documents/upload-sessions",
    response_model=list[UploadSessionRead],
    tags=["borrower", "documents"],
)
async def list_document_upload_sessions(
    application_id: uuid.UUID,
    db: Db,
    user: User,
):
    """List the authenticated borrower's upload-session history for one application.

    Presigned upload URLs are intentionally not re-issued from this read endpoint.
    A new POST upload session is required for every new upload attempt.
    """
    await services.get_authorized_application(db, application_id, user)
    statement = select(portal_models.DocumentUploadSession).where(
        portal_models.DocumentUploadSession.application_id == application_id
    )
    if "*" not in user.permissions:
        statement = statement.where(
            portal_models.DocumentUploadSession.created_by_subject == user.subject
        )
    rows = list(
        (
            await db.scalars(
                statement.order_by(portal_models.DocumentUploadSession.created_at.desc()).limit(100)
            )
        ).all()
    )
    return [UploadSessionRead.model_validate(row) for row in rows]
