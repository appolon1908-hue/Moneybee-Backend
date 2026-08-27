from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as application_schemas
from app.auth import bearer, decode_access_token
from app.db import get_db
from app.portal.account_schemas import AccountBootstrapRead
from app.portal.account_service import bootstrap_account


router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=160),
]


@router.post(
    "/auth/bootstrap",
    response_model=AccountBootstrapRead,
    responses={
        401: {
            "model": application_schemas.ErrorResponse,
            "description": "Authentication failed",
        },
        403: {
            "model": application_schemas.ErrorResponse,
            "description": "Email verification or invitation is required",
        },
        409: {
            "model": application_schemas.ErrorResponse,
            "description": "Account binding or idempotency conflict",
        },
        503: {
            "model": application_schemas.ErrorResponse,
            "description": "Account provisioning is not configured",
        },
    },
    tags=["identity", "account"],
)
async def account_bootstrap(
    request: Request,
    db: Db,
    credentials: Credentials,
    idempotency_key: IdempotencyKey,
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(credentials.credentials)
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    correlation_id = request.headers.get("X-Correlation-ID") or request_id
    return await bootstrap_account(
        db,
        claims=claims,
        idempotency_key=idempotency_key,
        request_id=request_id,
        correlation_id=correlation_id,
    )
