"""
bridge_client.py - add-on side of the bridge.

TWO MODES (ADR 0015):
  - MANAGED (production, default): the add-on is the TCP SERVER. It opens an
    ephemeral loopback port + token, LAUNCHES the engine as a client process
    (EngineLauncher, using FreeCAD's bundled Python), accepts the engine's
    connection and VALIDATES its `session.hello` token. No discovery file, no
    START_ENGINE.bat: the user just clicks "Connect" and the engine starts.
  - ATTACH (debug): the add-on is the TCP CLIENT. It reads host/port/token from
    the discovery file (~/.freecad-agent/bridge.json) written by a standalone
    engine (START_ENGINE.bat) and connects to it. Kept for our own debugging.

In BOTH modes the add-on exposes the same handlers the engine calls (`ping`,
`command.execute`, `python.execute`, `perception.*`, `transaction.rollback`, and
the `agent.status` notification) and offers `send_command_request()` /
`send_user_prompt()` for the panel. Only the handshake DIRECTION differs: in
managed mode WE validate the token; in attach mode we present it. The bridge core
is symmetric (ADR 0001), so this is the only thing that changes.

Threading:
- All network work runs on a dedicated WORKER thread: the UI never freezes.
- INCOMING handlers run on the MAIN THREAD via the invoker (FreeCAD APIs are not
  thread-safe). See qt_invoker.py.
- `send_command_request()` makes a BLOCKING call: it must be invoked from a worker
  thread, NEVER from the Qt main thread (otherwise the returning `command.execute`,
  which needs the main thread, would deadlock). The panel takes care of that.

Callbacks to the UI (all optional, may arrive from different threads: the panel
re-routes them onto the main thread with a Qt Signal):
- on_state(state)   : "connecting" | "connected" | "disconnected" | "failed"
- on_status(params) : payload of an `agent.status` notification from the engine
- logger(msg)       : a line of text for the log
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional

from . import executor
from .engine_launcher import EngineLauncher

# The neutral bridge library (shared/bridge): made importable by InitGui.py
# (or the macro), which puts shared/ on sys.path before importing this module.
from bridge import (  # type: ignore
    FramedConnection,
    JsonRpcPeer,
    JsonRpcError,
    ConnectionClosed,
    ErrorCode,
    discovery,
    PROTOCOL_VERSION,
)

ADDON_VERSION = "0.12.0-phase6"


class BridgeClient:
    def __init__(self, invoker=None, logger=None,
                 on_state: Optional[Callable[[str], None]] = None,
                 on_status: Optional[Callable[[dict], None]] = None,
                 on_python: Optional[Callable[[str, str], None]] = None,
                 launcher: "EngineLauncher | None" = None,
                 accept_timeout: float = 30.0,
                 max_reconnect: int = 5, reconnect_delay: float = 2.0) -> None:
        """
        invoker: MainThreadInvoker. If None (e.g. tests outside FreeCAD), handlers
                 run inline on the network thread (NOT safe with FreeCAD).
        on_python: called (code, reason) when the engine proposes free Python, so
                 the panel can SHOW it (transparency, principle 5) before it runs.
        launcher: EngineLauncher used in MANAGED mode to start/stop the engine
                 process (ADR 0015). Injectable for tests; a real one by default.
        accept_timeout: seconds to wait, in managed mode, for the engine to
                 connect back and complete the handshake.
        """
        self._invoker = invoker
        self._log = logger or (lambda msg: print(f"[addon] {msg}", flush=True))
        self._on_state = on_state or (lambda state: None)
        self._on_status = on_status or (lambda params: None)
        self._on_python = on_python or (lambda code, reason: None)
        self._launcher = launcher or EngineLauncher(logger=self._log)
        self._accept_timeout = accept_timeout
        self._max_reconnect = max_reconnect
        self._reconnect_delay = reconnect_delay

        self._peer: Optional[JsonRpcPeer] = None
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        # Managed mode (ADR 0015): the add-on is the SERVER and launches the engine.
        self._managed = True
        self._server_token = ""          # token WE generate; the engine must present it
        self._authenticated = threading.Event()
        self.engine_info: dict = {}  # filled in by the handshake (versions, commands)

    @property
    def launcher(self) -> "EngineLauncher":
        return self._launcher

    # -- handlers exposed to the engine ---------------------------------------

    def _on_ping(self, params: dict) -> dict:
        self._log(f"ping received (ts={params.get('ts')}) -> pong")
        return {"pong": True, "ts": time.time(), "addon_version": ADDON_VERSION}

    def _on_command_execute(self, params: dict) -> dict:
        # params is a commandInvocation {cmd, params}. The executor opens the
        # undoable transaction and returns a commandResult.
        self._log(f"command.execute: {params.get('cmd')} {params.get('params')}")
        result = executor.execute(params)
        self._log(f"  -> {result}")
        return result

    def _on_transaction_rollback(self, params: dict) -> dict:
        return executor.rollback(params.get("transaction_id", ""))

    def _on_perception_overview(self, params: dict) -> dict:
        # The agent's "eyes": concise summary of the active document.
        from . import perception
        return perception.overview()

    def _on_perception_detail(self, params: dict) -> dict:
        from . import perception
        return perception.detail(params.get("target", ""))

    def _on_python_execute(self, params: dict) -> dict:
        # Free Python channel (principle 5): SHOW the code first (transparency),
        # then run it inside an undoable transaction (principle 6).
        code = params.get("code", "")
        reason = params.get("reason", "")
        self._log(f"python.execute proposed (reason: {reason})")
        try:
            self._on_python(code, reason)  # push the code to the UI banner
        except Exception:  # the UI must never break the bridge
            pass
        return executor.run_python(code, reason)

    def _on_agent_status(self, params: dict) -> None:
        # Status notification from the engine: forward it to the UI.
        self._log(f"[status] {params.get('phase')}: {params.get('message')}")
        try:
            self._on_status(params)
        except Exception:  # pragma: no cover - the UI must not break the bridge
            pass

    def _on_hello_server(self, params: dict) -> dict:
        """
        MANAGED (production) handshake: here the ADD-ON is the SERVER, so WE
        validate the token the engine-client presents (the roles are swapped vs the
        prototype, where the engine validated - see ADR 0015 / ADR 0002). The bridge
        core is symmetric, so only this handshake direction changes; every other
        handler keeps its role.
        """
        token = params.get("token", "")
        proto = params.get("protocol_version", "?")
        if token != self._server_token:
            self._log("handshake REJECTED: the engine presented the wrong token.")
            raise JsonRpcError(ErrorCode.AUTH_FAILED, "invalid token")
        if proto != PROTOCOL_VERSION:
            self._log(f"WARNING: protocol addon={PROTOCOL_VERSION} engine={proto}")
        self.engine_info = {
            "engine_version": params.get("engine_version"),
            "protocol_version": proto,
        }
        self._authenticated.set()
        self._log(f"handshake OK: engine v{params.get('engine_version')} attached.")
        return {"ok": True, "addon_version": ADDON_VERSION,
                "protocol_version": PROTOCOL_VERSION}

    def _register_addon_handlers(self, peer: JsonRpcPeer) -> None:
        """Register the handlers the engine calls on us. SAME in both topologies
        (the bridge is symmetric): the add-on always exposes these."""
        peer.register("ping", self._on_ping)
        peer.register("command.execute", self._on_command_execute)
        peer.register("python.execute", self._on_python_execute)
        peer.register("perception.overview", self._on_perception_overview)
        peer.register("perception.detail", self._on_perception_detail)
        peer.register("transaction.rollback", self._on_transaction_rollback)
        peer.register("agent.status", self._on_agent_status)

    # -- lifecycle -------------------------------------------------------------

    def start(self, managed: bool = True) -> None:
        """
        Start the client on a worker thread (non-blocking).

        managed=True (default, PRODUCTION - ADR 0015): the add-on is the SERVER; it
        opens an ephemeral loopback port + token, LAUNCHES the engine as a client,
        and validates its handshake. No discovery file, no START_ENGINE.bat.

        managed=False (DEBUG): the add-on is the CLIENT; it reads the discovery file
        written by a standalone engine started by START_ENGINE.bat and attaches.
        """
        if self._worker and self._worker.is_alive():
            self._log("client already started.")
            return
        self._managed = managed
        self._stop.clear()
        self._authenticated.clear()
        target = self._run_managed if managed else self._run_attach
        self._worker = threading.Thread(target=target, name="bridge-client", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._log("client stop requested.")
        self._stop.set()
        if self._peer is not None:
            self._peer.close()
        # In managed mode make sure the engine process is terminated (no orphan).
        try:
            self._launcher.stop()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

    def engine_running(self) -> bool:
        """True if we launched an engine process that is still alive (managed mode)."""
        try:
            return self._launcher.is_running()
        except Exception:  # pragma: no cover
            return False

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self._connected.wait(timeout)

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # -- sending a structured command to the engine ----------------------------

    def send_command_request(self, invocation: dict, timeout: float = 70.0) -> dict:
        """
        Send `command.request` to the engine and BLOCK until the commandResult.
        MUST be called from a worker thread (not the Qt main thread).
        Raises ConnectionClosed if not connected.
        """
        peer = self._peer
        if peer is None or not self._connected.is_set():
            raise ConnectionClosed("not connected to the engine")
        return peer.call("command.request", invocation, timeout=timeout)

    def send_user_prompt(self, text: str, selection=None, ai_timeout=None,
                         timeout: "float | None" = None) -> dict:
        """
        Send a natural-language request (`user.prompt`) and BLOCK until the engine
        finishes the whole plan. MUST be called from a worker thread (the engine
        calls perception/command.execute back on us, which need the main thread).

        ai_timeout: per-call Ollama timeout (seconds) chosen in the panel and
                    forwarded to the engine. 0 (or None) means UNLIMITED - the
                    default - in which case the RPC wait below is also unlimited and
                    the user stops a stuck request with Cancel. A positive value
                    sizes the RPC wait to outlast the engine's worst case (a plan
                    plus up to MAX_REPAIR_ATTEMPTS self-corrections, each a model
                    call up to ai_timeout), so the panel never gives up first.
        """
        peer = self._peer
        if peer is None or not self._connected.is_set():
            raise ConnectionClosed("not connected to the engine")
        params: dict = {"text": text, "selection": selection or []}
        # Always send ai_timeout (0 included) so the engine can reset a prior cap.
        params["ai_timeout"] = ai_timeout or 0
        if timeout is None:
            if ai_timeout and float(ai_timeout) > 0:
                # plan + 2 repairs (engine MAX_REPAIR_ATTEMPTS) + margin for
                # perception/execute round-trips.
                timeout = float(ai_timeout) * 3 + 90.0
            else:
                timeout = None  # unlimited: rely on Cancel to stop a stuck request
        return peer.call("user.prompt", params, timeout=timeout)

    def send_user_cancel(self, task_id: str, timeout: float = 10.0) -> dict:
        """
        Ask the engine to cancel the running natural-language task (ADR 0008).
        Returns immediately on the engine side (it just records the request and
        stops at the next checkpoint). MUST be called from a worker thread, NOT
        the Qt main thread, AND it is safe to call while a `user.prompt` is still
        in flight: the JSON-RPC peer is bidirectional and thread-safe (the send is
        lock-guarded and the engine handler pool serves it concurrently).
        """
        peer = self._peer
        if peer is None or not self._connected.is_set():
            raise ConnectionClosed("not connected to the engine")
        return peer.call("user.cancel", {"task_id": task_id}, timeout=timeout)

    # -- internals -------------------------------------------------------------

    def _dispatcher(self, handler, params):
        """Peer dispatcher: marshal onto the Qt main thread if available."""
        if self._invoker is not None:
            return self._invoker.invoke(handler, params)
        return handler(params)  # inline fallback (only outside FreeCAD/tests)

    # -- MANAGED mode (production, ADR 0015): add-on = SERVER, launches engine --

    def _run_managed(self) -> None:
        """
        Open an ephemeral loopback server + token, launch the engine as a client,
        accept its connection and validate the handshake. On any exit, terminate
        the engine so no orphan process survives FreeCAD.
        """
        srv = None
        try:
            self._on_state("connecting")
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((discovery.HOST, 0))       # 127.0.0.1, ephemeral port
            srv.listen(1)
            port = srv.getsockname()[1]
            self._server_token = discovery.generate_token()
            self._log(f"add-on server listening on {discovery.HOST}:{port} "
                      f"(ephemeral port, token generated).")

            # Launch the engine as a CLIENT that connects back to us. Avoids the
            # double start if one is already running (EngineLauncher.is_running).
            started = self._launcher.ensure_running(
                discovery.HOST, port, self._server_token)
            self._log(f"engine launch: {started.get('status')} - {started.get('message')}")
            if not started.get("ok"):
                self._on_state("failed")
                return

            # Wait for the engine to connect back.
            srv.settimeout(self._accept_timeout)
            try:
                client_sock, addr = srv.accept()
            except socket.timeout:
                self._log("the engine did not connect back in time.")
                self._on_state("failed")
                return
            self._log(f"engine connected from {addr}.")
            client_sock.settimeout(None)       # blocking reads on the persistent link
            self._serve_server_session(client_sock)
        except Exception as exc:  # noqa: BLE001 - report and clean up
            self._log(f"managed engine session ended: {exc}")
        finally:
            if srv is not None:
                try:
                    srv.close()
                except OSError:
                    pass
            self._connected.clear()
            self._authenticated.clear()
            try:
                self._launcher.stop()          # no orphan engine left behind
            except Exception:  # pragma: no cover
                pass
            self._on_state("disconnected")
            self._log("managed client terminated (engine stopped).")

    def _serve_server_session(self, sock: socket.socket) -> None:
        """As the SERVER: validate the engine's handshake, then serve until close."""
        conn = FramedConnection(sock)
        peer = JsonRpcPeer(conn, name="addon", dispatcher=self._dispatcher, logger=self._log)
        self._peer = peer
        # As SERVER we EXPOSE session.hello to validate the token (roles swapped).
        peer.register("session.hello", self._on_hello_server)
        self._register_addon_handlers(peer)
        peer.start()

        # The engine (client) greets us with the token; wait for it.
        if not self._authenticated.wait(timeout=self._accept_timeout):
            self._log("the engine did not complete the handshake in time.")
            peer.close()
            raise ConnectionClosed("handshake timeout")

        self._connected.set()
        self._on_state("connected")
        self._log("engine attached and authenticated. Ready to send commands.")

        # Stay alive while the connection holds or until we're asked to stop.
        while not self._stop.is_set():
            if peer.wait_closed(timeout=0.5):
                raise ConnectionClosed("connection closed by the engine")
        peer.close()

    # -- ATTACH mode (debug): add-on = CLIENT, reads the discovery file ---------

    def _run_attach(self) -> None:
        attempts = 0
        while not self._stop.is_set():
            endpoint = discovery.read_endpoint()
            if endpoint is None:
                attempts += 1
                if attempts > self._max_reconnect:
                    self._log("no discovery file: is the engine running? Giving up.")
                    self._on_state("failed")
                    return
                self._log(f"engine not found (discovery file missing). "
                          f"Retrying in {self._reconnect_delay}s... ({attempts}/{self._max_reconnect})")
                self._on_state("connecting")
                self._stop.wait(self._reconnect_delay)
                continue

            host, port, token = endpoint
            try:
                self._serve_session(host, port, token)
                attempts = 0  # session ok: reset the counter.
            except (OSError, JsonRpcError, ConnectionClosed, TimeoutError) as exc:
                attempts += 1
                self._connected.clear()
                self._on_state("disconnected")
                if self._stop.is_set():
                    break
                if attempts > self._max_reconnect:
                    self._log(f"connection failed ({exc}). Attempts exhausted. Giving up.")
                    self._on_state("failed")
                    return
                self._log(f"connection lost/failed: {exc}. "
                          f"Reconnecting in {self._reconnect_delay}s... ({attempts}/{self._max_reconnect})")
                self._stop.wait(self._reconnect_delay)
        self._connected.clear()
        self._on_state("disconnected")
        self._log("client terminated.")

    def _serve_session(self, host: str, port: int, token: str) -> None:
        self._log(f"connecting to {host}:{port} ...")
        self._on_state("connecting")
        sock = socket.create_connection((host, port), timeout=10)
        # IMPORTANT: create_connection leaves a 10s timeout on the socket. The
        # persistent read loop must BLOCK waiting for data, otherwise an idle
        # connection (no traffic while the user reads/types) would raise a socket
        # timeout after 10s and drop. Switch to blocking mode; application-level
        # call timeouts are handled separately by the JSON-RPC peer.
        sock.settimeout(None)
        conn = FramedConnection(sock)
        peer = JsonRpcPeer(conn, name="addon", dispatcher=self._dispatcher, logger=self._log)
        self._peer = peer

        # Register the handlers the engine can call (same set in both topologies).
        self._register_addon_handlers(peer)
        peer.start()

        # Handshake: present the token to the engine (see ADR 0002 for the direction).
        hello = peer.call("session.hello", {
            "token": token,
            "addon_version": ADDON_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        }, timeout=10)
        self._log(f"handshake engine reply: {hello}")
        if not hello.get("ok"):
            raise JsonRpcError(ErrorCode.AUTH_FAILED, "handshake rejected by the engine")

        self.engine_info = hello
        self._connected.set()
        self._on_state("connected")
        self._log("attached to the engine. Ready to send commands from the panel.")

        # Stay alive while the connection holds or until we're asked to stop.
        while not self._stop.is_set():
            if peer.wait_closed(timeout=0.5):
                raise ConnectionClosed("connection closed by the engine")
        peer.close()
