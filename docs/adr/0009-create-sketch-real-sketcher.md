# ADR 0009 - `create_sketch` as a real Sketcher sketch (to unlock `extrude`)

Status: Accepted (Phase 5, Session 9)
Date: 2026-06-25

## Context

`extrude` was the only command in the vocabulary never validated on real FreeCAD,
because there was no way to produce a profile to extrude. Every other command was
exercised in natural language; `extrude` had no input. We need a `create_sketch`
command so the canonical FreeCAD pipeline "draw a 2D profile -> extrude it into a
solid" works end to end from natural language.

The brief asked for the minimal *useful* form for a small local model: a simple
rectangular or circular profile on a standard plane, with dimensions. The open
design question (this ADR) is how to REPRESENT that profile.

## Decision

`create_sketch` creates a **real `Sketcher::SketchObject`** (Marco chose the
recommended option among: real Sketcher sketch / plain `Part::Feature` face).

Catalog entry (`shared/commands.schema.json`, bumped to `0.3.0`):

```
create_sketch:
  required: [shape]
  shape:     "rectangle" | "circle"          (required)
  plane:     "XY" | "XZ" | "YZ"              (default "XY")
  width,height: number > 0                    (rectangle)
  radius:    number > 0                        (circle)
  placement: [x,y,z] origin offset            (optional)
```

Executor (`addon/ai_copilot/executor/vocabulary/create_sketch.py`):

1. Create `Sketcher::SketchObject` named **`Sketch`**, oriented onto the chosen
   plane via its `Placement` (XY = identity, XZ = +90 deg about X, YZ = +90 deg
   about Y). The sketch then extrudes along its own normal (`extrude` uses
   `DirMode = "Normal"`), so the plane choice also sets the extrusion direction.
2. **Rectangle**: four `Part.LineSegment` edges (corner at the local origin) plus
   four `Sketcher` coincidence constraints, so it is a clean closed loop that
   `extrude` (`Solid = True`) caps into a solid, and a properly constrained sketch
   the user can still edit.
3. **Circle**: one `Part.Circle` centred on the local origin.
4. Shape-specific requirements (width+height for a rectangle, radius for a circle)
   are validated IN THE EXECUTOR, raising clear `ValueError`s, because the minimal
   engine-side validator (`fake_brain`) does not support conditional `required`
   (JSON Schema if/then). The errors feed the self-correction loop (principle 7).

The model is told (system prompt + two few-shot examples) that to extrude it first
calls `create_sketch` (which makes an object named `Sketch`) and then `extrude`
with `target: "Sketch"`. The catalog block the model sees is generated from the
schema, so `create_sketch` appears automatically (principle 5).

`extrude` now also hides the consumed profile (`hide_object`, the same fix used for
fillet/chamfer in ADR 0006): created via the data API, `Part::Extrusion` does not
auto-hide its base, which would leave the sketch lines drawn over the solid.

## Why this over the alternatives

- **Plain `Part::Feature` face** (a wire/face, no Sketcher): simpler and very robust
  to extrude, but it is NOT an editable sketch and breaks the "create sketch" mental
  model. Rejected: the whole point is to unlock the real sketch->extrude workflow and
  leave the user something they can open in the Sketcher workbench.
- **Draft workbench objects** (`Draft.makeRectangle`/`makeCircle`): editable too, but
  pulls in a workbench dependency and more surface for little gain at this scale.
- **Conditional `required` in the schema** (width/height only for rectangle): our
  stdlib validator does not implement if/then; adding it now is scope creep. Validating
  shape-specific params in the executor is consistent with how the other geometry
  commands already report clear errors.

## Consequences

- `extrude` becomes reachable from natural language: "draw a 40x30 rectangle and
  extrude it 10 mm", "extrude a circle of radius 12 by 20 mm". The model emits a
  two-step plan (create_sketch -> extrude) it has a few-shot example for.
- Vocabulary grows from 7 to **8** commands. Catalog -> `0.3.0`; engine and add-on
  -> `0.8.0-phase5`.
- Headless tests: `mock_freecad` gained fake `Part` (LineSegment, Circle) and
  `Sketcher` (Constraint) modules and a `Sketcher::SketchObject` shape so selection
  and extrusion are testable without FreeCAD. New `test_create_sketch.py` (geometry +
  graceful failures); `test_vocabulary_exec.py` now runs create_sketch -> extrude for
  rectangle and circle and asserts the sketch is hidden after the extrude.
  `RUN_ALL_TESTS.bat` -> 13 tests.
- Plane orientation uses the conventional axis rotations; the common XY case is the
  default and the most robust. Arbitrary placements/planes may need follow-up once
  validated on real FreeCAD (documented limitation).
- Naming: the first sketch is `Sketch`, the next `Sketch001`, etc. (FreeCAD auto-
  uniquifies). With several sketches the model must pick the right id from the
  document overview, exactly like the other "reference an existing object" commands.

## Note on phase numbering

This work is tagged `phase5` as the next validated milestone (sketch + extrude).
It is distinct from the older roadmap's "Phase 5 = interchangeable cloud model
adapters" in `PIANO_SVILUPPO_FUTURO.md`, which remains future work; the version tag
just marks this milestone.
