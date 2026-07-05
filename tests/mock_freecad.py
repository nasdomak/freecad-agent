"""
tests/mock_freecad.py - a SMALL fake of the FreeCAD API for headless tests.

It lets us exercise the add-on executor (vocabulary commands, python.execute) and
the perception module WITHOUT a running FreeCAD. It is deliberately minimal: it
models just enough of the document/object/transaction API that our code touches.
It is NOT a geometry kernel — shapes carry only the counts and bounding boxes our
perception needs.

Usage:
    import mock_freecad
    mock_freecad.install()          # registers a fake `FreeCAD` module in sys.modules
    ...                             # now `import FreeCAD` returns the fake
    mock_freecad.uninstall()
"""

from __future__ import annotations

import math
import sys
import types
from typing import List, Optional


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    # Minimal arithmetic so transform code/tests can compose positions.
    def __add__(self, other: "Vector") -> "Vector":
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vector") -> "Vector":
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __eq__(self, other) -> bool:
        return (isinstance(other, Vector)
                and abs(self.x - other.x) < 1e-9
                and abs(self.y - other.y) < 1e-9
                and abs(self.z - other.z) < 1e-9)

    def __repr__(self) -> str:
        return f"Vector({self.x:g}, {self.y:g}, {self.z:g})"


class Rotation:
    """
    Faithful-enough rotation: built from an axis vector + angle in DEGREES (the
    signature rotate.py uses), stored as a 3x3 matrix so we can rotate vectors and
    compose rotations. Rotation() is the identity. Enough to read back a rotated
    position in headless tests (the real FreeCAD does the same maths).
    """

    def __init__(self, axis: Optional["Vector"] = None, angle: float = 0.0):
        if axis is None:
            self._m = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            self.Axis = Vector(0, 0, 1)
            self.Angle = 0.0
            return
        n = math.sqrt(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z) or 1.0
        kx, ky, kz = axis.x / n, axis.y / n, axis.z / n
        th = math.radians(float(angle))
        c, s, t = math.cos(th), math.sin(th), 1.0 - math.cos(th)
        self._m = (
            (c + kx * kx * t,      kx * ky * t - kz * s, kx * kz * t + ky * s),
            (ky * kx * t + kz * s, c + ky * ky * t,      ky * kz * t - kx * s),
            (kz * kx * t - ky * s, kz * ky * t + kx * s, c + kz * kz * t),
        )
        self.Axis = Vector(kx, ky, kz)
        self.Angle = th  # radians, like FreeCAD's Rotation.Angle

    @classmethod
    def _from_matrix(cls, m) -> "Rotation":
        r = cls()
        r._m = m
        return r

    def multVec(self, v: "Vector") -> "Vector":
        m = self._m
        return Vector(m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
                      m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
                      m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z)

    def __mul__(self, other: "Rotation") -> "Rotation":
        a, b = self._m, other._m
        m = tuple(
            tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
            for i in range(3)
        )
        return Rotation._from_matrix(m)


class Placement:
    """
    Rigid transform p -> Rotation.multVec(p) + Base. Like FreeCAD, a 3-arg
    constructor Placement(base, rotation, center) folds the pivot into Base
    immediately (center is not stored): Base = base + center - rotation*center.
    """

    def __init__(self, base: Optional[Vector] = None,
                 rot: Optional[Rotation] = None,
                 center: Optional[Vector] = None):
        rot = rot or Rotation()
        base = base or Vector()
        if center is not None:
            base = base + center - rot.multVec(center)
        self.Base = base
        self.Rotation = rot

    def multiply(self, other: "Placement") -> "Placement":
        """Compose: (self*other).multVec(v) == self.multVec(other.multVec(v))."""
        new_rot = self.Rotation * other.Rotation
        new_base = self.Rotation.multVec(other.Base) + self.Base
        return Placement(new_base, new_rot)

    def multVec(self, v: "Vector") -> "Vector":
        return self.Rotation.multVec(v) + self.Base


class BoundBox:
    def __init__(self, xmin, ymin, zmin, xmax, ymax, zmax):
        self.XMin, self.YMin, self.ZMin = xmin, ymin, zmin
        self.XMax, self.YMax, self.ZMax = xmax, ymax, zmax

    def add(self, other: "BoundBox"):
        self.XMin = min(self.XMin, other.XMin)
        self.YMin = min(self.YMin, other.YMin)
        self.ZMin = min(self.ZMin, other.ZMin)
        self.XMax = max(self.XMax, other.XMax)
        self.YMax = max(self.YMax, other.YMax)
        self.ZMax = max(self.ZMax, other.ZMax)


class _Face:
    def __init__(self, nz: float):
        self._nz = nz

    def normalAt(self, u, v):
        return Vector(0, 0, self._nz)


# --- toy Sketcher geometry (enough for create_sketch headless tests) ----------
# These mimic the small slice of the Part/Sketcher API that create_sketch touches:
# Part.LineSegment, Part.Circle and Sketcher.Constraint. They only carry the data
# our mock recompute needs to synthesize the sketch's bounding box.

class _GeomLine:
    kind = "line"

    def __init__(self, p1: Vector, p2: Vector):
        self.StartPoint = p1
        self.EndPoint = p2


