"""
executor/vocabulary/mirror.py - implementation of the `mirror` command (Phase 6).

Command definition: shared/commands.schema.json -> catalog.mirror
  params: target (req); plane ('XY'/'XZ'/'YZ', default 'YZ'); base [x,y,z] (opt,
          default origin). Units: mm.

Reflects an existing object across a standard plane using Part::Mirroring, a
parametric Part-workbench feature (principle 2: no Draft dependency). The mirror
plane is given as a friendly string and resolved to its NORMAL in the executor
(ADR 0011); the default plane is YZ (a left/right mirror across the X axis), the
most common intent. The ORIGINAL is kept visible: a mirror almost always wants
both halves (unlike fillet/extrude, which consume their base).
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object, resolve_plane_normal


def mirror(doc, params: dict) -> List:
    """Mirror an existing object across a standard plane, keeping the original."""
    import FreeCAD  # lazy import: available only inside FreeCAD.

    target = resolve_object(doc, params["target"])
    normal = resolve_plane_normal(params.get("plane"), default="YZ")

    base = params.get("base")
    if base is not None:
        if not isinstance(base, (list, tuple)) or len(base) < 3:
            raise ValueError("'base' must be a list of three numbers [x,y,z]")
        base_vec = FreeCAD.Vector(float(base[0]), float(base[1]), float(base[2]))
    else:
        base_vec = FreeCAD.Vector(0.0, 0.0, 0.0)

    feat = doc.addObject("Part::Mirroring", "Mirror")
    feat.Source = target
    feat.Base = base_vec     # a point the mirror plane passes through
    feat.Normal = normal     # the plane's normal (ADR 0011)

    # Verify we produced a real shape (principle 7/8: no hollow success). Only
    # enforced when shape info is readable (FreeCAD); the headless mock has no
    # such attribute, so the check is skipped there.
    try:
        doc.recompute()
    except Exception:
        pass
    shape = getattr(feat, "Shape", None)
    if shape is not None:
        faces = getattr(shape, "Faces", None)
        if faces is not None and len(faces) == 0:
            raise ValueError("the mirror produced an empty shape; check the target")

    return [feat]
