# ADR 0014 - sketch_on_face (FlatFace attachment) and pocket (extrude op=cut)

Status: Accepted (Phase 6, Session 11)
Date: 2026-06-26

## Context

So far sketches were drawn on the global XY/XZ/YZ planes (`create_sketch`, ADR
0009). Real components need features built ON an existing body: a boss raised from
its top face, or a pocket cut into it. That requires a sketch ATTACHED to a face,
and a SUBTRACTIVE extrude.

Two fragilities to avoid, both already familiar: making a small model name a face
(`Face6`) is as unreliable as enumerating edges (ADR 0006); and chaining the new
sketch into the following extrude is the ADR 0010/0013 problem again.

## Decision

**sketch_on_face** (`vocabulary/sketch_on_face.py`): create a real
`Sketcher::SketchObject` attached to a face via `AttachmentSupport=[(obj,(face,))]`
+ `MapMode="FlatFace"` (legacy `Support` fallback; optional `AttachmentOffset`).
- `target` (required, the owner object); `where` (`enum top/bottom`, default `top`)
  OR an explicit `face` id; `shape` (`rectangle/circle`) with width/height or
  radius; `offset` optional.
- The face is resolved IN THE EXECUTOR (principle 7): it reads the real faces and
  picks the planar one whose normal is +Z (top) / -Z (bottom) at the highest /
  lowest Z. An explicit `face` id is still honoured.
- Geometry reuses `create_sketch`'s `draw_profile` helper (shared closed
  rectangle/circle), so both sketch commands build identical clean wires.
- The sketch is named `Sketch`, so the engine chains the next extrude onto it; we
  extended ADR 0010's `_next_profile_id` to treat `sketch_on_face` like
  `create_sketch`.

**pocket** = a subtractive extrude. Rather than add a separate command, we extended
`extrude` with `op` (`enum add/cut`, default `add`):
- `add` (default): the existing behaviour, a `Part::Extrusion` boss.
- `cut`: the profile is extruded INTO the body and a `Part::Cut` removes it from the
  owner body (found via `_attachment_owner`; a pocket from a free-standing sketch is
  refused with a clear message).

**Real-FreeCAD robustness fixes (Session 11 follow-up).** The first real test of a
pocket failed: the cut removed nothing. Two causes, both fixed:
1. **Direction.** Part::Extrusion with `DirMode="Normal"` + `Reversed` did not
   reliably dig into the body on an attached sketch. The pocket now computes the
   into-body direction EXPLICITLY (`DirMode="Custom"`, `Dir` = the sketch's world
   normal flipped toward the body's bbox centre). As a safety net, if the cut still
   removes no material we flip the direction once and retry; if it still removes
   nothing we fail with a clear message (principle 7: no false success). Volume
   comparison is skipped in the headless mock (no real volume).
2. **Placement.** `sketch_on_face` drew the profile at the face's attachment ORIGIN
   (a corner), which is confusing and can leave the feature hanging off the edge.
   It now CENTRES the profile on the face: after the attachment recompute it maps
   the face centre (`CenterOfMass`) into the sketch's local plane and draws there
   (shared `draw_profile` gained an `origin`/`centered` option; `create_sketch`
   keeps its corner-at-origin behaviour). Best-effort - falls back to the local
   origin when the maths is unavailable (mock).

## Why this over the alternatives

- **A separate `pocket` command**: would duplicate the extrusion logic and the
  solid-verification check. Extending `extrude` with `op` keeps one place for "turn
  a profile into a swept solid" and reads naturally in a plan
  (`sketch_on_face` -> `extrude op=cut`).
- **PartDesign Body/Pad/Pocket**: more "correct" CAD, but it forces every object
  into a PartDesign Body and is far more state-sensitive (the very thing that
  confused the early real tests). We stay on the free Part workbench, consistent
  with the rest of the vocabulary.
- **Model picks the face index**: rejected for the same reason as ADR 0006; the
  executor resolves `top`/`bottom` from real geometry.

## Consequences

- The agent can add bosses and cut pockets on existing bodies, the last big step
  toward whole components.
- A pocket only works on a face-attached sketch; this is enforced and reported, so
  the model self-corrects rather than producing a wrong result.
- The headless mock resolves `top`/`bottom` via face normals and records the
  attachment; covered by `tests/test_sketch_on_face.py` (boss + pocket + face
  selector + graceful failures).
- Catalog schema -> `0.5.0` (extrude gains `op`, new `sketch_on_face`); engine +
  add-on -> `0.10.0-phase6`.
