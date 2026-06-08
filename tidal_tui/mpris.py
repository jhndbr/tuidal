"""MPRIS D-Bus integration for tuidal.

Exposes the player as a standard MPRIS media player so desktop
environments (GNOME, KDE, etc.) can show/control playback.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from mpris_server.adapters import MprisAdapter
from mpris_server.events import EventAdapter
from mpris_server.server import Server

if TYPE_CHECKING:
    from tidal_tui.daemon import TuidalDaemon


from mpris_server.base import PlayState

class TuidalMprisAdapter(MprisAdapter):
    """Maps MPRIS D-Bus calls to the tuidal player backend."""

    def __init__(self, daemon: TuidalDaemon) -> None:
        self._app = daemon

    # -- Playback Status --
    def get_playstate(self) -> PlayState:
        """Return PlayState."""
        if self._app.queue.current_track is None:
            return PlayState.STOPPED
        return PlayState.PAUSED if self._app.player.paused else PlayState.PLAYING

    # -- Metadata --
    def metadata(self) -> dict:
        """Return current track metadata in MPRIS format."""
        track = self._app.queue.current_track
        if track is None:
            return {"mpris:trackid": "/org/mpris/MediaPlayer2/TrackList/NoTrack"}
        meta = {
            "mpris:trackid": f"/org/mpris/MediaPlayer2/Track/{track.id}",
            "mpris:length": int(track.duration_seconds * 1_000_000),  # microseconds
            "xesam:title": track.title,
            "xesam:artist": [track.artist] if track.artist else [],
            "xesam:album": track.album or "",
        }
        if track.album_art_url:
            meta["mpris:artUrl"] = track.album_art_url
        return meta

    # -- Transport Controls --
    def play(self):
        self._app.player.paused = False
        with self._app.state.lock:
            self._app.state.is_paused = False
        self._app.broadcast_state_sync()

    def pause(self):
        self._app.player.paused = True
        with self._app.state.lock:
            self._app.state.is_paused = True
        self._app.broadcast_state_sync()

    def play_pause(self):
        self._app._action_toggle_play()

    def stop(self):
        self._app.player.stop()
        with self._app.state.lock:
            self._app.state.is_paused = True
            self._app.state.track_title = "Stopped"
            self._app.state.playing_id = None
        self._app.broadcast_state_sync()

    def next(self):
        self._app._action_next_track()

    def previous(self):
        self._app._action_prev_track()

    def seek(self, offset: int):
        """Seek by offset microseconds."""
        self._app.player.seek(offset / 1_000_000, relative=True)

    def set_position(self, track_id: str, position: int):
        """Seek to absolute position (microseconds)."""
        self._app.player.seek(position / 1_000_000, relative=False)

    # -- Volume (0.0 to 1.0 for MPRIS) --
    def get_volume(self) -> float:
        return self._app.player.volume / 100.0

    def set_volume(self, volume: float):
        self._app.player.volume = volume * 100.0
        with self._app.state.lock:
            self._app.state.volume = int(self._app.player.volume)
        self._app.broadcast_state_sync()

    # -- Position --
    def get_current_position(self) -> int:
        """Current position in microseconds."""
        return int(self._app.player.position * 1_000_000)

    # -- Capabilities --
    def can_play(self) -> bool:
        return True

    def can_pause(self) -> bool:
        return True

    def can_seek(self) -> bool:
        return True

    def can_go_next(self) -> bool:
        return self._app.queue.has_next

    def can_go_previous(self) -> bool:
        return self._app.queue.has_prev

    def can_control(self) -> bool:
        return True


class TuidalEventHandler(EventAdapter):
    """Emits D-Bus PropertiesChanged signals when app state changes."""

    def on_playback_status_change(self):
        self.on_playpause()

    def on_track_change(self):
        self.on_options()  # emits metadata + status changes

    def on_volume_change(self):
        self.on_volume()


def create_mpris_server(daemon: TuidalDaemon) -> Server:
    """Create and publish the MPRIS server."""
    adapter = TuidalMprisAdapter(daemon)
    mpris = Server(name="tuidal", adapter=adapter)
    event_handler = TuidalEventHandler(root=mpris.root)

    # Store event_handler on daemon so it can emit signals
    daemon._mpris_events = event_handler

    mpris.publish()
    
    # Run the GLib main loop in a background thread
    threading.Thread(target=mpris.loop, daemon=True, name="mpris-loop").start()
    
    return mpris
