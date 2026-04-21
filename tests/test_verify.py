from __future__ import annotations

import json
import os
from pathlib import Path

from preflight.cli import main
from preflight.verify import _build_execution_env, verify_manifest


def test_verify_returns_dry_run_plan(tmp_path: Path, capsys) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "demo", "scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )

    exit_code = main(["verify", str(tmp_path), "--no-cache"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["success"] is True
    assert payload["policy"]["allow_risky"] is False
    assert payload["steps"][0]["status"] == "planned"
    assert any(step["name"] == "test" and step["risk"] == "low" for step in payload["steps"])


def test_verify_blocks_risky_install_without_flag(tmp_path: Path, capsys) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "demo", "scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )

    exit_code = main(["verify", str(tmp_path), "--run", "--command", "install", "--no-cache"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["steps"][0]["status"] == "blocked"
    assert "allow-risky" in payload["steps"][0]["blocked_reason"]


def test_verify_injects_src_pythonpath_for_python_projects(tmp_path: Path) -> None:
    package_dir = tmp_path / "src" / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    manifest = {
        "root": str(tmp_path),
        "projects": [{"types": ["python"]}],
        "commands": {
            "test": {
                "command": "python -c \"import demo\"",
                "confidence": "high",
                "source": "manual",
                "risk": "low",
                "evidence": [],
            }
        },
    }

    result = verify_manifest(manifest, selected_commands=["test"], run=True)

    assert result["success"] is True
    assert result["steps"][0]["status"] == "passed"


def test_verify_runs_pytest_with_current_interpreter(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_yaml_import.py").write_text(
        "\n".join(
            [
                "import yaml",
                "",
                "def test_yaml_import() -> None:",
                "    assert yaml is not None",
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "root": str(tmp_path),
        "projects": [{"types": ["python"]}],
        "commands": {
            "test": {
                "command": "pytest -q",
                "confidence": "high",
                "source": "manual",
                "risk": "low",
                "evidence": [],
            }
        },
    }

    result = verify_manifest(manifest, selected_commands=["test"], run=True)

    assert result["success"] is True
    assert result["steps"][0]["status"] == "passed"


def test_verify_rewrites_python_module_commands_to_current_interpreter(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_yaml_import.py").write_text(
        "\n".join(
            [
                "import yaml",
                "",
                "def test_yaml_import() -> None:",
                "    assert yaml is not None",
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "root": str(tmp_path),
        "projects": [{"types": ["python"]}],
        "commands": {
            "test": {
                "command": "python -m pytest -q",
                "confidence": "high",
                "source": "manual",
                "risk": "low",
                "evidence": [],
            }
        },
    }

    result = verify_manifest(manifest, selected_commands=["test"], run=True)

    assert result["success"] is True
    assert result["steps"][0]["status"] == "passed"


def test_verify_adds_windows_scripts_directory_to_path(tmp_path: Path) -> None:
    scripts_dir = tmp_path / ".venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    manifest = {
        "root": str(tmp_path),
        "projects": [{"types": ["python"]}],
    }

    env = _build_execution_env(tmp_path, manifest, {})

    assert env["PATH"].split(os.pathsep)[0] == str(scripts_dir)
