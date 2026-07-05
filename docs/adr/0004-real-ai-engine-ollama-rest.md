# ADR 0004 — Real AI engine: local Ollama over its REST API, no venv, keep the prototype topology (for now)

- **Status:** Accepted (proposed by the Lead Architect in Session 4, 2026-06-20;
  Marco delegated the choice, asking for "the most security-first, robust, best"
  option, and accepted the recommendation.)
- **Supersedes/extends:** ADR 0002 and ADR 0003 (which named the arrival of engine
  dependencies / a venv as the trigger to consider the production topology). This
  ADR resolves that trigger.

## Context

Phase 2 gives the engine a real brain: it must turn natural language into
structured commands using a **local** model. The starting prompt assumed this
would require a Python virtual environment (the `ollama` client library, maybe
`jsonschema`) and possibly the move to the *production* topology (the add-on
launches the engine and hands it the token, removing the discovery file).

Two things changed the calculus:

1. **Ollama already exposes a local HTTP REST API** (`http://127.0.0.1:11434`).
   We can drive it with `urllib` from the Python standard library. No third-party
   package is needed for chat or for listing models.
2. **The catalog validator is already pure stdlib** (`engine/fake_brain.py`), so
   `jsonschema` is not required either.

Therefore the engine can gain a real brain **while staying pure stdlib**.

## Decision

### 1. Talk to Ollama over its REST API using only the standard library
`engine/ollama_client.py` uses `urllib` to call `GET /api/tags` (list models /
availability probe) and `POST /api/chat` (completion, forced to JSON output with
`format="json"`). No `pip install`, no third-party code in the engine.

**Why this is the security-first AND robust choice (Marco's ask):**
- *Security:* zero third-party dependencies = **zero supply-chain attack
  surface**. There is nothing to install, pin, audit or trust beyond Python itself
  and Ollama. Traffic is loopback-only (`127.0.0.1`); nothing leaves the machine
  (principle 1, privacy/local-first).
- *Robustness/portability:* the engine runs on **any** Python ≥ 3.8 and never
  touches FreeCAD's Python 3.11 (principle 3). Nothing to break on upgrades.
- *Simplicity for a non-developer:* starting the engine stays a **single
  double-click** on `START_ENGINE.bat`. No environment to create or activate.

### 2. No virtual environment yet
Because the engine has **no third-party dependencies**, a venv would add a setup
step and Windows fragility (activation, interpreter selection) for no benefit.
We explicitly defer it. **Trigger to revisit:** the first time the engine genuinely
needs a third-party package (e.g. a cloud SDK in a later phase, or a heavier local
validator). At that point we add a venv that `START_ENGINE.bat` creates/uses
automatically, so the experience stays one double-click.

### 3. Model-agnostic structured output, not model-specific tool-calling
The brain (`engine/brain.py`) builds the vocabulary description **from
`shared/commands.schema.json`** and asks the model for one JSON object with an
`actions` array. We force JSON mode and robustly extract the object (tolerating a
`<think>` preamble). We do **not** depend on a particular model's native
tool-calling API. This honours principle 9 (adapt, don't exclude): the tester's
`qwen3:4b` is just one model; nothing is tuned to it. Every command action is
re-validated against the catalog before it runs (principle 7).

### 4. Keep the prototype topology (engine = server, add-on = client) for Phase 2
We do **not** flip to the production topology now. The add-on still attaches to a
running engine via the discovery file.

**Rationale (security-aware):** the production topology (add-on spawns the engine,
passes the token in memory, no file on disk) is genuinely a bit more secure —
nothing writes the token to disk. But it reintroduces exactly the Windows
subprocess fragility ADR 0003 warned about (which interpreter to launch, PATH),
right as we are validating the AI loop, and it works against the non-developer's
"one simple start". The current surface is already narrow: **loopback-only**, an
**ephemeral 256-bit token**, and a discovery file we now **lock down to the current
user** (see below). We judged the marginal security gain smaller than the
reliability/usability cost at this moment.

**Mitigation adopted now:** harden the discovery file permissions on every OS.
On POSIX it was already `0o600`; on Windows we now best-effort strip inherited ACLs
and grant access to the current user only (`icacls`), so another user on the same
machine cannot read the token.

**Trigger to flip (unchanged intent, restated):** when we add the engine venv (see
§2), do the topology flip in the same step — the add-on launches the engine with
the chosen interpreter and passes the token directly, and the discovery file goes
away. The bridge core is symmetric, so only the bootstrap changes, never the
handlers or the wire format.

### 5. Free Python is transparent and auto-runs inside a transaction
When no structured command fits, the model may propose Python (`python.execute`).
The add-on **shows the exact code** in a prominent banner (principle 5) and runs it
inside an **undoable transaction** (principle 6), with **no confirmation click**
(principle 4: the agent acts without asking permission for reversible actions).
Irreversible actions remain gated by `ui.confirm`. Marco chose this posture
explicitly.

### 6. Basic self-correction
After an action fails, the engine feeds the FreeCAD error back to the model
(`Brain.repair`) and retries the corrected action **once** (bounded, to avoid loops
— principle 8).

## Consequences

- New engine modules: `ollama_client.py` (stdlib REST client, graceful
  degradation) and `brain.py` (NL → validated plan, self-correction). Both have no
  FreeCAD dependency and are tested headless with a fake `chat`/HTTP server.
- `bridge_server.py` implements `user.prompt` for real (perceive → plan → act →
  repair) and logs Ollama availability at startup. `command.request` stays as the
  expert mode.
- New add-on modules: `perception.py` (`perception.overview`/`detail`) and
  `executor/python_exec.py` (`python.execute`). The panel gains a natural-language
  box and an active Python transparency banner.
- `shared/bridge/discovery.py` now hardens file permissions on Windows too.
- If Ollama is absent, natural language is **refused gracefully** with an
  actionable message; structured commands keep working (principle 9).
- Configuration via env vars (optional): `FREECAD_AGENT_OLLAMA_URL`,
  `FREECAD_AGENT_OLLAMA_MODEL`, `FREECAD_AGENT_OLLAMA_TIMEOUT`.
- No protocol ADR is reopened; `protocol.schema.json` already defined
  `user.prompt`, `perception.*` and `python.execute`.
