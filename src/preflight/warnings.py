from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from preflight.scanner import COMPOSE_NAMES, ScanResult

CommandCandidates = dict[str, list[dict[str, Any]]]

PACKAGE_MANAGER_TERMS = ("npm", "pnpm", "yarn", "bun", "uv", "pip")
RULE_KIND_LABELS = {
    "agents": "AGENTS",
    "claude": "CLAUDE",
    "copilot": "Copilot",
    "contributing": "CONTRIBUTING",
    "cursor": "Cursor",
    "gemini": "GEMINI",
}


@dataclass(frozen=True)
class WarningObject:
    id: str
    severity: str
    category: str
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    affected_paths: list[str] = field(default_factory=list)
    suggested_action: str | None = None
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "evidence": self.evidence,
            "affected_paths": self.affected_paths,
            "confidence": self.confidence,
        }
        if self.suggested_action is not None:
            payload["suggested_action"] = self.suggested_action
        return payload


def build_warning_objects(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
    command_candidates: CommandCandidates,
    raw_warnings: list[str],
) -> list[dict[str, Any]]:
    warnings: list[WarningObject] = []
    warnings.extend(_raw_warning_objects(raw_warnings))
    warnings.extend(_detect_package_manager_conflicts(scan_result))
    warnings.extend(_detect_command_context_warnings(scan_result, commands, command_candidates))
    warnings.extend(_detect_monorepo_warnings(scan_result, commands, command_candidates))
    warnings.extend(_detect_rule_and_doc_warnings(scan_result))
    warnings.extend(_detect_analyzer_coverage_warnings(scan_result, commands))
    return [warning.to_dict() for warning in _dedupe_warning_objects(warnings)]


def warning_strings(warning_objects: list[dict[str, Any]]) -> list[str]:
    strings: list[str] = []
    for warning in warning_objects:
        message = warning.get("message")
        if isinstance(message, str):
            strings.append(message)
    return strings


def _raw_warning_objects(raw_warnings: list[str]) -> list[WarningObject]:
    out: list[WarningObject] = []
    for message in raw_warnings:
        out.append(
            WarningObject(
                id=f"raw_{_slug(message)}",
                severity="warning",
                category="scan",
                message=message,
                evidence=[{"kind": "raw_warning", "detail": message}],
                affected_paths=_guess_paths_from_text(message),
                suggested_action=(
                    "Inspect the referenced file or parsing issue before "
                    "relying on the manifest."
                ),
                confidence="high",
            )
        )
    return out


