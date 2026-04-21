from __future__ import annotations

import json
from pathlib import Path

from preflight.manifest import build_manifest
from preflight.schema import manifest_schema


def test_schema_file_matches_runtime_schema() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "manifest.schema.json"
    file_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert file_schema == manifest_schema()


def test_packaged_schema_file_matches_runtime_schema() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "src" / "preflight" / "manifest.schema.json"
    file_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert file_schema == manifest_schema()


def test_manifest_contains_schema_required_fields(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    manifest = build_manifest(tmp_path, use_cache=False)
    schema = manifest_schema()
    for field in schema["required"]:
        assert field in manifest
