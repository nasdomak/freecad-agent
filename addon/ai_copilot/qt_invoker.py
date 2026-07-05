"""
qt_invoker.py - marshalling calls onto FreeCAD's Qt main thread.

THE MOST DELICATE POINT OF PHASE 1a (RISK #2).
FreeCAD and Qt APIs are NOT thread-safe: they must be touched ONLY from the GUI
main thread. But incoming bridge requests are handled on a worker thread. When a
request arrives (e.g. command.execute) its handler will touch FreeCAD: we must
"hop" onto the main thread, run there, and bring the result back.

Mechanism (robust and Qt-version independent):
- a QObject living on the main thread exposes a Signal;
- emitting the Signal from another thread, with the automatic connection type,
  queues the slot on the main thread's event loop (QueuedConnection);
- the calling thread BLOCKS on a threading.Event until the slot has finished.

This confines the Qt complexity here: the bridge core (shared/bridge) stays
neutral and execution is serialized safely.

We use FreeCAD's `PySide` shim, which maps to the Qt version actually in use
(PySide2 or PySide6), so the code is version-agnostic.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

# FreeCAD's PySide shim: imported here so the module is importable only inside
# FreeCAD (outside it isn't needed: the headless tests use the inline dispatcher).
from PySide import QtCore  # type: ignore


class _Task:
    __slots__ = ("fn", "params", "event", "result", "error")

    def __init__(self, fn: Callable[[dict], Any], params: dict) -> None:
        self.fn = fn
        self.params = params
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class MainThreadInvoker(QtCore.QObject):
    """
    Runs callables on the Qt main thread. MUST be instantiated on the main thread
    (e.g. inside a FreeCAD macro) so its slots run there.
    """

    _run_signal = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        # AutoConnection: if emitted from another thread -> QueuedConnection.
        self._run_signal.connect(self._run_on_main)

    @QtCore.Slot(object)
    def _run_on_main(self, task: _Task) -> None:
        try:
            task.result = task.fn(task.params)
        except BaseException as exc:  # catch everything: re-raised on the caller side
            task.error = exc
        finally:
            task.event.set()

    def invoke(self, fn: Callable[[dict], Any], params: dict, timeout: float = 60.0) -> Any:
        """
        Run fn(params) on the main thread and return its result (blocking).
        Meant to be used as the JsonRpcPeer `dispatcher`:
            peer = JsonRpcPeer(conn, dispatcher=invoker.invoke)
        """
        task = _Task(fn, params)
        self._run_signal.emit(task)  # -> queued on the main thread
        if not task.event.wait(timeout):
            raise TimeoutError(f"main-thread execution exceeded {timeout}s (UI blocked?)")
        if task.error is not None:
            raise task.error
        return task.result
