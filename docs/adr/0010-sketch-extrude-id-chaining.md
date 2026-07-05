# ADR 0010 - Chain the new sketch's id into the following extrude

Status: Accepted (Phase 5, Session 9)
Date: 2026-06-26

## Context

After `create_sketch` shipped (ADR 0009), the very first real test exposed a bug.
"draw a rectangle and extrude it" worked; a SECOND request, "extrude a circle of
radius 12 by 20 mm", created the circle sketch but left it as a bare wire - no
solid - and produced a stray, wrong extrusion.

Root cause: the model emits a two-step plan `create_sketch` then `extrude`, and the
few-shot teaches it to write `extrude target = "Sketch"`. FreeCAD auto-uniquifies
object names: the FIRST sketch is `Sketch`, the next `Sketch001`, and so on. On the
first request the guess `"Sketch"` happens to be right. On the second request the
new sketch is `Sketch001`, but the model still says `"Sketch"`, which resolves to
the ALREADY-consumed first sketch. So the extrude hits the wrong (old) object and
the freshly created circle sketch is never extruded.

This is the same class of failure as ADR 0006 (edge enumeration): a small local
model cannot reliably produce a fragile reference - here, the auto-generated name
of an object it has not created yet.

## Decision

Resolve the reference in the ENGINE, not in the model. When executing a plan, the
engine remembers the id that `create_sketch` actually produced and rewrites the
following `extrude` to use it (`engine/bridge_server.py`):

- `_next_profile_id(current, action, res)`: after each action, a successful
  `create_sketch` sets the marker to its created id; a successful `extrude` clears
  it (the profile is consumed); anything else leaves it unchanged.
- `_rewrite_extrude_target(action, profile_id)`: a pure helper that, if the action
  is an `extrude` and a profile id is in flight and differs from the model's target,
  returns a COPY whose `target` is the real id (never mutates the input).
- `_link_profile_target(...)`: applies the rewrite and logs it transparently
  (`agent.status linking`, privacy local) so the user can see what happened.

The rewrite is applied to the original action AND to any repaired action. Plans that
extrude a PRE-EXISTING sketch (no `create_sketch` before the extrude in the same
plan) are unaffected: with no profile in flight, the model's target is used as-is.

Defence in depth (`extrude.py`): after building the `Part::Extrusion` the executor
recomputes and checks the result actually has a solid; if the profile was not a
closed region it raises a clear error instead of reporting a hollow success
(principle 7/8). The check is skipped where real solid info is unavailable (the
headless mock), so tests are unaffected.

## Why this over the alternatives

- **Hardening the prompt** (tell the model to use the right name): cannot work -
  the model has no way to know the name before the object exists. Same dead end as
  asking it to enumerate edges in ADR 0006.
- **Executor fallback to "the newest sketch"** inside `extrude`: would fire only
  when the target fails to resolve, but here the wrong name `"Sketch"` DOES resolve
  (to the old sketch), so a resolve-failure fallback never triggers. The engine, by
  contrast, knows what the preceding step just created.
- **Feeding created ids back into the model between steps**: heavier (an extra
  model round-trip per step) and still trusts the model to copy the id. The
  deterministic rewrite is cheaper and reliable.

## Consequences

- "create a shape and extrude it" works on the second, third, ... request, not just
  the first; the new sketch is the one that gets extruded.
- Transparent: the panel/engine log shows "extruding the sketch just created (<id>)"
  when the rewrite fires.
- An empty extrusion now fails loudly (clear message + self-correction) instead of a
  misleading "completed".
- Engine + add-on -> `0.8.1-phase5`. New `tests/test_extrude_link.py` unit-tests the
  two pure helpers and the executor's no-solid guard; `RUN_ALL_TESTS.bat` -> 14
  tests. No change to the catalog or the protocol.
- Limitation: only ONE profile is tracked per plan (the most recent sketch). A plan
  that interleaves several create_sketch/extrude pairs in one request would chain
  only the latest; this is rare and can be revisited if it ever comes up.
