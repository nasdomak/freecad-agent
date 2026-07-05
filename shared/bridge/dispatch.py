"""
dispatch.py - DEPRECATED (Phase 1).

An early draft kept here a `ThreadedDispatcher` that ran each handler on a thread
pool. It turned out to be the WRONG solution to the nested-call problem: even so,
the read loop was left blocked waiting for the dispatcher's result, so it could
not read the nested response -> same deadlock.

The CORRECT solution was moved into `JsonRpcPeer` (jsonrpc.py): the read loop
hands each incoming request to an internal pool and returns to reading
IMMEDIATELY; the pool worker sends the response. This way a handler can make
nested calls without blocking the read loop.

The peer's injectable `dispatcher` goes back to its only legitimate purpose:
deciding WHERE the handler body runs (inline for engine/tests; on the Qt main
thread for the add-on, via qt_invoker). This module is intentionally left empty
and is no longer exported by `bridge`. See ADR 0003.
"""
