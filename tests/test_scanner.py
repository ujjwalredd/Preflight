from __future__ import annotations

import json
from pathlib import Path

from preflight.scanner import scan


def test_scan_package_json_scripts(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "a",
                "scripts": {"test": "jest", "lint": "eslint ."},
                "dependencies": {"react": "^18.0.0"},
            }
        ),
        encoding="utf-8",
    )
    result = scan(tmp_path, use_cache=False)
    package = result.files["package.json"]
    assert package["scripts"]["test"] == "jest"
    assert "react" in package["dependencies"]


def test_scan_lockfiles(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("lockfile: true\n", encoding="utf-8")
    result = scan(tmp_path, use_cache=False)
    assert result.files["lockfiles"]["pnpm-lock.yaml"] == "pnpm"


def test_scan_cursor_rules(tmp_path: Path) -> None:
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "python.mdc").write_text("---\nrule body\n", encoding="utf-8")
    result = scan(tmp_path, use_cache=False)
    assert ".cursor/rules/python.mdc" in result.agent_rules
    assert result.rules[0]["excerpt"] == "---\nrule body"


def test_scan_pyproject_uses_real_toml_parser(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                'dependencies = ["fastapi>=0.1", "uvicorn>=0.1"]',
                "",
                "[project.optional-dependencies]",
                'dev = ["pytest>=8.0.0", "ruff>=0.6.0"]',
                "",
                "[build-system]",
                'build-backend = "hatchling.build"',
            ]
        ),
        encoding="utf-8",
    )
    result = scan(tmp_path, use_cache=False)
    pyproject = result.files["pyproject.toml"]
    assert pyproject["name"] == "demo"
    assert "fastapi" in pyproject["dependencies"]
    assert pyproject["optional_dependencies"]["dev"] == ["pytest>=8.0.0", "ruff>=0.6.0"]


def test_scan_discovers_nested_projects_and_graph(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "root",
                "workspaces": ["packages/*"],
                "dependencies": {"api": "workspace:*"},
            }
        ),
        encoding="utf-8",
    )
    nested = tmp_path / "packages" / "api"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text(
        json.dumps({"name": "api", "scripts": {"start": "node server.js"}}),
        encoding="utf-8",
    )
    result = scan(tmp_path, use_cache=False)
    paths = [project["path"] for project in result.projects]
    assert "." in paths
    assert "packages/api" in paths
    assert any(edge["to"] == "packages/api" for edge in result.project_graph["edges"])


def test_scan_parses_workflow_compose_and_frameworks(tmp_path: Path) -> None:
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
                "      - uses: actions/checkout@v4",
                "      - run: pytest -q",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "compose.yml").write_text(
        "\n".join(
            [
                "services:",
                "  web:",
                "    image: nginx:latest",
                '    ports: ["8080:80"]',
                "  api:",
                "    build:",
                "      context: .",
                '    command: ["python", "app.py"]',
                "    depends_on:",
                "      - web",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "svc"',
                'dependencies = ["fastapi>=0.1"]',
            ]
        ),
        encoding="utf-8",
    )
    app_dir = tmp_path / "service"
    app_dir.mkdir()
    (app_dir / "api.py").write_text(
        "\n".join(
            [
                "from fastapi import FastAPI",
                "app = FastAPI()",
                '@app.get("/items")',
                "def items():",
                "    return []",
            ]
        ),
        encoding="utf-8",
    )

    result = scan(tmp_path, use_cache=False)

    assert result.files["github_actions"][0]["trigger_hints"] == ["push"]
    assert result.files["compose.yml"]["services"][0]["name"] == "api"
    root_project = next(project for project in result.projects if project["path"] == ".")
    assert root_project["analysis"]["fastapi_routes"][0]["path"] == "/items"


def test_scan_cache_hits_on_second_run(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    first = scan(tmp_path)
    second = scan(tmp_path)
    assert first.cache["status"] == "miss"
    assert second.cache["status"] == "hit"
    assert Path(second.cache["path"]).is_file()


def test_scan_cache_invalidates_when_fastapi_source_changes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\ndependencies = ['fastapi>=0.1']\n",
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    route_file = app_dir / "routes.py"
    route_file.write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "router = APIRouter()",
                '@router.get("/a")',
                "def a():",
                "    return 1",
            ]
        ),
        encoding="utf-8",
    )
    first = scan(tmp_path)
    route_file.write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "router = APIRouter()",
                '@router.get("/b")',
                "def b():",
                "    return 1",
            ]
        ),
        encoding="utf-8",
    )
    second = scan(tmp_path)
    assert first.projects[0]["analysis"]["fastapi_routes"][0]["path"] == "/a"
    assert second.projects[0]["analysis"]["fastapi_routes"][0]["path"] == "/b"
    assert second.cache["status"] == "miss"


def test_scan_cache_invalidates_when_next_source_changes(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "demo", "dependencies": {"next": "14.0.0"}}),
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    page = app_dir / "page.tsx"
    page.write_text("export default function Page() { return null }\n", encoding="utf-8")
    first = scan(tmp_path)
    page.unlink()
    about_dir = app_dir / "about"
    about_dir.mkdir()
    (about_dir / "page.tsx").write_text(
        "export default function About() { return null }\n",
        encoding="utf-8",
    )
    second = scan(tmp_path)
    assert first.projects[0]["analysis"]["next_routes"][0]["route"] == "/"
    assert second.projects[0]["analysis"]["next_routes"][0]["route"] == "/about"
    assert second.cache["status"] == "miss"
