"""Keyboard input handler — readchar in a daemon thread.

Captures single keypresses without blocking the main rendering loop.
Keys are placed into a queue.Queue for the main thread to consume.
The caller can pass a threading.Event that gets set on every keypress
so the render loop wakes up immediately without polling.
"""
from __future__ import annotations

import threading
from queue import Empty, Queue
from typing import Optional

import readchar


class InputListener:
    """Non-blocking keyboard listener running in a daemon thread.

    Usage::

        listener = InputListener(render_event)
        listener.start()

        # In your main loop:
        for key in listener.drain():
            handle_key(key)

        listener.stop()
    """

    def __init__(self, render_event: Optional[threading.Event] = None) -> None:
        self._queue: Queue[str] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._render_event = render_event

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
        """Return all pending keys (non-blocking)."""
        keys: list[str] = []
        while True:
            try:
                keys.append(self._queue.get_nowait())
            except Empty:
                break
        return keys

    # -- Internal -------------------------------------------------------------

    def _listen(self) -> None:
        """Read keys in a loop until stopped."""
        while not self._stop.is_set():
            try:
                key = readchar.readkey()
                self._queue.put(key)
                # Wake the render loop immediately on every keypress
                if self._render_event is not None:
                    self._render_event.set()
            except Exception:
                break

