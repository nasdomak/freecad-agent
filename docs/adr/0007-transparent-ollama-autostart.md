# ADR 0007 - Transparent auto-start of the local AI (Ollama)

Status: Accepted (Phase 4, Session 7)
Date: 2026-06-24

## Context

Until now, if Ollama was not already running, the first natural-language request
failed with `WinError 10061 ... target machine actively refused it` on
`127.0.0.1:11434`. After every reboot the user had to remember to start Ollama by
hand before using natural language. This is friction for a non-developer who just
wants to open FreeCAD and start working.

Two facts make this easy to fix gracefully:

- The system already **degrades gracefully** (principle 9): the structured commands
  ("expert mode" in the panel) work with no AI at all; only natural language needs
  Ollama.
- `on_user_prompt` already **re-checks availability on every request**, so if Ollama
  is started *after* the engine, natural language resumes on its own - no engine
  restart needed. The only missing piece was launching Ollama automatically.

## Decision

Add a transparent auto-start of Ollama, implemented **in the engine (Python)**, not
in `START_ENGINE.bat`.

- New `engine/ollama_launch.py` with `ensure_running(client, ...)`: probe
  reachability; if down and the `ollama` executable is installed, launch
  `ollama serve` as a detached background process, wait a few seconds, and re-probe.
  Pure standard library (ADR 0004): only `os`, `shutil`, `subprocess`, `time`.
  All side effects (`which`, `spawn`, `sleep`, the reachability `client`) are
  injectable, so every branch is unit-tested without a real Ollama or a real launch.
- `Brain.ensure_server(log)` delegates to it using the brain's own client as probe.
- The engine calls it in **two places**:
  1. **At startup** (`serve_forever`), so launching `START_ENGINE.bat` ensures
     Ollama for the whole session.
  2. **Lazily on the first `user.prompt`** while Ollama is down (at most once per
     session), covering the case where Ollama is killed after the engine started.
- If Ollama is **not installed**, nothing is launched and the engine keeps running;
  the panel and engine messages make clear that structured commands still work and
  that natural language will resume by itself once Ollama is up.
- Kill switch: `FREECAD_AGENT_NO_AUTOSTART=1` disables auto-start entirely (used by
  the test suite and available to power users).

### Why the engine, not the .bat (the one notable choice)

The literal request was "make `START_ENGINE.bat` ensure Ollama". Implementing the
logic in the engine instead satisfies that (the .bat runs the engine) **and** is
strictly better for an open-source, cross-platform release (principle 9):

- One implementation serves Windows, macOS and Linux; a future `START_ENGINE.sh`
  inherits it for free, with no duplicated, OS-specific shell logic.
- It is unit-testable headless; batch/shell auto-start logic is not.

`START_ENGINE.bat` keeps a simple banner telling the user that Ollama is started
automatically. This is the recommended option; flagged here for Marco to confirm
a posteriori.

## Consequences

- The user can launch the engine (or just send a prompt) without thinking about
  Ollama; it is started for them when installed.
- The launched `ollama serve` is **detached** and intentionally **outlives** the
  engine window, so the model server stays available for the rest of the FreeCAD
  session (and for other tools). Stopping the engine with Ctrl+C does not stop
  Ollama; that is by design.
- No new dependency, no venv (ADR 0004 still holds): still a single double-click.
- Messages in the engine log and the panel now state explicitly that structured
  commands always work and that natural language resumes automatically once Ollama
  is reachable - no restart.

## Status of related nodes

- Closes **open node #2** (transparent Ollama start).
- Versions bumped engine + addon to `0.6.0-phase4`. Headless suite: 10/10 green
  (new `tests/test_ollama_launch.py`).
