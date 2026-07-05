#!/usr/bin/env python3
"""
test_brain.py - the real planning brain (engine/brain.py) WITHOUT Ollama.

We inject a fake "chat" function in place of the local model, so we can test the
brain's logic deterministically: it builds a prompt from the vocabulary, parses
the model's JSON, validates command actions (dropping invalid ones), keeps python
actions, surfaces a clarification, and repairs a failed action.

Runnable:
    python tests/test_brain.py
    pytest tests/test_brain.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

import brain as brain_mod  # noqa: E402
import fake_brain          # noqa: E402


def run_scenario():
    cat = fake_brain.Catalog()
    details = {}

    # 1) The system prompt is GENERATED from the vocabulary (principle 5).
    def capture_chat(system, user):
        capture_chat.system = system
        capture_chat.user = user
        return {"actions": [
            {"type": "command", "cmd": "create_box",
             "params": {"length": 20, "width": 15, "height": 10}},
            {"type": "command", "cmd": "drill_hole",
             "params": {"target": "Box", "diameter": 5, "depth": 10}},
            {"type": "command", "cmd": "create_box", "params": {"length": -1}},  # invalid
            {"type": "python", "code": "doc.addObject('Part::Sphere','S')",
             "reason": "no sphere command yet"},
        ]}

    b = brain_mod.Brain(catalog=cat, chat=capture_chat)
    # Phase 3: pass geometric detail (objectDetail) and check it reaches the prompt.
    box_detail = {
        "id": "Box", "type": "Part::Box", "label": "Box",
        "dimensions": {"Length": 20.0, "Width": 15.0, "Height": 10.0},
        "bounding_box": {"min": [0, 0, 0], "max": [20, 15, 10]},
        "named_subelements": [
            {"ref": "Face1", "kind": "face", "hint": "top face"},
            {"ref": "Edge1", "kind": "edge", "hint": ""},
            {"ref": "Edge7", "kind": "edge", "hint": ""},
        ],
    }
    plan = b.plan("make a box with a hole and a sphere",
                  overview={"document_name": "Doc", "object_count": 1,
                            "objects": [{"id": "Box", "type": "Part::Box"}]},
                  details=[box_detail])
    for cmd in ("create_box", "drill_hole", "chamfer", "boolean"):
        assert cmd in capture_chat.system, f"{cmd} missing from the system prompt"
    # Few-shot examples must be present to steer small models.
    assert "EXAMPLES" in capture_chat.system, "few-shot examples missing"
    # The geometric detail (Edge*/Face*) must be in the user prompt (RAG).
    assert "DETAILED GEOMETRY" in capture_chat.user, "detail block missing from prompt"
    assert "Edge7" in capture_chat.user and "top face" in capture_chat.user, \
        "named sub-elements/hints missing from the detail block"
    valid = plan["valid_actions"]
    assert len(valid) == 3, f"expected 3 valid actions, got {valid}"
    assert valid[0]["cmd"] == "create_box" and valid[1]["cmd"] == "drill_hole"
    assert valid[2]["type"] == "python"
    assert any("dropped" in n for n in plan["notes"]), plan["notes"]
    details["plan"] = [a.get("cmd", a.get("type")) for a in valid]

    # 2) Clarification path: empty actions + a clarification message.
    def clarify_chat(system, user):
        return {"actions": [], "clarification": "Which dimensions for the box?"}

    b2 = brain_mod.Brain(catalog=cat, chat=clarify_chat)
    p2 = b2.plan("make a box")
    assert p2["valid_actions"] == [] and p2["clarification"], p2
    details["clarification"] = p2["clarification"]

    # 3) Unparseable / wrong shape -> PlanError.
    def broken_chat(system, user):
        return {"not_actions": 1}
    b3 = brain_mod.Brain(catalog=cat, chat=broken_chat)
    p3 = b3.plan("whatever")
    assert p3["valid_actions"] == [], p3  # 'actions' missing -> treated as empty list?
    # (the model returned a dict without 'actions'; normalize treats it as empty)

    # 4) Repair: feed back an execution error, get a corrected single action.
    def repair_chat(system, user):
        assert "FreeCAD error" in user, "repair prompt should include the error"
        return {"actions": [{"type": "command", "cmd": "create_cylinder",
                             "params": {"radius": 3, "height": 6}}]}
    b4 = brain_mod.Brain(catalog=cat, chat=repair_chat)
    fixed = b4.repair("make a peg",
                      {"type": "command", "cmd": "create_cylinder", "params": {"radius": -1}},
                      "radius must be > 0")
    assert fixed and fixed["cmd"] == "create_cylinder" and fixed["params"]["radius"] == 3, fixed
    details["repair"] = fixed

    return True, details


def test_brain():
    ok, details = run_scenario()
    assert ok, f"brain scenario failed: {details}"


if __name__ == "__main__":
    print("== test_brain: NL -> validated plan, clarification, repair (no Ollama) ==")
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
    print("PASS - the brain plans, validates, clarifies and self-corrects.")
    sys.exit(0)
