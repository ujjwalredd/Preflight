# Contributing

Thanks for helping improve Preflight.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Preflight requires Python `>=3.11`.

## Development loop

Run these before opening a PR:

```bash
ruff check .
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m preflight verify . --run --command lint --no-cache
PYTHONPATH=src python3 -m preflight verify . --run --command test --no-cache
```

`preflight verify` exercises the same command-inference path that users rely on,
so it is worth running when you touch manifest generation, warning detectors, or
verification behavior.

## Common change areas

- `src/preflight/scanner.py`: repo scanning, analyzers, cache inputs
- `src/preflight/manifest.py`: manifest assembly and command inference
- `src/preflight/warnings.py`: structured warning detectors
- `src/preflight/schema.py`: runtime schema definition
- `tests/`: regression coverage

## If you change the schema

Update the runtime schema and regenerate both shipped schema files:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from src.preflight.schema import manifest_schema

schema = manifest_schema()
for path in [Path("manifest.schema.json"), Path("src/preflight/manifest.schema.json")]:
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
PY
```

Then rerun tests and `preflight verify`.

## If you change warnings or command inference

Please add or update tests in `tests/test_warnings.py` and, when possible,
rerun the public warning corpus benchmark:

```bash
PYTHONPATH=src python3 scripts/benchmark_warning_corpus.py \
  --repo fastapi/fastapi=/abs/path/to/fastapi \
  --repo django/django=/abs/path/to/django \
  --repo vercel/next.js=/abs/path/to/nextjs \
  --repo astral-sh/ruff=/abs/path/to/ruff \
  --repo mixed/repo=/abs/path/to/mixed \
  --output-dir /tmp/preflight-benchmark
```

This writes `summary.json`, `summary.md`, and per-repo manifest snapshots for
inspection.

## Local environment note

Use the same Python interpreter for install and execution. On some systems,
`/bin/zsh -lc 'python3 ...'` can resolve to a different Python than the one used
to install dev dependencies, which can look like missing-package failures.

## Pull requests

- Keep changes scoped and explain the user-facing effect.
- Include tests for bug fixes and new detectors.
- Mention benchmark changes when a PR intentionally affects warning volume,
  canonical command selection, or token compression.
