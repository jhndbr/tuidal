"""Synchronous socket client connecting the TUI to the background daemon."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from tidal_tui.models import AppState
from tidal_tui.daemon import SOCKET_PATH, PID_FILE, is_daemon_running
from tidal_tui.protocol import update_state_from_dict


class TuidalClient:
    """Connects to the tuidal daemon and synchronizes AppState."""

    def __init__(self, state: AppState):
        self.state = state
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._running = False
        self._thread: threading.Thread | None = None

    def connect_or_start_daemon(self, quality: str = "high") -> None:
        """Connect to the daemon, starting it if not running."""
        for attempt in range(2):
            if not is_daemon_running() or not SOCKET_PATH.exists():
                if attempt == 0:
                    print("Starting daemon in background...")
                log_file = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tuidal" / "daemon.log"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file, "a") as f:
                    subprocess.Popen(
                        [sys.executable, "-m", "tidal_tui", "daemon", "-d", "--quality", quality],
                        start_new_session=True,
                        stdout=f,
                        stderr=subprocess.STDOUT,
                    )
                # Wait for socket to appear
                for _ in range(20):
                    if SOCKET_PATH.exists() and is_daemon_running():
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Timeout waiting for daemon to start")

            try:
                self.sock.connect(str(SOCKET_PATH))
                break
            except ConnectionRefusedError:
                # Stale socket / dead daemon
                if SOCKET_PATH.exists():
                    SOCKET_PATH.unlink(missing_ok=True)
                if PID_FILE.exists():
                    PID_FILE.unlink(missing_ok=True)
                if attempt == 1:
                    raise RuntimeError("Failed to connect to daemon: connection refused.")
            except FileNotFoundError:
                raise RuntimeError("Daemon socket not found")

        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True, name="client-recv")
        self._thread.start()

    def disconnect(self) -> None:
        """Disconnect from daemon."""
        self._running = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        self.sock.close()

    def _listen(self) -> None:
        """Background thread to receive state updates from daemon."""
        f = self.sock.makefile("r", encoding="utf-8")
        while self._running:
            try:
                line = f.readline()
                if not line:
                    break
                msg = json.loads(line)
                if msg.get("type") == "state":
                    update_state_from_dict(self.state, msg["data"])
                elif msg.get("type") == "shutdown":
                    with self.state.lock:
                        self.state.running = False
            except Exception:
                break

    def send_action(self, action: str, args: dict | None = None) -> None:
        """Send a UI action to the daemon."""
        if not self._running:
            return
        msg = {"action": action, "args": args or {}}
        self._send_raw(msg)

    def send_search_key(self, key: str) -> None:
        """Send a search input key to the daemon."""
        if not self._running:
            return
        msg = {"search_key": key}
        self._send_raw(msg)

    def _send_raw(self, msg: dict) -> None:
        try:
            data = json.dumps(msg).encode("utf-8") + b"\n"
            self.sock.sendall(data)
        except (BrokenPipeError, OSError):
            self._running = False
