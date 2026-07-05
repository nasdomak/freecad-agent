"""
engine/brain.py - the REAL planning brain (Phase 2).

It replaces the "decision" role of the Phase 1 fake brain: given a natural-language
request (and a concise perception of the active document), it asks a local model
(via Ollama) to produce a PLAN: an ordered list of actions. Each action is either

  - a structured-vocabulary command  {type:"command", cmd, params}, or
  - a free-Python proposal           {type:"python", code, reason}.

Design choices (see ADR 0004):
  - Model-agnostic structured output: we describe the exact JSON shape in the
    system prompt and force JSON mode (ollama format="json"). We do NOT rely on a
    specific model's native tool-calling, so the engine "adapts, not excludes"
    (principle 9). The tester's model is qwen3:4b, but nothing here is tuned to it.
  - The vocabulary the model sees is GENERATED from shared/commands.schema.json
    (principle 5: the vocabulary is neutral data). Add a command to the schema and
    the brain automatically offers it to the model.
  - Validation downstream of the model (principle 7: don't trust, verify): every
    command action is re-validated against the catalog by fake_brain before it is
    allowed to run. Invalid actions are dropped with a reported reason.
  - Self-correction (principle 6/8): repair() lets the engine feed an execution
    error back to the model and ask for a corrected action.

This module has NO dependency on FreeCAD and is fully testable headless by
injecting a fake "chat" function in place of the Ollama client.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

import fake_brain  # engine/fake_brain.py: catalog loader + validator (stdlib)
from ollama_client import OllamaClient, OllamaUnavailable

# A "chat" callable: (system_prompt, user_prompt) -> parsed JSON dict.
# Default is the real Ollama client; tests inject a fake one.
ChatFn = Callable[[str, str], Dict[str, Any]]


class PlanError(RuntimeError):
    """The brain could not produce a usable plan (model error or unparseable)."""


class Brain:
    """Turns natural language into a validated plan of CAD actions."""

    def __init__(self, catalog: Optional[fake_brain.Catalog] = None,
                 chat: Optional[ChatFn] = None,
                 client: Optional[OllamaClient] = None) -> None:
        self.catalog = catalog or fake_brain.Catalog()
        # Either an explicit chat function (tests) or a real Ollama client.
        self._client = client or OllamaClient()
        self._chat: ChatFn = chat or self._client.chat_json

    # -- runtime configuration -------------------------------------------------

    def set_timeout(self, seconds) -> bool:
        """
        Set the per-call Ollama timeout at runtime (Phase 4: configurable from the
        panel instead of only via FREECAD_AGENT_OLLAMA_TIMEOUT).

        Convention: None or a non-positive number means UNLIMITED (no timeout) -
        the default; a positive number caps each model call. Best-effort and never
        raises: ignores bad values and clients without a `timeout` attribute (e.g. a
        fake chat injected in tests). Returns True if it was applied.
        """
        if not hasattr(self._client, "timeout"):
            return False
        if seconds is None:
            self._client.timeout = None  # unlimited
            return True
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return False
        # 0 or negative => unlimited; otherwise the positive cap.
        self._client.timeout = value if value > 0 else None
        return True

    def get_timeout(self):
        """Return the current per-call Ollama timeout, or None if not applicable."""
        return getattr(self._client, "timeout", None)

    # -- availability ----------------------------------------------------------

    def availability(self) -> Dict[str, Any]:
        """Report whether the local model is reachable (for graceful degradation)."""
        try:
            models = self._client.list_models()
        except OllamaUnavailable as exc:
            return {"available": False, "reason": str(exc), "models": []}
        except Exception:  # a fake chat without a real client: assume available
            return {"available": True, "reason": "", "models": []}
        if not models:
            return {
                "available": False,
                "reason": ("Ollama is running but no model is installed. "
                           f"Pull one, e.g. `ollama pull {self._client.model}`."),
                "models": [],
            }
        # Resolve the tag we will actually use (may differ from the configured one).
        try:
            effective = self._client.effective_model()
        except Exception:
            effective = self._client.model
        return {
            "available": True,
            "reason": "",
            "models": models,
            "has_default_model": self._client.has_model(),
            "model": effective,
        }

    # -- transparent auto-start (Phase 4, ADR 0007) ----------------------------

    def ensure_server(self, log=None, wait_seconds: float = 20.0) -> Dict[str, Any]:
        """
        Make sure the local AI server (Ollama) is running, launching it if needed.

        Delegates to ollama_launch.ensure_running using THIS brain's client as the
        reachability probe. Only meaningful with a real OllamaClient; with a fake
        chat injected for tests it is a harmless no-op probe. Never raises.
        """
        try:
            from ollama_launch import ensure_running
        except Exception as exc:  # pragma: no cover - import guard
            return {"status": "error", "launched": False, "message": str(exc)}
        # The client must expose a no-raise is_available(); the real OllamaClient
        # does. If a bare fake without it was injected, skip gracefully.
        if not callable(getattr(self._client, "is_available", None)):
            return {"status": "skipped", "launched": False,
                    "message": "no real Ollama client to probe."}
        return ensure_running(self._client, log=log, wait_seconds=wait_seconds)

    # -- planning --------------------------------------------------------------

    def plan(self, request: str, overview: Optional[dict] = None,
             details: Optional[List[dict]] = None) -> Dict[str, Any]:
        """
        Produce a plan from a natural-language request.

        Args:
          request:  the user's natural-language text.
          overview: the cheap document overview (perception.overview): one line
                    per object (id/type/label).
          details:  optional list of objectDetail dicts (perception.detail), the
                    "geometric RAG" of Phase 3. They give the model the REAL
                    Edge*/Face* references (with hints) it needs to fillet, chamfer
                    or drill precise sub-elements, instead of guessing them.

        Returns: {"actions": [...], "valid_actions": [...], "notes": [...],
                  "clarification": str|None}
        - actions:        everything the model proposed (raw)
        - valid_actions:  the subset that passed validation and is safe to run
        - notes:          human-readable messages (dropped actions, warnings)
        - clarification:  set when the model asks for more info / refuses
        Raises PlanError if the model reply is unusable.
        """
        system = self._system_prompt()
        user = self._user_prompt(request, overview, details)
        try:
            reply = self._chat(system, user)
        except OllamaUnavailable:
            raise
        except Exception as exc:  # parsing or transport problem
            raise PlanError(f"the model did not return a usable plan: {exc}") from exc

        return self._normalize(reply)

    def repair(self, request: str, failed_action: dict, error: str,
               overview: Optional[dict] = None,
               details: Optional[List[dict]] = None) -> Optional[dict]:
        """
        Ask the model to fix a single action that failed at execution time
        (self-correction). Returns a corrected action dict, or None if the model
        cannot fix it. Bounded by the caller to avoid loops (principle 8).

        The geometric detail (Phase 3) is fed back too: many failures are wrong
        Edge*/Face* references, which the detail lets the model correct.
        """
        system = self._system_prompt()
        user = (
            "A previous action FAILED when executed in FreeCAD. "
            "Return a corrected plan as the same JSON object with an 'actions' "
            "array (usually a single fixed action). Do not repeat the same mistake.\n\n"
            f"Original request: {request}\n"
            f"Failed action: {json.dumps(failed_action)}\n"
            f"FreeCAD error: {error}\n\n"
            f"{self._overview_block(overview)}"
            f"{self._details_block(details)}"
        )
        try:
            reply = self._chat(system, user)
        except Exception:
            return None
        plan = self._normalize(reply)
        valid = plan.get("valid_actions") or []
        return valid[0] if valid else None

    # -- prompt construction ---------------------------------------------------

    def _system_prompt(self) -> str:
        """Describe the role, the vocabulary (from the schema) and the output shape."""
        lines: List[str] = [
            "You are the planning brain of FreeCAD Agent, an assistant that builds "
            "3D CAD models in FreeCAD. Convert the user's request into an ordered "
            "plan of actions. Units are millimetres and degrees.",
            "",
            "You can use these STRUCTURED COMMANDS (prefer them whenever they fit):",
        ]
        lines.append(self._catalog_block())
        lines += [
            "",
            "If (and only if) no structured command fits, you may propose FREE "
            "PYTHON for FreeCAD as an action of type 'python' with fields 'code' "
            "(FreeCAD Python using the variables `doc` and `FreeCAD`) and 'reason' "
            "(why the vocabulary was not enough). The user always sees this code.",
            "",
            "To reference an EXISTING object, use the exact `id` from the document "
            "overview the user gives you. Do not invent ids.",
            "",
            "Answer with ONE JSON object, no prose, with this exact shape:",
            '{"actions": [',
            '  {"type": "command", "cmd": "<command name>", "params": { ... }},',
            '  {"type": "python", "code": "<freecad python>", "reason": "<why>"}',
            "],",
            '"clarification": "<set only if you cannot proceed and need more info, '
            'otherwise omit or null>"}',
            "",
            "Rules: output valid JSON only; keep the plan minimal and correct; "
            "never include comments in the JSON; if the request is impossible or "
            "ambiguous, return an empty actions array and a clarification message.",
            "",
            "For fillet and chamfer you normally do NOT list edges. Omit 'edges' "
            "and optionally set 'where' to choose a group: 'all' (default), 'top', "
            "'bottom', 'vertical' or 'horizontal'. The tool reads the real geometry "
            "and selects the matching edges itself. Only pass an explicit 'edges' "
            "list (e.g. from 'DETAILED GEOMETRY') when the user clearly wants "
            "specific edges; never invent edge numbers. "
            "For drilling a centred hole you do NOT need a position: omit it and the "
            "tool drills from the top centre automatically. To drill at a specific "
            "point instead, pass position [x, y] (top-view coordinates in mm); the "
            "tool drills downwards from the top face at that point.",
            "",
            "To EXTRUDE a 2D shape into a solid, first create the profile with "
            "create_sketch (it makes an object named 'Sketch'), then call extrude "
            "with target 'Sketch'. A rectangle needs width and height; a circle "
            "needs radius. The default plane is XY.",
            "",
            "To MOVE an existing object use move with 'by' [dx,dy,dz] for a "
            "relative shift (preferred) or 'to' [x,y,z] for an absolute position. "
            "To ROTATE an existing object use rotate with an 'angle' in degrees and "
            "an 'axis' of 'X', 'Y' or 'Z' (default 'Z'); the tool spins it around "
            "its own centre. Give axes as these letters, never as raw vectors.",
            "",
            "To DUPLICATE shapes: use mirror to reflect an object across a plane "
            "('XY'/'XZ'/'YZ', the original is kept); use array for a pattern of "
            "copies - pattern 'linear' (with count, spacing and a direction X/Y/Z) "
            "or pattern 'polar' (with count and axis X/Y/Z). count is the TOTAL "
            "number of items including the original. A POLAR pattern makes the items "
            "ORBIT a central axis (the file origin by default), forming a ring - it "
            "does NOT spin the object on itself. If the user names a centre or point, "
            "pass it as center [x,y,z]; if the user gives a circle radius, pass it as "
            "radius (the tool then places the items on that circle); otherwise the "
            "items orbit at the object's current distance from the centre. Optional "
            "angle (default a full 360 circle). To operate on something you JUST "
            "created, reference it by the name you gave it; the tool links to the "
            "real object automatically.",
            "",
            "To add or remove material on an existing body: use sketch_on_face to "
            "put a sketch on a flat face (where 'top' or 'bottom'; the tool finds "
            "the real face), then extrude it. extrude with op 'add' (default) grows "
            "a boss out of the face; extrude with op 'cut' sinks a POCKET into the "
            "body. Do not guess face numbers - use 'where'.",
            "",
            "EXAMPLES (input on the left, the exact JSON you must output on the right):",
            'Request: "create a box 30x20x10"',
            '{"actions": [{"type": "command", "cmd": "create_box", '
            '"params": {"length": 30, "width": 20, "height": 10}}]}',
            'Request: "drill a 6 mm hole through the centre of Box" '
            '(document has Box, height 10)',
            '{"actions": [{"type": "command", "cmd": "drill_hole", '
            '"params": {"target": "Box", "diameter": 6, "depth": 10}}]}',
            'Request: "drill a 5 mm hole 12 mm deep in Plate at position [30, 0]" '
            '(document has Plate)',
            '{"actions": [{"type": "command", "cmd": "drill_hole", '
            '"params": {"target": "Plate", "diameter": 5, "depth": 12, '
            '"position": [30, 0]}}]}',
            'Request: "round all the edges of Box with radius 2"',
            '{"actions": [{"type": "command", "cmd": "fillet", "params": '
            '{"target": "Box", "radius": 2}}]}',
            'Request: "chamfer the top edges of Box by 1.5"',
            '{"actions": [{"type": "command", "cmd": "chamfer", "params": '
            '{"target": "Box", "size": 1.5, "where": "top"}}]}',
            'Request: "merge Box and Cylinder"',
            '{"actions": [{"type": "command", "cmd": "boolean", "params": '
            '{"op": "union", "a": "Box", "b": "Cylinder"}}]}',
            'Request: "create a box 40x40x10 and drill a 8 mm hole in the centre"',
            '{"actions": [{"type": "command", "cmd": "create_box", "params": '
            '{"length": 40, "width": 40, "height": 10}}, '
            '{"type": "command", "cmd": "drill_hole", "params": '
            '{"target": "Box", "diameter": 8, "depth": 10}}]}',
            'Request: "draw a 40x30 rectangle and extrude it 10 mm"',
            '{"actions": [{"type": "command", "cmd": "create_sketch", "params": '
            '{"shape": "rectangle", "width": 40, "height": 30}}, '
            '{"type": "command", "cmd": "extrude", "params": '
            '{"target": "Sketch", "distance": 10}}]}',
            'Request: "extrude a circle of radius 12 by 20 mm"',
            '{"actions": [{"type": "command", "cmd": "create_sketch", "params": '
            '{"shape": "circle", "radius": 12}}, '
            '{"type": "command", "cmd": "extrude", "params": '
            '{"target": "Sketch", "distance": 20}}]}',
            'Request: "move Box 20 mm along X" (document has Box)',
            '{"actions": [{"type": "command", "cmd": "move", "params": '
            '{"target": "Box", "by": [20, 0, 0]}}]}',
            'Request: "rotate Cylinder 45 degrees around Z" (document has Cylinder)',
            '{"actions": [{"type": "command", "cmd": "rotate", "params": '
            '{"target": "Cylinder", "angle": 45, "axis": "Z"}}]}',
            'Request: "mirror Bracket across the YZ plane" (document has Bracket)',
            '{"actions": [{"type": "command", "cmd": "mirror", "params": '
            '{"target": "Bracket", "plane": "YZ"}}]}',
            'Request: "make a row of 5 copies of Box, 30 mm apart along X" '
            '(document has Box)',
            '{"actions": [{"type": "command", "cmd": "array", "params": '
            '{"target": "Box", "pattern": "linear", "count": 5, "spacing": 30, '
            '"direction": "X"}}]}',
            'Request: "arrange 6 copies of Pin in a circle around Z" '
            '(document has Pin)',
            '{"actions": [{"type": "command", "cmd": "array", "params": '
            '{"target": "Pin", "pattern": "polar", "count": 6, "axis": "Z"}}]}',
            'Request: "arrange 8 copies of Hole on a circle of radius 40 around the '
            'Z axis" (document has Hole)',
            '{"actions": [{"type": "command", "cmd": "array", "params": '
            '{"target": "Hole", "pattern": "polar", "count": 8, "axis": "Z", '
            '"radius": 40}}]}',
            'Request: "draw a 20x10 rectangle on the top face of Box and extrude it '
            '5 mm" (document has Box)',
            '{"actions": [{"type": "command", "cmd": "sketch_on_face", "params": '
            '{"target": "Box", "where": "top", "shape": "rectangle", "width": 20, '
            '"height": 10}}, {"type": "command", "cmd": "extrude", "params": '
            '{"target": "Sketch", "distance": 5}}]}',
            'Request: "cut a round pocket of radius 6, 4 mm deep, into the top of '
            'Box" (document has Box)',
            '{"actions": [{"type": "command", "cmd": "sketch_on_face", "params": '
            '{"target": "Box", "where": "top", "shape": "circle", "radius": 6}}, '
            '{"type": "command", "cmd": "extrude", "params": '
            '{"target": "Sketch", "distance": 4, "op": "cut"}}]}',
        ]
        return "\n".join(lines)

    def _catalog_block(self) -> str:
        """Compact, model-friendly description of each command and its parameters."""
        out: List[str] = []
        for name in self.catalog.names():
            spec = self.catalog.spec(name) or {}
            summary = spec.get("summary", "")
            pschema = spec.get("params", {})
            required = set(pschema.get("required", []))
            props = pschema.get("properties", {})
            parts = []
            for pname, pspec in props.items():
                ptype = pspec.get("type", "any")
                if "enum" in pspec:
                    ptype = "one of " + "/".join(map(str, pspec["enum"]))
                tag = "required" if pname in required else "optional"
                parts.append(f"{pname} ({ptype}, {tag})")
            params_desc = "; ".join(parts) if parts else "no parameters"
            out.append(f"- {name}: {summary} Params: {params_desc}.")
        return "\n".join(out)

    def _user_prompt(self, request: str, overview: Optional[dict],
                     details: Optional[List[dict]] = None) -> str:
        return (f"{self._overview_block(overview)}"
                f"{self._details_block(details)}"
                f"User request: {request}")

    def _details_block(self, details: Optional[List[dict]]) -> str:
        """
        Render the geometric RAG concisely (Phase 3). One short paragraph per
        object: dimensions, bounding box and the referenceable Edge*/Face* with
        their hints, so a small local model can target real sub-elements. Kept
        terse on purpose (context.schema.json goal: do not saturate small models).
        """
        if not details:
            return ""
        lines = ["DETAILED GEOMETRY (use these exact references):"]
        for d in details:
            if not isinstance(d, dict) or d.get("error"):
                continue
            oid = d.get("id", "?")
            otype = d.get("type", "?")
            dims = d.get("dimensions") or {}
            dims_txt = ", ".join(f"{k}={v}" for k, v in dims.items())
            head = f"  - {oid} ({otype})"
            if dims_txt:
                head += f": {dims_txt}"
            bb = d.get("bounding_box") or {}
            if bb.get("min") and bb.get("max"):
                head += f"; bbox min {bb['min']} max {bb['max']}"
            lines.append(head)
            subs = d.get("named_subelements") or []
            faces = [s for s in subs if s.get("kind") == "face"]
            edges = [s for s in subs if s.get("kind") == "edge"]
            if faces:
                ftxt = ", ".join(
                    f"{s['ref']}" + (f"({s['hint']})" if s.get("hint") else "")
                    for s in faces)
                lines.append(f"      faces: {ftxt}")
            if edges:
                etxt = ", ".join(s["ref"] for s in edges)
                lines.append(f"      edges: {etxt}")
        return "\n".join(lines) + "\n\n"

    def _overview_block(self, overview: Optional[dict]) -> str:
        if not overview:
            return "The document is currently empty or its content is unknown.\n\n"
        objs = overview.get("objects", [])
        if not objs:
            return (f"Active document '{overview.get('document_name', '?')}' is empty "
                    f"(no objects yet).\n\n")
        lines = [f"Active document '{overview.get('document_name', '?')}' contains "
                 f"{overview.get('object_count', len(objs))} object(s):"]
        for o in objs:
            lines.append(f"  - id={o.get('id')} type={o.get('type')} "
                         f"label={o.get('label')}")
        return "\n".join(lines) + "\n\n"

    # -- normalization + validation --------------------------------------------

    def _normalize(self, reply: Any) -> Dict[str, Any]:
        """Validate the model reply structurally and split valid/invalid actions."""
        if not isinstance(reply, dict):
            raise PlanError("the model reply is not a JSON object")

        actions = reply.get("actions", [])
        if not isinstance(actions, list):
            raise PlanError("the 'actions' field is not a list")

        clarification = reply.get("clarification") or None
        notes: List[str] = []
        valid: List[dict] = []

        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                notes.append(f"action #{i}: ignored (not an object)")
                continue
            atype = action.get("type", "command")
            if atype == "python":
                code = action.get("code")
                if not isinstance(code, str) or not code.strip():
                    notes.append(f"action #{i}: python action without code, dropped")
                    continue
                valid.append({"type": "python", "code": code,
                              "reason": action.get("reason", "")})
            elif atype == "command":
                invocation = {"cmd": action.get("cmd"),
                              "params": action.get("params", {}) or {}}
                errors = fake_brain.validate_invocation(invocation, self.catalog)
                if fake_brain.is_blocking(errors):
                    notes.append(
                        f"action #{i} ({invocation['cmd']}): dropped, "
                        f"{'; '.join(errors)}")
                    continue
                if errors:  # non-blocking warnings
                    notes.append(f"action #{i} ({invocation['cmd']}): "
                                 f"{'; '.join(errors)}")
                valid.append({"type": "command", **invocation})
            else:
                notes.append(f"action #{i}: unknown action type '{atype}', dropped")

        return {
            "actions": actions,
            "valid_actions": valid,
            "notes": notes,
            "clarification": clarification,
        }
