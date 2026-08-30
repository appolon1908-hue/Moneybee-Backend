import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backend_certification_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("backend_certification_check", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    joined = " ".join(command)
    if "production_launch_check.py" in joined:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {
                    "final_status": "BLOCKED",
                    "totals": {"PASS": 24, "BLOCKED": 40, "FAIL": 0, "SKIP": 0},
                }
            ),
            stderr="",
        )
    if "compute-configuration-checksum.py" in joined:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "configuration_checksum": "a" * 64,
                    "backend_dirty": False,
                    "files": [
                        {"scope": "backend", "path": "deploy/Caddyfile.staging", "source": "git_blob"},
                        {"scope": "frontend", "path": "deploy/compose.frontend.yml", "source": "git_blob"},
                    ],
                }
            ),
            stderr="",
        )
    return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def test_backend_certification_is_partial_when_only_container_gate_is_blocked():
    checker = load_checker()

    checks = checker.collect_certification(
        runner=fake_runner,
        frontend_root=Path("C:/tmp/Moneybee-frontend-"),
        include_containers=False,
    )

    statuses = {item.name: item.status for item in checks}
    assert statuses["backend.release_configuration_checksum.git_blob"] == "PASS"
    assert statuses["backend.production_launch_gate.fail_closed"] == "PASS"
    assert statuses["backend.container_validation"] == "BLOCKED"
    assert checker.final_status(checks) == "PARTIAL"


def test_backend_certification_fails_if_launch_gate_allows_deployment():
    checker = load_checker()

    def ready_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "production_launch_check.py" in " ".join(command):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "final_status": "READY",
                        "totals": {"PASS": 64, "BLOCKED": 0, "FAIL": 0, "SKIP": 0},
                    }
                ),
                stderr="",
            )
        return fake_runner(command, cwd)

    check = checker.launch_gate_check(ready_runner, Path("C:/tmp/Moneybee-frontend-"))

    assert check.status == "FAIL"


def test_backend_certification_evidence_never_permits_deployment(tmp_path):
    checker = load_checker()
    checks = checker.collect_certification(
        runner=fake_runner,
        frontend_root=Path("C:/tmp/Moneybee-frontend-"),
        include_containers=False,
    )
    output = tmp_path / "backend-certification.json"

    checker.write_evidence(output, checks)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"] == "BACKEND_CERTIFICATION"
    assert payload["status"] == "PARTIAL"
    assert payload["metadata"]["deployment_permitted"] is False
    assert payload["metadata"]["checks"][-1]["status"] == "BLOCKED"
