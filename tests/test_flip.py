#!/usr/bin/env python3
"""
test_flip.py - PRODUCTION topology (the "flip", ADR 0015), WITHOUT FreeCAD.

After the flip the ADD-ON is the TCP SERVER and the ENGINE is the CLIENT. This
test drives the REAL engine client code (bridge_server.run_as_client) against a
fake add-on server that validates the handshake token, and proves:

  1. the engine connects and greets the add-on with the token via session.hello
     (handshake roles swapped: the ADD-ON now validates);
  2. bidirectional calls still work in the flipped topology - the add-on (server)
     calls `command.request` on the engine, and the engine calls `command.execute`
     back on the add-on (the anti-deadlock pool of ADR 0003 still holds);
  3. a WRONG token is rejected and the engine exits with code 2.

Runnable:
    python tests/test_flip.py
    pytest tests/test_flip.py
"""

import os
import socket
import sys
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

# Never touch a real Ollama from the tests.
os.environ["FREECAD_AGENT_NO_AUTOSTART"] = "1"

from bridge import (  # noqa: E402
    FramedConnection, JsonRpcPeer, JsonRpcError, ErrorCode, PROTOCOL_VERSION,
)
import bridge_server  # noqa: E402


class _NoAiBrain:
    """Stub brain: reports the local model as unavailable (no Ollama in tests)."""

    def availability(self):
        return {"available": False, "reason": "AI disabled in the flip test",
                "models": []}


def _start_addon_server(token_expected):
    """
    Start a fake ADD-ON server (the flipped role). Returns (host, port, holder).
    `holder` is filled once the engine connects: authed Event, the peer, and the
    invocation recorded when the engine calls command.execute back.
    """
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    port = lst.getsockname()[1]
    holder = {"authed": threading.Event(), "recorded": {}, "peer": None,
              "statuses": []}

    def _serve():
        srv_sock, _ = lst.accept()
        lst.close()
        peer = JsonRpcPeer(FramedConnection(srv_sock), name="addon-test")

        def on_hello(params):
            # The ADD-ON validates the token now (roles swapped).
            if params.get("token") != token_expected:
                raise JsonRpcError(ErrorCode.AUTH_FAILED, "wrong token")
            holder["engine_version"] = params.get("engine_version")
            holder["authed"].set()
            return {"ok": True, "addon_version": "test",
                    "protocol_version": PROTOCOL_VERSION}

        def on_command_execute(params):
            holder["recorded"]["invocation"] = params
            return {"ok": True, "transaction_id": "tx-flip",
                    "created_ids": ["Box"], "recompute_ok": True}

        def on_agent_status(params):
            holder["statuses"].append(params)

        peer.register("session.hello", on_hello)
        peer.register("command.execute", on_command_execute)
        peer.register("agent.status", on_agent_status)
        peer.start()
        holder["peer"] = peer

    threading.Thread(target=_serve, daemon=True).start()
    return "127.0.0.1", port, holder


def run_scenario():
    details = {}

    # --- 1) GOOD token: handshake + bidirectional round-trip ---
    token = "flip-good-token"
    host, port, holder = _start_addon_server(token)
    rc = {}

    def _engine():
        rc["code"] = bridge_server.run_as_client(
            host, port, token, brain=_NoAiBrain(),
            connect_timeout=5, connect_attempts=40)

    et = threading.Thread(target=_engine, daemon=True)
    et.start()

    assert holder["authed"].wait(5), "the engine did not complete the handshake"
    details["handshake"] = "ok (engine greeted the add-on server with the token)"

    # Wait until the add-on peer object is available.
    deadline = time.time() + 5
    while holder["peer"] is None and time.time() < deadline:
        time.sleep(0.02)
    peer = holder["peer"]
    assert peer is not None, "the add-on server peer was not set up"

    # The ADD-ON (server) calls command.request on the ENGINE (client); the engine
    # validates and calls command.execute BACK on the add-on -> full round-trip.
    inv = {"cmd": "create_box", "params": {"length": 20, "width": 15, "height": 10}}
    result = peer.call("command.request", inv, timeout=10)
    assert result["ok"] is True, f"command.request failed: {result}"
    assert holder["recorded"].get("invocation") == inv, \
        "the engine did not call command.execute back with the exact invocation"
    details["roundtrip"] = "ok (command.request -> command.execute back)"

    # Closing the add-on peer ends the engine's session -> clean exit code 0.
    peer.close()
    et.join(timeout=5)
    assert rc.get("code") == 0, f"the engine did not exit cleanly: {rc}"
    details["clean_exit"] = rc["code"]

    # --- 2) WRONG token: the add-on rejects it, the engine exits 2 ---
    host2, port2, holder2 = _start_addon_server("the-right-token")
    rc2 = {}

    def _engine_bad():
        rc2["code"] = bridge_server.run_as_client(
            host2, port2, "the-WRONG-token", brain=_NoAiBrain(),
            connect_timeout=5, connect_attempts=40)

    bt = threading.Thread(target=_engine_bad, daemon=True)
    bt.start()
    bt.join(timeout=6)
    assert rc2.get("code") == 2, \
        f"a wrong token should make the engine exit 2, got {rc2}"
    assert not holder2["authed"].is_set(), \
        "the add-on wrongly authenticated a bad token"
    details["bad_token_rejected"] = rc2["code"]

    return True, details


def test_flip():
    ok, details = run_scenario()
    assert ok, f"flip scenario failed: {details}"


if __name__ == "__main__":
    print("== test_flip: PRODUCTION topology (addon=server, engine=client) ==")
    try:
        ok, details = run_scenario()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    for k, v in details.items():
        print(f"  [ok] {k}: {v}")
    print("PASS - flipped handshake, bidirectional round-trip, bad token rejected.")
    sys.exit(0)
