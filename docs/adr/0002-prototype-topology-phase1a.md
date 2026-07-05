# ADR 0002 — Bridge topology in the prototype (Phase 1a) and handshake direction

- **Status:** Accepted (proposed by the Lead Architect in Session 2, 2026-06-14; to be confirmed by Marco afterwards)
- **Context:** ADR 0001 fixes the transport (TCP loopback + token + JSON-RPC 2.0)
  but not *who* is the server and *who* the client, nor *who* presents the token.
  `shared/protocol.schema.json` describes the handshake in the **production**
  topology; Phase 1a (the first runnable code) needs the simplest path to start
  and to test by hand.

## Decision

**For the prototype (Phase 1a):**
- The **engine** is the **TCP server** (ephemeral port) and writes a *discovery
  file* `~/.freecad-agent/bridge.json` with `host`, `port`, `token`.
- The **add-on** is the **client**: it reads the discovery file, connects and
  **presents the token** via `session.hello`. The engine validates it.
- After the handshake, the engine **drives** the demonstration by calling methods
  on the add-on (`ping`, `command.execute`).

**For production (future, already foreseen in `protocol.schema.json`):**
- The roles reverse: the **add-on** starts the engine process passing it the
  token, and is the stable anchor; the **engine** connects and presents the token.
- The lifecycle stays the one from ADR 0001: the engine is a separate process,
  the add-on starts/attaches to it but does not own it.

## Rationale

- The **bridge core is symmetric** (`shared/bridge/jsonrpc.JsonRpcPeer`): a peer
  can both expose methods and call them, regardless of who opened the socket. So
  the server/client choice is a matter of *startup*, not *protocol*: switching to
  the production topology does not change the wire format.
- In the prototype Marco starts the engine by hand from a terminal: it is natural
  for it to be the listening server, and for the add-on (inside FreeCAD) to attach
  whenever it wants.
- The **security property of the handshake is preserved**: the token is an
  ephemeral secret known only to whoever can read the discovery file (same user,
  same machine). The direction in which the token is presented does not change the
  guarantee (loopback + shared secret). In production the token travels via
  argument/environment from the add-on to the engine, without a discovery file.

## Consequences

- A module `shared/bridge/discovery.py` (discovery file) exists, used **only** in
  the prototype topology. In production it will be replaced by passing the token
  directly at engine startup.
- When we implement the production topology, the only thing that changes is the
  *bootstrap* (who binds/accepts and how the token is exchanged), not the handlers
  nor the messages. No protocol ADR needs to be reopened.
- The discovery file contains a secret: written with 0o600 permissions on POSIX,
  removed on engine shutdown. On Windows it stays in the user's home.
