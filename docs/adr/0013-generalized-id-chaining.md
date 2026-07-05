# ADR 0013 - Generalized id-chaining of "the object I just created"

Status: Accepted (Phase 6, Session 11)
Date: 2026-06-26

## Context

ADR 0010 fixed one fragile multi-step case: a plan that does `create_sketch` then
`extrude` must extrude the sketch that was actually created, because FreeCAD
auto-renames objects (`Sketch`, then `Sketch001`, ...) and the model cannot predict
the new name. The engine rewrote the extrude's target to the real id.

Phase 6 multiplies this pattern. "Create a box and mirror it", "draw a profile then
array it", "make a bracket then cut a pocket in it" all say *create X, then operate
on X*. The model writes the name it expects (`Box`), but the real object may be
`Box001`, or the model uses a vague placeholder. The sketch->extrude special case
no longer covers enough.

## Decision

Generalize the chaining in `engine/bridge_server.py` to "the last object this plan
created", resolved in the engine (same philosophy as ADR 0006/0010/0011: fragile
references belong on the side that can see reality).

During plan execution the engine tracks two things:
- `known_ids`: the ids the model could legitimately reference - the document at
  plan start (`perception.overview`) plus every id created so far.
- `last_created_id`: the first `created_ids` of the most recent successful action.

Before running each step, `_rewrite_refs(action, last_created_id, known_ids)`:
- looks up the action's object-reference fields from a per-command table
  (`_REF_FIELDS`: `target` for most commands, `a`/`b` for boolean);
- if **exactly one** referenced id is NOT in `known_ids` (i.e. it does not exist
  yet), rewrites that one to `last_created_id`; otherwise leaves the action
  untouched. The single-unresolved rule avoids guessing for a boolean whose two
  operands are both unknown (too ambiguous to fix safely).

**Unambiguity guard (Session 11 follow-up).** The generic rewrite only fires while
the plan has created EXACTLY ONE object so far (`created_count == 1`). This is the
true "create one thing, then operate on it" idiom. In a plan that has created
several objects (e.g. box -> boss -> pocket), "the last created object" is NOT a
safe guess for an unresolved reference, so the model's name is left alone and a
genuine mistake fails and self-corrects (clear "object not found") rather than
silently pointing at the wrong body. This fixes a bug Marco caught: a pocket meant
for the base box was aimed at the freshly-made boss, so it cut nothing visible. The
sketch->extrude specialization (ADR 0010) is NOT subject to this guard - it is
narrowly scoped and always safe.

The helpers are pure and the rewrite is logged transparently (`agent.status`
`linking`). The ADR 0010 sketch->extrude rewrite is KEPT as a specialization
(`_rewrite_extrude_target`/`_next_profile_id`, now also primed by `sketch_on_face`):
it must fire even when a same-named OLD sketch still exists (so the name *does*
resolve), which the general "unresolved reference" rule would not catch. The two
mechanisms run side by side; the general one only touches references that do not
resolve.

## Why this over the alternatives

- **Re-feed the created ids to the model and re-plan**: more model round-trips,
  slower on weak hardware, and still fragile. Rejected.
- **Always rewrite the first reference**: would clobber correct references in
  multi-object plans (e.g. boolean of two existing bodies). The "must be currently
  unresolved" guard prevents that.
- **Fold sketch->extrude into the general rule**: it would miss the case where an
  old object of the same name still resolves (the original ADR 0010 bug). Kept as a
  deliberate specialization.

## Consequences

- Plans like "create a box and mirror it" / "...and make an array of it" work even
  when FreeCAD renames the new object, with no extra model calls.
- The behaviour is conservative: a reference that already resolves is never
  changed, so existing multi-object plans (e.g. boolean of two bodies) are
  unaffected.
- Pure helpers (`_known_ids`, `_update_created`, `_rewrite_refs`) are unit-tested
  headless in `tests/test_idchain.py`; `tests/test_extrude_link.py` (ADR 0010) stays
  green unchanged.
- engine + add-on -> `0.10.0-phase6`.
