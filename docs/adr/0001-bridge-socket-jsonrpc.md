# ADR 0001 — Add-on ↔ engine bridge: local TCP socket + JSON-RPC 2.0

- **Status:** Accepted (approved by Marco, 2026-06-14)
- **Context:** The add-on (FreeCAD's Python 3.11) and the AI engine (a separate
  process, its own Python) are two separate programs by principle 3. We need a
  communication channel (the "bridge") that is bidirectional, identical on
  Windows/macOS/Linux, inspectable, and free of external dependencies.

## Decision
A TCP socket on `127.0.0.1` (ephemeral port assigned at startup, handshake with a
shared token) as the transport, and **JSON-RPC 2.0** as the message format.

## Rejected alternatives
- **stdin/stdout (engine as a child of the add-on):** couples the lifecycles; the
  engine would die with FreeCAD — against principle 3. Hard to inspect.
- **HTTP REST on localhost:** overhead and no native engine→add-on push, which is
  needed for the act/observe loop.
- **Named pipe / file:** cross-platform fragmentation (Windows named pipe ≠ Unix
  socket).

## Consequences
- The engine is an independent process with its own lifecycle; the add-on
  starts/attaches to it but does not own it.
- Bidirectional: the engine calls add-on methods (`command.execute`,
  `perception.*`) and the add-on notifies the engine (`user.prompt`). See
  `shared/protocol.schema.json`.
- Security: loopback only + ephemeral token; no network exposure.
