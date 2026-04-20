# Preflight

Preflight scans a software project and produces a **single canonical manifest** meant for AI coding assistants: inferred commands with confidence, risk, and evidence, extracted AI instruction files, entrypoints, project graphs, framework analysis, CI hints, container metadata, and **consistency warnings** when signals disagree.

## Why this exists

Assistants burn tokens reconciling `README.md`, `package.json`, `Makefile`, `pyproject.toml`, CI YAML, workspace layouts, ad-hoc team docs, and service wiring. Preflight merges those signals into one JSON or Markdown document and can also emit a short **agent bootstrap brief** plus a **JSON schema contract** for downstream tools.

## Install

```bash
cd preflight
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Scan the current directory and print JSON to stdout:

```bash
preflight scan
```

Scan a path:

```bash
preflight scan /path/to/repo
```

Bypass the temporary scan cache:

```bash
preflight scan --no-cache
```

Print the agent bootstrap brief:

```bash
preflight bootstrap
```

Print the manifest schema:

```bash
preflight schema
```

Start a local server (default `127.0.0.1:8765`):

```bash
preflight serve
```

Preview which inferred commands Preflight would validate:

```bash
preflight verify
```

Actually run the inferred validation commands:

```bash
preflight verify --run
```

Allow risky commands such as `install` to run:

```bash
preflight verify --run --allow-risky
```

Then open or fetch:

- `http://127.0.0.1:8765/manifest.json`
- `http://127.0.0.1:8765/manifest.md`
- `http://127.0.0.1:8765/bootstrap.md`
- `http://127.0.0.1:8765/bootstrap.txt`
- `http://127.0.0.1:8765/schema.json`

Optional project overrides live in **`.preflight.json`** at the repo root (see schema in the example below).

## `.preflight.json` (optional)

```json
{
  "display_name": "My Service",
  "canonical": {
    "install": "pnpm install",
    "test": "pnpm test",
    "lint": "pnpm lint"
  },
  "notes": ["Migrations run via scripts/db-migrate.sh"]
}
```

Values under `canonical` override inferred defaults in the manifest.

Invalid `.preflight.json` files no longer crash the scan; Preflight records a warning instead.

## Manifest highlights

The JSON manifest now includes:

- `commands`: inferred commands with `command`, `confidence`, `risk`, `source`, and `evidence`
- `projects`: discovered root and nested workspaces/projects with framework analysis
- `project_graph`: internal dependency and workspace edges
- `rules`: extracted AI instruction files with kind, excerpt, and truncation info
- `entrypoints`: likely CLI, app, server, compose, and container entrypoints
- `agent_bootstrap`: a short AI-ready repo brief in Markdown and plain text
- `cache`: temp-dir cache metadata for the scan result
- `warnings`: consistency and parsing issues

## Current analyzers

Preflight currently does all of the following:

- Parses `pyproject.toml`, `Cargo.toml`, GitHub Actions YAML, and Compose YAML with real parsers
- Detects monorepo projects and builds an internal project graph
- Extracts FastAPI routes, Django settings/app hints, Next.js routes, and Terraform providers/modules
- Extracts AI rule files such as `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*`, and Copilot instructions
- Generates safer `verify` plans with risk labels and blocks shell-style or risky commands unless explicitly allowed

## Schema contract

The shipped schema file lives at `manifest.schema.json` and is also available via:

- `preflight schema`
- `GET /schema.json`

## License

MIT
