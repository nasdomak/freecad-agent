#!/usr/bin/env python3
"""
test_transform.py - Phase 6 Group A: move and rotate, through the REAL executor
against a fake FreeCAD (tests/mock_freecad.py), WITHOUT a running FreeCAD.

It proves the in-place transforms compose the object's Placement correctly and
fail gracefully on bad input. The mock's Placement/Rotation are faithful enough
to read back the new position/orientation (axis-angle maths), so we assert the
actual translated/rotated coordinates - not just that the command "returned ok".

Runnable:
    python tests/test_transform.py
    pytest tests/test_transform.py
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

        # A box 20x10x6 at the origin; bbox centre is (10, 5, 3).
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 20, "width": 10, "height": 6}})
        assert r["ok"], f"create_box failed: {r}"
        box_id = r["created_ids"][0]
        doc = FreeCAD.ActiveDocument
        box = doc.getObject(box_id)

        # 1) move BY a relative offset -> Base shifts by the delta.
        r = executor.execute({"cmd": "move",
                              "params": {"target": box_id, "by": [20, 0, 0]}})
        assert r["ok"], f"move by failed: {r}"
        b = box.Placement.Base
        assert (_approx(b.x, 20) and _approx(b.y, 0) and _approx(b.z, 0)), \
            f"move by [20,0,0] -> Base {b!r}"
        details["move_by"] = (b.x, b.y, b.z)

        # 1b) a second relative move composes on top of the first.
        r = executor.execute({"cmd": "move",
                              "params": {"target": box_id, "by": [0, 5, -2]}})
        assert r["ok"], f"second move failed: {r}"
        b = box.Placement.Base
        assert (_approx(b.x, 20) and _approx(b.y, 5) and _approx(b.z, -2)), \
            f"composed move -> Base {b!r}"
        details["move_compose"] = (b.x, b.y, b.z)

        # 2) move TO an absolute position -> Base is set exactly.
        r = executor.execute({"cmd": "move",
                              "params": {"target": box_id, "to": [1, 2, 3]}})
        assert r["ok"], f"move to failed: {r}"
        b = box.Placement.Base
        assert (_approx(b.x, 1) and _approx(b.y, 2) and _approx(b.z, 3)), \
            f"move to [1,2,3] -> Base {b!r}"
        details["move_to"] = (b.x, b.y, b.z)

        # 3) move with neither 'by' nor 'to' -> graceful failure (principle 7).
        r = executor.execute({"cmd": "move", "params": {"target": box_id}})
        assert not r["ok"], "move without by/to should be refused"
        details["move_no_target"] = "refused"

        # ---- rotate ----------------------------------------------------------
        # Fresh box at the origin for clean rotation assertions.
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 4, "width": 4, "height": 4}})
        box2_id = r["created_ids"][0]
        box2 = doc.getObject(box2_id)

        # 4) rotate 90 deg about Z through an EXPLICIT origin centre. The rotation
        #    maps the X axis onto the Y axis: R*(1,0,0) ~= (0,1,0).
        r = executor.execute({"cmd": "rotate",
                              "params": {"target": box2_id, "angle": 90,
                                         "axis": "Z", "center": [0, 0, 0]}})
        assert r["ok"], f"rotate failed: {r}"
        v = box2.Placement.Rotation.multVec(FreeCAD.Vector(1, 0, 0))
        assert (_approx(v.x, 0) and _approx(v.y, 1) and _approx(v.z, 0)), \
            f"90deg about Z should map X->Y, got {v!r}"
        details["rotate_z90"] = (v.x, v.y, v.z)

        # 5) rotate about the DEFAULT centre (bbox centre) keeps that centre fixed:
        #    a pure spin in place. The box bbox centre (2,2,2) must map to itself.
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 4, "width": 4, "height": 4}})
        box3_id = r["created_ids"][0]
        box3 = doc.getObject(box3_id)
        r = executor.execute({"cmd": "rotate",
                              "params": {"target": box3_id, "angle": 90, "axis": "Z"}})
        assert r["ok"], f"rotate default-centre failed: {r}"
        centre = FreeCAD.Vector(2, 2, 2)
        mapped = box3.Placement.multVec(centre)
        assert (_approx(mapped.x, 2) and _approx(mapped.y, 2) and _approx(mapped.z, 2)), \
            f"rotation about bbox centre must keep centre fixed, got {mapped!r}"
        details["rotate_about_centre_fixed"] = (mapped.x, mapped.y, mapped.z)

        # 6) rotate with a missing angle -> blocked by validation upstream, but the
        #    executor must also refuse it directly (defence in depth).
        r = executor.execute({"cmd": "rotate", "params": {"target": box3_id}})
        assert not r["ok"], "rotate without angle should be refused"
        details["rotate_no_angle"] = "refused"

        # 7) rotate with a bad axis string -> graceful failure.
        r = executor.execute({"cmd": "rotate",
                              "params": {"target": box3_id, "angle": 30,
                                         "axis": "W"}})
        assert not r["ok"], "rotate with axis 'W' should be refused"
        details["rotate_bad_axis"] = "refused"

        # 8) move/rotate on a missing object -> graceful failure.
        r = executor.execute({"cmd": "move",
                              "params": {"target": "Ghost", "by": [1, 1, 1]}})
        assert not r["ok"] and "not found" in r["error"], \
            f"missing move target not handled: {r}"
        details["move_missing"] = "refused"

        return True, details
    finally:
        mock_freecad.uninstall()


def test_transform():
    ok, details = run_scenario()
    assert ok, f"transform execution failed: {details}"


if __name__ == "__main__":
    print("== test_transform: move/rotate through the real executor (mock FreeCAD) ==")
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
    print("PASS - move and rotate compose the Placement correctly and fail gracefully.")
    sys.exit(0)
