#!/usr/bin/env python3
"""
test_idchain.py - generalized id-chaining in the engine (ADR 0013).

ADR 0010 made an extrude consume the sketch the preceding create_sketch produced.
ADR 0013 generalizes that to any "create X, then operate on X" plan: the engine
tracks the last object the plan created and rewrites a later step's object
reference when that reference does not exist yet (not in the document at plan start
nor among the ids created so far). This unit-tests the pure helpers that implement
it, with NO FreeCAD and NO model.

Runnable:
    python tests/test_idchain.py
    pytest tests/test_idchain.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))


def run_scenario():
    from bridge_server import Session
    out = {}

    # _known_ids reads the document overview gathered at plan start.
    overview = {"objects": [{"id": "Box"}, {"id": "Cylinder"}]}
    known = Session._known_ids(overview)
    assert known == {"Box", "Cylinder"}, known
    assert Session._known_ids(None) == set()
    out["known_ids"] = sorted(known)

    # _detail_candidates (Session 13 fix): only VISIBLE objects get a geometric
    # close-up in the prompt; hidden ones (consumed bases, drill tools, used
    # sketches) are noise that bloats a small model's context.
    objs = [{"id": "Drilled", "visible": True},
            {"id": "Cylinder", "visible": False},   # consumed base -> skipped
            {"id": "DrillTool", "visible": False},  # tool -> skipped
            {"id": "Legacy"},                        # no flag -> kept (lenient)
            {"visible": True}]                       # no id -> skipped
    cands = [o["id"] for o in Session._detail_candidates(objs)]
    assert cands == ["Drilled", "Legacy"], cands
    assert Session._detail_candidates(None) == []
    out["detail_candidates"] = cands

    # Consumed-target chaining (ADR 0016): the flange stress test. One plan,
    # four drills all naming "Cylinder"; each drill consumes its target, so the
    # later ones must be redirected to the live result (transitively).
    replaced = {}
    drill = {"type": "command", "cmd": "drill_hole",
             "params": {"target": "Cylinder", "diameter": 8, "depth": 12}}
    # drill #1 targets the real Cylinder: nothing to rewrite yet.
    assert Session._rewrite_consumed(drill, replaced) is drill
    replaced = Session._record_consumed(
        drill, {"ok": True, "created_ids": ["Drilled"]}, replaced)
    assert replaced == {"Cylinder": "Drilled"}, replaced
    # drill #2 still says "Cylinder" -> redirected to Drilled.
    d2 = Session._rewrite_consumed(drill, replaced)
    assert d2 is not drill and d2["params"]["target"] == "Drilled", d2
    assert drill["params"]["target"] == "Cylinder"  # input not mutated
    replaced = Session._record_consumed(
        d2, {"ok": True, "created_ids": ["Drilled001"]}, replaced)
    # drill #3: the chain Cylinder -> Drilled -> Drilled001 resolves fully.
    d3 = Session._rewrite_consumed(drill, replaced)
    assert d3["params"]["target"] == "Drilled001", d3
    assert Session._follow_replacements("Cylinder", replaced) == "Drilled001"
    # a FAILED action must record nothing; unknown commands consume nothing.
    assert Session._record_consumed(drill, {"ok": False}, replaced) == replaced
    move = {"type": "command", "cmd": "move", "params": {"target": "X", "by": [1, 0, 0]}}
    assert Session._record_consumed(
        move, {"ok": True, "created_ids": ["Y"]}, replaced) == replaced
    # boolean consumes BOTH operands.
    both = Session._record_consumed(
        {"type": "command", "cmd": "boolean",
         "params": {"op": "union", "a": "Box", "b": "Box_copy"}},
        {"ok": True, "created_ids": ["Union"]}, {})
    assert both == {"Box": "Union", "Box_copy": "Union"}, both
    out["consumed_chaining"] = "redirects dead references to the live result"

    # _update_created remembers the first created id and grows the known set.
    last, known2 = Session._update_created(None, known,
                                           {"ok": True, "created_ids": ["Box001"]})
    assert last == "Box001" and "Box001" in known2, (last, known2)
    # a failed action must NOT advance anything.
    last3, known3 = Session._update_created("Box001", known2, {"ok": False})
    assert last3 == "Box001" and known3 == known2
    out["update_created"] = "tracks last id + grows known set"

    # 1) "create a box, then mirror it" where the box was auto-renamed Box001 but
    #    the model still says target='Box': Box is NOT in known_ids -> rewrite.
    known_after_box = {"Box001"}
    mirror = {"type": "command", "cmd": "mirror",
              "params": {"target": "Box", "plane": "YZ"}}
    new, changed = Session._rewrite_refs(mirror, "Box001", known_after_box)
    assert changed == ["target"] and new["params"]["target"] == "Box001", new
    # the input action is NOT mutated.
    assert mirror["params"]["target"] == "Box", "input must not be mutated"
    out["mirror_placeholder_rewritten"] = "Box -> Box001"

    # 2) a reference that DOES resolve is left alone (no needless churn).
    array_ok = {"type": "command", "cmd": "array",
                "params": {"target": "Box001", "pattern": "linear",
                           "count": 3, "spacing": 10}}
    _, changed = Session._rewrite_refs(array_ok, "Box001", known_after_box)
    assert not changed, "a resolvable reference must be left alone"

    # 3) no object created yet -> nothing to chain onto.
    _, changed = Session._rewrite_refs(mirror, None, known_after_box)
    assert not changed

    # 4) a command without object references (create_box) is never touched.
    box = {"type": "command", "cmd": "create_box", "params": {"length": 10}}
    _, changed = Session._rewrite_refs(box, "Box001", known_after_box)
    assert not changed

    # 5) a boolean with BOTH operands unknown is too ambiguous to fix -> untouched;
    #    but a boolean with exactly ONE unknown operand gets that one rewritten.
    bool_both = {"type": "command", "cmd": "boolean",
                 "params": {"op": "difference", "a": "Foo", "b": "Bar"}}
    _, changed = Session._rewrite_refs(bool_both, "Box001", known_after_box)
    assert not changed, "two unknown operands must not be guessed"
    bool_one = {"type": "command", "cmd": "boolean",
                "params": {"op": "difference", "a": "Box001", "b": "Cyl"}}
    new, changed = Session._rewrite_refs(bool_one, "Box001", {"Box001"})
    # 'a' resolves, 'b' does not -> exactly one unresolved -> rewrite 'b'.
    assert changed == ["b"] and new["params"]["b"] == "Box001", new
    out["boolean"] = "one unknown rewritten, two unknown left alone"

    # 6) sketch_on_face now also primes the sketch->extrude marker (ADR 0010 reuse).
    sof = {"type": "command", "cmd": "sketch_on_face",
           "params": {"target": "Box", "shape": "rectangle"}}
    assert Session._next_profile_id(None, sof,
                                    {"ok": True, "created_ids": ["Sketch001"]}) == "Sketch001"
    extrude = {"type": "command", "cmd": "extrude", "params": {"target": "Sketch"}}
    assert Session._next_profile_id("Sketch001", extrude, {"ok": True}) is None
    out["sketch_on_face_chaining"] = "primes the extrude marker like create_sketch"

    return True, out


def test_idchain():
    ok, _ = run_scenario()
    assert ok


if __name__ == "__main__":
    print("== test_idchain: generalized id chaining (ADR 0013) ==")
    try:
        ok, out = run_scenario()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    for k, v in out.items():
        print(f"  [ok] {k}: {v}")
    print("PASS - the engine chains a later step onto the object it just created.")
    sys.exit(0)
