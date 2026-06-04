"""Keyboard input handler — readchar in a daemon thread.

Captures single keypresses without blocking the main rendering loop.
Keys are placed into a queue.Queue for the main thread to consume.
"""
from __future__ import annotations

import threading
from queue import Empty, Queue

import readchar


class InputListener:
    """Non-blocking keyboard listener running in a daemon thread.

    Usage::

        listener = InputListener()
        listener.start()

        # In your main loop:
        for key in listener.drain():
            handle_key(key)

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
                if key == "q":  # we still need a hard break if needed, but let's just keep reading until stopped. Wait, 'q' might not quit if searching.
                    pass
            except Exception:
                break

