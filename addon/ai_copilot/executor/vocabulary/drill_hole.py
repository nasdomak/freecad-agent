"""
executor/vocabulary/drill_hole.py - implementation of the `drill_hole` command.

Command definition: shared/commands.schema.json -> catalog.drill_hole
  params: target (id of the body), diameter, depth, position [x,y,z] (optional).
  Units: mm.

Strategy: create a cylindrical TOOL (Part::Cylinder, radius = diameter/2,
height = depth) and subtract it from the target with a Part::Cut. The whole thing
stays parametric and reversible (principle 6).

Where does it drill? (revised in Phase 3 - principle 7: perceive, don't guess)
  - If `position` is OMITTED, the command READS the target's bounding box and
    drills from the TOP face downwards, centred on the body. This makes the very
    common "create a box and drill a hole in the centre" work without the model
    having to compute coordinates it cannot see.
  - If `position` is [x, y] (two numbers), it drills from the top at that point.
  - If `position` is [x, y, z] (three numbers), it drills downwards starting at
    that exact point (back-compatible with the Phase 2 behaviour / explicit calls).
The drilling axis is -Z (downwards). A future revision can take a face/direction
reference once the model routinely points at real faces via perception.detail.
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object, bounding_box


def drill_hole(doc, params: dict) -> List:
    """Drill a cylindrical hole into an existing body."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    target = resolve_object(doc, params["target"])
    diameter = float(params["diameter"])
    depth = float(params["depth"])
    if diameter <= 0 or depth <= 0:
        raise ValueError("diameter and depth must be > 0")

    pos = params.get("position")
    bb = bounding_box(target)

    if pos is not None and len(pos) >= 3:
        # Explicit point: drill downwards from (x, y, z).
        x, y, z_top = float(pos[0]), float(pos[1]), float(pos[2])
    else:
        # Auto-locate on the body: we need the bounding box for this.
        if bb is None:
            raise ValueError(
                f"cannot locate '{target.Name}' to drill it (it has no computed "
                "shape yet); pass an explicit position [x, y, z]")
        if pos is not None and len(pos) >= 2:
            x, y = float(pos[0]), float(pos[1])
        else:
            # Centre of the top face.
            x = (bb.XMin + bb.XMax) / 2.0
            y = (bb.YMin + bb.YMax) / 2.0
        z_top = bb.ZMax

    # Tool cylinder occupying [z_top - depth, z_top] along Z, centred at (x, y),
    # so it removes material downwards from the top face.
    tool = doc.addObject("Part::Cylinder", "DrillTool")
    tool.Radius = diameter / 2.0
    tool.Height = depth
    tool.Placement = FreeCAD.Placement(
        FreeCAD.Vector(x, y, z_top - depth), FreeCAD.Rotation())

    cut = doc.addObject("Part::Cut", "Drilled")
    cut.Base = target
    cut.Tool = tool
    return [cut]
