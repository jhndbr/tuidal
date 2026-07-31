"""Main CLI application — Rich Live loop with keyboard input.

Replaces the Textual App with a Rich-based fullscreen interface
that uses the terminal's native ANSI color palette.

Key improvements over v1:
- Event-driven rendering: re-renders only on input/state-change, not every 50ms.
- Race-condition fix: stale URL resolvers are discarded before playback.
- Config persistence: volume is saved to disk on every change.
- Gapless playback: next track is pre-fetched 10 s before the current one ends.
- Advanced navigation: Page Up/Down (×10), Home, End.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import readchar
from rich.live import Live
from rich.text import Text

from tidal_tui.art_renderer import render_art
from tidal_tui.config import AppConfig
from tidal_tui.input import InputListener
from tidal_tui.models import AlbumInfo, ArtistInfo, QueueState, RepeatMode, SearchType
from tidal_tui.services.player_backend import PlayerBackend
from tidal_tui.services.tidal_service import TidalService
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
    readchar.key.PAGE_UP: "page_up",
    readchar.key.PAGE_DOWN: "page_down",
    readchar.key.HOME: "go_home",
    readchar.key.END: "go_end",
    "j": "cursor_down",
    "k": "cursor_up",
    "h": "focus_sidebar",
    "l": "focus_content",
    "/": "toggle_search",
    "f": "toggle_favorite",
    "R": "retry_playlists",
}

# How many items to skip when pressing Page Up/Down
_PAGE_SIZE = 10

# How many seconds before track end to begin preloading the next track
_GAPLESS_PRELOAD_SECONDS = 10.0

# Album art dimensions (must match sidebar content width)
_ART_WIDTH = 26
_ART_HEIGHT = 12
# Only show art when terminal is tall enough to fit both playlists and art
_MIN_TERM_FOR_ART = 30


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
    loading_playlist_id: str = ""
    sidebar_error: str = ""  # error message shown in sidebar

    # -- Tracks
    tracks: list = field(default_factory=list)
    track_cursor: int = 0
    playing_id: str | None = None
    favorite_track_ids: set[str] = field(default_factory=set)

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
    input_mode: str = "normal"  # "normal" or "search"
    search_query: str = ""
    search_type: SearchType = SearchType.ALL

    # -- Search results (artists/albums shown as browseable lists)
    search_results_artists: list = field(default_factory=list)
    search_results_albums: list = field(default_factory=list)
    search_results_mode: str = ""  # "tracks", "artists", "albums", or "" for normal

    # -- App control
    running: bool = True
    status_message: str = ""

    # -- Album art
    art_url: str | None = None      # URL of the current track's cover image
    art_text: Text | None = None    # Rendered art (set asynchronously)

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

    def __init__(
        self,
        tidal_service: TidalService,
        quality: str = "high",
        config: AppConfig | None = None,
    ) -> None:
        self.tidal = tidal_service
        self.player = PlayerBackend()
        self.queue = QueueState()
        self.state = AppState()
        self._render_event: threading.Event = threading.Event()
        self.input = InputListener(render_event=self._render_event)
        self._quality = quality
        self._config = config or AppConfig()

        # Timestamp of the last position-change render trigger (throttle to 1/s)
        self._last_position_render: float = 0.0

        # Flag: True once we have started pre-loading the next gapless track
        # so we don't trigger multiple concurrent preloads for the same track.
        self._gapless_preloading: bool = False
        self._preloaded_track = None

        # Apply saved volume from config
        self.state.volume = self._config.volume

    # -- Main entry point -----------------------------------------------------

    def run(self) -> None:
        """Start the application."""
        self._setup_player_callbacks()
        self._load_playlists_async()
        self.input.start()

        # Apply saved volume to mpv immediately
        self.player.volume = self.state.volume

        try:
            term_size = os.get_terminal_size()
            term_height = term_size.lines
        except OSError:
            term_height = 24

        try:
            with Live(
                build_layout(self.state, term_height),
                console=console,
                refresh_per_second=4,   # Fallback: still refresh 4× per second as a safety net
                screen=True,
                vertical_overflow="crop",
            ) as live:
                while self.state.running:
                    # Block until there's something to render (or timeout safety net)
                    self._render_event.wait(timeout=0.1)
                    self._render_event.clear()

                    # Process all pending keyboard input
                    keys = self.input.drain()
                    for key in keys:
                        self._handle_key(key)

                    # Update terminal size
                    try:
                        term_size = os.get_terminal_size()
                        term_height = term_size.lines
                    except OSError:
                        pass

                    # Render
                    live.update(build_layout(self.state, term_height))

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
        self.player.on_time_remaining(self._on_time_remaining)

    def _on_time_change(self, position: float) -> None:
        with self.state.lock:
            self.state.position = position
            is_paused = self.state.is_paused

        # Throttle render triggers from position updates: max once per second,
        # and only when the track is actually playing.
        if not is_paused:
            now = time.monotonic()
            if now - self._last_position_render >= 1.0:
                self._last_position_render = now
                self._render_event.set()

    def _on_duration_change(self, duration: float) -> None:
        with self.state.lock:
            self.state.duration = duration
        self._render_event.set()

    def _on_track_end(self) -> None:
        self._gapless_preloading = False
        track = self._preloaded_track
        if track is not None:
            self._preloaded_track = None
            nxt = self.queue.next_index
            if nxt is not None:
                self.queue.current_index = nxt
            with self.state.lock:
                self.state.playing_id = track.id
                self.state.track_title = track.display_label
                self.state.duration = track.duration_seconds
                self.state.position = 0.0
                self.state.art_url = None
                self.state.art_text = None

            # Kick off art download + render in background for newly started track
            threading.Thread(
                target=self._load_art_async,
                args=(track,),
                daemon=True,
                name="art-loader",
            ).start()
            self._notify_render()
        else:
            self._action_next_track()

    def _on_time_remaining(self, remaining: float) -> None:
        """Triggered on every position update with seconds remaining in the track.

        When we're close to the end, preload the next track URL into mpv's
        internal playlist so playback is seamless (gapless).
        """
        if remaining > _GAPLESS_PRELOAD_SECONDS:
            return
        if self._gapless_preloading or self.player._gapless_queued:
            return
        if self.queue.next_track is None:
            return
        # Don't preload if already paused/stopped
        with self.state.lock:
            is_paused = self.state.is_paused
        if is_paused:
            return

        self._gapless_preloading = True
        next_track = self.queue.next_track
        threading.Thread(
            target=self._preload_next_track,
            args=(next_track,),
            daemon=True,
            name="gapless-preloader",
        ).start()

    def _preload_next_track(self, track) -> None:
        """Resolve the next track's URL and append it to mpv for gapless play."""
        try:
            url = self.tidal.resolve_stream_url(track.id)
            if url:
                self.player.append_to_queue(url)
                self._preloaded_track = track
        except Exception:
            pass
        finally:
            self._gapless_preloading = False

    # -- Network loaders (background threads) ---------------------------------

    def _notify_render(self) -> None:
        """Signal the render loop that something changed."""
        self._render_event.set()

    def _load_playlists_async(self) -> None:
        """Load playlists from Tidal in a background thread."""

        def loader():
            try:
                from tidal_tui.models import PlaylistInfo

                loaded_playlists: list = []

                # Fetch just the favorites COUNT with a single lightweight request
                # so the sidebar shows the correct number without downloading all tracks.
                fav_count = 0
                try:
                    favs = getattr(self.tidal.session.user, "favorites", None)
                    if favs and hasattr(favs, "get_tracks_count"):
                        fav_count = favs.get_tracks_count()
                except Exception:
                    fav_count = 0

                # Fetch playlists (non-fatal if it fails)
                playlists_error = ""
                try:
                    loaded_playlists = self.tidal.get_playlists()
                except Exception as exc:
                    playlists_error = str(exc)

                # Build the final list — always add favorites entry at the top
                final: list = []
                fav_playlist = PlaylistInfo(
                    id="__favorites__",
                    name="♥ Favoritas",
                    num_tracks=fav_count,
                    description="Tus canciones favoritas",
                )
                final.append(fav_playlist)
                final.extend(loaded_playlists)

                with self.state.lock:
                    self.state.playlists = final
                    self.state.favorite_track_ids = set()  # populated below in background
                    if final:
                        self.state.sidebar_error = ""
                        self.state.status_message = f"Loaded {len(loaded_playlists)} playlists"
                    elif playlists_error:
                        self.state.sidebar_error = playlists_error
                        self.state.status_message = "Error loading playlists (/ to search)"
                    else:
                        self.state.sidebar_error = ""
                        self.state.status_message = "No playlists found"

                # Populate favorite_track_ids in background (cache-first — usually instant)
                def _load_fav_ids():
                    try:
                        fav_tracks = self.tidal.get_favorite_tracks()
                        with self.state.lock:
                            self.state.favorite_track_ids = {t.id for t in fav_tracks}
                            # Also update the num_tracks counter now we have the real total
                            for pl in self.state.playlists:
                                if pl.id == "__favorites__":
                                    pl.num_tracks = len(fav_tracks)
                                    break
                        self._notify_render()
                    except Exception:
                        pass

                threading.Thread(target=_load_fav_ids, daemon=True, name="fav-ids-loader").start()

            except Exception as exc:
                with self.state.lock:
                    self.state.sidebar_error = str(exc)
                    self.state.status_message = "Error loading playlists (/ to search)"
            finally:
                self._notify_render()

        threading.Thread(target=loader, daemon=True, name="playlist-loader").start()

    def _load_tracks_async(self, playlist_id: str, playlist_name: str) -> None:
        """Load tracks for a playlist in a background thread."""
        with self.state.lock:
            self.state.loading_playlist_id = playlist_id
            self.state.status_message = f"Loading {playlist_name}..."
        self._notify_render()

        def loader():
            try:
                if playlist_id == "__favorites__":
                    loaded_tracks = []

                    def on_chunk(chunk: list) -> bool:
                        with self.state.lock:
                            still_current = (self.state.loading_playlist_id == playlist_id)
                        if not still_current:
                            return False  # Abort fetching

                        loaded_tracks.extend(chunk)
                        with self.state.lock:
                            self.state.tracks = list(loaded_tracks)
                            self.state.playlist_name = playlist_name
                            self.state.search_results_mode = ""
                            self.state.search_results_artists = []
                            self.state.search_results_albums = []
                            self.state.status_message = f"Loaded {len(loaded_tracks)} favorites..."
                        self.queue.set_tracks(list(loaded_tracks))
                        self._notify_render()
                        return True

                    self.tidal.get_favorite_tracks_incremental(on_chunk)

                    with self.state.lock:
                        if self.state.loading_playlist_id == playlist_id:
                            self.state.status_message = ""
                    self._notify_render()
                else:
                    tracks = self.tidal.get_playlist_tracks(playlist_id)
                    with self.state.lock:
                        if self.state.loading_playlist_id == playlist_id:
                            self.state.tracks = tracks
                            self.state.track_cursor = 0
                            self.state.playlist_name = playlist_name
                            self.state.search_results_mode = ""
                            self.state.search_results_artists = []
                            self.state.search_results_albums = []
                            self.state.status_message = ""
                    self.queue.set_tracks(tracks)
            except Exception as exc:
                with self.state.lock:
                    if self.state.loading_playlist_id == playlist_id:
                        self.state.status_message = f"Error: {exc}"
            finally:
                self._notify_render()

        threading.Thread(target=loader, daemon=True, name="track-loader").start()

    def _search_async(self, query: str, search_type: SearchType = SearchType.ALL) -> None:
        """Execute a search in a background thread."""
        with self.state.lock:
            type_label = search_type.value
            self.state.status_message = f"Searching {type_label}: '{query}'..."
        self._notify_render()

        def loader():
            try:
                if search_type == SearchType.TRACKS:
                    tracks = self.tidal.search_tracks(query)
                    with self.state.lock:
                        self.state.tracks = tracks
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"🔍 Tracks: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "tracks"
                        self.state.search_results_artists = []
                        self.state.search_results_albums = []
                        self.state.status_message = ""
                    self.queue.set_tracks(tracks)

                elif search_type == SearchType.ARTISTS:
                    artists = self.tidal.search_artists(query)
                    with self.state.lock:
                        self.state.tracks = []
                        self.state.search_results_artists = artists
                        self.state.search_results_albums = []
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"🎤 Artists: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "artists"
                        self.state.status_message = ""

                elif search_type == SearchType.ALBUMS:
                    albums = self.tidal.search_albums(query)
                    with self.state.lock:
                        self.state.tracks = []
                        self.state.search_results_artists = []
                        self.state.search_results_albums = albums
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"💿 Albums: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "albums"
                        self.state.status_message = ""

                else:  # ALL
                    results = self.tidal.search_all(query)
                    tracks = results["tracks"]
                    artists = results["artists"]
                    albums = results["albums"]
                    with self.state.lock:
                        self.state.tracks = tracks
                        self.state.search_results_artists = artists
                        self.state.search_results_albums = albums
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"🔍 All: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "all"
                        self.state.status_message = ""
                    self.queue.set_tracks(tracks)

            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            finally:
                self._notify_render()

        threading.Thread(target=loader, daemon=True, name="search-loader").start()

    def _load_artist_tracks_async(self, artist_id: str, artist_name: str) -> None:
        """Load top tracks for an artist in a background thread."""
        with self.state.lock:
            self.state.status_message = f"Loading tracks for {artist_name}..."
        self._notify_render()

        def loader():
            try:
                tracks = self.tidal.get_artist_top_tracks(artist_id)
                with self.state.lock:
                    self.state.tracks = tracks
                    self.state.track_cursor = 0
                    self.state.playlist_name = f"🎤 {artist_name}"
                    self.state.search_results_mode = "tracks"
                    self.state.search_results_artists = []
                    self.state.search_results_albums = []
                    self.state.status_message = ""
                self.queue.set_tracks(tracks)
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            finally:
                self._notify_render()

        threading.Thread(target=loader, daemon=True, name="artist-loader").start()

    def _load_album_tracks_async(self, album_id: str, album_name: str) -> None:
        """Load tracks from an album in a background thread."""
        with self.state.lock:
            self.state.status_message = f"Loading {album_name}..."
        self._notify_render()

        def loader():
            try:
                tracks = self.tidal.get_album_tracks(album_id)
                with self.state.lock:
                    self.state.tracks = tracks
                    self.state.track_cursor = 0
                    self.state.playlist_name = f"💿 {album_name}"
                    self.state.search_results_mode = "tracks"
                    self.state.search_results_artists = []
                    self.state.search_results_albums = []
                    self.state.status_message = ""
                self.queue.set_tracks(tracks)
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            finally:
                self._notify_render()

        threading.Thread(target=loader, daemon=True, name="album-loader").start()

    # -- Action dispatcher ----------------------------------------------------

    def _handle_key(self, key: str) -> None:
        """Handle a raw keyboard input."""
        with self.state.lock:
            mode = self.state.input_mode

        if mode == "search":
            self._handle_search_key(key)
        else:
            action = KEY_MAP.get(key)
            if action:
                self._handle_action(action)

        # No need to call _notify_render() here: the main loop renders
        # unconditionally after draining all keys in each cycle.

    def _handle_search_key(self, key: str) -> None:
        """Process keys while in search mode.

        Tab cycles the search type: ALL → TRACKS → ARTISTS → ALBUMS → ALL.
        """
        if key == readchar.key.ESC:
            with self.state.lock:
                self.state.input_mode = "normal"
                self.state.search_query = ""
            return

        # Tab cycles through search types
        if key == "\t":
            cycle = [SearchType.ALL, SearchType.TRACKS, SearchType.ARTISTS, SearchType.ALBUMS]
            with self.state.lock:
                idx = cycle.index(self.state.search_type)
                self.state.search_type = cycle[(idx + 1) % len(cycle)]
            return

        if key in ("\r", "\n", readchar.key.ENTER):
            with self.state.lock:
                query = self.state.search_query
                search_type = self.state.search_type
                self.state.input_mode = "normal"
            if query.strip():
                self._search_async(query.strip(), search_type)
            return

        if key in (readchar.key.BACKSPACE, "\x7f", "\x08"):
            with self.state.lock:
                self.state.search_query = self.state.search_query[:-1]
            return

        # Only accept printable characters (crude check, but works for most TUI)
        if len(key) == 1 and key.isprintable():
            with self.state.lock:
                self.state.search_query += key

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
            "toggle_search": self._action_toggle_search,
            "toggle_favorite": self._action_toggle_favorite,
            "retry_playlists": self._action_retry_playlists,
            "page_up": self._action_page_up,
            "page_down": self._action_page_down,
            "go_home": self._action_go_home,
            "go_end": self._action_go_end,
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
            self._play_track_by_order_index(nxt)
        else:
            self.player.stop()
            with self.state.lock:
                self.state.track_title = "Queue finished"
                self.state.is_paused = True
        self._notify_render()

    def _action_prev_track(self) -> None:
        prev = self.queue.prev_index
        if prev is not None:
            self._play_track_by_order_index(prev)

    def _action_volume_up(self) -> None:
        self.player.volume = min(150, self.player.volume + 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)
        self._save_volume()

    def _action_volume_down(self) -> None:
        self.player.volume = max(0, self.player.volume - 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)
        self._save_volume()

    def _save_volume(self) -> None:
        """Persist the current volume to config.json (non-blocking)."""
        volume = self.state.volume

        def writer():
            try:
                self._config.volume = volume
                self._config.save()
            except Exception:
                pass

        threading.Thread(target=writer, daemon=True, name="config-writer").start()

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
                max_idx = self._max_content_index()
                self.state.track_cursor = min(max_idx, self.state.track_cursor + 1)

    def _action_page_up(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                self.state.playlist_cursor = max(0, self.state.playlist_cursor - _PAGE_SIZE)
            else:
                self.state.track_cursor = max(0, self.state.track_cursor - _PAGE_SIZE)

    def _action_page_down(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                max_idx = max(0, len(self.state.playlists) - 1)
                self.state.playlist_cursor = min(max_idx, self.state.playlist_cursor + _PAGE_SIZE)
            else:
                max_idx = self._max_content_index()
                self.state.track_cursor = min(max_idx, self.state.track_cursor + _PAGE_SIZE)

    def _action_go_home(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                self.state.playlist_cursor = 0
            else:
                self.state.track_cursor = 0

    def _action_go_end(self) -> None:
        with self.state.lock:
            if self.state.active_panel == "sidebar":
                self.state.playlist_cursor = max(0, len(self.state.playlists) - 1)
            else:
                self.state.track_cursor = self._max_content_index()

    def _max_content_index(self) -> int:
        """Return the maximum valid cursor index for the content panel (must be called under lock)."""
        if self.state.search_results_mode == "artists":
            return max(0, len(self.state.search_results_artists) - 1)
        elif self.state.search_results_mode == "albums":
            return max(0, len(self.state.search_results_albums) - 1)
        elif self.state.search_results_mode == "all":
            total = (len(self.state.search_results_artists)
                     + len(self.state.search_results_albums)
                     + len(self.state.tracks))
            return max(0, total - 1)
        else:
            return max(0, len(self.state.tracks) - 1)

    def _action_focus_sidebar(self) -> None:
        with self.state.lock:
            self.state.active_panel = "sidebar"

    def _action_focus_content(self) -> None:
        with self.state.lock:
            self.state.active_panel = "content"

    def _action_toggle_search(self) -> None:
        with self.state.lock:
            self.state.input_mode = "search"
            self.state.search_query = ""
            self.state.search_type = SearchType.ALL

    def _action_retry_playlists(self) -> None:
        """Retry loading playlists after an error."""
        with self.state.lock:
            self.state.sidebar_error = ""
            self.state.playlists = []
            self.state.status_message = "Retrying..."
        self._load_playlists_async()

    def _action_toggle_favorite(self) -> None:
        track = None
        with self.state.lock:
            if self.state.active_panel == "content" and self.state.tracks and self.state.track_cursor < len(self.state.tracks):
                track = self.state.tracks[self.state.track_cursor]

        if not track:
            return

        track_id = track.id
        with self.state.lock:
            is_fav = track_id in self.state.favorite_track_ids
            new_fav = not is_fav
            if new_fav:
                self.state.favorite_track_ids.add(track_id)
                self.state.status_message = f"Added {track.title} to favorites"
            else:
                self.state.favorite_track_ids.remove(track_id)
                self.state.status_message = f"Removed {track.title} from favorites"

        def toggler():
            try:
                self.tidal.toggle_favorite(track_id, new_fav)
                # Invalidate the favorites cache so the next visit re-fetches all tracks
                self.tidal.invalidate_favorite_tracks_cache()
                # Update num_tracks counter in the sidebar for the __favorites__ playlist
                with self.state.lock:
                    for pl in self.state.playlists:
                        if pl.id == "__favorites__":
                            pl.num_tracks += 1 if new_fav else -1
                            break
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            finally:
                self._notify_render()

        threading.Thread(target=toggler, daemon=True, name="favorite-toggler").start()

    def _action_select(self) -> None:
        playlist_to_load: tuple[str, str] | None = None
        track_index: int | None = None
        artist_to_load: tuple[str, str] | None = None
        album_to_load: tuple[str, str] | None = None

        with self.state.lock:
            if self.state.active_panel == "sidebar":
                if self.state.playlists and self.state.playlist_cursor < len(
                    self.state.playlists
                ):
                    pl = self.state.playlists[self.state.playlist_cursor]
                    playlist_to_load = (pl.id, pl.name)
                    self.state.active_panel = "content"
            else:
                mode = self.state.search_results_mode
                cursor = self.state.track_cursor

                if mode == "artists":
                    if self.state.search_results_artists and cursor < len(
                        self.state.search_results_artists
                    ):
                        a = self.state.search_results_artists[cursor]
                        artist_to_load = (a.id, a.name)

                elif mode == "albums":
                    if self.state.search_results_albums and cursor < len(
                        self.state.search_results_albums
                    ):
                        a = self.state.search_results_albums[cursor]
                        album_to_load = (a.id, a.name)

                elif mode == "all":
                    # Combined list: artists, then albums, then tracks
                    n_artists = len(self.state.search_results_artists)
                    n_albums = len(self.state.search_results_albums)
                    if cursor < n_artists:
                        a = self.state.search_results_artists[cursor]
                        artist_to_load = (a.id, a.name)
                    elif cursor < n_artists + n_albums:
                        a = self.state.search_results_albums[cursor - n_artists]
                        album_to_load = (a.id, a.name)
                    else:
                        track_idx = cursor - n_artists - n_albums
                        if self.state.tracks and track_idx < len(self.state.tracks):
                            track_index = track_idx

                else:
                    if self.state.tracks and cursor < len(self.state.tracks):
                        track_index = cursor

        if playlist_to_load:
            self._load_tracks_async(*playlist_to_load)
        elif artist_to_load:
            self._load_artist_tracks_async(*artist_to_load)
        elif album_to_load:
            self._load_album_tracks_async(*album_to_load)
        elif track_index is not None:
            self._play_track_at(track_index)

    def _action_quit(self) -> None:
        self.state.running = False
        self._notify_render()

    # -- Track playback -------------------------------------------------------

    def _play_track_at(self, real_index: int) -> None:
        """Resolve stream URL and start playback by real (absolute) track index."""
        track = self.queue.select(real_index)
        if not track:
            return

        with self.state.lock:
            self.state.track_title = f"Loading… {track.display_label}"
            self.state.playing_id = track.id
            self.state.is_paused = False
            self.state.position = 0.0
            self.state.duration = track.duration_seconds
            # Clear old art immediately so the sidebar doesn't show stale art
            self.state.art_url = None
            self.state.art_text = None
        self._gapless_preloading = False
        self._preloaded_track = None
        self._notify_render()

        # Kick off art download + render in background
        threading.Thread(
            target=self._load_art_async,
            args=(track,),
            daemon=True,
            name="art-loader",
        ).start()

        def resolver():
            try:
                url = self.tidal.resolve_stream_url(track.id)
                if url:
                    # Race condition guard: only play if this track is still selected
                    with self.state.lock:
                        still_current = self.state.playing_id == track.id
                    if still_current:
                        self.player.play(url)
                        with self.state.lock:
                            self.state.track_title = track.display_label
                            self.state.is_paused = False
                    # else: user already moved to another track, discard this URL
                else:
                    with self.state.lock:
                        if self.state.playing_id == track.id:
                            self.state.track_title = f"Error: {track.title}"
                            self.state.is_paused = True
            except Exception:
                with self.state.lock:
                    if self.state.playing_id == track.id:
                        self.state.track_title = f"Error: {track.title}"
                        self.state.is_paused = True
            finally:
                self._notify_render()

        threading.Thread(target=resolver, daemon=True, name="stream-resolver").start()

    def _load_art_async(self, track) -> None:
        """Download and render album art in a background thread.

        Tries the Tidal cover URL first. If that fails or is unavailable,
        queries the iTunes search API.
        """
        url = track.album_art_url
        art = None

        if url:
            with self.state.lock:
                if self.state.playing_id == track.id:
                    self.state.art_url = url
                else:
                    return
            art = render_art(url, width=_ART_WIDTH, height=_ART_HEIGHT)

        # Fallback to iTunes API if Tidal URL is missing or failed to render
        if not art:
            from tidal_tui.art_renderer import get_itunes_art_url
            url = get_itunes_art_url(track.artist, track.album or "", track.title)
            if url:
                with self.state.lock:
                    if self.state.playing_id == track.id:
                        self.state.art_url = url
                    else:
                        return
                art = render_art(url, width=_ART_WIDTH, height=_ART_HEIGHT)

        if art:
            with self.state.lock:
                if self.state.playing_id == track.id and self.state.art_url == url:
                    self.state.art_text = art
            self._notify_render()

    def _play_track_by_order_index(self, order_index: int) -> None:
        """Navigate to a track using its position in the current play order.

        This is used by next/prev/gapless so that shuffle order is respected.
        """
        self.queue.current_index = order_index
        real_idx = self.queue.current_track_real_index
        if real_idx >= 0:
            self._play_track_at(real_idx)

    # -- Lifecycle ------------------------------------------------------------

    def _shutdown(self) -> None:
        """Clean up resources and save config."""
        self.input.stop()
        # Persist final volume before exiting
        try:
            self._config.volume = self.state.volume
            self._config.save()
        except Exception:
            pass
        self.player.shutdown()
