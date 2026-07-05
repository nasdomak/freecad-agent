"""
perception.py - the agent's "eyes" on the FreeCAD document (Phase 2).

Implements the two perception methods of the protocol:
  - perception.overview : cheap, always-on summary of the active document
                          (documentOverview in shared/context.schema.json).
  - perception.detail   : on-demand close-up of one object the agent points at
                          (objectDetail) - "geometric RAG".

Stated design goal (context.schema.json): be CONCISE so as not to saturate the
context window of small local models. The overview emits ONE synthetic line per
object (id/type/label), never raw geometry; detail adds counts and a few named
sub-elements (faces/edges) the model can reference in commands.

These functions are defensive: they read whatever is available via getattr, so
they also run against partial/mock objects in headless tests. FreeCAD is imported
lazily; an explicit `doc` can be passed (tests), otherwise the active document is
used.
"""

from __future__ import annotations

from typing import List, Optional


def _active_document(doc=None):
    if doc is not None:
        return doc
    import FreeCAD  # lazy import: available only inside FreeCAD.
    return FreeCAD.ActiveDocument


def _bbox_dict(bb) -> Optional[dict]:
    """Convert a FreeCAD BoundBox to {min:[...], max:[...]} (rounded), or None."""
    if bb is None:
        return None
    try:
        return {
            "min": [round(bb.XMin, 3), round(bb.YMin, 3), round(bb.ZMin, 3)],
            "max": [round(bb.XMax, 3), round(bb.YMax, 3), round(bb.ZMax, 3)],
        }
    except Exception:
        return None


def _object_bbox(obj):
    """Best-effort bounding box of a single object (None if it has no shape)."""
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return None
    return getattr(shape, "BoundBox", None)


def overview(doc=None) -> dict:
    """
    Build a concise documentOverview of the active document.
    Returns a dict conforming to context.schema.json#/$defs/documentOverview.
    """
    doc = _active_document(doc)
    if doc is None:
        return {"document_name": "(none)", "object_count": 0, "units": "mm",
                "bounding_box": {}, "objects": []}

    objects: List[dict] = []
    overall = None
    for obj in getattr(doc, "Objects", []):
        visible = True
        vo = getattr(obj, "ViewObject", None)
        if vo is not None:
            visible = bool(getattr(vo, "Visibility", True))
        objects.append({
            "id": getattr(obj, "Name", "?"),
            "type": getattr(obj, "TypeId", "?"),
            "label": getattr(obj, "Label", getattr(obj, "Name", "?")),
            "visible": visible,
        })
        bb = _object_bbox(obj)
        if bb is not None:
            overall = bb if overall is None else _merge_bbox(overall, bb)

    return {
        "document_name": getattr(doc, "Name", "?"),
        "object_count": len(objects),
        "units": "mm",
        "bounding_box": _bbox_dict(overall) or {},
        "objects": objects,
    }


def _merge_bbox(a, b):
    """Union of two FreeCAD BoundBox objects (defensive)."""
    try:
        a.add(b)
        return a
    except Exception:
        return a


def detail(target: str, doc=None) -> dict:
    """
    Build an objectDetail for one object the agent asks about.
    Returns a dict conforming to context.schema.json#/$defs/objectDetail.
    """
    doc = _active_document(doc)
    obj = None
    if doc is not None:
        obj = doc.getObject(target) if hasattr(doc, "getObject") else None
        if obj is None:
            for cand in getattr(doc, "Objects", []):
                if getattr(cand, "Label", None) == target:
                    obj = cand
                    break
    if obj is None:
        return {"id": target, "type": "?", "error": f"object '{target}' not found"}

    result = {
        "id": getattr(obj, "Name", target),
        "type": getattr(obj, "TypeId", "?"),
        "label": getattr(obj, "Label", target),
        "dimensions": _dimensions(obj),
    }

    shape = getattr(obj, "Shape", None)
    if shape is not None:
        bb = getattr(shape, "BoundBox", None)
        if bb is not None:
            result["bounding_box"] = _bbox_dict(bb)
        result["topology"] = {
            "faces": len(getattr(shape, "Faces", []) or []),
            "edges": len(getattr(shape, "Edges", []) or []),
            "vertices": len(getattr(shape, "Vertexes", []) or []),
        }
        result["named_subelements"] = _named_subelements(shape)
    return result


# Common, model-relevant parameters per primitive type. Kept short on purpose.
_DIMENSION_PROPS = {
    "Part::Box": ["Length", "Width", "Height"],
    "Part::Cylinder": ["Radius", "Height"],
    "Part::Sphere": ["Radius"],
    "Part::Cone": ["Radius1", "Radius2", "Height"],
}


def _dimensions(obj) -> dict:
    """Read the relevant dimensional properties of the object (concise)."""
    dims = {}
    for prop in _DIMENSION_PROPS.get(getattr(obj, "TypeId", ""), []):
        val = getattr(obj, prop, None)
        if val is not None:
            # FreeCAD quantities expose .Value; fall back to the raw value.
            dims[prop] = round(float(getattr(val, "Value", val)), 3)
    return dims


def _named_subelements(shape) -> List[dict]:
    """
    A FEW referenceable faces/edges with human hints, so the model can target
    them in chamfer/fillet/drill. We label edges Edge1.. and faces Face1.. exactly
    as FreeCAD does, and add a cheap orientation hint where we can.
    """
    out: List[dict] = []
    faces = getattr(shape, "Faces", []) or []
    for i, face in enumerate(faces[:12], start=1):  # cap to stay concise
        hint = ""
        try:
            n = face.normalAt(0, 0)
            if abs(n.z) > 0.9:
                hint = "top face" if n.z > 0 else "bottom face"
            elif abs(n.x) > 0.9:
                hint = "face along X"
            elif abs(n.y) > 0.9:
                hint = "face along Y"
        except Exception:
            pass
        out.append({"ref": f"Face{i}", "kind": "face", "hint": hint})

    edges = getattr(shape, "Edges", []) or []
    for i in range(1, min(len(edges), 12) + 1):
        out.append({"ref": f"Edge{i}", "kind": "edge", "hint": ""})
    return out
