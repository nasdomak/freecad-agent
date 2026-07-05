"""
executor/ - runs the vocabulary commands INSIDE FreeCAD.

Entry point: execute(invocation) -> commandResult (dict), conforming to
shared/commands.schema.json ($defs.commandInvocation / $defs.commandResult).

Flow:
  1. resolve `cmd` in the REGISTRY of implemented commands;
  2. open an undoable transaction (transaction.undoable);
  3. run the vocabulary function;
  4. recompute the document and evaluate the outcome;
  5. commit (or abort+error on exception) and return the commandResult.

PRECONDITIONS: runs on the Qt main thread (guaranteed by qt_invoker). FreeCAD is
imported lazily.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from .transaction import undoable, rollback_last
from .python_exec import run_python  # noqa: F401  (re-exported: executor.run_python)
from .vocabulary import (
    create_box, create_cylinder, create_sketch, sketch_on_face, drill_hole,
    extrude, chamfer, fillet, boolean, move, rotate, mirror, array,
)

# Registry: command name (as in commands.schema.json) -> vocabulary function.
# It grows phase by phase together with the schema. Adding a command = one entry
# in the schema + one function in vocabulary/ + one line HERE.
REGISTRY: Dict[str, Callable[[object, dict], List]] = {
    "create_box": create_box,
    "create_cylinder": create_cylinder,
    "create_sketch": create_sketch,
    "sketch_on_face": sketch_on_face,
    "drill_hole": drill_hole,
    "extrude": extrude,
    "chamfer": chamfer,
    "fillet": fillet,
    "boolean": boolean,
    "move": move,
    "rotate": rotate,
    "mirror": mirror,
    "array": array,
}


def _ensure_document():
    """Return the active document, creating one if none exists."""
    import FreeCAD
    doc = FreeCAD.ActiveDocument
    if doc is None:
        doc = FreeCAD.newDocument("FreeCAD_Agent")
    return doc


def _recompute_ok(doc, objects: List) -> bool:
    """Recompute and evaluate the outcome (input for the future self-correction loop)."""
    doc.recompute()
    # An object "in error" after the recompute signals invalid geometry.
    for obj in objects:
        # mustExecute() False + State without 'Error' = ok; defensive check.
        state = getattr(obj, "State", []) or []
        if "Invalid" in state or "Error" in state:
            return False
    return True


def execute(invocation: dict) -> dict:
    """
    Run a commandInvocation and return a commandResult.
    invocation = {"cmd": "...", "params": {...}}
    """
    cmd = invocation.get("cmd")
    params = invocation.get("params", {}) or {}

    fn = REGISTRY.get(cmd)
    if fn is None:
        return {
            "ok": False,
            "transaction_id": "",
            "error": f"unknown command: {cmd!r} (not in the REGISTRY)",
        }

    try:
        doc = _ensure_document()
    except Exception as exc:  # FreeCAD unavailable / document not creatable
        return {"ok": False, "transaction_id": "", "error": f"document unavailable: {exc}"}

    try:
        with undoable(doc, cmd) as (tx_id, _tx_label):
            created = fn(doc, params) or []
            recompute_ok = _recompute_ok(doc, created)
            if not recompute_ok:
                # Invalid geometry: fail the transaction -> rollback.
                raise ValueError("recompute failed: invalid geometry")
        return {
            "ok": True,
            "transaction_id": tx_id,
            "created_ids": [obj.Name for obj in created],
            "recompute_ok": recompute_ok,
        }
    except Exception as exc:
        # undoable already called abortTransaction(): no trace left in the document.
        return {
            "ok": False,
            "transaction_id": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def rollback(transaction_id: str = "") -> dict:
    """Handler for the protocol's transaction.rollback (safety net)."""
    try:
        doc = _ensure_document()
        ok = rollback_last(doc)
        doc.recompute()
        return {"ok": ok}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
