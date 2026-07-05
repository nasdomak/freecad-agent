"""
jsonrpc.py - symmetric, bidirectional JSON-RPC 2.0 peer.

"Symmetric" = the same object can both EXPOSE methods (handlers) and CALL methods
on the remote peer. This is needed because the bridge is bidirectional
(protocol.schema.json): the engine calls `command.execute`/`perception.*` on the
add-on, and the add-on calls `user.prompt` on the engine.

THREADING ARCHITECTURE (RISK #2 of the plan)
--------------------------------------------
A single "read loop" thread reads incoming messages from the socket. For each
message it decides:
  - is it a RESPONSE to one of our calls? -> unblock the caller (Event), directly
    in the read loop (a fast operation).
  - is it an INCOMING REQUEST/NOTIFICATION? -> it does NOT run it on the read
    loop, but hands it to a thread from an internal pool. The read loop goes back
    to reading IMMEDIATELY.

WHY the pool (fix introduced in Phase 1, ADR 0003): a handler may in turn CALL a
method on the remote peer (e.g. the engine, having received `command.request`,
calls `command.execute` back on the add-on). That nested call blocks until the
response comes back; if the handler ran on the read loop, the read loop would be
stuck and could NEVER read that response -> deadlock. Running handlers on the
pool keeps the read loop free to receive the nested response and unblock the
handler. It is the pool worker, not the read loop, that sends the response when
the handler finishes.

CRITICAL POINT on the add-on side: handlers touch FreeCAD/Qt APIs, which are NOT
thread-safe and must run on the GUI main thread. That is why the handler *body*
is not wired here: it goes through an injectable `dispatcher`. By default the
dispatcher runs inline (perfect for the engine and headless tests). The add-on
injects a dispatcher that marshals the call onto the Qt main thread and blocks
until the result is ready (see qt_invoker.py): what blocks is the pool worker,
not the read loop nor the main thread.

This keeps the read loop simple and identical everywhere, confines the Qt
complexity to a single point, and lets handlers make nested calls.
"""

from __future__ import annotations

import itertools
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from .framing import FramedConnection, ConnectionClosed


class ErrorCode:
    """Standard JSON-RPC 2.0 error codes + application extensions."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # Application extensions of the bridge (range -32000..-32099 reserved for impl):
    AUTH_FAILED = -32001      # token missing or wrong
    NOT_AUTHENTICATED = -32002  # method called before session.hello
    HANDLER_ERROR = -32010    # unhandled exception inside a handler


class JsonRpcError(Exception):
    """A JSON-RPC error, both received from the peer and raised inside a handler."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data

    def to_obj(self) -> Dict[str, Any]:
        obj: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            obj["data"] = self.data
        return obj


# Dispatcher type: receives (handler, params) and returns the handler's result,
# possibly re-raising its exceptions. It MUST be blocking (we need the return
# value for the RPC response).
Dispatcher = Callable[[Callable[[dict], Any], dict], Any]


def _inline_dispatcher(handler: Callable[[dict], Any], params: dict) -> Any:
    """Default: run the handler on the read-loop's worker. Fine outside Qt."""
    return handler(params)


class _PendingCall:
    """Waiting slot for an outgoing call, unblocked by the read loop."""
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[JsonRpcError] = None


