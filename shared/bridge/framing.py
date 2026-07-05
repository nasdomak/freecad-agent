"""
framing.py - framing messages over the TCP socket.

Problem: TCP is a byte stream, not a message stream. We need to know where one
JSON message ends and the next begins.

Choice (Phase 1a prototype): one message = one line of *compact* JSON terminated
by '\\n'. json.dumps with compact separators never produces literal newlines
inside, so '\\n' is a safe delimiter. Simple, hand-readable with netcat, enough
for the local loopback.

If we ever need to carry huge or binary payloads, we can switch to length-prefixed
framing (LSP "Content-Length" style): this module's interface (send_message /
iter_messages) would stay identical. The decision is isolated here.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Iterator


class ConnectionClosed(Exception):
    """Raised when the remote peer closes the connection."""


class FramedConnection:
    """
    Wraps an already-connected socket and carries JSON messages over it.

    Thread-safety: sending is protected by a lock (multiple threads may send).
    Reading must be done by a SINGLE thread (the JSON-RPC peer read loop).
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._send_lock = threading.Lock()
        self._recv_buffer = bytearray()
        # Disable Nagle's algorithm: small messages, we want low latency.
        try:
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass  # some platforms/sockets don't support it: not critical.

    # -- sending ---------------------------------------------------------------

    def send_message(self, obj: Any) -> None:
        """Serialize obj to compact JSON and send it as one line."""
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
        line = data.encode("utf-8") + b"\n"
        with self._send_lock:
            try:
                self._sock.sendall(line)
            except OSError as exc:
                raise ConnectionClosed(str(exc)) from exc

    # -- receiving -------------------------------------------------------------

    def iter_messages(self) -> Iterator[Any]:
        """
        Generator: yields a Python object for each received message.
        Handles partial reads and multiple messages in the same TCP packet.
        Ends (StopIteration) when the peer closes the connection.
        """
        while True:
            # Consume all complete lines already in the buffer.
            while b"\n" in self._recv_buffer:
                raw, _, rest = self._recv_buffer.partition(b"\n")
                self._recv_buffer = bytearray(rest)
                raw = raw.strip()
                if not raw:
                    continue  # empty line (keep-alive): ignore.
                try:
                    yield json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    # Malformed message: report it as a special object; the peer
                    # will reply with error -32700 (parse error).
                    yield {"__parse_error__": str(exc), "__raw__": raw[:200].decode("utf-8", "replace")}

            # Buffer exhausted: read more bytes from the socket.
            try:
                chunk = self._sock.recv(65536)
            except OSError as exc:
                raise ConnectionClosed(str(exc)) from exc
            if not chunk:
                raise ConnectionClosed("peer closed the connection")
            self._recv_buffer.extend(chunk)

    # -- closing ---------------------------------------------------------------

    def close(self) -> None:
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
