"""MoneyBee backend certification report.

This certifies backend repository gates only. It does not authorize staging or
production deployment, image release, provider activation, or live writes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    status: str
    detail: str


class CommandRunner(Protocol):
    def __call__(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        ...


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def summarize_output(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if not lines:
        return f"exit={result.returncode}"
    interesting = [
        line
        for line in lines
        if any(
            marker in line
            for marker in (
                "passed",
                "failed",
                "SMOKE_SUMMARY",
                "OpenAPI contract verified",
                "All checks passed",
                "deployment_permitted",
                "configuration_checksum",
                "ERROR=",
            )
        )
    ]
    selected = interesting[-3:] if interesting else lines[-3:]
    return f"exit={result.returncode}; " + " | ".join(selected)


def command_check(
    name: str,
    command: list[str],
    runner: CommandRunner,
    *,
    expected_exit_codes: set[int] | None = None,
) -> CertificationCheck:
    result = runner(command, ROOT)
    expected = expected_exit_codes or {0}
    return CertificationCheck(
        name=name,
        status="PASS" if result.returncode in expected else "FAIL",
        detail=summarize_output(result),
    )


def launch_gate_check(runner: CommandRunner, frontend_root: Path) -> CertificationCheck:
    result = runner(
        [
            sys.executable,
            "scripts/production_launch_check.py",
            "--frontend-root",
            str(frontend_root),
            "--json",
        ],
        ROOT,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return CertificationCheck(
            name="backend.production_launch_gate.fail_closed",
            status="FAIL",
            detail=summarize_output(result),
        )
    deployment_permitted = payload.get("final_status") == "READY"
    totals = payload.get("totals", {})
    return CertificationCheck(
        name="backend.production_launch_gate.fail_closed",
        status="PASS" if result.returncode != 0 and not deployment_permitted else "FAIL",
        detail=(
            "deployment remains blocked; "
            f"pass={totals.get('PASS', 0)} blocked={totals.get('BLOCKED', 0)} "
            f"fail={totals.get('FAIL', 0)}"
        ),
    )


def checksum_gate_check(runner: CommandRunner, frontend_root: Path) -> CertificationCheck:
    result = runner(
        [
            sys.executable,
            "ops/compute-configuration-checksum.py",
            "--frontend-root",
            str(frontend_root),
            "--json",
        ],
        ROOT,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return CertificationCheck(
            name="backend.release_configuration_checksum.git_blob",
            status="FAIL",
            detail=summarize_output(result),
        )
    files = payload.get("files", [])
    uses_git_blobs = isinstance(files, list) and files and all(
        item.get("source") == "git_blob" for item in files if isinstance(item, dict)
    )
    clean = payload.get("backend_dirty") is False
    checksum = payload.get("configuration_checksum")
    return CertificationCheck(
        name="backend.release_configuration_checksum.git_blob",
        status="PASS" if result.returncode == 0 and uses_git_blobs and clean else "FAIL",
        detail=f"checksum={checksum}; backend_dirty={payload.get('backend_dirty')}; source=git_blob",
    )


def container_gate_check(include_containers: bool, runner: CommandRunner) -> CertificationCheck:
    if not include_containers:
        return CertificationCheck(
            name="backend.container_validation",
            status="BLOCKED",
            detail="not run locally; release image workflow must publish and scan immutable digests",
        )
    return command_check(
        "backend.container_validation",
        ["docker", "build", "-t", "moneybee-backend:test", "."],
        runner,
    )


def collect_certification(
    runner: CommandRunner = run_command,
    *,
    frontend_root: Path | None = None,
    include_containers: bool = False,
) -> list[CertificationCheck]:
    resolved_frontend_root = frontend_root or ROOT.parent / "Moneybee-frontend-"
    return [
        command_check(
            "backend.static_analysis",
            ["ruff", "check", "app", "scripts", "tests", "ops", "--output-format=concise"],
            runner,
        ),
        command_check(
            "backend.compileall",
            [sys.executable, "-m", "compileall", "-q", "app", "scripts", "ops", "migrations"],
            runner,
        ),
        command_check(
            "backend.release_locks.fail_closed_shape",
            [
                sys.executable,
                "ops/validate-release-lock.py",
                "--runtime-lock",
                "deploy/runtime-paths.lock.json",
                "--release-lock",
                "deploy/release.lock.json",
                "--allow-unverified",
            ],
            runner,
        ),
        checksum_gate_check(runner, resolved_frontend_root),
        command_check(
            "backend.openapi_contract",
            [sys.executable, "scripts/verify_openapi_contract.py"],
            runner,
        ),
        command_check("backend.pytest", [sys.executable, "-m", "pytest", "-q"], runner),
        command_check("backend.smoke_api", [sys.executable, "scripts/smoke_api.py"], runner),
        launch_gate_check(runner, resolved_frontend_root),
        container_gate_check(include_containers, runner),
    ]


def final_status(checks: list[CertificationCheck]) -> str:
    if any(item.status == "FAIL" for item in checks):
        return "FAIL"
    if any(item.status == "BLOCKED" for item in checks):
        return "PARTIAL"
    return "PASS"


def git_sha() -> str:
    result = run_command(["git", "rev-parse", "HEAD"], ROOT)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_evidence(path: Path, checks: list[CertificationCheck]) -> None:
    generated = datetime.now(UTC)
    payload = {
        "$schema": "../readiness/evidence.schema.json",
        "gate": "BACKEND_CERTIFICATION",
        "status": final_status(checks),
        "source_sha": git_sha(),
        "environment": "ci",
        "evidence_type": "backend-certification-check",
        "evidence_reference": "Generated by scripts/backend_certification_check.py from local backend source gates.",
        "generated_at": generated.isoformat(),
        "expires_at": (generated + timedelta(days=30)).isoformat(),
        "approved_by": None,
        "metadata": {
            "scope": "MoneyBee backend only",
            "deployment_permitted": False,
            "checks": [asdict(item) for item in checks],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-root", type=Path, default=ROOT.parent / "Moneybee-frontend-")
    parser.add_argument("--include-containers", action="store_true")
    parser.add_argument("--write-evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks = collect_certification(
        frontend_root=args.frontend_root,
        include_containers=args.include_containers,
    )
    status = final_status(checks)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "deployment_permitted": False,
        "checks": [asdict(item) for item in checks],
    }
    if args.write_evidence:
        write_evidence(args.write_evidence, checks)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in checks:
            print(f"{item.status} {item.name}: {item.detail}")
        print(f"BACKEND_CERTIFICATION status={status} deployment_permitted=false")
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
