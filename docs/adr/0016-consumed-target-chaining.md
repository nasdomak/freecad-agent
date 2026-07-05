# ADR 0016 - Redirect references to consumed objects within a plan

- Status: accepted (Session 13)
- Deciders: Marco (supervision), lead architect
- Related: ADR 0010 (sketch->extrude chaining), ADR 0013 (generalized id-chaining)

## Context

The Session 13 stress test asked for one plan with several drills on the same
body ("create a cylinder ... then drill four 8 mm holes ..."). Each successful
`drill_hole` wraps its target in a new `Part::Cut` feature (`Cylinder` becomes
`Drilled`); the old id survives only as the hidden, unmodified base. The model,
however, keeps naming the ORIGINAL id in the later steps of the plan - it cannot
know the auto-generated result names in advance. Result: every drill after the
first landed on the dead base, each producing a one-hole copy stacked on the
same spot, and the visible part ended up missing its holes.

This is the same fragility class as ADR 0010/0013 (the model referencing names
it cannot predict), but for a reference that RESOLVES - to the wrong, consumed
object - so the existing chaining (which only fires on unresolved references)
never triggers.

## Decision

Track, inside a single plan, which referenced objects each successful action
CONSUMED, and redirect later references from the consumed id to the feature
that swallowed it (transitively: Cylinder -> Drilled -> Drilled001 -> ...).

- A static table `CONSUMING_PARAMS` in `engine/bridge_server.py` lists, per
  command, which params reference consumed objects: `drill_hole.target`,
  `boolean.a/b`, `fillet.target`, `chamfer.target`, `extrude.target` (the used
  profile). `mirror`/`array` keep their source visible and `move`/`rotate`
  keep the same id, so they are not listed.
- Pure helpers on `Session` (headless-tested in `tests/test_idchain.py`):
  `_follow_replacements` (cycle-safe chain lookup), `_rewrite_consumed`
  (returns a redirected copy of the action, never mutates), `_record_consumed`
  (updates the mapping after a successful action).
- The plan loop applies the redirection to every action (and to every repaired
  action) AFTER the ADR 0010/0013 links, and logs each redirection as a
  `linking` status (transparency, principle 5).
- Scope: within ONE plan only, like all id-chaining. Across separate requests
  the model sees a fresh overview with the real ids.

## Consequences

- "Drill it four times" in one phrase now lands every hole on the live body.
- Phrases like "cut A from B then chamfer B" now chamfer the cut result, which
  is what the user means.
- Known limit (documented, not fixed): `extrude op=cut` also consumes the
  attachment OWNER body, but that id is not in the action params (it is found
  by the executor at run time), so it is not redirected. Extension candidate if
  it bites in practice.
- Known limit (model, not engine): a small model still cannot COMPUTE hole
  coordinates ("equally distributed on a radius" needs trigonometry). The test
  guide phrases give explicit positions instead.

## Alternatives considered

- Re-feeding the document state to the model between actions: an extra
  inference round-trip per step on slow local hardware, and the model would
  still have to re-aim mid-plan (rejected, principle 8/9).
- Executor-side "resolve to newest descendant" lookup: hides the redirection
  from the log and would guess OUTSIDE the plan too, where a stale name may be
  intentional (rejected, principle 5/7).

Engine+addon versions: 0.12.0-phase6. Wire protocol unchanged (0.1.0).
