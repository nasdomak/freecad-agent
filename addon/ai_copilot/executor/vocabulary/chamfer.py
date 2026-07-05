"""
executor/vocabulary/chamfer.py - implementation of the `chamfer` command.

Command definition: shared/commands.schema.json -> catalog.chamfer
  params: target (id), size. Units: mm.
  edge selection (one of):
    - where (str): "all" (default) / "top" / "bottom" / "vertical" / "horizontal"
                   -> the executor resolves the real edges itself (ADR 0006);
    - edges (list of edge ids, e.g. "Edge3"): explicit list (backward compatible).

Creates a Part::Chamfer on the chosen edges of the target. FreeCAD's Chamfer.Edges
takes a list of (edge_index, size1, size2) tuples; we apply an equal-sided chamfer
of `size`. The base object is consumed as a child of the chamfer (parametric,
reversible).

WHY executor-side selection (ADR 0006): see fillet.py. The model just sends
target+size; the executor picks the edges from the real geometry (principle 7).
"""

from __future__ import annotations

from typing import List

from ._common import (
    resolve_object, parse_edge_indices, select_edge_indices, hide_object,
)


def chamfer(doc, params: dict) -> List:
    """Apply a chamfer to the chosen edges of an existing body."""
    target = resolve_object(doc, params["target"])
    size = float(params["size"])
    if size <= 0:
        raise ValueError("chamfer size must be > 0")

    indices = _resolve_edges(target, params)

    feat = doc.addObject("Part::Chamfer", "Chamfer")
    feat.Base = target
    # Equal-sided chamfer: (edge index, size, size).
    feat.Edges = [(i, size, size) for i in indices]
    # The chamfer replaces the base visually: hide the original so its sharp
    # edges don't show through the bevelled result (see hide_object).
    hide_object(target)
    return [feat]


def _resolve_edges(target, params: dict) -> List[int]:
    """
    Decide which edges to chamfer. Explicit `edges` win (backward compatible);
    otherwise select them executor-side from `where` (default "all").
    """
    edges = params.get("edges")
    if edges:
        return parse_edge_indices(edges)
    shape = getattr(target, "Shape", None)
    if shape is None:
        raise ValueError(
            f"target '{getattr(target, 'Name', '?')}' has no shape yet; "
            "recompute the document first")
    return select_edge_indices(shape, params.get("where", "all"))
