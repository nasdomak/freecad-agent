#!/usr/bin/env python3
"""
test_cancel.py - cooperative cancellation of a natural-language task (ADR 0008).

Scenario, WITHOUT FreeCAD and WITHOUT Ollama:
  - the add-on sends `user.prompt`;
  - the engine perceives, then "thinks" (here a scripted brain BLOCKS inside
    plan(), simulating a slow model inference);
  - while the engine is thinking, the add-on sends `user.cancel(task_id)`;
  - we release the (slow) plan; the engine reaches the post-think checkpoint,
    sees the cancellation and STOPS, running NOTHING on the add-on.

Asserts the key safety property: after a cancel during thinking, no
`command.execute` (and no `python.execute`) ever reaches FreeCAD, and the
`user.prompt` result is reported as cancelled.

Runnable:
    python tests/test_cancel.py
    pytest tests/test_cancel.py
"""

import os
import socket
import sys
import threading
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

from bridge import FramedConnection, JsonRpcPeer, PROTOCOL_VERSION  # noqa: E402
import bridge_server  # noqa: E402
import fake_brain      # noqa: E402

TOKEN = "cancel-token"


class SlowCancelBrain:
    """Scripted brain whose plan() blocks until the test releases it."""

    def __init__(self):
        self.plan_started = threading.Event()
        self.release = threading.Event()

    def availability(self):
        return {"available": True, "model": "fake-model", "models": ["fake-model"]}

    def plan(self, text, overview=None, details=None):
        # Simulate a slow inference: signal we started, then wait for the test.
        self.plan_started.set()
        self.release.wait(timeout=5)
        # A perfectly valid plan: if the checkpoint did NOT stop us, this WOULD run.
        actions = [{"type": "command", "cmd": "create_box",
                    "params": {"length": 10, "width": 10, "height": 10}}]
        return {"actions": actions, "valid_actions": actions,
                "notes": [], "clarification": None}

    def repair(self, *a, **k):
        return None


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
    srv_sock, cli_sock = _make_pair()
    catalog = fake_brain.Catalog()
    brain = SlowCancelBrain()

    eng_peer = JsonRpcPeer(FramedConnection(srv_sock), name="engine")
    session = bridge_server.Session(eng_peer, TOKEN, catalog, brain=brain)
    eng_peer.register("session.hello", session.on_hello)
    eng_peer.register("user.prompt", session.on_user_prompt)
    eng_peer.register("user.cancel", session.on_user_cancel)
    eng_peer.start()

    # ADD-ON side: record any execution attempt; there must be NONE after cancel.
    executed = []
    statuses = []
    add_peer = JsonRpcPeer(FramedConnection(cli_sock), name="addon")
    add_peer.register("command.execute", lambda p: executed.append(("command", p)) or
                      {"ok": True, "transaction_id": "tx", "created_ids": []})
    add_peer.register("python.execute", lambda p: executed.append(("python", p)) or
                      {"ok": True, "transaction_id": "tx", "created_ids": []})
    add_peer.register("perception.overview", lambda p: {"objects": []})
    add_peer.register("perception.detail", lambda p: {})
    add_peer.register("agent.status", lambda p: statuses.append(p))
    add_peer.start()

    details = {}
    try:
        hello = add_peer.call("session.hello",
                              {"token": TOKEN, "protocol_version": PROTOCOL_VERSION}, timeout=5)
        assert hello["ok"], "handshake failed"

        # Run user.prompt on its own thread (it blocks until the engine returns).
        prompt_result = {}

        def do_prompt():
            prompt_result["res"] = add_peer.call(
                "user.prompt", {"text": "make a box"}, timeout=30)

        t = threading.Thread(target=do_prompt, name="prompt", daemon=True)
        t.start()

        # Wait until the engine is "thinking" (plan() entered and blocked).
        assert brain.plan_started.wait(timeout=5), "plan() never started"

        # Find the running task id from the streamed agent.status notifications.
        task_id = None
        deadline = time.time() + 3
        while time.time() < deadline and not task_id:
            for s in list(statuses):
                if s.get("task_id"):
                    task_id = s["task_id"]
                    break
            time.sleep(0.02)
        assert task_id, f"no task_id seen in statuses: {statuses}"
        details["task_id"] = task_id

        # Cancel WHILE the engine is still thinking.
        cancel_res = add_peer.call("user.cancel", {"task_id": task_id}, timeout=5)
        assert cancel_res.get("ok"), f"cancel rejected: {cancel_res}"

        # Now let the slow plan() finish: the engine should hit the post-think
        # checkpoint, see the cancellation and stop WITHOUT executing anything.
        brain.release.set()
        t.join(timeout=5)
        assert not t.is_alive(), "user.prompt did not return after cancel"

        res = prompt_result.get("res")
        assert isinstance(res, dict), f"no result: {res}"
        assert res.get("cancelled") is True, f"result not marked cancelled: {res}"
        assert executed == [], f"actions ran despite cancel: {executed}"
        # The 'cancelled' agent.status is fire-and-forget and may arrive just after
        # the user.prompt response: wait briefly for it (async notification).
        deadline = time.time() + 2
        while time.time() < deadline and not any(
                s.get("phase") == "cancelled" for s in list(statuses)):
            time.sleep(0.02)
        assert any(s.get("phase") == "cancelled" for s in statuses), \
            "no 'cancelled' status emitted"
        details["executed_actions"] = len(executed)
        details["result_summary"] = res.get("summary")

        # Sanity: an unknown task_id is refused (no silent success).
        bad = add_peer.call("user.cancel", {"task_id": ""}, timeout=5)
        assert bad.get("ok") is False, f"empty task_id should be refused: {bad}"

        return True, details
    finally:
        add_peer.close()
        eng_peer.close()


def test_cancel():
    ok, details = run_scenario()
    assert ok, f"cancellation test failed: {details}"


if __name__ == "__main__":
    print("== test_cancel: cancel during thinking -> nothing runs on FreeCAD ==")
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
    print("PASS - cooperative cancellation stops the agent with zero actions run.")
    sys.exit(0)