class _GeomCircle:
    kind = "circle"

    def __init__(self, center: Vector, normal: Vector, radius: float):
        self.Center = center
        self.Axis = normal
        self.Radius = float(radius)


class _Constraint:
    def __init__(self, *args):
        self.args = args


class _Edge:
    """A toy edge carrying only an axis-aligned BoundBox (enough for selection)."""
    def __init__(self, bbox: BoundBox):
        self.BoundBox = bbox


def _box_edges(L: float, W: float, H: float) -> List["_Edge"]:
    """
    The 12 edges of an axis-aligned box from (0,0,0) to (L,W,H), each as a tiny
    edge with its own bounding box. Lets tests exercise the geometric edge
    selector (top/bottom/vertical/horizontal) realistically.
    """
    e = []
    # 4 bottom edges (z = 0)
    e.append(_Edge(BoundBox(0, 0, 0, L, 0, 0)))
    e.append(_Edge(BoundBox(0, W, 0, L, W, 0)))
    e.append(_Edge(BoundBox(0, 0, 0, 0, W, 0)))
    e.append(_Edge(BoundBox(L, 0, 0, L, W, 0)))
    # 4 top edges (z = H)
    e.append(_Edge(BoundBox(0, 0, H, L, 0, H)))
    e.append(_Edge(BoundBox(0, W, H, L, W, H)))
    e.append(_Edge(BoundBox(0, 0, H, 0, W, H)))
    e.append(_Edge(BoundBox(L, 0, H, L, W, H)))
    # 4 vertical edges (run along Z at each corner)
    e.append(_Edge(BoundBox(0, 0, 0, 0, 0, H)))
    e.append(_Edge(BoundBox(L, 0, 0, L, 0, H)))
    e.append(_Edge(BoundBox(0, W, 0, 0, W, H)))
    e.append(_Edge(BoundBox(L, W, 0, L, W, H)))
    return e


class Shape:
    """A toy shape: only counts + bounding box (enough for perception)."""
    def __init__(self, faces=6, edges=12, vertices=8, bbox: Optional[BoundBox] = None,
                 edge_objs: Optional[List["_Edge"]] = None):
        self.Faces = [_Face(1.0 if i == 0 else -1.0 if i == 1 else 0.0)
                      for i in range(faces)]
        # If real edge objects are supplied (e.g. for a box), use them so the
        # geometric edge selector has something to read; otherwise plain ints.
        self.Edges = edge_objs if edge_objs is not None else list(range(edges))
        self.Vertexes = list(range(vertices))
        self.BoundBox = bbox or BoundBox(0, 0, 0, 1, 1, 1)

    def copy(self) -> "Shape":
        """A detached copy carrying the same counts and bounding box (enough for
        the `array` command, which copies a target's Shape into each item)."""
        bb = self.BoundBox
        return Shape(len(self.Faces), len(self.Edges), len(self.Vertexes),
                     BoundBox(bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax))


class _ViewObject:
    def __init__(self):
        self.Visibility = True


class DocumentObject:
    """A permissive object: any attribute can be set (like FreeCAD properties)."""
    def __init__(self, doc, type_id: str, name: str):
        object.__setattr__(self, "_doc", doc)
        self.TypeId = type_id
        self.Name = name
        self.Label = name
        self.State: List[str] = []
        self.ViewObject = _ViewObject()
        self.Shape = None  # filled in by recompute()
        self.Placement = Placement()  # identity until moved/rotated
        self._geometry: List[object] = []  # Sketcher geometry (create_sketch)

    # Minimal Sketcher API used by create_sketch (no-ops beyond recording geometry).
    def addGeometry(self, geo, construction: bool = False) -> int:
        self._geometry.append(geo)
        return len(self._geometry) - 1

    def addConstraint(self, constraint) -> int:
        return 0


