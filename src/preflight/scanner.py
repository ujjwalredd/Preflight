from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".next",
    ".nox",
    ".preflight",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".terraform",
    ".tox",
    ".turbo",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "site-packages",
    "target",
    "venv",
}
INSTRUCTION_FILE_KINDS = {
    "AGENTS.md": "agents",
    "agents.md": "agents",
    "CLAUDE.md": "claude",
    "GEMINI.md": "gemini",
    "COPILOT_INSTRUCTIONS.md": "copilot",
    "CONTRIBUTING.md": "contributing",
}
LOCKFILES = {
    "Cargo.lock": "cargo",
    "Pipfile.lock": "pipenv",
    "bun.lock": "bun",
    "bun.lockb": "bun",
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "poetry.lock": "poetry",
    "uv.lock": "uv",
    "yarn.lock": "yarn",
}
FRAMEWORK_HINTS = {
    "actix-web": "actix-web",
    "astro": "astro",
    "axum": "axum",
    "click": "click",
    "django": "django",
    "express": "express",
    "fastapi": "fastapi",
    "fastify": "fastify",
    "flask": "flask",
    "hono": "hono",
    "jest": "jest",
    "nestjs": "nestjs",
    "next": "next.js",
    "pytest": "pytest",
    "react": "react",
    "rocket": "rocket",
    "ruff": "ruff",
    "svelte": "svelte",
    "tokio": "tokio",
    "typer": "typer",
    "typescript": "typescript",
    "vite": "vite",
    "vue": "vue",
}
PROJECT_MARKERS = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}
RULE_EXCERPT_CHARS = 4000
RULE_EXCERPT_LINES = 120
README_NAMES = {"README.md", "Readme.md", "readme.md"}
MAKEFILE_NAMES = {"Makefile", "makefile"}
COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
ENV_EXAMPLE_NAMES = (".env.example", ".env.sample", "env.example")
COMMON_PYTHON_ENTRYPOINTS = {"main.py", "app.py", "manage.py", "server.py"}
CACHE_VERSION = 2


class _PreflightYamlLoader(yaml.SafeLoader):
    pass


for first_char, resolvers in list(_PreflightYamlLoader.yaml_implicit_resolvers.items()):
    _PreflightYamlLoader.yaml_implicit_resolvers[first_char] = [
        (tag, regex)
        for tag, regex in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]


@dataclass
class ScanResult:
    root: Path
    files: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    project_graph: dict[str, Any] = field(default_factory=dict)
    entrypoints: list[dict[str, Any]] = field(default_factory=list)
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_rules(self) -> list[str]:
        return [str(rule["path"]) for rule in self.rules]


def scan(root: Path, use_cache: bool = True) -> ScanResult:
    root = root.resolve()
    if not root.is_dir():
        return ScanResult(root=root, warnings=["root is not a directory"])

    signature = _build_scan_signature(root)
    cache_path = _cache_file_path(root)
    if use_cache:
        cached = _load_cached_scan(root, cache_path, signature)
        if cached is not None:
            return cached

    out = ScanResult(root=root)
    _scan_package_json(root, out)
    _scan_pyproject(root, out)
    _scan_cargo(root, out)
    _scan_go_mod(root, out)
    _scan_makefile(root, out)
    _scan_docker(root, out)
    _scan_env_example(root, out)
    _scan_readme(root, out)
    _scan_github_actions(root, out)
    _scan_lockfiles(root, out)
    _scan_instruction_files(root, out)
    _scan_terraform(root, out)
    out.projects = _discover_projects(root, out)
    out.project_graph = _build_project_graph(out.projects)
    out.entrypoints = _collect_entrypoints(root, out)
    out.cache = _cache_metadata("miss", cache_path, signature)

    if use_cache:
        _store_cached_scan(cache_path, signature, out)
    else:
        out.cache = _cache_metadata("disabled", cache_path, signature)

    return out


def _cache_file_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "preflight-cache" / digest / (
        f"scan-cache-v{CACHE_VERSION}.json"
    )


def _cache_metadata(status: str, path: Path, signature: str) -> dict[str, Any]:
    return {
        "status": status,
        "path": str(path),
        "signature": signature[:16],
        "version": CACHE_VERSION,
    }


def _serialize_scan_result(scan_result: ScanResult) -> dict[str, Any]:
    return {
        "files": scan_result.files,
        "rules": scan_result.rules,
        "warnings": scan_result.warnings,
        "projects": scan_result.projects,
        "project_graph": scan_result.project_graph,
        "entrypoints": scan_result.entrypoints,
    }


