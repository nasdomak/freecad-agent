#!/usr/bin/env python3
"""
test_sketch_on_face.py - Phase 6 Group C: sketch_on_face + pocket, through the REAL
executor against a fake FreeCAD (tests/mock_freecad.py), WITHOUT FreeCAD (ADR 0014).

It proves a sketch can be attached to a resolved face of an existing body, then
extruded into a boss (op 'add') or sunk as a pocket (op 'cut', a Part::Cut against
the owner body), and that the face selector and graceful failures work.

Runnable:
    python tests/test_sketch_on_face.py
    pytest tests/test_sketch_on_face.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402


def run_scenario():
    mock_freecad.install()
    try:
        import ai_copilot.executor as executor
        import FreeCAD
        details = {}
        doc = FreeCAD.newDocument("T")

        # A box to build features on.
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 40, "width": 40, "height": 10}})
        assert r["ok"], f"create_box failed: {r}"
        box_id = r["created_ids"][0]

        # 1) sketch_on_face on the TOP face (resolved by the executor, not guessed).
        r = executor.execute({"cmd": "sketch_on_face",
                              "params": {"target": box_id, "where": "top",
                                         "shape": "rectangle", "width": 20,
                                         "height": 10}})
        assert r["ok"], f"sketch_on_face top failed: {r}"
        sketch_id = r["created_ids"][0]
        sketch = doc.getObject(sketch_id)
        # the sketch is attached to the box's top face (Face1 in the mock).
        sup = getattr(sketch, "AttachmentSupport", None)
        assert sup and sup[0][0].Name == box_id and sup[0][1] == ("Face1",), \
            f"sketch not attached to the top face: {sup!r}"
        assert sketch.MapMode == "FlatFace", "expected FlatFace map mode"
        details["sketch_on_face_top"] = (sketch_id, sup[0][1])

        # 2) extrude it (op add) into a boss -> solid; the sketch is hidden.
        r = executor.execute({"cmd": "extrude",
                              "params": {"target": sketch_id, "distance": 5}})
        assert r["ok"], f"extrude (add) failed: {r}"
        assert sketch.ViewObject.Visibility is False, "extrude must hide the sketch"
        details["extrude_add"] = r["created_ids"]

        # 3) sketch_on_face on the BOTTOM face -> resolves Face2 in the mock.
        r = executor.execute({"cmd": "sketch_on_face",
                              "params": {"target": box_id, "where": "bottom",
                                         "shape": "circle", "radius": 6}})
        assert r["ok"], f"sketch_on_face bottom failed: {r}"
        sketch2 = doc.getObject(r["created_ids"][0])
        assert sketch2.AttachmentSupport[0][1] == ("Face2",), \
            f"bottom face should resolve to Face2: {sketch2.AttachmentSupport!r}"
        details["sketch_on_face_bottom"] = sketch2.AttachmentSupport[0][1]

        # 4) POCKET: a sketch on the top face, extruded with op 'cut' -> a Part::Cut
        #    against the owner body (material removed).
        r = executor.execute({"cmd": "sketch_on_face",
                              "params": {"target": box_id, "where": "top",
                                         "shape": "circle", "radius": 6}})
        assert r["ok"], f"sketch_on_face for pocket failed: {r}"
        pocket_sketch = r["created_ids"][0]
        r = executor.execute({"cmd": "extrude",
                              "params": {"target": pocket_sketch, "distance": 4,
                                         "op": "cut"}})
        assert r["ok"], f"pocket (extrude cut) failed: {r}"
        cut = doc.getObject(r["created_ids"][0])
        assert cut.TypeId == "Part::Cut", f"a pocket must be a Part::Cut, got {cut.TypeId}"
        assert cut.Base.Name == box_id, "the pocket must cut from the owner body"
        details["pocket"] = r["created_ids"]

        # 5) graceful failures.
        r = executor.execute({"cmd": "sketch_on_face",
                              "params": {"target": "Ghost", "where": "top",
                                         "shape": "circle", "radius": 3}})
        assert not r["ok"] and "not found" in r["error"], f"missing target: {r}"
        details["missing_target"] = "refused"

        # a pocket from a free-standing sketch (not on a face) is refused.
        r = executor.execute({"cmd": "create_sketch",
                              "params": {"shape": "circle", "radius": 3}})
        free_sketch = r["created_ids"][0]
        r = executor.execute({"cmd": "extrude",
                              "params": {"target": free_sketch, "distance": 4,
                                         "op": "cut"}})
        assert not r["ok"], "a pocket needs a sketch attached to a face"
        details["pocket_without_face"] = "refused"

        return True, details
    finally:
        mock_freecad.uninstall()


def test_sketch_on_face():
    ok, details = run_scenario()
    assert ok, f"sketch_on_face execution failed: {details}"


if __name__ == "__main__":
    print("== test_sketch_on_face: sketch on a face + pocket (mock FreeCAD) ==")
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
    print("PASS - sketch_on_face attaches to the right face; pocket removes material.")
    sys.exit(0)
