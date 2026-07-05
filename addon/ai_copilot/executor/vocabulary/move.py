"""
executor/vocabulary/move.py - implementation of the `move` command (Phase 6).

Command definition: shared/commands.schema.json -> catalog.move
  params: target (req); by [dx,dy,dz] (relative, recommended) OR to [x,y,z]
          (absolute). Units: mm.

Translates an EXISTING object by composing its Placement (parametric-friendly and
reversible: the whole thing runs in an undoable transaction, so Ctrl+Z restores
the previous position). No new object is created. The object's existing rotation
is preserved; only the translation part (Placement.Base) changes.

`by` vs `to`: exactly one is required. The schema marks both optional because the
stdlib validator cannot express "one of"; the check lives here with a clear,
user-facing message (same pattern as create_sketch's per-shape requirements).
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object


def _vec3(values, what: str):
    """Read a 3-number list into an (x, y, z) float tuple, or raise."""
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        raise ValueError(f"'{what}' must be a list of three numbers [x,y,z]")
    return float(values[0]), float(values[1]), float(values[2])


def move(doc, params: dict) -> List:
    """Translate an existing object in document `doc`."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    obj = resolve_object(doc, params.get("target"))
    placement = obj.Placement
    base = placement.Base

    by = params.get("by")
    to = params.get("to")
    if by is not None:
        dx, dy, dz = _vec3(by, "by")
        new_base = FreeCAD.Vector(base.x + dx, base.y + dy, base.z + dz)
    elif to is not None:
        x, y, z = _vec3(to, "to")
        new_base = FreeCAD.Vector(x, y, z)
    else:
        raise ValueError("move needs 'by' [dx,dy,dz] (relative) or 'to' [x,y,z] "
                         "(absolute)")

    # Keep the existing rotation; only change the translation part.
    obj.Placement = FreeCAD.Placement(new_base, placement.Rotation)
    return [obj]
