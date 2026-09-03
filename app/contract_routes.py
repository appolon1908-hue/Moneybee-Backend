from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas, services
from app.auth import Principal, current_principal
from app.db import get_db


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


class EffectivePermissionsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_organization_id: uuid.UUID | None
    roles: list[str]
    permissions: list[str]
    membership_types: list[str]


class PublicProductRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_type: str = Field(min_length=1, max_length=80)


class ApplicationStatusRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: uuid.UUID
    status: str
    completion_percentage: int = Field(ge=0, le=100)
    version: int = Field(ge=1)


@router.get(
    "/me/permissions",
    response_model=EffectivePermissionsRead,
    tags=["identity"],
    operation_id="identity_get_effective_permissions",
)
async def me_permissions(user: User) -> EffectivePermissionsRead:
    """Return the effective local authorization set for the active tenant context."""
    return EffectivePermissionsRead(
        active_organization_id=user.active_organization_id,
        roles=sorted(user.roles),
        permissions=sorted(user.permissions),
        membership_types=sorted(user.membership_types),
    )


@router.get(
    "/public/products",
    response_model=list[PublicProductRead],
    tags=["public"],
    operation_id="public_list_products",
)
async def public_products(db: Db) -> list[PublicProductRead]:
    """Expose only product categories backed by active lender programs.

    Lender identity, ranking inputs, underwriting criteria, prices, and private
    program configuration are intentionally omitted. An empty catalog is a
    valid fail-closed state.
    """
    product_types = (
        await db.scalars(
            select(models.LenderProgram.product_type)
            .where(models.LenderProgram.active.is_(True))
            .distinct()
            .order_by(models.LenderProgram.product_type)
        )
    ).all()
    return [PublicProductRead(product_type=value) for value in product_types if value]


@router.get(
    "/applications/{application_id}/status",
    response_model=ApplicationStatusRead,
    tags=["applications"],
    operation_id="applications_get_status",
)
async def application_status(
    application_id: uuid.UUID,
    db: Db,
    user: User,
) -> ApplicationStatusRead:
    application = await services.get_authorized_application(
        db,
        application_id,
        user,
        write=False,
    )
    return ApplicationStatusRead(
        application_id=application.id,
        status=application.status.value,
        completion_percentage=application.completion_percentage,
        version=application.version,
    )


@router.get(
    "/offers/{offer_id}",
    response_model=schemas.OfferRead,
    tags=["offers"],
    operation_id="offers_get_detail",
)
async def offer_detail(
    offer_id: uuid.UUID,
    db: Db,
    user: User,
) -> models.Offer:
    offer = await db.scalar(select(models.Offer).where(models.Offer.id == offer_id))
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    await services.get_authorized_application(
        db,
        offer.application_id,
        user,
        write=False,
    )
    return offer
