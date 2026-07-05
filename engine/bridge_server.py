#!/usr/bin/env python3
"""
engine/bridge_server.py - PERSISTENT ENGINE of Phase 1 (still WITHOUT AI).

Difference from Phase 1a: it no longer runs a one-shot demo and no longer exits.
It keeps listening (accept loop), handles multiple commands per session, survives
add-on disconnections (it goes back to waiting), and shuts down cleanly (Ctrl+C)
removing the discovery file.

TWO RUN MODES (ADR 0015 "engine lifecycle" + topology flip):
  - CLIENT mode (PRODUCTION, default when the add-on launches us): if we receive
    --host/--port/--token (or the FREECAD_AGENT_HOST/PORT/TOKEN env vars), the
    ADD-ON is the TCP server; we connect to it and present the token via
    session.hello (the add-on validates it). No discovery file. This is the
    topology ADR 0002 foresaw for production; the bridge core is symmetric
    (ADR 0001), so only the handshake roles swap - all the operational handlers
    keep their direction.
  - SERVER standalone mode (DEBUG, when launched with no connection args, e.g.
    from START_ENGINE.bat): we are the TCP server on 127.0.0.1 with an ephemeral
    port + token and we write the discovery file so an add-on in "attach (debug)"
    mode can find us. This is the historical prototype behaviour, kept for our
    own debugging.

Role (see ADR 0002 + ADR 0003):
  - As the "fake brain" it receives an ALREADY-structured command from
    the add-on panel via `command.request`, VALIDATES it against
    commands.schema.json (fake_brain) and, if valid, forwards it to the add-on as
    `command.execute` (exercising both directions of the bridge). It emits
    `agent.status`.
  - `user.prompt` (natural language) is NOT implemented in Phase 1: a polite
    refusal (the AI arrives in Phase 2).

Threading (RISK #2): the peer runs incoming handlers on an internal pool (see
shared/bridge/jsonrpc.py), so the `command.request` handler can call
`command.execute` back on the add-on without blocking the read loop (ADR 0003).

Environment variables (for automated tests):
  FREECAD_AGENT_ACCEPT_TIMEOUT  seconds to wait for EACH connection (default: none = infinite)
  FREECAD_AGENT_ONESHOT         if "1", serve a SINGLE connection then exit (for tests)

Start (Windows): double-click START_ENGINE.bat, or:
    cd freecad-agent\\engine
    python bridge_server.py
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

# --- Import the neutral bridge library (shared/bridge) ------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from bridge import (  # noqa: E402
    FramedConnection,
    JsonRpcPeer,
    JsonRpcError,
    ConnectionClosed,
    ErrorCode,
    discovery,
    PROTOCOL_VERSION,
)
import fake_brain  # noqa: E402  (engine/fake_brain.py, same folder)
from brain import Brain, PlanError  # noqa: E402  (the real Phase 2 planning brain)
from ollama_client import OllamaUnavailable  # noqa: E402

ENGINE_VERSION = "0.12.0-phase6"

# Phase 3 "geometric RAG": before planning we fetch perception.detail for the
# existing objects so the model sees real Edge*/Face* references. We only do this
# for SMALL documents, to stay concise for small local models (principle 9). For
# bigger documents we fall back to the cheap overview only.
MAX_DETAIL_OBJECTS = 8
# ADR 0016: commands whose new feature CONSUMES the object(s) these params
# reference (Part::Cut / boolean / dress-up features swallow their base, which
# survives only as a hidden child). Within one plan, a later step that still
# names the OLD id really means the NEW result: we redirect it. mirror/array
# keep their source visible and move/rotate keep the same id, so they are not
# listed. (extrude consumes its sketch profile, ADR 0009/0010.)
CONSUMING_PARAMS = {
    "drill_hole": ("target",),
    "boolean": ("a", "b"),
    "fillet": ("target",),
    "chamfer": ("target",),
    "extrude": ("target",),
}
# Bounded self-correction (principle 8: no infinite loops).
MAX_REPAIR_ATTEMPTS = 2


def log(msg: str) -> None:
    print(f"[engine] {msg}", flush=True)


class Session:
    """
    A session = one add-on connection. It owns the peer and the handlers.
    The "fake brain" lives here: it validates commands and forwards them to the
    add-on.
    """

    def __init__(self, peer: JsonRpcPeer, token: str, catalog: fake_brain.Catalog,
                 brain: "Brain | None" = None) -> None:
        self.peer = peer
        self.token = token
        self.catalog = catalog
        # The real planning brain (Phase 2). Injectable so headless tests can pass
        # a fake one; by default it talks to a local Ollama (ADR 0004).
        self.brain = brain or Brain(catalog)
        self.authenticated = threading.Event()
        self._task_counter = 0
        # Phase 4 (ADR 0007): try a "lazy" Ollama auto-start at most once per
        # session, the first time natural language is used while it is down.
        self._ollama_autostart_tried = False
        # Phase 4 (ADR 0008): cooperative cancellation. user.cancel(task_id) just
        # records the id here; the running on_user_prompt loop checks it at safe
        # checkpoints and stops without executing any further FreeCAD action. We
        # cannot abort an in-flight model inference, so cancel takes effect at the
        # NEXT checkpoint (correctness over speed - principle 8).
        self._cancel_lock = threading.Lock()
        self._cancelled_tasks: "set[str]" = set()

    # -- handshake -------------------------------------------------------------

    def on_hello(self, params: dict) -> dict:
        """The add-on (client) presents the token; we validate it (see ADR 0002)."""
        client_token = params.get("token", "")
        client_proto = params.get("protocol_version", "?")
        if client_token != self.token:
            log("handshake REJECTED: wrong token")
            raise JsonRpcError(ErrorCode.AUTH_FAILED, "invalid token")
        if client_proto != PROTOCOL_VERSION:
            log(f"WARNING: protocol_version addon={client_proto} engine={PROTOCOL_VERSION}")
        self.authenticated.set()
        version, names = fake_brain.summarize(self.catalog)
        log(f"handshake OK (addon proto={client_proto}). Vocabulary v{version}: {', '.join(names)}")
        return {
            "ok": True,
            "engine_version": ENGINE_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "vocabulary_version": version,
            "commands": names,
        }

    # -- main Phase 1 channel: structured command from the panel ---------------

    def on_command_request(self, params: dict) -> dict:
        """
        Receives a commandInvocation {cmd, params}. Validates it and, if valid,
        forwards it to the add-on as `command.execute`. Returns a commandResult.

        Runs on a pool thread (the peer's internal pool), so it can make the
        nested `command.execute` call without deadlocking.
        """
        self._task_counter += 1
        task_id = f"task-{self._task_counter:04d}"
        cmd = params.get("cmd") if isinstance(params, dict) else None
        log(f"[{task_id}] command.request: {cmd} {params.get('params') if isinstance(params, dict) else ''}")

        # 1) VALIDATION (the fake brain's job)
        self._notify(task_id, "validation", f"checking '{cmd}' against the vocabulary")
        errors = fake_brain.validate_invocation(params, self.catalog)
        if fake_brain.is_blocking(errors):
            msg = "; ".join(errors)
            log(f"[{task_id}] REJECTED (validation): {msg}")
            self._notify(task_id, "rejected", msg)
            # Graceful refusal (principle 7): commandResult ok=false, no exception.
            return {"ok": False, "transaction_id": "", "error": f"validation failed: {msg}"}
        if errors:  # non-blocking warnings only
            log(f"[{task_id}] warnings: {'; '.join(errors)}")

        # 2) EXECUTION: forward to the add-on (engine -> addon)
        self._notify(task_id, "execution", f"running '{cmd}' on FreeCAD", privacy="local")
        try:
            result = self.peer.call("command.execute", params, timeout=60)
        except (JsonRpcError, TimeoutError) as exc:
            log(f"[{task_id}] error during command.execute: {exc}")
            self._notify(task_id, "error", str(exc))
            return {"ok": False, "transaction_id": "", "error": f"execution failed: {exc}"}

        ok = bool(result.get("ok"))
        if ok:
            log(f"[{task_id}] OK: tx={result.get('transaction_id')} objects={result.get('created_ids')}")
            self._notify(task_id, "completed",
                         f"created: {result.get('created_ids')} (Ctrl+Z to undo)")
        else:
            log(f"[{task_id}] execution failed on the add-on side: {result.get('error')}")
            self._notify(task_id, "error", str(result.get("error")))
        return result

    # -- natural-language channel: the real AI agent (Phase 2) -----------------

    def on_user_prompt(self, params: dict) -> dict:
        """
        The user typed a natural-language request. Orchestrate the full loop:
          perceive (ask the add-on for the document overview)
            -> think (ask the local model for a plan)
            -> execute each action on the add-on (command.execute / python.execute)
            -> self-correct once on failure.
        Emits agent.status notifications throughout. Runs on a pool thread, so the
        nested calls back to the add-on do not deadlock (ADR 0003).
        Degrades gracefully if the local model is unavailable (principle 9).
        """
        self._task_counter += 1
        task_id = f"nl-{self._task_counter:04d}"
        text = (params.get("text") or "").strip() if isinstance(params, dict) else ""
        if not text:
            return {"accepted": False, "task_id": task_id, "error": "empty request"}
        log(f"[{task_id}] user.prompt: {text!r}")

        # Optional per-request AI timeout from the panel (Phase 4). Default is
        # UNLIMITED; the user may opt into a cap. We apply whatever the panel sends
        # (including 0 = unlimited) so toggling the limit off resets a previous cap.
        if isinstance(params, dict) and "ai_timeout" in params \
                and hasattr(self.brain, "set_timeout"):
            ai_timeout = params.get("ai_timeout")
            if self.brain.set_timeout(ai_timeout):
                shown = "unlimited" if not ai_timeout else f"{ai_timeout}s"
                log(f"[{task_id}] AI per-call timeout set to {shown} (from panel)")

        # 0) Is the local model reachable? If not, try a lazy auto-start ONCE
        #    (Phase 4, ADR 0007), then re-check; if still down, refuse politely
        #    (principle 9). This covers "Ollama was killed after the engine
        #    started": the user does not have to restart the engine.
        avail = self.brain.availability()
        if not avail.get("available") and not self._ollama_autostart_tried \
                and hasattr(self.brain, "ensure_server"):
            self._ollama_autostart_tried = True
            self._notify(task_id, "starting-ai",
                         "local AI was off - trying to start it for you...",
                         privacy="local")
            outcome = self.brain.ensure_server(log=lambda m: log(f"[{task_id}] {m}"))
            log(f"[{task_id}] auto-start: {outcome.get('status')} - {outcome.get('message')}")
            avail = self.brain.availability()  # re-probe after the attempt
        if not avail.get("available"):
            reason = avail.get("reason", "local AI model not available")
            # Make the limitation actionable: structured commands always work, and
            # natural language resumes by itself once Ollama is up (no restart).
            friendly = (f"{reason} | Natural language needs the local AI (Ollama). "
                        "Meanwhile the structured commands (expert mode) work "
                        "normally; natural language resumes automatically as soon "
                        "as Ollama is running - no need to restart the engine.")
            log(f"[{task_id}] AI unavailable: {reason}")
            self._notify(task_id, "unavailable", friendly, privacy="local")
            return {"accepted": False, "task_id": task_id, "error": friendly}

        # 1) Perceive the active document (the agent's eyes).
        self._notify(task_id, "perceiving", "looking at the active document", privacy="local")
        overview = None
        try:
            overview = self.peer.call("perception.overview", {}, timeout=20)
        except (JsonRpcError, TimeoutError) as exc:
            self._notify(task_id, "warning", f"could not read the document: {exc}")

        # 1b) Geometric RAG (Phase 3): for a small document, fetch the close-up of
        #     each object so the model can reference real edges/faces.
        details = self._gather_details(task_id, overview)

        # Checkpoint (ADR 0008): the user may have cancelled while we perceived.
        if self._is_cancelled(task_id):
            return self._cancelled_result(task_id)

        # 2) Think: ask the local model for a plan.
        model_name = avail.get("model", "local model")
        self._notify(task_id, "thinking", f"asking the local model ({model_name})", privacy="local")
        try:
            plan = self.brain.plan(text, overview, details)
        except OllamaUnavailable as exc:
            self._notify(task_id, "unavailable", str(exc), privacy="local")
            return {"accepted": False, "task_id": task_id, "error": str(exc)}
        except PlanError as exc:
            self._notify(task_id, "error", str(exc), privacy="local")
            return {"accepted": False, "task_id": task_id, "error": str(exc)}

        for note in plan.get("notes", []):
            self._notify(task_id, "note", note)

        valid_actions = plan.get("valid_actions", [])
        clarification = plan.get("clarification")
        if not valid_actions:
            msg = clarification or "the model did not produce any runnable action."
            self._notify(task_id, "clarification", msg)
            return {"accepted": True, "task_id": task_id, "results": [],
                    "clarification": msg}

        # Checkpoint (ADR 0008): if the user cancelled while the model was
        # thinking, discard the plan and run NOTHING on FreeCAD. This is the most
        # valuable cancel point: the slow step is the inference, and we stop right
        # after it without touching the document.
        if self._is_cancelled(task_id):
            return self._cancelled_result(task_id)

        # 3) Execute each action, with BOUNDED self-correction on failure
        #    (principle 8): retry up to MAX_REPAIR_ATTEMPTS, never repeating an
        #    action we already tried (no infinite loops).
        results = []
        last_profile_id = None  # id of the most recent sketch created in THIS plan
        # Generalized id-chaining (ADR 0013): the id of the most recent object this
        # plan created, plus the set of ids the model could legitimately know about
        # (the document at plan start + everything created so far). A later step that
        # references an object the document does not contain yet is rewritten to the
        # last created id (e.g. "create a box and mirror it" when the box was named
        # 'Box001'). This is ADR 0010 generalized to "operate on the thing I just made".
        last_created_id = None
        # Number of objects this plan has created so far. The generic id-chaining
        # (ADR 0013) only fires while this is exactly 1: that is the unambiguous
        # "create ONE thing, then operate on it" idiom. In a plan that has created
        # several objects (e.g. box -> boss -> pocket), "the last created object" is
        # NOT a safe guess for an unresolved reference, so we leave the model's name
        # alone and let a genuine mistake fail and self-correct instead of silently
        # pointing at the wrong body. (This is the bug where a pocket meant for the
        # base box got aimed at the freshly-made boss.)
        created_count = 0
        known_ids = self._known_ids(overview)
        # Consumed-object redirection (ADR 0016): old id -> the feature that
        # swallowed it (e.g. Cylinder -> Drilled after a drill_hole). A later
        # step naming the old id is redirected, so "drill it four times" in one
        # plan lands every hole on the LIVE body, not on the dead base.
        replaced: dict = {}
        for idx, action in enumerate(valid_actions, 1):
            # Checkpoint before EACH action: stop between steps of a multi-step
            # plan, leaving the already-applied steps in place (Ctrl+Z undoes them).
            if self._is_cancelled(task_id):
                return self._cancelled_result(task_id, results)
            # Within a plan, make an extrude consume the sketch the preceding
            # create_sketch / sketch_on_face just made (its REAL id), instead of
            # trusting the model to predict the auto-generated name like 'Sketch001'
            # (ADR 0010; same philosophy as ADR 0006 for edges).
            action = self._link_profile_target(task_id, action, last_profile_id)
            # General id-chaining (ADR 0013), only when unambiguous (one creation).
            if created_count == 1:
                action = self._link_last_created(task_id, action,
                                                 last_created_id, known_ids)
            # Consumed-object redirection (ADR 0016).
            action = self._link_consumed(task_id, idx, action, replaced)
            res = self._run_action(task_id, idx, action)
            tried = {self._action_signature(action)}
            attempts = 0
            current = action
            while not res.get("ok") and attempts < MAX_REPAIR_ATTEMPTS:
                if self._is_cancelled(task_id):
                    break  # stop self-correcting; record what we have so far.
                repaired = self.brain.repair(
                    text, current, str(res.get("error", "")), overview, details)
                if not repaired:
                    break
                repaired = self._link_profile_target(task_id, repaired, last_profile_id)
                if created_count == 1:
                    repaired = self._link_last_created(task_id, repaired,
                                                       last_created_id, known_ids)
                repaired = self._link_consumed(task_id, idx, repaired, replaced)
                sig = self._action_signature(repaired)
                if sig in tried:  # the model keeps proposing the same fix: stop.
                    self._notify(task_id, "repair",
                                 f"action {idx}: no new correction proposed, giving up")
                    break
                tried.add(sig)
                attempts += 1
                self._notify(task_id, "repair",
                             f"action {idx} failed; retry {attempts}/{MAX_REPAIR_ATTEMPTS} "
                             "with a corrected version")
                res = self._run_action(task_id, idx, repaired)
                current = repaired
            results.append(res)
            # Remember the sketch made in this plan so the next extrude consumes it;
            # an extrude clears it (the profile is now used up).
            last_profile_id = self._next_profile_id(last_profile_id, current, res)
            # Remember the last object created and grow the set of known ids so the
            # next step can chain onto it (ADR 0013).
            last_created_id, known_ids = self._update_created(
                last_created_id, known_ids, res)
            # Note what the executed action consumed, so later steps that still
            # name the old id get redirected to its result (ADR 0016).
            replaced = self._record_consumed(current, res, replaced)
            if isinstance(res, dict) and res.get("ok") and res.get("created_ids"):
                created_count += 1

        ok_count = sum(1 for r in results if r.get("ok"))
        self._notify(task_id, "completed",
                     f"{ok_count}/{len(results)} action(s) done (Ctrl+Z to undo)")
        return {"accepted": True, "task_id": task_id, "results": results,
                "summary": f"{ok_count}/{len(results)} action(s) executed"}

    # -- consumed-target chaining (ADR 0016) -----------------------------------

    @staticmethod
    def _follow_replacements(ref: str, replaced: dict) -> str:
        """Resolve a reference through the chain of consumed->result mappings
        (Cylinder -> Drilled -> Drilled001 -> ...). Cycle-safe. Pure."""
        seen = set()
        while ref in replaced and ref not in seen:
            seen.add(ref)
            ref = replaced[ref]
        return ref

    @staticmethod
    def _rewrite_consumed(action: dict, replaced: dict) -> dict:
        """
        Return the action with references to CONSUMED objects redirected to the
        feature that swallowed them (ADR 0016). Within one plan, "drill Cylinder"
        after a previous drill already turned Cylinder into Drilled must target
        Drilled, or the second hole lands on the dead base and the visible result
        loses it. Returns the SAME object when nothing changes. Pure.
        """
        if not replaced or action.get("type", "command") != "command":
            return action
        params = action.get("params") or {}
        changed = {}
        for key in ("target", "a", "b"):
            ref = params.get(key)
            if isinstance(ref, str) and ref:
                new = Session._follow_replacements(ref, replaced)
                if new != ref:
                    changed[key] = new
        if not changed:
            return action
        new_params = dict(params)
        new_params.update(changed)
        out = dict(action)
        out["params"] = new_params
        return out

    @staticmethod
    def _record_consumed(action: dict, result: dict, replaced: dict) -> dict:
        """
        After a SUCCESSFUL action, record which referenced ids its new feature
        consumed (per CONSUMING_PARAMS), mapping old id -> first created id.
        Returns the updated mapping (input is not mutated). Pure.
        """
        if not (isinstance(result, dict) and result.get("ok")):
            return replaced
        created = result.get("created_ids") or []
        if not created:
            return replaced
        keys = CONSUMING_PARAMS.get(action.get("cmd")) or ()
        if not keys:
            return replaced
        params = action.get("params") or {}
        new_id = created[0]
        out = dict(replaced)
        for key in keys:
            ref = params.get(key)
            if isinstance(ref, str) and ref and ref != new_id:
                out[ref] = new_id
        return out

    def _link_consumed(self, task_id: str, idx: int, action: dict,
                       replaced: dict) -> dict:
        """Apply _rewrite_consumed and log any redirection (transparency)."""
        new_action = self._rewrite_consumed(action, replaced)
        if new_action is not action:
            old_p = action.get("params") or {}
            new_p = new_action.get("params") or {}
            moves = ", ".join(f"{old_p[k]!r} -> {new_p[k]!r}"
                              for k in ("target", "a", "b")
                              if old_p.get(k) != new_p.get(k))
            self._notify(task_id, "linking",
                         f"action {idx}: reference(s) to a consumed object "
                         f"redirected: {moves}")
        return new_action

    @staticmethod
    def _detail_candidates(objs: "list | None") -> list:
        """
        Which objects deserve a geometric close-up in the prompt: the VISIBLE
        ones. Hidden objects are almost always consumed inputs (the base a Cut
        replaced, a drill tool, an extruded sketch): describing their edges and
        faces bloats the prompt of a small model and invites it to target dead
        geometry. The cheap overview still lists ALL ids, so the model can
        reference a hidden object when the user asks explicitly. (Session 13
        fix: a 3-object document pushed the prompt past the model context.)
        Pure helper, unit-tested headless.
        """
        return [o for o in (objs or [])
                if o.get("id") and o.get("visible") is not False]

    def _gather_details(self, task_id: str, overview: "dict | None") -> "list[dict]":
        """
        Phase 3 geometric RAG: fetch perception.detail for each existing object so
        the model can reference real Edge*/Face*. Best-effort: a failure here just
        falls back to the cheap overview (graceful degradation, principle 9).
        Only VISIBLE objects are inspected (see _detail_candidates).
        """
        if not overview:
            return []
        objs = self._detail_candidates(overview.get("objects"))
        if not objs or len(objs) > MAX_DETAIL_OBJECTS:
            return []  # empty or too big: stay concise, overview only.
        self._notify(task_id, "inspecting",
                     f"inspecting {len(objs)} object(s) for edges/faces", privacy="local")
        details: list = []
        for o in objs:
            oid = o.get("id")
            if not oid:
                continue
            try:
                d = self.peer.call("perception.detail", {"target": oid}, timeout=20)
                if isinstance(d, dict) and not d.get("error"):
                    details.append(d)
            except (JsonRpcError, TimeoutError):
                continue  # skip this one; the overview still covers it.
        return details

    @staticmethod
    def _action_signature(action: dict) -> str:
        """Stable signature of an action, to detect a repair that repeats itself."""
        try:
            import json as _json
            return _json.dumps(action, sort_keys=True)
        except Exception:
            return repr(action)

    # -- sketch -> extrude id chaining (ADR 0010) -------------------------------
    # A small model cannot predict the auto-generated name of a sketch it is about
    # to create (the first is 'Sketch', the next 'Sketch001', ...). So when a plan
    # does create_sketch then extrude, we rewrite the extrude's target to the id the
    # create_sketch actually produced, rather than the name the model guessed. This
    # is the same "resolve fragile references in the engine" idea as ADR 0006.

    @staticmethod
    def _is_cmd(action: dict, name: str) -> bool:
        return (isinstance(action, dict)
                and action.get("type", "command") == "command"
                and action.get("cmd") == name)

    @staticmethod
    def _rewrite_extrude_target(action: dict, profile_id):
        """
        Pure helper. If `action` is an extrude and `profile_id` is set and differs
        from the model's target, return (copy_with_new_target, True); otherwise
        return (action, False). Never mutates the input.
        """
        if profile_id and Session._is_cmd(action, "extrude"):
            params = dict(action.get("params") or {})
            if params.get("target") != profile_id:
                return {**action, "params": {**params, "target": profile_id}}, True
        return action, False

    @staticmethod
    def _next_profile_id(current_id, action: dict, res: dict):
        """
        Update the 'sketch created in this plan' marker after running an action: a
        successful create_sketch (or sketch_on_face) sets it to the created id; a
        successful extrude clears it (the profile is consumed); anything else leaves
        it unchanged.
        """
        if not isinstance(res, dict) or not res.get("ok"):
            return current_id
        if Session._is_cmd(action, "create_sketch") \
                or Session._is_cmd(action, "sketch_on_face"):
            ids = res.get("created_ids") or []
            return ids[0] if ids else current_id
        if Session._is_cmd(action, "extrude"):
            return None
        return current_id

    def _link_profile_target(self, task_id: str, action: dict, profile_id):
        """Apply _rewrite_extrude_target and log it transparently when it fires."""
        new_action, changed = self._rewrite_extrude_target(action, profile_id)
        if changed:
            self._notify(task_id, "linking",
                         f"extruding the sketch just created ({profile_id})",
                         privacy="local")
        return new_action

    # -- generalized id chaining (ADR 0013) ------------------------------------
    # ADR 0010 solved one case (sketch -> extrude). The same fragility appears
    # whenever a plan says "create X, then operate on X": the model writes the name
    # it expects ("Box"), but FreeCAD may have auto-renamed it ("Box001"), or the
    # model uses a vague placeholder. We resolve it in the engine: track the last
    # object the plan created and, for a later step whose object reference does NOT
    # exist (neither in the document at plan start nor among the ids created so
    # far), rewrite that single reference to the last created id. Pure + logged.

    # For each command, the params that hold a reference to an EXISTING object.
    _REF_FIELDS = {
        "extrude": ("target",),
        "drill_hole": ("target",),
        "fillet": ("target",),
        "chamfer": ("target",),
        "move": ("target",),
        "rotate": ("target",),
        "mirror": ("target",),
        "array": ("target",),
        "sketch_on_face": ("target",),
        "boolean": ("a", "b"),
    }

    @staticmethod
    def _known_ids(overview) -> "set[str]":
        """Ids the model could legitimately reference: the document at plan start."""
        ids: set = set()
        if isinstance(overview, dict):
            for o in overview.get("objects", []) or []:
                oid = o.get("id") if isinstance(o, dict) else None
                if oid:
                    ids.add(oid)
        return ids

    @staticmethod
    def _update_created(last_created_id, known_ids: "set[str]", res: dict):
        """After a successful action, remember its first created id and add the
        created ids to the known set (so the next step can reference them)."""
        if isinstance(res, dict) and res.get("ok"):
            ids = res.get("created_ids") or []
            if ids:
                return ids[0], (known_ids | set(ids))
        return last_created_id, known_ids

    @staticmethod
    def _rewrite_refs(action: dict, last_created_id, known_ids: "set[str]"):
        """
        Pure helper. If `action` references an object that is not known yet (not in
        `known_ids`) and exactly ONE such reference is unresolved, rewrite it to
        `last_created_id`. Returns (action_or_copy, [changed_field_names]); never
        mutates the input. Requiring a single unresolved reference avoids guessing
        for a boolean whose two operands are both unknown (too ambiguous to fix).
        """
        if not last_created_id or not isinstance(action, dict):
            return action, []
        if action.get("type", "command") != "command":
            return action, []
        fields = Session._REF_FIELDS.get(action.get("cmd"))
        if not fields:
            return action, []
        params = dict(action.get("params") or {})
        unresolved = [f for f in fields
                      if isinstance(params.get(f), str)
                      and params.get(f) not in known_ids]
        if len(unresolved) != 1:
            return action, []
        field = unresolved[0]
        if params.get(field) == last_created_id:
            return action, []
        params[field] = last_created_id
        return {**action, "params": params}, [field]

    def _link_last_created(self, task_id: str, action: dict,
                           last_created_id, known_ids: "set[str]"):
        """Apply _rewrite_refs and log it transparently when it fires."""
        new_action, changed = self._rewrite_refs(action, last_created_id, known_ids)
        if changed:
            self._notify(task_id, "linking",
                         f"using the object just created ({last_created_id}) "
                         f"for {', '.join(changed)}", privacy="local")
        return new_action

    def _run_action(self, task_id: str, idx: int, action: dict) -> dict:
        """Execute one planned action on the add-on. Returns a commandResult."""
        atype = action.get("type", "command")
        if atype == "python":
            reason = action.get("reason", "")
            self._notify(task_id, "python",
                         f"proposing free Python: {reason}", privacy="local")
            try:
                return self.peer.call("python.execute",
                                      {"code": action.get("code", ""), "reason": reason},
                                      timeout=120)
            except (JsonRpcError, TimeoutError) as exc:
                return {"ok": False, "transaction_id": "", "error": str(exc)}
        cmd = action.get("cmd")
        self._notify(task_id, "executing", f"action {idx}: {cmd}", privacy="local")
        try:
            return self.peer.call("command.execute",
                                  {"cmd": cmd, "params": action.get("params", {})},
                                  timeout=60)
        except (JsonRpcError, TimeoutError) as exc:
            return {"ok": False, "transaction_id": "", "error": str(exc)}

    def on_user_cancel(self, params: dict) -> dict:
        """
        Cooperative cancellation (ADR 0008). Record the task id; the running
        on_user_prompt loop checks it at the next checkpoint and stops there,
        WITHOUT executing any further FreeCAD action. Returns immediately (the
        UI stays responsive); the actual stop is reported via agent.status
        ("cancelling" now, "cancelled" when the loop reaches a checkpoint).
        We cannot interrupt an in-flight model inference, so a long "thinking"
        step finishes first and its plan is then discarded (nothing is run).
        """
        task_id = (params.get("task_id") or "").strip() if isinstance(params, dict) else ""
        if not task_id:
            return {"ok": False, "error": "user.cancel needs a task_id"}
        self._mark_cancelled(task_id)
        log(f"[{task_id}] user.cancel received - will stop at the next checkpoint")
        self._notify(task_id, "cancelling",
                     "cancel requested - stopping at the next safe point "
                     "(no further action will run)")
        return {"ok": True}

    # -- cooperative cancellation helpers (ADR 0008) ---------------------------

    def _mark_cancelled(self, task_id: str) -> None:
        with self._cancel_lock:
            self._cancelled_tasks.add(task_id)

    def _is_cancelled(self, task_id: str) -> bool:
        with self._cancel_lock:
            return task_id in self._cancelled_tasks

    def _cancelled_result(self, task_id: str, results: "list | None" = None) -> dict:
        """Build the response when a task was stopped on user request."""
        results = results or []
        done = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
        self._notify(task_id, "cancelled",
                     f"stopped on request - {done} action(s) already done "
                     "(Ctrl+Z to undo).")
        log(f"[{task_id}] cancelled by the user after {done} action(s)")
        return {"accepted": True, "task_id": task_id, "cancelled": True,
                "results": results,
                "summary": f"cancelled after {done} action(s)"}

    # -- helpers ---------------------------------------------------------------

    def _notify(self, task_id: str, phase: str, message: str, privacy: str = "local") -> None:
        """Status notification to the UI (best-effort: errors don't block)."""
        try:
            self.peer.notify("agent.status", {
                "task_id": task_id, "phase": phase, "message": message, "privacy": privacy,
            })
        except Exception:  # pragma: no cover - defensive
            pass


def _register_engine_handlers(peer: JsonRpcPeer, session: "Session",
                              include_hello: bool) -> None:
    """
    Register the engine's operational handlers on a peer. These are the SAME in
    both topologies (the bridge is symmetric, ADR 0001): the engine always exposes
    command.request / user.prompt / user.cancel. Only `session.hello` differs:
      - SERVER standalone mode: the engine validates the token -> include it here.
      - CLIENT mode (production): the ADD-ON validates the token, so the engine
        does NOT expose session.hello; it CALLS it instead (see run_as_client).
    """
    if include_hello:
        peer.register("session.hello", session.on_hello)
    peer.register("command.request", session.on_command_request)
    peer.register("user.prompt", session.on_user_prompt)
    peer.register("user.cancel", session.on_user_cancel)


def _prepare_ai(brain: "Brain") -> None:
    """
    Transparent Ollama auto-start + reachability log (ADR 0007). Shared by both run
    modes so natural language works the same whether the engine was launched by the
    add-on (client) or by the .bat (server). Defensive about the brain interface so
    a stub brain (headless tests) is fine.
    """
    if hasattr(brain, "ensure_server"):
        autostart = brain.ensure_server(log=log)
        log(f"local AI (Ollama) auto-start: {autostart.get('status')} - {autostart.get('message')}")
    avail = brain.availability()
    if avail.get("available"):
        models = ", ".join(avail.get("models", [])) or "(none installed)"
        flag = "OK" if avail.get("has_default_model") else "default model NOT pulled"
        log(f"local AI (Ollama): reachable [{flag}]. model={avail.get('model')}; installed: {models}")
    else:
        log("local AI (Ollama): NOT reachable. Natural language will be refused "
            "gracefully; structured commands from the panel still work, and "
            "natural language resumes by itself once Ollama is up (no restart).")
        log(f"  -> {avail.get('reason')}")


def serve_connection(client_sock: socket.socket, token: str,
                     catalog: fake_brain.Catalog, brain: "Brain | None" = None) -> None:
    """Handle ONE add-on connection from the greeting until disconnection."""
    conn = FramedConnection(client_sock)
    # Default (inline) dispatcher: handlers run on the peer's internal pool, so
    # they can make nested calls without deadlocking (ADR 0003).
    peer = JsonRpcPeer(conn, name="engine", logger=log)
    session = Session(peer, token, catalog, brain=brain)

    _register_engine_handlers(peer, session, include_hello=True)
    peer.start()

    try:
        if not session.authenticated.wait(timeout=30):
            log("handshake not received in time: closing the connection.")
            return
        log("add-on attached. Ready to receive commands from the panel. "
            "(The add-on may disconnect and reconnect at will.)")
        # Stay alive until the add-on closes the connection.
        peer.wait_closed()
        log("add-on disconnected.")
    finally:
        peer.close()


def serve_forever(accept_timeout: float | None = None, oneshot: bool = False) -> int:
    """
    Start the server and serve connections PERSISTENTLY until interrupted
    (Ctrl+C). Returns an exit code.
    """
    catalog = fake_brain.Catalog()
    # One brain shared by all connections (it is stateless across requests).
    brain = Brain(catalog)
    token = discovery.generate_token()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((discovery.HOST, 0))  # ephemeral port
    srv.listen(1)
    port = srv.getsockname()[1]

    discovery.write(port, token, PROTOCOL_VERSION)
    version, names = fake_brain.summarize(catalog)
    log(f"listening on {discovery.HOST}:{port} (ephemeral port)")
    log(f"discovery file: {discovery.DEFAULT_FILE}")
    log(f"ephemeral token: {token[:8]}... (loopback only)")
    log(f"vocabulary v{version}: {', '.join(names)}")
    # Phase 4 (ADR 0007): transparent auto-start + reachability probe.
    _prepare_ai(brain)
    log("ENGINE READY. Leave this window open and use the panel in FreeCAD.")
    log("To stop the engine: Ctrl+C in this window.")

    # Accept timeout only if requested (for tests); otherwise wait forever.
    srv.settimeout(accept_timeout)

    try:
        while True:
            log("waiting for a connection from the add-on...")
            try:
                client_sock, addr = srv.accept()
            except socket.timeout:
                log("no connection within the timeout: exiting.")
                return 2
            log(f"connection from {addr}")
            try:
                serve_connection(client_sock, token, catalog, brain=brain)
            except Exception as exc:  # a blown-up session must not kill the engine
                log(f"session ended with error: {exc}")
            if oneshot:
                log("oneshot mode: one connection served, exiting.")
                return 0
            # back to the top of the loop: ready for a new connection
    finally:
        srv.close()
        discovery.remove()
        log("server closed, discovery file removed.")


def run_as_client(host: str, port: int, token: str,
                  brain: "Brain | None" = None,
                  connect_timeout: float = 10.0, connect_attempts: int = 40) -> int:
    """
    PRODUCTION topology (ADR 0015; ADR 0002 prod). The ADD-ON is the TCP server and
    has launched us with its host/port/token. We connect to it, greet it with the
    token via session.hello (the ADD-ON validates it - handshake roles swapped),
    then serve the add-on's requests until the connection closes (e.g. FreeCAD is
    closed or the panel disconnects), at which point we exit so no orphan is left.

    Returns an exit code (0 = clean end, 2 = could not connect / handshake failed).
    """
    catalog = fake_brain.Catalog()
    brain = brain or Brain(catalog)
    version, names = fake_brain.summarize(catalog)
    log(f"CLIENT mode: connecting to the add-on server at {host}:{port} ...")
    log(f"vocabulary v{version}: {', '.join(names)}")

    # The add-on should already be listening before it launches us, but retry a few
    # times to absorb any start-up race (principle 8: correctness over speed).
    sock = None
    last_exc = None
    for _ in range(max(1, connect_attempts)):
        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout)
            break
        except OSError as exc:
            last_exc = exc
            time.sleep(0.25)
    if sock is None:
        log(f"could not connect to the add-on server: {last_exc}")
        return 2
    # Blocking reads on the persistent link; call timeouts are the peer's job.
    sock.settimeout(None)

    conn = FramedConnection(sock)
    peer = JsonRpcPeer(conn, name="engine", logger=log)
    session = Session(peer, token, catalog, brain=brain)
    # CLIENT mode: we do NOT expose session.hello (the add-on validates); we call it.
    _register_engine_handlers(peer, session, include_hello=False)
    peer.start()

    # Transparent Ollama auto-start + reachability probe (same as server mode).
    _prepare_ai(brain)

    try:
        hello = peer.call("session.hello", {
            "token": token,
            "engine_version": ENGINE_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        }, timeout=connect_timeout)
    except (JsonRpcError, TimeoutError, ConnectionClosed) as exc:
        log(f"handshake with the add-on failed: {exc}")
        peer.close()
        return 2
    if not (isinstance(hello, dict) and hello.get("ok")):
        log(f"add-on rejected the handshake: {hello}")
        peer.close()
        return 2
    log(f"handshake OK. add-on v{hello.get('addon_version')}, "
        f"protocol {hello.get('protocol_version')}")
    log("ENGINE READY (client mode). Serving the add-on until it disconnects.")

    try:
        peer.wait_closed()
    except KeyboardInterrupt:
        pass
    finally:
        peer.close()
    log("add-on disconnected. Engine exiting (client mode).")
    return 0


def _connection_from_args_or_env(argv) -> "tuple[str, int, str] | None":
    """
    Return (host, port, token) if the add-on passed connection info (=> CLIENT
    mode), otherwise None (=> SERVER standalone mode for the .bat).

    CLI (any order): --host H --port P --token T  (also --host=H form).
    Env fallback: FREECAD_AGENT_HOST / FREECAD_AGENT_PORT / FREECAD_AGENT_TOKEN.
    """
    args: dict = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and "=" in a:
            key, val = a[2:].split("=", 1)
            args[key] = val
            i += 1
        elif a.startswith("--") and i + 1 < len(argv):
            args[a[2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    host = args.get("host") or os.environ.get("FREECAD_AGENT_HOST")
    port = args.get("port") or os.environ.get("FREECAD_AGENT_PORT")
    token = args.get("token") or os.environ.get("FREECAD_AGENT_TOKEN")
    if host and port and token:
        try:
            return host, int(port), token
        except (TypeError, ValueError):
            return None
    return None


def main() -> int:
    log(f"FreeCAD Agent - engine v{ENGINE_VERSION}, protocol {PROTOCOL_VERSION}")
    conn_info = _connection_from_args_or_env(sys.argv[1:])
    if conn_info is not None:
        host, port, token = conn_info
        try:
            return run_as_client(host, port, token)
        except KeyboardInterrupt:
            log("interrupted by the user (Ctrl+C).")
            return 130
    # No connection info: SERVER standalone mode (discovery file) for .bat debug.
    log("no connection args: starting in SERVER standalone mode (debug / .bat).")
    raw_timeout = os.environ.get("FREECAD_AGENT_ACCEPT_TIMEOUT", "")
    accept_timeout = float(raw_timeout) if raw_timeout else None
    oneshot = os.environ.get("FREECAD_AGENT_ONESHOT", "") == "1"
    try:
        return serve_forever(accept_timeout=accept_timeout, oneshot=oneshot)
    except KeyboardInterrupt:
        log("interrupted by the user (Ctrl+C).")
        discovery.remove()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
