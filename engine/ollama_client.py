"""
engine/ollama_client.py - minimal Ollama client using ONLY the Python standard
library (urllib). No third-party packages, no virtual environment required.

WHY stdlib over the REST API (ADR 0004):
  - Security-first: zero third-party dependencies means zero supply-chain attack
    surface. Nothing to `pip install`, nothing to trust or audit.
  - Robustness/portability (principle 3 + 9): the engine stays pure stdlib, so it
    runs on ANY Python >= 3.8 without a venv. The engine never touches FreeCAD's
    Python 3.11.
  - Simplicity for a non-developer: starting the engine stays a single double-click
    on START_ENGINE.bat.

Ollama exposes a local HTTP API (default http://127.0.0.1:11434). We use:
  - GET  /api/tags   -> list installed models (also our availability probe)
  - POST /api/chat   -> chat completion (we force JSON output with format="json")

Graceful degradation (principle 9): if Ollama is not installed/running, every
call raises OllamaUnavailable with a friendly, actionable message; the engine
turns that into a polite refusal instead of crashing.

Configuration via environment variables (optional):
  FREECAD_AGENT_OLLAMA_URL    base URL          (default http://127.0.0.1:11434)
  FREECAD_AGENT_OLLAMA_MODEL  model tag         (default qwen3:4b)
  FREECAD_AGENT_OLLAMA_TIMEOUT seconds per call (default: UNLIMITED / no timeout)
  FREECAD_AGENT_OLLAMA_NUM_CTX context window in tokens (default 8192; 0 = let
                               Ollama use its own default)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_URL = os.environ.get("FREECAD_AGENT_OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("FREECAD_AGENT_OLLAMA_MODEL", "qwen3:4b")
# Per-call timeout. Default is UNLIMITED (None): wait as long as the model needs,
# unless the user opts into a limit (panel) or sets FREECAD_AGENT_OLLAMA_TIMEOUT.
_RAW_TIMEOUT = os.environ.get("FREECAD_AGENT_OLLAMA_TIMEOUT", "").strip()
DEFAULT_TIMEOUT: "float | None" = float(_RAW_TIMEOUT) if _RAW_TIMEOUT else None
# Reachability probes (list_models / is_available) must stay snappy regardless of
# the (possibly unlimited) inference timeout.
PROBE_TIMEOUT = 10.0
# Context window (tokens) requested per chat call. Ollama's own default (2048 or
# 4096 depending on the build) is SMALLER than our planning prompt once the
# document holds a few objects: Ollama then silently TRUNCATES the beginning of
# the prompt (i.e. our instructions) and small models reply with empty/garbled
# content. Seen in the real Session 13 test ("the model returned an empty
# reply" on the third request). 8192 fits the system prompt (~2.8k tokens) plus
# a detailed document with headroom, and a 4B model handles it fine. 0 disables
# the override (Ollama's default is used again).
_RAW_NUM_CTX = os.environ.get("FREECAD_AGENT_OLLAMA_NUM_CTX", "").strip()
DEFAULT_NUM_CTX: int = int(_RAW_NUM_CTX) if _RAW_NUM_CTX else 8192


class OllamaUnavailable(RuntimeError):
    """Raised when Ollama cannot be reached or the model is missing.

    The message is written to be shown straight to the user (principle 9).
    """


class OllamaClient:
    """Tiny HTTP client for a local Ollama server (stdlib only)."""

    def __init__(self, base_url: str = DEFAULT_URL, model: str = DEFAULT_MODEL,
                 timeout: "float | None" = DEFAULT_TIMEOUT,
                 num_ctx: int = DEFAULT_NUM_CTX) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # None => no per-call timeout (wait indefinitely). A positive number caps
        # each model call.
        self.timeout = timeout
        # Context window requested per call (see DEFAULT_NUM_CTX above).
        # <= 0 means "do not override Ollama's default".
        self.num_ctx = num_ctx
        # The actually-used model tag, resolved against what is installed. The
        # configured `model` is just a preference: if it is not installed we fall
        # back to a matching/available one (principle 9: adapt, don't exclude).
        self._effective_model: Optional[str] = None

    # -- low-level HTTP --------------------------------------------------------

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OllamaUnavailable(self._http_error(path, exc)) from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailable(self._friendly_error(exc)) from exc
        except (TimeoutError, ConnectionError) as exc:  # pragma: no cover
            raise OllamaUnavailable(self._friendly_error(exc)) from exc

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OllamaUnavailable(self._http_error(path, exc)) from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailable(self._friendly_error(exc)) from exc
        except (TimeoutError, ConnectionError) as exc:  # pragma: no cover
            raise OllamaUnavailable(self._friendly_error(exc)) from exc

    def _http_error(self, path: str, exc: "urllib.error.HTTPError") -> str:
        """Build a clear message from an HTTP error, including Ollama's own body."""
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace").strip()
        except Exception:
            pass
        return (f"Ollama answered HTTP {exc.code} on {path}: "
                f"{body or exc.reason}. (The server is reachable; this is usually a "
                f"missing model or an unsupported endpoint.)")

    def _friendly_error(self, exc: Exception) -> str:
        return (
            f"Cannot reach the local AI (Ollama) at {self.base_url}. "
            "Make sure Ollama is installed and running, then pull a model "
            f"(e.g. `ollama pull {self.model}`). Underlying error: {exc}"
        )

    # -- public API ------------------------------------------------------------

    def list_models(self) -> List[str]:
        """Return the tags of the installed models. Doubles as a reachability probe."""
        data = self._get("/api/tags")
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def is_available(self) -> bool:
        """True if the server answers. Never raises (principle 9)."""
        try:
            self.list_models()
            return True
        except OllamaUnavailable:
            return False

    def has_model(self, model: Optional[str] = None) -> bool:
        """True if `model` (or the default) is installed locally."""
        target = model or self.model
        try:
            installed = self.list_models()
        except OllamaUnavailable:
            return False
        # Ollama tags may carry a ":latest" suffix; match leniently.
        bare = target.split(":")[0]
        return any(name == target or name.split(":")[0] == bare for name in installed)

    def effective_model(self) -> str:
        """
        Resolve the model tag to actually use against what is installed:
          1) the configured tag if installed exactly;
          2) otherwise any installed tag with the same base name
             (e.g. configured 'qwen3:4b' -> installed 'qwen3:8b' or 'qwen3:latest');
          3) otherwise the first installed model.
        Raises OllamaUnavailable if the server is unreachable or has no models.
        Cached after the first successful resolution.
        """
        if self._effective_model:
            return self._effective_model
        installed = self.list_models()  # may raise OllamaUnavailable
        if not installed:
            raise OllamaUnavailable(
                "Ollama is running but no model is installed. Pull one first, "
                f"e.g. `ollama pull {self.model}`.")
        chosen = None
        if self.model in installed:
            chosen = self.model
        else:
            bare = self.model.split(":")[0]
            same_base = [m for m in installed if m.split(":")[0] == bare]
            chosen = same_base[0] if same_base else installed[0]
        self._effective_model = chosen
        return chosen

    def chat_json(self, system: str, user: str,
                  temperature: float = 0.0) -> Dict[str, Any]:
        """
        Send a (system, user) pair and return the model's reply PARSED as JSON.

        We force JSON output with format="json" (supported by every recent Ollama
        build and model-agnostic). A low temperature keeps the planner
        deterministic (principle 8: correctness before speed). Robust against the
        "thinking" preamble some models emit: we extract the JSON object from the
        content if needed.
        """
        options: Dict[str, Any] = {"temperature": temperature}
        # Ask for a context window large enough for our prompt: without this,
        # Ollama's small default truncates the instructions and the model can
        # return an EMPTY reply (see DEFAULT_NUM_CTX above).
        if isinstance(self.num_ctx, int) and self.num_ctx > 0:
            options["num_ctx"] = self.num_ctx
        payload = {
            "model": self.effective_model(),  # use an actually-installed tag
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": options,
        }
        reply = self._post("/api/chat", payload)
        content = (reply.get("message") or {}).get("content", "")
        return _parse_json_object(content)


def _parse_json_object(content: str) -> Dict[str, Any]:
    """
    Parse the model's textual reply into a JSON object.

    First try a straight json.loads; if the model wrapped the JSON in prose or a
    <think> block, fall back to extracting the outermost {...} span. Raises
    ValueError if nothing parseable is found.
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("the model returned an empty reply")
    try:
        return json.loads(content)
    except ValueError:
        pass
    # Fallback: grab the outermost balanced object.
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = content[start:end + 1]
        return json.loads(snippet)  # may still raise: caller handles it
    raise ValueError(f"no JSON object found in the model reply: {content[:200]!r}")
