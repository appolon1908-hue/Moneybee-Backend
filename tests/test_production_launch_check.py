import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_launch_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("production_launch_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _marketing_fixture(tmp_path: Path, checker) -> Path:
    marketing_root = tmp_path / "Moneybee-frontend-" / "apps" / "marketing"
    landing_pages = "\n".join(
        f'{{ slug: "landing-{index}", title: "Landing {index}" }},'
        for index in range(checker.REQUIRED_LANDING_COUNT)
    )
    policy_pages = "\n".join(
        f'{{ slug: "{slug}" }},' for slug in sorted(checker.REQUIRED_POLICY_SLUGS)
    )
    sitemap_count = checker.REQUIRED_LANDING_COUNT + len(checker.REQUIRED_POLICY_SLUGS)

    _write(marketing_root / "src" / "landingPages.ts", landing_pages)
    _write(marketing_root / "src" / "resourcePages.ts", policy_pages)
    _write(
        marketing_root / "src" / "seo.ts",
        'const structuredDataType = "application/ld+json";\n',
    )
    _write(
        marketing_root / "src" / "components" / "CookieConsent.vue",
        "<template><aside>Cookie preferences</aside></template>\n",
    )
    _write(
        marketing_root / "public" / "sitemap.xml",
        "<urlset>\n" + ("<url></url>\n" * sitemap_count) + "</urlset>\n",
    )
    _write(
        marketing_root / "public" / "robots.txt",
        "User-agent: *\nAllow: /\nSitemap: https://moneybeeloan.com/sitemap.xml\n",
    )
    _write(
        marketing_root / "public" / "ads.txt",
        "google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0\n",
    )
    _write(
        marketing_root / "index.html",
        '<link rel="canonical" href="https://moneybeeloan.com/">\n'
        '<meta property="og:title" content="MoneyBee">\n',
    )
    return marketing_root


def test_launch_check_separates_repo_ready_from_external_blockers(
    tmp_path, monkeypatch
):
    checker = load_checker()
    marketing_root = _marketing_fixture(tmp_path, checker)
    monkeypatch.delenv("GOOGLE_ADSENSE_PUBLISHER_ID", raising=False)
    evidence = checker.load_evidence(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "evidence"
        / "identity-email-activation-2026-08-29.json"
    )

    checks = [
        *checker.repo_marketing_checks(marketing_root),
        *checker.identity_email_checks(evidence),
        *checker.external_approval_checks(evidence),
    ]
    statuses = {item.name: item.status for item in checks}

    assert statuses["marketing.landing_pages.count"] == "PASS"
    assert statuses["marketing.policy.privacy"] == "PASS"
    assert statuses["identity.dns.dkim"] == "PASS"
    assert statuses["identity.control.reset_tokens_external"] == "PASS"
    assert statuses["identity.live.keycloak_password_reset_test"] == "BLOCKED"
    assert statuses["google.ads_txt.publisher"] == "BLOCKED"
    assert statuses["external.google_search_console_verified"] == "BLOCKED"


def test_launch_check_blocks_an_incomplete_frontend_checkout(tmp_path):
    checker = load_checker()
    checks = checker.repo_marketing_checks(tmp_path / "apps" / "marketing")

    assert len(checks) == 1
    assert checks[0].name == "marketing.repository.assets"
    assert checks[0].status == "BLOCKED"
    assert "landingPages.ts" in checks[0].detail