class Document:
    def __init__(self, name: str):
        self.Name = name
        self.Objects: List[DocumentObject] = []
        self._used_names = {}
        self._tx_stack = []      # open transactions: snapshot of len(Objects)
        self._undo = []          # committed transactions: (label, [names])

    # -- object management -----------------------------------------------------

    def addObject(self, type_id: str, name: str = "") -> DocumentObject:
        base = name or type_id.split("::")[-1]
        # FreeCAD auto-uniquifies names.
        n = self._used_names.get(base, 0)
        self._used_names[base] = n + 1
        unique = base if n == 0 else f"{base}{n:03d}"
        obj = DocumentObject(self, type_id, unique)
        self.Objects.append(obj)
        return obj

    def getObject(self, name: str) -> Optional[DocumentObject]:
        for o in self.Objects:
            if o.Name == name:
                return o
        return None

    def removeObject(self, name: str) -> None:
        self.Objects = [o for o in self.Objects if o.Name != name]

    # -- recompute: synthesize toy shapes so perception has something to read ---

    def recompute(self) -> int:
        for o in self.Objects:
            o.Shape = self._shape_for(o)
            o.State = []
        return 0

    def _shape_for(self, o: DocumentObject) -> Shape:
        t = o.TypeId
        if t == "Part::Box":
            L = float(getattr(o, "Length", 1)); W = float(getattr(o, "Width", 1))
            H = float(getattr(o, "Height", 1))
            return Shape(6, 12, 8, BoundBox(0, 0, 0, L, W, H),
                         edge_objs=_box_edges(L, W, H))
        if t == "Part::Cylinder":
            R = float(getattr(o, "Radius", 1)); H = float(getattr(o, "Height", 1))
            return Shape(3, 3, 2, BoundBox(-R, -R, 0, R, R, H))
        if t == "Sketcher::SketchObject":
            return self._sketch_shape(o)
        if t == "Part::Feature":
            # An array copy (or any manual feature): keep the Shape assigned by the
            # command (a Shape.copy()); only synthesize one if none was set.
            existing = getattr(o, "Shape", None)
            return existing if existing is not None else Shape(6, 12, 8)
        if t == "Part::Mirroring":
            # Inherit the Source's bbox (a reflected copy keeps the same extent).
            src = getattr(o, "Source", None)
            if src is not None and getattr(src, "Shape", None) is not None:
                bb = src.Shape.BoundBox
                return Shape(6, 12, 8, BoundBox(bb.XMin, bb.YMin, bb.ZMin,
                                                bb.XMax, bb.YMax, bb.ZMax))
            return Shape(6, 12, 8)
        # Booleans/fillets/etc.: inherit the base's bbox if present.
        base = getattr(o, "Base", None)
        if base is not None and getattr(base, "Shape", None) is not None:
            bb = base.Shape.BoundBox
            return Shape(6, 12, 8, BoundBox(bb.XMin, bb.YMin, bb.ZMin,
                                            bb.XMax, bb.YMax, bb.ZMax))
        return Shape(6, 12, 8)

    @staticmethod
    def _sketch_shape(o: "DocumentObject") -> Shape:
        """
        Build a toy shape for a sketch from its recorded geometry (local coords,
        z = 0). Enough for create_sketch -> extrude tests: a bounding box and an
        edge count. The placement rotation is ignored (irrelevant to the tests).
        """
        pts: List[Vector] = []
        geom = getattr(o, "_geometry", []) or []
        for g in geom:
            kind = getattr(g, "kind", None)
            if kind == "line":
                pts.append(g.StartPoint)
                pts.append(g.EndPoint)
            elif kind == "circle":
                c, r = g.Center, g.Radius
                pts.append(Vector(c.x - r, c.y - r, c.z))
                pts.append(Vector(c.x + r, c.y + r, c.z))
        if not pts:
            return Shape(1, 1, 1)
        xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
        bbox = BoundBox(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        return Shape(faces=1, edges=max(len(geom), 1), vertices=len(pts), bbox=bbox)

    # -- transactions ----------------------------------------------------------

    def openTransaction(self, label: str) -> None:
        self._tx_stack.append((label, len(self.Objects)))

    def commitTransaction(self) -> None:
        if not self._tx_stack:
            return
        label, start = self._tx_stack.pop()
        added = [o.Name for o in self.Objects[start:]]
        self._undo.append((label, added))

    def abortTransaction(self) -> None:
        if not self._tx_stack:
            return
        _label, start = self._tx_stack.pop()
        # Roll back: drop everything created since the transaction opened.
        self.Objects = self.Objects[:start]

    def getUndoNames(self) -> List[str]:
        return [label for label, _ in self._undo]

    def undo(self) -> None:
        if not self._undo:
            return
        _label, added = self._undo.pop()
        for name in added:
            self.removeObject(name)


def _make_module() -> types.ModuleType:
    mod = types.ModuleType("FreeCAD")
    mod.Vector = Vector
    mod.Rotation = Rotation
    mod.Placement = Placement
    mod.BoundBox = BoundBox
    mod.ActiveDocument = None

    def newDocument(name: str = "Unnamed"):
        doc = Document(name)
        mod.ActiveDocument = doc
        return doc

    mod.newDocument = newDocument
    return mod


def _make_part_module() -> types.ModuleType:
    """Fake `Part` module: just the geometry constructors create_sketch uses."""
    mod = types.ModuleType("Part")
    mod.LineSegment = _GeomLine
    mod.Circle = _GeomCircle
    return mod


def _make_sketcher_module() -> types.ModuleType:
    """Fake `Sketcher` module: just the Constraint constructor."""
    mod = types.ModuleType("Sketcher")
    mod.Constraint = _Constraint
    return mod


_SAVED = {}
_FAKE_MODULES = {
    "FreeCAD": _make_module,
    "Part": _make_part_module,
    "Sketcher": _make_sketcher_module,
}


def install() -> types.ModuleType:
    """Install the fake FreeCAD/Part/Sketcher modules; return the FreeCAD one."""
    for name, factory in _FAKE_MODULES.items():
        _SAVED[name] = sys.modules.get(name)
        sys.modules[name] = factory()
    return sys.modules["FreeCAD"]


def uninstall() -> None:
    for name in _FAKE_MODULES:
        prev = _SAVED.get(name)
        if prev is not None:
            sys.modules[name] = prev
        else:
            sys.modules.pop(name, None)
