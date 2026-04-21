from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import tiktoken

from preflight.manifest import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Preflight on a public warning corpus.")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Benchmark target in the form label=/abs/path/to/repo. May be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results"),
        help="Directory for JSON and Markdown benchmark artifacts.",
    )
    args = parser.parse_args()

    if not args.repo:
        parser.error("at least one --repo label=/path entry is required")

    repos = [_parse_repo_arg(raw) for raw in args.repo]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    encoding = tiktoken.get_encoding("o200k_base")
    summary: list[dict[str, object]] = []
    for label, repo_path in repos:
        manifest = build_manifest(repo_path, use_cache=False)
        orientation_files = _pick_orientation_files(repo_path)
        raw_bundle = _orientation_bundle(repo_path, orientation_files)
        raw_tokens = len(encoding.encode(raw_bundle)) if raw_bundle else 0
        bootstrap_text = (manifest.get("agent_bootstrap") or {}).get("text", "")
        bootstrap_tokens = len(encoding.encode(bootstrap_text)) if bootstrap_text else 0
        item = {
            "repo": label,
            "path": str(repo_path),
            "projects": len(manifest.get("projects") or []),
            "rules": len(manifest.get("rules") or []),
            "warnings": len(manifest.get("warnings") or []),
            "warning_ids": [
                warning.get("id")
                for warning in manifest.get("warning_objects") or []
                if isinstance(warning, dict)
            ],
            "commands": sorted((manifest.get("commands") or {}).keys()),
            "orientation_bundle_tokens": raw_tokens,
            "bootstrap_tokens": bootstrap_tokens,
            "token_reduction_percent": round(
                ((raw_tokens - bootstrap_tokens) / raw_tokens * 100), 1
            )
            if raw_tokens
            else 0.0,
        }
        summary.append(item)
        (output_dir / f"{_safe_name(label)}.manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "repos": summary,
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "summary.md").write_text(_summary_markdown(payload), encoding="utf-8")
    print(output_dir)
    return 0


def _parse_repo_arg(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise SystemExit(f"invalid --repo value: {raw!r}")
    label, path_str = raw.split("=", 1)
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"repo path is not a directory: {path}")
    return label, path


def _pick_orientation_files(root: Path) -> list[Path]:
    selected: list[Path] = []
    seen: set[Path] = set()
    candidates = [
        "README.md",
        "readme.md",
        "AGENTS.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        "contributing.md",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "pnpm-workspace.yaml",
        "turbo.json",
        "tsconfig.json",
    ]
    for name in candidates:
        path = root / name
        if path.is_file() and path not in seen:
            selected.append(path)
            seen.add(path)
    workflow_dir = root / ".github" / "workflows"
    if workflow_dir.is_dir():
        workflow_files = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
        for path in workflow_files[:2]:
            if path not in seen:
                selected.append(path)
                seen.add(path)
    return selected


def _orientation_bundle(root: Path, files: list[Path]) -> str:
    parts: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        parts.append(f"FILE: {path.relative_to(root)}\n{text}")
    return "\n\n".join(parts)


def _summary_markdown(payload: dict[str, object]) -> str:
    rows = [
        "| Repo | Projects | Rules | Warnings | Tokens raw -> bootstrap | Reduction |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in payload["repos"]:
        if not isinstance(item, dict):
            continue
        rows.append(
            (
                "| `{repo}` | `{projects}` | `{rules}` | `{warnings}` | "
                "`{raw} -> {bootstrap}` | `{reduction}%` |"
            ).format(
                repo=item["repo"],
                projects=item["projects"],
                rules=item["rules"],
                warnings=item["warnings"],
                raw=item["orientation_bundle_tokens"],
                bootstrap=item["bootstrap_tokens"],
                reduction=item["token_reduction_percent"],
            )
        )
    return "\n".join(
        [
            "# Warning Corpus Benchmark",
            "",
            f"Generated at: `{payload['generated_at']}`",
            "",
            *rows,
            "",
        ]
    )


def _safe_name(label: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in label).strip("-").lower()


if __name__ == "__main__":
    raise SystemExit(main())
