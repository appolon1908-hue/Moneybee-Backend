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

LIVE_EVIDENCE_FLAGS = {
    "MONEYBEE_POSTAL_DKIM_ROTATED": (),
    "MONEYBEE_POSTAL_OLD_SELECTOR_REMOVED": (),
    "MONEYBEE_POSTAL_SPF": ("SPF",),
    "MONEYBEE_POSTAL_DKIM": ("DKIM",),
    "MONEYBEE_POSTAL_DMARC_ALIGNMENT": ("DMARC",),
    "MONEYBEE_POSTAL_MX": ("MONEYBEE_DOMAIN_FULLY_CONNECTED",),
    "MONEYBEE_POSTAL_RETURN_PATH": ("MONEYBEE_DOMAIN_FULLY_CONNECTED",),
    "MONEYBEE_POSTAL_TLS": ("STARTTLS",),
    "MONEYBEE_POSTAL_BOUNCE_HANDLING": (),
    "MONEYBEE_POSTAL_SUPPRESSION_HANDLING": (),
    "KEYCLOAK_SMTP_TEST": (),
    "KEYCLOAK_VERIFY_EMAIL_TEST": (),
    "KEYCLOAK_PASSWORD_RESET_TEST": (),
    "KEYCLOAK_EXPIRED_LINK_TEST": (),
    "KEYCLOAK_WRONG_RECIPIENT_TEST": (),
    "ACCOUNT_REGISTERED_OUTBOX": (),
    "KLYROW_WELCOME_EMAIL_SANDBOX": (),
}

NEGATIVE_CONTROL_FLAGS = {
    "DIRECT_APP_SMTP_ACCESS": "BLOCKED",
    "DIRECT_APP_KLYROW_ACCESS": "BLOCKED",
    "RESET_TOKEN_OUTSIDE_KEYCLOAK": "BLOCKED",
    "PLAINTEXT_SMTP_SECRET_IN_GIT": "BLOCKED",
}


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


def load_evidence_file(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    evidence_path = Path(path)
    if not evidence_path.is_absolute():
        evidence_path = ROOT / evidence_path
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata", {})
    checks = metadata.get("checks", {})
    if not isinstance(checks, dict):
        raise ValueError("Evidence metadata.checks must be an object")
    return {
        str(key).strip().upper(): str(value).strip().upper()
        for key, value in checks.items()
        if str(key).strip()
    }


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


def evidence_value(
    evidence: dict[str, str],
    name: str,
    aliases: tuple[str, ...] = (),
) -> str:
    keys = (name, *aliases)
    for key in keys:
        normalized = key.strip().upper()
        value = os.environ.get(normalized, "").strip().upper()
        if value:
            return value
        if normalized in evidence:
            return evidence[normalized]
    return ""


def check_live_evidence(
    require_live_evidence: bool,
    evidence: dict[str, str],
) -> list[CheckResult]:
    results = []
    for name, aliases in LIVE_EVIDENCE_FLAGS.items():
        value = evidence_value(evidence, name, aliases)
        if value == "PASS":
            detail = "PASS"
            if aliases and name not in evidence and not os.environ.get(name):
                detail = f"PASS via {', '.join(aliases)}"
            results.append(pass_check(f"evidence.{name}", detail))
        elif require_live_evidence:
            results.append(fail_check(f"evidence.{name}", "set to PASS before production launch"))
        else:
            results.append(skip_check(f"evidence.{name}", "not required for repository CI"))
    for name, expected in NEGATIVE_CONTROL_FLAGS.items():
        value = evidence_value(evidence, name)
        if value == expected:
            results.append(pass_check(f"evidence.{name}", expected))
        elif require_live_evidence:
            results.append(fail_check(f"evidence.{name}", f"set to {expected} before production launch"))
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
    parser.add_argument(
        "--evidence-file",
        help="non-secret readiness evidence JSON with metadata.checks",
    )
    args = parser.parse_args()
    evidence = load_evidence_file(args.evidence_file)

    results = [
        *check_keycloak_policy(load_keycloak_policy()),
        *check_default_provider_locks(),
        *check_live_evidence(args.require_live_evidence, evidence),
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
