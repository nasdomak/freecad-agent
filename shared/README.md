# shared/ — Shared contracts

Neutral schemas (JSON Schema 2020-12) acting as the **joint** between the add-on
and the engine. They are the source of truth: both the add-on (FreeCAD's Python)
and the engine (its own Python) read them, but neither owns them. Changing a
contract is a deliberate act: bump the version and, if needed, write an ADR.

- **`protocol.schema.json`** — bridge messages (JSON-RPC 2.0): handshake,
  engine→add-on methods (`command.execute`, `python.execute`, `perception.*`,
  `transaction.rollback`, `ui.confirm`, `ui.highlight`), add-on→engine methods
  (`user.prompt`, `command.request`, `user.cancel`) and status notifications.
- **`commands.schema.json`** — the structured vocabulary as data: catalog of safe
  commands with their parameters. The implementation lives in
  `addon/ai_copilot/executor/vocabulary/`.
- **`context.schema.json`** — document perception format: `documentOverview`
  (cheap overview) and `objectDetail` (on-demand detail, geometric RAG).

All at version **0.1.0**. The catalog and formats will grow phase by phase (see
`docs/02_PIANO_DI_AZIONE.md`).

The bridge transport library lives in `shared/bridge/` (pure stdlib, no FreeCAD
dependency).
