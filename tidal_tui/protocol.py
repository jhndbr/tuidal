"""Serialization helpers for passing state between the daemon and TUI client."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tidal_tui.models import AlbumInfo, AppState, ArtistInfo, PlaylistInfo, RepeatMode, SearchType, TrackInfo


def serialize_state(state: AppState) -> dict[str, Any]:
    """Serialize the AppState to a JSON-compatible dictionary."""
    with state.lock:
        return {
            "playlists": [asdict(p) for p in state.playlists],
            "playlist_name": state.playlist_name,
            "playlist_cursor": state.playlist_cursor,
            "sidebar_error": state.sidebar_error,
            "tracks": [asdict(t) for t in state.tracks],
            "track_cursor": state.track_cursor,
            "playing_id": state.playing_id,
            "favorite_track_ids": list(state.favorite_track_ids),
            "track_title": state.track_title,
            "album_art_url": state.album_art_url,
            "album_art_text": state.album_art_text,
            "position": state.position,
            "duration": state.duration,
            "volume": state.volume,
            "is_paused": state.is_paused,
            "shuffle": state.shuffle,
            "repeat": state.repeat.value,
            "active_panel": state.active_panel,
            "input_mode": state.input_mode,
            "search_query": state.search_query,
            "search_type": state.search_type.value,
            "search_results_artists": [asdict(a) for a in state.search_results_artists],
            "search_results_albums": [asdict(a) for a in state.search_results_albums],
            "search_results_mode": state.search_results_mode,
            "running": state.running,
            "status_message": state.status_message,
        }


def update_state_from_dict(state: AppState, data: dict[str, Any]) -> None:
    """Update an AppState object from a serialized dictionary."""
    with state.lock:
        state.playlists = [PlaylistInfo(**p) for p in data.get("playlists", [])]
        state.playlist_name = data.get("playlist_name", "")
        state.playlist_cursor = data.get("playlist_cursor", 0)
        state.sidebar_error = data.get("sidebar_error", "")
        
        state.tracks = [TrackInfo(**t) for t in data.get("tracks", [])]
        state.track_cursor = data.get("track_cursor", 0)
        state.playing_id = data.get("playing_id")
        state.favorite_track_ids = set(data.get("favorite_track_ids", []))
        
        state.track_title = data.get("track_title", "")
        state.album_art_url = data.get("album_art_url")
        state.album_art_text = data.get("album_art_text", "")
        state.position = data.get("position", 0.0)
        state.duration = data.get("duration", 0.0)
        state.volume = data.get("volume", 75)
        state.is_paused = data.get("is_paused", True)
        
        state.shuffle = data.get("shuffle", False)
        
        repeat_val = data.get("repeat", "off")
        try:
            state.repeat = RepeatMode(repeat_val)
        except ValueError:
            state.repeat = RepeatMode.OFF
            
        state.active_panel = data.get("active_panel", "sidebar")
        state.input_mode = data.get("input_mode", "normal")
        state.search_query = data.get("search_query", "")
        
        search_type_val = data.get("search_type", "all")
        try:
            state.search_type = SearchType(search_type_val)
        except ValueError:
            state.search_type = SearchType.ALL
            
        state.search_results_artists = [ArtistInfo(**a) for a in data.get("search_results_artists", [])]
        state.search_results_albums = [AlbumInfo(**a) for a in data.get("search_results_albums", [])]
        state.search_results_mode = data.get("search_results_mode", "")
        
        state.running = data.get("running", True)
        state.status_message = data.get("status_message", "")
