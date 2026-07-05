"""
discovery.py - discovery file to hook the add-on and the engine together.

In the Phase 1a prototype the ENGINE is the server: it picks an ephemeral port
and generates a token. The add-on (client) must discover the port + token. It
does so by reading a small JSON file that the engine writes at startup in a known,
platform-independent location:

    ~/.freecad-agent/bridge.json

Contents: { host, port, token, pid, protocol_version, created }

Security: the token is an ephemeral secret valid only for loopback. On POSIX the
file is written with 0o600 permissions (owner only). On Windows it stays in the
user's home. The engine deletes the file on shutdown.

ARCHITECTURAL NOTE: in production the roles are reversed (the add-on starts the
engine and passes it the token; see protocol.schema.json/handshake and ADR 0002).
The bridge core is symmetric, so it supports both topologies. This discovery file
serves the prototype topology (engine started by hand, add-on attaching).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_DIR = Path.home() / ".freecad-agent"
DEFAULT_FILE = DEFAULT_DIR / "bridge.json"
HOST = "127.0.0.1"  # loopback only: no network exposure.


def generate_token() -> str:
    """Ephemeral secret token (256 bits) for the handshake."""
    return secrets.token_hex(32)


def write(port: int, token: str, protocol_version: str,
          path: Path = DEFAULT_FILE) -> Path:
    """Write the discovery file. Called by the engine at startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": HOST,
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "protocol_version": protocol_version,
        "created": time.time(),
    }
    data = json.dumps(payload, indent=2)
    # Atomic write: write to tmp and rename (avoids partial reads).
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data, encoding="utf-8")
    _harden_permissions(tmp)
    os.replace(tmp, path)
    _harden_permissions(path)  # re-apply after replace (ACLs can reset on Windows)
    return path


def _harden_permissions(path: Path) -> None:
    """
    Restrict the discovery file to the current user only (ADR 0004, security).

    The file carries the ephemeral bridge token. On POSIX we set 0o600. On Windows
    chmod is a no-op, so we best-effort use `icacls` to remove inherited ACLs and
    grant access to the current user alone, so another local user cannot read the
    token. Every step is best-effort: failures never block the engine.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if os.name == "nt":  # Windows: tighten the ACL with icacls.
        user = os.environ.get("USERNAME")
        if not user:
            return
        import subprocess
        try:
            # /inheritance:r removes inherited permissions; /grant:r grants only us.
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        except Exception:  # icacls missing / sandboxed: ignore; loopback+token remain
            pass


def read(path: Path = DEFAULT_FILE) -> Optional[dict]:
    """Read the discovery file. Returns None if missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_endpoint(path: Path = DEFAULT_FILE) -> Optional[Tuple[str, int, str]]:
    """Convenience: returns (host, port, token) or None."""
    info = read(path)
    if not info:
        return None
    try:
        return info["host"], int(info["port"]), info["token"]
    except (KeyError, ValueError, TypeError):
        return None


def remove(path: Path = DEFAULT_FILE) -> None:
    """Delete the discovery file. Called by the engine on shutdown."""
    try:
        path.unlink()
    except OSError:
        pass
