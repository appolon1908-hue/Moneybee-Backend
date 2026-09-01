"""MoneyBee production launch checklist.

The checker is intentionally evidence-based. It can verify local repository
assets and optional live URLs, but external approvals must be supplied through
environment variables or a non-secret evidence file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT.parent / "Moneybee-frontend-"
DEFAULT_MARKETING_ROOT = FRONTEND_ROOT / "apps" / "marketing"
IDENTITY_EVIDENCE = ROOT / "docs" / "evidence" / "identity-email-activation-2026-08-29.json"

REQUIRED_LANDING_COUNT = 20
REQUIRED_POLICY_SLUGS = {
    "privacy",
    "terms",
    "cookie-notice",
    "advertising-disclosure",
    "privacy-choices",
    "consents-and-disclosures",
    "accessibility",
    "complaints",
}
REQUIRED_EXTERNAL_FLAGS = {
    "GOOGLE_SEARCH_CONSOLE_VERIFIED": "PASS",
    "GOOGLE_ADSENSE_SITE_APPROVED": "PASS",
    "LEGAL_PRIVACY_APPROVED": "PASS",
    "LEGAL_TERMS_APPROVED": "PASS",
    "LEGAL_COOKIE_NOTICE_APPROVED": "PASS",
    "LEGAL_ADVERTISING_DISCLOSURE_APPROVED": "PASS",
    "STAGING_BROWSER_LOGIN_E2E": "PASS",
    "STAGING_PUBLIC_FORM_E2E": "PASS",
    "STAGING_SECURITY_HEADERS_E2E": "PASS",
    "PROVIDER_ACTIVATION_REVIEWED": "PASS",
}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def check(name: str, status: str, detail: str) -> Check:
    return Check(name=name, status=status, detail=detail)


def load_evidence(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    checks = payload.get("metadata", {}).get("checks", {})
    if not isinstance(checks, dict):
        return {}
    return {
        str(key).strip().upper(): str(value).strip().upper()
        for key, value in checks.items()
        if str(key).strip()
    }


def evidence_value(evidence: dict[str, str], name: str) -> str:
    normalized = name.upper()
    return os.getenv(normalized, "").strip().upper() or evidence.get(normalized, "")


def git_short_sha(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def repo_marketing_checks(marketing_root: Path) -> list[Check]:
    src = marketing_root / "src"
    required_assets = (
        src / "landingPages.ts",
        src / "resourcePages.ts",
        marketing_root / "public" / "sitemap.xml",
        marketing_root / "public" / "robots.txt",
        marketing_root / "public" / "ads.txt",
        marketing_root / "index.html",
    )
    missing_assets = [
        str(path.relative_to(marketing_root))
        for path in required_assets
        if not path.is_file()
    ]
    if missing_assets:
        return [
            check(
                "marketing.repository.assets",
                "BLOCKED",
                "frontend marketing checkout is incomplete: " + ", ".join(missing_assets),
            )
        ]

    landing = read_text(src / "landingPages.ts")
    resources = read_text(src / "resourcePages.ts")
    sitemap = read_text(marketing_root / "public" / "sitemap.xml")
    robots = read_text(marketing_root / "public" / "robots.txt")
    ads = read_text(marketing_root / "public" / "ads.txt")
    index = read_text(marketing_root / "index.html")

    landing_count = landing.count('title: "')
    results = [
        check(
            "marketing.landing_pages.count",
            "PASS" if landing_count >= REQUIRED_LANDING_COUNT else "FAIL",
            f"{landing_count} landing pages found",
        ),
        check(
            "marketing.seo.runtime_meta",
            "PASS"
            if (src / "seo.ts").exists()
            and "application/ld+json" in read_text(src / "seo.ts")
            else "FAIL",
            "route metadata and JSON-LD are configured",
        ),
        check(
            "marketing.cookie_consent",
            "PASS" if (src / "components" / "CookieConsent.vue").exists() else "FAIL",
            "cookie consent component exists",
        ),
        check(
            "marketing.robots",
            "PASS" if "Sitemap: https://moneybeeloan.com/sitemap.xml" in robots else "FAIL",
            "robots.txt points to production sitemap",
        ),
        check(
            "marketing.sitemap",
            "PASS"
            if sitemap.count("<url>") >= REQUIRED_LANDING_COUNT + len(REQUIRED_POLICY_SLUGS)
            else "FAIL",
            f"{sitemap.count('<url>')} sitemap URLs found",
        ),
        check(
            "marketing.html_head",
            "PASS" if "canonical" in index and "og:title" in index else "FAIL",
            "baseline canonical and social tags exist",
        ),
    ]

    for slug in REQUIRED_POLICY_SLUGS:
        results.append(
            check(
                f"marketing.policy.{slug}",
                "PASS" if slug in resources else "FAIL",
                "required policy page is defined",
            )
        )

    publisher_id = os.getenv("GOOGLE_ADSENSE_PUBLISHER_ID", "").strip()
    has_real_adsense = (
        bool(publisher_id)
        and publisher_id in ads
        and "pub-0000000000000000" not in ads
    )
    results.append(
        check(
            "google.ads_txt.publisher",
            "PASS" if has_real_adsense else "BLOCKED",
            "real Google AdSense publisher ID is required in apps/marketing/public/ads.txt",
        )
    )
    return results


def identity_email_checks(evidence: dict[str, str]) -> list[Check]:
    mapped = {
        "identity.keycloak.registration": "KEYCLOAK_REGISTRATION_ENABLED",
        "identity.keycloak.reset_password": "KEYCLOAK_RESET_PASSWORD_ENABLED",
        "identity.keycloak.email_verification": "KEYCLOAK_EMAIL_VERIFICATION",
        "identity.smtp.connectivity": "KLYROW_SMTP_CONNECTIVITY",
        "identity.smtp.starttls": "STARTTLS",
        "identity.dns.spf": "SPF",
        "identity.dns.dkim": "DKIM",
        "identity.dns.dmarc": "DMARC",
        "identity.control.direct_smtp_blocked": "DIRECT_APP_SMTP_ACCESS",
        "identity.control.reset_tokens_external": "RESET_TOKEN_OUTSIDE_KEYCLOAK",
    }
    results = []
    for name, flag in mapped.items():
        expected = "BLOCKED" if name.startswith("identity.control") else "PASS"
        value = evidence_value(evidence, flag)
        results.append(
            check(
                name,
                "PASS" if value == expected else "BLOCKED",
                f"{flag}={value or 'missing'}",
            )
        )
    for flag in (
        "KEYCLOAK_SMTP_TEST",
        "KEYCLOAK_VERIFY_EMAIL_TEST",
        "KEYCLOAK_PASSWORD_RESET_TEST",
        "KEYCLOAK_EXPIRED_LINK_TEST",
        "KEYCLOAK_WRONG_RECIPIENT_TEST",
        "MONEYBEE_POSTAL_BOUNCE_HANDLING",
        "MONEYBEE_POSTAL_SUPPRESSION_HANDLING",
    ):
        value = evidence_value(evidence, flag)
        results.append(
            check(
                f"identity.live.{flag.lower()}",
                "PASS" if value == "PASS" else "BLOCKED",
                f"{flag}={value or 'missing'}",
            )
        )
    return results


def external_approval_checks(evidence: dict[str, str]) -> list[Check]:
    return [
        check(
            f"external.{name.lower()}",
            "PASS" if evidence_value(evidence, name) == expected else "BLOCKED",
            f"{name} must be {expected}",
        )
        for name, expected in REQUIRED_EXTERNAL_FLAGS.items()
    ]


def probe_url(url: str, timeout: float = 10.0) -> Check:
    request = Request(url, headers={"User-Agent": "MoneyBeeLaunchCheck/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        return check(f"url.{url}", "FAIL", f"HTTP {exc.code}")
    except URLError as exc:
        return check(f"url.{url}", "BLOCKED", str(exc.reason))
    except OSError as exc:
        return check(f"url.{url}", "BLOCKED", str(exc))

    security = []
    if headers.get("strict-transport-security"):
        security.append("hsts")
    if headers.get("content-security-policy"):
        security.append("csp")
    return check(
        f"url.{url}",
        "PASS" if 200 <= status < 400 else "FAIL",
        f"HTTP {status}; security headers: {', '.join(security) or 'not observed'}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-root", type=Path, default=FRONTEND_ROOT)
    parser.add_argument("--evidence-file", type=Path, default=IDENTITY_EVIDENCE)
    parser.add_argument("--url", action="append", default=[], help="Optional live URL to probe")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    evidence = load_evidence(args.evidence_file)
    marketing_root = args.frontend_root / "apps" / "marketing"
    checks = [
        *repo_marketing_checks(marketing_root),
        *identity_email_checks(evidence),
        *external_approval_checks(evidence),
        *(probe_url(url) for url in args.url),
    ]
    totals = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "SKIP": 0}
    for item in checks:
        totals[item.status] = totals.get(item.status, 0) + 1

    final_status = "READY" if totals["FAIL"] == 0 and totals["BLOCKED"] == 0 else "BLOCKED"
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "final_status": final_status,
        "backend_sha": git_short_sha(ROOT),
        "frontend_sha": git_short_sha(args.frontend_root),
        "totals": totals,
        "checks": [asdict(item) for item in checks],
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in checks:
            print(f"{item.status} {item.name}: {item.detail}")
        print(
            "LAUNCH_SUMMARY "
            f"status={final_status} pass={totals['PASS']} "
            f"blocked={totals['BLOCKED']} fail={totals['FAIL']}"
        )
    return 0 if final_status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
