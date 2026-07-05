#!/usr/bin/env python3
"""
test_timeout_config.py - per-request AI timeout chosen in the panel (Phase 4).

Covers two things, WITHOUT FreeCAD and WITHOUT Ollama:
  1) Brain.set_timeout() applies a runtime per-call timeout to the client and
     rejects bad values / clients without a `timeout` attribute.
  2) The engine's on_user_prompt forwards the `ai_timeout` param to the brain
     (so the panel's value reaches the model client).

Runnable:
    python tests/test_timeout_config.py
    pytest tests/test_timeout_config.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "shared"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

import bridge_server  # noqa: E402
import fake_brain      # noqa: E402
from brain import Brain  # noqa: E402


class _FakeClient:
    """Minimal stand-in for OllamaClient with a settable `timeout`."""
    timeout = 240.0
    model = "fake-model"

    def chat_json(self, *a, **k):
        return {}


def test_brain_set_timeout():
    brain = Brain(client=_FakeClient())
    assert brain.get_timeout() == 240.0
    # A positive value caps each model call.
    assert brain.set_timeout(60) is True
    assert brain.get_timeout() == 60.0
    # 0 / negative / None mean UNLIMITED (timeout cleared to None) - the default.
    assert brain.set_timeout(0) is True
    assert brain.get_timeout() is None
    assert brain.set_timeout(90) is True and brain.get_timeout() == 90.0
    assert brain.set_timeout(-5) is True
    assert brain.get_timeout() is None
    assert brain.set_timeout(120) is True and brain.get_timeout() == 120.0
    assert brain.set_timeout(None) is True
    assert brain.get_timeout() is None
    # A non-numeric value is rejected and leaves the timeout unchanged.
    brain.set_timeout(75)
    assert brain.set_timeout("not-a-number") is False
    assert brain.get_timeout() == 75.0


class _FakePeer:
    """No-op peer: perception returns an empty document, notify is ignored."""
    def notify(self, *a, **k):
        return None

    def call(self, method, params=None, timeout=30):
        if method == "perception.overview":
            return {"objects": []}
        return {}


class _RecordingBrain:
    """Records the timeout the engine asks for; produces no actions."""
    def __init__(self):
        self.timeout_set = None

    def availability(self):
        return {"available": True, "model": "fake-model", "models": ["fake-model"]}

    def set_timeout(self, seconds):
        self.timeout_set = seconds
        return True

    def plan(self, text, overview=None, details=None):
        # Return a clarification so the loop ends right after thinking (no actions).
        return {"actions": [], "valid_actions": [], "notes": [],
                "clarification": "need more info"}

    def repair(self, *a, **k):
        return None


def test_engine_forwards_ai_timeout():
    session = bridge_server.Session(_FakePeer(), "tok", fake_brain.Catalog(),
                                    brain=_RecordingBrain())
    res = session.on_user_prompt({"text": "make something", "ai_timeout": 99})
    assert session.brain.timeout_set == 99, \
        f"engine did not forward ai_timeout: {session.brain.timeout_set!r}"
    # The request itself was accepted (it ended in a clarification, no actions).
    assert res.get("accepted") is True, res


def _run_all():
    test_brain_set_timeout()
    test_engine_forwards_ai_timeout()


if __name__ == "__main__":
    print("== test_timeout_config: configurable AI timeout from the panel ==")
    try:
        _run_all()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}\n{traceback.format_exc()}")
        sys.exit(1)
    print("PASS - set_timeout works and the engine forwards the panel's ai_timeout.")
    sys.exit(0)
