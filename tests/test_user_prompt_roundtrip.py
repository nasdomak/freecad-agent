#!/usr/bin/env python3
"""
test_user_prompt_roundtrip.py - the FULL natural-language loop, WITHOUT FreeCAD
and WITHOUT Ollama.

This is the Phase 2 headline test. It wires the REAL engine orchestration
(bridge_server.Session.on_user_prompt) to a fake "add-on" that runs the REAL
executor + perception against a mock FreeCAD. The model is replaced by a scripted
FakeBrain so the flow is deterministic.

Proven sequence (both bridge directions + nested calls, ADR 0003):
  addon --user.prompt--> ENGINE
  ENGINE --perception.overview--> addon            (the agent looks)
  ENGINE --(FakeBrain plan)                          (the agent thinks)
  ENGINE --command.execute / python.execute--> addon (the agent acts)
  ENGINE --(self-correction via FakeBrain.repair)--> addon (the agent fixes)

Runnable:
    python tests/test_user_prompt_roundtrip.py
    pytest tests/test_user_prompt_roundtrip.py
"""

import os
import socket
import sys
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon"))

import mock_freecad  # noqa: E402
from bridge import FramedConnection, JsonRpcPeer, PROTOCOL_VERSION  # noqa: E402
import bridge_server  # noqa: E402
import fake_brain      # noqa: E402

TOKEN = "nl-roundtrip-token"


class FakeBrain:
    """A scripted stand-in for the Ollama-backed Brain."""

    last_details = None  # records the geometric detail the engine passed to plan()

    def availability(self):
        return {"available": True, "model": "fake-model", "models": ["fake-model"]}

    def plan(self, text, overview=None, details=None):
        # Phase 3: the engine now passes geometric detail; remember we received it.
        FakeBrain.last_details = details
        if "fail" in text:
            # An action that will fail at execution (boolean of a body with itself).
            actions = [{"type": "command", "cmd": "boolean",
                        "params": {"op": "difference", "a": "Box", "b": "Box"}}]
        else:
            actions = [
                {"type": "command", "cmd": "create_box",
                 "params": {"length": 20, "width": 15, "height": 10}},
                # No position: exercise the Phase 3 auto-centred drilling.
                {"type": "command", "cmd": "drill_hole",
                 "params": {"target": "Box", "diameter": 5, "depth": 10}},
                {"type": "python", "code": "doc.addObject('Part::Sphere', 'Ball')",
                 "reason": "there is no sphere command in the vocabulary yet"},
            ]
        return {"actions": actions, "valid_actions": actions,
                "notes": [], "clarification": None}

    def repair(self, text, action, error, overview=None, details=None):
        # Fix the failed boolean by making a separate cylinder instead.
        return {"type": "command", "cmd": "create_cylinder",
                "params": {"radius": 3, "height": 6}}


def _wait_phase(statuses, phase, timeout=3.0):
    """agent.status notifications are async; give the last one time to arrive."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(s.get("phase") == phase for s in list(statuses)):
            return True
        time.sleep(0.02)
    return False


def _make_pair():
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
    mock_freecad.install()
    try:
        import ai_copilot.executor as executor
        from ai_copilot import perception

        srv_sock, cli_sock = _make_pair()
        catalog = fake_brain.Catalog()
        details = {}

        # ENGINE side: real Session with the scripted brain injected.
        eng_peer = JsonRpcPeer(FramedConnection(srv_sock), name="engine")
        session = bridge_server.Session(eng_peer, TOKEN, catalog, brain=FakeBrain())
        eng_peer.register("session.hello", session.on_hello)
        eng_peer.register("command.request", session.on_command_request)
        eng_peer.register("user.prompt", session.on_user_prompt)
        eng_peer.start()

        # ADD-ON side: real executor + perception over the mock FreeCAD.
        statuses = []

        add_peer = JsonRpcPeer(FramedConnection(cli_sock), name="addon")
        add_peer.register("command.execute", lambda p: executor.execute(p))
        add_peer.register("python.execute",
                          lambda p: executor.run_python(p.get("code", ""), p.get("reason", "")))
        add_peer.register("perception.overview", lambda p: perception.overview())
        add_peer.register("perception.detail", lambda p: perception.detail(p.get("target", "")))
        add_peer.register("agent.status", lambda p: statuses.append(p))
        add_peer.start()

        try:
            hello = add_peer.call("session.hello",
                                  {"token": TOKEN, "protocol_version": PROTOCOL_VERSION}, timeout=5)
            assert hello["ok"], "handshake failed"

            # 1) Natural-language request -> full plan executed.
            res = add_peer.call("user.prompt",
                                {"text": "make a box with a hole and a sphere"}, timeout=30)
            assert res["accepted"], f"prompt refused: {res}"
            results = res["results"]
            assert len(results) == 3, f"expected 3 actions, got {results}"
            assert all(r.get("ok") for r in results), f"some action failed: {results}"
            # The python action actually created the sphere in the mock document.
            import FreeCAD
            names = [o.Name for o in FreeCAD.ActiveDocument.Objects]
            assert "Box" in names and "Ball" in names, names
            assert _wait_phase(statuses, "perceiving"), "no perceive status"
            assert _wait_phase(statuses, "completed"), "no completed status"
            details["full_plan"] = res["summary"]

            # 2) Self-correction: a failing action gets repaired and retried.
            statuses.clear()
            res2 = add_peer.call("user.prompt", {"text": "please fail then fix it"}, timeout=30)
            assert res2["accepted"], res2
            assert res2["results"] and res2["results"][0].get("ok"), \
                f"self-correction did not recover: {res2}"
            assert _wait_phase(statuses, "repair"), "no repair status emitted"
            details["self_correction"] = "recovered after repair"

            # 3) Phase 3 geometric RAG: by now the document has objects, so the
            #    engine must have fetched perception.detail and handed it to the brain.
            assert isinstance(FakeBrain.last_details, list) and FakeBrain.last_details, \
                f"expected geometric detail to reach the brain, got {FakeBrain.last_details!r}"
            assert any(d.get("named_subelements") for d in FakeBrain.last_details), \
                "detail should carry referenceable sub-elements (Edge*/Face*)"
            details["geometric_rag"] = f"{len(FakeBrain.last_details)} object detail(s) used"

            return True, details
        finally:
            add_peer.close()
            eng_peer.close()
    finally:
        mock_freecad.uninstall()


def test_user_prompt_roundtrip():
    ok, details = run_scenario()
    assert ok, f"NL round-trip failed: {details}"


if __name__ == "__main__":
    print("== test_user_prompt_roundtrip: prompt -> perceive -> plan -> act -> repair ==")
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
    print("PASS - the full natural-language loop works end to end.")
    sys.exit(0)
