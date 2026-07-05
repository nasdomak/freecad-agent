"""
executor/vocabulary/_common.py - small helpers shared by the vocabulary commands.

Phase 2 commands often reference EXISTING objects (a body to drill, the two bodies
of a boolean, the edges to fillet). These helpers resolve those references and
parse sub-element ids ("Edge7" -> 7) in one place, so every command behaves the
same and fails with clear, user-facing messages (principle 7: verify the input).
"""

from __future__ import annotations

from typing import List


def bounding_box(obj):
    """
    Best-effort bounding box of an object's shape, or None if it has none yet.
    Used by commands that must locate an existing body in space (e.g. drilling a
    hole on its top face) instead of trusting coordinates the model guessed
    (principle 7: the agent perceives and verifies).
    """
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return None
    return getattr(shape, "BoundBox", None)


def hide_object(obj) -> None:
    """
    Hide an object in the 3D view (best-effort, no-op without a GUI).

    When a feature CONSUMES a base object (fillet/chamfer round the base; a
    boolean fuses/cuts its operands), FreeCAD's interactive commands hide the
    original so you only see the result. Creating the same feature through the
    data API does NOT hide it, which leaves the original body drawn ON TOP of the
    result - e.g. a sharp-edged box covering the rounded fillet, so the rounding
    "looks like it did nothing". We replicate the GUI behaviour explicitly.

    Booleans (Part::Cut/Fuse/Common) already auto-hide their operands via their
    own view provider; this helper covers the features that do not (fillet,
    chamfer). It is defensive: ViewObject is None in headless/console runs.
    """
    try:
        view = getattr(obj, "ViewObject", None)
        if view is not None:
            view.Visibility = False
    except Exception:
        pass


# --- model-friendly axis/plane resolution (ADR 0011) -------------------------
# Phase 6 commands point along an AXIS (rotate) or across a PLANE (mirror). A
# small local model produces free 3D vectors unreliably, so the CONTRACT uses
# short strings ("X"/"Y"/"Z", "XY"/"XZ"/"YZ") and the EXECUTOR maps them to real
# vectors here - the same lesson as ADR 0006/0010 (resolve fragile references in
# the executor, which can read real geometry, not in the model).

_AXIS_VECTORS = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
_PLANE_NORMALS = {"XY": (0.0, 0.0, 1.0), "XZ": (0.0, 1.0, 0.0), "YZ": (1.0, 0.0, 0.0)}


def resolve_axis(axis, default: str = "Z"):
    """
    Map an axis spec to a FreeCAD.Vector. Accepts the strings 'X'/'Y'/'Z' (the
    model-friendly contract) and, for power users, an explicit [x,y,z] vector.
    None falls back to `default`. Raises ValueError on an unknown string.
    """
    import FreeCAD
    if axis is None:
        axis = default
    if isinstance(axis, str):
        key = axis.strip().upper()
        if key not in _AXIS_VECTORS:
            raise ValueError(
                f"unknown axis '{axis}'. Use one of: {', '.join(_AXIS_VECTORS)}")
        return FreeCAD.Vector(*_AXIS_VECTORS[key])
    if isinstance(axis, (list, tuple)) and len(axis) >= 3:
        return FreeCAD.Vector(float(axis[0]), float(axis[1]), float(axis[2]))
    raise ValueError(f"invalid axis: {axis!r} (use 'X'/'Y'/'Z' or [x,y,z])")


def resolve_plane_normal(plane, default: str = "XY"):
    """
    Map a plane spec ('XY'/'XZ'/'YZ') to the FreeCAD.Vector of its NORMAL. Also
    accepts an explicit [x,y,z] normal. None falls back to `default`.
    """
    import FreeCAD
    if plane is None:
        plane = default
    if isinstance(plane, str):
        key = plane.strip().upper()
        if key not in _PLANE_NORMALS:
            raise ValueError(
                f"unknown plane '{plane}'. Use one of: {', '.join(_PLANE_NORMALS)}")
        return FreeCAD.Vector(*_PLANE_NORMALS[key])
    if isinstance(plane, (list, tuple)) and len(plane) >= 3:
        return FreeCAD.Vector(float(plane[0]), float(plane[1]), float(plane[2]))
    raise ValueError(f"invalid plane: {plane!r} (use 'XY'/'XZ'/'YZ' or [x,y,z])")


def bbox_center(obj):
    """
    Centre of the object's bounding box as a FreeCAD.Vector, or the origin if the
    object has no shape yet. Used as the default pivot for rotate (the agent
    perceives the real centre instead of trusting a coordinate the model guessed).
    """
    import FreeCAD
    bb = bounding_box(obj)
    if bb is None:
        return FreeCAD.Vector(0.0, 0.0, 0.0)
    return FreeCAD.Vector((bb.XMin + bb.XMax) / 2.0,
                          (bb.YMin + bb.YMax) / 2.0,
                          (bb.ZMin + bb.ZMax) / 2.0)


