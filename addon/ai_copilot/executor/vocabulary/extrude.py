"""
executor/vocabulary/extrude.py - implementation of the `extrude` command.

Command definition: shared/commands.schema.json -> catalog.extrude
  params: target (id of the sketch/profile), distance, symmetric (opt bool),
          op ('add'|'cut', default 'add'). Units: mm.

'add' (default): creates a Part::Extrusion of the target profile, a solid along
the profile's normal by `distance` (or symmetrically). Parametric and reversible.

'cut' (a POCKET, ADR 0014): the profile is pushed INTO the body it sits on and the
swept volume is removed with a Part::Cut. The sketch must be attached to a face
(use sketch_on_face) so the executor can find the body to cut. The cut direction is
computed EXPLICITLY (toward the body interior) rather than guessed via Reversed -
Part::Extrusion's Normal+Reversed proved unreliable on attached sketches in real
FreeCAD. As a safety net, if the first attempt removes no material we flip the
direction once and re-check.
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object, hide_object


def extrude(doc, params: dict) -> List:
    """Extrude a sketch/profile into a solid, or cut a pocket with op='cut'."""
    target = resolve_object(doc, params["target"])
    distance = float(params["distance"])
    if distance == 0:
        raise ValueError("distance must be non-zero")
    op = str(params.get("op", "add")).strip().lower()
    if op not in ("add", "cut"):
        raise ValueError("op must be 'add' or 'cut'")

    if op == "cut":
        return _pocket(doc, target, distance)

    # op == 'add': a boss/solid growing out along the profile's own normal.
    symmetric = bool(params.get("symmetric", False))
    ext = doc.addObject("Part::Extrusion", "Extrude")
    ext.Base = target
    ext.DirMode = "Normal"          # extrude along the profile's own normal
    ext.LengthFwd = abs(distance)
    ext.Symmetric = symmetric
    ext.Solid = True                # produce a solid, not a shell
    ext.Reversed = distance < 0
    try:
        doc.recompute()
    except Exception:
        pass
    _require_solid(ext)
    # Hide the consumed profile so the sketch lines do not show through the solid
    # (Part::Extrusion does not auto-hide its base via the data API).
    hide_object(target)
    return [ext]


def _pocket(doc, target, distance: float) -> List:
    """Cut a pocket: extrude the sketch INTO the body it sits on, then Part::Cut."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    base_solid = _attachment_owner(target)
    if base_solid is None:
        raise ValueError(
            "a pocket (op='cut') needs a sketch attached to a face; create it "
            "with sketch_on_face so the body to cut from can be found")

    into = _into_body_direction(target, base_solid)

    ext = doc.addObject("Part::Extrusion", "Extrude")
    ext.Base = target
    ext.DirMode = "Custom"          # explicit direction, no Normal/Reversed guessing
    ext.Dir = into
    ext.LengthFwd = abs(distance)
    ext.Solid = True
    ext.Reversed = False
    try:
        doc.recompute()
    except Exception:
        pass
    _require_solid(ext)

    base_shape = getattr(base_solid, "Shape", None)
    base_volume = getattr(base_shape, "Volume", None) if base_shape is not None else None

    cut = doc.addObject("Part::Cut", "Pocket")
    cut.Base = base_solid
    cut.Tool = ext
    try:
        doc.recompute()
    except Exception:
        pass

    # Confirm the pocket actually removed material (principle 7). If the tool went
    # the wrong way (nothing removed), flip the direction once and retry; if still
    # nothing, fail with a clear message instead of a false success.
    if _removed_nothing(base_volume, cut):
        ext.Dir = FreeCAD.Vector(-into.x, -into.y, -into.z)
        try:
            doc.recompute()
        except Exception:
            pass
        if _removed_nothing(base_volume, cut):
            raise ValueError(
                "the pocket removed no material; the sketch is likely on the wrong "
                "face or body, or the profile/depth does not reach into it")

    # Part::Cut auto-hides its operands; hide the consumed sketch too.
    hide_object(target)
    return [cut]


def _require_solid(ext) -> None:
    """Raise if the extrusion produced no solid (skipped when solid info is absent,
    e.g. the headless mock has no .Solids)."""
    shape = getattr(ext, "Shape", None)
    solids = getattr(shape, "Solids", None) if shape is not None else None
    if solids is not None and len(solids) == 0:
        raise ValueError(
            "the extrusion produced no solid; the profile may not be a single "
            "closed region (check the target is a closed sketch)")


def _removed_nothing(base_volume, cut) -> bool:
    """True if the cut left the body's volume unchanged (nothing removed). Returns
    False when volumes are unavailable (mock), so the caller does not misjudge."""
    if base_volume is None:
        return False
    cut_shape = getattr(cut, "Shape", None)
    cut_volume = getattr(cut_shape, "Volume", None) if cut_shape is not None else None
    if cut_volume is None:
        return False
    return cut_volume >= base_volume - 1e-6


def _into_body_direction(sketch, base_solid):
    """
    A vector pointing from the sketch's face INTO the base body, so a pocket cuts
    inward. It is the sketch's world normal, flipped if it points away from the
    body's centre. Defensive: falls back to +Z-ish sensible values in the mock.
    """
    import FreeCAD
    try:
        normal = sketch.Placement.Rotation.multVec(FreeCAD.Vector(0.0, 0.0, 1.0))
    except Exception:
        normal = FreeCAD.Vector(0.0, 0.0, 1.0)
    bb = getattr(getattr(base_solid, "Shape", None), "BoundBox", None)
    if bb is None:
        return normal
    centre = FreeCAD.Vector((bb.XMin + bb.XMax) / 2.0,
                            (bb.YMin + bb.YMax) / 2.0,
                            (bb.ZMin + bb.ZMax) / 2.0)
    try:
        sk = sketch.Placement.Base
    except Exception:
        sk = FreeCAD.Vector(0.0, 0.0, 0.0)
    v = centre - sk
    if (v.x * normal.x + v.y * normal.y + v.z * normal.z) < 0:
        return FreeCAD.Vector(-normal.x, -normal.y, -normal.z)
    return normal


def _attachment_owner(sketch):
    """
    Return the object a sketch is attached to (its AttachmentSupport/Support
    owner), or None if it is not attached to anything. Used by a pocket to find
    the body to cut from.
    """
    support = getattr(sketch, "AttachmentSupport", None) \
        or getattr(sketch, "Support", None)
    if not support:
        return None
    try:
        first = support[0]
        return first[0] if isinstance(first, (list, tuple)) else first
    except Exception:
        return None
