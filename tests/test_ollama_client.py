#!/usr/bin/env python3
"""
test_ollama_client.py - the stdlib Ollama client against a FAKE local HTTP server.

We never touch a real Ollama: a tiny http.server impersonates the /api/tags and
/api/chat endpoints. We test model listing, availability, JSON chat parsing (incl.
a model that wraps JSON in a <think> block), and graceful degradation when the
server is unreachable (principle 9).

Runnable:
    python tests/test_ollama_client.py
    pytest tests/test_ollama_client.py
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "engine"))

import ollama_client  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the test server
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "qwen3:4b"}, {"name": "llama3:8b"}]})
        else:
            self._json({"error": "not found"}, 404)

    # The last /api/chat payload received, so tests can assert on the options
    # we send (e.g. num_ctx, the Session 13 empty-reply fix).
    last_chat_payload = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            _Handler.last_chat_payload = json.loads(body.decode("utf-8"))
        except Exception:
            _Handler.last_chat_payload = None
        # Simulate a model that emits a <think> preamble before the JSON.
        content = ('<think>let me plan</think>\n'
                   '{"actions": [{"type": "command", "cmd": "create_box", '
                   '"params": {"length": 1, "width": 1, "height": 1}}]}')
        self._json({"message": {"role": "assistant", "content": content}})


def _start_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def run_scenario():
    details = {}
    srv = _start_server()
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        c = ollama_client.OllamaClient(base_url=base, model="qwen3:4b")

        # 1) list_models + availability
        models = c.list_models()
        assert "qwen3:4b" in models, models
        assert c.is_available() is True
        assert c.has_model("qwen3:4b") is True
        assert c.has_model("does-not-exist") is False
        details["models"] = models

        # 2) chat_json parses JSON even with a <think> wrapper.
        reply = c.chat_json("system", "make a 1mm cube")
        assert reply["actions"][0]["cmd"] == "create_box", reply
        details["chat"] = reply["actions"][0]["cmd"]

        # 2b) the request asks for a context window big enough for our prompt
        # (Session 13 fix: Ollama's small default truncated the instructions and
        # the model returned an EMPTY reply). Default must be sent...
        sent = _Handler.last_chat_payload or {}
        assert sent.get("options", {}).get("num_ctx") == \
            ollama_client.DEFAULT_NUM_CTX, sent.get("options")
        assert ollama_client.DEFAULT_NUM_CTX >= 8192, ollama_client.DEFAULT_NUM_CTX
        # ...and num_ctx <= 0 must NOT override Ollama's own default.
        c_off = ollama_client.OllamaClient(base_url=base, model="qwen3:4b",
                                           num_ctx=0)
        c_off.chat_json("system", "make a 1mm cube")
        sent_off = _Handler.last_chat_payload or {}
        assert "num_ctx" not in sent_off.get("options", {}), sent_off.get("options")
        details["num_ctx"] = ollama_client.DEFAULT_NUM_CTX
    finally:
        srv.shutdown()

    # 3) graceful degradation: server gone -> OllamaUnavailable / available False.
    dead = ollama_client.OllamaClient(base_url=base, model="qwen3:4b", timeout=2)
    assert dead.is_available() is False, "should report unavailable after shutdown"
    try:
        dead.list_models()
        raise AssertionError("expected OllamaUnavailable")
    except ollama_client.OllamaUnavailable:
        details["graceful"] = "OllamaUnavailable raised"

    # 4) the JSON extractor handles bare and wrapped objects.
    assert ollama_client._parse_json_object('{"a":1}')["a"] == 1
    assert ollama_client._parse_json_object('noise {"a":2} tail')["a"] == 2
    details["parser"] = "ok"

    return True, details


def test_ollama_client():
    ok, details = run_scenario()
    assert ok, f"ollama client scenario failed: {details}"


if __name__ == "__main__":
    print("== test_ollama_client: stdlib client vs fake server + graceful degradation ==")
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
    print("PASS - Ollama client talks JSON and degrades gracefully.")
    sys.exit(0)
