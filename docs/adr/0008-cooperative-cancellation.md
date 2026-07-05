# ADR 0008 - Cooperative cancellation of a natural-language task

Status: Accepted (Phase 4, Session 8)
Date: 2026-06-25

## Context

A natural-language request can be slow: on modest hardware the local model can
take many seconds (sometimes much longer on the first request, while the model is
loaded). Until now the panel had no way to stop a request once sent: the user
could only wait. The wire protocol already declared `user.cancel { task_id }`
(see `shared/protocol.schema.json`), but the engine handler was a no-op left over
from Phase 1 ("commands are instant, nothing to cancel").

We need a Cancel that is **safe** and **honest**:

- Safe (principle 6, reversibility): cancelling must never leave FreeCAD in a
  surprising state. In particular, after the user asks to stop, the agent must not
  apply *new* geometry behind their back.
- Honest (principle 8, correctness over speed): we must not claim an instantaneous
  abort we cannot deliver. The slow step is a blocking HTTP inference call to
  Ollama (`urllib`); interrupting it mid-flight would mean forcibly closing the
  socket from another thread, which is fragile and OS-specific, and the model would
  keep running on the Ollama side anyway.

## Decision

Implement **cooperative cancellation at checkpoints**, entirely server-side state
plus UI wiring. No mid-inference interruption.

Engine (`engine/bridge_server.py`):

- `Session` keeps a small set of cancelled task ids guarded by a lock
  (`_cancelled_tasks`, `_cancel_lock`). Task ids are monotonic per session and
  never reused, so the set needs no cleanup.
- `on_user_cancel(task_id)` just records the id, logs it, emits an
  `agent.status` `cancelling` notification, and returns immediately. The UI stays
  responsive; the real stop happens at the next checkpoint.
- `on_user_prompt` checks `_is_cancelled(task_id)` at every safe checkpoint:
  after perceiving, **after thinking (before any action runs)**, before each action
  of a multi-step plan, and before each self-correction retry. On a hit it stops and
  returns `{ accepted: true, cancelled: true, results: [...partial...] }`, emitting
  an `agent.status` `cancelled`.

Add-on client (`addon/ai_copilot/bridge_client.py`): `send_user_cancel(task_id)`,
documented as safe to call from a worker thread while a `user.prompt` is still in
flight (the JSON-RPC peer is bidirectional; sends are lock-guarded and the engine
handler pool serves the cancel concurrently).

Panel (`addon/ai_copilot/ui/panel.py`): while a request runs, show a busy row with
an indeterminate progress bar, an elapsed-seconds label, and a Cancel button. The
running `task_id` is learned from the first `agent.status`; Cancel is enabled once
it is known and, when clicked, calls `send_user_cancel` from a short worker thread.
After ~15s the log shows a one-time hint that a slow local model is normal.

## Consequences

- The most valuable case works: if the user cancels while the model is thinking,
  the finished plan is **discarded and nothing is executed on FreeCAD**.
- For a multi-step plan, cancellation stops **between** steps. Steps already
  applied stay in place; each is an undoable transaction, so `Ctrl+Z` reverts them.
  The `cancelled` message reminds the user of this.
- A single in-flight inference is **not** aborted instantly: cancel takes effect at
  the next checkpoint (typically right after that inference returns). This is the
  honest trade-off; "Cancelling…" is shown meanwhile.
- The contract is unchanged (`user.cancel { task_id }` already existed); only the
  engine behaviour and the UI are new. Headless coverage added in
  `tests/test_cancel.py` (cancel during thinking -> zero actions executed).

## Alternatives considered

- **Hard interruption** of the HTTP inference (closing the socket from another
  thread): rejected as fragile, OS-specific, and ineffective (Ollama keeps
  generating server-side). Cooperative checkpoints are simpler and safe.
- **Auto-undo** of already-applied steps on cancel: rejected for now. It would be
  surprising to silently delete work the user could see being created; `Ctrl+Z`
  already gives them explicit control (principle 6).
