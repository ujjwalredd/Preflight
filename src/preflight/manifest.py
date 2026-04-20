from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight.config import PreflightOverrides
from preflight.scanner import COMPOSE_NAMES, ScanResult, scan

COMMAND_SCORES = {
    "override": 200,
    "explicit_script": 120,
    "make_target": 90,
    "cargo_default": 80,
    "go_default": 80,
    "ci_command": 65,
    "tooling_hint": 55,
    "package_manager": 50,
}
COMMAND_RISK = {
    "install": "high",
    "build": "medium",
    "dev": "medium",
    "start": "medium",
    "test": "low",
    "lint": "low",
    "check": "low",
    "ci": "high",
}


def build_manifest(
    root: Path,
    overrides: PreflightOverrides | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    overrides = overrides or PreflightOverrides.load(root)
    scan_result = scan(root, use_cache=use_cache)
    commands = _infer_commands(scan_result, overrides)
    conflicts = _detect_conflicts(scan_result, commands)
    display_name = overrides.display_name or _default_display_name(scan_result)

    manifest: dict[str, Any] = {
        "preflight_version": 3,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "root": str(scan_result.root),
        "display_name": display_name,
        "schema_ref": "manifest.schema.json",
        "commands": commands,
        "canonical_commands": {name: meta["command"] for name, meta in commands.items()},
        "sources": scan_result.files,
        "rules": scan_result.rules,
        "agent_rule_files": scan_result.agent_rules,
        "projects": scan_result.projects,
        "project_graph": scan_result.project_graph,
        "entrypoints": scan_result.entrypoints,
        "evidence": _build_evidence_summary(scan_result, commands),
        "cache": scan_result.cache,
        "human_notes": overrides.notes,
        "warnings": overrides.warnings + scan_result.warnings + conflicts,
    }
    manifest["agent_bootstrap"] = {
        "markdown": manifest_to_bootstrap(manifest),
        "text": manifest_to_bootstrap(manifest, plain=True),
    }
    return manifest


def manifest_to_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def manifest_to_markdown(manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    title = manifest.get("display_name") or Path(manifest["root"]).name
    lines.append(f"# Preflight manifest: {title}")
    lines.append("")
    lines.append(f"- **Root:** `{manifest['root']}`")
    lines.append(f"- **Generated:** {manifest['generated_at']}")
    cache = manifest.get("cache") or {}
    if isinstance(cache, dict):
        lines.append(f"- **Cache:** {cache.get('status', 'unknown')}")
    lines.append("")

    projects = manifest.get("projects") or []
    if projects:
        lines.append("## Projects")
        lines.append("")
        for project in projects:
            if not isinstance(project, dict):
                continue
            path = project.get("path") or "."
            kinds = ", ".join(project.get("types") or [])
            frameworks = ", ".join(project.get("framework_hints") or [])
            lines.append(f"- **{project.get('name', path)}** `{path}`")
            if kinds:
                lines.append(f"  - Types: {kinds}")
            if frameworks:
                lines.append(f"  - Frameworks: {frameworks}")
            internal = ", ".join(project.get("internal_dependencies") or [])
            if internal:
                lines.append(f"  - Internal deps: {internal}")
        lines.append("")

    commands = manifest.get("commands") or {}
    if commands:
        lines.append("## Commands")
        lines.append("")
        for name in sorted(commands):
            meta = commands[name]
            if not isinstance(meta, dict):
                continue
            summary = (
                f"{meta.get('confidence')} confidence, "
                f"{meta.get('risk')} risk"
            )
            lines.append(
                f"- **{name}:** `{meta.get('command')}` ({summary})"
            )
        lines.append("")

    entrypoints = manifest.get("entrypoints") or []
    if entrypoints:
        lines.append("## Entrypoints")
        lines.append("")
        for entry in entrypoints:
            if not isinstance(entry, dict):
                continue
            label = entry.get("path") or entry.get("command") or entry.get("target") or "unknown"
            lines.append(f"- **{entry.get('kind', 'entrypoint')}:** `{label}`")
        lines.append("")

    graph = manifest.get("project_graph") or {}
    edges = graph.get("edges") if isinstance(graph, dict) else []
    if isinstance(edges, list) and edges:
        lines.append("## Project Graph")
        lines.append("")
        for edge in edges[:20]:
            if not isinstance(edge, dict):
                continue
            detail = f"{edge.get('kind')}: {edge.get('dependency')}"
            lines.append(
                f"- `{edge.get('from')}` -> `{edge.get('to')}` ({detail})"
            )
        lines.append("")

    rules = manifest.get("rules") or []
    if rules:
        lines.append("## AI Rules")
        lines.append("")
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            lines.append(f"- **{rule.get('kind')}:** `{rule.get('path')}`")
        lines.append("")

    warns = manifest.get("warnings") or []
    if warns:
        lines.append("## Warnings")
        lines.append("")
        for warning in warns:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## Agent Bootstrap")
    lines.append("")
    bootstrap = manifest.get("agent_bootstrap") or {}
    lines.append("```markdown")
    lines.append(bootstrap.get("markdown", "").strip())
    lines.append("```")
    lines.append("")

    lines.append("## Raw Signals (truncated)")
    lines.append("")
    lines.append("```json")
    raw = json.dumps(manifest.get("sources"), indent=2)
    if len(raw) > 12000:
        raw = raw[:12000] + "\n... (truncated)"
    lines.append(raw)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def manifest_to_bootstrap(manifest: dict[str, Any], plain: bool = False) -> str:
    title = manifest.get("display_name") or Path(manifest["root"]).name
    commands = manifest.get("commands") or {}
    projects = manifest.get("projects") or []
    rules = manifest.get("rules") or []
    warnings = manifest.get("warnings") or []
    entrypoints = manifest.get("entrypoints") or []
    graph = manifest.get("project_graph") or {}
    edges = graph.get("edges") if isinstance(graph, dict) else []

    command_lines = []
    for name in ("install", "lint", "test", "build", "dev", "start"):
        meta = commands.get(name)
        if isinstance(meta, dict):
            command_lines.append(f"{name}: {meta['command']}")

    project_lines = []
    for project in projects[:6]:
        if not isinstance(project, dict):
            continue
        kinds = ", ".join(project.get("types") or [])
        frameworks = ", ".join(project.get("framework_hints") or [])
        parts = [f"{project.get('name')} ({project.get('path')})"]
        if kinds:
            parts.append(kinds)
        if frameworks:
            parts.append(frameworks)
        project_lines.append(" | ".join(parts))

    rule_lines = [str(rule["path"]) for rule in rules[:5] if isinstance(rule, dict)]
    entry_lines = []
    for entry in entrypoints[:6]:
        if not isinstance(entry, dict):
            continue
        label = entry.get("path") or entry.get("command") or entry.get("target") or "unknown"
        entry_lines.append(f"{entry.get('kind')}: {label}")

    analysis_lines = _bootstrap_analysis_lines(projects)
    edge_lines = []
    for edge in edges[:6] if isinstance(edges, list) else []:
        if isinstance(edge, dict):
            edge_lines.append(f"{edge.get('from')} -> {edge.get('to')} ({edge.get('kind')})")

    if plain:
        planned_commands = [f"- {line}" for line in command_lines] or ["- none detected"]
        planned_projects = [f"- {line}" for line in project_lines] or ["- none detected"]
        planned_entries = [f"- {line}" for line in entry_lines] or ["- none detected"]
        planned_rules = [f"- {line}" for line in rule_lines] or ["- none detected"]
        planned_analysis = [f"- {line}" for line in analysis_lines] or ["- no framework analysis"]
        planned_edges = [f"- {line}" for line in edge_lines] or ["- no internal edges"]
        planned_warnings = [f"- {line}" for line in warnings[:8]] or ["- none"]
        lines = [
            f"Preflight bootstrap for {title}",
            f"Root: {manifest['root']}",
            "Commands:",
            *planned_commands,
            "Projects:",
            *planned_projects,
            "Entrypoints:",
            *planned_entries,
            "Rules:",
            *planned_rules,
            "Architecture:",
            *planned_analysis,
            "Graph:",
            *planned_edges,
            "Warnings:",
            *planned_warnings,
        ]
        return "\n".join(lines)

    lines = [f"# Preflight bootstrap: {title}", ""]
    lines.append(f"- **Root:** `{manifest['root']}`")
    lines.append("")
    lines.append("## Recommended commands")
    lines.append("")
    for line in command_lines or ["none detected"]:
        lines.append(f"- `{line}`" if line != "none detected" else "- none detected")
    lines.append("")
    lines.append("## Project layout")
    lines.append("")
    for line in project_lines or ["none detected"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## Entrypoints")
    lines.append("")
    for line in entry_lines or ["none detected"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## Rules")
    lines.append("")
    for line in rule_lines or ["none detected"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## High-signal architecture")
    lines.append("")
    for line in analysis_lines or ["no framework analysis"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## Internal graph")
    lines.append("")
    for line in edge_lines or ["no internal edges"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    for warning in warnings[:8] or ["none"]:
        lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def _bootstrap_analysis_lines(projects: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        analysis = project.get("analysis")
        if not isinstance(analysis, dict):
            continue
        if analysis.get("fastapi_routes"):
            routes = analysis["fastapi_routes"][:4]
            summary = ", ".join(f"{route['method']} {route['path']}" for route in routes)
            lines.append(f"{project['path']}: FastAPI routes {summary}")
        if analysis.get("next_routes"):
            routes = analysis["next_routes"][:4]
            summary = ", ".join(route["route"] for route in routes)
            lines.append(f"{project['path']}: Next.js routes {summary}")
        if analysis.get("django"):
            django = analysis["django"]
            settings = ", ".join(django.get("settings_files") or [])
            if settings:
                lines.append(f"{project['path']}: Django settings {settings}")
    return lines[:10]


def _infer_commands(
    scan_result: ScanResult,
    overrides: PreflightOverrides,
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    pkg = scan_result.files.get("package.json") or {}
    pyproject = scan_result.files.get("pyproject.toml") or {}
    github_actions = scan_result.files.get("github_actions") or []
    makefile = scan_result.files.get("Makefile") or {}

    if isinstance(pkg, dict):
        scripts = pkg.get("scripts") or {}
        package_manager = _pick_package_manager(scan_result)
        if isinstance(scripts, dict):
            for key in ("test", "lint", "build", "dev", "start"):
                if key in scripts and isinstance(scripts[key], str):
                    _add_candidate(
                        candidates,
                        key,
                        _js_script_command(scripts[key], key, package_manager),
                        "package.json#scripts",
                        "explicit_script",
                        detail=f"package.json script `{key}` exists",
                    )
        if (scan_result.root / "package.json").is_file():
            _add_candidate(
                candidates,
                "install",
                _install_command_for_pm(package_manager),
                "package.json + lockfile",
                "package_manager",
                detail=f"package manager resolved to `{package_manager}`",
            )

    if isinstance(pyproject, dict):
        dependencies = set(pyproject.get("dependencies") or [])
        optional = pyproject.get("optional_dependencies") or {}
        optional_deps: set[str] = set()
        if isinstance(optional, dict):
            for values in optional.values():
                if isinstance(values, list):
                    optional_deps.update(_dependency_names_from_entries(values))
        tools = set(pyproject.get("tool_sections") or [])
        prefix = "uv run " if _has_lockfile(scan_result, "uv.lock") else ""
        src_prefix = "PYTHONPATH=src " if _needs_pythonpath_prefix(scan_result) else ""
        if (scan_result.root / "pyproject.toml").is_file():
            install_cmd = "uv sync" if _has_lockfile(scan_result, "uv.lock") else "pip install -e ."
            _add_candidate(
                candidates,
                "install",
                install_cmd,
                "pyproject.toml",
                "package_manager",
                detail="python project install command inferred from pyproject.toml",
            )
        if "pytest" in dependencies or "pytest" in optional_deps or "pytest" in tools:
            _add_candidate(
                candidates,
                "test",
                f"{src_prefix}{prefix}pytest".strip(),
                "pyproject.toml",
                "tooling_hint",
                detail="pytest detected in dependencies or tool config",
            )
        if "ruff" in dependencies or "ruff" in optional_deps or "ruff" in tools:
            _add_candidate(
                candidates,
                "lint",
                f"{prefix}ruff check .".strip(),
                "pyproject.toml",
                "tooling_hint",
                detail="ruff detected in dependencies or tool config",
            )

    if (scan_result.root / "Cargo.toml").is_file():
        _add_candidate(
            candidates,
            "test",
            "cargo test",
            "Cargo.toml",
            "cargo_default",
            detail="default Rust test command",
        )
        _add_candidate(
            candidates,
            "build",
            "cargo build",
            "Cargo.toml",
            "cargo_default",
            detail="default Rust build command",
        )
        _add_candidate(
            candidates,
            "lint",
            "cargo clippy",
            "Cargo.toml",
            "cargo_default",
            detail="default Rust lint command",
        )

    if (scan_result.root / "go.mod").is_file():
        _add_candidate(
            candidates,
            "test",
            "go test ./...",
            "go.mod",
            "go_default",
            detail="default Go test command",
        )
        _add_candidate(
            candidates,
            "build",
            "go build ./...",
            "go.mod",
            "go_default",
            detail="default Go build command",
        )

    targets = makefile.get("targets") or []
    if isinstance(targets, list):
        for name in ("test", "lint", "check", "ci"):
            if name in targets:
                _add_candidate(
                    candidates,
                    name,
                    f"make {name}",
                    "Makefile",
                    "make_target",
                    detail=f"Makefile target `{name}` exists",
                )

    if isinstance(github_actions, list):
        for workflow in github_actions:
            if not isinstance(workflow, dict):
                continue
            for run_command in workflow.get("run_commands") or []:
                if not isinstance(run_command, str):
                    continue
                normalized = run_command.strip()
                matched = _classify_ci_command(normalized)
                if matched is None:
                    continue
                _add_candidate(
                    candidates,
                    matched,
                    normalized,
                    workflow.get("file", "github_actions"),
                    "ci_command",
                    detail="command observed in CI workflow",
                )

    commands: dict[str, dict[str, Any]] = {}
    for name, items in candidates.items():
        chosen = max(items, key=lambda item: item["score"])
        commands[name] = {
            "command": chosen["command"],
            "confidence": _confidence_label(chosen["score"]),
            "source": chosen["source"],
            "risk": _command_risk(name, chosen["command"]),
            "evidence": _strip_scores(items),
        }

    for name, command in overrides.canonical.items():
        previous = commands.get(name, {})
        evidence = previous.get("evidence") if isinstance(previous, dict) else []
        if not isinstance(evidence, list):
            evidence = []
        commands[name] = {
            "command": command,
            "confidence": "override",
            "source": ".preflight.json#canonical",
            "risk": _command_risk(name, command),
            "evidence": [
                {
                    "command": command,
                    "source": ".preflight.json#canonical",
                    "detail": "explicit maintainer override",
                    "kind": "override",
                },
                *[item for item in evidence if isinstance(item, dict)],
            ],
        }

    return dict(sorted(commands.items()))


def _default_display_name(scan_result: ScanResult) -> str | None:
    if scan_result.projects:
        primary = scan_result.projects[0]
        if isinstance(primary, dict):
            name = primary.get("name")
            if isinstance(name, str):
                return name
    return None


def _build_evidence_summary(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_files": sorted(scan_result.files.keys()),
        "project_markers": [
            {"path": project["path"], "markers": project["markers"]}
            for project in scan_result.projects
            if isinstance(project, dict)
        ],
        "rule_files": [
            {"path": rule["path"], "kind": rule["kind"]}
            for rule in scan_result.rules
            if isinstance(rule, dict)
        ],
        "command_sources": {
            name: meta.get("evidence", [])
            for name, meta in commands.items()
            if isinstance(meta, dict)
        },
        "cache": scan_result.cache,
        "graph_edge_count": len(scan_result.project_graph.get("edges") or []),
    }


def _detect_conflicts(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
) -> list[str]:
    messages: list[str] = []
    locks = scan_result.files.get("lockfiles") or {}
    pkg = scan_result.files.get("package.json") or {}
    if isinstance(locks, dict) and isinstance(pkg, dict):
        package_manager = pkg.get("packageManager")
        if "yarn.lock" in locks and "package-lock.json" in locks:
            messages.append(
                "Both yarn.lock and package-lock.json present; pick one package manager."
            )
        if (
            isinstance(package_manager, str)
            and "yarn" in package_manager
            and "package-lock.json" in locks
        ):
            messages.append("packageManager suggests Yarn but package-lock.json exists.")
        if isinstance(package_manager, str) and "pnpm" in package_manager and "yarn.lock" in locks:
            messages.append("packageManager suggests pnpm but yarn.lock exists.")

    readme = scan_result.files.get("README.md") or {}
    preview = readme.get("preview_lines") or []
    if isinstance(preview, list):
        blob = "\n".join(str(line) for line in preview)
        if "yarn" in blob.lower() and isinstance(locks, dict) and "package-lock.json" in locks:
            messages.append("README mentions Yarn but npm lockfile detected.")
        if "pnpm" in blob.lower() and isinstance(locks, dict) and "yarn.lock" in locks:
            messages.append("README mentions pnpm but yarn.lock detected.")

    github_actions = scan_result.files.get("github_actions") or []
    if isinstance(github_actions, list) and github_actions and "test" not in commands:
        has_testish = False
        for workflow in github_actions:
            if not isinstance(workflow, dict):
                continue
            for line in workflow.get("run_commands") or []:
                if not isinstance(line, str):
                    continue
                if re.search(
                    r"\b(pytest|tox|npm test|pnpm test|yarn test|cargo test|go test)\b",
                    line,
                ):
                    has_testish = True
        if has_testish:
            messages.append("CI appears to run tests but no local `test` command was inferred.")

    if len(scan_result.projects) > 1:
        messages.append("Multiple projects detected; check `project_graph` and `projects`.")

    compose_names = [name for name in COMPOSE_NAMES if name in scan_result.files]
    if compose_names and not scan_result.entrypoints:
        messages.append("Compose services detected but no entrypoints were extracted.")

    return messages


def _pick_package_manager(scan_result: ScanResult) -> str:
    locks = scan_result.files.get("lockfiles") or {}
    if not isinstance(locks, dict):
        locks = {}
    if "pnpm-lock.yaml" in locks:
        return "pnpm"
    if "yarn.lock" in locks:
        return "yarn"
    if "bun.lock" in locks or "bun.lockb" in locks:
        return "bun"
    pkg = scan_result.files.get("package.json") or {}
    package_manager = pkg.get("packageManager")
    if isinstance(package_manager, str) and package_manager.startswith("pnpm"):
        return "pnpm"
    if isinstance(package_manager, str) and package_manager.startswith("yarn"):
        return "yarn"
    if isinstance(package_manager, str) and package_manager.startswith("bun"):
        return "bun"
    return "npm"


def _has_lockfile(scan_result: ScanResult, name: str) -> bool:
    locks = scan_result.files.get("lockfiles") or {}
    return isinstance(locks, dict) and name in locks


def _needs_pythonpath_prefix(scan_result: ScanResult) -> bool:
    return (scan_result.root / "src").is_dir() and (scan_result.root / "tests").exists()


def _install_command_for_pm(package_manager: str) -> str:
    if package_manager == "yarn":
        return "yarn install"
    if package_manager == "pnpm":
        return "pnpm install"
    if package_manager == "bun":
        return "bun install"
    return "npm install"


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


def _add_candidate(
    candidates: dict[str, list[dict[str, Any]]],
    name: str,
    command: str,
    source: str,
    kind: str,
    detail: str,
) -> None:
    candidates.setdefault(name, []).append(
        {
            "command": command,
            "source": source,
            "kind": kind,
            "detail": detail,
            "score": COMMAND_SCORES[kind],
        }
    )


def _strip_scores(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "command": item["command"],
            "source": item["source"],
            "kind": item["kind"],
            "detail": item["detail"],
        }
        for item in items
    ]


def _confidence_label(score: int) -> str:
    if score >= 110:
        return "high"
    if score >= 75:
        return "medium"
    return "low"


def _dependency_names_from_entries(entries: list[str]) -> list[str]:
    names: list[str] = []
    for entry in entries:
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)", entry)
        if match:
            names.append(match.group(1))
    return names


def _classify_ci_command(command: str) -> str | None:
    if re.search(r"\b(pytest|tox|npm test|pnpm test|yarn test|cargo test|go test)\b", command):
        return "test"
    if re.search(
        r"\b(ruff check|eslint|cargo clippy|npm run lint|pnpm lint|yarn lint)\b",
        command,
    ):
        return "lint"
    if re.search(r"\b(npm run build|pnpm build|yarn build|cargo build|go build)\b", command):
        return "build"
    if re.search(
        r"\b(npm install|pnpm install|yarn install|bun install|uv sync|pip install)\b",
        command,
    ):
        return "install"
    return None


def _command_risk(name: str, command: str) -> str:
    if re.search(r"(^|[^\w])(rm|sudo|dd|mkfs|shutdown|reboot)([^\w]|$)", command):
        return "critical"
    if any(token in command for token in ("|", "&&", "||", ";", ">", "<", "`", "$(")):
        return "high"
    return COMMAND_RISK.get(name, "medium")
