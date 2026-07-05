#!/usr/bin/env python3
"""
test_launcher.py - engine launcher + FreeCAD-Python finder (ADR 0015), headless.

No FreeCAD, no real subprocess: the interpreter finder and the spawn call are
injected, so every branch is deterministic:
  - find_freecad_python: bundled interpreter found; and the PATH/current-exe
    fallback when the bundled one is absent;
  - find_engine_script: resolves the REAL engine/bridge_server.py from the tree;
  - ensure_running: launches once, does NOT relaunch if already running;
  - stop: terminates the process (idempotent);
  - graceful failure when no interpreter / no script is found (principle 9).

Runnable:
    python tests/test_launcher.py
    pytest tests/test_launcher.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Import the module directly (no FreeCAD-bound package imports).
sys.path.insert(0, os.path.join(_REPO_ROOT, "addon", "ai_copilot"))

import engine_launcher as EL  # noqa: E402


class _FakeProc:
    """Minimal process double: alive until terminate()/kill()."""

    def __init__(self, pid=4242):
        self.pid = pid
        self._alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


def run_scenario():
    details = {}

    # --- find_freecad_python: bundled interpreter present ---
    def exists_bundled(path):
        p = path.replace("\\", "/")
        return "/fake/fc/bin/" in p

    found = EL.find_freecad_python(home="/fake/fc", exists=exists_bundled)
    assert found is not None and "bin" in found.replace("\\", "/"), \
        f"bundled interpreter not found: {found}"
    details["bundled_python"] = found

    # --- find_freecad_python: nothing bundled -> falls back to current exe/PATH ---
    fallback = EL.find_freecad_python(home=None, exists=lambda p: False)
    # With exists() always False the bundled + current-exe checks fail; the PATH
    # fallback (shutil.which) should still find a python on any test machine.
    assert fallback is not None, "no interpreter found even via PATH fallback"
    details["fallback_python"] = fallback

    # --- find_engine_script: resolves the real script from THIS tree ---
    script = EL.find_engine_script(
        start=os.path.join(_REPO_ROOT, "addon", "ai_copilot", "engine_launcher.py"))
    assert script and script.endswith("bridge_server.py") and os.path.isfile(script), \
        f"engine script not resolved: {script}"
    details["engine_script"] = os.path.basename(script)

    # --- ensure_running: launches once, no double start; stop terminates ---
    spawned = []

    def spawn(cmd, log_path):
        spawned.append((cmd, log_path))
        return _FakeProc()

    launcher = EL.EngineLauncher(
        python_finder=lambda: "py",
        script_finder=lambda: "/x/engine/bridge_server.py",
        spawn=spawn,
        log_file="/tmp/fca_engine_test.log")

    r1 = launcher.ensure_running("127.0.0.1", 5555, "tok")
    assert r1["ok"] and r1["status"] == "launched", f"launch failed: {r1}"
    assert launcher.is_running(), "launcher should report running after launch"
    assert spawned[0][0] == ["py", "/x/engine/bridge_server.py",
                             "--host", "127.0.0.1", "--port", "5555", "--token", "tok"], \
        f"unexpected command line: {spawned[0][0]}"
    details["launched"] = spawned[0][0]

    r2 = launcher.ensure_running("127.0.0.1", 5555, "tok")
    assert r2["status"] == "already-running", f"should not relaunch: {r2}"
    assert len(spawned) == 1, "the engine was spawned twice (double start)"
    details["no_double_start"] = True

    s = launcher.stop()
    assert s["status"] == "stopped", f"stop should terminate: {s}"
    assert not launcher.is_running(), "launcher should report stopped after stop"
    # stop again is a no-op.
    assert launcher.stop()["status"] == "not-running"
    details["stopped"] = True

    # --- graceful failure: no interpreter, no script ---
    no_py = EL.EngineLauncher(python_finder=lambda: None,
                              script_finder=lambda: "/x/s.py", spawn=spawn)
    rp = no_py.ensure_running("h", 1, "t")
    assert not rp["ok"] and rp["status"] == "no-python", f"expected no-python: {rp}"

    no_script = EL.EngineLauncher(python_finder=lambda: "py",
                                  script_finder=lambda: None, spawn=spawn)
    rs = no_script.ensure_running("h", 1, "t")
    assert not rs["ok"] and rs["status"] == "no-script", f"expected no-script: {rs}"
    details["graceful_failures"] = "no-python + no-script"

    return True, details


def test_launcher():
    ok, details = run_scenario()
    assert ok, f"launcher scenario failed: {details}"


if __name__ == "__main__":
    print("== test_launcher: engine launcher + FreeCAD-Python finder ==")
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
    print("PASS - interpreter finder, script resolution, launch/stop, graceful fails.")
    sys.exit(0)
