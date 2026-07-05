"""
executor/vocabulary/sketch_on_face.py - the `sketch_on_face` command (Phase 6).

Command definition: shared/commands.schema.json -> catalog.sketch_on_face
  params: target (req, the object that owns the face); where ('top'/'bottom',
          default 'top') OR face (explicit id like 'Face6'); shape
          ('rectangle'/'circle'); width/height or radius; offset (opt). Units: mm.

Creates a real Sketcher::SketchObject ATTACHED to a flat face of an existing body
(MapMode 'FlatFace'), so the next extrude grows a boss out of that face, or - with
extrude op='cut' - sinks a pocket into it. The geometry is the same closed
rectangle/circle that create_sketch builds (shared draw_profile helper).

Resolving the face (ADR 0006/0014, principle 7): a small model cannot reliably
name 'Face6'. So the model says where='top'/'bottom' and the EXECUTOR reads the
real geometry to find the matching planar face. An explicit 'face' id is still
honoured for power users. The sketch is named 'Sketch', so the engine chains the
following extrude onto it (ADR 0010/0013).
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object
from .create_sketch import draw_profile


def sketch_on_face(doc, params: dict) -> List:
    """Create a Sketcher sketch attached to a flat face of an existing object."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    target = resolve_object(doc, params["target"])
    shape = str(params.get("shape", "")).strip().lower()
    if shape not in ("rectangle", "circle"):
        raise ValueError("shape must be 'rectangle' or 'circle'")

    face_ref = _resolve_face(target, params)

    sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
    # Attach the sketch to the chosen face. FreeCAD >= 0.21 uses AttachmentSupport;
    # fall back to the legacy Support for safety. MapMode 'FlatFace' lays the sketch
    # flat on the face plane.
    support = [(target, (face_ref,))]
    try:
        sketch.AttachmentSupport = support
    except Exception:
        sketch.Support = support
    sketch.MapMode = "FlatFace"

    offset = params.get("offset")
    if offset:
        sketch.AttachmentOffset = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, float(offset)), FreeCAD.Rotation())

    # Recompute so the attachment sets the sketch's Placement, then draw the profile
    # CENTRED on the face (not at the face's corner origin, which is confusing and
    # can leave the feature hanging off the edge). We convert the face centre into
    # the sketch's local plane; if anything is unavailable (headless mock), we fall
    # back to the local origin.
    try:
        doc.recompute()
    except Exception:
        pass
    origin = _face_centre_local(target, face_ref, sketch)
    draw_profile(sketch, shape, params, origin=origin, centered=True)
    return [sketch]


def _face_centre_local(target, face_ref: str, sketch):
    """
    The centre of the chosen face expressed in the sketch's LOCAL plane (x, y), so
    draw_profile can centre the profile on the face. Best-effort: returns (0, 0) if
    the real geometry/placement maths is unavailable (e.g. the headless mock).
    """
    try:
        idx = int("".join(ch for ch in str(face_ref) if ch.isdigit()))
        face = target.Shape.Faces[idx - 1]
        centre_world = getattr(face, "CenterOfMass", None)
        if centre_world is None:
            bb = face.BoundBox
            import FreeCAD
            centre_world = FreeCAD.Vector((bb.XMin + bb.XMax) / 2.0,
                                          (bb.YMin + bb.YMax) / 2.0,
                                          (bb.ZMin + bb.ZMax) / 2.0)
        local = sketch.Placement.inverse().multVec(centre_world)
        return (local.x, local.y)
    except Exception:
        return (0.0, 0.0)


def _resolve_face(target, params: dict) -> str:
    """
    Decide which face to attach to. An explicit 'face' id wins; otherwise pick the
    'top'/'bottom' planar face by reading the real geometry (principle 7): the face
    whose normal points along +Z (top) / -Z (bottom), at the highest / lowest Z.
    """
    face = params.get("face")
    if face:
        return str(face)

    where = str(params.get("where", "top")).strip().lower()
    if where not in ("top", "bottom"):
        raise ValueError("'where' must be 'top' or 'bottom' (or pass an explicit "
                         "'face' id)")

    shape = getattr(target, "Shape", None)
    if shape is None:
        raise ValueError(
            f"target '{getattr(target, 'Name', '?')}' has no shape yet; "
            "recompute the document first")
    faces = list(getattr(shape, "Faces", []) or [])
    if not faces:
        raise ValueError(f"target '{getattr(target, 'Name', '?')}' has no faces")

    best_idx = None
    best_z = None
    for i, f in enumerate(faces, start=1):
        try:
            n = f.normalAt(0, 0)
        except Exception:
            continue
        bb = getattr(f, "BoundBox", None)
        if where == "top" and n.z > 0.9:
            z = bb.ZMax if bb is not None else 0.0
            if best_z is None or z > best_z:
                best_z, best_idx = z, i
        elif where == "bottom" and n.z < -0.9:
            z = bb.ZMin if bb is not None else 0.0
            if best_z is None or z < best_z:
                best_z, best_idx = z, i

    if best_idx is None:
        raise ValueError(
            f"could not find a flat '{where}' face on "
            f"'{getattr(target, 'Name', '?')}'; pass an explicit 'face' id")
    return f"Face{best_idx}"
