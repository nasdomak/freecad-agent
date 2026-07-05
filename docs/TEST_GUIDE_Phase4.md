# Test Guide - Phase 4 (transparent Ollama auto-start)

This guide is written for a non-developer. Follow it from top to bottom. Every
step says exactly what to open, click or type.

What you are testing this time:
1. You no longer have to start Ollama by hand. When you start the engine, it
   starts Ollama for you (if Ollama is installed).
2. If Ollama is off, the panel still works: the **structured commands** ("expert
   mode") run without it, and **natural language comes back on its own** once
   Ollama is up - no need to restart anything.

This session changed only the **engine** and the **add-on panel text**. To be safe,
refresh both.

---

## 0) Before you start - the update flow (IMPORTANT)

1. Make sure kDrive has finished syncing the project folder (green check on the
   folder) before continuing.
2. **Double-click `INSTALL_ADDON.bat`** (in the `freecad-agent` folder). Wait for
   it to say it finished. (The panel text changed, so re-install the add-on.)
3. **Close FreeCAD** completely if it is open, then **open it again**.

You will start the engine inside the tests below.

Optional but recommended: **double-click `RUN_ALL_TESTS.bat`** once. It should end
with **RESULT: ALL TESTS PASSED** (now 10 tests).

---

## Test A - the engine starts Ollama for you

1. **Important first step:** make sure Ollama is **NOT** already running, so you
   can see the engine start it. The simplest way: restart your PC and do NOT open
   anything. (Or, if you know how, quit Ollama from the system tray.)
2. **Double-click `START_ENGINE.bat`.** A black window opens and stays open.
3. Watch the lines near the top. You should see, in order:
   - a line like `local AI (Ollama) not reachable - starting it for you ...`
   - then `local AI (Ollama) auto-start: started - started the local AI (Ollama)
     automatically.`
   - then `local AI (Ollama): reachable [...]. model=...`
   - then `ENGINE READY` and `v0.6.0-phase4`.
4. In FreeCAD, pick the **FreeCAD Agent** workbench, open the panel, click
   **Connect** (the dot turns green).
5. In **Ask in plain language**, type: `create a box 20x20x10` and click
   **Ask the agent**. A box should appear. (Ctrl+Z undoes it.)

**Expected:** you never opened Ollama yourself, yet natural language worked.

> Note: the engine starts Ollama in the background and leaves it running on
> purpose, so it stays ready for the rest of your session. Pressing Ctrl+C in the
> engine window stops the engine, not Ollama.

---

## Test B - working while Ollama is off (graceful degradation)

This shows that you can start working even if Ollama is not available.

1. Temporarily make Ollama unavailable: the easy way is to set the kill switch so
   the engine does NOT auto-start it. Close the engine window, then in the same
   folder **double-click `START_ENGINE.bat`** again - but first we disable
   auto-start so you can see the "off" behaviour:
   - Press the Windows key, type `cmd`, open Command Prompt.
   - Paste this line and press Enter (it sets the switch only for that window):
     `set FREECAD_AGENT_NO_AUTOSTART=1`
   - Then in the SAME window paste (adjust the path if needed) and press Enter:
     `cd /d "%USERPROFILE%\kDrive\003_Sigic\001_Progetti\000009___Freecad_copilot\freecad-agent\engine" && py bridge_server.py`
   - The engine starts but the line will say Ollama is **NOT reachable**.
   - (If `py` is not found, use `python` instead.)
2. In the panel, in **Structured command (expert mode)**, choose `create_box`,
   fill the sizes, and click **Run**. **It works** - structured commands do not
   need Ollama.
3. Now type a natural-language request and click **Ask the agent**. You get a
   clear message that natural language needs the local AI, that structured
   commands work meanwhile, and that it will resume by itself when Ollama is up.

**Expected:** structured commands always work; natural language fails politely
with a helpful message (no scary `WinError 10061`).

---

## Test C - natural language resumes by itself (no restart)

Continue from Test B (engine still running, Ollama still off).

1. Leave the engine window open. Start Ollama by hand now (open the Ollama app, or
   run `ollama serve` in another window).
2. Wait a few seconds. **Without** restarting the engine or reconnecting, type a
   natural-language request again and click **Ask the agent**.

**Expected:** it now works. The engine re-checks Ollama on every request, so
natural language comes back on its own.

---

## Test D - progress bar and Cancel on a slow request (new)

This checks the new progress indicator and the Cancel button.

1. With the engine running and Ollama on, type a request that takes a moment, for
   example: `create a box and round all its edges with radius 2`, then click
   **Ask the agent**.
2. While it works you should see, under the button, a **moving progress bar**, an
   **elapsed-time** counter (`working… 3s`, `4s`, ...) and a **Cancel** button. If
   it runs long, the log adds a one-time note that a slow local model is normal.
3. Let this first one finish normally (the shape appears).
4. Now send another request and, **while the progress bar is moving**, click
   **Cancel**. The button shows `Cancelling…`, and shortly the log says it stopped
   on request. The agent does **not** create new geometry after you cancel.
   - If part of a multi-step request had already been applied before you cancelled,
     it stays; press **Ctrl+Z** once per applied step to undo it.

**Expected:** you can see progress, and Cancel stops the agent cleanly. (Note: if
the model is mid-thinking, Cancel takes effect the moment that step finishes - it
will not apply the result.)

### The "Limit AI wait time" option (new)

Just above the **Ask the agent** button there is a **Limit AI wait time** tick box
with a seconds field next to it.

- **Default: OFF = no time limit.** The agent waits as long as the local model
  needs. If a request runs too long, stop it with **Cancel** (Test D).
- **Tick it** to set a cap: the seconds field becomes active; choose how long the
  agent waits for ONE local-model reply before giving up. This replaces setting the
  `FREECAD_AGENT_OLLAMA_TIMEOUT` environment variable by hand. The setting is sent
  with every request, so just change it and click **Ask the agent**.

To check the cap works, tick the box, set a small value like `30`, and send a heavy
request on slow hardware: it should give up at about 30s (a timeout message in the
log) instead of waiting indefinitely. Untick the box to go back to no limit.

> Also fixed this session: the harmless `addCommand failed` / missing toolbar icon
> message at startup is gone. The Report view should now show only
> `[FreeCAD Agent] workbench initialized.` (the `QWindowsWindow::setGeometry` line,
> if present, is an unrelated Qt notice).

---

## If something looks wrong

- The engine window flashes and closes: tell me - it usually means a file did not
  sync. Wait for kDrive's green check and try again.
- `RUN_ALL_TESTS.bat` does not end with ALL TESTS PASSED: open `tests_output.txt`
  in the same folder and send me the bottom part.
- You want to check Ollama any time: **double-click `CHECK_OLLAMA.bat`**.
