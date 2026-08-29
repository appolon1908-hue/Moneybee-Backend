# MoneyBee account lifecycle: Keycloak, Klyrow SMTP, Codestra Middleware and Odoo

## Security ownership

- **Keycloak** is the only system that stores usernames, password credentials, MFA credentials, recovery state, login sessions and federated identity links.
- **MoneyBee** stores the local `issuer + subject` identity binding, organization membership, roles, permissions and lending-domain records. MoneyBee never receives or stores a user password, reset token or verification secret.
- **Klyrow/Postal** is transport for Keycloak verification, password-reset and security email. It does not become the password authority.
- **Codestra Middleware** receives durable MoneyBee account and CRM events and governs approved cross-system delivery.
- **Odoo** receives an approved CRM projection. It is not an authentication store and cannot write directly to MoneyBee PostgreSQL.

## Browser routes

```text
/auth/login                 Keycloak login
/auth/register              borrower self-registration through the gated Keycloak flow
/auth/forgot-password       Keycloak reset-credentials flow
/auth/change-password       authenticated Keycloak update-password action
/auth/verify-email          Keycloak verify-email required action
/auth/account               Keycloak Account Console
/auth/logout                OIDC logout
/auth/callback              Authorization Code + PKCE callback
/auth/silent-callback       silent session renewal
/auth/session-expired       recovery screen
/403                        wrong-role or denied account
```

## Backend bootstrap

After a successful Keycloak callback, the portal calls:

```http
POST /api/v2/auth/bootstrap
Authorization: Bearer <Keycloak access token>
Idempotency-Key: <stable UUID>
```

The endpoint:

1. validates issuer, signature, audience, expiry and required claims;
2. requires `email_verified=true`;
3. binds only by Keycloak `issuer + subject` and never by email alone;
4. allows new self-registration only from the allowlisted borrower client;
5. creates the MoneyBee user, borrower organization, membership and default borrower role in one transaction;
6. creates audit and idempotency evidence;
7. writes an `account.registered.v1` outbox event without credentials or tokens;
8. leaves external delivery disabled until Middleware, Klyrow and Odoo staging tests pass.

The borrower allowlist is explicit:

```dotenv
ACCOUNT_SELF_REGISTRATION_CLIENT_IDS=moneybee-borrower
```

Lender and administrator accounts must be invited or privileged-provisioned. An unbound lender/admin token receives `INVITATION_REQUIRED` rather than a borrower account.

## Keycloak registration policy

MoneyBee does not enable unrestricted realm-wide registration by itself. The central Keycloak GitOps policy owns a `codestra-registration-gate` and permits `moneybee-borrower` only after the gated registration flow is installed and read back.

Source desired state remains fail closed:

```text
Realm registration before gated-flow readback: OFF
MoneyBee borrower registration: DECLARED_GATED
MoneyBee lender registration: BLOCKED
MoneyBee admin registration: BLOCKED
Verify email: ON
Forgot password: ON
Duplicate emails: OFF
Edit username: OFF
Brute-force protection: ON
Password/reset authority: KEYCLOAK_ONLY
```

A workflow or MoneyBee application setting must never bypass the central Keycloak gate.

## Klyrow SMTP for identity emails

The reviewed shared Keycloak transport uses secret-managed Klyrow SMTP values:

```text
Host: mail.klyrow.com
Port: 25
Authentication: enabled
STARTTLS: enabled
Username: protected KC_SMTP_USERNAME value
Password: protected KC_SMTP_PASSWORD value
Stream: SECURITY
```

Keycloak currently has one realm SMTP configuration. MoneyBee must not assume it can independently replace the shared realm `From:` address. The exact realm security sender and reply-to identity are managed centrally in the Keycloak repository and must be verified before activation.

Do not store SMTP credentials in Git, frontend variables, browser storage, Docker image labels or MoneyBee database rows.

Keycloak sends:

- email verification;
- password reset;
- update-email verification;
- required-action and administrator-triggered credential email.

Reset tokens, temporary passwords, verification secrets and complete action URLs must never enter MoneyBee, Middleware, Kong, Odoo, n8n or ordinary application logs.

## MoneyBee business integration boundary

MoneyBee business/account events use the durable Middleware path:

```text
MoneyBee account transaction
→ account.registered.v1 outbox event
→ dedicated MoneyBee Middleware ingress
→ governed downstream adapter/projection
→ signed Middleware receipt
→ MoneyBee durable inbox and delivery evidence
```

MoneyBee must not use public Kong (`api.codestra.co`) as its configured Middleware destination. The approved production template uses the dedicated `moneybee-events.codestra.co` ingress, with external delivery disabled by default.

Welcome/CRM email is business communication and may be coordinated through Middleware. Credential verification/reset email is different and stays directly under Keycloak → Klyrow SECURITY SMTP.

## Required staging tests

```text
USERNAME_LOGIN=PASS
EMAIL_LOGIN=PASS
WRONG_PASSWORD=REJECTED
BRUTE_FORCE_LOCKOUT=PASS
BORROWER_REGISTRATION=PASS
LENDER_SELF_REGISTRATION=REJECTED
ADMIN_SELF_REGISTRATION=REJECTED
UNAPPROVED_CLIENT_REGISTRATION=REJECTED
EMAIL_VERIFICATION=PASS
UNVERIFIED_BOOTSTRAP=REJECTED
PASSWORD_RESET_EMAIL=PASS
EXPIRED_RESET_LINK=REJECTED
RESET_REPLAY=REJECTED
CHANGE_PASSWORD=PASS
OLD_PASSWORD_AFTER_CHANGE=REJECTED
LOGOUT=PASS
LOGOUT_ALL_SESSIONS=PASS
MFA_ENROLLMENT=PASS
KEYCLOAK_SMTP_STARTTLS=PASS
KEYCLOAK_SMTP_AUTH=PASS
RESET_MATERIAL_IN_MIDDLEWARE=ZERO
DIRECT_PUBLIC_KONG_MIDDLEWARE_CONFIG=REJECTED
ACCOUNT_REGISTERED_EVENT=PASS
ODOO_DUPLICATE_PROJECTION=PASS
SIGNED_RECEIPT=PASS
```

External delivery, Odoo writes and production financial capabilities remain disabled until the required evidence is reviewed. No Git change alone is production activation.
