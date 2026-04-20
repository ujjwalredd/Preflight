from __future__ import annotations

from typing import Any


def manifest_schema() -> dict[str, Any]:
    command_schema = {
        "type": "object",
        "required": ["command", "confidence", "source", "evidence", "risk"],
        "properties": {
            "command": {"type": "string"},
            "confidence": {"type": "string"},
            "source": {"type": "string"},
            "risk": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["command", "source", "kind", "detail"],
                    "properties": {
                        "command": {"type": "string"},
                        "source": {"type": "string"},
                        "kind": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Preflight Manifest",
        "type": "object",
        "required": [
            "preflight_version",
            "generated_at",
            "root",
            "commands",
            "canonical_commands",
            "sources",
            "rules",
            "agent_rule_files",
            "projects",
            "project_graph",
            "entrypoints",
            "evidence",
            "agent_bootstrap",
            "cache",
            "human_notes",
            "warnings",
        ],
        "properties": {
            "preflight_version": {"type": "integer", "const": 3},
            "generated_at": {"type": "string"},
            "root": {"type": "string"},
            "display_name": {"type": ["string", "null"]},
            "schema_ref": {"type": "string"},
            "commands": {
                "type": "object",
                "additionalProperties": command_schema,
            },
            "canonical_commands": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "sources": {"type": "object"},
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "kind", "excerpt", "truncated"],
                    "properties": {
                        "path": {"type": "string"},
                        "kind": {"type": "string"},
                        "excerpt": {"type": "string"},
                        "truncated": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
            },
            "agent_rule_files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "projects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "name", "types", "markers"],
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                        "types": {"type": "array", "items": {"type": "string"}},
                        "markers": {"type": "array", "items": {"type": "string"}},
                        "framework_hints": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "entrypoints": {"type": "array", "items": {"type": "object"}},
                        "internal_dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "workspace_children": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "analysis": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
            },
            "project_graph": {
                "type": "object",
                "required": ["edges", "adjacency", "roots"],
                "properties": {
                    "edges": {"type": "array", "items": {"type": "object"}},
                    "adjacency": {"type": "object"},
                    "roots": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            "entrypoints": {"type": "array", "items": {"type": "object"}},
            "evidence": {"type": "object"},
            "agent_bootstrap": {
                "type": "object",
                "required": ["markdown", "text"],
                "properties": {
                    "markdown": {"type": "string"},
                    "text": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "cache": {
                "type": "object",
                "required": ["status", "path", "signature", "version"],
                "properties": {
                    "status": {"type": "string"},
                    "path": {"type": "string"},
                    "signature": {"type": "string"},
                    "version": {"type": "integer"},
                },
                "additionalProperties": True,
            },
            "human_notes": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    }
