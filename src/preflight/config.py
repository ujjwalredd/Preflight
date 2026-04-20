from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PreflightOverrides:
    display_name: str | None = None
    canonical: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> PreflightOverrides:
        path = root / ".preflight.json"
        if not path.is_file():
            return cls()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return cls(warnings=[f".preflight.json could not be read: {exc}"])
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return cls(warnings=[f".preflight.json is invalid JSON: {exc.msg}"])
        if not isinstance(data, dict):
            return cls(warnings=[".preflight.json must contain a JSON object"])
        return cls._from_mapping(data)

    @classmethod
    def _from_mapping(cls, data: dict[str, Any]) -> PreflightOverrides:
        display = data.get("display_name")
        canonical = data.get("canonical") or {}
        notes = data.get("notes") or []
        if not isinstance(canonical, dict):
            canonical = {}
        if not isinstance(notes, list):
            notes = []
        canon_str = {str(k): str(v) for k, v in canonical.items()}
        note_strs = [str(n) for n in notes]
        return cls(
            display_name=str(display) if display is not None else None,
            canonical=canon_str,
            notes=note_strs,
        )
