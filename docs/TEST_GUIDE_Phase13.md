# Test guide - Session 13: complex components (final shakedown)

This is the FINAL test session before the open-source release. Instead of single
commands, you will build four small REAL parts with multi-step natural-language
sequences. The same sequences are the shot list for the demo video (Session 14).

Written for a non-developer: follow it step by step, paste the phrases EXACTLY
as printed (one phrase = one "Ask the agent" click).

## Before you start

1. Nothing in the code changed since Session 12, so if the add-on worked in your
   last test you are already up to date. If unsure: wait for the kDrive icon to
   be green, double-click **`INSTALL_ADDON.bat`**, wait for "DONE", then restart
   FreeCAD.
2. Ollama: leave it as it is. On your PC it starts at boot, which is what we
   want today (all tests use the AI). Reminder for other sessions only: to test
   the "AI off" branches you must quit Ollama from the system tray.
3. In FreeCAD pick the **FreeCAD Agent** workbench, click **Connect** in the
   panel. The engine starts by itself: **Engine: running** (green), status
   **Connected to engine**.

### General rules for every test

- Start each component in a FRESH document: menu **File > New**. This makes the
  object names in the phrases predictable (Box, Cylinder, Drilled, ...).
- Paste ONE phrase at a time into "Ask in plain language", click **Ask the
  agent**, WAIT until the busy bar disappears and the result is in the log.
- Object names: look at the model tree (left side). After each step I tell you
  the name the new object should have. If a name on your screen differs (e.g.
  `Drilled005` instead of `Drilled001` because a step was repeated), use the
  name YOU see in the tree in the next phrase.
- **Ctrl+Z** undoes one step at a time (each command is one transaction).
- If a step fails: copy the error text from the panel log, click **Show engine
  log** and copy the last lines too, note WHICH phrase it was, and send me all
  of it. Then continue with the next component if possible.

---

## Component 1 - Drilled flange (centre bore + 4 bolt holes + rounded rim)

Goal: a round flange with a through bore in the middle, four through bolt
holes on a circle, and a rounded top rim. Checks: drilling at explicit
positions, holes really go THROUGH, fillet with the "top" selector.

File > New, then paste one line at a time:

1. `create a cylinder of radius 40 and height 10`
   - A flat disc appears. Tree: **Cylinder**.
2. `drill a 16 mm hole in the centre of Cylinder, 12 mm deep`
   - Centre bore. Tree: **Drilled** (the disc now has a hole in the middle).
3. `drill an 8 mm hole 12 mm deep in Drilled at position [28, 0]`
   - First bolt hole, right side. Tree: **Drilled001**.
4. `drill an 8 mm hole 12 mm deep in Drilled001 at position [0, 28]`
   - Second bolt hole. Tree: **Drilled002**.
5. `drill an 8 mm hole 12 mm deep in Drilled002 at position [-28, 0]`
   - Third bolt hole. Tree: **Drilled003**.
6. `drill an 8 mm hole 12 mm deep in Drilled003 at position [0, -28]`
   - Fourth bolt hole. Tree: **Drilled004**.
7. `round the top edges of Drilled004 with radius 2`
   - The top rim (and the top edge of each hole) gets rounded. Tree: **Fillet**.

**What to verify**
- Rotate the view (hold middle mouse button / use the navigation cube) and look
  from BELOW: all five holes must be visible from the bottom too (they are
  THROUGH holes - depth 12 on a 10 mm disc).
- The four bolt holes sit on a circle around the centre, 90 degrees apart.
- Press Ctrl+Z once: the fillet disappears. Ctrl+Z again: the last hole comes
  back closed. (Then Ctrl+Shift+Z / Redo if you want the part back.)

---

## Component 2 - Bracket (pocket on the top face + fixing hole + chamfer)

Goal: a block with a centred rectangular pocket sunk into its top face, a
fixing hole through the pocket floor, and a chamfered top. Checks: sketch on
face, pocket cuts the RIGHT body and is centred (ADR 0013/0014), drilling
through a stepped body.

File > New, then:

1. `create a box 80x50x15`
   - Tree: **Box**.
2. `cut a rectangular pocket 40x20, 6 mm deep, into the top of Box`
   - A rectangular cavity, CENTRED on the top face. Tree: **Pocket** (plus a
     hidden **Sketch**). The cavity must be sunk INTO the box (not a boss
     sticking out, not a cut through some other object).
3. `drill a 6 mm hole 20 mm deep in the centre of Pocket`
   - A hole in the middle of the pocket floor, going through to the bottom of
     the block. Tree: **Drilled**.
4. `chamfer the top edges of Drilled by 1`
   - The top rim of the block (and of the pocket) gets a flat bevel.
     Tree: **Chamfer**.

