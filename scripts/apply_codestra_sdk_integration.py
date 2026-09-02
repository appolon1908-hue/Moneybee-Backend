"""Apply the reviewed Codestra SDK configuration integration exactly once.

This temporary branch tool performs narrow, fail-closed source edits that are
then validated by the repository's normal CI. It contains no credentials and is
removed after the resulting source commit is verified.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str, *, already: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if already in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"Expected one integration marker in {path!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "app/config.py",
        "    codestra_middleware_webhook_tolerance_seconds: int = 300\n",
        "    codestra_middleware_webhook_tolerance_seconds: int = 300\n"
        "    codestra_sdk_enabled: bool = False\n"
        "    codestra_sdk_capabilities_csv: str = \"\"\n",
        already="    codestra_sdk_enabled: bool = False\n",
    )
    replace_once(
        "app/config.py",
        "    @property\n    def provider_webhook_allowlist(self) -> set[str]:\n",
        "    @property\n"
        "    def codestra_sdk_capabilities(self) -> frozenset[str]:\n"
        "        return self._csv_set(self.codestra_sdk_capabilities_csv)\n\n"
        "    @property\n"
        "    def provider_webhook_allowlist(self) -> set[str]:\n",
        already="    def codestra_sdk_capabilities(self) -> frozenset[str]:\n",
    )
    replace_once(
        "app/config.py",
        "            if self.crm_provider == \"odoo\" and not all(\n",
        "            if self.codestra_sdk_enabled:\n"
        "                if self.middleware_provider != \"codestra\":\n"
        "                    raise ValueError(\n"
        "                        \"CODESTRA_SDK_ENABLED requires MIDDLEWARE_PROVIDER=codestra\"\n"
        "                    )\n"
        "                if not self.codestra_sdk_capabilities:\n"
        "                    raise ValueError(\n"
        "                        \"CODESTRA_SDK_ENABLED requires a nonempty capability allowlist\"\n"
        "                    )\n"
        "                if not self.source_sha:\n"
        "                    raise ValueError(\n"
        "                        \"CODESTRA_SDK_ENABLED requires immutable SOURCE_SHA provenance\"\n"
        "                    )\n"
        "            if self.crm_provider == \"odoo\" and not all(\n",
        already="CODESTRA_SDK_ENABLED requires MIDDLEWARE_PROVIDER=codestra",
    )
    for env_path in (".env.example", ".env.production.example"):
        replace_once(
            env_path,
            "CODESTRA_MIDDLEWARE_WEBHOOK_TOLERANCE_SECONDS=300\n",
            "CODESTRA_MIDDLEWARE_WEBHOOK_TOLERANCE_SECONDS=300\n"
            "# Server-only command SDK. Activation is a separate reviewed action.\n"
            "CODESTRA_SDK_ENABLED=false\n"
            "CODESTRA_SDK_CAPABILITIES_CSV=\n",
            already="CODESTRA_SDK_ENABLED=false\n",
        )
    replace_once(
        "ops/verify-runtime-env.py",
        "OPTIONAL_FALSE = {\n    \"ENABLE_EXTERNAL_DELIVERY\",\n",
        "OPTIONAL_FALSE = {\n"
        "    \"ENABLE_EXTERNAL_DELIVERY\",\n"
        "    \"CODESTRA_SDK_ENABLED\",\n",
        already='    "CODESTRA_SDK_ENABLED",\n',
    )
    print("Applied Codestra SDK configuration integration")


if __name__ == "__main__":
    main()
