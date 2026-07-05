# Test guide — Phase 1 (the usable skeleton, still without AI)

This guide is meant for non-developers. Everything is done with double-clicks and
a few clicks in FreeCAD. Time required: ~10 minutes.

What we test in this phase:
- the add-on becomes a real FreeCAD **workbench** (it appears in the top bar),
  with a **panel** on the right;
- the **engine** stays running and accepts **multiple commands** in a row (before
  it did just one);
- from the panel you pick a command (e.g. *create_box*), send it, and the object
  appears in FreeCAD; **Ctrl+Z** undoes it.

No artificial intelligence is needed yet: the engine acts as a "pass-through"
that **validates** the command and sends it back to the add-on.

---

## Test A — Without FreeCAD (optional, 1 minute)

This only checks that the engine works on your PC.

1. Double-click **`RUN_ALL_TESTS.bat`** (in the `freecad-agent` folder).
   You should see three **PASS** lines. If so, the system's "brain" is fine.
2. (Optional) Double-click **`TEST_WITHOUT_FREECAD.bat`**: it opens the engine and
   a "fake add-on" that sends it two commands (one valid and one wrong). You
   should see `handshake`, then one command **executed** and one **gracefully
   rejected**.

If these pass, move on to FreeCAD.

---

## Test B — In FreeCAD (the heart of Phase 1)

### Step 1 — Install the add-on as a workbench (once)

1. Close FreeCAD if it is open.
2. Double-click **`INSTALL_ADDON.bat`** (in the `freecad-agent` folder).
   It links the add-on into FreeCAD. **No administrator needed.** It should end
   with *"DONE"*.
3. Reopen FreeCAD.

> Note: the link is "live". If the add-on is updated later, just restart FreeCAD:
> you don't need to reinstall anything.

### Step 2 — Start the engine

1. Double-click **`START_ENGINE.bat`**.
2. A black window opens saying **"ENGINE READY"**. **Leave it open.**
   (To stop it later: click that window and press `Ctrl + C`.)

### Step 3 — Open the panel in FreeCAD

1. In FreeCAD, the top bar has a dropdown listing the *workbenches* (usually shows
   "Start" or "Part"). Open it and pick **"FreeCAD Agent"**.
2. The **"FreeCAD Agent" panel** appears on the right.
   (If you don't see it: menu **View → Panels → FreeCAD Agent**.)

### Step 4 — Connect and create a box

1. In the panel click **«Connect»**.
   - The dot at the top turns **green** ("Connected to engine").
   - The handshake lines appear in the log.
2. Under *"Structured command"* leave **`create_box`** selected.
3. Fill the fields (`*` are required), for example:
   - `length` → `20`
   - `width` → `15`
   - `height` → `10`
   - `placement` (optional) → leave empty, or type `0,0,0`
4. Click **«Run»**.
   - The log shows the states scrolling: *validation → execution → completed*.
   - A **box** appears in FreeCAD (you may need to "fit to view"/scroll to see it).
5. **Press `Ctrl + Z`** in FreeCAD: the box **disappears** (reversibility).
   Press `Ctrl + Y` to redo it, if you like.

### Step 5 — Try the second command and a wrong command

1. In the command dropdown pick **`create_cylinder`**, set `radius` `8` and
   `height` `25`, click **«Run»**: a cylinder appears. (This shows that adding
   commands is easy.)
2. Go back to `create_box`, leave `height` **empty** and click «Run»: the panel
   tells you **«required parameter "height" is empty»** and does nothing. If
   instead you fill the fields with absurd values (e.g. negative `length`), the
   **engine** **gracefully rejects** it and you see it written in the log. No
   harm to the drawing.

### Step 6 — Multiple commands and reconnection

- You can click «Run» many times: the engine **stays running** and handles them
  all (before it closed after one).
- If you close and reopen the engine window, click **«Connect»** again in the
  panel: it reattaches.

---

## What to look at / what to report

All good if: green dot, the box and the cylinder appear, `Ctrl+Z` undoes them,
wrong commands are rejected without harm, and you can run several commands in a row.

If something goes wrong, tell me:
- which **step** you got stuck at;
- what the **panel log** says (you can copy it);
- what the **black engine window** says;
- whether FreeCAD's UI **froze** even for a moment (that's the point we watch:
  RISK #2, threads with Qt).

---

## Command cheat sheet

| Command | What it does | Parameters |
|---|---|---|
| `create_box` | creates a box | length*, width*, height*, placement |
| `create_cylinder` | creates a cylinder | radius*, height*, placement |

(`*` = required. Dimensions in millimetres. `placement` = position `x,y,z`.)

The "old" method (launching the `addon/start_bridge_client.FCMacro` macro by hand)
still works as a shortcut, but with the workbench installed it is **no longer needed**.
