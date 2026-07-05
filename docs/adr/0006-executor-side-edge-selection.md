# ADR 0006 - Executor-side edge selection for fillet/chamfer

Status: Accepted (Phase 3, Session 6)
Date: 2026-06-23

## Context

After ADR 0005, fillet/chamfer still failed in real natural-language use, while
drill/boolean/multi-step worked. The reason was specific: `fillet`/`chamfer`
required the model to emit an explicit list of edge ids, e.g.
`["Edge1", ..., "Edge12"]`. Producing a long, exact array of sub-element ids is
the single most fragile output for a small local model (the tester's `qwen3:4b`):

- "round all the edges" -> the model emitted an empty/partial/invalid `edges`
  array, so the action was dropped at validation or failed at recompute, the
  bounded repair loop retried, and it gave up: **the command did not complete**.
- "chamfer all the edges" -> the model listed only some edges, so only those were
  bevelled: **partial / wrong result**.

The geometric detail from ADR 0005 (the real `Edge*` references in the prompt) was
not enough: even told the right numbers, a small model does not reliably copy a
12-item array into JSON. The fragile step is the *enumeration itself*, regardless
of the sub-cause. Drill/boolean work precisely because they never ask the model to
list edges.

## Decision

Move edge selection from the model to the executor (principle 7: the agent
perceives and verifies; it does not ask a small model to guess/list a dozen ids).

1. **`edges` becomes optional** in `fillet` and `chamfer`. Required params are now
   just `target` + `radius`/`size`.

2. **New `where` selector** (string enum): `all` (default), `top`, `bottom`,
   `vertical`, `horizontal`. When `edges` is omitted, the executor resolves the
   real edges itself from the target's geometry.

3. **Executor-side selection** (`vocabulary/_common.py::select_edge_indices`):
   reads each edge's bounding box (assuming +Z is "up") and groups them - flat at
   max Z = top, flat at min Z = bottom, running along Z = vertical, any flat
   constant-Z plane = horizontal, everything = all. It falls back to "all" when no
   global frame is available and raises a clear error for an unknown selector or a
   group that matches nothing (so the repair loop can react).

4. **Backward compatible.** An explicit `edges` list still works exactly as before
   and takes precedence over `where`. The model may still pass specific edges when
   the user clearly wants them.

5. **Prompt updated.** The system prompt now tells the model it normally does NOT
   list edges: omit `edges`, optionally set `where`. The verbose 12-edge few-shot
   example was replaced by the simple forms (`fillet` all, `chamfer` top).

## Why this over the alternatives

- **Two new commands `round_edges` / `chamfer_edges`** (the Session-6 brief's
  fallback): same end result for the model, but grows the catalog to 9 commands
  with near-duplicate semantics. Extending the existing two keeps the vocabulary
  at 7, stays backward compatible, and the model burden is identical (it just
  omits `edges`).
- **Only hardening the prompt:** leaves the fragile enumeration in the model's
  hands; rejected as the primary fix (kept as a secondary improvement - we did
  update the prompt too).

## Consequences

- "round all the edges with radius 3" becomes, for the model, a trivial
  `{"cmd":"fillet","params":{"target":"Box","radius":3}}` - no edge list. Partial
  selectors ("the top edges", "the vertical edges") work without naming any edge.
- The catalog version is bumped to `0.2.0`; engine and add-on to `0.5.0-phase3`.
- Headless tests: all stay green and one was added. `test_edge_selection` unit-
  tests the selector (all=12, top/bottom/vertical=4, horizontal=8, partitioning,
  unknown selector refused); `test_vocabulary_exec` now also exercises the no-edges
  fillet, `where:"top"` chamfer and `where:"vertical"` fillet. `mock_freecad` gained
  real-ish box edges (12 edges with bounding boxes) so selection is testable
  headless. 9 tests total.
- Selection assumes the conventional +Z-up orientation for top/bottom/vertical.
  `all` is orientation-independent and is the default, so the common case is safe;
  arbitrarily-rotated bodies may need explicit `edges` (documented limitation).

## Follow-up fix (same session): hide the consumed base

Real-FreeCAD validation showed the fillet was applied correctly to all 12 edges
(`Fillet.Edges` = 12 tuples, state Up-to-date) but **the rounding looked like it
did nothing**. Ground truth from the Python console: both the `Fillet` and its
base `Box` were visible (`VIS_fillet True VIS_base True`). FreeCAD's interactive
fillet/chamfer commands hide the base so only the result shows; creating the
feature through the data API does not, so the original sharp-edged box was drawn
on top of the rounded result.

Fix: `vocabulary/_common.py::hide_object(obj)` (best-effort, no-op without a GUI),
called by `fillet`/`chamfer` after building the feature. Booleans (Part::Cut/
Fuse/Common) already auto-hide their operands via their own view provider, which
is why drill/boolean looked correct and only fillet/chamfer were affected.
`test_vocabulary_exec` now asserts the base is hidden after a fillet. Versions
bumped to `0.5.1-phase3`.
