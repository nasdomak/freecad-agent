#!/usr/bin/env python3
"""
test_bridge_core.py - test the bridge OUTSIDE FreeCAD (RISK #2 isolated).

Shows that the bridge core (shared/bridge) works without FreeCAD: it connects two
JsonRpcPeers over a real loopback socket and runs handshake + ping/pong + a
command.execute (with a fake executor). No AI, no FreeCAD.

Runnable two ways:
    python tests/test_bridge_core.py        # prints PASS/FAIL and exits 0/1
    pytest tests/test_bridge_core.py        # as a pytest test
"""

import os
import socket
import sys
import threading
import time

# Make shared/bridge importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))

from bridge import (  # noqa: E402
    FramedConnection, JsonRpcPeer, JsonRpcError, ErrorCode, PROTOCOL_VERSION,
)

TOKEN = "test-token-0123456789"


def _make_pair():
    """Create a pair of connected sockets over loopback (server+client)."""
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    port = lst.getsockname()[1]

    holder = {}

    def _accept():
        holder["srv"], _ = lst.accept()

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    cli = socket.create_connection(("127.0.0.1", port), timeout=5)
    t.join(timeout=5)
    lst.close()
    return holder["srv"], cli


def run_scenario():
    """Return (ok: bool, details: dict)."""
    srv_sock, cli_sock = _make_pair()

    # --- "engine" side (server) ---
    authed = threading.Event()

    def on_hello(params):
        if params.get("token") != TOKEN:
            raise JsonRpcError(ErrorCode.AUTH_FAILED, "wrong token")
        authed.set()
        return {"ok": True, "engine_version": "test", "protocol_version": PROTOCOL_VERSION}

    engine = JsonRpcPeer(FramedConnection(srv_sock), name="engine-test")
    engine.register("session.hello", on_hello)
    engine.start()

    # --- "add-on" side (client) with a FAKE executor (no FreeCAD) ---
    executed = {}

    def on_ping(params):
        return {"pong": True, "echo_ts": params.get("ts")}

    def on_command_execute(params):
        executed["invocation"] = params
        # Simulate a successful transaction conforming to commandResult.
        return {
            "ok": True,
            "transaction_id": "tx-fake-001",
            "created_ids": ["Box"],
            "recompute_ok": True,
        }

    addon = JsonRpcPeer(FramedConnection(cli_sock), name="addon-test")
    addon.register("ping", on_ping)
    addon.register("command.execute", on_command_execute)
    addon.start()

    details = {}
    try:
        # 1) handshake (addon -> engine)
        hello = addon.call("session.hello", {"token": TOKEN, "protocol_version": PROTOCOL_VERSION})
        assert hello["ok"] is True, "handshake not ok"
        assert authed.wait(2), "engine not authenticated"
        details["hello"] = hello

        # 2) ping (engine -> addon)
        pong = engine.call("ping", {"ts": 123.0})
        assert pong == {"pong": True, "echo_ts": 123.0}, f"unexpected pong: {pong}"
        details["pong"] = pong

        # 3) command.execute create_box (engine -> addon)
        invocation = {"cmd": "create_box", "params": {"length": 20, "width": 15, "height": 10}}
        result = engine.call("command.execute", invocation)
        assert result["ok"] is True, "command.execute not ok"
        assert result["created_ids"] == ["Box"], "unexpected created_ids"
        assert executed["invocation"] == invocation, "the add-on did not receive the exact invocation"
        details["command_result"] = result

        # 4) wrong token -> must be rejected
        s2, c2 = _make_pair()
        eng2 = JsonRpcPeer(FramedConnection(s2), name="engine2")
        eng2.register("session.hello", on_hello)
        eng2.start()
        add2 = JsonRpcPeer(FramedConnection(c2), name="addon2")
        add2.start()
        rejected = False
        try:
            add2.call("session.hello", {"token": "WRONG"})
        except JsonRpcError as exc:
            rejected = (exc.code == ErrorCode.AUTH_FAILED)
        assert rejected, "the wrong token was NOT rejected"
        details["bad_token_rejected"] = True
        eng2.close(); add2.close()

        # 5) unknown method -> METHOD_NOT_FOUND
        method_err = False
        try:
            engine.call("method.does_not_exist", {})
        except JsonRpcError as exc:
            method_err = (exc.code == ErrorCode.METHOD_NOT_FOUND)
        assert method_err, "unknown method not handled"
        details["unknown_method_handled"] = True

        return True, details
    finally:
        engine.close()
        addon.close()


# --- pytest interface ---
def test_bridge_core():
    ok, details = run_scenario()
    assert ok, f"scenario failed: {details}"


if __name__ == "__main__":
    print("== test_bridge_core: addon<->engine bridge WITHOUT FreeCAD ==")
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
    print("PASS - the bridge carries handshake, ping/pong and command.execute.")
    sys.exit(0)
