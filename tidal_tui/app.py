"""Main CLI application — Rich Live loop with keyboard input.

Replaces the Textual App with a Rich-based fullscreen interface
that uses the terminal's native ANSI color palette.
"""

from __future__ import annotations

import os
import time

import readchar
from rich.live import Live

from tidal_tui.client import TuidalClient
from tidal_tui.input import InputListener
from tidal_tui.models import AlbumInfo, AppState, ArtistInfo, RepeatMode, SearchType
from tidal_tui.theme import console
from tidal_tui.ui.layout import build_layout


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
    "/": "toggle_search",
    "f": "toggle_favorite",
    "R": "retry_playlists",
}





class TidalCLI:
    """Rich-based CLI music player for Tidal.

    Connects to the background daemon via TuidalClient to retrieve
    state and send commands, acting purely as a TUI.
    """

    def __init__(self, quality: str = "high") -> None:
        self.state = AppState()
        self.input = InputListener()
        self.client = TuidalClient(self.state)
        self._quality = quality

    # -- Main entry point -----------------------------------------------------

    def run(self) -> None:
        """Start the application."""
        self.client.connect_or_start_daemon(self._quality)
        self.input.start()

        try:
            term_size = os.get_terminal_size()
            term_height = term_size.lines
        except OSError:
            term_height = 24

        try:
            with Live(
                build_layout(self.state, term_height),
                console=console,
                refresh_per_second=10,
                screen=True,
                vertical_overflow="crop",
            ) as live:
                while self.state.running:
                    # Process keyboard input
                    for key in self.input.drain():
                        self._handle_key(key)

                    # Update terminal size
                    try:
                        term_size = os.get_terminal_size()
                        term_height = term_size.lines
                    except OSError:
                        pass

                    # Render
                    live.update(build_layout(self.state, term_height))
                    time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _handle_key(self, key: str) -> None:
        """Handle a raw keyboard input."""
        with self.state.lock:
            mode = self.state.input_mode

        if mode == "search":
            self.client.send_search_key(key)
        else:
            action = KEY_MAP.get(key)
            if action:
                if action == "quit":
                    self.state.running = False
                else:
                    self.client.send_action(action)

    def _shutdown(self) -> None:
        """Clean up resources."""
        self.input.stop()
        self.client.disconnect()
