"""
executor/vocabulary/boolean.py - implementation of the `boolean` command.

Command definition: shared/commands.schema.json -> catalog.boolean
  params: op (union|difference|intersection), a (id of body A), b (id of body B).

Creates a parametric boolean feature of the Part workbench:
  union        -> Part::Fuse   (A + B)
  difference   -> Part::Cut    (A - B)
  intersection -> Part::Common (A & B)
The operands keep living in the document tree as children of the result (FreeCAD
hides them automatically); the operation is fully parametric and reversible.
"""

from __future__ import annotations

from typing import List

from ._common import resolve_object

# op name (vocabulary) -> FreeCAD parametric feature type.
_OP_TYPE = {
    "union": "Part::Fuse",
    "difference": "Part::Cut",
    "intersection": "Part::Common",
}


def boolean(doc, params: dict) -> List:
    """Run a boolean operation between two existing bodies."""
    op = params["op"]
    feature_type = _OP_TYPE.get(op)
    if feature_type is None:
        raise ValueError(f"unknown boolean op '{op}' "
                         f"(allowed: {', '.join(_OP_TYPE)})")

    base = resolve_object(doc, params["a"])
    tool = resolve_object(doc, params["b"])
    if base.Name == tool.Name:
        raise ValueError("a boolean needs two DIFFERENT bodies")

    feature = doc.addObject(feature_type, op.capitalize())
    feature.Base = base
    feature.Tool = tool
    return [feature]
