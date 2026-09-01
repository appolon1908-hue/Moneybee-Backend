from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.auth import Principal, current_principal
from app.db import get_db


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
User = Annotated[Principal, Depends(current_principal)]


class EffectivePermissionsRead(BaseModel):
    active_organization_id: uuid.UUID | None
    roles: list[str]
    permissions: list[str]
    membership_types: list[str]


class PublicProductRead(BaseModel):
    product_type: str = Field(min_length=1, max_length=80)


@router.get(
    "/me/permissions",
    response_model=EffectivePermissionsRead,
    tags=["identity"],
)
async def me_permissions(user: User) -> EffectivePermissionsRead:
    """Return the effective local authorization set for the active MoneyBee context."""
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
)
async def public_products(db: Db) -> list[PublicProductRead]:
    """Expose only public product categories backed by active lender programs.

    This deliberately omits lender identity, private underwriting criteria, ranking
    inputs, and program configuration. An empty catalog is a valid fail-closed state.
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
