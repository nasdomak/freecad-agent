#!/usr/bin/env python3
"""
mock_addon_client.py - a FAKE add-on to test the PERSISTENT engine without FreeCAD.

It impersonates the add-on+panel: it connects to the engine, does the handshake,
then SENDS structured commands (`command.request`) just like the panel would when
you click «Run». For the returning `command.execute` it does NOT touch FreeCAD:
it simulates the execution and prints what it would do. Useful to validate the
engine before opening FreeCAD.

Use:
    Terminal 1:  python engine/bridge_server.py     (or START_ENGINE.bat)
    Terminal 2:  python tests/mock_addon_client.py
"""

import os
import sys
import socket
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))

from bridge import (  # noqa: E402
    FramedConnection, JsonRpcPeer, JsonRpcError, discovery, PROTOCOL_VERSION,
)


def log(msg):
    print(f"[mock-addon] {msg}", flush=True)


def on_command_execute(params):
    # Does NOT touch FreeCAD: simulate a successful transaction conforming to commandResult.
    log(f"  <- command.execute from the engine: {params}")
    log("     (mock) pretending to create the object inside an undoable transaction")
    return {"ok": True, "transaction_id": "tx-mock-0001",
            "created_ids": ["Box"], "recompute_ok": True}


def on_agent_status(params):
    log(f"  · status: {params.get('phase')}: {params.get('message')}")


def main():
    endpoint = discovery.read_endpoint()
    if endpoint is None:
        log("discovery file not found: start the engine first (START_ENGINE.bat).")
        return 2
    host, port, token = endpoint
    log(f"connecting to {host}:{port}")
    sock = socket.create_connection((host, port), timeout=10)
    peer = JsonRpcPeer(FramedConnection(sock), name="mock-addon", logger=log)
    peer.register("command.execute", on_command_execute)
    peer.register("agent.status", on_agent_status)
    peer.start()

    hello = peer.call("session.hello", {
        "token": token, "addon_version": "mock", "protocol_version": PROTOCOL_VERSION,
    }, timeout=10)
    log(f"handshake: {hello}")
    if not hello.get("ok"):
        log("handshake rejected")
        return 1

    # 1) VALID command -> the engine validates it and forwards it to us (command.execute)
    log("sending a VALID command.request (create_box 20x15x10)...")
    res = peer.call("command.request",
                    {"cmd": "create_box", "params": {"length": 20, "width": 15, "height": 10}},
                    timeout=15)
    log(f"  -> result: {res}")

    # 2) INVALID command -> graceful refusal, no command.execute
    log("sending an INVALID command.request (missing 'height')...")
    res_bad = peer.call("command.request",
                        {"cmd": "create_box", "params": {"length": 20, "width": 15}},
                        timeout=15)
    log(f"  -> result: {res_bad}")

    log("test done. Closing (the engine stays listening for other clients).")
    peer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
