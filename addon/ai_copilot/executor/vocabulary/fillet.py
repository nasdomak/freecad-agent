"""
executor/vocabulary/fillet.py - implementation of the `fillet` command.

Command definition: shared/commands.schema.json -> catalog.fillet
  params: target (id), radius. Units: mm.
  edge selection (one of):
    - where (str): "all" (default) / "top" / "bottom" / "vertical" / "horizontal"
                   -> the executor resolves the real edges itself (ADR 0006);
    - edges (list of edge ids, e.g. "Edge3"): explicit list (backward compatible).

Creates a Part::Fillet that rounds the chosen edges of the target. FreeCAD's
Fillet.Edges takes a list of (edge_index, radius1, radius2) tuples; we apply a
constant-radius fillet. Parametric and reversible.

WHY executor-side selection (ADR 0006): asking a small local model to enumerate
Edge1..Edge12 correctly is the most fragile output it produces. Letting the
executor pick the edges from the real geometry (principle 7: perceive, don't
guess) makes "round all the edges" reliable. The model just sends target+radius.
"""

from __future__ import annotations

from typing import List

from ._common import (
    resolve_object, parse_edge_indices, select_edge_indices, hide_object,
)


def fillet(doc, params: dict) -> List:
    """Apply a fillet (rounding) to the chosen edges of an existing body."""
    target = resolve_object(doc, params["target"])
    radius = float(params["radius"])
    if radius <= 0:
        raise ValueError("fillet radius must be > 0")

    indices = _resolve_edges(target, params)

    feat = doc.addObject("Part::Fillet", "Fillet")
    feat.Base = target
    # Constant-radius fillet: (edge index, radius, radius).
    feat.Edges = [(i, radius, radius) for i in indices]
    # The fillet replaces the base visually: hide the original so its sharp edges
    # don't show through the rounded result (see hide_object).
    hide_object(target)
    return [feat]


def _resolve_edges(target, params: dict) -> List[int]:
    """
    Decide which edges to round. Explicit `edges` win (backward compatible);
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
