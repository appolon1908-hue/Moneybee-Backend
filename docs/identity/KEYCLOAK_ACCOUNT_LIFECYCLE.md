# MoneyBee account lifecycle: Keycloak, Klyrow SMTP, Codestra middleware and Odoo

## Security ownership

- **Keycloak** is the only system that stores usernames, password credentials, MFA credentials, recovery state, login sessions and federated Google links.
- **MoneyBee** stores the local `issuer + subject` identity binding, organization membership, roles, permissions and lending-domain records. MoneyBee never receives or stores a user password.
- **Klyrow/Postal** is the SMTP transport for Keycloak verification, password-reset and security emails.
- **Codestra middleware** receives durable MoneyBee account and CRM events, invokes allowlisted Klyrow and Odoo adapters, deduplicates delivery and returns signed receipts.
- **Odoo** receives an approved CRM projection. It is not an authentication store and cannot write directly to MoneyBee PostgreSQL.

## Browser routes

```text
/auth/login                 username or email + password, or Google
/auth/register              borrower self-registration
/auth/forgot-password       reset-credentials flow
/auth/change-password       authenticated update-password action
/auth/verify-email          verify-email required action
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
4. allows new self-registration only from an allowlisted borrower client;
5. creates the MoneyBee user, borrower organization, membership and default borrower role in one transaction;
6. creates audit and idempotency evidence;
7. writes an `account.registered.v1` outbox event without credentials or tokens;
8. leaves external delivery disabled until Codestra, Klyrow and Odoo staging tests pass.

Configure the borrower client allowlist outside Git:

```dotenv
ACCOUNT_SELF_REGISTRATION_CLIENT_IDS=moneybee-borrower
```

Lender and administrator accounts must be invited and pre-provisioned. An unbound lender/admin token receives `INVITATION_REQUIRED` rather than a borrower account.

## Keycloak realm policy

Configure realm `codestra` with:

```text
User registration: ON
Login with email: ON
Email as username: OFF
Duplicate emails: OFF
Verify email: ON
Forgot password: ON
Remember me: ON
Edit username: OFF after registration
Brute-force detection: ON
Terms and conditions required action: ON after legal text approval
```

Keycloak 26.7 recommends verifying the email before credential setup for new self-registration. Keep the deprecated “always set password on register form” behavior disabled.

## Klyrow SMTP for identity emails

Configure Keycloak Realm Settings → Email using secret-managed values:

```text
Host: KLYROW_SMTP_HOST
Port: KLYROW_SMTP_PORT
From: accounts@moneybeeloan.com
From display name: MoneyBee
Reply-to: support@moneybeeloan.com
Authentication: enabled
STARTTLS: enabled where supported
Username: KLYROW_SMTP_USERNAME
Password: KLYROW_SMTP_PASSWORD
```

Do not store SMTP credentials in Git, frontend variables, browser storage, Docker image labels or MoneyBee database rows.

Keycloak sends:

- email verification;
- password reset;
- update-email verification;
- required-action and administrator-triggered credential emails.

MoneyBee welcome and CRM messages use the durable path instead:

```text
MoneyBee account transaction
→ account.registered.v1 outbox event
→ Codestra durable inbox
→ allowlisted Klyrow welcome-email adapter
→ allowlisted Odoo contact/lead projection
→ signed Codestra receipt
→ MoneyBee durable inbox and delivery evidence
```

## Required staging tests

```text
USERNAME_LOGIN=PASS
EMAIL_LOGIN=PASS
WRONG_PASSWORD=REJECTED
BRUTE_FORCE_LOCKOUT=PASS
REGISTRATION=PASS
DUPLICATE_USERNAME=REJECTED
DUPLICATE_EMAIL=REJECTED
EMAIL_VERIFICATION=PASS
UNVERIFIED_BOOTSTRAP=REJECTED
PASSWORD_RESET_EMAIL=PASS
EXPIRED_RESET_LINK=REJECTED
CHANGE_PASSWORD=PASS
OLD_PASSWORD_AFTER_CHANGE=REJECTED
GOOGLE_FIRST_LOGIN=PASS
GOOGLE_EXISTING_ACCOUNT_LINK=PASS
UNBOUND_LENDER_SELF_REGISTRATION=REJECTED
LOGOUT=PASS
LOGOUT_ALL_SESSIONS=PASS
MFA_ENROLLMENT=PASS
ACCOUNT_REGISTERED_EVENT=PASS
KLYROW_WELCOME_EMAIL_SANDBOX=PASS
ODOO_DUPLICATE_PROJECTION=PASS
SIGNED_RECEIPT=PASS
```

External delivery, Odoo writes and production email remain disabled until this evidence is reviewed.
