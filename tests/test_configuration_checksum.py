import importlib.util
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
    assert [entry["path"] for entry in entries] == [
        "deploy/Caddyfile.staging",
        "deploy/compose.backend.yml",
        "deploy/compose.data.yml",
        "deploy/compose.edge.yml",
        "deploy/compose.frontend.yml",
    ]
    assert checksum == tool.configuration_checksum(entries)


def test_configuration_checksum_expectation_mismatch_exits_nonzero(capsys):
    tool = load_tool()
    frontend_root = Path(__file__).resolve().parents[2] / "Moneybee-frontend-"

    result = tool.main(["--frontend-root", str(frontend_root), "--expect", "0" * 64])

    assert result == 1
    assert "configuration checksum mismatch" in capsys.readouterr().err
