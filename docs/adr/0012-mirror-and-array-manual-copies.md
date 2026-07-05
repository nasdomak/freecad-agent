# ADR 0012 - mirror and array as manual Part copies (no Draft)

Status: Accepted (Phase 6, Session 11)
Date: 2026-06-26

## Context

To build a whole component the agent must DUPLICATE existing geometry: reflect a
part across a plane (`mirror`) and repeat it in a row or around an axis (`array`).
FreeCAD ships a Draft workbench with `Draft.mirror`, `Draft.array` etc., which
would be the obvious building blocks.

But Draft is a heavy optional workbench. Depending on it would dilute principle 2
("FreeCAD untouched", we are an add-on on a stock base) and adds a failure surface
on machines where Draft is not loaded. The Part workbench (always present in the
core) already offers everything we need.

## Decision

Implement both commands on the **core Part workbench only**.

**mirror** (`vocabulary/mirror.py`) uses `Part::Mirroring`, a parametric feature:
- `target` (required); `plane` (`enum XY/XZ/YZ`, default `YZ`); `base` `[x,y,z]`
  optional (a point the mirror plane passes through, default origin).
- The plane is resolved to its NORMAL with `resolve_plane_normal` (ADR 0011).
- The ORIGINAL is kept visible: a mirror almost always wants both halves (unlike
  fillet/extrude, which consume their base).

**array** (`vocabulary/array.py`) makes **manual copies**: for each item it creates
a plain `Part::Feature`, assigns `Shape = target.Shape.copy()` and sets its own
`Placement`. No Draft, no parametric array object - just independent solids the
user can edit freely.
- `pattern` (`enum linear/polar`); `count` is the **TOTAL** number of items
  (original included), so the executor creates `count-1` copies.
- linear: `spacing` (required) along `direction` (`enum X/Y/Z`, default `X`); item
  `i` sits at `base + i*spacing*direction`.
- polar: `angle` (default 360) about `axis` (`enum X/Y/Z`, default `Z`) through
  `center` (default the **file origin** `[0,0,0]`); item `i` is rotated by
  `i*angle/count`, so a full 360 circle of `count` items is evenly spaced. The
  items ORBIT the central axis - the default centre is the origin, NOT the object's
  own centre (pivoting on the object's own axis would just spin it in place and
  overlap the copies, the original Session-11 bug Marco caught). Optional `radius`:
  when given, the original is repositioned onto a circle of that radius around the
  centre (the whole ring then sits at that radius); when omitted, the items orbit
  at the object's current distance from the centre.

Per-pattern requirements (`spacing` for linear) are validated **in the executor**,
not in the schema: the stdlib catalog validator cannot express conditional
`required` (JSON Schema if/then), the same approach as `create_sketch`'s
width/height. Clear `ValueError`s feed the self-correction loop (principle 7/8).

## Why this over the alternatives

- **Draft.array / Draft.mirror**: less code, but a heavy dependency and against
  principle 2. Rejected.
- **A single parametric Part array object**: FreeCAD core has no general array
  primitive; building one is more fragile than N independent copies and harder for
  a non-developer to edit afterwards. Manual copies are transparent and undoable.
- **`count` = number of NEW copies**: confusing ("array of 6" should leave 6). We
  chose `count` = total, matching how users and most CAD tools talk.

## Consequences

- mirror and array work with no workbench beyond Part, on any FreeCAD install.
- Each array item is a free, independently editable solid (no hidden parametric
  link to the source) - simple and predictable, at the cost of not auto-updating
  if the source later changes (acceptable for this stage).
- The headless mock gained `Shape.copy()` and handles `Part::Feature` (keeps an
  assigned Shape) and `Part::Mirroring` (inherits the Source bbox); covered by
  `tests/test_duplicate.py`.
- Catalog schema -> `0.5.0`; engine + add-on -> `0.10.0-phase6`.