def _scan_result_from_payload(
    root: Path,
    payload: dict[str, Any],
    cache_path: Path,
    signature: str,
    status: str,
) -> ScanResult:
    return ScanResult(
        root=root,
        files=payload.get("files") or {},
        rules=payload.get("rules") or [],
        warnings=payload.get("warnings") or [],
        projects=payload.get("projects") or [],
        project_graph=payload.get("project_graph") or {},
        entrypoints=payload.get("entrypoints") or [],
        cache=_cache_metadata(status, cache_path, signature),
    )


def _load_cached_scan(root: Path, cache_path: Path, signature: str) -> ScanResult | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("signature") != signature:
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    return _scan_result_from_payload(root, result, cache_path, signature, "hit")


def _store_cached_scan(cache_path: Path, signature: str, scan_result: ScanResult) -> None:
    payload = {
        "signature": signature,
        "result": _serialize_scan_result(scan_result),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        return


def _build_scan_signature(root: Path) -> str:
    watched: list[list[Any]] = []
    for path in _walk_files(root):
        rel = path.relative_to(root)
        if not _should_watch_path(rel):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        watched.append([rel.as_posix(), stat.st_mtime_ns, stat.st_size])
    raw = json.dumps({"version": CACHE_VERSION, "files": watched}, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _should_watch_path(rel: Path) -> bool:
    name = rel.name
    if (
        name in PROJECT_MARKERS
        or name in LOCKFILES
        or name in README_NAMES
        or name in MAKEFILE_NAMES
    ):
        return True
    if name == ".preflight.json" or name == "Dockerfile" or name in COMPOSE_NAMES:
        return True
    if name in ENV_EXAMPLE_NAMES:
        return True
    if rel.suffix == ".tf":
        return True
    if _instruction_kind(rel) is not None:
        return True
    if _is_workflow_path(rel):
        return True
    if _is_common_entrypoint_path(rel):
        return True
    return False


def _is_workflow_path(rel: Path) -> bool:
    return len(rel.parts) >= 3 and rel.parts[0] == ".github" and rel.parts[1] == "workflows"


def _is_common_entrypoint_path(rel: Path) -> bool:
    if rel.name in COMMON_PYTHON_ENTRYPOINTS:
        return True
    if rel.as_posix().endswith("/main.go") or rel.as_posix().endswith("/main.rs"):
        return True
    parts = rel.parts
    return len(parts) >= 3 and parts[0] == "src" and parts[-1] == "__main__.py"


def _read_json(path: Path, out: ScanResult | None = None) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} could not be read: {exc}")
    except json.JSONDecodeError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} is invalid JSON: {exc.msg}")
    return None


def _read_toml(path: Path, out: ScanResult | None = None) -> dict[str, Any] | None:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} could not be read: {exc}")
    except tomllib.TOMLDecodeError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} is invalid TOML: {exc}")
    return None


def _read_yaml(path: Path, out: ScanResult | None = None) -> Any | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} could not be read: {exc}")
        return None
    try:
        return yaml.load(text, Loader=_PreflightYamlLoader)
    except yaml.YAMLError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} is invalid YAML: {exc}")
        return None


def _safe_read_text(path: Path, out: ScanResult | None = None) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        if out is not None:
            out.warnings.append(f"{path.name} could not be read: {exc}")
    return None


def _scan_package_json(root: Path, out: ScanResult) -> None:
    path = root / "package.json"
    if not path.is_file():
        return
    data = _read_json(path, out)
    if not isinstance(data, dict):
        return
    deps = _normalize_dependency_keys(data.get("dependencies"))
    dev_deps = _normalize_dependency_keys(data.get("devDependencies"))
    out.files["package.json"] = {
        "name": _as_str(data.get("name")),
        "private": data.get("private"),
        "packageManager": _as_str(data.get("packageManager")),
        "scripts": _string_mapping(data.get("scripts")),
        "main": _as_str(data.get("main")),
        "bin": _normalize_bin_field(data.get("bin")),
        "workspaces": _normalize_workspaces(data.get("workspaces")),
        "dependencies": deps,
        "dev_dependencies": dev_deps,
    }


