"""
executor/python_exec.py - the "free Python" channel (principle 5).

When the structured vocabulary is not enough, the model may propose raw FreeCAD
Python. This module runs that code, but always:
  - inside an UNDOABLE transaction, so Ctrl+Z reverts it (principle 6 - safety =
    reversibility), and
  - AFTER the panel has shown the code and a transparency banner (principle 5).
    The transparency is handled in the add-on/panel; here we just execute.

The code runs with a small, explicit namespace:
    FreeCAD / App   -> the FreeCAD module
    FreeCADGui / Gui-> the GUI module (if available)
    doc             -> the active document
This keeps the proposed snippets short and predictable.

Self-correction (principle 8): on failure we return a commandResult with ok=false
and the error text, so the engine can feed it back to the model and retry once.
We do NOT try to sandbox Python (FreeCAD's API is too broad for that); the safety
net is the undoable transaction plus full transparency to the user.
"""

from __future__ import annotations

from typing import List

from .transaction import undoable


def _recompute_ok(doc, before_names: set) -> tuple:
    """Recompute and return (ok, created_names). created = objects new since `before`."""
    doc.recompute()
    created = [o for o in doc.Objects if o.Name not in before_names]
    for obj in created:
        state = getattr(obj, "State", []) or []
        if "Invalid" in state or "Error" in state:
            return False, [o.Name for o in created]
    return True, [o.Name for o in created]


def run_python(code: str, reason: str = "") -> dict:
    """
    Execute free FreeCAD Python inside an undoable transaction.
    Returns a commandResult (shared/commands.schema.json#/$defs/commandResult).
    """
    import FreeCAD  # lazy import: available only inside FreeCAD.

    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "transaction_id": "", "error": "no Python code provided"}

    doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("FreeCAD_Agent")
    before = {o.Name for o in doc.Objects}

    env = {"FreeCAD": FreeCAD, "App": FreeCAD, "doc": doc, "__name__": "__agent_python__"}
    try:
        import FreeCADGui  # optional: not present in headless mode
        env["FreeCADGui"] = FreeCADGui
        env["Gui"] = FreeCADGui
    except Exception:
        pass

    try:
        with undoable(doc, "python.execute") as (tx_id, _label):
            exec(compile(code, "<agent-python>", "exec"), env)  # noqa: S102 - by design (principle 5)
            recompute_ok, created = _recompute_ok(doc, before)
            if not recompute_ok:
                raise ValueError("recompute failed: invalid geometry after the script")
        return {
            "ok": True,
            "transaction_id": tx_id,
            "created_ids": created,
            "recompute_ok": recompute_ok,
        }
    except Exception as exc:
        # The transaction was aborted: nothing is left in the document.
        return {"ok": False, "transaction_id": "", "error": f"{type(exc).__name__}: {exc}"}
