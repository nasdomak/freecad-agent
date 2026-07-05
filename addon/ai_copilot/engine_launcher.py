"""
engine_launcher.py - start/stop the FreeCAD Agent engine as a SEPARATE process.

ADR 0015 (engine lifecycle). The add-on starts the engine (engine/bridge_server.py)
as its OWN operating-system process, so the user never has to launch anything from
disk. The engine is pure stdlib (ADR 0004), therefore it can run on the Python
interpreter BUNDLED with FreeCAD -> ZERO installation for the user.

Production topology (the "flip", ADR 0015 / ADR 0002 prod): the ADD-ON is the TCP
server; the engine is the CLIENT. We pass host/port/token to the engine on the
command line; it connects back and presents the token via session.hello. The
engine's stdout/stderr are redirected to a log file, so no console window is
needed (a plain double-click experience).

Testability (principle 8): every piece the process model needs - the interpreter
finder and the actual spawn - is INJECTABLE, so the whole launcher is unit-tested
headless, with no FreeCAD and no real subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

# Where the engine writes its log when launched by the add-on. Shown in the panel.
DEFAULT_LOG_DIR = Path.home() / ".freecad-agent"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "engine.log"


# --- finding the interpreter and the engine script ---------------------------

def _freecad_home() -> Optional[str]:
    """FreeCAD install root, or None outside FreeCAD (tests)."""
    try:
        import FreeCAD  # type: ignore
        return FreeCAD.getHomePath()
    except Exception:
        return None


def find_freecad_python(home: Optional[str] = None,
                        exists: Callable[[str], bool] = os.path.isfile) -> Optional[str]:
    """
    Locate a Python interpreter to run the engine, cross-platform.

    Search order (first hit wins):
      1) FreeCAD's bundled interpreter: <home>/bin/python(.exe) / python3.
      2) the current interpreter (sys.executable) if it looks like python -
         covers running inside FreeCAD's own python, or headless tests.
      3) 'python3' / 'python' on the PATH (shutil.which) - reasoned fallback so
         the add-on still works if the bundled interpreter cannot be located
         (graceful degradation, principle 9).

    `home`/`exists` are injectable for headless tests. Returns a path/command
    string, or None if nothing usable is found (the caller degrades with a clear
    message).
    """
    if home is None:
        home = _freecad_home()

    candidates = []
    if home:
        bindir = os.path.join(home, "bin")
        names = ("python.exe", "python") if os.name == "nt" else ("python3", "python")
        candidates.extend(os.path.join(bindir, n) for n in names)
    for cand in candidates:
        if exists(cand):
            return cand

    exe = sys.executable
    if exe and exists(exe) and "python" in os.path.basename(exe).lower():
        return exe

    import shutil
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return None


def find_engine_script(start: Optional[str] = None) -> Optional[str]:
    """
    Absolute path to engine/bridge_server.py, resolved RELATIVE to this add-on
    install (no hard-coded paths, works for the open-source release). This module
    lives at .../<root>/addon/ai_copilot/engine_launcher.py; the engine is at
    .../<root>/engine/bridge_server.py. We walk up until we find it.
    """
    here = Path(start or __file__).resolve()
    for base in here.parents:
        cand = base / "engine" / "bridge_server.py"
        if cand.is_file():
            return str(cand)
    return None


# --- the actual (non-test) spawn ---------------------------------------------

def _default_spawn(cmd, log_path: str):
    """
    Spawn the engine DETACHED and cross-platform, redirecting output to a file so
    no console window is required.

    - Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP -> no black window, the
      engine survives, and Ctrl+C in FreeCAD does not propagate to it.
    - POSIX (macOS/Linux): start_new_session=True -> own session, detached.
    """
    logf = open(log_path, "ab", buffering=0)
    kwargs = dict(stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        # 0x00000008 DETACHED_PROCESS, 0x00000200 CREATE_NEW_PROCESS_GROUP.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


# --- the launcher ------------------------------------------------------------

class EngineLauncher:
    """
    Owns the engine child process. `ensure_running` starts it (once); `stop`
    terminates it cleanly (no orphan process left behind when FreeCAD closes).

    All external effects are injected so this is fully unit-testable:
      python_finder() -> interpreter path or None
      script_finder() -> engine script path or None
      spawn(cmd, log_path) -> a process-like object (poll/terminate/wait/kill/pid)
    """

    def __init__(self,
                 python_finder: Optional[Callable[[], Optional[str]]] = None,
                 script_finder: Optional[Callable[[], Optional[str]]] = None,
                 spawn: Optional[Callable[[list, str], object]] = None,
                 logger: Optional[Callable[[str], None]] = None,
                 log_file=DEFAULT_LOG_FILE) -> None:
        self._find_python = python_finder or find_freecad_python
        self._find_script = script_finder or find_engine_script
        self._spawn = spawn or _default_spawn
        self._log = logger or (lambda msg: None)
        self._log_file = Path(log_file)
        self._proc = None

    @property
    def log_file(self) -> Path:
        return self._log_file

    def is_running(self) -> bool:
        """True if we launched an engine that is still alive."""
        proc = self._proc
        return proc is not None and proc.poll() is None

    def ensure_running(self, host: str, port: int, token: str) -> dict:
        """
        Start the engine as a CLIENT of the add-on server, unless one we launched
        is already alive (avoid the double start). Returns
        {ok, status, message}; status in
        {already-running, launched, no-python, no-script, spawn-failed}.
        """
        if self.is_running():
            return {"ok": True, "status": "already-running",
                    "message": f"engine already running (pid {self._proc.pid})."}

        python = self._find_python()
        if not python:
            return {"ok": False, "status": "no-python",
                    "message": ("could not find a Python interpreter to run the "
                                "engine (FreeCAD's bundled python was not located "
                                "and none is on PATH).")}
        script = self._find_script()
        if not script:
            return {"ok": False, "status": "no-script",
                    "message": "could not find engine/bridge_server.py next to the add-on."}

        cmd = [python, script,
               "--host", str(host), "--port", str(port), "--token", token]
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # best-effort: the log dir is a convenience, not required.
        try:
            self._proc = self._spawn(cmd, str(self._log_file))
        except Exception as exc:
            return {"ok": False, "status": "spawn-failed",
                    "message": f"failed to start the engine: {exc}"}
        pid = getattr(self._proc, "pid", "?")
        self._log(f"engine launched (pid {pid}); log -> {self._log_file}")
        return {"ok": True, "status": "launched",
                "message": f"engine started (pid {pid}); log at {self._log_file}."}

    def stop(self, timeout: float = 5.0) -> dict:
        """Terminate the engine cleanly (terminate -> wait -> kill). Idempotent."""
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return {"ok": True, "status": "not-running", "message": "engine not running."}
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except Exception:
                proc.kill()  # last resort if it ignores terminate.
            self._log("engine stopped.")
            return {"ok": True, "status": "stopped", "message": "engine stopped."}
        except Exception as exc:
            return {"ok": False, "status": "error", "message": f"stop failed: {exc}"}
