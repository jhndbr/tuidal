"""Keyboard input handler — readchar in a dedicated thread.

Captures single keypresses without blocking the main rendering loop.
Keys are placed into a queue.Queue for the main thread to consume.
"""
from __future__ import annotations

import threading
from queue import Empty, Queue

import readchar


# Map raw keys to action names (mirrors the old Textual bindings).
KEY_MAP: dict[str, str] = {
    " ": "toggle_play",
    "n": "next_track",
    "p": "prev_track",
    "=": "volume_up",
    "+": "volume_up",
    "-": "volume_down",
    "]": "seek_forward",
    "[": "seek_backward",
    "s": "toggle_shuffle",
    "r": "toggle_repeat",
    "q": "quit",
    "\r": "select",
    "\n": "select",
    readchar.key.UP: "cursor_up",
    readchar.key.DOWN: "cursor_down",
    readchar.key.LEFT: "focus_sidebar",
    readchar.key.RIGHT: "focus_content",
    "j": "cursor_down",
    "k": "cursor_up",
    "h": "focus_sidebar",
    "l": "focus_content",
}


class InputListener:
    """Non-blocking keyboard listener running in a daemon thread.

    Usage::

        listener = InputListener()
        listener.start()

        # In your main loop:
        for action in listener.drain():
            handle(action)

        listener.stop()
    """

    def __init__(self) -> None:
        self._queue: Queue[str] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the input listener thread."""
        self._thread = threading.Thread(
            target=self._listen, daemon=True, name="input-listener"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._stop.set()

    def drain(self) -> list[str]:
        """Return all pending actions (non-blocking)."""
        actions: list[str] = []
        while True:
            try:
                actions.append(self._queue.get_nowait())
            except Empty:
                break
        return actions

    # -- Internal -------------------------------------------------------------

    def _listen(self) -> None:
        """Read keys in a loop until stopped."""
        while not self._stop.is_set():
            try:
                key = readchar.readkey()
                action = KEY_MAP.get(key)
                if action:
                    self._queue.put(action)
                    if action == "quit":
                        break
            except Exception:
                break
