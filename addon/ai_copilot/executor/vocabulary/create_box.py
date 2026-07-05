"""
executor/vocabulary/create_box.py - implementation of the `create_box` command.

Command definition: shared/commands.schema.json -> catalog.create_box
  params: length (req), width (req), height (req), placement [x,y,z] (opt).
  Units: mm.

Creates a Part::Box (a primitive of the Part workbench, always available in the
FreeCAD core). Returns the list of created objects (here just one).
"""

from __future__ import annotations

from typing import List


def create_box(doc, params: dict) -> List:
    """Create a box in document `doc`."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    length = float(params["length"])
    width = float(params["width"])
    height = float(params["height"])
    if length <= 0 or width <= 0 or height <= 0:
        raise ValueError("length, width and height must be > 0")

    box = doc.addObject("Part::Box", "Box")
    box.Length = length
    box.Width = width
    box.Height = height

    placement = params.get("placement")
    if placement and len(placement) >= 3:
        x, y, z = (float(placement[0]), float(placement[1]), float(placement[2]))
        box.Placement = FreeCAD.Placement(FreeCAD.Vector(x, y, z), FreeCAD.Rotation())

    return [box]
