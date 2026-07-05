# ADR 0015 - Engine lifecycle managed by the add-on + flip to the production topology

Status: ACCEPTED (Session 12)
Date: 2026-07-01
Supersedes for production: ADR 0002 (prototype topology), the discovery-file path of ADR 0003.
Related: ADR 0001 (symmetric bridge), ADR 0004 (pure-stdlib engine), ADR 0007 (transparent Ollama).

## Context

Until now the user had to start the engine by hand (`START_ENGINE.bat`) before
clicking *Connect* in the panel. In that prototype topology (ADR 0002) the ENGINE
was the TCP server: it picked an ephemeral port, generated a token, and wrote a
discovery file (`~/.freecad-agent/bridge.json`); the ADD-ON was the client and read
that file to attach.

For a worldwide open-source release this is unacceptable: a non-developer must be
able to start everything from inside FreeCAD, on Windows/macOS/Linux, with nothing
to launch from disk. Marco asked to do this now AND, at the same time, to flip to
the production topology foreseen by ADR 0002.

Two facts make this cheap and safe:
1. The engine is pure stdlib (ADR 0004), so it can run on the Python interpreter
   BUNDLED with FreeCAD - zero installation for the user.
2. The bridge core is symmetric and bidirectional (ADR 0001), so either side can be
   the TCP server; only the handshake direction needs to swap.

## Decision

### 1. The add-on starts the engine as a SEPARATE process
On *Connect* the add-on launches `engine/bridge_server.py` as its own OS process
(principle 3: the brain stays a separate, swappable process - NOT in-process),
using FreeCAD's bundled Python (`FreeCAD.getHomePath()` + `bin/python(.exe)`, with
reasoned fallbacks to the current interpreter and to `python`/`python3` on PATH).
The engine's stdout/stderr are redirected to `~/.freecad-agent/engine.log`, so no
console window is required. Implemented in `addon/ai_copilot/engine_launcher.py`
(`EngineLauncher.ensure_running` / `stop`, both with injectable interpreter finder
and spawn for headless tests).

### 2. Topology flip: the ADD-ON is now the TCP server
The add-on opens a loopback socket (`127.0.0.1`, ephemeral port) and generates the
token. It passes host/port/token to the engine on the command line
(`--host --port --token`). The engine connects back as a CLIENT and presents the
token via `session.hello`; the ADD-ON validates it. **No more discovery file in the
production path.** Only the handshake roles swap: every operational handler keeps
its direction (the add-on still exposes `command.execute`/`perception.*`/
`python.execute`; the engine still exposes `command.request`/`user.prompt`/
`user.cancel`).

### 3. The engine has TWO run modes (debug is preserved)
`bridge_server.py::main()` decides at startup:
- **CLIENT mode (production):** if it receives `--host/--port/--token` (or the env
  vars `FREECAD_AGENT_HOST/PORT/TOKEN`), it connects to the add-on server and greets
  it with the token (`run_as_client`).
- **SERVER standalone mode (debug):** with no connection args it behaves as before
  (ephemeral port + token + discovery file), so `START_ENGINE.bat` keeps working for
  our own debugging. The panel has a *"Debug: attach to a manually-started engine"*
  checkbox that switches the add-on back to CLIENT/attach mode for this case.

### 4. UX and lifecycle
- Auto-start on *Connect* (open the server, launch the engine, wait for the
  handshake); explicit *Stop engine* button; an *Engine: running/stopped* status
  light; a *Show engine log* button that tails the engine log file.
- No double start: `EngineLauncher` does not relaunch an engine it already runs.
- Clean shutdown: the panel terminates the engine on *Stop engine*, on disconnect,
  and on FreeCAD exit (`QApplication.aboutToQuit`) - no orphan process.
- Ollama still auto-starts from the engine (ADR 0007), in both modes.

## Alternatives considered (and rejected)
- **Run the engine in-process (inside FreeCAD's Python).** Rejected: violates
  principle 3 (separate, swappable brain) and couples the engine to FreeCAD's 3.11.
- **Keep the engine as server + discovery file in production.** Rejected: it is the
  prototype topology; ADR 0002 always foresaw the flip, and the discovery file is an
  attack-surface/robustness cost we can now drop.
- **Bundle a separate Python for the engine.** Unnecessary: the engine is stdlib, so
  FreeCAD's bundled interpreter suffices - zero install.
- **Remove the add-on's attach/client mode entirely.** Rejected: keeping it (behind a
  debug checkbox) preserves `START_ENGINE.bat` for diagnosis at near-zero cost and
  keeps every path testable.

## Consequences
- The user starts everything from FreeCAD; nothing to launch from disk.
- Versions bumped to `0.11.0-phase6` (engine + add-on). Protocol unchanged (`0.1.0`):
  the wire format is identical; only who-greets-whom changed.
- New headless tests: `tests/test_flip.py` (real engine client vs a fake add-on
  server: flipped handshake, bidirectional round-trip, bad token rejected) and
  `tests/test_launcher.py` (interpreter finder, script resolution, launch/no-double-
  start/stop, graceful failures). Suite is now 21/21 green (`RUN_ALL_TESTS.bat`).
- `START_ENGINE.bat` stays as an optional debug tool (standalone server mode).
