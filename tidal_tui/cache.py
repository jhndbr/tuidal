"""Metadata cache for Tidal TUI — SQLite-backed, zero extra dependencies.

Caches playlist tracks, artist/album tracks and search results to disk so
subsequent navigations are instant instead of hitting the Tidal API every time.

Cache location: ~/.config/tidal-tui/cache.db

TTL defaults:
  - Playlist / album / artist tracks:  5 minutes
  - Search results:                    2 minutes
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from tidal_tui.models import AlbumInfo, ArtistInfo, TrackInfo


# Default time-to-live in seconds
_TTL_TRACKS: int = 300   # 5 minutes
_TTL_SEARCH: int = 120   # 2 minutes
_TTL_FAVORITES: int = 600  # 10 minutes

_DB_PATH = Path.home() / ".config" / "tidal-tui" / "cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS track_cache (
    key        TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS artist_cache (
    key        TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS album_cache (
    key        TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS search_cache (
    key        TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS favorites_cache (
    key        TEXT PRIMARY KEY,
    data_json  TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


class MetadataCache:
    """Thread-safe SQLite cache for Tidal metadata.

    Each ``get_*`` method returns cached data (list of model objects) if the
    cache entry exists and has not expired, otherwise returns ``None`` so the
    caller knows to fetch from the API.

    Usage::

        cache = MetadataCache()
        tracks = cache.get_playlist_tracks("abc123")
        if tracks is None:
            tracks = tidal_service.get_playlist_tracks("abc123")
            cache.set_playlist_tracks("abc123", tracks)
    """

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = db_path
        self._init_db()

    # -- Setup ----------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- Playlist track cache -------------------------------------------------

    def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo] | None:
        """Return cached tracks for a playlist, or None if missing/expired."""
        row = self._get("track_cache", f"playlist:{playlist_id}", _TTL_TRACKS)
        if row is None:
            return None
        return [TrackInfo(**t) for t in json.loads(row)]

    def set_playlist_tracks(self, playlist_id: str, tracks: list[TrackInfo]) -> None:
        """Store playlist tracks in the cache."""
        data = json.dumps([_track_to_dict(t) for t in tracks])
        self._set("track_cache", f"playlist:{playlist_id}", data)

    # -- Artist top-tracks cache ----------------------------------------------

    def get_artist_tracks(self, artist_id: str) -> list[TrackInfo] | None:
        """Return cached top tracks for an artist, or None if missing/expired."""
        row = self._get("artist_cache", artist_id, _TTL_TRACKS)
        if row is None:
            return None
        return [TrackInfo(**t) for t in json.loads(row)]

    def set_artist_tracks(self, artist_id: str, tracks: list[TrackInfo]) -> None:
        data = json.dumps([_track_to_dict(t) for t in tracks])
        self._set("artist_cache", artist_id, data)

    # -- Album tracks cache ---------------------------------------------------

    def get_album_tracks(self, album_id: str) -> list[TrackInfo] | None:
        """Return cached tracks for an album, or None if missing/expired."""
        row = self._get("album_cache", album_id, _TTL_TRACKS)
        if row is None:
            return None
        return [TrackInfo(**t) for t in json.loads(row)]

    def set_album_tracks(self, album_id: str, tracks: list[TrackInfo]) -> None:
        data = json.dumps([_track_to_dict(t) for t in tracks])
        self._set("album_cache", album_id, data)

    # -- Search results cache -------------------------------------------------

    def get_search_results(self, query: str, search_type: str) -> dict[str, list] | None:
        """Return cached search results, or None if missing/expired."""
        key = f"{search_type}:{query.lower().strip()}"
        row = self._get("search_cache", key, _TTL_SEARCH)
        if row is None:
            return None
        raw = json.loads(row)
        return {
            "tracks":  [TrackInfo(**t) for t in raw.get("tracks", [])],
            "artists": [ArtistInfo(**a) for a in raw.get("artists", [])],
            "albums":  [AlbumInfo(**a) for a in raw.get("albums", [])],
        }

    def set_search_results(self, query: str, search_type: str, results: dict[str, list]) -> None:
        key = f"{search_type}:{query.lower().strip()}"
        data = json.dumps({
            "tracks":  [_track_to_dict(t) for t in results.get("tracks", [])],
            "artists": [_artist_to_dict(a) for a in results.get("artists", [])],
            "albums":  [_album_to_dict(a) for a in results.get("albums", [])],
        })
        self._set("search_cache", key, data)

    # -- Invalidation ---------------------------------------------------------

    def invalidate_playlist(self, playlist_id: str) -> None:
        """Force-expire a playlist's cached tracks."""
        self._delete("track_cache", f"playlist:{playlist_id}")

    # -- Favorites cache ------------------------------------------------------

    def get_favorite_tracks(self, order: str = "DATE", direction: str = "DESC") -> list[TrackInfo] | None:
        """Return all cached favorite tracks for a given order, or None if missing/expired."""
        key = f"favorites:{order}:{direction}"
        row = self._get("favorites_cache", key, _TTL_FAVORITES)
        if row is None:
            return None
        return [TrackInfo(**t) for t in json.loads(row)]

    def set_favorite_tracks(self, tracks: list[TrackInfo], order: str = "DATE", direction: str = "DESC") -> None:
        """Store the full list of favorite tracks in cache with order key."""
        key = f"favorites:{order}:{direction}"
        data = json.dumps([_track_to_dict(t) for t in tracks])
        self._set("favorites_cache", key, data)

    def invalidate_favorite_tracks(self) -> None:
        """Force-expire all cached favorites (e.g. after toggling a favorite)."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM favorites_cache")
        except sqlite3.Error:
            pass

    def clear_expired(self) -> None:
        """Remove all expired entries from every table."""
        now = time.time()
        for table, ttl in [
            ("track_cache", _TTL_TRACKS),
            ("artist_cache", _TTL_TRACKS),
            ("album_cache", _TTL_TRACKS),
            ("search_cache", _TTL_SEARCH),
        ]:
            with self._connect() as conn:
                conn.execute(
                    f"DELETE FROM {table} WHERE fetched_at < ?",  # noqa: S608
                    (now - ttl,),
                )

    # -- Low-level helpers ----------------------------------------------------

    def _get(self, table: str, key: str, ttl: int) -> str | None:
        """Return the cached JSON string if present and fresh, else None."""
        cutoff = time.time() - ttl
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT data_json FROM {table} WHERE key = ? AND fetched_at >= ?",  # noqa: S608
                    (key, cutoff),
                ).fetchone()
        except sqlite3.Error:
            return None
        return row["data_json"] if row else None

    def _set(self, table: str, key: str, data_json: str) -> None:
        """Insert or replace a cache entry."""
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} (key, data_json, fetched_at) VALUES (?, ?, ?)",  # noqa: S608
                    (key, data_json, now),
                )
        except sqlite3.Error:
            pass  # Cache is best-effort; never crash the app on a cache error

    def _delete(self, table: str, key: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    f"DELETE FROM {table} WHERE key = ?",  # noqa: S608
                    (key,),
                )
        except sqlite3.Error:
            pass


# -- Serialization helpers ----------------------------------------------------

def _track_to_dict(t: TrackInfo) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "artist": t.artist,
        "album": t.album,
        "duration_seconds": t.duration_seconds,
        "album_art_url": t.album_art_url,
        "track_number": t.track_number,
    }


def _artist_to_dict(a: ArtistInfo) -> dict[str, Any]:
    return {"id": a.id, "name": a.name}


def _album_to_dict(a: AlbumInfo) -> dict[str, Any]:
    return {
        "id": a.id,
        "name": a.name,
        "artist": a.artist,
        "num_tracks": a.num_tracks,
        "duration_seconds": a.duration_seconds,
        "year": a.year,
    }
