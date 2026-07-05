#!/usr/bin/env python3
"""
test_validation.py - test the "fake brain" (engine/fake_brain) WITHOUT FreeCAD.

Checks that validating structured commands against shared/commands.schema.json
accepts valid input and gracefully rejects wrong input (principle 7). No sockets,
no FreeCAD: pure logic.

Runnable two ways:
    python tests/test_validation.py        # prints PASS/FAIL and exits 0/1
    pytest tests/test_validation.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

import fake_brain  # noqa: E402


def _blocking(invocation, catalog):
    """True if the invocation is REJECTED (at least one blocking error)."""
    return fake_brain.is_blocking(fake_brain.validate_invocation(invocation, catalog))


def run_scenario():
    cat = fake_brain.Catalog()
    details = {}

    # The catalog loads and contains the expected commands.
    names = cat.names()
    assert "create_box" in names, f"create_box missing from the catalog: {names}"
    assert "create_cylinder" in names, f"create_cylinder missing: {names}"
    details["catalog"] = names

    # 1) valid create_box -> accepted
    ok_box = {"cmd": "create_box", "params": {"length": 20, "width": 15, "height": 10}}
    assert not _blocking(ok_box, cat), "valid create_box wrongly rejected"
    details["box_valid"] = "accepted"

    # 2) create_box with a valid optional placement -> accepted
    ok_box2 = {"cmd": "create_box",
               "params": {"length": 5, "width": 5, "height": 5, "placement": [1, 2, 3]}}
    assert not _blocking(ok_box2, cat), "create_box with placement rejected"

    # 3) missing a required field (height) -> rejected
    assert _blocking({"cmd": "create_box", "params": {"length": 20, "width": 15}}, cat), \
        "missing 'height' not detected"
    details["missing_required"] = "rejected"

    # 4) wrong type (length as string) -> rejected
    assert _blocking({"cmd": "create_box", "params": {"length": "twenty", "width": 1, "height": 1}}, cat), \
        "wrong type not detected"
    details["wrong_type"] = "rejected"

    # 5) minimum violated (negative length) -> rejected
    assert _blocking({"cmd": "create_box", "params": {"length": -3, "width": 1, "height": 1}}, cat), \
        "minimum (>=0) not enforced"
    details["minimum_violated"] = "rejected"

    # 6) unknown command -> rejected
    assert _blocking({"cmd": "teleport", "params": {}}, cat), \
        "unknown command not rejected"
    details["unknown_command"] = "rejected"

    # 7) valid create_cylinder -> accepted
    assert not _blocking({"cmd": "create_cylinder", "params": {"radius": 5, "height": 12}}, cat), \
        "valid create_cylinder rejected"
    details["cylinder_valid"] = "accepted"

    # 8) enum: boolean with a non-allowed op -> rejected
    assert _blocking({"cmd": "boolean", "params": {"op": "merge", "a": "X", "b": "Y"}}, cat), \
        "enum 'op' not enforced"
    # ...and with a valid op -> accepted
    assert not _blocking({"cmd": "boolean", "params": {"op": "union", "a": "X", "b": "Y"}}, cat), \
        "valid boolean rejected"
    details["enum"] = "enforced"

    # 9) extra parameter -> WARNING, non-blocking (accepted)
    extra = {"cmd": "create_box", "params": {"length": 1, "width": 1, "height": 1, "color": "red"}}
    errs = fake_brain.validate_invocation(extra, cat)
    assert errs and not fake_brain.is_blocking(errs), \
        "the extra parameter should be a non-blocking warning"
    details["extra_parameter"] = "non-blocking warning"

    return True, details


def test_validation():
    ok, details = run_scenario()
    assert ok, f"validation scenario failed: {details}"


if __name__ == "__main__":
    print("== test_validation: the fake brain validates commands (without FreeCAD) ==")
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
    print("PASS - validation: accepts the valid ones, gracefully rejects the invalid ones.")
    sys.exit(0)
