#!/usr/bin/env python3
"""
test_extrude_link.py - sketch -> extrude id chaining in the engine (ADR 0010).

A small model cannot predict the auto-generated name of a sketch it is about to
create ('Sketch', then 'Sketch001', ...). When a plan does create_sketch then
extrude, the engine must rewrite the extrude's target to the id the create_sketch
actually produced, not the name the model guessed. This unit-tests the two pure
helpers that implement that, plus the executor-side "no solid -> clear error".

Runnable:
    python tests/test_extrude_link.py
    pytest tests/test_extrude_link.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))


def run_scenario():
    from bridge_server import Session
    out = {}

    extrude = {"type": "command", "cmd": "extrude",
               "params": {"target": "Sketch", "distance": 10}}

    # 1) A wrong, guessed target is rewritten to the real created id.
    new, changed = Session._rewrite_extrude_target(extrude, "Sketch001")
    assert changed and new["params"]["target"] == "Sketch001", new
    # the original action is NOT mutated.
    assert extrude["params"]["target"] == "Sketch", "input must not be mutated"
    out["rewrite_wrong_target"] = "Sketch -> Sketch001"

    # 2) No profile in flight -> left alone.
    _, changed = Session._rewrite_extrude_target(extrude, None)
    assert not changed
    # 3) Target already correct -> left alone (no needless churn).
    ok_extrude = {"type": "command", "cmd": "extrude",
                  "params": {"target": "Sketch001"}}
    _, changed = Session._rewrite_extrude_target(ok_extrude, "Sketch001")
    assert not changed
    # 4) Non-extrude action -> never touched.
    box = {"type": "command", "cmd": "create_box", "params": {"length": 1}}
    _, changed = Session._rewrite_extrude_target(box, "Sketch001")
    assert not changed
    out["leaves_alone"] = ["no_profile", "already_correct", "non_extrude"]

    # 5) _next_profile_id: create_sketch sets it, extrude clears it.
    sk = {"type": "command", "cmd": "create_sketch", "params": {"shape": "circle"}}
    assert Session._next_profile_id(None, sk,
                                    {"ok": True, "created_ids": ["Sketch001"]}) == "Sketch001"
    assert Session._next_profile_id("Sketch001", extrude, {"ok": True}) is None
    # a failed create_sketch must NOT advance the marker.
    assert Session._next_profile_id("X", sk, {"ok": False}) == "X"
    # an unrelated command leaves it unchanged.
    assert Session._next_profile_id("Sketch001", box, {"ok": True}) == "Sketch001"
    out["next_profile_id"] = "set on create_sketch, cleared on extrude"

    # 6) End-to-end of the helper pair: simulate "circle then extrude" when a
    #    sketch named 'Sketch' already exists, so the new one is 'Sketch001' but
    #    the model still says 'Sketch'. The extrude must end up on 'Sketch001'.
    profile = None
    profile = Session._next_profile_id(profile, sk,
                                       {"ok": True, "created_ids": ["Sketch001"]})
    linked, changed = Session._rewrite_extrude_target(extrude, profile)
    assert changed and linked["params"]["target"] == "Sketch001"
    out["end_to_end"] = "circle sketch correctly extruded"

    return True, out


def run_executor_no_solid():
    """The executor reports a clear error when an extrusion yields no solid."""
    import mock_freecad
    mod = mock_freecad.install()
    try:
        from ai_copilot.executor.vocabulary.extrude import extrude

        class _EmptyShape:
            Solids = []  # readable solid info, but empty -> must raise

        class _Sketch:
            Name = "Sketch"
            Label = "Sketch"
            ViewObject = type("V", (), {"Visibility": True})()

        class _Doc:
            def __init__(self):
                self._ext = type("E", (), {})()
            def getObject(self, name):
                return _Sketch() if name in ("Sketch", "Sketch001") else None
            Objects = []
            def addObject(self, type_id, name=""):
                return self._ext
            def recompute(self):
                self._ext.Shape = _EmptyShape()
                return 0

        doc = _Doc()
        try:
            extrude(doc, {"target": "Sketch", "distance": 10})
            return False, "expected ValueError for an empty extrusion"
        except ValueError as exc:
            assert "no solid" in str(exc), exc
            return True, "empty extrusion refused with a clear message"
    finally:
        mock_freecad.uninstall()


def test_extrude_link():
    ok, _ = run_scenario()
    assert ok
    ok, msg = run_executor_no_solid()
    assert ok, msg


if __name__ == "__main__":
    print("== test_extrude_link: sketch->extrude id chaining (ADR 0010) ==")
    try:
        ok, out = run_scenario()
        ok2, msg = run_executor_no_solid()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    for k, v in out.items():
        print(f"  [ok] {k}: {v}")
    print(f"  [ok] executor_no_solid: {msg}")
    print("PASS - the engine links the new sketch to the extrude and rejects empty solids.")
    sys.exit(0)