def _scan_pyproject(root: Path, out: ScanResult) -> None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return
    data = _read_toml(path, out)
    if not isinstance(data, dict):
        return
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    build_system = data.get("build-system") if isinstance(data.get("build-system"), dict) else {}
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
    scripts = _string_mapping(project.get("scripts"))
    if not scripts:
        scripts = _string_mapping(poetry.get("scripts"))
    out.files["pyproject.toml"] = {
        "name": _as_str(project.get("name")) or _as_str(poetry.get("name")),
        "scripts": scripts,
        "optional_dependencies": _normalize_optional_dependencies(
            project.get("optional-dependencies")
        ),
        "dependencies": _normalize_python_dependency_entries(project.get("dependencies"))
        or _normalize_dependency_keys(poetry.get("dependencies"), drop={"python"}),
        "build_backend": _as_str(build_system.get("build-backend")),
        "requires_python": _as_str(project.get("requires-python")),
        "tool_sections": sorted(str(key) for key in tool.keys()),
    }


def _scan_cargo(root: Path, out: ScanResult) -> None:
    path = root / "Cargo.toml"
    if not path.is_file():
        return
    data = _read_toml(path, out)
    if not isinstance(data, dict):
        return
    package = data.get("package") if isinstance(data.get("package"), dict) else {}
    bins = data.get("bin") if isinstance(data.get("bin"), list) else []
    out.files["Cargo.toml"] = {
        "name": _as_str(package.get("name")),
        "edition": _as_str(package.get("edition")),
        "dependencies": _normalize_dependency_keys(data.get("dependencies")),
        "bins": [bin_item for bin_item in (_normalize_cargo_bin(x) for x in bins) if bin_item],
    }


def _scan_go_mod(root: Path, out: ScanResult) -> None:
    path = root / "go.mod"
    if not path.is_file():
        return
    text = _safe_read_text(path, out)
    if text is None:
        return
    module = None
    go_version = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            module = stripped.removeprefix("module ").strip()
        if stripped.startswith("go "):
            go_version = stripped.removeprefix("go ").strip()
    out.files["go.mod"] = {"module": module, "go_version": go_version}


def _scan_makefile(root: Path, out: ScanResult) -> None:
    for name in MAKEFILE_NAMES:
        path = root / name
        if not path.is_file():
            continue
        text = _safe_read_text(path, out)
        if text is None:
            return
        targets = re.findall(r"^([A-Za-z0-9_.-]+)\s*:", text, flags=re.MULTILINE)
        filtered = [target for target in targets if not target.startswith(".")]
        out.files["Makefile"] = {"targets": sorted(set(filtered))[:80]}
        return


def _scan_docker(root: Path, out: ScanResult) -> None:
    for compose_name in COMPOSE_NAMES:
        compose_path = root / compose_name
        if not compose_path.is_file():
            continue
        record: dict[str, Any] = {"path": str(compose_path.relative_to(root))}
        data = _read_yaml(compose_path, out)
        if isinstance(data, dict):
            services = data.get("services")
            if isinstance(services, dict):
                record["services"] = [
                    _normalize_compose_service(name, value)
                    for name, value in sorted(services.items())
                    if isinstance(value, dict)
                ]
            version = data.get("version")
            if isinstance(version, str):
                record["version"] = version
        out.files[compose_name] = record

    dockerfile = root / "Dockerfile"
    if not dockerfile.is_file():
        return
    text = _safe_read_text(dockerfile, out)
    if text is None:
        return
    cmds = re.findall(r"^\s*CMD\s+(.*)$", text, flags=re.MULTILINE | re.IGNORECASE)
    entrypoints = re.findall(
        r"^\s*ENTRYPOINT\s+(.*)$", text, flags=re.MULTILINE | re.IGNORECASE
    )
    out.files["Dockerfile"] = {
        "cmd": cmds[-1] if cmds else None,
        "entrypoint": entrypoints[-1] if entrypoints else None,
    }


def _normalize_compose_service(name: str, value: dict[str, Any]) -> dict[str, Any]:
    build = value.get("build")
    if isinstance(build, dict):
        build_value: str | None = _as_str(build.get("context"))
    else:
        build_value = _as_str(build)
    ports = value.get("ports")
    depends_on = value.get("depends_on")
    if isinstance(depends_on, dict):
        depends_list = sorted(str(key) for key in depends_on.keys())
    elif isinstance(depends_on, list):
        depends_list = [str(item) for item in depends_on]
    else:
        depends_list = []
    return {
        "name": name,
        "image": _as_str(value.get("image")),
        "build": build_value,
        "command": _stringify_command_field(value.get("command")),
        "entrypoint": _stringify_command_field(value.get("entrypoint")),
        "ports": [str(item) for item in ports] if isinstance(ports, list) else [],
        "depends_on": depends_list,
    }


