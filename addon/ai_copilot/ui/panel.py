# -*- coding: utf-8 -*-
"""
panel.py - Qt dock panel of the FreeCAD Agent add-on (Phase 1).

What it offers:
- a connection STATUS indicator for the engine (grey/yellow/green/red);
- Connect / Disconnect buttons (they manage the BridgeClient lifecycle);
- a STRUCTURED COMMAND composer: pick a command from the vocabulary (read from
  shared/commands.schema.json) and fill in its parameters;
- a "Run" button that sends the command to the engine (`command.request`) and
  shows the outcome;
- an on-screen LOG;
- PLACEHOLDERS (inactive, for Phase 2): privacy indicator (local/remote) and the
  "Free Python" banner (principle 5 - transparency).

THREADING (important):
- The panel lives on the Qt MAIN THREAD. BridgeClient callbacks may arrive from
  network threads: we re-route them onto the main thread via Qt Signals
  (sig_log/sig_state/sig_status/sig_result) -> no widget is ever touched from a
  foreign thread.
- "Run" makes a BLOCKING call to the engine: we run it on a worker thread, NEVER
  on the main thread (otherwise the returning `command.execute`, which needs the
  main thread, would deadlock). The result comes back to the UI via sig_result.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

# FreeCAD's PySide shim: maps to the Qt version in use (PySide2/PySide6).
from PySide import QtCore  # type: ignore
try:
    from PySide import QtWidgets  # type: ignore  (Qt5/Qt6)
except ImportError:  # pragma: no cover - very old FreeCAD (Qt4)
    from PySide import QtGui as QtWidgets  # type: ignore

from ..qt_invoker import MainThreadInvoker
from ..bridge_client import BridgeClient

# The vocabulary is shared neutral DATA: we read it to build the form.
# panel.py lives in addon/ai_copilot/ui/ -> the repo root is 3 levels up.
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "shared" / "commands.schema.json"

# The command the composer selects by default (handy: the simplest one).
_DEFAULT_COMMAND = "create_box"

# Status-indicator colours (state name -> (text, colour)).
_STATE_STYLE = {
    "disconnected": ("Disconnected", "#9e9e9e"),
    "connecting":   ("Connecting…", "#f4b400"),
    "connected":    ("Connected to engine", "#0f9d58"),
    "failed":       ("Connection failed", "#db4437"),
}


def _load_catalog() -> dict:
    """Return {command_name: spec} from the vocabulary. Empty if unreadable."""
    try:
        data = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    catalog = data.get("catalog", {})
    return {
        name: spec for name, spec in catalog.items()
        if not name.startswith("_") and isinstance(spec, dict) and "params" in spec
    }


class AgentPanel(QtWidgets.QDockWidget):
    """Main dock panel of the add-on."""

    # Signals to re-route updates onto the main thread.
    sig_log = QtCore.Signal(str)
    sig_state = QtCore.Signal(str)
    sig_status = QtCore.Signal(object)
    sig_result = QtCore.Signal(object)
    sig_python = QtCore.Signal(object)   # (code, reason) proposed free Python
    sig_nl_result = QtCore.Signal(object)  # outcome of a natural-language request

    def __init__(self, parent=None) -> None:
        super().__init__("FreeCAD Agent", parent)
        self.setObjectName("FreeCADAgentPanel")

        self._catalog = _load_catalog()
        self._invoker = MainThreadInvoker()   # created on the main thread
        self._client = None                   # BridgeClient, created on "Connect"
        self._param_widgets: dict = {}        # parameter name -> widget

        # Natural-language request progress/cancel state (ADR 0008).
        self._current_task_id = None          # set from the first agent.status
        self._busy_seconds = 0                # elapsed time of the running request
        self._slow_hint_shown = False         # show the "slow model" hint only once
        self._busy_timer = QtCore.QTimer(self)
        self._busy_timer.setInterval(1000)    # tick once per second while busy
        self._busy_timer.timeout.connect(self._on_busy_tick)

        self._build_ui()
        self._wire_signals()
        self._on_cmd_changed()                # build the first command's fields
        # Terminate the engine when FreeCAD quits, so no orphan process survives
        # (ADR 0015). aboutToQuit fires on application exit.
        try:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._shutdown_engine)
        except Exception:
            pass
        self._set_state("disconnected")
        self.log("Ready. Click «Connect»: the engine starts automatically "
                 "(no need to launch anything).")

    # -- UI construction -------------------------------------------------------

    def _build_ui(self) -> None:
        # The panel is split into two USER-RESIZABLE panes (QSplitter): the
        # controls on top (scrollable when the dock is short) and the log at
        # the bottom. Drag the splitter handle between them to give the log as
        # much room as you need; the dock itself resizes as usual in FreeCAD.
        controls = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(controls)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Status row + privacy indicator (placeholder) ---
        status_row = QtWidgets.QHBoxLayout()
        self._dot = QtWidgets.QLabel("●")
        self._dot.setStyleSheet("color:#9e9e9e; font-size:16px;")
        self._state_label = QtWidgets.QLabel("Disconnected")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._state_label, 1)
        # Privacy indicator placeholder (inactive in Phase 1).
        self._privacy_label = QtWidgets.QLabel("Privacy: local")
        self._privacy_label.setToolTip("Where the AI runs. 'local' = your machine "
                                       "(Ollama), nothing leaves your computer.")
        self._privacy_label.setStyleSheet("color:#0f9d58; font-weight:bold;")
        status_row.addWidget(self._privacy_label)
        layout.addLayout(status_row)

        # --- Connection buttons ---
        # "Connect" starts the engine FOR the user and connects (managed mode,
        # ADR 0015): no START_ENGINE.bat needed. "Stop engine" disconnects and
        # terminates the engine process (no orphan).
        conn_row = QtWidgets.QHBoxLayout()
        self._btn_connect = QtWidgets.QPushButton("Connect")
        self._btn_disconnect = QtWidgets.QPushButton("Stop engine")
        self._btn_disconnect.setEnabled(False)
        self._btn_connect.clicked.connect(self._do_connect)
        self._btn_disconnect.clicked.connect(self._do_disconnect)
        conn_row.addWidget(self._btn_connect)
        conn_row.addWidget(self._btn_disconnect)
        layout.addLayout(conn_row)

        # --- Engine status + tools (managed engine lifecycle, ADR 0015) ---
        engine_row = QtWidgets.QHBoxLayout()
        self._engine_label = QtWidgets.QLabel("Engine: stopped")
        self._engine_label.setStyleSheet("color:#9e9e9e; font-size:11px;")
        self._btn_log = QtWidgets.QPushButton("Show engine log")
        self._btn_log.setToolTip("Show the tail of the engine log file "
                                 "(~/.freecad-agent/engine.log).")
        self._btn_log.clicked.connect(self._show_engine_log)
        engine_row.addWidget(self._engine_label, 1)
        engine_row.addWidget(self._btn_log)
        layout.addLayout(engine_row)

        # Debug option: attach to an engine started by hand (START_ENGINE.bat)
        # instead of launching one. Off by default (the normal user never needs it).
        self._attach_check = QtWidgets.QCheckBox(
            "Debug: attach to a manually-started engine (START_ENGINE.bat)")
        self._attach_check.setChecked(False)
        self._attach_check.setStyleSheet("color:#666; font-size:11px;")
        self._attach_check.setToolTip(
            "Off (default): clicking Connect starts the engine for you.\n"
            "On: Connect attaches to an engine you started with START_ENGINE.bat "
            "(uses the discovery file). For debugging only.")
        layout.addWidget(self._attach_check)

        layout.addWidget(self._hline())

        # --- Natural-language request (the AI agent, Phase 2) ---
        layout.addWidget(QtWidgets.QLabel("<b>Ask in plain language</b>"))
        self._nl_input = QtWidgets.QPlainTextEdit()
        self._nl_input.setPlaceholderText(
            "e.g. \"create a 20x15x10 box and drill a 5 mm hole in the middle\"")
        self._nl_input.setMaximumHeight(60)
        layout.addWidget(self._nl_input)

        # Configurable AI timeout (Phase 4). DEFAULT IS UNLIMITED: the agent waits
        # as long as the local model needs. The user may OPT IN to a cap by ticking
        # the box, which enables the seconds field. Sent with each request.
        timeout_row = QtWidgets.QHBoxLayout()
        timeout_row.setContentsMargins(0, 0, 0, 0)
        self._limit_check = QtWidgets.QCheckBox("Limit AI wait time")
        self._limit_check.setChecked(False)       # unlimited by default
        self._limit_check.setStyleSheet("color:#666; font-size:11px;")
        self._limit_check.setToolTip(
            "Off (default): wait as long as the local model needs - stop a long "
            "request with Cancel. On: give up after the chosen number of seconds.")
        self._timeout_spin = QtWidgets.QSpinBox()
        self._timeout_spin.setRange(30, 1800)     # 30 s .. 30 min
        self._timeout_spin.setSingleStep(30)
        self._timeout_spin.setValue(120)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setEnabled(False)      # only active when the box is on
        self._limit_check.toggled.connect(self._timeout_spin.setEnabled)
        timeout_row.addWidget(self._limit_check)
        timeout_row.addWidget(self._timeout_spin)
        timeout_row.addStretch(1)
        layout.addLayout(timeout_row)

        self._btn_ask = QtWidgets.QPushButton("Ask the agent")
        self._btn_ask.setEnabled(False)
        self._btn_ask.clicked.connect(self._do_ask)
        layout.addWidget(self._btn_ask)

        # --- Busy row for a running NL request: progress + elapsed + Cancel ---
        # Hidden until a request is in flight. The progress bar is indeterminate
        # (range 0,0 = animated "busy") because we cannot know how long the local
        # model will take. Cancel is enabled once we know the task id (ADR 0008).
        self._busy_row = QtWidgets.QWidget()
        busy_layout = QtWidgets.QHBoxLayout(self._busy_row)
        busy_layout.setContentsMargins(0, 0, 0, 0)
        self._progress = QtWidgets.QProgressBar()
        self._progress.setRange(0, 0)         # indeterminate / busy animation
        self._progress.setTextVisible(False)
        self._elapsed_label = QtWidgets.QLabel("working… 0s")
        self._elapsed_label.setStyleSheet("color:#666; font-size:11px;")
        self._btn_cancel = QtWidgets.QPushButton("Cancel")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._do_cancel)
        busy_layout.addWidget(self._progress, 1)
        busy_layout.addWidget(self._elapsed_label)
        busy_layout.addWidget(self._btn_cancel)
        self._busy_row.setVisible(False)
        layout.addWidget(self._busy_row)

        # Reassure the user about graceful degradation (Phase 4): natural language
        # needs the local AI (Ollama), but everything below keeps working without
        # it, and natural language comes back on its own once Ollama is up.
        nl_hint = QtWidgets.QLabel(
            "Natural language uses the local AI (Ollama). If it is off, the engine "
            "tries to start it for you; meanwhile the structured commands below "
            "work without it, and natural language resumes automatically once "
            "Ollama is running."
        )
        nl_hint.setWordWrap(True)
        nl_hint.setStyleSheet("color:#666; font-size:11px;")
        layout.addWidget(nl_hint)

        layout.addWidget(self._hline())

        # --- Command composer (expert mode: structured command) ---
        layout.addWidget(QtWidgets.QLabel("<b>Structured command (expert mode)</b>"))
        self._cmd_combo = QtWidgets.QComboBox()
        for name in sorted(self._catalog.keys()):
            summary = self._catalog[name].get("summary", "")
            self._cmd_combo.addItem(name, name)
            idx = self._cmd_combo.count() - 1
            self._cmd_combo.setItemData(idx, summary, QtCore.Qt.ToolTipRole)
        if self._cmd_combo.count() == 0:
            self._cmd_combo.addItem("(vocabulary not found)")
            self._cmd_combo.setEnabled(False)
        else:
            # Default to the simplest command if available.
            default_idx = self._cmd_combo.findData(_DEFAULT_COMMAND)
            if default_idx >= 0:
                self._cmd_combo.setCurrentIndex(default_idx)
        self._cmd_combo.currentIndexChanged.connect(self._on_cmd_changed)
        layout.addWidget(self._cmd_combo)

        self._summary_label = QtWidgets.QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("color:#666;")
        layout.addWidget(self._summary_label)

        # Container for the parameter fields (rebuilt when the command changes).
        self._form_container = QtWidgets.QWidget()
        self._form_layout = QtWidgets.QFormLayout(self._form_container)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._form_container)

        self._btn_run = QtWidgets.QPushButton("Run")
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._do_run)
        layout.addWidget(self._btn_run)

        layout.addWidget(self._hline())

        # --- "Free Python" transparency banner (principle 5) ---
        # Shows the exact Python the agent runs when the vocabulary is not enough.
        self._py_banner = QtWidgets.QLabel(
            "⚠  «Free Python» channel: idle. When the agent runs free Python "
            "(because no structured command fits), the exact code appears here "
            "before it executes — inside an undoable transaction (Ctrl+Z)."
        )
        self._py_banner.setWordWrap(True)
        self._py_banner.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._py_banner.setStyleSheet(
            "background:#fff8e1; border:1px solid #ffe082; border-radius:4px;"
            " padding:6px; color:#7a5c00;"
        )
        layout.addWidget(self._py_banner)

        layout.addStretch(1)

        # --- Log (its OWN splitter pane, resizable by dragging the handle) ---
        log_pane = QtWidgets.QWidget()
        log_layout = QtWidgets.QVBoxLayout(log_pane)
        log_layout.setContentsMargins(8, 4, 8, 8)
        log_layout.setSpacing(4)
        log_layout.addWidget(QtWidgets.QLabel("<b>Log</b>"))
        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)   # keep a long history
        self._log_view.setMinimumHeight(60)
        log_layout.addWidget(self._log_view, 1)

        # Controls scroll when the dock is short, so nothing is ever clipped.
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(controls)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(scroll)
        splitter.addWidget(log_pane)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setChildrenCollapsible(False)

        self.setWidget(splitter)

    def _hline(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    def _wire_signals(self) -> None:
        self.sig_log.connect(self._append_log)
        self.sig_state.connect(self._apply_state)
        self.sig_status.connect(self._apply_status)
        self.sig_result.connect(self._apply_result)
        self.sig_python.connect(self._apply_python)
        self.sig_nl_result.connect(self._apply_nl_result)

    # -- composer: dynamic fields for the selected command ---------------------

    def _on_cmd_changed(self) -> None:
        # Clear the previous fields.
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._param_widgets = {}

        cmd = self._cmd_combo.currentData()
        spec = self._catalog.get(cmd) if cmd else None
        if not spec:
            self._summary_label.setText("")
            return
        self._summary_label.setText(spec.get("summary", ""))

        pschema = spec.get("params", {})
        required = set(pschema.get("required", []))
        properties = pschema.get("properties", {})
        for name, pspec in properties.items():
            label = name + (" *" if name in required else "")
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText(self._hint_for(pspec))
            self._param_widgets[name] = (field, pspec, name in required)
            self._form_layout.addRow(label, field)

    def _hint_for(self, pspec: dict) -> str:
        jtype = pspec.get("type", "")
        if jtype == "array":
            return pspec.get("description", "e.g. 0,0,0")
        if jtype in ("number", "integer"):
            mn = pspec.get("minimum")
            return f"number{f' (>= {mn})' if mn is not None else ''}, e.g. 10"
        if jtype == "boolean":
            return "true / false"
        return pspec.get("description", jtype)

    # -- actions: connection ---------------------------------------------------

    def _do_connect(self) -> None:
        if self._client is not None and self._client.is_connected():
            self.log("Already connected.")
            return
        attach = self._attach_check.isChecked()
        if attach:
            self.log("Attaching to a manually-started engine (debug mode)…")
        else:
            self.log("Starting the engine and connecting… (a few seconds)")
        self._client = BridgeClient(
            invoker=self._invoker,
            logger=lambda m: self.sig_log.emit(str(m)),
            on_state=lambda s: self.sig_state.emit(str(s)),
            on_status=lambda p: self.sig_status.emit(p),
            on_python=lambda code, reason: self.sig_python.emit((code, reason)),
        )
        # Global references: keep the GC from destroying client/invoker.
        try:
            import FreeCAD
            FreeCAD.__freecad_agent_client__ = self._client
            FreeCAD.__freecad_agent_invoker__ = self._invoker
        except Exception:
            pass
        # managed=True (default): the add-on launches the engine itself.
        self._client.start(managed=not attach)
        self._btn_connect.setEnabled(False)
        self._btn_disconnect.setEnabled(True)

    def _do_disconnect(self) -> None:
        """Disconnect and, in managed mode, terminate the engine (no orphan)."""
        if self._client is not None:
            self.log("Stopping the engine…")
            self._client.stop()
        self._btn_disconnect.setEnabled(False)
        self._btn_connect.setEnabled(True)

    def _shutdown_engine(self) -> None:
        """Best-effort clean stop of the engine on FreeCAD exit (no orphan)."""
        try:
            if self._client is not None:
                self._client.stop()
        except Exception:
            pass

    def _show_engine_log(self) -> None:
        """Show the tail of the engine log file in the panel log (managed mode)."""
        try:
            from ..engine_launcher import DEFAULT_LOG_FILE
            path = DEFAULT_LOG_FILE
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self._append_log(f"Could not read the engine log: {exc}")
            return
        tail = "\n".join(text.splitlines()[-100:]) or "(engine log is empty)"
        self._append_log("---- engine log (last lines) ----")
        self._append_log(tail)
        self._append_log("---- end of engine log ----")

    # -- actions: run a command ------------------------------------------------

    def _do_run(self) -> None:
        if self._client is None or not self._client.is_connected():
            self.log("Not connected: click «Connect» first.")
            return
        invocation, parse_error = self._build_invocation()
        if parse_error:
            self.log(f"Invalid input: {parse_error}")
            return

        self._btn_run.setEnabled(False)
        self.log(f"Sending command: {json.dumps(invocation, ensure_ascii=False)}")

        def worker():
            try:
                result = self._client.send_command_request(invocation)
            except Exception as exc:  # network/timeout/not connected
                result = {"ok": False, "transaction_id": "", "error": f"{type(exc).__name__}: {exc}"}
            self.sig_result.emit(result)

        threading.Thread(target=worker, name="cmd-request", daemon=True).start()

    # -- actions: natural-language request (the AI agent) ----------------------

    def _do_ask(self) -> None:
        if self._client is None or not self._client.is_connected():
            self.log("Not connected: click «Connect» first.")
            return
        text = self._nl_input.toPlainText().strip()
        if not text:
            self.log("Type a request first.")
            return
        self._btn_ask.setEnabled(False)
        self._set_busy(True)
        # 0 = unlimited (box unticked); otherwise the chosen seconds cap.
        ai_timeout = self._timeout_spin.value() if self._limit_check.isChecked() else 0
        self.log(f"You: {text}")

        def worker():
            try:
                result = self._client.send_user_prompt(text, ai_timeout=ai_timeout)
            except Exception as exc:  # network/timeout/not connected
                result = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
            self.sig_nl_result.emit(result)

        threading.Thread(target=worker, name="user-prompt", daemon=True).start()

    # -- progress / cancel of a natural-language request (ADR 0008) ------------

    def _set_busy(self, busy: bool) -> None:
        """Show/hide the progress row and start/stop the elapsed timer."""
        if busy:
            self._current_task_id = None      # learned from the first agent.status
            self._busy_seconds = 0
            self._slow_hint_shown = False
            self._elapsed_label.setText("working… 0s")
            self._btn_cancel.setEnabled(False)  # enabled once we know the task id
            self._btn_cancel.setText("Cancel")
            self._busy_row.setVisible(True)
            self._busy_timer.start()
        else:
            self._busy_timer.stop()
            self._busy_row.setVisible(False)
            self._btn_cancel.setEnabled(False)
            self._current_task_id = None

    def _on_busy_tick(self) -> None:
        """Once per second while a request runs: update elapsed time + slow hint."""
        self._busy_seconds += 1
        self._elapsed_label.setText(f"working… {self._busy_seconds}s")
        # After a while, reassure the user that a slow local model is normal.
        if self._busy_seconds == 15 and not self._slow_hint_shown:
            self._slow_hint_shown = True
            self._append_log(
                "  · still working — the local model can be slow, especially on "
                "the first request. You can wait or press Cancel.")

    def _do_cancel(self) -> None:
        """Send user.cancel for the running task (from a worker thread)."""
        task_id = self._current_task_id
        if self._client is None or not self._client.is_connected() or not task_id:
            return
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setText("Cancelling…")
        self._append_log("  · cancel requested…")

        def worker(tid=task_id):
            try:
                self._client.send_user_cancel(tid)
            except Exception as exc:  # best-effort: the result handler still runs
                self.sig_log.emit(f"  · cancel call failed: {type(exc).__name__}: {exc}")

        threading.Thread(target=worker, name="user-cancel", daemon=True).start()

    def _build_invocation(self):
        """Build {cmd, params} from the fields. Returns (invocation, error|None)."""
        cmd = self._cmd_combo.currentData()
        if not cmd:
            return None, "no command selected"
        params = {}
        for name, (field, pspec, is_required) in self._param_widgets.items():
            text = field.text().strip()
            if not text:
                if is_required:
                    return None, f"required parameter «{name}» is empty"
                continue
            value, err = self._parse_value(text, pspec)
            if err:
                return None, f"parameter «{name}»: {err}"
            params[name] = value
        return {"cmd": cmd, "params": params}, None

    def _parse_value(self, text: str, pspec: dict):
        jtype = pspec.get("type")
        try:
            if jtype in ("number", "integer"):
                return (float(text) if jtype == "number" else int(text)), None
            if jtype == "boolean":
                return text.lower() in ("true", "1", "yes"), None
            if jtype == "array":
                parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
                return [float(p) for p in parts], None
            return text, None  # string
        except ValueError:
            return None, f"value not parsable as {jtype}"

    # -- main-thread slots (they update the widgets) ---------------------------

    def _append_log(self, msg: str) -> None:
        self._log_view.appendPlainText(msg)

    def log(self, msg: str) -> None:
        # Safe from any thread (goes through the Signal).
        self.sig_log.emit(str(msg))

    def _set_state(self, state: str) -> None:
        self.sig_state.emit(state)

    def _apply_state(self, state: str) -> None:
        text, color = _STATE_STYLE.get(state, (state, "#9e9e9e"))
        self._dot.setStyleSheet(f"color:{color}; font-size:16px;")
        self._state_label.setText(text)
        connected = (state == "connected")
        self._btn_run.setEnabled(connected)
        self._btn_ask.setEnabled(connected)
        self._btn_connect.setEnabled(state in ("disconnected", "failed"))
        self._btn_disconnect.setEnabled(state in ("connected", "connecting"))
        # Engine status light. In managed mode a live connection means our engine
        # process is running; when disconnected/failed the engine is stopped.
        running = self._client is not None and self._client.engine_running()
        if connected or running:
            self._engine_label.setText("Engine: running")
            self._engine_label.setStyleSheet("color:#0f9d58; font-size:11px; font-weight:bold;")
        elif state == "connecting":
            self._engine_label.setText("Engine: starting…")
            self._engine_label.setStyleSheet("color:#f4b400; font-size:11px;")
        else:
            self._engine_label.setText("Engine: stopped")
            self._engine_label.setStyleSheet("color:#9e9e9e; font-size:11px;")

    def _apply_status(self, params) -> None:
        if isinstance(params, dict):
            self._append_log(f"  · {params.get('phase')}: {params.get('message')}")
            # Learn the running task id from the first status, so Cancel can target
            # it (ADR 0008). Only while a request is in flight (the busy row shows).
            task_id = params.get("task_id")
            if task_id and self._busy_row.isVisible():
                self._current_task_id = task_id
                if params.get("phase") != "cancelling":
                    self._btn_cancel.setEnabled(True)
            privacy = params.get("privacy")
            if privacy == "local":
                self._privacy_label.setText("Privacy: local")
                self._privacy_label.setStyleSheet("color:#0f9d58; font-weight:bold;")
            elif privacy == "remote":
                self._privacy_label.setText("Privacy: REMOTE")
                self._privacy_label.setStyleSheet("color:#db4437; font-weight:bold;")

    def _apply_result(self, result) -> None:
        self._btn_run.setEnabled(self._client is not None and self._client.is_connected())
        if not isinstance(result, dict):
            self._append_log(f"Unexpected result: {result}")
            return
        if result.get("ok"):
            self._append_log(
                f"✓ DONE. transaction={result.get('transaction_id')} "
                f"objects={result.get('created_ids')}. Press Ctrl+Z to undo."
            )
        else:
            self._append_log(f"✗ REJECTED/FAILED: {result.get('error')}")

    def _apply_python(self, payload) -> None:
        """Show the exact free Python the agent is about to run (transparency)."""
        code, reason = (payload if isinstance(payload, (list, tuple)) else (payload, ""))
        self._py_banner.setStyleSheet(
            "background:#fde7e9; border:1px solid #f3a3ab; border-radius:4px;"
            " padding:6px; color:#7a1620; font-family:monospace;"
        )
        header = "⚠  The agent is running FREE PYTHON"
        if reason:
            header += f" — {reason}"
        self._py_banner.setText(f"{header}\n\n{code}\n\n(inside an undoable "
                                f"transaction — Ctrl+Z reverts it)")

    def _apply_nl_result(self, result) -> None:
        """Outcome of a natural-language request (user.prompt)."""
        self._set_busy(False)
        self._btn_ask.setEnabled(self._client is not None and self._client.is_connected())
        if not isinstance(result, dict):
            self._append_log(f"Unexpected result: {result}")
            return
        if result.get("cancelled"):
            self._append_log(f"⏹ Cancelled. {result.get('summary', '')} "
                             "Press Ctrl+Z to undo any applied step.")
            return
        if not result.get("accepted", False):
            self._append_log(f"✗ Agent could not run it: {result.get('error')}")
            return
        if result.get("clarification"):
            self._append_log(f"🛈 Agent needs more info: {result.get('clarification')}")
            return
        summary = result.get("summary", "")
        results = result.get("results", []) or []
        ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
        self._append_log(f"✓ Agent done: {summary or f'{ok}/{len(results)} actions'}. "
                         f"Press Ctrl+Z to undo (once per action).")


# --- Convenience API for InitGui / macro -------------------------------------

_PANEL_REF = None  # keeps the instance alive


def show_panel():
    """
    Create (if needed) and show the panel docked to FreeCAD's main window.
    Returns the panel instance. Idempotent.
    """
    global _PANEL_REF
    import FreeCADGui

    mw = FreeCADGui.getMainWindow()
    if _PANEL_REF is None:
        _PANEL_REF = AgentPanel(mw)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _PANEL_REF)
    _PANEL_REF.show()
    _PANEL_REF.raise_()
    return _PANEL_REF
