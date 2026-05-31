"""Main CLI application — Rich Live loop with keyboard input.

Replaces the Textual App with a Rich-based fullscreen interface
that uses the terminal's native ANSI color palette.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from rich.live import Live

from tidal_tui.input import InputListener
from tidal_tui.models import QueueState, RepeatMode
from tidal_tui.services.player_backend import PlayerBackend
from tidal_tui.services.tidal_service import TidalService
from tidal_tui.theme import console
from tidal_tui.ui.layout import build_layout


@dataclass
class AppState:
    """Shared application state — updated by main loop, mpv callbacks, and loaders.

    All mutations should be done under the lock when accessed from
    multiple threads (mpv callbacks, network loaders, main loop).
    """

    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- Playlists
    playlists: list = field(default_factory=list)
    playlist_name: str = ""
    playlist_cursor: int = 0

    # -- Tracks
    tracks: list = field(default_factory=list)
    track_cursor: int = 0
    playing_id: str | None = None

    # -- Playback
    track_title: str = "No track playing"
    position: float = 0.0
    duration: float = 0.0
    volume: int = 75
    is_paused: bool = True

    # -- Queue state
    shuffle: bool = False
    repeat: RepeatMode = RepeatMode.OFF

    # -- UI focus
    active_panel: str = "sidebar"  # "sidebar" or "content"

    # -- App control
    running: bool = True
    status_message: str = ""

    @property
    def repeat_label(self) -> str:
        """Human-readable repeat mode."""
        return {
            RepeatMode.OFF: "off",
            RepeatMode.ALL: "all",
            RepeatMode.ONE: "one",
        }[self.repeat]


class TidalCLI:
    """Rich-based CLI music player for Tidal.

    Runs a Rich Live display with keyboard input from a separate thread.
    All rendering uses ANSI colors that inherit the terminal's palette.
    """

    def __init__(self, tidal_service: TidalService, quality: str = "high") -> None:
        self.tidal = tidal_service
        self.player = PlayerBackend()
        self.queue = QueueState()
        self.state = AppState()
        self.input = InputListener()
        self._quality = quality

    # -- Main entry point -----------------------------------------------------

    def run(self) -> None:
        """Start the application."""
        self._setup_player_callbacks()
        self._load_playlists_async()
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
                    for action in self.input.drain():
                        self._handle_action(action)

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

    # -- Player callbacks (run in mpv thread) ---------------------------------

    def _setup_player_callbacks(self) -> None:
        """Wire up mpv callbacks to update shared state."""
        self.player.on_time_change(self._on_time_change)
        self.player.on_duration_change(self._on_duration_change)
        self.player.on_track_end(self._on_track_end)
        self.state.volume = int(self.player.volume)

    def _on_time_change(self, position: float) -> None:
        with self.state.lock:
            self.state.position = position

    def _on_duration_change(self, duration: float) -> None:
        with self.state.lock:
            self.state.duration = duration

    def _on_track_end(self) -> None:
        self._action_next_track()

    # -- Network loaders (background threads) ---------------------------------

    def _load_playlists_async(self) -> None:
        """Load playlists from Tidal in a background thread."""

        def loader():
            try:
                playlists = self.tidal.get_playlists()
                with self.state.lock:
                    self.state.playlists = playlists
                    self.state.status_message = f"Loaded {len(playlists)} playlists"
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"

        threading.Thread(target=loader, daemon=True, name="playlist-loader").start()

    def _load_tracks_async(self, playlist_id: str, playlist_name: str) -> None:
        """Load tracks for a playlist in a background thread."""
        with self.state.lock:
            self.state.status_message = f"Loading {playlist_name}..."

        def loader():
            try:
                tracks = self.tidal.get_playlist_tracks(playlist_id)
                with self.state.lock:
                    self.state.tracks = tracks
                    self.state.track_cursor = 0
                    self.state.playlist_name = playlist_name
                    self.state.status_message = ""
                self.queue.set_tracks(tracks)
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"

        threading.Thread(target=loader, daemon=True, name="track-loader").start()

    # -- Action dispatcher ----------------------------------------------------

    def _handle_action(self, action: str) -> None:
        """Dispatch a keyboard action to the appropriate handler."""
        handlers = {
            "toggle_play": self._action_toggle_play,
            "next_track": self._action_next_track,
            "prev_track": self._action_prev_track,
            "volume_up": self._action_volume_up,
            "volume_down": self._action_volume_down,
            "seek_forward": self._action_seek_forward,
            "seek_backward": self._action_seek_backward,
            "toggle_shuffle": self._action_toggle_shuffle,
            "toggle_repeat": self._action_toggle_repeat,
            "quit": self._action_quit,
            "select": self._action_select,
            "cursor_up": self._action_cursor_up,
            "cursor_down": self._action_cursor_down,
            "focus_sidebar": self._action_focus_sidebar,
            "focus_content": self._action_focus_content,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    # -- Playback actions -----------------------------------------------------

    def _action_toggle_play(self) -> None:
        if self.queue.current_track is None:
            return
        self.player.toggle_pause()
        with self.state.lock:
            self.state.is_paused = self.player.paused

    def _action_next_track(self) -> None:
        nxt = self.queue.next_index
        if nxt is not None:
            self._play_track_at(nxt)
        else:
            self.player.stop()
            with self.state.lock:
                self.state.track_title = "Queue finished"
                self.state.is_paused = True

    def _action_prev_track(self) -> None:
        prev = self.queue.prev_index
        if prev is not None:
            self._play_track_at(prev)

    def _action_volume_up(self) -> None:
        self.player.volume = min(150, self.player.volume + 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)

    def _action_volume_down(self) -> None:
        self.player.volume = max(0, self.player.volume - 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)

    def _action_seek_forward(self) -> None:
        self.player.seek(10, relative=True)

    def _action_seek_backward(self) -> None:
        self.player.seek(-10, relative=True)

    def _action_toggle_shuffle(self) -> None:
        enabled = self.queue.toggle_shuffle()
        with self.state.lock:
            self.state.shuffle = enabled

    def _action_toggle_repeat(self) -> None:
        mode = self.queue.toggle_repeat()
        with self.state.lock:
            self.state.repeat = mode

    # -- Navigation actions ---------------------------------------------------

    def _action_cursor_up(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                self.state.playlist_cursor = max(0, self.state.playlist_cursor - 1)
            else:
                self.state.track_cursor = max(0, self.state.track_cursor - 1)

    def _action_cursor_down(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                max_idx = max(0, len(self.state.playlists) - 1)
                self.state.playlist_cursor = min(
                    max_idx, self.state.playlist_cursor + 1
                )
            else:
                max_idx = max(0, len(self.state.tracks) - 1)
                self.state.track_cursor = min(max_idx, self.state.track_cursor + 1)

    def _action_focus_sidebar(self) -> None:
        with self.state.lock:
            self.state.active_panel = "sidebar"

    def _action_focus_content(self) -> None:
        with self.state.lock:
            self.state.active_panel = "content"

    def _action_select(self) -> None:
        playlist_to_load: tuple[str, str] | None = None
        track_index: int | None = None
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                if self.state.playlists and self.state.playlist_cursor < len(
                    self.state.playlists
                ):
                    pl = self.state.playlists[self.state.playlist_cursor]
                    playlist_to_load = (pl.id, pl.name)
                    self.state.active_panel = "content"
            else:
                if self.state.tracks and self.state.track_cursor < len(
                    self.state.tracks
                ):
                    track_index = self.state.track_cursor

        if playlist_to_load:
            self._load_tracks_async(*playlist_to_load)
        elif track_index is not None:
            self._play_track_at(track_index)

    def _action_quit(self) -> None:
        self.state.running = False

    # -- Track playback -------------------------------------------------------

    def _play_track_at(self, index: int) -> None:
        """Resolve stream URL and start playback."""
        track = self.queue.select(index)
        if not track:
            return

        with self.state.lock:
            self.state.track_title = f"Loading… {track.display_label}"
            self.state.playing_id = track.id
            self.state.is_paused = False
            self.state.position = 0.0
            self.state.duration = track.duration_seconds

        def resolver():
            try:
                url = self.tidal.resolve_stream_url(track.id)
                if url:
                    self.player.play(url)
                    with self.state.lock:
                        self.state.track_title = track.display_label
                        self.state.is_paused = False
                else:
                    with self.state.lock:
                        self.state.track_title = f"Error: {track.title}"
                        self.state.is_paused = True
            except Exception:
                with self.state.lock:
                    self.state.track_title = f"Error: {track.title}"
                    self.state.is_paused = True

        threading.Thread(target=resolver, daemon=True, name="stream-resolver").start()

    # -- Lifecycle ------------------------------------------------------------

    def _shutdown(self) -> None:
        """Clean up resources."""
        self.input.stop()
        self.player.shutdown()
