import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "compute-configuration-checksum.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("configuration_checksum", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_configuration_checksum_is_deterministic():
    tool = load_tool()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"

    entries = tool.configuration_manifest(frontend_root)
    checksum = tool.configuration_checksum(entries)

    assert len(checksum) == 64
    assert {entry["scope"] for entry in entries} == {"backend", "frontend"}
    assert {entry["source"] for entry in entries} == {"git_blob"}
    assert [entry["path"] for entry in entries] == [
        "deploy/Caddyfile.staging",
        "deploy/compose.backend.yml",
        "deploy/compose.data.yml",
        "deploy/compose.edge.yml",
        "deploy/compose.frontend.yml",
    ]
    assert checksum == tool.configuration_checksum(entries)
    assert tool.canonical_lines(entries).startswith(
        "backend/deploy/Caddyfile.staging  "
    )


def test_configuration_checksum_json_includes_source_provenance(capsys):
    tool = load_tool()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"

    result = tool.main(["--frontend-root", str(frontend_root), "--json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["configuration_checksum"]) == 64
    assert "backend/deploy/Caddyfile.staging" in payload["canonical"]
    assert len(payload["backend_sha"]) == 40
    assert len(payload["frontend_sha"]) == 40
    assert isinstance(payload["backend_dirty"], bool)
    assert payload["frontend_dirty"] is False


def test_configuration_checksum_uses_git_blobs_not_worktree_crlf(tmp_path):
    tool = load_tool()
    backend_root = tmp_path / "backend"
    frontend_root = tmp_path / "frontend"
    backend_files = [
        "deploy/Caddyfile.staging",
        "deploy/compose.backend.yml",
        "deploy/compose.data.yml",
        "deploy/compose.edge.yml",
    ]
    frontend_files = ["deploy/compose.frontend.yml"]

    for root, files in ((backend_root, backend_files), (frontend_root, frontend_files)):
        (root / "deploy").mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
        for relative in files:
            (root / relative).write_text("line-one\nline-two\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "fixtures"], cwd=root, check=True, capture_output=True)

    original_backend_root = tool.BACKEND_ROOT
    try:
        tool.BACKEND_ROOT = backend_root
        before = tool.configuration_checksum(tool.configuration_manifest(frontend_root))
        (backend_root / "deploy" / "compose.backend.yml").write_text(
            "line-one\r\nline-two\r\n",
            encoding="utf-8",
        )
        after = tool.configuration_checksum(tool.configuration_manifest(frontend_root))
    finally:
        tool.BACKEND_ROOT = original_backend_root

    assert before == after
    assert tool.git_dirty(backend_root) is True


def test_configuration_checksum_expectation_mismatch_exits_nonzero(capsys):
    tool = load_tool()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"

    result = tool.main(["--frontend-root", str(frontend_root), "--expect", "0" * 64])

    assert result == 1
    assert "configuration checksum mismatch" in capsys.readouterr().err
