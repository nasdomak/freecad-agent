"""
executor/vocabulary/array.py - implementation of the `array` command (Phase 6).

Command definition: shared/commands.schema.json -> catalog.array
  params: target (req); pattern ('linear'|'polar', req); count (req, total items);
          linear -> spacing (req), direction ('X'/'Y'/'Z', default 'X');
          polar  -> angle (default 360), axis ('X'/'Y'/'Z', default 'Z'),
                    center [x,y,z] (opt, default the GLOBAL origin [0,0,0]:
                    the items orbit that axis, not the object's own centre),
                    radius (opt, places the ring on a circle of that radius).
  Units: mm and degrees.

Why MANUAL copies and not Draft (ADR 0012, principle 2 "FreeCAD untouched"): the
Draft workbench is a heavy optional dependency. We stay on the core Part workbench
by creating plain Part::Feature objects whose Shape is a COPY of the target's
shape, each with its own Placement. `count` is the TOTAL number of items, so the
original counts as one and we create count-1 copies (matching how users think:
"make an array of 6" leaves 6 objects in total).

Per-pattern requirements (spacing for linear) are validated HERE, not in the
catalog schema: the minimal stdlib validator cannot express conditional 'required'
(JSON Schema if/then), the same approach as create_sketch's width/height. Clear
ValueErrors feed the self-correction loop (principle 7/8).
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object, resolve_axis


def _coerce_count(value) -> int:
    """Accept an int (or an integral float like 6.0) >= 1; raise otherwise."""
    if isinstance(value, bool) or value is None:
        raise ValueError("count must be an integer >= 1")
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError("count must be an integer >= 1")
    if count != float(value):
        raise ValueError("count must be a whole number")
    if count < 1:
        raise ValueError("count must be >= 1 (it is the TOTAL number of items)")
    return count


def array(doc, params: dict) -> List:
    """Create a linear or polar pattern of copies of an existing object."""
    import math
    import FreeCAD  # lazy import: available only inside FreeCAD.

    target = resolve_object(doc, params["target"])
    pattern = str(params.get("pattern", "")).strip().lower()
    if pattern not in ("linear", "polar"):
        raise ValueError("pattern must be 'linear' or 'polar'")

    count = _coerce_count(params.get("count"))

    src_shape = getattr(target, "Shape", None)
    if src_shape is None:
        raise ValueError(
            f"target '{getattr(target, 'Name', '?')}' has no shape yet; "
            "recompute the document first")

    base_placement = target.Placement
    created: List = []

    if pattern == "linear":
        spacing = params.get("spacing")
        if spacing is None:
            raise ValueError("a linear array needs 'spacing' (distance between items)")
        spacing = float(spacing)
        direction = resolve_axis(params.get("direction"), default="X")
        b = base_placement.Base
        for i in range(1, count):
            copy = doc.addObject("Part::Feature", f"{target.Name}_copy")
            copy.Shape = src_shape.copy()
            new_base = FreeCAD.Vector(b.x + direction.x * spacing * i,
                                      b.y + direction.y * spacing * i,
                                      b.z + direction.z * spacing * i)
            copy.Placement = FreeCAD.Placement(new_base, base_placement.Rotation)
            created.append(copy)
    else:  # polar
        angle_total = params.get("angle")
        angle_total = 360.0 if angle_total is None else float(angle_total)
        axis = resolve_axis(params.get("axis"), default="Z")
        center = params.get("center")
        if center is not None:
            if not isinstance(center, (list, tuple)) or len(center) < 3:
                raise ValueError("'center' must be a list of three numbers [x,y,z]")
            center_vec = FreeCAD.Vector(float(center[0]), float(center[1]),
                                        float(center[2]))
        else:
            # Default pivot = the GLOBAL axis through the origin, NOT the object's
            # own centre. A polar pattern means the items ORBIT a central axis; if
            # we pivoted on the object's own bbox centre, the copies would just spin
            # in place and overlap (the degenerate case). The user can override the
            # centre in the request; by default it is the file's origin.
            center_vec = FreeCAD.Vector(0.0, 0.0, 0.0)

        # Optional radius: by default the items orbit at the object's CURRENT
        # distance from the centre. If the request gives a radius, reposition the
        # original (and therefore the whole ring) onto a circle of that radius
        # around the centre, in the plane perpendicular to the axis.
        radius = params.get("radius")
        if radius is not None:
            radius = float(radius)
            if radius < 0:
                raise ValueError("radius must be >= 0")
            b = base_placement.Base
            dx, dy, dz = b.x - center_vec.x, b.y - center_vec.y, b.z - center_vec.z
            dot = dx * axis.x + dy * axis.y + dz * axis.z   # axis is a unit vector
            rx, ry, rz = dx - dot * axis.x, dy - dot * axis.y, dz - dot * axis.z
            rlen = math.sqrt(rx * rx + ry * ry + rz * rz)
            if rlen < 1e-9:
                # The object sits on the axis: pick a default radial direction
                # perpendicular to the axis (X, unless the axis is X, then Y).
                if abs(axis.x) > 0.9:
                    ux, uy, uz = 0.0, 1.0, 0.0
                else:
                    ux, uy, uz = 1.0, 0.0, 0.0
            else:
                ux, uy, uz = rx / rlen, ry / rlen, rz / rlen
            new_base = FreeCAD.Vector(center_vec.x + ux * radius,
                                      center_vec.y + uy * radius,
                                      center_vec.z + uz * radius)
            base_placement = FreeCAD.Placement(new_base, base_placement.Rotation)
            target.Placement = base_placement  # move the original onto the ring

        # Even spread: step = angle/count, so a full 360 circle of `count` items is
        # evenly spaced (the original at 0, copies at step, 2*step, ...).
        step = angle_total / count
        for i in range(1, count):
            copy = doc.addObject("Part::Feature", f"{target.Name}_copy")
            copy.Shape = src_shape.copy()
            rotation = FreeCAD.Rotation(axis, step * i)
            delta = FreeCAD.Placement(FreeCAD.Vector(0.0, 0.0, 0.0),
                                      rotation, center_vec)
            copy.Placement = delta.multiply(base_placement)
            created.append(copy)

    if not created:
        raise ValueError(
            "count=1 makes no new copies (the original is the only item)")
    return created
