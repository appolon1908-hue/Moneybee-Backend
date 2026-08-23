from fastapi import APIRouter

from app.core.config import settings


router = APIRouter(
    prefix="/system",
    tags=["system"],
)


@router.get("/version")
async def version() -> dict[str, str]:
    return {
        "application": "moneybee-api",
        "build_sha": settings.build_sha,
        "migration_head": settings.migration_head,
        "environment": settings.app_env,
    }


@router.get("/readiness")
async def readiness() -> dict[str, object]:
    return {
        "FINAL_STATUS": "PARTIAL",
        "OVERALL_SYSTEM_STATUS": "PARTIAL",
        "SOURCE_SHA": settings.build_sha,
        "MIGRATION_HEAD": settings.migration_head,
        "AUTH_STATUS": "PARTIAL",
        "IDENTITY_BINDING_STATUS": "BLOCKED",
        "TENANCY_STATUS": "BLOCKED",
        "COMMAND_STATUS": "BLOCKED",
        "IDEMPOTENCY_STATUS": "BLOCKED",
        "CONCURRENCY_STATUS": "BLOCKED",
        "OUTBOX_STATUS": "BLOCKED",
        "INBOX_STATUS": "BLOCKED",
        "DOCUMENT_SECURITY_STATUS": "BLOCKED",
        "PII_STATUS": "BLOCKED",
        "LENDER_STATUS": "BLOCKED",
        "CONTRACT_STATUS": "BLOCKED",
        "FUNDING_STATUS": "BLOCKED",
        "POSTGRES_TEST_STATUS": "PARTIAL",
        "STAGING_STATUS": "BLOCKED",
        "RESTORE_STATUS": "BLOCKED",
        "PRODUCTION_FEATURES_ENABLED": [],
        "BLOCKERS": [
            "Step 1A frontend Keycloak PKCE not implemented",
            "Step 1B local identity and tenancy not implemented",
            "Steps 2-12 not complete",
            "Complete production launch gate has not passed",
        ],
        "NEXT_SAFE_ACTION": (
            "Complete Step 0 bootstrap PR review, then implement "
            "frontend/keycloak-pkce and auth/local-identity-tenancy."
        ),
    }
