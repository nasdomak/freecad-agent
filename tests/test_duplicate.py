#!/usr/bin/env python3
"""
test_duplicate.py - Phase 6 Group B: mirror and array, through the REAL executor
against a fake FreeCAD (tests/mock_freecad.py), WITHOUT a running FreeCAD (ADR 0012).

It proves mirror creates a new reflected object (keeping the original) and array
creates the right number of copies at the right positions, and that both fail
gracefully on bad input (principle 7).

Runnable:
    python tests/test_duplicate.py
    pytest tests/test_duplicate.py
"""

import math
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def run_scenario():
    mock_freecad.install()
    try:
        import ai_copilot.executor as executor
        import FreeCAD
        details = {}
        doc = FreeCAD.newDocument("T")

        # A box to duplicate.
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 20, "width": 10, "height": 6}})
        assert r["ok"], f"create_box failed: {r}"
        box_id = r["created_ids"][0]

        # ---- mirror ----------------------------------------------------------
        # 1) mirror across YZ -> a new object exists, the original is kept.
        n_before = len(doc.Objects)
        r = executor.execute({"cmd": "mirror",
                              "params": {"target": box_id, "plane": "YZ"}})
        assert r["ok"], f"mirror failed: {r}"
        assert len(doc.Objects) == n_before + 1, "mirror must add exactly one object"
        assert doc.getObject(box_id) is not None, "mirror must keep the original"
        details["mirror"] = r["created_ids"]

        # 2) mirror with a bad plane -> graceful failure.
        r = executor.execute({"cmd": "mirror",
                              "params": {"target": box_id, "plane": "QQ"}})
        assert not r["ok"], "mirror with plane 'QQ' should be refused"
        details["mirror_bad_plane"] = "refused"

        # 3) mirror a missing object -> graceful failure.
        r = executor.execute({"cmd": "mirror",
                              "params": {"target": "Ghost", "plane": "XY"}})
        assert not r["ok"] and "not found" in r["error"], f"missing target: {r}"
        details["mirror_missing"] = "refused"

        # ---- array: linear ---------------------------------------------------
        # 4) a linear array of 5 (total) -> 4 NEW copies, 30 mm apart along X.
        r = executor.execute({"cmd": "array",
                              "params": {"target": box_id, "pattern": "linear",
                                         "count": 5, "spacing": 30,
                                         "direction": "X"}})
        assert r["ok"], f"linear array failed: {r}"
        copies = r["created_ids"]
        assert len(copies) == 4, f"count=5 total must make 4 copies, got {len(copies)}"
        # the i-th copy sits at x = 30*i (the original box base is at the origin).
        for i, cid in enumerate(copies, start=1):
            b = doc.getObject(cid).Placement.Base
            assert _approx(b.x, 30 * i) and _approx(b.y, 0) and _approx(b.z, 0), \
                f"copy {i} expected x={30*i}, got {b!r}"
        details["array_linear"] = [doc.getObject(c).Placement.Base.x for c in copies]

        # 5) linear array missing spacing -> graceful failure.
        r = executor.execute({"cmd": "array",
                              "params": {"target": box_id, "pattern": "linear",
                                         "count": 3}})
        assert not r["ok"], "linear array without spacing should be refused"
        details["array_no_spacing"] = "refused"

        # ---- array: polar ----------------------------------------------------
        # 6) polar array around the DEFAULT centre (the file origin), NOT the
        #    object's own axis. Offset the box first so the copies ORBIT instead of
        #    overlapping (the bug Marco hit: a cylinder on its own axis just spun).
        executor.execute({"cmd": "move",
                          "params": {"target": box_id, "to": [30, 0, 0]}})
        r = executor.execute({"cmd": "array",
                              "params": {"target": box_id, "pattern": "polar",
                                         "count": 4, "axis": "Z"}})
        assert r["ok"], f"polar array failed: {r}"
        copies = r["created_ids"]
        assert len(copies) == 3, f"count=4 total must make 3 copies, got {len(copies)}"
        for cid in copies:
            b = doc.getObject(cid).Placement.Base
            rad = math.sqrt(b.x * b.x + b.y * b.y)
            assert _approx(rad, 30, 1e-3), f"copy should orbit at radius 30, got {rad}"
            assert not (_approx(b.x, 30) and _approx(b.y, 0)), \
                "copy overlaps the original (it spun in place instead of orbiting)"
        details["array_polar_orbit"] = "copies orbit the origin at r=30"

        # 6b) polar array with an explicit RADIUS: the original (here on the Z axis)
        #     is repositioned onto a circle of that radius and the copies orbit it.
        r = executor.execute({"cmd": "create_cylinder",
                              "params": {"radius": 2, "height": 10}})
        cyl_id = r["created_ids"][0]   # created at the origin (on the Z axis)
        r = executor.execute({"cmd": "array",
                              "params": {"target": cyl_id, "pattern": "polar",
                                         "count": 4, "axis": "Z", "radius": 25}})
        assert r["ok"], f"polar radius array failed: {r}"
        ob = doc.getObject(cyl_id).Placement.Base
        assert _approx(math.sqrt(ob.x * ob.x + ob.y * ob.y), 25, 1e-3), \
            f"radius should move the original onto r=25, got {ob!r}"
        for cid in r["created_ids"]:
            b = doc.getObject(cid).Placement.Base
            assert _approx(math.sqrt(b.x * b.x + b.y * b.y), 25, 1e-3), \
                "copy not on the r=25 circle"
        details["array_polar_radius"] = "original + copies placed on r=25"

        # 7) unknown pattern -> graceful failure.
        r = executor.execute({"cmd": "array",
                              "params": {"target": box_id, "pattern": "spiral",
                                         "count": 3, "spacing": 5}})
        assert not r["ok"], "unknown pattern should be refused"
        details["array_bad_pattern"] = "refused"

        # 8) count < 1 -> graceful failure.
        r = executor.execute({"cmd": "array",
                              "params": {"target": box_id, "pattern": "linear",
                                         "count": 0, "spacing": 5}})
        assert not r["ok"], "count 0 should be refused"
        details["array_bad_count"] = "refused"

        return True, details
    finally:
        mock_freecad.uninstall()


def test_duplicate():
    ok, details = run_scenario()
    assert ok, f"duplicate execution failed: {details}"


if __name__ == "__main__":
    print("== test_duplicate: mirror/array through the real executor (mock FreeCAD) ==")
    try:
        ok, details = run_scenario()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    for k, v in details.items():
        print(f"  [ok] {k}: {v}")
    print("PASS - mirror and array build the right objects and fail gracefully.")
    sys.exit(0)
