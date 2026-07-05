# ADR 0005 - Geometric RAG: feed perception.detail into the planning loop

Status: Accepted (Phase 3, Session 5)
Date: 2026-06-21

## Context

Phase 2 gave the model only a cheap `perception.overview` (one line per object:
id/type/label). That is enough to create primitives, but not to edit existing
geometry: `fillet`, `chamfer` and precise `drill_hole` need to reference REAL
sub-elements (`Edge7`, `Face1`, the top face, the bounding box). Without that, a
small local model has to GUESS edge numbers and hole coordinates, which fails
often (principle 7: don't trust, verify).

We already had `perception.detail` (the close-up: dimensions, bounding box,
topology counts, and a few named `Edge*`/`Face*` with hints). It existed but was
NOT used by the brain. The open question (PIANO_SVILUPPO_FUTURO, Phase 3) was how
to wire it in without saturating a small model's context window.

## Decision

1. **Pre-fetch detail for small documents.** Before planning, the engine
   (`bridge_server.on_user_prompt`) calls `perception.detail` for each existing
   object and passes the list to `Brain.plan(..., details=...)`. This is done
   ONLY when the document has at most `MAX_DETAIL_OBJECTS` (= 8) objects; larger
   documents fall back to the overview alone. This keeps the prompt concise for
   small local models (principle 9) and avoids an extra "which object should I
   inspect?" model round-trip, which would be slow on weak hardware.

2. **Concise detail block in the prompt.** `Brain._details_block` renders, per
   object, one short paragraph: dimensions, bounding box, and the referenceable
   `Edge*`/`Face*` with their hints (e.g. "top face"). The system prompt tells the
   model to use ONLY those references for fillet/chamfer and never invent numbers.

3. **Few-shot examples.** The system prompt now carries a handful of compact
   input -> exact-JSON examples (box, centred hole, fillet-all-edges, boolean,
   two-step box+hole), to steer small models toward valid output.

4. **Auto-located drilling.** `drill_hole` now reads the target's bounding box at
   execution time: with no `position`, it drills from the TOP face centre
   downwards. `position` may be `[x,y]` (drill at that point on the top) or
   `[x,y,z]` (explicit, back-compatible). This removes the model's need to compute
   coordinates it cannot see, and is the executor-side half of the same principle:
   perceive, don't guess.

5. **Bounded self-correction.** The repair loop now retries up to
   `MAX_REPAIR_ATTEMPTS` (= 2), feeding the geometric detail back to the model and
   refusing to re-run an action whose signature it already tried (no infinite
   loops, principle 8).

## Consequences

- The model can now target real edges/faces, so fillet/chamfer/precise-drill have
  a real chance on a small local model. Multi-step requests (create + drill) work
  because the detail of freshly created objects is available on the next request.
- Slightly larger prompts, bounded by `MAX_DETAIL_OBJECTS` and the per-object cap
  already in `perception.detail` (max 12 faces/edges). Acceptable for the small
  documents this project targets; revisit if we ever support large assemblies.
- Versions bumped to `0.4.0-phase3` (engine and add-on). All 8 headless tests stay
  green; `test_brain`, `test_vocabulary_exec` and `test_user_prompt_roundtrip`
  were extended to cover the detail block, auto-centred drilling and the RAG path.
- `Brain.plan` / `Brain.repair` signatures gained an optional `details` argument
  (backward compatible: defaults to None).

## Alternatives considered

- **Model-driven inspection** (ask the model which object to inspect, then fetch
  detail, then plan): more scalable for huge documents but adds a model round-trip
  - too slow on the tester's hardware and unnecessary for small documents. Kept as
  a future option if assemblies grow.
- **Always send full detail for every object**: rejected to protect small models'
  context; capped by `MAX_DETAIL_OBJECTS` instead.
