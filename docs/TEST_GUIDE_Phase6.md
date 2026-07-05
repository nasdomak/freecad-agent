# Test Guide - Phase 6 (Modelling), Blocks A + B + C

This guide validates everything Phase 6 added for MODELLING, in plain English. No
coding needed - type each phrase, one at a time, into the panel's "Ask in plain
language" box and click **Ask the agent**, in the order shown.

Vocabulary now has **14 commands** (engine + add-on `0.10.0-phase6`):

- Block A - **move**, **rotate** (already validated in Session 10).
- Block B - **mirror** (reflect across a plane), **array** (a row, or a circle of
  copies).
- Block C - **sketch_on_face** (draw on an existing face) + **extrude** with
  **op = cut** (a pocket) or op = add (a boss).

Everything is reversible: **Ctrl+Z** undoes the last action.

---

## Step 0 - Update both parts (important)

This release changed BOTH the add-on and the engine, so refresh both.

1. Wait until kDrive has finished syncing the project folder (folder icon green /
   "up to date"). This avoids half-downloaded files.
2. Double-click **INSTALL_ADDON.bat** (copies the new add-on into FreeCAD).
3. If FreeCAD is open, **close and reopen it** so it loads the new add-on.
4. Double-click **START_ENGINE.bat** (start, or restart if already running) so the
   engine picks up the new commands. Leave its window open.

You do NOT need to start Ollama yourself: the engine starts it for you if it is
installed. Tip: in the top toolbar use View -> Standard views -> Axonometric (or
press 0) so you can see the geometry clearly.

---

## Step 1 - Open the panel and connect

1. In FreeCAD, switch the workbench selector (top toolbar) to **FreeCAD Agent**.
2. The panel appears on the side. Click **Connect**; the status light turns green.
3. Make sure you have an active document (File -> New if the 3D area is empty).

---

# BLOCK A - Move and Rotate (re-check)

Type these one at a time:

```
create a box 30x20x10
```
Expected: a **Box** appears at the origin.

```
move Box 25 mm along X
```
Expected: the box slides 25 mm in +X.

```
move Box up 15 mm
```
Expected: it moves 15 mm up (+Z). Press **Ctrl+Z** twice and watch it step back.

```
rotate Box 45 degrees around Z
```
Expected: the box turns 45 degrees about the vertical axis, **staying in place**
(it spins around its own centre, it does not fly off).

```
rotate Box 90 degrees around X
```
Expected: it tips over about X. **Ctrl+Z** undoes each rotation.

```
move Box to 0, 0, 0
```
Expected: the box jumps back so its origin is at the world origin (absolute move).

Before Block B, undo back to a single clean box at the origin (press **Ctrl+Z**
until only the original Box remains), or start a new document and re-create it.

---

# BLOCK B - Mirror and Array

### B1 - Mirror

Make an off-centre box so the reflection is obvious:

```
create a box 40x10x10 at 20, 0, 0
```
Expected: a box sitting to the +X side of the origin.

```
mirror Box across the YZ plane
```
Expected: a SECOND box appears on the opposite (-X) side, a mirror image. The
ORIGINAL stays. **Ctrl+Z** removes the mirrored copy.

### B2 - Linear array (a row)

Start clean (new document, or undo to one box), then:

```
create a box 10x10x10
```
```
make a row of 5 copies of Box 20 mm apart along X
```
Expected: **5 boxes in total** in a row along X, 20 mm apart (the original plus 4
copies). **Ctrl+Z** removes the copies in one step.

### B3 - Polar array (a circle)

A circular array makes the items ORBIT a central axis. By default that axis is the
**file's Z axis (the origin)**, NOT the object's own axis - so the object must sit
AWAY from the centre to form a ring (otherwise the copies would land on top of each
other). Two ways to get the ring:

Way 1 - move the object out first, then orbit. Start clean, then:

```
create a cylinder radius 4 height 30
```
```
move Cylinder 30 mm along X
```
```
arrange 6 copies of Cylinder in a circle around Z
```
Expected: **6 cylinders** evenly spaced around the file's Z axis, at radius 30 (a
bolt-circle). They must NOT all sit in the same spot. **Ctrl+Z** removes the copies.

Way 2 - give the radius directly (the agent places the ring for you). Start clean,
then:

```
create a cylinder radius 4 height 30
```
```
arrange 8 copies of Cylinder on a circle of radius 40 around the Z axis
```
Expected: **8 cylinders** on a circle of radius 40 around the origin, even if the
cylinder started on the axis (the agent moves it onto the circle first).

If you want the circle around a different point, say so, e.g. "...around the point
0, 0, 0" or name a centre; the agent uses that instead of the default origin.

### B4 - Create-and-duplicate in one phrase (id-chaining)

This checks the agent can operate on something it just made, in a single request:

```
create a box 25x25x5 and mirror it across the XZ plane
```
Expected: a box AND its mirror across XZ, from one sentence. (If the box gets an
internal name like `Box001`, the agent still links the mirror to it correctly.)

---

# BLOCK C - Build features on a face (boss and pocket)

Start clean, then make a base plate:

```
create a box 60x60x10
```
Expected: a flat plate.

### C1 - A raised boss (sketch on the top face + extrude add)

```
draw a 20x20 rectangle on the top face of Box and extrude it 8 mm
```
Expected: a square block RISES 8 mm out of the top face of the plate. **Ctrl+Z**
twice removes the boss and its sketch.

### C2 - A pocket (sketch on the top face + extrude cut)

```
cut a round pocket of radius 8, 5 mm deep, into the top of Box
```
Expected: a round hole/pocket is carved 5 mm DOWN into the top face (material
removed, not added). **Ctrl+Z** restores the solid.

### C3 - Pocket with a rectangle (optional)

```
cut a 30x10 rectangular pocket 4 mm deep into the top of Box
```
Expected: a rectangular slot sunk 4 mm into the top face.

The key things to confirm in Block C: the sketch lands ON the chosen face (you did
NOT have to name a face number), a boss goes OUT and a pocket goes IN.

---

## If something does not work

- **"Ask the agent" stays busy a long time**: the local model can be slow on modest
  hardware. There is a progress row with elapsed seconds and a **Cancel** button;
  cancel and try a shorter phrase. The structured "expert mode" (command +
  parameters form) always works even without the AI.
- **"object 'Box' not found"**: the object may have a different internal name (e.g.
  `Box001`). Check the model tree on the left for the exact name, or say "mirror the
  box ..." and let the agent read the document.
- **A pocket adds material instead of removing it (or vice-versa)**: tell me - the
  cut direction should go into the body. Send the red error text from the panel log
  or the engine window; that is the fastest way to diagnose.
- **The mirror/array copy lands in an unexpected spot**: note the exact phrase you
  used and what you saw, and send it over.

---

## What to report back

For each block, did the geometry appear as described, and did **Ctrl+Z** undo it?
The phrases that matter most:

- Block B: "make a row of 5 copies ..." (linear array) and "arrange 6 copies ... in
  a circle" (polar array), plus the one-sentence "create a box ... and mirror it"
  (id-chaining).
- Block C: "draw a ... rectangle on the top face ... and extrude it" (boss) and
  "cut a ... pocket ... into the top" (pocket).

Once Blocks A+B+C are confirmed, Session 12 is the final end-to-end test with more
complex, multi-step components.
