# ADR 0011 - Model-friendly axis/plane strings, resolved in the executor

Status: Accepted (Phase 6, Session 10)
Date: 2026-06-26

## Context

Phase 6 adds commands that operate along an AXIS or across a PLANE: `rotate`
(axis of rotation), and later `mirror` (mirror plane) and `array` (direction /
polar axis). The natural CAD parameter for these is a 3D vector (e.g. the axis
`[0,0,1]`, the plane normal `[1,0,0]`).

But free 3D vectors are exactly the kind of output a small local model gets wrong:
it confuses sign, order, or normalization, and there is no cheap way to validate
"is this the Z axis" from three floats. We already learned this lesson twice -
ADR 0006 (don't make the model enumerate edges) and ADR 0010 (don't make the model
predict an auto-generated name): fragile references belong in the executor, which
runs inside FreeCAD and can resolve them deterministically.

`create_sketch` (ADR 0009) already proved the friendlier idiom: it takes a `plane`
STRING (`"XY"`/`"XZ"`/`"YZ"`), not a normal vector, and the executor maps it.

## Decision

Standardize a small, model-friendly vocabulary for directions, resolved by the
EXECUTOR into real `FreeCAD.Vector`s:

- **axis** = the string `"X"`, `"Y"` or `"Z"` (each command declares its own
  default, e.g. `rotate` defaults to `"Z"`).
- **plane** = the string `"XY"`, `"XZ"` or `"YZ"` (the executor uses the plane's
  normal: `XY -> Z`, `XZ -> Y`, `YZ -> X`).
- **point / centre** = `[x,y,z]`, optional; when omitted the executor uses the
  object's bounding-box centre (perception, not a guess) or the origin.

The resolution lives in `addon/ai_copilot/executor/vocabulary/_common.py`:

- `resolve_axis(axis, default="Z") -> FreeCAD.Vector` - maps the string to a unit
  vector; also accepts an explicit `[x,y,z]` for power users, but the schema only
  advertises the strings (the model is never asked to produce a vector).
- `resolve_plane_normal(plane, default=...) -> FreeCAD.Vector` - maps the plane
  string to its normal (added when `mirror` lands).
- `bbox_center(obj) -> FreeCAD.Vector` - the centre of the object's bounding box,
  or the origin if it has no shape yet.

The catalog (`shared/commands.schema.json`) declares `axis` as an `enum`
(`X`/`Y`/`Z`) and `plane` as an `enum` (`XY`/`XZ`/`YZ`), so an out-of-range string
is caught by validation before execution. `center` stays an optional numeric array.

## Why this over the alternatives

- **Free vectors in the schema**: most flexible, but the small model produces them
  unreliably and they cannot be sanity-checked cheaply. Rejected as the PRIMARY
  contract; still accepted opportunistically by `resolve_axis` for experts.
- **Per-command ad-hoc handling**: each new command re-deriving "what does Z mean"
  invites drift. A shared helper keeps every command consistent and testable.

## Consequences

- Every Phase 6 command speaks the same friendly direction language as
  `create_sketch`, so few-shot examples stay short and consistent.
- Validation rejects a bad axis/plane string up front (blocking enum error), which
  feeds the self-correction loop with a clear message.
- The executor owns the string -> vector mapping in one place (`_common.py`), unit
  tested headless. The mock's `Vector`/`Rotation`/`Placement` were made faithful
  enough to read back a moved/rotated position (see `tests/test_transform.py`).
- Catalog schema -> `0.4.0`; engine + add-on -> `0.9.0-phase6`.