def resolve_object(doc, obj_id: str):
    """
    Return the FreeCAD object whose internal Name is `obj_id`.
    Raises ValueError with a helpful message if it does not exist.
    """
    if not obj_id or not isinstance(obj_id, str):
        raise ValueError("an object id (string) is required")
    obj = doc.getObject(obj_id)
    if obj is None:
        # Be forgiving: the model might pass the user-visible Label instead.
        for candidate in doc.Objects:
            if getattr(candidate, "Label", None) == obj_id:
                return candidate
        known = ", ".join(o.Name for o in doc.Objects) or "(document is empty)"
        raise ValueError(f"object '{obj_id}' not found. Existing objects: {known}")
    return obj


def parse_edge_index(edge_ref: str) -> int:
    """
    Convert an edge reference like 'Edge7' (or plain '7') into the 1-based index
    FreeCAD expects in Chamfer/Fillet. Raises ValueError on garbage input.
    """
    if isinstance(edge_ref, int):
        return edge_ref
    s = str(edge_ref).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        raise ValueError(f"invalid edge reference: {edge_ref!r} (expected e.g. 'Edge7')")
    return int(digits)


def parse_edge_indices(edges: List[str]) -> List[int]:
    """Map a list of edge references to their 1-based indices."""
    if not edges:
        raise ValueError("at least one edge id is required")
    return [parse_edge_index(e) for e in edges]


# --- executor-side edge selection (ADR 0006) ---------------------------------
# Fillet/chamfer can pick edges WITHOUT the model enumerating Edge1..EdgeN. The
# executor runs inside FreeCAD, so it can read the real geometry and choose the
# right edges itself (principle 7: the agent perceives and verifies, it does not
# ask a small model to list a dozen edge ids correctly).

EDGE_SELECTORS = ("all", "top", "bottom", "vertical", "horizontal")


class _SimpleBBox:
    """A tiny stand-in for FreeCAD's BoundBox, built from an edge's vertices."""
    __slots__ = ("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax")

    def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
        self.XMin, self.XMax = xmin, xmax
        self.YMin, self.YMax = ymin, ymax
        self.ZMin, self.ZMax = zmin, zmax


def _edge_bbox(edge):
    """
    Best-effort axis-aligned bounding box of a single edge. Prefers the edge's
    own BoundBox (real FreeCAD); falls back to the span of its vertices. Returns
    None if no geometry is available.
    """
    bb = getattr(edge, "BoundBox", None)
    if bb is not None:
        return bb
    verts = getattr(edge, "Vertexes", None)
    if not verts:
        return None
    xs, ys, zs = [], [], []
    for v in verts:
        p = getattr(v, "Point", None)
        if p is None:
            return None
        xs.append(p.x)
        ys.append(p.y)
        zs.append(p.z)
    if not xs:
        return None
    return _SimpleBBox(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def select_edge_indices(shape, where: str = "all") -> List[int]:
    """
    Return the 1-based indices of `shape`'s edges that match a selector:

      all        -> every edge
      top        -> edges lying flat at the highest Z
      bottom     -> edges lying flat at the lowest Z
      vertical   -> edges running along the Z axis
      horizontal -> edges lying flat in any constant-Z plane (top + bottom)

    Selection is GEOMETRIC (reads each edge's bounding box), assuming the common
    orientation where "up" is +Z. If global geometry is unavailable we fall back
    to "all" so the operation still has edges to act on rather than failing.
    Raises ValueError for an empty shape, an unknown selector, or a selector that
    matches no edge (so the caller can report a clear message and self-correct).
    """
    edges = list(getattr(shape, "Edges", []) or [])
    n = len(edges)
    if n == 0:
        raise ValueError("the target has no edges to operate on")

    where = (where or "all").lower()
    if where not in EDGE_SELECTORS:
        raise ValueError(
            f"unknown edge selector '{where}'. Use one of: {', '.join(EDGE_SELECTORS)}")

    if where == "all":
        return list(range(1, n + 1))

    sbb = getattr(shape, "BoundBox", None)
    if sbb is None:
        return list(range(1, n + 1))  # no global frame: act on all edges.

    z_min, z_max = sbb.ZMin, sbb.ZMax
    span = max(sbb.XMax - sbb.XMin, sbb.YMax - sbb.YMin, z_max - z_min, 1.0)
    tol = span * 1e-4  # generous tolerance, robust to rounding.

    chosen: List[int] = []
    for i, edge in enumerate(edges, start=1):
        ebb = _edge_bbox(edge)
        if ebb is None:
            continue
        ez = abs(ebb.ZMax - ebb.ZMin)
        ex = abs(ebb.XMax - ebb.XMin)
        ey = abs(ebb.YMax - ebb.YMin)
        is_flat = ez <= tol                       # edge stays in one Z plane
        is_vertical = (ez > tol) and (ex <= tol) and (ey <= tol)
        if where == "vertical" and is_vertical:
            chosen.append(i)
        elif where == "horizontal" and is_flat:
            chosen.append(i)
        elif where == "top" and is_flat and abs(ebb.ZMax - z_max) <= tol:
            chosen.append(i)
        elif where == "bottom" and is_flat and abs(ebb.ZMin - z_min) <= tol:
            chosen.append(i)

    if not chosen:
        raise ValueError(
            f"no edges matched selector '{where}' on this shape; "
            "try 'all' or list explicit edge ids")
    return chosen