def _detect_package_manager_conflicts(scan_result: ScanResult) -> list[WarningObject]:
    warnings: list[WarningObject] = []
    locks = scan_result.files.get("lockfiles") or {}
    pkg = scan_result.files.get("package.json") or {}
    readme = scan_result.files.get("README.md") or {}
    github_actions = scan_result.files.get("github_actions") or []

    if not isinstance(locks, dict):
        locks = {}
    if not isinstance(pkg, dict):
        pkg = {}
    if not isinstance(readme, dict):
        readme = {}
    if not isinstance(github_actions, list):
        github_actions = []

    detected_pm = _detected_package_manager(locks, pkg)
    workflow_terms = _package_managers_from_workflows(github_actions)
    readme_terms = _package_managers_from_lines(readme.get("preview_lines") or [])
    affected_paths = sorted(
        set(
            [
                "package.json",
                "README.md",
                *locks.keys(),
                *[item.get("file") for item in github_actions],
            ]
        )
    )
    affected_paths = [path for path in affected_paths if isinstance(path, str)]

    if "yarn.lock" in locks and "package-lock.json" in locks:
        warnings.append(
            WarningObject(
                id="mixed_lockfiles",
                severity="warning",
                category="package_manager",
                message=(
                    "Both yarn.lock and package-lock.json are present; "
                    "package-manager intent is ambiguous."
                ),
                evidence=[
                    {
                        "kind": "lockfile",
                        "source": "yarn.lock",
                        "detail": "yarn lockfile committed",
                    },
                    {
                        "kind": "lockfile",
                        "source": "package-lock.json",
                        "detail": "npm lockfile committed",
                    },
                ],
                affected_paths=["yarn.lock", "package-lock.json"],
                suggested_action=(
                    "Commit a single lockfile or document which package "
                    "manager should win."
                ),
                confidence="high",
            )
        )

    package_manager = pkg.get("packageManager")
    if (
        isinstance(package_manager, str)
        and package_manager.startswith("yarn")
        and "package-lock.json" in locks
    ):
        warnings.append(
            WarningObject(
                id="package_manager_lock_mismatch",
                severity="warning",
                category="package_manager",
                message="packageManager declares Yarn but package-lock.json is present.",
                evidence=[
                    {
                        "kind": "package_manager",
                        "source": "package.json",
                        "detail": f"packageManager={package_manager}",
                    },
                    {
                        "kind": "lockfile",
                        "source": "package-lock.json",
                        "detail": "npm lockfile committed",
                    },
                ],
                affected_paths=["package.json", "package-lock.json"],
                suggested_action=(
                    "Align packageManager, lockfiles, and onboarding docs to "
                    "the same tool."
                ),
                confidence="high",
            )
        )
    if (
        isinstance(package_manager, str)
        and package_manager.startswith("pnpm")
        and "yarn.lock" in locks
    ):
        warnings.append(
            WarningObject(
                id="package_manager_lock_mismatch_pnpm_yarn",
                severity="warning",
                category="package_manager",
                message="packageManager declares pnpm but yarn.lock is present.",
                evidence=[
                    {
                        "kind": "package_manager",
                        "source": "package.json",
                        "detail": f"packageManager={package_manager}",
                    },
                    {
                        "kind": "lockfile",
                        "source": "yarn.lock",
                        "detail": "Yarn lockfile committed",
                    },
                ],
                affected_paths=["package.json", "yarn.lock"],
                suggested_action=(
                    "Remove the stale lockfile or switch packageManager to "
                    "match committed artifacts."
                ),
                confidence="high",
            )
        )

    if detected_pm is not None and readme_terms and detected_pm not in readme_terms:
        warnings.append(
            WarningObject(
                id="readme_package_manager_mismatch",
                severity="warning",
                category="docs",
                message=(
                    f"README onboarding mentions {', '.join(sorted(readme_terms))}, "
                    f"but the repo resolves to {detected_pm}."
                ),
                evidence=[
                    {
                        "kind": "readme_preview",
                        "source": "README.md",
                        "detail": f"package-manager terms seen: {', '.join(sorted(readme_terms))}",
                    },
                    {
                        "kind": "detected_package_manager",
                        "source": "package.json/lockfiles",
                        "detail": f"resolved package manager: {detected_pm}",
                    },
                ],
                affected_paths=[
                    path for path in ["README.md", "package.json", *locks.keys()] if path
                ],
                suggested_action=(
                    "Update README install/test instructions to match the "
                    "committed package manager."
                ),
                confidence="medium",
            )
        )

    if detected_pm is not None and workflow_terms and detected_pm not in workflow_terms:
        warnings.append(
            WarningObject(
                id="workflow_package_manager_mismatch",
                severity="warning",
                category="docs",
                message=(
                    f"Workflow commands use {', '.join(sorted(workflow_terms))}, "
                    f"but the repo resolves to {detected_pm}."
                ),
                evidence=[
                    {
                        "kind": "workflow_package_managers",
                        "source": ".github/workflows",
                        "detail": (
                            "package-manager terms seen in workflows: "
                            f"{', '.join(sorted(workflow_terms))}"
                        ),
                    },
                    {
                        "kind": "detected_package_manager",
                        "source": "package.json/lockfiles",
                        "detail": f"resolved package manager: {detected_pm}",
                    },
                ],
                affected_paths=affected_paths,
                suggested_action="Align CI install steps with the repo's declared package manager.",
                confidence="medium",
            )
        )

    js_workflow_terms = {term for term in workflow_terms if term in {"npm", "pnpm", "yarn", "bun"}}
    if len(js_workflow_terms) > 1:
        warnings.append(
            WarningObject(
                id="mixed_package_managers_in_workflows",
                severity="warning",
                category="package_manager",
                message=(
                    "Workflow commands mix package managers "
                    f"({', '.join(sorted(js_workflow_terms))}); "
                    "install semantics may drift across jobs."
                ),
                evidence=[
                    {
                        "kind": "workflow_package_managers",
                        "source": ".github/workflows",
                        "detail": (
                            "package-manager terms seen in workflows: "
                            f"{', '.join(sorted(js_workflow_terms))}"
                        ),
                    }
                ],
                affected_paths=[
                    item.get("file") for item in github_actions if isinstance(item, dict)
                ],
                suggested_action=(
                    "Standardize workflow jobs on one package manager or "
                    "document intentional exceptions."
                ),
                confidence="high",
            )
        )

    return warnings