def _stringify_command_field(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return None


def _scan_env_example(root: Path, out: ScanResult) -> None:
    for name in ENV_EXAMPLE_NAMES:
        path = root / name
        if not path.is_file():
            continue
        text = _safe_read_text(path, out)
        if text is None:
            return
        keys: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                keys.append(stripped.split("=", 1)[0].strip())
        out.files[name] = {"var_names": keys[:200]}
        return


def _scan_readme(root: Path, out: ScanResult) -> None:
    for name in README_NAMES:
        path = root / name
        if not path.is_file():
            continue
        text = _safe_read_text(path, out)
        if text is None:
            return
        out.files["README.md"] = {"preview_lines": text.splitlines()[:40], "source": name}
        return


def _scan_github_actions(root: Path, out: ScanResult) -> None:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return
    workflows: list[dict[str, Any]] = []
    for path in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        data = _read_yaml(path, out)
        if not isinstance(data, dict):
            continue
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        triggers = data.get("on")
        if triggers is None and "on" not in data and True in data:
            triggers = data.get(True)
        run_commands: list[str] = []
        uses_actions: set[str] = set()
        reusable: set[str] = set()
        services: set[str] = set()
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            if isinstance(job.get("uses"), str):
                reusable.add(job["uses"])
            job_services = job.get("services")
            if isinstance(job_services, dict):
                services.update(str(key) for key in job_services.keys())
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                run = step.get("run")
                if isinstance(run, str):
                    run_commands.extend(_split_multiline_run(run))
                uses = step.get("uses")
                if isinstance(uses, str):
                    uses_actions.add(uses)
        workflows.append(
            {
                "file": str(path.relative_to(root)),
                "name": _as_str(data.get("name")),
                "trigger_hints": _normalize_trigger_hints(triggers),
                "job_hints": sorted(str(key) for key in jobs.keys())[:30],
                "run_commands": run_commands[:30],
                "uses_actions": sorted(uses_actions)[:30],
                "reusable_workflows": sorted(reusable)[:10],
                "service_hints": sorted(services)[:20],
            }
        )
    if workflows:
        out.files["github_actions"] = workflows


def _split_multiline_run(command: str) -> list[str]:
    return [line.strip() for line in command.splitlines() if line.strip()]


def _normalize_trigger_hints(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return sorted(str(key) for key in value.keys())
    return []


def _scan_lockfiles(root: Path, out: ScanResult) -> None:
    found: dict[str, str] = {}
    for filename, ecosystem in LOCKFILES.items():
        if (root / filename).is_file():
            found[filename] = ecosystem
    if found:
        out.files["lockfiles"] = found


def _scan_instruction_files(root: Path, out: ScanResult) -> None:
    rules: list[dict[str, Any]] = []
    for path in _walk_files(root):
        rel = path.relative_to(root)
        kind = _instruction_kind(rel)
        if kind is None:
            continue
        text = _safe_read_text(path, out)
        if text is None:
            continue
        excerpt, truncated = _excerpt_text(text)
        rules.append(
            {
                "path": rel.as_posix(),
                "kind": kind,
                "line_count": len(text.splitlines()),
                "char_count": len(text),
                "excerpt": excerpt,
                "truncated": truncated,
            }
        )
    out.rules = sorted(rules, key=lambda rule: rule["path"])


def _scan_terraform(root: Path, out: ScanResult) -> None:
    providers: set[str] = set()
    modules: list[dict[str, str]] = []
    files: list[str] = []
    for path in _walk_files(root):
        if path.suffix != ".tf":
            continue
        files.append(path.relative_to(root).as_posix())
        text = _safe_read_text(path, out)
        if text is None:
            continue
        providers.update(re.findall(r'provider\s+"([^"]+)"', text))
        for match in re.finditer(r'module\s+"([^"]+)"\s*\{(.*?)\}', text, flags=re.DOTALL):
            source_match = re.search(r'\bsource\s*=\s*"([^"]+)"', match.group(2))
            modules.append(
                {
                    "name": match.group(1),
                    "source": source_match.group(1) if source_match else "",
                }
            )
    if files:
        out.files["terraform"] = {
            "files": sorted(files),
            "providers": sorted(providers),
            "modules": sorted(modules, key=lambda item: item["name"]),
        }


def _discover_projects(root: Path, out: ScanResult) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        marker_names = sorted(PROJECT_MARKERS.intersection(filenames))
        if not marker_names:
            continue
        project_dir = Path(dirpath)
        project = _build_project(root, project_dir, marker_names)
        if project is not None:
            projects.append(project)
    return sorted(projects, key=lambda project: project["path"])


def _build_project(root: Path, project_dir: Path, markers: list[str]) -> dict[str, Any] | None:
    rel_path = "." if project_dir == root else project_dir.relative_to(root).as_posix()
    kinds: set[str] = set()
    frameworks: set[str] = set()
    entrypoints: list[dict[str, Any]] = []
    package_managers: set[str] = set()
    test_paths: set[str] = set()
    declared_dependencies: set[str] = set()
    workspace_patterns: list[str] = []
    name: str | None = None

    if "package.json" in markers:
        data = _read_json(project_dir / "package.json")
        if isinstance(data, dict):
            kinds.add("javascript")
            name = name or _as_str(data.get("name"))
            deps = _normalize_dependency_keys(data.get("dependencies"))
            dev_deps = _normalize_dependency_keys(data.get("devDependencies"))
            declared_dependencies.update(deps)
            declared_dependencies.update(dev_deps)
            frameworks.update(_infer_framework_hints(deps + dev_deps))
            package_manager = _pick_js_package_manager(project_dir, data)
            package_managers.add(package_manager)
            scripts = _string_mapping(data.get("scripts"))
            workspace_patterns = _normalize_workspaces(data.get("workspaces"))
            main = _as_str(data.get("main"))
            if main:
                entrypoints.append(
                    {
                        "path": _join_rel(rel_path, main),
                        "kind": "node_main",
                        "source": "package.json#main",
                    }
                )
            for bin_name, bin_path in _normalize_bin_field(data.get("bin")).items():
                entrypoints.append(
                    {
                        "path": _join_rel(rel_path, bin_path),
                        "kind": "node_bin",
                        "name": bin_name,
                        "source": "package.json#bin",
                    }
                )
            for script_name in ("start", "dev"):
                if script_name in scripts:
                    entrypoints.append(
                        {
                            "kind": "script",
                            "name": script_name,
                            "command": _js_script_command(
                                scripts[script_name],
                                script_name,
                                package_manager,
                            ),
                            "source": f"package.json#scripts.{script_name}",
                        }
                    )

    if "pyproject.toml" in markers:
        data = _read_toml(project_dir / "pyproject.toml")
        if isinstance(data, dict):
            kinds.add("python")
            project = data.get("project") if isinstance(data.get("project"), dict) else {}
            tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
            poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
            name = name or _as_str(project.get("name")) or _as_str(poetry.get("name"))
            deps = _normalize_python_dependency_entries(project.get("dependencies"))
            optional = _normalize_optional_dependencies(project.get("optional-dependencies"))
            if not deps:
                deps = _normalize_dependency_keys(poetry.get("dependencies"), drop={"python"})
            declared_dependencies.update(deps)
            declared_dependencies.update(_flatten_optional_deps(optional))
            frameworks.update(_infer_framework_hints(list(declared_dependencies)))
            package_managers.add("uv" if (project_dir / "uv.lock").is_file() else "pip")
            scripts = _string_mapping(project.get("scripts")) or _string_mapping(
                poetry.get("scripts")
            )
            for script_name, target in scripts.items():
                entrypoints.append(
                    {
                        "kind": "console_script",
                        "name": script_name,
                        "target": target,
                        "source": "pyproject.toml#scripts",
                    }
                )
            for main_path in sorted(project_dir.glob("src/*/__main__.py")):
                entrypoints.append(
                    {
                        "path": _join_rel(rel_path, main_path.relative_to(project_dir).as_posix()),
                        "kind": "python_module",
                        "source": "__main__.py",
                    }
                )
            for candidate in COMMON_PYTHON_ENTRYPOINTS:
                if (project_dir / candidate).is_file():
                    entrypoints.append(
                        {
                            "path": _join_rel(rel_path, candidate),
                            "kind": "python_file",
                            "source": "common_python_entrypoint",
                        }
                    )

    if "Cargo.toml" in markers:
        data = _read_toml(project_dir / "Cargo.toml")
        if isinstance(data, dict):
            kinds.add("rust")
            package = data.get("package") if isinstance(data.get("package"), dict) else {}
            name = name or _as_str(package.get("name"))
            deps = _normalize_dependency_keys(data.get("dependencies"))
            declared_dependencies.update(deps)
            frameworks.update(_infer_framework_hints(deps))
            package_managers.add("cargo")
            if (project_dir / "src" / "main.rs").is_file():
                entrypoints.append(
                    {
                        "path": _join_rel(rel_path, "src/main.rs"),
                        "kind": "rust_binary",
                        "source": "src/main.rs",
                    }
                )
            bins = data.get("bin") if isinstance(data.get("bin"), list) else []
            for raw_bin in bins:
                normalized = _normalize_cargo_bin(raw_bin)
                if normalized is None:
                    continue
                entrypoints.append({"kind": "rust_bin", **normalized, "source": "Cargo.toml#bin"})

    if "go.mod" in markers:
        kinds.add("go")
        text = _safe_read_text(project_dir / "go.mod")
        if text:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("module "):
                    name = name or stripped.removeprefix("module ").strip()
                    break
        package_managers.add("go")
        for main_path in sorted(project_dir.glob("cmd/*/main.go")):
            entrypoints.append(
                {
                    "path": _join_rel(rel_path, main_path.relative_to(project_dir).as_posix()),
                    "kind": "go_binary",
                    "source": "cmd/*/main.go",
                }
            )
        if (project_dir / "main.go").is_file():
            entrypoints.append(
                {
                    "path": _join_rel(rel_path, "main.go"),
                    "kind": "go_binary",
                    "source": "main.go",
                }
            )

    for test_dir_name in ("tests", "test", "__tests__", "spec"):
        if (project_dir / test_dir_name).exists():
            test_paths.add(_join_rel(rel_path, test_dir_name))

    if not kinds:
        return None

    analysis = _analyze_project(project_dir, frameworks)
    project: dict[str, Any] = {
        "path": rel_path,
        "name": name or project_dir.name,
        "types": sorted(kinds),
        "markers": markers,
        "manifest_files": [_join_rel(rel_path, marker) for marker in markers],
        "package_managers": sorted(package_managers),
        "framework_hints": sorted(frameworks),
        "entrypoints": _dedupe_objects(entrypoints),
        "test_paths": sorted(test_paths),
        "declared_dependencies": sorted(declared_dependencies),
        "workspace_patterns": workspace_patterns,
        "internal_dependencies": [],
        "workspace_children": [],
    }
    if analysis:
        project["analysis"] = analysis
    return project


def _analyze_project(project_dir: Path, frameworks: set[str]) -> dict[str, Any]:
    analysis: dict[str, Any] = {}
    if "fastapi" in frameworks:
        routes = _analyze_fastapi_routes(project_dir)
        if routes:
            analysis["fastapi_routes"] = routes
    if "django" in frameworks or (project_dir / "manage.py").is_file():
        django = _analyze_django_project(project_dir)
        if django:
            analysis["django"] = django
    if "next.js" in frameworks:
        routes = _analyze_next_routes(project_dir)
        if routes:
            analysis["next_routes"] = routes
    return analysis


def _analyze_fastapi_routes(project_dir: Path) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    pattern = re.compile(
        r"@(?:\w+)\.(get|post|put|delete|patch|options|head|api_route)\(\s*([\"'])(.+?)\2"
    )
    for path in _walk_project_files(project_dir, suffixes={".py"}):
        text = _safe_read_text(path)
        if text is None or "FastAPI" not in text and "@app." not in text and "@router." not in text:
            continue
        for match in pattern.finditer(text):
            method = match.group(1).upper()
            routes.append(
                {
                    "path": match.group(3),
                    "method": method if method != "API_ROUTE" else "API_ROUTE",
                    "file": path.relative_to(project_dir).as_posix(),
                }
            )
    return _dedupe_objects(routes)[:100]


def _analyze_django_project(project_dir: Path) -> dict[str, Any]:
    settings_files = []
    app_modules = []
    for path in _walk_project_files(project_dir, suffixes={".py"}):
        rel = path.relative_to(project_dir).as_posix()
        if path.name == "settings.py":
            settings_files.append(rel)
        if path.name == "apps.py" and path.parent != project_dir:
            app_modules.append(path.parent.relative_to(project_dir).as_posix())
    result: dict[str, Any] = {}
    if settings_files:
        result["settings_files"] = settings_files[:20]
    if app_modules:
        result["app_modules"] = sorted(set(app_modules))[:50]
    if (project_dir / "manage.py").is_file():
        result["manage_py"] = "manage.py"
    return result


def _analyze_next_routes(project_dir: Path) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    app_dir = project_dir / "app"
    if app_dir.is_dir():
        for path in sorted(app_dir.rglob("*")):
            if not path.is_file():
                continue
            if not (path.name.startswith("page.") or path.name.startswith("route.")):
                continue
            rel_parent = path.parent.relative_to(app_dir)
            segments = [
                segment
                for segment in rel_parent.parts
                if not segment.startswith("(") and not segment.startswith("@")
            ]
            route = "/" + "/".join(segments)
            route = route.rstrip("/") or "/"
            kind = "route_handler" if path.name.startswith("route.") else "page"
            routes.append(
                {
                    "route": route,
                    "kind": kind,
                    "file": path.relative_to(project_dir).as_posix(),
                }
            )

    pages_dir = project_dir / "pages"
    if pages_dir.is_dir():
        for path in sorted(pages_dir.rglob("*")):
            if not path.is_file() or path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".mdx"}:
                continue
            if path.name.startswith("_"):
                continue
            rel = path.relative_to(pages_dir)
            stem = rel.stem
            segments = list(rel.parts[:-1])
            if stem != "index":
                segments.append(stem)
            route = "/" + "/".join(segments)
            route = route.rstrip("/") or "/"
            kind = "api" if segments and segments[0] == "api" else "page"
            routes.append(
                {
                    "route": route,
                    "kind": kind,
                    "file": path.relative_to(project_dir).as_posix(),
                }
            )
    return _dedupe_objects(routes)[:100]


def _build_project_graph(projects: list[dict[str, Any]]) -> dict[str, Any]:
    projects_by_name: dict[str, list[dict[str, Any]]] = {}
    for project in projects:
        name = project.get("name")
        if isinstance(name, str):
            projects_by_name.setdefault(name, []).append(project)

    edges: list[dict[str, Any]] = []
    for project in projects:
        source_path = project["path"]
        seen_targets: set[str] = set()
        for dependency in project.get("declared_dependencies") or []:
            for target in projects_by_name.get(dependency, []):
                target_path = target["path"]
                if target_path == source_path or target_path in seen_targets:
                    continue
                seen_targets.add(target_path)
                edges.append(
                    {
                        "from": source_path,
                        "to": target_path,
                        "dependency": dependency,
                        "kind": "internal_dependency",
                    }
                )
        patterns = project.get("workspace_patterns") or []
        workspace_children = []
        for target in projects:
            target_path = target["path"]
            if target_path == source_path:
                continue
            if not any(_matches_workspace_pattern(target_path, pattern) for pattern in patterns):
                continue
            workspace_children.append(target_path)
            edges.append(
                {
                    "from": source_path,
                    "to": target_path,
                    "dependency": target["name"],
                    "kind": "workspace_child",
                }
            )
        project["workspace_children"] = sorted(set(workspace_children))

    deduped_edges = _dedupe_objects(edges)
    adjacency: dict[str, list[str]] = {}
    incoming: dict[str, int] = {project["path"]: 0 for project in projects}
    for edge in deduped_edges:
        adjacency.setdefault(edge["from"], []).append(edge["to"])
        incoming[edge["to"]] = incoming.get(edge["to"], 0) + 1

    for project in projects:
        internal = [
            edge["to"]
            for edge in deduped_edges
            if edge["from"] == project["path"] and edge["kind"] == "internal_dependency"
        ]
        project["internal_dependencies"] = sorted(set(internal))

    return {
        "edges": deduped_edges,
        "adjacency": {key: sorted(set(value)) for key, value in adjacency.items()},
        "roots": sorted(path for path, degree in incoming.items() if degree == 0),
    }


def _matches_workspace_pattern(path: str, pattern: str) -> bool:
    if fnmatch(path, pattern):
        return True
    return fnmatch(f"{path}/package.json", pattern) or fnmatch(f"{path}/pyproject.toml", pattern)


def _collect_entrypoints(root: Path, out: ScanResult) -> list[dict[str, Any]]:
    entrypoints: list[dict[str, Any]] = []
    for project in out.projects:
        for entry in project.get("entrypoints") or []:
            if not isinstance(entry, dict):
                continue
            enriched = dict(entry)
            enriched.setdefault("project_path", project["path"])
            entrypoints.append(enriched)

    docker = out.files.get("Dockerfile") or {}
    if isinstance(docker, dict):
        if isinstance(docker.get("entrypoint"), str):
            entrypoints.append(
                {
                    "kind": "docker_entrypoint",
                    "command": docker["entrypoint"],
                    "source": "Dockerfile#ENTRYPOINT",
                }
            )
        if isinstance(docker.get("cmd"), str):
            entrypoints.append(
                {
                    "kind": "docker_cmd",
                    "command": docker["cmd"],
                    "source": "Dockerfile#CMD",
                }
            )

    for compose_name in COMPOSE_NAMES:
        compose = out.files.get(compose_name)
        if not isinstance(compose, dict):
            continue
        for service in compose.get("services") or []:
            if not isinstance(service, dict):
                continue
            label = service.get("entrypoint") or service.get("command")
            if not isinstance(label, str):
                continue
            entrypoints.append(
                {
                    "kind": "compose_service",
                    "command": label,
                    "service": service.get("name"),
                    "source": compose_name,
                }
            )

    return _dedupe_objects(entrypoints)


def _walk_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in sorted(filenames):
            paths.append(Path(dirpath) / filename)
    return paths


def _walk_project_files(project_dir: Path, suffixes: set[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if suffixes is not None and path.suffix not in suffixes:
                continue
            paths.append(path)
    return paths


def _instruction_kind(rel: Path) -> str | None:
    name = rel.name
    if name in INSTRUCTION_FILE_KINDS:
        return INSTRUCTION_FILE_KINDS[name]
    if rel.as_posix() == ".github/copilot-instructions.md":
        return "copilot"
    if len(rel.parts) >= 3 and rel.parts[-3] == ".cursor" and rel.parts[-2] == "rules":
        if rel.suffix in {".md", ".mdc"}:
            return "cursor"
    return None


def _excerpt_text(text: str) -> tuple[str, bool]:
    lines = text.splitlines()[:RULE_EXCERPT_LINES]
    excerpt = "\n".join(lines).strip()
    truncated = len(text) > len(excerpt) or len(text.splitlines()) > RULE_EXCERPT_LINES
    if len(excerpt) > RULE_EXCERPT_CHARS:
        excerpt = excerpt[:RULE_EXCERPT_CHARS].rstrip()
        truncated = True
    return excerpt, truncated


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): raw_value for key, raw_value in value.items() if isinstance(raw_value, str)}


def _normalize_bin_field(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        return {"default": value}
    return _string_mapping(value)


def _normalize_workspaces(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict) and isinstance(value.get("packages"), list):
        return [str(item) for item in value["packages"]]
    return []


def _normalize_optional_dependencies(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, raw_items in value.items():
        if isinstance(raw_items, list):
            out[str(key)] = [str(item) for item in raw_items]
    return out


def _normalize_python_dependency_entries(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            name = _python_requirement_name(entry)
            if name:
                names.append(name)
    return sorted(set(names))


def _normalize_dependency_keys(value: Any, drop: set[str] | None = None) -> list[str]:
    if not isinstance(value, dict):
        return []
    drop = drop or set()
    return sorted(str(key) for key in value.keys() if str(key) not in drop)


def _python_requirement_name(requirement: str) -> str | None:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", requirement)
    if match is None:
        return None
    return match.group(1)


def _normalize_cargo_bin(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, str] = {}
    for key in ("name", "path"):
        if isinstance(value.get(key), str):
            out[key] = value[key]
    return out or None


def _infer_framework_hints(packages: list[str]) -> list[str]:
    hints = {FRAMEWORK_HINTS[pkg] for pkg in packages if pkg in FRAMEWORK_HINTS}
    return sorted(hints)


def _pick_js_package_manager(project_dir: Path, package_data: dict[str, Any]) -> str:
    if (project_dir / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (project_dir / "yarn.lock").is_file():
        return "yarn"
    if (project_dir / "bun.lock").is_file() or (project_dir / "bun.lockb").is_file():
        return "bun"
    package_manager = package_data.get("packageManager")
    if isinstance(package_manager, str) and package_manager.startswith("pnpm"):
        return "pnpm"
    if isinstance(package_manager, str) and package_manager.startswith("yarn"):
        return "yarn"
    if isinstance(package_manager, str) and package_manager.startswith("bun"):
        return "bun"
    return "npm"


def _js_script_command(script_body: str, name: str, package_manager: str) -> str:
    body = script_body.strip()
    if body.startswith(("npm ", "pnpm ", "yarn ", "bun ")):
        return body
    if package_manager == "pnpm":
        return f"pnpm {name}"
    if package_manager == "yarn":
        return f"yarn {name}"
    if package_manager == "bun":
        return f"bun run {name}"
    return f"npm run {name}"


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _flatten_optional_deps(optional_deps: dict[str, list[str]]) -> list[str]:
    items: list[str] = []
    for group in optional_deps.values():
        items.extend(_normalize_python_dependency_entries(group))
    return sorted(set(items))


def _join_rel(base: str, child: str) -> str:
    if base == ".":
        return child
    return f"{base}/{child}"


def _dedupe_objects(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out
