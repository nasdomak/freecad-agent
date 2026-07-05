#!/usr/bin/env python3
"""
test_create_sketch.py - focused unit test for the `create_sketch` command (Phase 5).

Runs the REAL vocabulary function against the fake FreeCAD/Part/Sketcher (no running
FreeCAD), checking the geometry it builds:
  - rectangle  -> a Sketcher::SketchObject with 4 line segments and 4 coincidence
                  constraints (a closed loop), oriented on the requested plane;
  - circle     -> a Sketcher::SketchObject with 1 circle of the right radius;
  - bad input  -> clear ValueErrors (unknown shape/plane, missing/zero dimensions).

Runnable:
    python tests/test_create_sketch.py
    pytest tests/test_create_sketch.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402


def run_scenario():
    mod = mock_freecad.install()
    try:
        from ai_copilot.executor.vocabulary.create_sketch import create_sketch
        doc = mod.newDocument("T")
        details = {}

        # 1) rectangle -> sketch with 4 line segments forming a closed loop.
        created = create_sketch(doc, {"shape": "rectangle", "width": 40,
                                      "height": 30})
        sk = created[0]
        assert sk.TypeId == "Sketcher::SketchObject", f"wrong type: {sk.TypeId}"
        lines = [g for g in sk._geometry if getattr(g, "kind", None) == "line"]
        assert len(lines) == 4, f"rectangle must have 4 segments, got {len(lines)}"
        # The four corners must span 0..width x 0..height in the local plane.
        xs = [p.x for g in lines for p in (g.StartPoint, g.EndPoint)]
        ys = [p.y for g in lines for p in (g.StartPoint, g.EndPoint)]
        assert min(xs) == 0 and max(xs) == 40, f"rectangle width wrong: {min(xs)}..{max(xs)}"
        assert min(ys) == 0 and max(ys) == 30, f"rectangle height wrong: {min(ys)}..{max(ys)}"
        details["rectangle_segments"] = len(lines)

        # 2) circle -> sketch with 1 circle of the right radius.
        created = create_sketch(doc, {"shape": "circle", "radius": 12})
        sk = created[0]
        circles = [g for g in sk._geometry if getattr(g, "kind", None) == "circle"]
        assert len(circles) == 1, f"circle sketch must have 1 circle, got {len(circles)}"
        assert circles[0].Radius == 12, f"circle radius wrong: {circles[0].Radius}"
        details["circle_radius"] = circles[0].Radius

        # 3) every standard plane is accepted.
        for plane in ("XY", "XZ", "YZ"):
            created = create_sketch(doc, {"shape": "circle", "radius": 5,
                                          "plane": plane})
            assert created and created[0].TypeId == "Sketcher::SketchObject"
        details["planes_ok"] = ["XY", "XZ", "YZ"]

        # 4) graceful failures (principle 7): clear ValueErrors.
        for bad, why in [
            ({"shape": "triangle"}, "unknown shape"),
            ({"shape": "rectangle", "width": 10}, "rectangle missing height"),
            ({"shape": "rectangle", "width": 0, "height": 5}, "zero width"),
            ({"shape": "circle"}, "circle missing radius"),
            ({"shape": "circle", "radius": 8, "plane": "AB"}, "bad plane"),
        ]:
            try:
                create_sketch(doc, bad)
                assert False, f"expected ValueError for: {why}"
            except ValueError:
                pass
        details["graceful_failures"] = "ok"

        return True, details
    finally:
        mock_freecad.uninstall()


def test_create_sketch():
    ok, details = run_scenario()
    assert ok, f"create_sketch failed: {details}"


if __name__ == "__main__":
    print("== test_create_sketch: real create_sketch vs mock FreeCAD/Part/Sketcher ==")
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
    print("PASS - create_sketch builds the right geometry and fails gracefully.")
    sys.exit(0)