class JsonRpcPeer:
    """
    A JSON-RPC peer over an already-established connection.

    Typical use:
        peer = JsonRpcPeer(conn, name="engine")
        peer.register("ping", lambda p: {"pong": True})
        peer.start()                      # start the read loop on a thread
        res = peer.call("command.execute", {...}, timeout=30)
        peer.close()
    """

    def __init__(
        self,
        conn: FramedConnection,
        name: str = "peer",
        dispatcher: Optional[Dispatcher] = None,
        on_close: Optional[Callable[[], None]] = None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._conn = conn
        self._name = name
        self._dispatcher: Dispatcher = dispatcher or _inline_dispatcher
        self._on_close = on_close
        self._log = logger or (lambda msg: None)

        self._handlers: Dict[str, Callable[[dict], Any]] = {}
        self._pending: Dict[Any, _PendingCall] = {}
        self._pending_lock = threading.Lock()
        self._id_counter = itertools.count(1)
        self._reader_thread: Optional[threading.Thread] = None
        # Pool to RUN incoming handlers off the read loop (anti-deadlock for
        # nested calls). Created in start(), closed in close().
        self._request_pool: Optional[ThreadPoolExecutor] = None
        self._closed = threading.Event()

    # -- handler registration --------------------------------------------------

    def register(self, method: str, handler: Callable[[dict], Any]) -> None:
        """Expose a method callable by the remote peer."""
        self._handlers[method] = handler

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        """Start the handler pool and the read loop on a daemon thread."""
        self._request_pool = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix=f"rpc-h-{self._name}"
        )
        self._reader_thread = threading.Thread(
            target=self._read_loop, name=f"jsonrpc-{self._name}", daemon=True
        )
        self._reader_thread.start()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._conn.close()
        # Unblock all pending calls with an error.
        with self._pending_lock:
            for pend in self._pending.values():
                pend.error = JsonRpcError(ErrorCode.INTERNAL_ERROR, "connection closed")
                pend.event.set()
            self._pending.clear()
        # Close the handler pool (no wait: fast shutdown).
        pool, self._request_pool = self._request_pool, None
        if pool is not None:
            pool.shutdown(wait=False)

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def wait_closed(self, timeout: Optional[float] = None) -> bool:
        return self._closed.wait(timeout)

    # -- outgoing calls --------------------------------------------------------

    def call(self, method: str, params: Optional[dict] = None, timeout: float = 30.0) -> Any:
        """
        Call a method on the remote peer and BLOCK until the response.
        Returns `result`, or raises JsonRpcError / ConnectionClosed / TimeoutError.
        """
        if self._closed.is_set():
            raise ConnectionClosed("peer closed")
        call_id = next(self._id_counter)
        pend = _PendingCall()
        with self._pending_lock:
            self._pending[call_id] = pend

        message = {"jsonrpc": "2.0", "method": method, "id": call_id}
        if params is not None:
            message["params"] = params
        self._log(f"-> call {method} (id={call_id})")
        self._conn.send_message(message)

        if not pend.event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(call_id, None)
            raise TimeoutError(f"timeout on '{method}' after {timeout}s")

        if pend.error is not None:
            raise pend.error
        return pend.result

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        """Send a notification (no id, no response expected)."""
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._log(f"-> notify {method}")
        self._conn.send_message(message)

    # -- read loop -------------------------------------------------------------

    def _read_loop(self) -> None:
        try:
            for msg in self._conn.iter_messages():
                self._handle_incoming(msg)
        except ConnectionClosed as exc:
            self._log(f"connection closed: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"error in read loop: {exc}\n{traceback.format_exc()}")
        finally:
            was_open = not self._closed.is_set()
            self.close()
            if was_open and self._on_close is not None:
                try:
                    self._on_close()
                except Exception:  # pragma: no cover
                    pass

    def _handle_incoming(self, msg: Any) -> None:
        # Message not interpretable as valid JSON (from framing).
        if isinstance(msg, dict) and "__parse_error__" in msg:
            self._send_error(None, ErrorCode.PARSE_ERROR, "invalid JSON")
            return
        if not isinstance(msg, dict):
            self._send_error(None, ErrorCode.INVALID_REQUEST, "message is not an object")
            return

        # Is it a RESPONSE (has result or error and an id we know)?
        if ("result" in msg or "error" in msg) and "method" not in msg:
            self._handle_response(msg)
            return

        # Otherwise it is a REQUEST or a NOTIFICATION.
        self._handle_request(msg)

    def _handle_response(self, msg: dict) -> None:
        call_id = msg.get("id")
        with self._pending_lock:
            pend = self._pending.pop(call_id, None)
        if pend is None:
            self._log(f"response for unknown id: {call_id}")
            return
        if "error" in msg and msg["error"] is not None:
            err = msg["error"]
            pend.error = JsonRpcError(
                err.get("code", ErrorCode.INTERNAL_ERROR),
                err.get("message", "unknown error"),
                err.get("data"),
            )
        else:
            pend.result = msg.get("result")
        pend.event.set()

    def _handle_request(self, msg: dict) -> None:
        method = msg.get("method")
        params = msg.get("params") or {}
        req_id = msg.get("id")  # absent => notification
        is_notification = "id" not in msg

        handler = self._handlers.get(method)
        if handler is None:
            self._log(f"<- unknown method: {method}")
            if not is_notification:
                self._send_error(req_id, ErrorCode.METHOD_NOT_FOUND, f"unknown method: {method}")
            return

        self._log(f"<- {'notify' if is_notification else 'call'} {method} (id={req_id})")
        # We do NOT run the handler on the read loop: we hand it to the pool, so
        # the read loop stays free (the handler may make nested calls). It is the
        # worker that sends the response when the handler finishes.
        pool = self._request_pool
        if pool is None:
            # Peer not started with start() (atypical use): run inline.
            self._run_handler(handler, params, req_id, is_notification, method)
            return
        try:
            pool.submit(self._run_handler, handler, params, req_id, is_notification, method)
        except RuntimeError:
            # Pool already closed (peer shutting down): inline fallback, best-effort.
            self._run_handler(handler, params, req_id, is_notification, method)

    def _run_handler(self, handler: Callable[[dict], Any], params: dict,
                     req_id: Any, is_notification: bool, method: str) -> None:
        """Run a handler (on the pool) and send the response. Never on the read loop."""
        try:
            # Goes through the dispatcher: inline (engine/tests) or Qt main thread (add-on).
            result = self._dispatcher(handler, params)
        except JsonRpcError as exc:
            if not is_notification:
                self._send_error(req_id, exc.code, exc.message, exc.data)
            return
        except Exception as exc:
            self._log(f"exception in handler '{method}': {exc}\n{traceback.format_exc()}")
            if not is_notification:
                self._send_error(req_id, ErrorCode.HANDLER_ERROR, f"{type(exc).__name__}: {exc}")
            return

        if not is_notification:
            try:
                self._conn.send_message({"jsonrpc": "2.0", "id": req_id, "result": result})
            except ConnectionClosed:
                pass

    def _send_error(self, req_id: Any, code: int, message: str, data: Any = None) -> None:
        err: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        try:
            self._conn.send_message({"jsonrpc": "2.0", "id": req_id, "error": err})
        except ConnectionClosed:
            pass
