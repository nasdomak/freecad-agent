# Test guide - Session 12: start the engine from FreeCAD

This session removes `START_ENGINE.bat` from the normal workflow. The engine now
starts BY ITSELF when you click **Connect** in the panel. This guide is written for
a non-developer: do it step by step.

## Before you start (update the add-on)

Both the add-on and the engine changed, so refresh the installed copy:

1. Open the project folder in kDrive and wait until it is fully synced
   (the folder icon is green, no rotating arrows).
2. Double-click **`INSTALL_ADDON.bat`**. Wait for "DONE".
3. **Close FreeCAD completely and reopen it.**
4. If Ollama is installed on your PC, leave it as it is (the engine will start it
   for you if needed). Nothing to launch by hand.

## Test A - the engine starts by itself (the main test)

1. In FreeCAD, pick the **FreeCAD Agent** workbench (top toolbar dropdown).
   The panel appears on the right.
2. Look at the panel: the light says **Disconnected**, and **Engine: stopped**.
3. Click **Connect**.
   - The status goes **Connecting…** then **Connected to engine** (green).
   - The engine indicator turns **Engine: running** (green).
   - You did NOT open `START_ENGINE.bat`, and there is no black engine window.
4. In the box **"Ask in plain language"** type:
   `create a box 30x20x15`
   then click **Ask the agent**. A Box should appear. Press **Ctrl+Z** to undo.

If you see the Box, the engine started from FreeCAD and everything works.

## Test B - stop the engine (no leftover process)

1. Click **Stop engine**.
   - The status returns to **Disconnected**, **Engine: stopped**.
2. (Optional check) Open Windows Task Manager: there should be no leftover
   `python.exe` running the engine.
3. Click **Connect** again: it starts a fresh engine and reconnects.

## Test C - closing FreeCAD stops the engine

1. With the engine **running** (connected), simply **close FreeCAD**.
2. The engine process is terminated automatically (no orphan). Reopen FreeCAD and
   click **Connect** again to verify it still starts cleanly.

## Test D - see the engine log (if something looks off)

1. Click **Show engine log**. The last lines of the engine log appear in the panel
   log area (this is the file `~/.freecad-agent/engine.log`).
2. Useful if Connect fails: the log usually says why (e.g. Python not found).

## Test E (optional, for debugging only) - the old .bat still works

You normally never need this. It is kept only for debugging.

1. In the panel, tick **"Debug: attach to a manually-started engine"**.
2. Double-click **`START_ENGINE.bat`** (a black window opens: the standalone
   engine). Leave it open.
3. Click **Connect**. The panel attaches to that engine (using the discovery file)
   instead of launching its own. Untick the box to go back to the normal mode.

## If Connect fails

- Click **Show engine log** and read the last lines.
- Most likely cause: the add-on could not find a Python interpreter. In that case
  the log says so. Tell me what the log shows and I will help.
- You can always fall back to Test E (debug mode) while we investigate.

---

Automated tests (no FreeCAD needed): double-click **`RUN_ALL_TESTS.bat`** - it
should end with **ALL TESTS PASSED** (21 tests, now including the topology flip and
the engine launcher).
