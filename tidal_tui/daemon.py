"""Daemon process for tuidal.

Runs the audio player and network loaders in the background.
Exposes a Unix Domain Socket to serve state and receive commands
from the TUI client.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tidal_tui.models import AppState, QueueState, SearchType
from tidal_tui.mpris import create_mpris_server
from tidal_tui.protocol import serialize_state
from tidal_tui.services.album_art import render_album_art
from tidal_tui.services.player_backend import PlayerBackend
from tidal_tui.services.tidal_service import TidalService


SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tuidal" / "daemon.sock"
PID_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tuidal" / "daemon.pid"


class TuidalDaemon:
    """Headless music player daemon."""

    def __init__(self, quality: str = "high"):
        self.tidal = TidalService(quality=quality)
        self.player = PlayerBackend()
        self.queue = QueueState()
        self.state = AppState()
        
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tuidald")
        self._search_generation = 0
        self._search_gen_lock = threading.Lock()
        
        # Asyncio IPC
        self._clients: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        
        self._setup_player_callbacks()

    # -- IPC Server -----------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon server."""
        self._loop = asyncio.get_running_loop()
        
        # Authenticate if needed
        try:
            self.tidal.authenticate()
        except Exception as exc:
            print(f"Authentication failed: {exc}", file=sys.stderr)
            sys.exit(1)

        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        for sig in (signal.SIGTERM, signal.SIGINT):
            self._loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(SOCKET_PATH)
        )
        os.chmod(SOCKET_PATH, 0o600)
        
        # Start initial load
        self._load_playlists_async()

        # MPRIS hook
        try:
            self._mpris_server = create_mpris_server(self)
        except Exception as exc:
            print(f"Warning: Failed to start MPRIS server: {exc}", file=sys.stderr)
            self._mpris_events = None
            self._mpris_server = None

        print(f"Daemon listening on {SOCKET_PATH}")
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Graceful shutdown."""
        print("Shutting down daemon...")
        await self._broadcast({"type": "shutdown"})

        for writer in list(self._clients):
            writer.close()
        self._clients.clear()

        if self._server:
            self._server.close()

        self.player.shutdown()
        self._pool.shutdown(wait=False, cancel_futures=True)

        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        if PID_FILE.exists():
            PID_FILE.unlink()

        if self._loop:
            self._loop.stop()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single connected client."""
        self._clients.add(writer)
        try:
            # Send initial state
            await self._send(writer, {"type": "state", "data": serialize_state(self.state)})
            
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue

                if "action" in msg:
                    self._handle_action(msg["action"], msg.get("args", {}))
                elif "search_key" in msg:
                    self._handle_search_key(msg["search_key"])
                    
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def broadcast_state_sync(self) -> None:
        """Trigger state broadcast from a synchronous thread."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._broadcast_state())
            )

    async def _broadcast_state(self) -> None:
        """Broadcast current state to all connected clients."""
        await self._broadcast({"type": "state", "data": serialize_state(self.state)})

    async def _broadcast(self, msg: dict) -> None:
        """Send message to all clients."""
        data = json.dumps(msg).encode("utf-8") + b"\n"
        dead = []
        for writer in self._clients:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                dead.append(writer)
        for w in dead:
            self._clients.discard(w)

    async def _send(self, writer: asyncio.StreamWriter, msg: dict) -> None:
        writer.write(json.dumps(msg).encode("utf-8") + b"\n")
        await writer.drain()

    # -- Actions (mirrored from app.py) ---------------------------------------

    def _handle_action(self, action: str, args: dict) -> None:
        """Dispatch an action from the client."""
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
        }
        handler = handlers.get(action)
        if handler:
            handler()
            self.broadcast_state_sync()

    def _handle_search_key(self, key: str) -> None:
        """Process search input."""
        import readchar
        
        if key == readchar.key.ESC:
            with self.state.lock:
                self.state.input_mode = "normal"
                self.state.search_query = ""
            self.broadcast_state_sync()
            return

        if key == "\t":
            cycle = [SearchType.ALL, SearchType.TRACKS, SearchType.ARTISTS, SearchType.ALBUMS]
            with self.state.lock:
                idx = cycle.index(self.state.search_type)
                self.state.search_type = cycle[(idx + 1) % len(cycle)]
            self.broadcast_state_sync()
            return

        if key in ("\r", "\n", readchar.key.ENTER):
            with self.state.lock:
                query = self.state.search_query
                search_type = self.state.search_type
                self.state.input_mode = "normal"
            if query.strip():
                self._search_async(query.strip(), search_type)
            self.broadcast_state_sync()
            return
            
        if key in (readchar.key.BACKSPACE, "\x7f", "\x08"):
            with self.state.lock:
                self.state.search_query = self.state.search_query[:-1]
            self.broadcast_state_sync()
            return
            
        if len(key) == 1 and key.isprintable():
            with self.state.lock:
                self.state.search_query += key
            self.broadcast_state_sync()

    # -- Playback Actions -----------------------------------------------------

    def _action_toggle_play(self) -> None:
        if self.queue.current_track is None:
            return
        self.player.toggle_pause()
        with self.state.lock:
            self.state.is_paused = self.player.paused
        if getattr(self, "_mpris_events", None):
            self._mpris_events.on_playback_status_change()

    def _action_next_track(self) -> None:
        nxt = self.queue.next_index
        if nxt is not None:
            self._play_track_at(nxt)
        else:
            self.player.stop()
            with self.state.lock:
                self.state.track_title = "Queue finished"
                self.state.is_paused = True
            if getattr(self, "_mpris_events", None):
                self._mpris_events.on_playback_status_change()

    def _action_prev_track(self) -> None:
        prev = self.queue.prev_index
        if prev is not None:
            self._play_track_at(prev)

    def _action_volume_up(self) -> None:
        self.player.volume = min(150, self.player.volume + 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)
        if getattr(self, "_mpris_events", None):
            self._mpris_events.on_volume_change()

    def _action_volume_down(self) -> None:
        self.player.volume = max(0, self.player.volume - 5)
        with self.state.lock:
            self.state.volume = int(self.player.volume)
        if getattr(self, "_mpris_events", None):
            self._mpris_events.on_volume_change()

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

    def _action_quit(self) -> None:
        # Quit client, but leave daemon running. Handled by client.py
        pass

    # -- Navigation Actions ---------------------------------------------------

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
                self.state.playlist_cursor = min(max_idx, self.state.playlist_cursor + 1)
            else:
                if self.state.search_results_mode == "artists":
                    max_idx = max(0, len(self.state.search_results_artists) - 1)
                elif self.state.search_results_mode == "albums":
                    max_idx = max(0, len(self.state.search_results_albums) - 1)
                elif self.state.search_results_mode == "all":
                    total = (len(self.state.search_results_artists)
                             + len(self.state.search_results_albums)
                             + len(self.state.tracks))
                    max_idx = max(0, total - 1)
                else:
                    max_idx = max(0, len(self.state.tracks) - 1)
                self.state.track_cursor = min(max_idx, self.state.track_cursor + 1)

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
            except Exception as exc:
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            self.broadcast_state_sync()

        self._pool.submit(toggler)

    def _action_select(self) -> None:
        playlist_to_load: tuple[str, str] | None = None
        track_index: int | None = None
        artist_to_load: tuple[str, str] | None = None
        album_to_load: tuple[str, str] | None = None

        with self.state.lock:
            if self.state.active_panel == "sidebar":
                if self.state.playlists and self.state.playlist_cursor < len(self.state.playlists):
                    pl = self.state.playlists[self.state.playlist_cursor]
                    playlist_to_load = (pl.id, pl.name)
                    self.state.active_panel = "content"
            else:
                mode = self.state.search_results_mode
                cursor = self.state.track_cursor

                if mode == "artists":
                    if self.state.search_results_artists and cursor < len(self.state.search_results_artists):
                        a = self.state.search_results_artists[cursor]
                        artist_to_load = (a.id, a.name)
                elif mode == "albums":
                    if self.state.search_results_albums and cursor < len(self.state.search_results_albums):
                        a = self.state.search_results_albums[cursor]
                        album_to_load = (a.id, a.name)
                elif mode == "all":
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

    # -- Player Callbacks -----------------------------------------------------

    def _setup_player_callbacks(self) -> None:
        self.player.on_time_change(self._on_time_change)
        self.player.on_duration_change(self._on_duration_change)
        self.player.on_track_end(self._on_track_end)
        self.state.volume = int(self.player.volume)

    def _on_time_change(self, position: float) -> None:
        # Throttle position broadcasts to save CPU/Network if needed, 
        # but TUI usually refreshes at 10fps anyway.
        with self.state.lock:
            self.state.position = position
        self.broadcast_state_sync()

    def _on_duration_change(self, duration: float) -> None:
        with self.state.lock:
            self.state.duration = duration
        self.broadcast_state_sync()

    def _on_track_end(self) -> None:
        self._action_next_track()
        self.broadcast_state_sync()

    # -- Loaders --------------------------------------------------------------

    def _load_playlists_async(self) -> None:
        def loader():
            try:
                from tidal_tui.models import PlaylistInfo
                fav_tracks = []
                try:
                    fav_tracks = self.tidal.get_favorite_tracks()
                except Exception:
                    pass
                
                playlists_error = ""
                loaded_playlists = []
                try:
                    loaded_playlists = self.tidal.get_playlists()
                except Exception as exc:
                    playlists_error = str(exc)

                final = []
                if fav_tracks:
                    final.append(PlaylistInfo(
                        id="__favorites__",
                        name="\u2764\ufe0f Favoritas",
                        num_tracks=len(fav_tracks),
                        description="Tus canciones favoritas",
                    ))
                final.extend(loaded_playlists)

                with self.state.lock:
                    self.state.playlists = final
                    self.state.favorite_track_ids = {t.id for t in fav_tracks}
                    if final:
                        self.state.sidebar_error = ""
                        self.state.status_message = f"Loaded {len(loaded_playlists)} playlists"
                    elif playlists_error:
                        self.state.sidebar_error = playlists_error
                        self.state.status_message = "Error loading playlists (/ to search)"
                    else:
                        self.state.sidebar_error = ""
                        self.state.status_message = "No playlists found"
            except Exception as exc:
                with self.state.lock:
                    self.state.sidebar_error = str(exc)
                    self.state.status_message = "Error loading playlists (/ to search)"
            self.broadcast_state_sync()

        self._pool.submit(loader)

    def _load_tracks_async(self, playlist_id: str, playlist_name: str) -> None:
        with self.state.lock:
            self.state.status_message = f"Loading {playlist_name}..."
        self.broadcast_state_sync()

        def loader():
            try:
                if playlist_id == "__favorites__":
                    tracks = self.tidal.get_favorite_tracks()
                else:
                    tracks = self.tidal.get_playlist_tracks(playlist_id)
                with self.state.lock:
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
                    self.state.status_message = f"Error: {exc}"
            self.broadcast_state_sync()

        self._pool.submit(loader)

    def _search_async(self, query: str, search_type: SearchType = SearchType.ALL) -> None:
        with self._search_gen_lock:
            self._search_generation += 1
            gen = self._search_generation

        with self.state.lock:
            self.state.status_message = f"Searching {search_type.value}: '{query}'..."
        self.broadcast_state_sync()

        def loader():
            try:
                if search_type == SearchType.TRACKS:
                    tracks = self.tidal.search_tracks(query)
                    with self._search_gen_lock:
                        if gen != self._search_generation: return
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
                    with self._search_gen_lock:
                        if gen != self._search_generation: return
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
                    with self._search_gen_lock:
                        if gen != self._search_generation: return
                    with self.state.lock:
                        self.state.tracks = []
                        self.state.search_results_artists = []
                        self.state.search_results_albums = albums
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"💿 Albums: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "albums"
                        self.state.status_message = ""

                else:
                    results = self.tidal.search_all(query)
                    with self._search_gen_lock:
                        if gen != self._search_generation: return
                    with self.state.lock:
                        self.state.tracks = results["tracks"]
                        self.state.search_results_artists = results["artists"]
                        self.state.search_results_albums = results["albums"]
                        self.state.track_cursor = 0
                        self.state.playlist_name = f"🔍 All: {query}"
                        self.state.active_panel = "content"
                        self.state.search_results_mode = "all"
                        self.state.status_message = ""
                    self.queue.set_tracks(results["tracks"])
            except Exception as exc:
                with self._search_gen_lock:
                    if gen != self._search_generation: return
                with self.state.lock:
                    self.state.status_message = f"Error: {exc}"
            self.broadcast_state_sync()

        self._pool.submit(loader)

    def _load_artist_tracks_async(self, artist_id: str, artist_name: str) -> None:
        with self.state.lock:
            self.state.status_message = f"Loading tracks for {artist_name}..."
        self.broadcast_state_sync()

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
            self.broadcast_state_sync()

        self._pool.submit(loader)

    def _load_album_tracks_async(self, album_id: str, album_name: str) -> None:
        with self.state.lock:
            self.state.status_message = f"Loading {album_name}..."
        self.broadcast_state_sync()

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
            self.broadcast_state_sync()

        self._pool.submit(loader)

    def _play_track_at(self, index: int) -> None:
        track = self.queue.select(index)
        if not track:
            return

        with self.state.lock:
            self.state.track_title = f"Loading… {track.display_label}"
            self.state.album_art_url = track.album_art_url
            self.state.album_art_text = ""  # Clear previous
            self.state.playing_id = track.id
            self.state.is_paused = False
            self.state.position = 0.0
            self.state.duration = track.duration_seconds

        def art_renderer():
            if track.album_art_url:
                # Increased size for better resolution in sidebar (width 30)
                art = render_album_art(track.album_art_url, width=28, height=14)
                with self.state.lock:
                    if self.state.playing_id == track.id:
                        self.state.album_art_text = art
                self.broadcast_state_sync()

        self._pool.submit(art_renderer)
        self.broadcast_state_sync()

        def resolver():
            try:
                url = self.tidal.resolve_stream_url(track.id)
                if url:
                    self.player.play(url)
                    with self.state.lock:
                        self.state.track_title = track.display_label
                        self.state.is_paused = False
                    if getattr(self, "_mpris_events", None):
                        self._mpris_events.on_track_change()
                else:
                    with self.state.lock:
                        self.state.track_title = f"Error: {track.title}"
                        self.state.is_paused = True
            except Exception:
                with self.state.lock:
                    self.state.track_title = f"Error: {track.title}"
                    self.state.is_paused = True
            self.broadcast_state_sync()

        self._pool.submit(resolver)


# --- Lifecycle Helpers ---

def is_daemon_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False

def stop_daemon() -> None:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to daemon (PID {pid})")
        except (ProcessLookupError, ValueError):
            print("Daemon not running or stale PID file.")
            PID_FILE.unlink(missing_ok=True)
    else:
        print("Daemon not running.")
