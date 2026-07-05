#!/usr/bin/env python3
"""
test_edge_selection.py - unit test for the executor-side edge selector (ADR 0006).

select_edge_indices() lets fillet/chamfer pick edges from the real geometry so a
small local model never has to enumerate Edge1..EdgeN. Here we feed it the 12
edges of a unit-ish box (via the mock) and check each selector returns the right
group: all=12, top/bottom=4, vertical=4, horizontal=8.

Runnable:
    python tests/test_edge_selection.py
    pytest tests/test_edge_selection.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402


def _box_shape(L=30.0, W=20.0, H=10.0):
    """A toy box shape with 12 real-ish edges (from the mock)."""
    return mock_freecad.Shape(
        6, 12, 8,
        mock_freecad.BoundBox(0, 0, 0, L, W, H),
        edge_objs=mock_freecad._box_edges(L, W, H),
    )


def run_scenario():
    from ai_copilot.executor.vocabulary._common import select_edge_indices
    shape = _box_shape()
    out = {}

    allv = select_edge_indices(shape, "all")
    assert allv == list(range(1, 13)), f"all should be 12 edges: {allv}"
    out["all"] = allv

    default = select_edge_indices(shape)  # default == all
    assert default == allv, f"default selector should equal 'all': {default}"

    top = select_edge_indices(shape, "top")
    assert len(top) == 4, f"top should be 4 edges: {top}"
    out["top"] = top

    bottom = select_edge_indices(shape, "bottom")
    assert len(bottom) == 4, f"bottom should be 4 edges: {bottom}"
    out["bottom"] = bottom

    vertical = select_edge_indices(shape, "vertical")
    assert len(vertical) == 4, f"vertical should be 4 edges: {vertical}"
    out["vertical"] = vertical

    horizontal = select_edge_indices(shape, "horizontal")
    assert len(horizontal) == 8, f"horizontal should be 8 edges: {horizontal}"
    out["horizontal"] = horizontal

    # top, bottom and vertical must be disjoint and together cover all 12 edges.
    assert sorted(top + bottom + vertical) == allv, "groups must partition all edges"
    # horizontal must be exactly top + bottom.
    assert sorted(horizontal) == sorted(top + bottom), "horizontal == top + bottom"

    # An unknown selector is refused clearly (principle 7).
    try:
        select_edge_indices(shape, "diagonal")
        raise AssertionError("unknown selector should raise")
    except ValueError:
        out["unknown_selector"] = "refused"

    return True, out


def test_edge_selection():
    mock_freecad.install()
    try:
        ok, _ = run_scenario()
        assert ok
    finally:
        mock_freecad.uninstall()


if __name__ == "__main__":
    print("== test_edge_selection: executor-side edge selector (ADR 0006) ==")
    mock_freecad.install()
    try:
        ok, out = run_scenario()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    finally:
        mock_freecad.uninstall()
    for k, v in out.items():
        print(f"  [ok] {k}: {v}")
    print("PASS - the geometric edge selector groups edges correctly.")
    sys.exit(0)