def _detect_command_context_warnings(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
    command_candidates: CommandCandidates,
) -> list[WarningObject]:
    warnings: list[WarningObject] = []
    project_count = len(scan_result.projects)

    for name, meta in commands.items():
        if not isinstance(meta, dict):
            continue
        chosen_command = meta.get("command")
        chosen_context = meta.get("context")
        if not isinstance(chosen_command, str) or not isinstance(chosen_context, str):
            continue
        candidates = command_candidates.get(name) or []
        local_commands = sorted(
            {
                item["command"]
                for item in candidates
                if item.get("context") == "dev" and item.get("usable", True)
            }
        )
        ci_commands = sorted(
            {
                item["command"]
                for item in candidates
                if item.get("context") in {"ci", "release", "publish", "benchmark"}
                and item.get("usable", True)
            }
        )
        release_commands = sorted(
            {
                item["command"]
                for item in candidates
                if item.get("context") in {"release", "publish"} and item.get("usable", True)
            }
        )
        ci_sources = sorted(
            {
                str(item.get("source"))
                for item in candidates
                if item.get("context") in {"ci", "release", "publish", "benchmark"}
            }
        )

        if (
            project_count > 1
            and local_commands
            and ci_commands
            and set(local_commands) != set(ci_commands)
        ):
            samples = ", ".join(ci_commands[:3])
            warnings.append(
                WarningObject(
                    id=f"{name}_ci_local_drift",
                    severity="warning",
                    category="command_context",
                    message=(
                        f"Local and CI `{name}` commands diverge; canonical "
                        f"`{chosen_command}` differs from CI variants like "
                        f"`{samples}`."
                    ),
                    evidence=[
                        {
                            "kind": "local_commands",
                            "source": "local",
                            "detail": ", ".join(local_commands[:3]),
                        },
                        {
                            "kind": "ci_commands",
                            "source": ".github/workflows",
                            "detail": ", ".join(ci_commands[:3]),
                        },
                    ],
                    affected_paths=ci_sources,
                    suggested_action=(
                        "Treat the canonical command as a local default and "
                        "document CI-only variants separately."
                    ),
                    confidence="high",
                )
            )

        if project_count > 1 and release_commands and chosen_context not in {"release", "publish"}:
            warnings.append(
                WarningObject(
                    id=f"{name}_release_variants_excluded",
                    severity="info",
                    category="command_context",
                    message=(
                        f"Release-only `{name}` variants were excluded from "
                        f"the canonical local `{name}` command."
                    ),
                    evidence=[
                        {
                            "kind": "release_commands",
                            "source": ".github/workflows",
                            "detail": ", ".join(release_commands[:3]),
                        },
                        {
                            "kind": "chosen_command",
                            "source": str(meta.get("source")),
                            "detail": str(chosen_command),
                        },
                    ],
                    affected_paths=ci_sources,
                    suggested_action=(
                        "Keep canonical commands developer-friendly and treat "
                        "release steps as specialized automation."
                    ),
                    confidence="medium",
                )
            )

        if chosen_context in {"release", "publish"}:
            warnings.append(
                WarningObject(
                    id=f"{name}_canonical_release_only",
                    severity="warning",
                    category="command_context",
                    message=(
                        f"Canonical `{name}` command comes from a "
                        f"{chosen_context} workflow, not a local development "
                        "path."
                    ),
                    evidence=[
                        {
                            "kind": "chosen_command",
                            "source": str(meta.get("source")),
                            "detail": str(chosen_command),
                        }
                    ],
                    affected_paths=[str(meta.get("source"))],
                    suggested_action=(
                        "Infer or override a local developer command so "
                        "release automation does not become the default."
                    ),
                    confidence="high",
                )
            )
        elif project_count > 1 and chosen_context != "dev" and not local_commands:
            warnings.append(
                WarningObject(
                    id=f"{name}_ci_only_command",
                    severity="warning",
                    category="command_context",
                    message=(
                        f"Canonical `{name}` command was inferred only from "
                        "CI workflow evidence; no local developer command was "
                        "found."
                    ),
                    evidence=[
                        {
                            "kind": "chosen_command",
                            "source": str(meta.get("source")),
                            "detail": str(chosen_command),
                        }
                    ],
                    affected_paths=[str(meta.get("source"))],
                    suggested_action=(
                        "Add a script, Make target, or override so local "
                        "execution intent is explicit."
                    ),
                    confidence="medium",
                )
            )
    return warnings


