"""
engine/fake_brain.py - the Phase 1 "fake brain" (no AI).

Its single job in this phase: given an ALREADY-structured command invocation
(arriving from the panel via `command.request`), VALIDATE it against the
vocabulary `shared/commands.schema.json`. If valid, the engine forwards it to the
add-on as `command.execute`; if not, it refuses gracefully (principle 7: don't
trust the input, perceive and verify).

This module is the CLEAN INSERTION POINT for the real agent: in Phase 2+ here
(or alongside) will live the natural-language -> command translation and command
selection; validation stays useful downstream of the model anyway.

Validator: deliberately MINIMAL and pure stdlib, so the engine runs on Marco's
plain Python without installing anything. It is not a full JSON Schema validator:
it covers what our catalog actually uses (required, basic types, minimum, enum,
typed arrays). When the engine has its own venv (Phase 2/3) we can switch to the
`jsonschema` library without changing the interface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# The command catalog is shared neutral DATA (principle 5).
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "shared" / "commands.schema.json"


class Catalog:
    """Loads and queries the structured vocabulary (commands.schema.json)."""

    def __init__(self, schema_path: Path = _SCHEMA_PATH) -> None:
        self.path = schema_path
        data = json.loads(schema_path.read_text(encoding="utf-8"))
        self.version: str = data.get("version", "?")
        self.catalog: Dict[str, dict] = data.get("catalog", {})
        # Drop service keys (e.g. "_comment") that aren't commands.
        self.commands: Dict[str, dict] = {
            name: spec for name, spec in self.catalog.items()
            if not name.startswith("_") and isinstance(spec, dict) and "params" in spec
        }

    def names(self) -> List[str]:
        return sorted(self.commands.keys())

    def spec(self, cmd: str) -> Optional[dict]:
        return self.commands.get(cmd)


# Map JSON Schema types -> accepted Python types (bools are NOT numbers).
def _type_ok(value: Any, json_type: str) -> bool:
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return True  # unhandled type: don't block.


def _validate_param(name: str, value: Any, pspec: dict) -> List[str]:
    """Validate a single parameter against its mini-schema. Returns errors."""
    errors: List[str] = []
    jtype = pspec.get("type")
    if jtype and not _type_ok(value, jtype):
        errors.append(f"parameter '{name}': expected {jtype}, got {type(value).__name__}")
        return errors  # wrong type: no point checking the rest

    if jtype in ("number", "integer") and "minimum" in pspec:
        if value < pspec["minimum"]:
            errors.append(f"parameter '{name}': must be >= {pspec['minimum']} (got {value})")

    if "enum" in pspec and value not in pspec["enum"]:
        errors.append(f"parameter '{name}': value '{value}' not allowed (allowed: {pspec['enum']})")

    if jtype == "array":
        items = pspec.get("items")
        if isinstance(items, dict) and "type" in items:
            for i, el in enumerate(value):
                if not _type_ok(el, items["type"]):
                    errors.append(f"parameter '{name}'[{i}]: expected {items['type']}")
    return errors


def validate_invocation(invocation: Any, catalog: Optional[Catalog] = None) -> List[str]:
    """
    Validate a commandInvocation {cmd, params} against the catalog.
    Returns the (possibly empty) list of error messages.
    Empty list = valid invocation.
    """
    cat = catalog or Catalog()
    errors: List[str] = []

    if not isinstance(invocation, dict):
        return ["the invocation is not an object {cmd, params}"]

    cmd = invocation.get("cmd")
    params = invocation.get("params", {})

    if not cmd or not isinstance(cmd, str):
        return ["field 'cmd' missing or invalid"]

    spec = cat.spec(cmd)
    if spec is None:
        return [f"unknown command: '{cmd}'. Known commands: {', '.join(cat.names())}"]

    if not isinstance(params, dict):
        return [f"'params' must be an object for command '{cmd}'"]

    pschema = spec.get("params", {})
    required = pschema.get("required", [])
    properties = pschema.get("properties", {})

    # 1) required parameters present?
    for req in required:
        if req not in params:
            errors.append(f"missing required parameter '{req}'")

    # 2) is every provided parameter valid?
    for name, value in params.items():
        pspec = properties.get(name)
        if pspec is None:
            # Unexpected extra parameter: a warning, not a blocking error.
            errors.append(f"unexpected parameter for '{cmd}': '{name}' (ignored)")
            continue
        errors.extend(_validate_param(name, value, pspec))

    return errors


def is_blocking(errors: List[str]) -> bool:
    """
    True if at least one error is BLOCKING. Warnings about extra parameters
    ('ignored') do not block execution.
    """
    return any("ignored" not in e for e in errors)


def summarize(catalog: Optional[Catalog] = None) -> Tuple[str, List[str]]:
    """Return (vocabulary_version, command_list). Handy for logs/handshake."""
    cat = catalog or Catalog()
    return cat.version, cat.names()
