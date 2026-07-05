# ADR 0003 — Persistent engine, `command.request` channel and topology for Phase 1

- **Status:** Accepted (proposed by the Lead Architect in Session 3, 2026-06-14; to be confirmed by Marco afterwards)
- **Context:** Phase 1a validated the bridge end-to-end on real FreeCAD with a
  *one-shot* engine (it ran ONE hardcoded demo and closed) and a prototype topology
  (engine = server, add-on = client; see ADR 0002). Phase 1 must make the skeleton
  *usable by Marco by hand*, still **without AI**: the add-on as a real workbench
  with a panel, and an engine that keeps listening and handles multiple commands in
  one session. Three things remained to decide: (1) how the panel sends an
  already-structured command to the add-on-engine; (2) how to avoid the deadlock of
  nested calls on the bridge; (3) whether to move to the *production* topology now
  (add-on that starts/manages the engine).

## Decision

### 1. Persistent engine with a pass-through "fake brain"
The engine no longer runs a demo: it enters an **accept loop**, accepts one
connection at a time, handles multiple commands per session, survives add-on
disconnections (it goes back to `accept`) and shuts down cleanly (Ctrl+C) removing
the discovery file. Without AI it acts as a **validating pass-through**: it receives
the structured command, checks it against `shared/commands.schema.json`, and — if
valid — forwards it to the add-on as `command.execute`. This exercises **both
directions** of the bridge and leaves a clean insertion point for the real agent
(which will replace only the "decision" stage).

### 2. New `command.request` channel (add-on → engine)
The panel produces an **already-structured** command (the user picks `create_box`
and the parameters), not natural language. We add to `protocol.schema.json` the
`command.request` method (params = `commandInvocation`, result = `commandResult`).
`user.prompt` stays reserved for the real agent's natural-language channel
(Phase 2+); in Phase 1 the engine replies to it with a polite refusal (principle 7).
`command.request` is not a throwaway dead-end: with the AI it becomes the **expert
mode** that bypasses language interpretation.

### 3. Incoming handlers run OFF the read loop (anti-deadlock)
The `command.request` handler must, in turn, **call** `command.execute` back on the
add-on. If it ran on the read-loop thread it would deadlock: the nested call waits
for a response that only the read loop can read... but the read loop is stuck inside
the handler.

**Correct solution inside `JsonRpcPeer`:** the read loop no longer runs handlers; it
hands every incoming request/notification to an **internal pool** and goes back to
reading IMMEDIATELY. It is the pool worker that sends the response when the handler
finishes. This way a nested call blocks *the worker*, while the read loop stays free
to receive and route the response. The injectable `dispatcher` goes back to its only
legitimate purpose: deciding WHERE the handler *body* runs (inline for engine/tests;
on the **Qt main thread** for the add-on, via `qt_invoker`) — now invoked by the
worker, not by the read loop. (Historical note: an early version used an external
`ThreadedDispatcher`; it was ineffective because the read loop stayed blocked waiting
for the dispatcher. See `shared/bridge/dispatch.py`, now deprecated.)

On the panel side the rule still holds: `command.request` must be sent from a
**worker** thread, never from the Qt main thread (otherwise the returning
`command.execute`, which needs the main thread, would deadlock).

### 4. Topology: the prototype one (engine=server, add-on=client) is CONFIRMED for all of Phase 1
We do **not** yet move to the production topology (add-on starting the engine
process). The direction of ADR 0002 stays valid.

## Rationale (on the topology)

- **Minimal risk, reuse of what was validated.** Phase 1a already proved on real
  FreeCAD that `engine=server / add-on=client` holds up against Qt threading
  (RISK #2). Reversing the roles now would mean re-validating everything from
  scratch with no functional benefit in this phase.
- **The hard part of production is premature.** Having the add-on start the engine
  requires deciding *which* Python interpreter to launch (the engine must NOT depend
  on FreeCAD's Python 3.11 — principle 3) and managing its venv/dependencies. Today
  the engine is pure stdlib and has no venv: solving the subprocess launch now
  optimizes nothing and introduces fragility on Windows (PATH, missing interpreter)
  exactly while we want Marco to *use* the skeleton.
- **Zero cost of deferral.** The bridge core is **symmetric** (`JsonRpcPeer`): when
  we flip the topology only the *bootstrap* changes (who binds/accepts and how the
  token is passed), not the handlers nor the wire format. No protocol ADR will be
  reopened.

**When to flip (explicit triggers for the future ADR):** as soon as the real AI
engine has its own venv with dependencies (Phase 2/3). At that point the add-on will
start the engine process passing it the token (no more discovery file), and the
engine will connect as a client — exactly the production topology already described
in `protocol.schema.json` and ADR 0002.

## Consequences

- `shared/protocol.schema.json` gains `command.request`; `user.prompt` is marked as
  not implemented in Phase 1.
- `shared/bridge/jsonrpc.py` now runs incoming handlers on an internal pool (the
  read loop never blocks). `shared/bridge/dispatch.py` remains as a deprecated note.
- The engine becomes a persistent service: Marco's experience is "I start the engine
  once, then I use the panel as many times as I want".
- The discovery file (`~/.freecad-agent/bridge.json`) stays in use for all of
  Phase 1 (prototype topology). It will be replaced by passing the token directly
  when the production topology is adopted.