def _detect_monorepo_warnings(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
    command_candidates: CommandCandidates,
) -> list[WarningObject]:
    warnings: list[WarningObject] = []
    project_count = len(scan_result.projects)
    edge_count = len(scan_result.project_graph.get("edges") or [])
    nested_rules = _package_scoped_rules(scan_result.rules)
    mixed_types = sorted(
        {
            str(kind)
            for project in scan_result.projects
            if isinstance(project, dict)
            for kind in project.get("types") or []
        }
    )

    if project_count >= 50:
        warnings.append(
            WarningObject(
                id="large_monorepo",
                severity="warning",
                category="monorepo",
                message=(
                    f"Large monorepo detected: {project_count} projects and "
                    f"{edge_count} graph edges; root bootstrap only shows a "
                    "slice."
                ),
                evidence=[
                    {
                        "kind": "project_count",
                        "source": "project_graph",
                        "detail": str(project_count),
                    },
                    {"kind": "edge_count", "source": "project_graph", "detail": str(edge_count)},
                ],
                affected_paths=["project_graph"],
                suggested_action=(
                    "Scope the scan or bootstrap to a package before making "
                    "targeted edits."
                ),
                confidence="high",
            )
        )

    if project_count >= 20:
        warnings.append(
            WarningObject(
                id="workspace_overflow",
                severity="info",
                category="monorepo",
                message=(
                    f"{project_count} projects were detected; a root-level summary "
                    "cannot represent every workspace accurately."
                ),
                evidence=[
                    {"kind": "project_count", "source": "projects", "detail": str(project_count)}
                ],
                affected_paths=["projects"],
                suggested_action=(
                    "Narrow the working set to one workspace when planning edits or tests."
                ),
                confidence="high",
            )
        )

    if nested_rules:
        samples = ", ".join(nested_rules[:3])
        warnings.append(
            WarningObject(
                id="nested_rules_present",
                severity="warning" if project_count > 1 else "info",
                category="rules",
                message=(
                    f"Nested rule files are present ({samples}); root guidance may not "
                    "apply to every package."
                ),
                evidence=[
                    {
                        "kind": "nested_rules",
                        "source": "rules",
                        "detail": ", ".join(nested_rules[:5]),
                    }
                ],
                affected_paths=nested_rules[:8],
                suggested_action=(
                    "Check package-level AGENTS or contributing files before editing "
                    "nested workspaces."
                ),
                confidence="high",
            )
        )

    if project_count > 1 and len(mixed_types) > 1:
        warnings.append(
            WarningObject(
                id="mixed_toolchains",
                severity="warning",
                category="monorepo",
                message=(
                    f"Mixed toolchains detected across the repo ({', '.join(mixed_types)}); "
                    "one root command set may not fit every project."
                ),
                evidence=[
                    {
                        "kind": "project_types",
                        "source": "projects",
                        "detail": ", ".join(mixed_types),
                    }
                ],
                affected_paths=["projects"],
                suggested_action=(
                    "Scope commands and bootstrap summaries to the language stack "
                    "you are actively editing."
                ),
                confidence="high",
            )
        )

    if project_count >= 10 and edge_count >= 10:
        hotspots = _graph_hotspots(scan_result)
        if hotspots:
            warnings.append(
                WarningObject(
                    id="graph_hotspots",
                    severity="info",
                    category="monorepo",
                    message=f"Most connected projects: {', '.join(hotspots)}.",
                    evidence=[
                        {
                            "kind": "graph_hotspots",
                            "source": "project_graph",
                            "detail": ", ".join(hotspots),
                        }
                    ],
                    affected_paths=["project_graph"],
                    suggested_action=(
                        "Start with high-degree packages when tracing repo-wide changes."
                    ),
                    confidence="medium",
                )
            )

    if project_count >= 10:
        drift_samples: list[str] = []
        for name in ("install", "test", "build"):
            meta = commands.get(name)
            candidates = command_candidates.get(name) or []
            if not isinstance(meta, dict):
                continue
            unique_commands = sorted(
                {item["command"] for item in candidates if item.get("usable", True)}
            )
            if len(unique_commands) < 2:
                continue
            drift_samples.append(f"{name}={meta.get('command')}")
        if drift_samples:
            warnings.append(
                WarningObject(
                    id="root_commands_may_be_misleading",
                    severity="warning",
                    category="monorepo",
                    message=(
                        f"Root commands may be misleading for a {project_count}-project "
                        f"workspace; canonical choices like {', '.join(drift_samples[:3])} "
                        "are only one slice of execution reality."
                    ),
                    evidence=[
                        {
                            "kind": "command_variants",
                            "source": "commands",
                            "detail": ", ".join(drift_samples[:5]),
                        }
                    ],
                    affected_paths=["commands", "projects"],
                    suggested_action=(
                        "Treat root commands as defaults and inspect package-level "
                        "scripts or workflows when scoping work."
                    ),
                    confidence="medium",
                )
            )

    return warnings


