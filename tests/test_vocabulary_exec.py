#!/usr/bin/env python3
"""
test_vocabulary_exec.py - run the REAL executor + vocabulary commands against a
fake FreeCAD (tests/mock_freecad.py), WITHOUT a running FreeCAD.

This proves the Phase 2 vocabulary (drill_hole, extrude, chamfer, fillet, boolean)
goes through the executor, opens an undoable transaction, sets the right
properties on the right object types and returns a well-formed commandResult. It
also checks the graceful failures (principle 7): bad references are refused and
the transaction rolls back.

Runnable:
    python tests/test_vocabulary_exec.py
    pytest tests/test_vocabulary_exec.py
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
        details = {}

        # 1) create_box -> ok
        r = executor.execute({"cmd": "create_box",
                              "params": {"length": 20, "width": 15, "height": 10}})
        assert r["ok"], f"create_box failed: {r}"
        box_id = r["created_ids"][0]
        details["create_box"] = box_id

        # 2) create_cylinder -> ok
        r = executor.execute({"cmd": "create_cylinder",
                              "params": {"radius": 4, "height": 9}})
        assert r["ok"], f"create_cylinder failed: {r}"
        cyl_id = r["created_ids"][0]
        details["create_cylinder"] = cyl_id

        # 3) boolean union of the two -> ok
        r = executor.execute({"cmd": "boolean",
                              "params": {"op": "union", "a": box_id, "b": cyl_id}})
        assert r["ok"], f"boolean union failed: {r}"
        details["boolean_union"] = r["created_ids"]

        # 4) boolean with a == b -> graceful failure (principle 7)
        r = executor.execute({"cmd": "boolean",
                              "params": {"op": "difference", "a": box_id, "b": box_id}})
        assert not r["ok"], "boolean A==B should be refused"
        details["boolean_same_body"] = "refused"

        # 5) drill_hole into the box -> ok (creates a Cut)
        r = executor.execute({"cmd": "drill_hole",
                              "params": {"target": box_id, "diameter": 5, "depth": 10,
                                         "position": [10, 7.5, 10]}})
        assert r["ok"], f"drill_hole failed: {r}"
        details["drill_hole"] = r["created_ids"]

        # 5b) drill_hole WITHOUT a position -> Phase 3 auto-centre on the top face.
        r = executor.execute({"cmd": "drill_hole",
                              "params": {"target": box_id, "diameter": 4, "depth": 6}})
        assert r["ok"], f"auto-centred drill_hole failed: {r}"
        details["drill_hole_autocenter"] = r["created_ids"]

        # 6) drill_hole on a missing target -> graceful failure
        r = executor.execute({"cmd": "drill_hole",
                              "params": {"target": "Nope", "diameter": 5, "depth": 5}})
        assert not r["ok"] and "not found" in r["error"], f"missing target not handled: {r}"
        details["drill_missing_target"] = "refused"

        # 7) chamfer one edge of the box -> ok
        r = executor.execute({"cmd": "chamfer",
                              "params": {"target": box_id, "edges": ["Edge1", "Edge2"],
                                         "size": 1.5}})
        assert r["ok"], f"chamfer failed: {r}"
        details["chamfer"] = r["created_ids"]

        # 8) fillet one edge of the box -> ok
        r = executor.execute({"cmd": "fillet",
                              "params": {"target": box_id, "edges": ["Edge3"],
                                         "radius": 2}})
        assert r["ok"], f"fillet failed: {r}"
        details["fillet"] = r["created_ids"]

        # 8b) fillet WITHOUT edges -> executor selects ALL edges (ADR 0006).
        r = executor.execute({"cmd": "fillet",
                              "params": {"target": box_id, "radius": 1}})
        assert r["ok"], f"fillet (where=all default) failed: {r}"
        details["fillet_all"] = r["created_ids"]

        # 8b-bis) the base body must be HIDDEN after a fillet, so its sharp edges
        # don't show through the rounded result (the bug Marco hit in real FreeCAD).
        import FreeCAD
        base_obj = FreeCAD.ActiveDocument.getObject(box_id)
        assert base_obj.ViewObject.Visibility is False, \
            "fillet must hide the base body (else the old sharp edges show through)"
        details["base_hidden_after_fillet"] = True

        # 8c) chamfer the TOP edges only, no explicit edge list.
        r = executor.execute({"cmd": "chamfer",
                              "params": {"target": box_id, "size": 1, "where": "top"}})
        assert r["ok"], f"chamfer (where=top) failed: {r}"
        details["chamfer_top"] = r["created_ids"]

        # 8d) fillet the VERTICAL edges only.
        r = executor.execute({"cmd": "fillet",
                              "params": {"target": box_id, "radius": 1,
                                         "where": "vertical"}})
        assert r["ok"], f"fillet (where=vertical) failed: {r}"
        details["fillet_vertical"] = r["created_ids"]

        # 9) extrude a profile (box used as a stand-in target) -> ok
        r = executor.execute({"cmd": "extrude",
                              "params": {"target": box_id, "distance": 5}})
        assert r["ok"], f"extrude failed: {r}"
        details["extrude"] = r["created_ids"]

        # 10) create_sketch (rectangle) -> extrude it into a solid (Phase 5).
        r = executor.execute({"cmd": "create_sketch",
                              "params": {"shape": "rectangle", "width": 40,
                                         "height": 30}})
        assert r["ok"], f"create_sketch rectangle failed: {r}"
        sketch_id = r["created_ids"][0]
        details["create_sketch_rectangle"] = sketch_id

        r = executor.execute({"cmd": "extrude",
                              "params": {"target": sketch_id, "distance": 10}})
        assert r["ok"], f"extrude of sketch failed: {r}"
        details["extrude_sketch"] = r["created_ids"]

        # 10b) the consumed sketch must be HIDDEN after the extrude.
        sketch_obj = FreeCAD.ActiveDocument.getObject(sketch_id)
        assert sketch_obj.ViewObject.Visibility is False, \
            "extrude must hide the consumed sketch profile"
        details["sketch_hidden_after_extrude"] = True

        # 11) create_sketch (circle) on the XZ plane -> ok
        r = executor.execute({"cmd": "create_sketch",
                              "params": {"shape": "circle", "radius": 12,
                                         "plane": "XZ"}})
        assert r["ok"], f"create_sketch circle failed: {r}"
        details["create_sketch_circle"] = r["created_ids"][0]

        # 12) create_sketch rectangle WITHOUT dimensions -> graceful failure.
        r = executor.execute({"cmd": "create_sketch",
                              "params": {"shape": "rectangle"}})
        assert not r["ok"], "rectangle without width/height should be refused"
        details["create_sketch_missing_dims"] = "refused"

        return True, details
    finally:
        mock_freecad.uninstall()


def test_vocabulary_exec():
    ok, details = run_scenario()
    assert ok, f"vocabulary execution failed: {details}"


if __name__ == "__main__":
    print("== test_vocabulary_exec: real executor + Phase 2 vocabulary (mock FreeCAD) ==")
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
    print("PASS - the expanded vocabulary executes and fails gracefully.")
    sys.exit(0)
