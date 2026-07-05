"""
executor/vocabulary/create_sketch.py - implementation of the `create_sketch` command.

Command definition: shared/commands.schema.json -> catalog.create_sketch
  params: shape ('rectangle'|'circle', required), plane ('XY'|'XZ'|'YZ', default XY),
          width/height (rectangle), radius (circle), placement [x,y,z] (optional).
  Units: mm.

Why a REAL Sketcher sketch (see ADR 0009): this unlocks `extrude`, the canonical
FreeCAD "sketch -> solid" workflow, and leaves the user an editable sketch they can
open in the Sketcher workbench. The profile is drawn in the sketch's LOCAL plane
(z = 0) and the sketch is oriented onto the chosen standard plane via its Placement.

  - rectangle: four closed Part.LineSegment edges (corner at the local origin),
    plus coincidence constraints so the wire is a clean closed loop that extrude
    can cap into a solid, and so the sketch stays properly constrained for editing.
  - circle:    one Part.Circle centred on the local origin.

Shape-specific parameters (width/height vs radius) are validated HERE, not in the
catalog schema: the minimal engine-side validator does not support conditional
'required' (JSON Schema if/then). Clear ValueErrors feed the self-correction loop
(principle 7: perceive and verify; principle 6/8: bounded self-correction).
"""

from __future__ import annotations

from typing import List

# Standard-plane orientation for the sketch. Each entry rotates the sketch's local
# XY plane onto the requested global plane, expressed as (axis, angle_degrees) for
# FreeCAD.Rotation. XY is the identity. The sketch then extrudes along its own
# normal (extrude uses DirMode "Normal"), so these orientations also set the
# extrusion direction.
_PLANE_ROTATIONS = {
    "XY": ((0.0, 0.0, 1.0), 0.0),
    "XZ": ((1.0, 0.0, 0.0), 90.0),
    "YZ": ((0.0, 1.0, 0.0), 90.0),
}


def draw_profile(sketch, shape: str, params: dict,
                 origin=(0.0, 0.0), centered: bool = False) -> None:
    """
    Draw the requested 2D profile into an EXISTING sketch, in its local plane
    (z = 0). Shared by create_sketch (sketch on a standard plane) and
    sketch_on_face (sketch attached to an object's face) so both build identical,
    cleanly closed geometry. `shape` is 'rectangle' or 'circle'; the rectangle
    needs width and height, the circle needs radius (validated here with clear
    ValueErrors, since the stdlib catalog validator cannot do conditional required).

    `origin` (ox, oy) is a reference point in the sketch's local plane. With
    `centered=False` (create_sketch) the rectangle's corner sits at `origin` and a
    circle is centred on `origin` - i.e. origin (0,0) reproduces the historical
    corner-at-origin behaviour. With `centered=True` (sketch_on_face) the profile is
    CENTRED on `origin`, so the feature lands in the middle of the face, not at a
    corner.
    """
    import FreeCAD  # lazy import: available only inside FreeCAD.
    import Part      # Part geometry (LineSegment, Circle) - FreeCAD core.
    import Sketcher  # Sketcher constraints - FreeCAD core.

    ox, oy = float(origin[0]), float(origin[1])

    if shape == "rectangle":
        width = float(params.get("width", 0) or 0)
        height = float(params.get("height", 0) or 0)
        if width <= 0 or height <= 0:
            raise ValueError("a rectangle needs width > 0 and height > 0")
        # Bottom-left corner: at `origin`, or offset so the rectangle is centred.
        x0 = ox - width / 2.0 if centered else ox
        y0 = oy - height / 2.0 if centered else oy
        p0 = FreeCAD.Vector(x0, y0, 0.0)
        p1 = FreeCAD.Vector(x0 + width, y0, 0.0)
        p2 = FreeCAD.Vector(x0 + width, y0 + height, 0.0)
        p3 = FreeCAD.Vector(x0, y0 + height, 0.0)
        sketch.addGeometry(Part.LineSegment(p0, p1), False)
        sketch.addGeometry(Part.LineSegment(p1, p2), False)
        sketch.addGeometry(Part.LineSegment(p2, p3), False)
        sketch.addGeometry(Part.LineSegment(p3, p0), False)
        # Close the loop: end of each segment coincides with the start of the next
        # (point index 1 = start, 2 = end). A clean closed wire extrudes to a solid.
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
    elif shape == "circle":
        radius = float(params.get("radius", 0) or 0)
        if radius <= 0:
            raise ValueError("a circle needs radius > 0")
        centre = FreeCAD.Vector(ox, oy, 0.0)
        normal = FreeCAD.Vector(0.0, 0.0, 1.0)  # local plane normal
        sketch.addGeometry(Part.Circle(centre, normal, radius), False)
    else:
        raise ValueError("shape must be 'rectangle' or 'circle'")


def create_sketch(doc, params: dict) -> List:
    """Create a Sketcher sketch (rectangle or circle) on a standard plane."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    shape = str(params.get("shape", "")).strip().lower()
    if shape not in ("rectangle", "circle"):
        raise ValueError("shape must be 'rectangle' or 'circle'")

    plane = str(params.get("plane", "XY")).strip().upper()
    if plane not in _PLANE_ROTATIONS:
        raise ValueError("plane must be one of: XY, XZ, YZ")

    sketch = doc.addObject("Sketcher::SketchObject", "Sketch")

    # Orient the sketch onto the chosen plane, then offset by the optional origin.
    axis, angle = _PLANE_ROTATIONS[plane]
    rotation = FreeCAD.Rotation(FreeCAD.Vector(*axis), angle)
    origin = FreeCAD.Vector(0.0, 0.0, 0.0)
    placement = params.get("placement")
    if placement and len(placement) >= 3:
        origin = FreeCAD.Vector(float(placement[0]), float(placement[1]),
                                float(placement[2]))
    sketch.Placement = FreeCAD.Placement(origin, rotation)

    draw_profile(sketch, shape, params)
    return [sketch]
