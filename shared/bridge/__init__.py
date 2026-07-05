"""
freecad-agent · bridge core (neutral library of the add-on <-> engine bridge)
=============================================================================

This package contains ONLY the bridge transport, written in pure stdlib.

Principles respected (see docs/00_SINTESI_Brainstorming.md):
- Principle 2/3: no dependency on FreeCAD nor on its Python 3.11. It runs on any
  Python >= 3.8. That is why it is fully testable OUTSIDE FreeCAD.
- It is a neutral *contract* library, on the same footing as the JSON Schemas in
  shared/: the add-on and the engine do not import each other, but they share
  this common joint. They remain separate processes with separate interpreters.

Contents:
- framing.py    : frames messages on the socket (newline-delimited JSON).
- jsonrpc.py    : symmetric, bidirectional JSON-RPC 2.0 peer.
- discovery.py  : discovery file (host/port/token) to hook the processes together.

Source of truth for the wire format: shared/protocol.schema.json (JSON-RPC 2.0).
"""

from .framing import FramedConnection, ConnectionClosed
from .jsonrpc import JsonRpcPeer, JsonRpcError, ErrorCode
from . import discovery

__all__ = [
    "FramedConnection",
    "ConnectionClosed",
    "JsonRpcPeer",
    "JsonRpcError",
    "ErrorCode",
    "discovery",
]

PROTOCOL_VERSION = "0.1.0"