def _detect_rule_and_doc_warnings(scan_result: ScanResult) -> list[WarningObject]:
    warnings: list[WarningObject] = []
    rules = scan_result.rules
    rule_kinds = sorted(
        {
            RULE_KIND_LABELS.get(str(rule.get("kind")), str(rule.get("kind")))
            for rule in rules
            if isinstance(rule, dict)
        }
    )
    if len(rules) >= 4:
        warnings.append(
            WarningObject(
                id="multiple_instruction_sources",
                severity="info",
                category="rules",
                message=(
                    f"Multiple instruction sources detected ({', '.join(rule_kinds)}); "
                    "guidance may overlap or conflict across tools."
                ),
                evidence=[
                    {
                        "kind": "rule_kinds",
                        "source": "rules",
                        "detail": ", ".join(rule_kinds),
                    }
                ],
                affected_paths=[
                    str(rule.get("path")) for rule in rules[:8] if isinstance(rule, dict)
                ],
                suggested_action=(
                    "Prefer the most local agent instructions and document precedence "
                    "if files intentionally differ."
                ),
                confidence="medium",
            )
        )
    return warnings


def _detect_analyzer_coverage_warnings(
    scan_result: ScanResult,
    commands: dict[str, dict[str, Any]],
) -> list[WarningObject]:
    warnings: list[WarningObject] = []
    workflows = scan_result.files.get("github_actions") or []
    if not isinstance(workflows, list):
        workflows = []

    if len(workflows) >= 5 and len(commands) <= 2:
        warnings.append(
            WarningObject(
                id="many_workflows_few_commands",
                severity="info",
                category="coverage",
                message=(
                    f"{len(workflows)} workflows were detected, but only "
                    f"{len(commands)} canonical commands were inferred."
                ),
                evidence=[
                    {
                        "kind": "workflow_count",
                        "source": ".github/workflows",
                        "detail": str(len(workflows)),
                    },
                    {
                        "kind": "command_count",
                        "source": "commands",
                        "detail": str(len(commands)),
                    },
                ],
                affected_paths=[item.get("file") for item in workflows if isinstance(item, dict)],
                suggested_action=(
                    "Add more command-context detectors or project-level scripts "
                    "so the manifest explains CI breadth better."
                ),
                confidence="medium",
            )
        )

    if len(scan_result.projects) >= 15 and len(scan_result.entrypoints) <= 2:
        warnings.append(
            WarningObject(
                id="many_projects_few_entrypoints",
                severity="info",
                category="coverage",
                message=(
                    f"{len(scan_result.projects)} projects were detected, but only "
                    f"{len(scan_result.entrypoints)} entrypoints were extracted."
                ),
                evidence=[
                    {
                        "kind": "project_count",
                        "source": "projects",
                        "detail": str(len(scan_result.projects)),
                    },
                    {
                        "kind": "entrypoint_count",
                        "source": "entrypoints",
                        "detail": str(len(scan_result.entrypoints)),
                    },
                ],
                affected_paths=["projects", "entrypoints"],
                suggested_action=(
                    "Add framework or language-specific entrypoint analyzers "
                    "for under-described project types."
                ),
                confidence="medium",
            )
        )

    framework_projects = [
        project
        for project in scan_result.projects
        if isinstance(project, dict) and project.get("framework_hints")
    ]
    analyzed_projects = [
        project
        for project in scan_result.projects
        if isinstance(project, dict) and project.get("analysis")
    ]
    if framework_projects and not analyzed_projects:
        framework_names = sorted(
            {
                str(hint)
                for project in framework_projects
                for hint in project.get("framework_hints") or []
            }
        )
        warnings.append(
            WarningObject(
                id="frameworks_without_detailed_analysis",
                severity="info",
                category="coverage",
                message=(
                    f"Framework hints were detected ({', '.join(framework_names)}), "
                    "but no detailed framework analysis was extracted."
                ),
                evidence=[
                    {
                        "kind": "framework_hints",
                        "source": "projects",
                        "detail": ", ".join(framework_names),
                    }
                ],
                affected_paths=["projects"],
                suggested_action=(
                    "Add analyzers for the hinted frameworks or scope the scan "
                    "to a supported project type."
                ),
                confidence="medium",
            )
        )

    compose_names = [name for name in COMPOSE_NAMES if name in scan_result.files]
    if compose_names and not scan_result.entrypoints:
        warnings.append(
            WarningObject(
                id="compose_without_entrypoints",
                severity="warning",
                category="coverage",
                message=(
                    "Compose services were detected, but no service entrypoints were extracted."
                ),
                evidence=[
                    {
                        "kind": "compose_files",
                        "source": "compose",
                        "detail": ", ".join(compose_names),
                    }
                ],
                affected_paths=compose_names,
                suggested_action=(
                    "Capture service commands or entrypoints from compose metadata "
                    "so the manifest can explain how services start."
                ),
                confidence="high",
            )
        )

    return warnings


