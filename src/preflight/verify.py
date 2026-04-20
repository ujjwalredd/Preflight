from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_VERIFY_ORDER = ("install", "lint", "test", "build")
SHELL_OPERATORS = ("|", "&&", "||", ";", ">", "<", "`", "$(")


@dataclass
class ExecutionPlan:
    args: list[str]
    env_overrides: dict[str, str]


def verify_manifest(
    manifest: dict[str, Any],
    selected_commands: list[str] | None = None,
    run: bool = False,
    allow_risky: bool = False,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    commands = manifest.get("commands") or {}
    root = Path(manifest["root"])
    chosen = selected_commands or [name for name in DEFAULT_VERIFY_ORDER if name in commands]
    steps: list[dict[str, Any]] = []
    success = True

    for name in chosen:
        meta = commands.get(name)
        if not isinstance(meta, dict):
            steps.append({"name": name, "status": "missing"})
            success = False
            continue
        command = meta.get("command")
        if not isinstance(command, str):
            steps.append({"name": name, "status": "missing"})
            success = False
            continue

        risk = str(meta.get("risk") or _fallback_risk(name, command))
        allowed, blocked_reason = _allow_execution(name, risk, command, allow_risky)
        step: dict[str, Any] = {
            "name": name,
            "command": command,
            "confidence": meta.get("confidence"),
            "source": meta.get("source"),
            "risk": risk,
            "allowed": allowed,
        }
        if blocked_reason is not None:
            step["blocked_reason"] = blocked_reason

        if not run:
            step["status"] = "planned"
            steps.append(step)
            continue

        if not allowed:
            step["status"] = "blocked"
            steps.append(step)
            success = False
            continue

        plan, parse_error = _parse_command(command)
        if plan is None:
            step["status"] = "blocked"
            step["blocked_reason"] = parse_error or "command could not be executed safely"
            steps.append(step)
            success = False
            continue

        args = _normalize_python_tool_args(plan.args, manifest)
        env = _build_execution_env(root, manifest, plan.env_overrides)
        try:
            completed = subprocess.run(
                args,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            step["status"] = "timeout"
            step["timeout_seconds"] = timeout_seconds
            step["stdout"] = (exc.stdout or "")[-4000:]
            step["stderr"] = (exc.stderr or "")[-4000:]
            steps.append(step)
            success = False
            continue

        step["status"] = "passed" if completed.returncode == 0 else "failed"
        step["returncode"] = completed.returncode
        if completed.stdout:
            step["stdout"] = completed.stdout[-4000:]
        if completed.stderr:
            step["stderr"] = completed.stderr[-4000:]
        steps.append(step)
        success = success and completed.returncode == 0

    return {
        "root": str(root),
        "run": run,
        "selected_commands": chosen,
        "policy": {
            "allow_risky": allow_risky,
            "timeout_seconds": timeout_seconds,
            "shell_policy": "blocked",
        },
        "steps": steps,
        "success": success,
    }


def _allow_execution(
    name: str,
    risk: str,
    command: str,
    allow_risky: bool,
) -> tuple[bool, str | None]:
    if any(operator in command for operator in SHELL_OPERATORS):
        return False, "shell operators are blocked by verify safety policy"
    if risk in {"high", "critical"} and not allow_risky:
        return False, "risky command blocked; rerun with --allow-risky if you want to execute it"
    if name in {"dev", "start"}:
        return False, "long-running commands are not executed by verify"
    return True, None


def _parse_command(command: str) -> tuple[ExecutionPlan | None, str | None]:
    if any(operator in command for operator in SHELL_OPERATORS):
        return None, "shell operators are blocked by verify safety policy"
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return None, f"command could not be parsed: {exc}"
    if not tokens:
        return None, "empty command"

    env_overrides: dict[str, str] = {}
    index = 0
    while index < len(tokens) and _is_env_assignment(tokens[index]):
        key, value = tokens[index].split("=", 1)
        env_overrides[key] = value
        index += 1
    args = tokens[index:]
    if not args:
        return None, "command only contained environment assignments"
    return ExecutionPlan(args=args, env_overrides=env_overrides), None


def _is_env_assignment(token: str) -> bool:
    return re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", token) is not None


def _build_execution_env(
    root: Path,
    manifest: dict[str, Any],
    overrides: dict[str, str],
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)

    path_parts: list[str] = []
    for bin_dir in (root / ".venv" / "bin", root / "venv" / "bin"):
        if bin_dir.is_dir():
            path_parts.append(str(bin_dir))
    if path_parts:
        env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])

    if _has_python_project(manifest) and (root / "src").is_dir() and "PYTHONPATH" not in overrides:
        current = env.get("PYTHONPATH")
        src_path = str(root / "src")
        env["PYTHONPATH"] = src_path if not current else os.pathsep.join([src_path, current])

    return env


def _has_python_project(manifest: dict[str, Any]) -> bool:
    for project in manifest.get("projects") or []:
        if isinstance(project, dict) and "python" in (project.get("types") or []):
            return True
    return False


def _normalize_python_tool_args(args: list[str], manifest: dict[str, Any]) -> list[str]:
    if not args or not _has_python_project(manifest):
        return args
    if args[0] == "pytest":
        return [sys.executable, "-m", "pytest", *args[1:]]
    if args[0] == "ruff":
        return [sys.executable, "-m", "ruff", *args[1:]]
    if args[:2] == ["pip", "install"]:
        return [sys.executable, "-m", "pip", *args[1:]]
    return args


def _fallback_risk(name: str, command: str) -> str:
    if re.search(r"(^|[^\w])(rm|sudo|dd|mkfs|shutdown|reboot)([^\w]|$)", command):
        return "critical"
    if name == "install":
        return "high"
    if name in {"test", "lint", "check"}:
        return "low"
    return "medium"
