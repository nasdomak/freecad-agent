"""
executor/vocabulary/rotate.py - implementation of the `rotate` command (Phase 6).

Command definition: shared/commands.schema.json -> catalog.rotate
  params: target (req); angle (req, degrees); axis ('X'/'Y'/'Z', default 'Z');
          center [x,y,z] (opt, default: the object's bounding-box centre).

Rotates an EXISTING object by composing its Placement around a pivot point. Like
move, it creates no new object and is fully reversible (undoable transaction ->
Ctrl+Z). The axis is given as a friendly string and resolved to a vector in the
executor (ADR 0011); the default pivot is the object's perceived bbox centre, so
the object spins in place rather than around the global origin.
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object, resolve_axis, bbox_center


def rotate(doc, params: dict) -> List:
    """Rotate an existing object in document `doc`."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    obj = resolve_object(doc, params.get("target"))

    angle = params.get("angle")
    if angle is None:
        raise ValueError("rotate needs an 'angle' in degrees")
    angle = float(angle)

    axis_vec = resolve_axis(params.get("axis"), default="Z")

    center = params.get("center")
    if center is not None:
        if not isinstance(center, (list, tuple)) or len(center) < 3:
            raise ValueError("'center' must be a list of three numbers [x,y,z]")
        center_vec = FreeCAD.Vector(float(center[0]), float(center[1]),
                                    float(center[2]))
    else:
        center_vec = bbox_center(obj)

    # Rotation about `center_vec`: a Placement with zero base, the rotation, and
    # the pivot as its centre. Left-multiply so the rotation is applied in the
    # global frame on top of the object's current placement.
    rotation = FreeCAD.Rotation(axis_vec, angle)
    delta = FreeCAD.Placement(FreeCAD.Vector(0.0, 0.0, 0.0), rotation, center_vec)
    obj.Placement = delta.multiply(obj.Placement)
    return [obj]
