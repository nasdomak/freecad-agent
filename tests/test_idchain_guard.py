#!/usr/bin/env python3
"""
test_idchain_guard.py - the id-chaining guard in the engine loop (ADR 0013).

Regression test for the Session-11 bug Marco caught: in a multi-step plan
(box -> boss -> pocket), the generic id-chaining rewrote the pocket's target to
"the last created object" (the boss) when the model used a name that did not
resolve, so the pocket cut the boss instead of the base box.

The fix: the generic rewrite only fires while the plan has created EXACTLY ONE
object (the unambiguous "create one thing, then operate on it" idiom). With several
creations, an unresolved reference is left alone and fails/self-corrects instead of
silently pointing at the wrong body.

This drives Session.on_user_prompt with a fake peer + fake brain (no FreeCAD, no
model) and checks the target the engine actually sends to command.execute.

Runnable:
    python tests/test_idchain_guard.py
    pytest tests/test_idchain_guard.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))


class _FakePeer:
    """Records command.execute calls; returns a created id per create command."""
    def __init__(self):
        self.calls = []

    def call(self, method, params, timeout=None):
        if method == "perception.overview":
            return {"document_name": "T", "object_count": 0, "objects": []}
        if method == "perception.detail":
            return {}
        if method == "command.execute":
            self.calls.append(params)
            cmd = params.get("cmd")
            # Hand back a created id for the creating commands so the engine's
            # created_count / last_created tracking advances.
            created = {"create_box": ["Box"], "create_cylinder": ["Cylinder"],
                       "mirror": ["Mirror"], "sketch_on_face": ["Sketch"],
                       "extrude": ["Extrude"]}.get(cmd, [])
            return {"ok": True, "transaction_id": "tx", "created_ids": created}
        return {"ok": True}

    def notify(self, *a, **k):
        pass


class _FakeBrain:
    def __init__(self, plan):
        self._plan = plan

    def availability(self):
        return {"available": True, "model": "fake"}

    def plan(self, text, overview=None, details=None):
        return {"valid_actions": self._plan, "notes": [], "clarification": None}

    def repair(self, *a, **k):
        return None


def _targets_for(plan, cmd):
    import fake_brain
    from bridge_server import Session
    peer = _FakePeer()
    session = Session(peer, "tok", fake_brain.Catalog(), brain=_FakeBrain(plan))
    session.on_user_prompt({"text": "go"})
    return [c["params"].get("target") for c in peer.calls if c.get("cmd") == cmd]


def run_scenario():
    out = {}

    # A) MULTI-create plan: box -> boss(sketch_on_face+extrude) -> pocket sketch on
    #    a NON-resolvable name. The guard must NOT rewrite it to the boss; the
    #    target stays as the model wrote it (so a real mistake fails/self-corrects).
    multi = [
        {"type": "command", "cmd": "create_box",
         "params": {"length": 60, "width": 60, "height": 10}},
        {"type": "command", "cmd": "sketch_on_face",
         "params": {"target": "Box", "where": "top", "shape": "rectangle",
                    "width": 20, "height": 20}},
        {"type": "command", "cmd": "extrude",
         "params": {"target": "Sketch", "distance": 8}},
        {"type": "command", "cmd": "sketch_on_face",
         "params": {"target": "the_base_plate", "where": "top",  # unresolvable name
                    "shape": "circle", "radius": 8}},
    ]
    sof_targets = _targets_for(multi, "sketch_on_face")
    # the boss sketch keeps "Box"; the pocket sketch keeps its (wrong) name - it must
    # NOT have been rewritten to the boss/last-created object.
    assert sof_targets[0] == "Box", sof_targets
    assert sof_targets[1] == "the_base_plate", \
        f"guard failed: pocket target was rewritten to {sof_targets[1]!r}"
    out["multi_create_not_chained"] = sof_targets

    # B) SINGLE-create plan: box -> mirror with a non-resolvable name. Here chaining
    #    SHOULD help: exactly one object was created, so the reference is rewritten
    #    to it.
    single = [
        {"type": "command", "cmd": "create_box",
         "params": {"length": 10, "width": 10, "height": 10}},
        {"type": "command", "cmd": "mirror",
         "params": {"target": "the_box", "plane": "YZ"}},  # unresolvable -> Box
    ]
    mir_targets = _targets_for(single, "mirror")
    assert mir_targets == ["Box"], \
        f"single-create chaining should rewrite to Box, got {mir_targets}"
    out["single_create_chained"] = mir_targets

    return True, out


def test_idchain_guard():
    ok, _ = run_scenario()
    assert ok


if __name__ == "__main__":
    print("== test_idchain_guard: chaining only when unambiguous (ADR 0013) ==")
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
    print("PASS - the engine chains onto a just-made object only when unambiguous.")
    sys.exit(0)
