"""Check MoneyBee identity email and password-recovery readiness.

This validates the committed Keycloak account lifecycle template and optional
live evidence flags. It intentionally does not require or print SMTP secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KEYCLOAK_POLICY = ROOT / "deploy" / "keycloak" / "codestra-moneybee-account-policy.example.json"

EXPECTED_SMTP_PLACEHOLDERS = {
    "host": "${KLYROW_SMTP_HOST}",
    "port": "${KLYROW_SMTP_PORT}",
    "user": "${KLYROW_SMTP_USERNAME}",
    "password": "${KLYROW_SMTP_PASSWORD}",
}

LIVE_EVIDENCE_FLAGS = (
    "MONEYBEE_POSTAL_DKIM_ROTATED",
    "MONEYBEE_POSTAL_OLD_SELECTOR_REMOVED",
    "MONEYBEE_POSTAL_SPF",
    "MONEYBEE_POSTAL_DKIM",
    "MONEYBEE_POSTAL_DMARC_ALIGNMENT",
    "MONEYBEE_POSTAL_MX",
    "MONEYBEE_POSTAL_RETURN_PATH",
    "MONEYBEE_POSTAL_TLS",
    "MONEYBEE_POSTAL_BOUNCE_HANDLING",
    "MONEYBEE_POSTAL_SUPPRESSION_HANDLING",
    "KEYCLOAK_SMTP_TEST",
    "KEYCLOAK_VERIFY_EMAIL_TEST",
    "KEYCLOAK_PASSWORD_RESET_TEST",
    "KEYCLOAK_EXPIRED_LINK_TEST",
    "KEYCLOAK_WRONG_RECIPIENT_TEST",
    "ACCOUNT_REGISTERED_OUTBOX",
    "KLYROW_WELCOME_EMAIL_SANDBOX",
)


@dataclass(frozen=True)
class CheckResult:
    status: str
    name: str
    detail: str


def pass_check(name: str, detail: str) -> CheckResult:
    return CheckResult("PASS", name, detail)


def fail_check(name: str, detail: str) -> CheckResult:
    return CheckResult("FAIL", name, detail)


def skip_check(name: str, detail: str) -> CheckResult:
    return CheckResult("SKIP", name, detail)


def load_keycloak_policy() -> dict[str, Any]:
    return json.loads(KEYCLOAK_POLICY.read_text(encoding="utf-8"))


def check_keycloak_policy(policy: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    required_flags = {
        "registrationAllowed": True,
        "registrationEmailAsUsername": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "verifyEmail": True,
        "resetPasswordAllowed": True,
        "bruteForceProtected": True,
    }
    for key, expected in required_flags.items():
        actual = policy.get(key)
        if actual == expected:
            results.append(pass_check(f"keycloak.{key}", f"expected {expected!r}"))
        else:
            results.append(fail_check(f"keycloak.{key}", f"got {actual!r}; expected {expected!r}"))

    smtp = policy.get("smtpServer")
    if not isinstance(smtp, dict):
        results.append(fail_check("keycloak.smtpServer", "SMTP server block is missing"))
        return results

    for key, expected in EXPECTED_SMTP_PLACEHOLDERS.items():
        actual = smtp.get(key)
        if actual == expected:
            results.append(pass_check(f"keycloak.smtpServer.{key}", "uses secret placeholder"))
        else:
            results.append(
                fail_check(
                    f"keycloak.smtpServer.{key}",
                    "must use the documented Klyrow/Postal secret placeholder",
                )
            )

    smtp_checks = {
        "from": "accounts@moneybeeloan.com",
        "replyTo": "support@moneybeeloan.com",
        "auth": "true",
        "starttls": "true",
        "ssl": "false",
    }
    for key, expected in smtp_checks.items():
        actual = smtp.get(key)
        if actual == expected:
            results.append(pass_check(f"keycloak.smtpServer.{key}", f"expected {expected!r}"))
        else:
            results.append(fail_check(f"keycloak.smtpServer.{key}", f"got {actual!r}"))

    return results


def check_default_provider_locks() -> list[CheckResult]:
    from app.config import Settings

    settings = Settings(_env_file=None)
    results = []
    if settings.email_provider == "disabled":
        results.append(pass_check("settings.EMAIL_PROVIDER", "disabled by default"))
    else:
        results.append(fail_check("settings.EMAIL_PROVIDER", f"default is {settings.email_provider!r}"))
    if settings.sms_provider == "disabled":
        results.append(pass_check("settings.SMS_PROVIDER", "disabled by default"))
    else:
        results.append(fail_check("settings.SMS_PROVIDER", f"default is {settings.sms_provider!r}"))
    if not settings.sendgrid_api_key and not settings.sendgrid_from_email:
        results.append(pass_check("settings.SENDGRID", "no committed live default credentials"))
    else:
        results.append(fail_check("settings.SENDGRID", "live defaults must not be committed"))
    if not settings.twilio_account_sid and not settings.twilio_auth_token:
        results.append(pass_check("settings.TWILIO", "no committed live default credentials"))
    else:
        results.append(fail_check("settings.TWILIO", "live defaults must not be committed"))
    return results


def check_live_evidence(require_live_evidence: bool) -> list[CheckResult]:
    results = []
    for name in LIVE_EVIDENCE_FLAGS:
        value = os.environ.get(name, "").strip().upper()
        if value == "PASS":
            results.append(pass_check(f"evidence.{name}", "PASS"))
        elif require_live_evidence:
            results.append(fail_check(f"evidence.{name}", "set to PASS before production launch"))
        else:
            results.append(skip_check(f"evidence.{name}", "not required for repository CI"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-live-evidence",
        action="store_true",
        help="fail unless all Postal/Keycloak live evidence flags are PASS",
    )
    args = parser.parse_args()

    results = [
        *check_keycloak_policy(load_keycloak_policy()),
        *check_default_provider_locks(),
        *check_live_evidence(args.require_live_evidence),
    ]

    totals = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    for result in results:
        totals[result.status] += 1
        print(f"{result.status} {result.name}: {result.detail}")
    print(
        "IDENTITY_EMAIL_SUMMARY "
        f"pass={totals['PASS']} skip={totals['SKIP']} fail={totals['FAIL']}"
    )
    return 1 if totals["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
