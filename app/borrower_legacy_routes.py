from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal, current_principal
from app.db import get_db


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


@router.get("/borrower/dashboard", tags=["borrower"])
async def borrower_dashboard(db: Db, user: User):
    if user.borrower_id is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "An active borrower membership is required.",
            },
        )
    items = list(
        (
            await db.scalars(
                select(models.Application)
                .where(
                    or_(
                        models.Application.borrower_organization_id == user.borrower_id,
                        (
                            models.Application.borrower_organization_id.is_(None)
                            & (models.Application.borrower_subject == user.subject)
                        ),
                    )
                )
                .order_by(models.Application.updated_at.desc())
            )
        ).all()
    )
    active = items[0] if items else None
    return {
        "applications": items,
        "active_application": active,
        "requirements": (await services.application_requirements(db, active) if active else None),
    }


@router.get(
    "/borrower/applications",
    response_model=list[schemas.ApplicationRead],
    tags=["borrower"],
)
async def borrower_applications(db: Db, user: User):
    if user.borrower_id is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RESOURCE_ACCESS_DENIED",
                "message": "An active borrower membership is required.",
            },
        )
    return list(
        (
            await db.scalars(
                select(models.Application)
                .where(
                    or_(
                        models.Application.borrower_organization_id == user.borrower_id,
                        (
                            models.Application.borrower_organization_id.is_(None)
                            & (models.Application.borrower_subject == user.subject)
                        ),
                    )
                )
                .order_by(models.Application.updated_at.desc())
            )
        ).all()
    )
