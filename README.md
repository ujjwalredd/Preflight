<p align="center">
  <img src="image/preflight.png" alt="Preflight logo" width="500">
</p>

# Preflight

Preflight scans a software project and produces a **single canonical manifest**
for AI coding assistants. It turns scattered repo signals into one structured
document: inferred commands with confidence, risk, and evidence; extracted AI
instruction files; entrypoints; project graphs; framework analysis; CI hints;
container metadata; and **consistency warnings** when those signals disagree.

## Why this exists

Assistants burn tokens reconciling `README.md`, `package.json`, `Makefile`,
`pyproject.toml`, CI YAML, workspace layouts, ad-hoc team docs, and service
wiring. Preflight merges those signals into one JSON or Markdown document and
can also emit a short **agent bootstrap brief** plus a **JSON schema contract**
for downstream tools.

## What you get

- `commands` with `command`, `confidence`, `risk`, `context`, `contexts`, and
  supporting `evidence`
- `warning_objects` with structured warning metadata for contradictions, drift,
  and coverage gaps
- `projects` plus `project_graph` for monorepos and nested workspaces
- `rules` with extracted `AGENTS.md`, `CLAUDE.md`, Copilot instructions, and
  other agent-facing guidance
- `entrypoints` for apps, CLIs, services, and inferred startup paths
- `agent_bootstrap` for a small LLM-oriented orientation brief
- `schema.json` and `manifest.schema.json` for downstream validation

## Latest benchmark

Latest public warning-corpus benchmark run: `2026-04-21T12:06:19Z`

| Repo | Projects | Rules | Warnings | Tokens raw -> bootstrap | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fastapi/fastapi` | `1` | `1` | `0` | `17417 -> 103` | `99.4%` |
| `django/django` | `1` | `1` | `0` | `1550 -> 95` | `93.9%` |
| `vercel/next.js` | `680` | `3` | `12` | `40912 -> 770` | `98.1%` |
| `astral-sh/ruff` | `101` | `7` | `13` | `54179 -> 624` | `98.8%` |
| `jakedoublev/pnpm-lock-to-npm-lock` | `1` | `0` | `0` | `1204 -> 116` | `90.4%` |

This table reflects only the most recent 5-repo benchmark run, not the earlier exploratory scans.

## Quick start

```bash
cd preflight
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

Requirements:

- Python `>=3.11`
- `PyYAML` is installed automatically from the package dependencies

Try it on the repo you are standing in:

```bash
preflight scan .
preflight bootstrap .
preflight verify .
```

## CLI reference

| Command | What it does | Common flags |
| --- | --- | --- |
| `preflight scan [path]` | Print the manifest as JSON | `--md`, `--no-cache` |
| `preflight bootstrap [path]` | Print the short agent bootstrap brief | `--text`, `--no-cache` |
| `preflight schema` | Print the manifest JSON schema | none |
| `preflight serve [path]` | Serve manifest/bootstrap/schema over HTTP | `--host`, `--port`, `--no-cache` |
| `preflight verify [path]` | Validate inferred commands as dry-run JSON | `--command`, `--timeout`, `--no-cache` |
| `preflight verify [path] --run` | Execute inferred validation commands | `--allow-risky`, `--command`, `--timeout`, `--no-cache` |

## Usage examples

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

- `commands`: inferred commands with `command`, `confidence`, `risk`, `source`,
  `context`, `contexts`, and `evidence`
- `warning_objects`: structured warnings with `id`, `severity`, `category`,
  `message`, `evidence`, `affected_paths`, `suggested_action`, and `confidence`
- `warnings`: compatibility projection of warning messages as plain strings
- `projects`: discovered root and nested workspaces/projects with framework analysis
- `project_graph`: internal dependency and workspace edges
- `rules`: extracted AI instruction files with kind, excerpt, and truncation info
- `entrypoints`: likely CLI, app, server, compose, and container entrypoints
- `agent_bootstrap`: a short AI-ready repo brief in Markdown and plain text
- `cache`: temp-dir cache metadata for the scan result

`warning_objects` is the preferred field for downstream tooling. `warnings`
exists so older integrations do not break.

## Current analyzers

Preflight currently does all of the following:

- Parses `pyproject.toml`, `Cargo.toml`, GitHub Actions YAML, and Compose YAML with real parsers
- Detects monorepo projects and builds an internal project graph
- Extracts FastAPI routes, Django settings/app hints, Next.js routes, and Terraform providers/modules
- Extracts AI rule files such as `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*`, and Copilot instructions
- Generates safer `verify` plans with risk labels and blocks shell-style or risky commands unless explicitly allowed

## Contributing

Contributions are welcome. The fastest path is:

1. Read [CONTRIBUTING.md](CONTRIBUTING.md).
2. Install dev dependencies with `pip install -e ".[dev]"`.
3. Run `ruff check .` and `PYTHONPATH=src python3 -m pytest -q`.
4. If you touch command inference, warnings, or schema output, also run
   `PYTHONPATH=src python3 -m preflight verify . --run --command lint --no-cache`
   and
   `PYTHONPATH=src python3 -m preflight verify . --run --command test --no-cache`.

Good first contribution areas:

- new framework analyzers
- better warning precision on large monorepos
- additional benchmark corpus repos
- schema consumers and editor integrations

## Benchmarking

The warning benchmark corpus is scripted in
[scripts/benchmark_warning_corpus.py](scripts/benchmark_warning_corpus.py).
After cloning target repos locally, run:

```bash
PYTHONPATH=src python3 scripts/benchmark_warning_corpus.py \
  --repo fastapi/fastapi=/abs/path/to/fastapi \
  --repo django/django=/abs/path/to/django \
  --repo vercel/next.js=/abs/path/to/nextjs \
  --output-dir /tmp/preflight-benchmark
```

This writes `summary.json`, `summary.md`, and one manifest JSON per repo.

## Schema contract

The repository schema file lives at `manifest.schema.json`. Installed packages also bundle
`preflight/manifest.schema.json`, and the schema is available via:

- `preflight schema`
- `GET /schema.json`

## Limitations

- Preflight is a heuristic repo scanner, not a full build system or language
  server.
- The strongest results come from scanning a repo root, not an arbitrary nested
  directory.
- `verify --run` is intentionally conservative and blocks risky commands unless
  `--allow-risky` is passed.
- Very large monorepos may need a scoped follow-up scan even when the root
  manifest is accurate.

## License

MIT