**What to verify**
- The pocket is centred (equal margins all around) and 6 mm deep.
- Look from below: the small hole exits the bottom face (through hole).
- The chamfer is on the TOP edges only.

---

## Component 3 - Patterns (polar ring, linear row, mirror)

Goal: verify the duplication tools. The KEY check is the polar array: the
copies must ORBIT the centre of the file (forming a ring), NOT spin on
themselves and overlap (the Session 11 bug - it must stay fixed).

File > New, then:

1. `create a cylinder of radius 8 and height 30 and move it 35 mm along X`
   - One pillar, standing 35 mm to the right of the origin. Tree: **Cylinder**.
   - (This also checks "operate on what I just created": create + move in ONE
     phrase.)
2. `arrange 6 copies of Cylinder in a circle around the Z axis`
   - **THE ORBIT CHECK.** You must see a RING of 6 pillars, evenly spaced
     (60 degrees apart), all at the same distance from the centre. Tree:
     **Cylinder** plus 5 copies named **Cylinder_copy**, **Cylinder_copy001**, ...
   - WRONG result (report it!): pillars stacked on top of each other at one
     spot, or a single pillar that just rotated.
3. `create a box 15x15x25`
   - A block appears at the origin, in the middle of the ring. Tree: **Box**.
4. `make a row of 4 copies of Box, 15 mm apart along X`
   - The block becomes a contiguous row of 4 (they touch: spacing = width).
     Tree: **Box_copy**, **Box_copy001**, **Box_copy002**.
5. `mirror Box across the YZ plane`
   - A mirrored twin of the first block appears on the LEFT side of the origin
     (the original stays). Tree: **Mirror**.
6. (optional) `merge Box and Box_copy`
   - The first two blocks of the row become ONE solid. Tree: **Union**.

**What to verify**
- Step 2 makes a ring (orbit), not an overlap.
- Step 4 spaces the copies along X, all aligned.
- Step 5 keeps the original AND adds the mirrored one.

---

## Component 4 - Complete part (only if 1-3 passed)

Goal: one realistic part in 6 steps mixing everything: base plate, rounded
corners, a centred boss grown from a sketch on the face, a boolean union, a
through bore, a final chamfer. This is the "whole component" stress test of
id-chaining across many steps - and the hero sequence for the video.

File > New, then:

1. `create a box 90x60x12`
   - Base plate. Tree: **Box**.
2. `round the vertical edges of Box with radius 8`
   - The four corners of the plate get rounded. Tree: **Fillet**.
3. `draw a circle of radius 15 on the top face of Fillet and extrude it 25 mm`
   - A cylindrical BOSS grows from the middle of the top face. Tree:
     **Extrude** (plus a hidden Sketch).
4. `merge Fillet and Extrude`
   - Plate and boss become one solid. Tree: **Union**.
5. `drill a 12 mm hole 40 mm deep in the centre of Union`
   - A bore straight down the middle of the boss, through the boss AND the
     plate (look from below: the hole exits the bottom). Tree: **Drilled**.
6. `chamfer the top edges of Drilled by 1.5`
   - The top rim of the boss and of the bore get a bevel. Tree: **Chamfer**.

**What to verify**
- The boss is centred on the plate and the bore is centred in the boss.
- The bore is a THROUGH hole (visible from below).
- The corner fillets from step 2 survived all later steps.

---

## Stress test S1 (optional, AFTER the four components)

UPDATED after the first run (engine 0.12.0, ADR 0016): the engine now redirects
each drill to the LIVE result of the previous one, so this single phrase is
expected to WORK. Do it last, in a fresh document (File > New):

`create a cylinder of radius 40 and height 10, then drill four 8 mm holes 12 mm deep into it at positions [28, 0], [0, 28], [-28, 0] and [0, -28]`

- EXPECTED result: ONE disc with four through holes (like Component 1 in one
  shot). In the log you should see `linking` lines like
  `'Cylinder' -> 'Drilled'`: that is the engine re-aiming each drill.
- IMPORTANT: give the positions EXPLICITLY, as above. Phrasings like "four
  holes equally distributed on a radius of 20" ask the model to compute
  coordinates with trigonometry - beyond a small local model, and a documented
  limit of the MVP (not a bug we chase).
- If it still fails, tell me what you see in the tree and copy the panel log.

---

## What to report back

For each component: PASS / FAIL, plus for any failure the phrase, the panel
log text, and the last lines of **Show engine log**. Screenshots help.

If all four components pass, Session 13 is done and we are GO for the release
session (Session 14). These same sequences become the video storyboard.

---

Automated tests (no FreeCAD needed): double-click **`RUN_ALL_TESTS.bat`** - it
must still end with **ALL TESTS PASSED** (21 tests).
