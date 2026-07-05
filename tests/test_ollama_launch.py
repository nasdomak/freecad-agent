#!/usr/bin/env python3
"""
tests/test_ollama_launch.py - unit tests for the transparent Ollama auto-start
(Phase 4, ADR 0007). No real Ollama and no real process launch: the reachability
probe, the `which` lookup, the `spawn` call and `sleep` are all injected, so every
branch is covered deterministically and instantly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "engine"))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import ollama_launch as ol  # noqa: E402
from brain import Brain  # noqa: E402


class FakeClient:
    """A probe whose is_available() yields a scripted sequence (last value sticks)."""
    def __init__(self, sequence):
        self._seq = list(sequence)
        self.calls = 0

    def is_available(self) -> bool:
        self.calls += 1
        if len(self._seq) > 1:
            return self._seq.pop(0)
        return self._seq[0]


def _no_sleep(_seconds):  # never actually wait in tests
    pass


def _clear_env():
    """The full suite may set the kill switch; branch tests need it OFF."""
    os.environ.pop(ol.ENV_DISABLE, None)


def test_already_running():
    _clear_env()
    spawned = []
    res = ol.ensure_running(
        FakeClient([True]),
        which=lambda: "/usr/bin/ollama",
        spawn=lambda exe: spawned.append(exe),
        sleep=_no_sleep,
    )
    assert res["status"] == ol.STATUS_ALREADY_RUNNING, res
    assert res["launched"] is False
    assert spawned == [], "must not launch when already running"
    print("PASS already_running")


def test_not_installed():
    _clear_env()
    spawned = []
    res = ol.ensure_running(
        FakeClient([False]),
        which=lambda: None,  # ollama not on PATH
        spawn=lambda exe: spawned.append(exe),
        sleep=_no_sleep,
    )
    assert res["status"] == ol.STATUS_NOT_INSTALLED, res
    assert res["launched"] is False
    assert spawned == [], "must not launch when not installed"
    print("PASS not_installed")


def test_started_after_launch():
    _clear_env()
    spawned = []
    # down on the first probe, then comes up after we launch it.
    client = FakeClient([False, False, True])
    res = ol.ensure_running(
        client,
        which=lambda: "/usr/bin/ollama",
        spawn=lambda exe: spawned.append(exe),
        sleep=_no_sleep,
        wait_seconds=5.0,
        poll_interval=0.01,
    )
    assert res["status"] == ol.STATUS_STARTED, res
    assert res["launched"] is True
    assert spawned == ["/usr/bin/ollama"], "must launch exactly once"
    print("PASS started_after_launch")


def test_timeout():
    _clear_env()
    spawned = []
    res = ol.ensure_running(
        FakeClient([False]),  # never comes up
        which=lambda: "/usr/bin/ollama",
        spawn=lambda exe: spawned.append(exe),
        sleep=_no_sleep,
        wait_seconds=0.05,
        poll_interval=0.01,
    )
    assert res["status"] == ol.STATUS_TIMEOUT, res
    assert res["launched"] is True
    assert spawned == ["/usr/bin/ollama"]
    print("PASS timeout")


def test_disabled_via_env():
    os.environ[ol.ENV_DISABLE] = "1"
    try:
        spawned = []
        res = ol.ensure_running(
            FakeClient([False]),
            which=lambda: "/usr/bin/ollama",
            spawn=lambda exe: spawned.append(exe),
            sleep=_no_sleep,
        )
        assert res["status"] == ol.STATUS_DISABLED, res
        assert spawned == [], "must not launch when disabled"
    finally:
        del os.environ[ol.ENV_DISABLE]
    print("PASS disabled_via_env")


def test_brain_ensure_server_safe():
    """Brain.ensure_server must never raise and returns a status dict.

    With a real OllamaClient and no server in the sandbox, the result is a
    graceful 'not reachable' outcome (not_installed/timeout/launch_failed,
    depending on the environment) - never an exception.
    """
    _clear_env()
    res = Brain().ensure_server(wait_seconds=0.05)
    assert isinstance(res, dict) and "status" in res, res
    assert res["status"] in {
        ol.STATUS_ALREADY_RUNNING, ol.STATUS_NOT_INSTALLED,
        ol.STATUS_STARTED, ol.STATUS_TIMEOUT, ol.STATUS_LAUNCH_FAILED,
        ol.STATUS_DISABLED, "skipped",
    }, res
    print("PASS brain_ensure_server_safe ->", res["status"])


if __name__ == "__main__":
    test_already_running()
    test_not_installed()
    test_started_after_launch()
    test_timeout()
    test_disabled_via_env()
    test_brain_ensure_server_safe()
    print("ALL test_ollama_launch PASSED")