def _dedupe_warning_objects(items: list[WarningObject]) -> list[WarningObject]:
    seen: set[str] = set()
    out: list[WarningObject] = []
    for item in items:
        marker = json.dumps(item.to_dict(), sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _graph_hotspots(scan_result: ScanResult) -> list[str]:
    scores: dict[str, int] = {}
    for edge in scan_result.project_graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        scores[edge.get("from", "")] = scores.get(edge.get("from", ""), 0) + 1
        scores[edge.get("to", "")] = scores.get(edge.get("to", ""), 0) + 1
    hotspots = sorted(
        ((path, score) for path, score in scores.items() if path),
        key=lambda item: (-item[1], item[0]),
    )
    return [f"{path} ({score})" for path, score in hotspots[:5]]


def _package_scoped_rules(rules: list[dict[str, Any]]) -> list[str]:
    nested: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        path = str(rule.get("path") or "")
        if "/" not in path:
            continue
        if path.startswith(".github/") or path.startswith(".ai/") or path.startswith(".cursor/"):
            continue
        nested.append(path)
    return nested


def _detected_package_manager(locks: dict[str, Any], package_json: dict[str, Any]) -> str | None:
    package_manager = package_json.get("packageManager")
    if isinstance(package_manager, str):
        for term in PACKAGE_MANAGER_TERMS:
            if package_manager.startswith(term):
                return term
    if "pnpm-lock.yaml" in locks:
        return "pnpm"
    if "yarn.lock" in locks:
        return "yarn"
    if "package-lock.json" in locks:
        return "npm"
    if "bun.lock" in locks or "bun.lockb" in locks:
        return "bun"
    if "uv.lock" in locks:
        return "uv"
    return None


def _package_managers_from_lines(lines: list[Any]) -> set[str]:
    blob = "\n".join(str(line).lower() for line in lines if isinstance(line, str))
    return {term for term in PACKAGE_MANAGER_TERMS if re.search(rf"\b{re.escape(term)}\b", blob)}


def _package_managers_from_workflows(workflows: list[dict[str, Any]]) -> set[str]:
    managers: set[str] = set()
    for workflow in workflows:
        if not isinstance(workflow, dict):
            continue
        managers.update(_package_managers_from_lines(workflow.get("run_commands") or []))
    return managers


def _guess_paths_from_text(text: str) -> list[str]:
    matches = re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)", text)
    out: list[str] = []
    for match in matches:
        if match not in out:
            out.append(match)
    return out[:8]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:48] or "warning"
