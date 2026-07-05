# Test Guide - Phase 5 (Create Sketch -> Extrude)

This guide walks you through validating the new `create_sketch` command and the
`create_sketch -> extrude` chain in real FreeCAD, using plain English requests.
No coding needed. Just follow the steps in order.

What is new in this version (engine + add-on `0.8.0-phase5`):

- A new command **create_sketch** makes a real, editable Sketcher sketch
  (a rectangle or a circle, on the XY / XZ / YZ plane).
- This finally unlocks **extrude**: a sketch can be turned into a 3D solid.
- The agent now understands requests like "draw a 40x30 rectangle and extrude it
  10 mm".

---

## Step 0 - Update both parts (important)

This release changed BOTH the add-on and the engine, so you must refresh both.

1. Wait until kDrive has finished syncing the project folder (the folder icon is
   green / "up to date"). This avoids half-downloaded files.
2. Double-click **INSTALL_ADDON.bat** (copies the new add-on into FreeCAD).
3. If FreeCAD is open, **close and reopen it** so it loads the new add-on.
4. Double-click **START_ENGINE.bat** (start, or restart if already running) so the
   engine picks up the new command and the new vocabulary. Leave its window open.

You do NOT need to start Ollama yourself: the engine starts it for you if it is
installed (you may see "starting it for you" in the engine window the first time).

---

## Step 1 - Open the panel and connect

1. In FreeCAD, switch the workbench selector (top toolbar) to **FreeCAD Agent**.
2. The agent panel appears on the side. Click **Connect**. The status light should
   turn green.
3. Make sure you have an active document (use File -> New if the 3D area is empty).

---

## Step 2 - The main test: rectangle -> solid

In the panel's "Ask in plain language" box, type this and click **Ask the agent**:

```
draw a 40x30 rectangle and extrude it 10 mm
```

Expected result:

- A **Sketch** appears, then an **Extrude** solid 40 x 30 x 10 mm is built on top
  of it. In the 3D view you should see a solid block (the thin sketch lines are
  hidden automatically so they do not show through).
- Press **Ctrl+Z**: it undoes the operation (reversibility). Press **Ctrl+Y** or
  redo to bring it back if you like.

If the solid looks right, the main goal of this session is achieved.

---

## Step 3 - A circle -> cylinder-like solid (the important one)

This is the case that failed in the first test (the circle was drawn but not turned
into a solid). It is fixed now: do Step 2 first, THEN, in the SAME session, type and
Ask:

```
extrude a circle of radius 12 by 20 mm
```

Expected: a NEW sketch with a circle, then an **Extrude** solid 20 mm tall (a
disc/cylinder shape) - NOT just a flat circle outline. The new sketch is hidden
automatically. Ctrl+Z undoes it.

Why it matters: each new sketch gets a different internal name (Sketch, Sketch001,
...). The engine now automatically extrudes the sketch it just created, so the
second, third, ... "create a shape and extrude it" request works, not only the
first. If you watch the panel log you may see a line like "extruding the sketch
just created".

---

## Step 4 - Sketch only (no extrude)

Type and Ask:

```
create a rectangular sketch 50 by 20
```

Expected: just a **Sketch** object (no solid yet). Double-click it: it opens in the
Sketcher workbench and you can edit it by hand - it is a real, editable sketch.
Close the sketch editor when done.

Then, with that sketch present, type and Ask:

```
extrude the sketch 15 mm
```

Expected: the sketch becomes a 15 mm-tall solid.

---

## Step 5 (optional) - A different plane

Type and Ask:

```
draw a 30x30 rectangle on the XZ plane and extrude it 8 mm
```

Expected: the sketch lies on the vertical XZ plane and the solid grows
perpendicular to it. (XY is the default and the most common; XZ / YZ are there for
vertical profiles.)

---

## If something does not work

- **Nothing happens / "Ask the agent" stays busy a long time**: the local model can
  be slow on modest hardware. There is a progress row with elapsed seconds and a
  **Cancel** button; you can cancel and try a shorter phrase. The structured
  "expert mode" (the command + parameters form) always works even without the AI.
- **"could not find object 'Sketch'"** on the extrude step: make sure a sketch was
  actually created first (Step 4). The agent normally creates it in the same
  request, so prefer the combined phrases of Steps 2 and 3.
- **The sketch shows but no solid**: re-read the engine window for an error message
  and tell me what it says; the most likely cause is an unusual plane/placement we
  can refine.
- Copy any red error text from the panel log or the engine window and send it to
  me - that is the fastest way to diagnose.

---

## What to report back

For each step: did you get the expected sketch/solid, and did Ctrl+Z undo it?
Steps 2 and 3 are the ones that matter most (they prove sketch -> extrude in plain
English). Steps 4 and 5 are nice-to-have.
