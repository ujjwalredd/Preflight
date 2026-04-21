from __future__ import annotations

import json
from pathlib import Path

from preflight.manifest import build_manifest


def test_release_install_is_downranked_for_local_canonical(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'dependencies = ["pytest>=8.0.0"]',
            ]
        ),
        encoding="utf-8",
    )
    nested = tmp_path / "libs" / "helper"
    nested.mkdir(parents=True)
    (nested / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "helper"',
                'version = "0.1.0"',
            ]
        ),
        encoding="utf-8",
    )
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "release.yml").write_text(
        "\n".join(
            [
                "name: Release",
                "on:",
                "  push:",
                "jobs:",
                "  publish:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                '      - run: pip install dist/demo-0.1.0.tar.gz --force-reinstall',
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, use_cache=False)

    assert manifest["commands"]["install"]["command"] == "pip install -e ."
    assert any(
        warning["id"] == "install_release_variants_excluded"
        for warning in manifest["warning_objects"]
    )


def test_ci_install_command_is_not_misclassified_as_test(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'dependencies = ["pytest>=8.0.0"]',
            ]
        ),
        encoding="utf-8",
    )
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "checks.yml").write_text(
        "\n".join(
            [
                "name: Checks",
                "on:",
                "  push:",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                '      - run: pip install pytest pytest-asyncio pytest-cov',
                '      - run: python -m pytest -q',
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, use_cache=False)

    assert manifest["commands"]["test"]["command"] != "pip install pytest pytest-asyncio pytest-cov"


def test_nextjs_like_monorepo_emits_specific_warning_objects(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "repo",
                "packageManager": "pnpm@9.0.0",
                "workspaces": ["packages/*"],
                "scripts": {"test": "pnpm test-root", "build": "pnpm build"},
                "dependencies": {"next": "14.0.0", "react": "18.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text(
        "\n".join(
            [
                "[package]",
                'name = "repo-rust"',
                'version = "0.1.0"',
                'edition = "2021"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("Use npm install locally.\n", encoding="utf-8")
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "name: CI",
                "on:",
                "  push:",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                '      - run: pnpm install --frozen-lockfile',
                '      - run: pnpm test --filter web',
            ]
        ),
        encoding="utf-8",
    )

    packages = tmp_path / "packages"
    packages.mkdir()
    for index in range(55):
        package_dir = packages / f"pkg-{index}"
        package_dir.mkdir()
        payload = {
            "name": f"pkg-{index}",
            "scripts": {"test": "vitest"},
        }
        if index == 0:
            payload["dependencies"] = {"next": "14.0.0"}
        (package_dir / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    (packages / "pkg-0" / "AGENTS.md").write_text("Package specific guidance.\n", encoding="utf-8")

    manifest = build_manifest(tmp_path, use_cache=False)
    warning_ids = {warning["id"] for warning in manifest["warning_objects"]}

    assert "large_monorepo" in warning_ids
    assert "workspace_overflow" in warning_ids
    assert "nested_rules_present" in warning_ids
    assert "mixed_toolchains" in warning_ids
    assert "root_commands_may_be_misleading" in warning_ids


def test_fastapi_like_repo_stays_low_noise(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'dependencies = ["fastapi>=0.1", "pytest>=8.0.0", "ruff>=0.6.0"]',
            ]
        ),
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "\n".join(
            [
                "from fastapi import FastAPI",
                "app = FastAPI()",
                '@app.get("/health")',
                "def health():",
                "    return {'ok': True}",
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, use_cache=False)

    assert manifest["warning_objects"] == []


def test_rule_and_docs_package_manager_warning(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "demo", "packageManager": "pnpm@9.0.0"}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Run yarn install before contributing.\n", encoding="utf-8")
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "name: CI",
                "on:",
                "  push:",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                '      - run: pnpm install --frozen-lockfile',
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, use_cache=False)
    warning_ids = {warning["id"] for warning in manifest["warning_objects"]}

    assert "readme_package_manager_mismatch" in warning_ids
