"""
engine/ollama_launch.py - transparent auto-start of the local AI (Ollama).

Goal (Phase 4, ADR 0007): Marco wants to start working in FreeCAD without caring
whether Ollama is already running. If the engine finds Ollama unreachable but the
`ollama` command is installed, it launches `ollama serve` itself, waits a few
seconds, and re-checks. If Ollama is not installed, it does nothing and the engine
keeps working in degraded mode (structured commands always work; only natural
language needs Ollama - principle 9: adapt, don't exclude).

WHY this lives in the engine (Python) instead of START_ENGINE.bat:
  - Cross-platform by construction (principle 9 + world open-source release): the
    same logic serves Windows, macOS and Linux launchers. START_ENGINE.bat simply
    runs the engine, so "the .bat ensures Ollama" is satisfied for free, and a
    future START_ENGINE.sh inherits it without duplicated shell logic.
  - Testable headless: ensure_running() takes injectable `client` and `spawn`
    callables, so the suite verifies every branch without a real Ollama or a real
    process launch.

STILL pure standard library (ADR 0004): only `os`, `shutil`, `subprocess`, `time`.
No third-party packages, no virtual environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, Optional

# Status strings returned by ensure_running(). Stable identifiers so callers can
# branch on them and tests can assert them.
STATUS_ALREADY_RUNNING = "already_running"   # Ollama answered on the first probe
STATUS_STARTED = "started"                   # we launched it and it became reachable
STATUS_NOT_INSTALLED = "not_installed"       # the `ollama` command was not found
STATUS_LAUNCH_FAILED = "launch_failed"       # spawning the process raised
STATUS_TIMEOUT = "timeout"                   # launched, but not reachable in time
STATUS_DISABLED = "disabled"                 # auto-start switched off via env var

# Environment switch so automated tests (and power users) can disable auto-start.
ENV_DISABLE = "FREECAD_AGENT_NO_AUTOSTART"

# Default time budget to wait for the freshly-launched server to answer. Starting
# the HTTP server is quick; the (slow) model load happens later, on first inference.
DEFAULT_WAIT_SECONDS = 20.0
DEFAULT_POLL_INTERVAL = 1.0


def _default_spawn(exe: str) -> None:
    """
    Launch `ollama serve` as a detached background process that OUTLIVES the
    engine window (so the model server stays up for the rest of the FreeCAD
    session). No console window, output discarded.
    """
    kwargs: Dict[str, Any] = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW:
        # fully detached, no flashing console, survives our window closing.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = (
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        )
    else:
        # New session so the child is not killed when the engine exits.
        kwargs["start_new_session"] = True
    subprocess.Popen([exe, "serve"], **kwargs)  # noqa: S603 - fixed argv, no shell


def ollama_installed() -> Optional[str]:
    """Return the full path to the `ollama` executable, or None if not installed."""
    return shutil.which("ollama")


def ensure_running(
    client: Any,
    log: Optional[Callable[[str], None]] = None,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    spawn: Callable[[str], None] = _default_spawn,
    which: Callable[[], Optional[str]] = ollama_installed,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """
    Make sure the local AI server is reachable, launching it if needed.

    Args:
      client:       anything with a no-raise `is_available() -> bool` method
                    (our OllamaClient). Used as the reachability probe.
      log:          optional one-arg logger for human-readable progress.
      wait_seconds: how long to wait for a freshly-launched server to answer.
      poll_interval, spawn, which, sleep: injection points for tests.

    Returns a dict: {"status": <STATUS_*>, "launched": bool, "message": str}.
    Never raises: a failure to auto-start just leaves the engine in degraded mode.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    # Power users / tests can switch auto-start off entirely.
    if os.environ.get(ENV_DISABLE) == "1":
        return {"status": STATUS_DISABLED, "launched": False,
                "message": "auto-start disabled via " + ENV_DISABLE}

    # 1) Already up? Nothing to do (the common case after the first launch).
    if client.is_available():
        return {"status": STATUS_ALREADY_RUNNING, "launched": False,
                "message": "local AI (Ollama) already running."}

    # 2) Is Ollama even installed? If not, degrade gracefully (principle 9).
    exe = which()
    if not exe:
        return {"status": STATUS_NOT_INSTALLED, "launched": False,
                "message": ("Ollama is not installed, so natural language is off; "
                            "structured commands still work. Install it from "
                            "https://ollama.com/download to enable natural language.")}

    # 3) Launch it ourselves.
    _log(f"local AI (Ollama) not reachable - starting it for you ({exe})...")
    try:
        spawn(exe)
    except Exception as exc:  # pragma: no cover - OS-specific spawn failure
        return {"status": STATUS_LAUNCH_FAILED, "launched": False,
                "message": f"could not launch Ollama automatically: {exc}. "
                           "Start it manually, or just retry - natural language "
                           "resumes by itself once Ollama is up."}

    # 4) Poll until it answers or we run out of time.
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        sleep(poll_interval)
        if client.is_available():
            _log("local AI (Ollama) is up.")
            return {"status": STATUS_STARTED, "launched": True,
                    "message": "started the local AI (Ollama) automatically."}

    return {"status": STATUS_TIMEOUT, "launched": True,
            "message": (f"launched Ollama but it did not answer within "
                        f"{wait_seconds:.0f}s. It may still be warming up; natural "
                        "language resumes by itself once it is ready - no restart "
                        "needed.")}
