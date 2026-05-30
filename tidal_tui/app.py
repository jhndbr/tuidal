"""Main Textual application — orchestrates all TUI components.

This is the central hub that:
  - Wires up services (TidalService, PlayerBackend) with widgets
  - Routes events between components
  - Manages background workers for network/audio operations
  - Handles keybindings for playback control
"""
from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from tidal_tui.models import QueueState, RepeatMode
from tidal_tui.services.player_backend import PlayerBackend
from tidal_tui.services.tidal_service import TidalService
from tidal_tui.widgets.now_playing import NowPlaying
from tidal_tui.widgets.playlist_browser import PlaylistBrowser
from tidal_tui.widgets.track_list import TrackList


class TidalTUI(App):
    """Terminal UI music player for Tidal.

    Layout::

        ┌──────────────────────────────────────────────┐
        │ Header                                       │
        ├────────────┬─────────────────────────────────┤
        │ Playlists  │ Track List (DataTable)           │
        │ (sidebar)  │                                  │
        ├────────────┴─────────────────────────────────┤
        │ Now Playing (progress + controls)             │
        ├──────────────────────────────────────────────┤
        │ Footer (keybindings)                          │
        └──────────────────────────────────────────────┘
    """

    CSS_PATH = "styles/player.tcss"
    TITLE = "Tidal TUI"
    SUB_TITLE = "Terminal Music Player"

    BINDINGS = [
        Binding("space", "toggle_play", "Play/Pause", priority=True),
        Binding("n", "next_track", "Next"),
        Binding("p", "prev_track", "Prev"),
        Binding("equal", "volume_up", "Vol+", show=False),
        Binding("plus", "volume_up", "Vol+", show=False),
        Binding("minus", "volume_down", "Vol-", show=False),
        Binding("bracketright", "seek_forward", "→ 10s", show=False),
        Binding("bracketleft", "seek_backward", "← 10s", show=False),
        Binding("s", "toggle_shuffle", "Shuffle"),
        Binding("r", "toggle_repeat", "Repeat"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, tidal_service: TidalService, quality: str = "high") -> None:
        super().__init__()
        self.tidal = tidal_service
        self.player = PlayerBackend()
        self.queue = QueueState()
        self._quality = quality

    # -- Layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            yield PlaylistBrowser(id="sidebar")
            yield TrackList(id="content")
        yield NowPlaying(id="now-playing-bar")
        yield Footer()

    # -- Lifecycle ------------------------------------------------------------

    def on_mount(self) -> None:
        """Wire up player callbacks and kick off playlist loading."""
        # mpv callbacks fire in mpv's thread → use call_from_thread
        self.player.on_time_change(
            lambda pos: self.call_from_thread(self._update_position, pos)
        )
        self.player.on_duration_change(
            lambda dur: self.call_from_thread(self._update_duration, dur)
        )
        self.player.on_track_end(
            lambda: self.call_from_thread(self._on_track_ended)
        )

        # Initial volume
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.volume_level = int(self.player.volume)

        # Start loading playlists
        self._load_playlists()

    # -- UI update helpers (run on Textual thread) ----------------------------

    def _update_position(self, position: float) -> None:
        try:
            np = self.query_one("#now-playing-bar", NowPlaying)
            np.position = position
        except Exception:
            pass

    def _update_duration(self, duration: float) -> None:
        try:
            np = self.query_one("#now-playing-bar", NowPlaying)
            np.duration = duration
        except Exception:
            pass

    def _on_track_ended(self) -> None:
        """Auto-advance to the next track."""
        self.action_next_track()

    # -- Background workers ---------------------------------------------------

    @work(thread=True, exclusive=True)
    def _load_playlists(self) -> None:
        """Fetch playlists from Tidal (runs in background thread)."""
        try:
            playlists = self.tidal.get_playlists()
            self.call_from_thread(self._display_playlists, playlists)
        except Exception as exc:
            self.call_from_thread(
                self.notify,
                f"Error loading playlists: {exc}",
                severity="error",
            )

    def _display_playlists(self, playlists) -> None:
        browser = self.query_one("#sidebar", PlaylistBrowser)
        browser.load_playlists(playlists)
        if playlists:
            self.notify(f"Loaded {len(playlists)} playlists", timeout=3)

    @work(thread=True, exclusive=True)
    def _load_tracks(self, playlist_id: str, playlist_name: str) -> None:
        """Fetch tracks for a playlist (runs in background thread)."""
        self.call_from_thread(
            self.notify, f"Loading {playlist_name}...", timeout=2
        )
        try:
            tracks = self.tidal.get_playlist_tracks(playlist_id)
            self.call_from_thread(
                self._display_tracks, tracks, playlist_name
            )
        except Exception as exc:
            self.call_from_thread(
                self.notify,
                f"Error loading tracks: {exc}",
                severity="error",
            )

    def _display_tracks(self, tracks, playlist_name: str) -> None:
        track_list = self.query_one("#content", TrackList)
        track_list.load_tracks(tracks, playlist_name)
        self.queue.set_tracks(tracks)

    @work(thread=True, exclusive=True)
    def _play_track_at(self, index: int) -> None:
        """Resolve stream URL and start playback (background thread)."""
        track = self.queue.select(index)
        if not track:
            return

        # Show loading state
        self.call_from_thread(self._set_loading_state, track)

        try:
            url = self.tidal.resolve_stream_url(track.id)
            if url:
                self.player.play(url)
                self.call_from_thread(self._set_playing_state, track)
            else:
                self.call_from_thread(
                    self.notify,
                    f"Could not resolve stream: {track.title}",
                    severity="error",
                )
        except Exception as exc:
            self.call_from_thread(
                self.notify,
                f"Playback error: {exc}",
                severity="error",
            )

    def _set_loading_state(self, track) -> None:
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.track_title = f"Loading… {track.display_label}"
        np.is_paused = False
        tl = self.query_one("#content", TrackList)
        tl.set_playing(track.id)

    def _set_playing_state(self, track) -> None:
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.track_title = track.display_label
        np.position = 0.0
        np.duration = track.duration_seconds
        np.is_paused = False

    # -- Event handlers (messages from widgets) -------------------------------

    def on_playlist_browser_playlist_selected(
        self, event: PlaylistBrowser.PlaylistSelected
    ) -> None:
        """User picked a playlist → load its tracks."""
        self._load_tracks(event.playlist_id, event.playlist_name)

    def on_track_list_track_selected(
        self, event: TrackList.TrackSelected
    ) -> None:
        """User picked a track → resolve URL and play."""
        for i, t in enumerate(self.queue.tracks):
            if t.id == event.track_id:
                self._play_track_at(i)
                break

    # -- Actions (bound to keys) ----------------------------------------------

    def action_toggle_play(self) -> None:
        if self.queue.current_track is None:
            return
        self.player.toggle_pause()
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.is_paused = self.player.paused

    def action_next_track(self) -> None:
        nxt = self.queue.next_index
        if nxt is not None:
            self._play_track_at(nxt)
        else:
            self.player.stop()
            np = self.query_one("#now-playing-bar", NowPlaying)
            np.track_title = "Queue finished"
            np.is_paused = True

    def action_prev_track(self) -> None:
        prev = self.queue.prev_index
        if prev is not None:
            self._play_track_at(prev)

    def action_volume_up(self) -> None:
        self.player.volume = min(150, self.player.volume + 5)
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.volume_level = int(self.player.volume)

    def action_volume_down(self) -> None:
        self.player.volume = max(0, self.player.volume - 5)
        np = self.query_one("#now-playing-bar", NowPlaying)
        np.volume_level = int(self.player.volume)

    def action_seek_forward(self) -> None:
        self.player.seek(10, relative=True)

    def action_seek_backward(self) -> None:
        self.player.seek(-10, relative=True)

    def action_toggle_shuffle(self) -> None:
        enabled = self.queue.toggle_shuffle()
        self.notify(f"Shuffle: {'on' if enabled else 'off'}", timeout=2)

    def action_toggle_repeat(self) -> None:
        mode = self.queue.toggle_repeat()
        labels = {
            RepeatMode.OFF: "off",
            RepeatMode.ALL: "all",
            RepeatMode.ONE: "one",
        }
        self.notify(f"Repeat: {labels[mode]}", timeout=2)

    def action_quit_app(self) -> None:
        """Clean shutdown: stop mpv, then exit."""
        self.player.shutdown()
        self.exit()
