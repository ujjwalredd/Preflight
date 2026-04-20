from __future__ import annotations

import json
from pathlib import Path

from preflight.manifest import build_manifest, manifest_to_bootstrap, manifest_to_json


def test_build_manifest_minimal(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    manifest = build_manifest(tmp_path, use_cache=False)
    assert manifest["root"] == str(tmp_path.resolve())
    assert manifest["preflight_version"] == 3
    assert manifest["schema_ref"] == "manifest.schema.json"
    assert manifest["cache"]["status"] == "disabled"
    raw = json.loads(manifest_to_json(manifest))
    assert raw["root"] == manifest["root"]


def test_lockfile_conflict_warning(tmp_path: Path) -> None:
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    manifest = build_manifest(tmp_path, use_cache=False)
    assert any(
        "yarn.lock" in warning and "package-lock.json" in warning
        for warning in manifest["warnings"]
    )


def test_preflight_json_overrides(tmp_path: Path) -> None:
    (tmp_path / ".preflight.json").write_text(
        json.dumps(
            {
                "display_name": "X",
                "canonical": {"test": "pytest -q"},
                "notes": ["touch nothing"],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(tmp_path, use_cache=False)
    assert manifest["display_name"] == "X"
    assert manifest["commands"]["test"]["command"] == "pytest -q"
    assert manifest["commands"]["test"]["confidence"] == "override"
    assert manifest["human_notes"] == ["touch nothing"]


def test_invalid_preflight_json_becomes_warning(tmp_path: Path) -> None:
    (tmp_path / ".preflight.json").write_text("{bad", encoding="utf-8")
    manifest = build_manifest(tmp_path, use_cache=False)
    assert any(".preflight.json is invalid JSON" in warning for warning in manifest["warnings"])


def test_manifest_contains_graph_bootstrap_and_analysis(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'dependencies = ["fastapi>=0.1", "pytest>=8.0.0"]',
                "",
                "[project.scripts]",
                'demo = "demo.cli:main"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("Follow tests first.\n", encoding="utf-8")
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "routes.py").write_text(
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
    package_dir = tmp_path / "src" / "demo"
    package_dir.mkdir(parents=True)
    (package_dir / "__main__.py").write_text("print('hi')\n", encoding="utf-8")
    nested = tmp_path / "packages" / "web"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "dependencies": {"demo": "workspace:*", "next": "^14.0.0"},
                "scripts": {"dev": "next dev", "build": "next build"},
            }
        ),
        encoding="utf-8",
    )
    pages_dir = nested / "pages"
    pages_dir.mkdir()
    (pages_dir / "index.tsx").write_text(
        "export default function Page() { return null }\n",
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, use_cache=False)

    assert any(project["path"] == "." for project in manifest["projects"])
    assert any(project["path"] == "packages/web" for project in manifest["projects"])
    assert any(rule["path"] == "AGENTS.md" for rule in manifest["rules"])
    assert any(entry.get("target") == "demo.cli:main" for entry in manifest["entrypoints"])
    assert manifest["commands"]["test"]["command"] == "pytest"
    assert manifest["project_graph"]["edges"]
    bootstrap = manifest_to_bootstrap(manifest, plain=True)
    assert "FastAPI routes" in bootstrap
    assert "packages/web" in bootstrap
