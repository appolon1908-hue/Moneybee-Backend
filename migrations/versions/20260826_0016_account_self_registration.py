"""Seed the borrower role used by verified Keycloak self-registration.

Revision ID: 20260826_0016
Revises: 20260826_0015
Create Date: 2026-08-26
"""

from collections.abc import Sequence
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_0016"
down_revision: str | None = "20260826_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CODE = "BORROWER_USER"
PERMISSIONS = (
    "application.read.own",
    "application.edit.own",
    "application.submit.own",
    "condition.read.own",
    "complaint.create.own",
    "credit.authorize.own",
    "offer.accept.own",
    "document.read.own",
    "document.upload.own",
    "portal.message.own",
    "portal.task.own",
)


def _id(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"moneybee:{value}"))


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower
            ON users (lower(email))
            WHERE email IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO roles (id, code, description, active)
            VALUES (CAST(:id AS uuid), :code, :description, true)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "id": _id(f"role:{ROLE_CODE}"),
            "code": ROLE_CODE,
            "description": (
                "Default borrower portal role assigned only after verified "
                "Keycloak self-registration."
            ),
        },
    )
    for code in PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (id, code, description)
                VALUES (CAST(:id AS uuid), :code, :description)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {
                "id": _id(f"permission:{code}"),
                "code": code,
                "description": f"Default borrower permission: {code}",
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO role_permissions (id, role_id, permission_id)
                SELECT CAST(:id AS uuid), role.id, permission.id
                FROM roles AS role
                JOIN permissions AS permission ON permission.code = :permission_code
                WHERE role.code = :role_code
                  AND NOT EXISTS (
                      SELECT 1
                      FROM role_permissions AS existing
                      WHERE existing.role_id = role.id
                        AND existing.permission_id = permission.id
                  )
                """
            ),
            {
                "id": _id(f"role-permission:{ROLE_CODE}:{code}"),
                "role_code": ROLE_CODE,
                "permission_code": code,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    for code in PERMISSIONS:
        connection.execute(
            sa.text(
                """
                DELETE FROM role_permissions
                WHERE role_id IN (SELECT id FROM roles WHERE code = :role_code)
                  AND permission_id IN (
                      SELECT id FROM permissions WHERE code = :permission_code
                  )
                """
            ),
            {"role_code": ROLE_CODE, "permission_code": code},
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM roles
            WHERE code = :role_code
              AND NOT EXISTS (
                  SELECT 1 FROM user_role_bindings WHERE role_id = roles.id
              )
            """
        ),
        {"role_code": ROLE_CODE},
    )
    for code in PERMISSIONS:
        connection.execute(
            sa.text(
                """
                DELETE FROM permissions
                WHERE code = :permission_code
                  AND NOT EXISTS (
                      SELECT 1
                      FROM role_permissions
                      WHERE permission_id = permissions.id
                  )
                """
            ),
            {"permission_code": code},
        )
    connection.execute(
        sa.text("DROP INDEX IF EXISTS uq_users_email_lower")
    )
