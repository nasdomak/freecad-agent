#!/usr/bin/env python3
"""
test_roundtrip.py - FULL round-trip add-on <-> engine <-> add-on, WITHOUT FreeCAD.

This is the most important Phase 1 test: it exercises BOTH directions of the
bridge using the REAL engine code (engine.bridge_server.Session + the fake_brain
fake brain), over a real loopback socket, with a fake "add-on" impersonating the
executor (no FreeCAD).

Sequence proven:
  panel --command.request--> ENGINE --validate--> ENGINE --command.execute--> ADDON
  ADDON --commandResult--> ENGINE --commandResult--> panel

It also proves the anti-deadlock point: the engine's `command.request` handler,
while running, CALLS `command.execute` back on the add-on. It works because the
peer runs incoming handlers on its internal pool, leaving the read loop free to
receive the nested response (see jsonrpc.py and ADR 0003). If this test passes,
the topology holds on FreeCAD too.

Runnable:
    python tests/test_roundtrip.py
    pytest tests/test_roundtrip.py
"""

import os
import socket
import sys
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

from bridge import (  # noqa: E402
    FramedConnection, JsonRpcPeer, JsonRpcError, PROTOCOL_VERSION,
)
import fake_brain        # noqa: E402
import bridge_server     # noqa: E402  (importing it does NOT start the server: that's under __main__)

TOKEN = "roundtrip-test-token"


class _NoAiBrain:
    """
    Stub brain that reports the local model as UNAVAILABLE.

    This test exercises the BRIDGE, not the AI. The real Brain talks to a local
    Ollama if one is installed, which would make step 5 (graceful refusal of
    `user.prompt` when no model is available) non-deterministic: on a machine
    where Ollama happens to be running, the engine would start a real, slow
    inference and the test would hang or time out. Injecting this stub keeps the
    round-trip test fast and identical on every machine (with or without Ollama).
    The full natural-language loop is covered separately, with a fake brain, by
    tests/test_user_prompt_roundtrip.py.
    """

    def availability(self):
        return {"available": False,
                "reason": "local AI intentionally disabled in the bridge test",
                "models": []}


def _make_pair():
    """Pair of connected sockets over loopback (server, client)."""
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
    srv_sock, cli_sock = _make_pair()
    catalog = fake_brain.Catalog()
    details = {}

    # --- ENGINE side: real code (Session). The peer runs incoming handlers on
    #     its internal pool, so command.request can call command.execute. ---
    eng_conn = FramedConnection(srv_sock)
    eng_peer = JsonRpcPeer(eng_conn, name="engine")
    # Inject the stub brain so step 5 is deterministic regardless of whether a
    # local Ollama is installed/running on this machine.
    session = bridge_server.Session(eng_peer, TOKEN, catalog, brain=_NoAiBrain())
    eng_peer.register("session.hello", session.on_hello)
    eng_peer.register("command.request", session.on_command_request)
    eng_peer.register("user.prompt", session.on_user_prompt)
    eng_peer.register("user.cancel", session.on_user_cancel)
    eng_peer.start()

    # --- FAKE ADD-ON side: an executor that records the invocation (no FreeCAD) ---
    recorded = {}
    statuses = []

    def on_command_execute(params):
        recorded["invocation"] = params
        return {"ok": True, "transaction_id": "tx-roundtrip-001",
                "created_ids": ["Box"], "recompute_ok": True}

    def on_agent_status(params):
        statuses.append(params)

    add_peer = JsonRpcPeer(FramedConnection(cli_sock), name="addon")
    add_peer.register("command.execute", on_command_execute)
    add_peer.register("agent.status", on_agent_status)
    add_peer.start()

    try:
        # 1) handshake addon -> engine
        hello = add_peer.call("session.hello",
                              {"token": TOKEN, "protocol_version": PROTOCOL_VERSION}, timeout=5)
        assert hello["ok"] is True, "handshake not ok"
        assert "create_box" in hello.get("commands", []), "handshake does not report the vocabulary"
        details["handshake"] = hello.get("commands")

        # 2) VALID command: the engine validates it and forwards it to the add-on (round-trip)
        inv = {"cmd": "create_box", "params": {"length": 20, "width": 15, "height": 10}}
        result = add_peer.call("command.request", inv, timeout=10)
        assert result["ok"] is True, f"valid command.request failed: {result}"
        assert recorded.get("invocation") == inv, "the add-on did not receive the exact invocation"
        assert result["created_ids"] == ["Box"], "unexpected created_ids"
        # agent.status notifications are asynchronous (fire-and-forget): the final
        # 'completed' one may land just after command.request returns. Poll briefly.
        deadline = time.time() + 3.0
        while time.time() < deadline and not any(s.get("phase") == "completed" for s in list(statuses)):
            time.sleep(0.02)
        assert any(s.get("phase") == "completed" for s in statuses), \
            "missing the agent.status 'completed' notification"
        details["roundtrip_valid"] = result

        # 3) INVALID command (missing height): graceful refusal, NO command.execute
        recorded.clear()
        bad = {"cmd": "create_box", "params": {"length": 20, "width": 15}}
        res_bad = add_peer.call("command.request", bad, timeout=10)
        assert res_bad["ok"] is False, "invalid command wrongly accepted"
        assert "validation" in res_bad["error"], f"unexpected error: {res_bad['error']}"
        assert "invocation" not in recorded, "command.execute should NOT have been called"
        details["validation_refusal"] = res_bad["error"]

        # 4) unknown command: rejected
        res_unknown = add_peer.call("command.request", {"cmd": "fly", "params": {}}, timeout=10)
        assert res_unknown["ok"] is False, "unknown command accepted"
        details["unknown_command"] = "rejected"

        # 5) user.prompt: implemented in Phase 2, but here no Ollama is running, so
        #    the engine must degrade gracefully (principle 9): accepted=False with a
        #    clear reason, never a crash. (The full NL loop is covered, with a fake
        #    brain, by tests/test_user_prompt_roundtrip.py.)
        res_prompt = add_peer.call("user.prompt", {"text": "make me a box"}, timeout=10)
        assert res_prompt["accepted"] is False, \
            "without Ollama, user.prompt should be refused gracefully"
        assert res_prompt.get("error"), "the refusal should explain why"
        details["user_prompt"] = "gracefully refused (no Ollama)"

        # 6) multiple commands in the SAME session (persistent engine)
        inv2 = {"cmd": "create_cylinder", "params": {"radius": 4, "height": 9}}
        res2 = add_peer.call("command.request", inv2, timeout=10)
        assert res2["ok"] is True, "second command in the same session failed"
        details["multi_command"] = "ok"

        return True, details
    finally:
        add_peer.close()
        eng_peer.close()


def test_roundtrip():
    ok, details = run_scenario()
    assert ok, f"round-trip failed: {details}"


if __name__ == "__main__":
    print("== test_roundtrip: addon<->engine<->addon with the real code (without FreeCAD) ==")
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
    print("PASS - full round-trip, validation and anti-deadlock OK.")
    sys.exit(0)
