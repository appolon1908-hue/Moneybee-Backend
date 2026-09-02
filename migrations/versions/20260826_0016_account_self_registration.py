"""Add verified account metadata and seed the borrower self-registration role.

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


def _id(value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"moneybee:{value}")


def _uuid_statement(statement: str) -> sa.TextClause:
    return sa.text(statement).bindparams(sa.bindparam("id", type_=sa.Uuid()))


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("registration_source", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_last_login_at", "users", ["last_login_at"])

    connection = op.get_bind()
    duplicate_email = connection.execute(
        sa.text(
            """
            SELECT lower(email) AS normalized_email
            FROM users
            WHERE email IS NOT NULL
            GROUP BY lower(email)
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate_email is not None:
        raise RuntimeError(
            "Cannot enable verified account registration while duplicate "
            "case-insensitive user emails exist."
        )
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
        _uuid_statement(
            """
            INSERT INTO roles (id, code, description, active)
            VALUES (:id, :code, :description, true)
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
            _uuid_statement(
                """
                INSERT INTO permissions (id, code, description)
                VALUES (:id, :code, :description)
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
            _uuid_statement(
                """
                INSERT INTO role_permissions (id, role_id, permission_id)
                SELECT :id, role.id, permission.id
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
    connection.execute(sa.text("DROP INDEX IF EXISTS uq_users_email_lower"))
    op.drop_index("ix_users_last_login_at", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "registration_source")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "username")
