# Test Guide - Phase 2.1 (new commands) + Phase 3 (geometric "eyes")

This guide is written for a non-developer. Follow it from top to bottom. Every
step says exactly what to open, click or type. When in doubt, do the steps in
order and do not skip the "Update" section.

What you are testing this time:
1. The five newer commands on REAL geometry: `drill_hole`, `boolean`,
   `chamfer`, `fillet` (and a note about `extrude`).
2. The new Phase 3 "eyes": before acting, the agent now inspects each object and
   gets its real edges/faces, so rounding/chamfering/drilling are more reliable.
3. A smarter hole: you no longer need to give coordinates - "drill a hole in the
   centre" now finds the top centre by itself.

---

## 0) Before you start - the update flow (IMPORTANT)

The code changed on BOTH sides this session, so you must refresh both.

- The **engine** changed (the brain). -> You only need to restart the engine.
- The **add-on** changed (the drilling command). -> You must re-install the
  add-on AND restart FreeCAD.

Do this, in order:

1. Make sure kDrive has finished syncing the project folder (wait for the green
   check on the folder) before continuing.
2. **Double-click `INSTALL_ADDON.bat`** (in the `freecad-agent` folder). Wait for
   it to say it finished. This copies the new add-on into FreeCAD.
3. **Close FreeCAD** completely if it is open, then **open it again**.
4. **Double-click `START_ENGINE.bat`**. A black window opens and stays open.
   Leave it open. Near the top it should say `ENGINE READY` and
   `v0.5.1-phase3`. It should also print one line about Ollama being
   "reachable".
   - If it says Ollama is NOT reachable: open Ollama first, then close this
     window and double-click `START_ENGINE.bat` again. (You can check Ollama any
     time with `CHECK_OLLAMA.bat`.)

Optional but recommended: **double-click `RUN_ALL_TESTS.bat`** once. It should end
with all tests PASS (9 of them). This proves the code is healthy before you even
touch FreeCAD.

---

## 1) Connect FreeCAD to the engine

1. In FreeCAD, open the **workbench selector** (the dropdown in the toolbar) and
   choose **FreeCAD Agent**.
2. The agent panel appears on the side. Click **Connect**.
3. The status dot should turn **green** ("connected"). If it stays red, make sure
   the `START_ENGINE.bat` window is still open, then click Connect again.

You will type the test phrases into the **"Ask in plain language"** box and press
**"Ask the agent"**. After each test, watch the 3D view and the panel log.

Tip: on a modest PC the model can take a while to answer (up to a few minutes).
That is normal - wait for the "completed" line in the log.

---

## 2) The tests (do them in order)

After EACH test, look at the 3D model. To undo, click in the 3D view and press
**Ctrl+Z** (once per created object; press it a few times to fully undo).

### Test A - a simple box (warm-up)
Type: `create a box 40 x 40 x 10`
Expect: a flat square box appears.
Keep it for the next test (do NOT undo yet).

### Test B - drill a centred hole (the headline fix)
With the box from Test A still there, type:
`drill a hole 8 mm wide and 10 mm deep in the centre`
Expect: a round hole straight through the middle of the box, from the top.
(Before this session the hole could end up below the box and do nothing - that is
what we fixed. The agent now finds the top centre on its own.)
Then press **Ctrl+Z** a few times to clear the document.

### Test C - boolean: subtract one shape from another
Type these three phrases, one at a time, waiting for each to finish:
1. `create a box 30 x 30 x 20`
2. `create a cylinder radius 8 height 40`
3. `subtract the cylinder from the box`
Expect: the cylinder carves a round tunnel out of the box.
Try the variant on a fresh document: `merge the box and the cylinder` (after
creating a box and a cylinder) - this fuses them into one piece.
Clear with **Ctrl+Z**.

### Test D - round and bevel the edges (now fixed - the headline of this session)
1. `create a box 30 x 20 x 10`
2. `round all the edges of the box with radius 3`
Expect: ALL the box edges become smooth and rounded.

Then, on a fresh box, try a chamfer (a flat bevel instead of a round):
`chamfer all the edges of the box with size 2`
Expect: all edges get a flat 45-degree bevel.

Finally, try the new partial selectors (you do NOT have to name any edge):
- On a fresh box: `round the top edges of the box with radius 2`
  Expect: only the 4 top edges are rounded.
- On a fresh box: `chamfer the vertical edges of the box with size 2`
  Expect: only the 4 upright corner edges are bevelled.

Clear with **Ctrl+Z** between attempts.

Why this now works: the agent no longer asks the small model to list every edge
by number (the part that used to fail). It rounds/chamfers ALL edges by default,
or a named group ("top", "bottom", "vertical", "horizontal"), and figures out the
exact edges itself from the real geometry. If a request ever refuses or picks the
wrong group, copy the panel log and tell me - but it should "just work" now.

### Test E - two steps in one sentence
On a fresh document, type:
`create a box 50 x 50 x 12 and drill a 10 mm hole in the centre`
Expect: the box is created AND drilled, in one go.

---

## 3) What to report back

For each test, just tell me:
- Did the expected shape appear? (yes / no / something else)
- Roughly how long it took.
- If something went wrong, copy the last few lines from the panel log (and from
  the black engine window if it shows an error).

Don't worry about fixing anything yourself - your job is only to run the phrases
and tell me what happened. I will adjust the code based on your report.

---

## Notes / known limits (so nothing surprises you)

- `extrude` is intentionally NOT in the test list: it needs a 2D sketch as input,
  and we don't have a "create sketch" command yet. We'll add that later.
- The little cosmetic toolbar-icon warning at start-up is still there; it does not
  stop the panel from working. Ignore it for now.
- If a request takes very long, the local model is just slow on this PC - that is
  not a bug, and we are not optimising for this specific machine on purpose.
