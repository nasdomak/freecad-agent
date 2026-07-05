"""
executor/vocabulary/create_cylinder.py - implementation of the `create_cylinder` command.

Command definition: shared/commands.schema.json -> catalog.create_cylinder
  params: radius (req), height (req), placement [x,y,z] (opt). Units: mm.

Second vocabulary command: it DEMONSTRATES the extension pattern
"schema (data) + function (here) + registry (executor/__init__.py)". Creates a
Part::Cylinder, a primitive always available in the FreeCAD core.
"""

from __future__ import annotations

from typing import List


def create_cylinder(doc, params: dict) -> List:
    """Create a cylinder in document `doc`."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    radius = float(params["radius"])
    height = float(params["height"])
    if radius <= 0 or height <= 0:
        raise ValueError("radius and height must be > 0")

    cyl = doc.addObject("Part::Cylinder", "Cylinder")
    cyl.Radius = radius
    cyl.Height = height

    placement = params.get("placement")
    if placement and len(placement) >= 3:
        x, y, z = (float(placement[0]), float(placement[1]), float(placement[2]))
        cyl.Placement = FreeCAD.Placement(FreeCAD.Vector(x, y, z), FreeCAD.Rotation())

    return [cyl]
