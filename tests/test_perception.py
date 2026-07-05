#!/usr/bin/env python3
"""
test_perception.py - the add-on's "eyes" over a fake document (no FreeCAD).

Checks that perception.overview produces a concise documentOverview and that
perception.detail produces an objectDetail with topology counts and referenceable
sub-elements (Face*/Edge*), per shared/context.schema.json.

Runnable:
    python tests/test_perception.py
    pytest tests/test_perception.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402


def run_scenario():
    from ai_copilot import perception  # no FreeCAD import needed when doc is passed
    details = {}

    # Build a fake document with a box and a cylinder.
    doc = mock_freecad.Document("Part")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 20, 15, 10
    cyl = doc.addObject("Part::Cylinder", "Cylinder")
    cyl.Radius, cyl.Height = 4, 9
    doc.recompute()

    # 1) overview: concise, one line per object, with a bounding box.
    ov = perception.overview(doc)
    assert ov["object_count"] == 2, ov
    ids = {o["id"] for o in ov["objects"]}
    assert {"Box", "Cylinder"} <= ids, ids
    assert ov["bounding_box"].get("max"), "overview should expose a bounding box"
    details["overview"] = ov

    # 2) detail of the box: dimensions + topology + named sub-elements.
    d = perception.detail("Box", doc)
    assert d["type"] == "Part::Box", d
    assert d["dimensions"] == {"Length": 20.0, "Width": 15.0, "Height": 10.0}, d["dimensions"]
    assert d["topology"]["faces"] == 6 and d["topology"]["edges"] == 12, d["topology"]
    refs = {s["ref"] for s in d["named_subelements"]}
    assert "Face1" in refs and "Edge1" in refs, refs
    assert any(s.get("hint") == "top face" for s in d["named_subelements"]), \
        "expected a 'top face' hint"
    details["detail"] = d

    # 3) detail of a missing object -> graceful error, no crash.
    miss = perception.detail("Ghost", doc)
    assert "error" in miss, miss
    details["missing"] = "handled"

    return True, details


def test_perception():
    ok, details = run_scenario()
    assert ok, f"perception failed: {details}"


if __name__ == "__main__":
    print("== test_perception: document overview + detail (mock FreeCAD) ==")
    try:
        ok, details = run_scenario()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    print("  [ok] overview objects:", [o["id"] for o in details["overview"]["objects"]])
    print("  [ok] box dimensions:", details["detail"]["dimensions"])
    print("PASS - perception describes the document concisely.")
    sys.exit(0)
