from app import identity_models as identity


def test_local_user_table_stores_identity_metadata_but_never_passwords():
    columns = set(identity.User.__table__.columns.keys())
    assert {
        "id",
        "username",
        "email",
        "display_name",
        "email_verified_at",
        "registration_source",
        "last_login_at",
        "active",
        "created_at",
        "updated_at",
    }.issubset(columns)
    assert not {
        "password",
        "password_hash",
        "password_digest",
        "credential",
        "credential_secret",
        "refresh_token",
        "access_token",
    } & columns


def test_external_identity_binding_uses_issuer_and_subject():
    constraint_names = {
        constraint.name
        for constraint in identity.ExternalIdentity.__table__.constraints
        if constraint.name
    }
    assert "uq_external_identity_issuer_subject" in constraint_names
