# FreeCAD Agent — Test Guide (Phase 2: the first AI brain)

This guide is written for a non-developer. Follow it top to bottom. Every step
says exactly what to open, click or type. You never need to use a terminal.

Phase 2 adds three big things on top of the Phase 1 skeleton:

1. **Natural language** — type a request in plain English and a *local* AI model
   (via Ollama, on your own computer) turns it into CAD actions.
2. **A bigger vocabulary** — besides `create_box` and `create_cylinder`, the agent
   now knows `drill_hole`, `extrude`, `chamfer`, `fillet` and `boolean`.
3. **Free Python with full transparency** — when no structured command fits, the
   agent can run FreeCAD Python; the panel **shows you the exact code** before it
   runs, always inside an undoable transaction (Ctrl+Z).

Nothing leaves your computer: the AI runs locally.

---

## Part A — Quick check WITHOUT FreeCAD (2 minutes)

This proves the code is healthy before you open FreeCAD.

1. Open the project folder `freecad-agent`.
2. Double-click **`RUN_ALL_TESTS.bat`**.
3. A black window opens and runs 8 checks. Wait until it finishes.
4. You should read **`RESULT: ALL TESTS PASSED.`** at the bottom. Press a key to
   close it.

If anything says FAILED, stop here and tell me what the window shows.

---

## Part B — Is the local AI ready? (one-time setup)

The agent needs **Ollama** (a free app that runs AI models locally).

1. Double-click **`CHECK_OLLAMA.bat`**.
2. Read what it says:
   - **"Ollama is NOT installed"** → install it from <https://ollama.com/download>,
     then open `CHECK_OLLAMA.bat` again.
   - **"The model qwen3:4b is NOT installed"** → the window tells you the one line
     to run to download it. (Any other model works too; this is just our test one.)
   - **"Natural language is ready"** → you are all set. Close the window.

> You only do Part B once. If you skip it, everything else still works — the agent
> will simply say it cannot use natural language, and you can still use the
> structured command panel.

---

## Part C — Update the add-on in FreeCAD

The workbench is already installed from Phase 1. You only need FreeCAD to reload
the updated files.

1. **Make sure kDrive has finished syncing** the project folder (the folder icon
   should be the green "available offline" check, not the blue syncing arrows).
   This avoids the workbench disappearing.
2. **Close FreeCAD completely** if it is open.
3. **Open FreeCAD** again.
4. From the workbench dropdown (top toolbar), pick **"FreeCAD Agent"**.
5. The **FreeCAD Agent** panel appears on the right. You should now see, from top
   to bottom: the connection status, **Connect/Disconnect**, an **"Ask in plain
   language"** box with an **"Ask the agent"** button, then the **structured
   command (expert mode)** section, the yellow **Free Python** banner, and the Log.

---

## Part D — Start the engine and connect

1. In the `freecad-agent` folder, double-click **`START_ENGINE.bat`**.
2. A window opens and stays open. Near the top it prints whether the local AI is
   reachable:
   - `local AI (Ollama): reachable [OK]` → natural language will work.
   - `local AI (Ollama): NOT reachable` → only structured commands will work.
   **Leave this window open.**
3. Back in FreeCAD, click **Connect** in the panel.
4. The status dot turns **green** ("Connected to engine"). The buttons enable.

---

## Part E — The first natural-language model (the headline test)

1. In the panel's **"Ask in plain language"** box, type:

   > create a box 30 by 20 by 15 mm

2. Click **"Ask the agent"**.
3. Watch the **Log**. You will see the agent's steps stream by:
   `perceiving` → `thinking (local model)` → `executing action 1: create_box` →
   `completed`.
4. A **box appears** in the 3D view. 
5. Press **Ctrl+Z**: the box is undone. Press **Ctrl+Y** to redo if you like.

Now try a two-step request:

   > add a 6 mm hole through the top of the box, in the middle

The agent perceives the existing box, plans a `drill_hole`, and you should see a
hole appear. (Small local models are not perfect — if it misunderstands, rephrase
more concretely, e.g. *"drill a hole, diameter 6, depth 15, at position 15,10,15"*.)

> **Slow first answer?** The very first request after starting Ollama can take
> 10–60 seconds while the model loads into memory. Later requests are faster.

---

## Part F — See the "Free Python" transparency in action

Ask for something the structured vocabulary does **not** have yet, for example:

   > create a sphere of radius 8 mm

Because there is no `create_sphere` command, the agent may propose **free Python**.
When it does:

1. The yellow banner turns **red** and shows the **exact Python code** the agent is
   about to run, with the reason.
2. The code runs inside an undoable transaction, so **Ctrl+Z** reverts it.

This is principle 5 (transparency): you always see free Python before it acts.

---

## Part G — Expert mode (structured commands, no AI)

You can still drive the agent precisely without the model:

1. In the **structured command (expert mode)** section, pick a command from the
   dropdown (e.g. `boolean`).
2. Fill the fields. For commands that reference existing objects, use the object's
   name as shown in FreeCAD's model tree (e.g. `Box`, `Cylinder`). For `edges`,
   type something like `Edge1,Edge2`.
3. Click **Run**. The result appears in the Log; **Ctrl+Z** undoes it.

This path does not need Ollama at all.

---

## If something goes wrong

- **Panel says "Not connected"** → start `START_ENGINE.bat`, then click Connect.
- **"Agent could not run it: Cannot reach the local AI…"** → run `CHECK_OLLAMA.bat`
  (Part B). Structured commands still work meanwhile.
- **Workbench missing after restart** → wait for kDrive's green check before
  starting FreeCAD, then restart it.
- **The model does something odd** → press Ctrl+Z to undo, rephrase more concretely,
  and tell me what you typed and what happened.

Everything you do here is reversible. You cannot break anything by trying.
