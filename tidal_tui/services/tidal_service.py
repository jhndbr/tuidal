"""Tidal API service — wraps tidalapi with a clean interface.

All Tidal interactions go through this class so the rest of the app
never imports tidalapi directly. This makes it easy to mock for tests
or swap to a different backend.
"""
from __future__ import annotations

import time
from typing import Any

import tidalapi
import tidalapi.album as tidal_album
import tidalapi.artist as tidal_artist

from tidal_tui.config import load_session_tokens, save_session_tokens
from tidal_tui.models import AlbumInfo, ArtistInfo, PlaylistInfo, SearchType, TrackInfo


# ---------------------------------------------------------------------------
# Simple in-memory TTL cache (no extra dependencies needed)
# ---------------------------------------------------------------------------

class _TTLCache:
    """Minimal TTL cache — avoids redundant API calls.

    Each entry expires after *default_ttl* seconds. Thread-safe enough
    for our use case (dict ops are atomic in CPython).
    """

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._store: dict[str, tuple[float, Any]] = {}  # key → (expiry_ts, value)
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Return cached value if still valid, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if time.monotonic() > expiry:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with optional per-key TTL override."""
        self._store[key] = (time.monotonic() + (ttl or self._default_ttl), value)

    def invalidate(self, key: str) -> None:
        """Remove a single key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop everything."""
        self._store.clear()


# Maps user-facing quality names to tidalapi enum values.
# tidalapi 0.8.x uses: low_96k, low_320k, high_lossless, hi_res_lossless
_QUALITY_MAP: dict[str, tidalapi.Quality] = {}


def _init_quality_map() -> None:
    """Build quality map defensively (tidalapi versions differ)."""
    # Try modern names first (0.8.x), then legacy names
    candidates = [
        ("low", ["low_96k", "low"]),
        ("high", ["low_320k", "high"]),
        ("lossless", ["high_lossless", "lossless"]),
        ("max", ["hi_res_lossless", "hi_res", "master"]),
    ]
    for user_name, attrs in candidates:
        for attr in attrs:
            val = getattr(tidalapi.Quality, attr, None)
            if val is not None:
                _QUALITY_MAP[user_name] = val
                break


_init_quality_map()

# Safe default: pick the first available quality
_DEFAULT_QUALITY = next(iter(tidalapi.Quality), None)


class TidalService:
    """High-level wrapper around tidalapi.

    Usage::

        svc = TidalService(quality="high")
        svc.authenticate()          # OAuth (opens browser first time)
        playlists = svc.get_playlists()
        tracks = svc.get_playlist_tracks(playlists[0].id)
        url = svc.resolve_stream_url(tracks[0].id)
    """

    # Cache TTLs (seconds)
    _PLAYLISTS_TTL = 300.0       # 5 min — playlist list rarely changes mid-session
    _PLAYLIST_TRACKS_TTL = 180.0 # 3 min — tracks in a playlist
    _ALBUM_TRACKS_TTL = 600.0    # 10 min — album contents almost never change
    _ARTIST_TRACKS_TTL = 300.0   # 5 min — artist top tracks
    _FAVORITES_TTL = 120.0       # 2 min — favorites may change from other devices

    def __init__(self, quality: str = "high") -> None:
        tidal_quality = _QUALITY_MAP.get(quality, _DEFAULT_QUALITY)
        config = tidalapi.Config(quality=tidal_quality)
        self._session = tidalapi.Session(config)
        self._cache = _TTLCache()

    # -- Authentication -------------------------------------------------------

    def authenticate(self) -> None:
        """Authenticate with Tidal.

        Tries to restore a saved session first. If that fails,
        falls back to full OAuth flow (opens browser).
        """
        if self._try_restore_session():
            return
        self._session.login_oauth_simple()
        self._persist_session()

    def _try_restore_session(self) -> bool:
        """Attempt to restore session from saved tokens."""
        tokens = load_session_tokens()
        if tokens is None:
            return False
        try:
            self._session.load_oauth_session(
                token_type=tokens["token_type"],
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token"),
                expiry_time=tokens.get("expiry_time"),
            )
            if self._session.check_login():
                self._persist_session()  # tokens may have been refreshed
                return True
        except Exception:
            pass
        return False

    def _persist_session(self) -> None:
        """Save current session tokens to disk."""
        save_session_tokens(
            token_type=self._session.token_type,
            access_token=self._session.access_token,
            refresh_token=self._session.refresh_token,
            expiry_time=self._session.expiry_time,
        )

    # -- Playlists ------------------------------------------------------------

    def get_playlists(self) -> list[PlaylistInfo]:
        """Fetch all playlists for the authenticated user.
        
        Bypasses `self._session.user.playlists()` because that implementation
        does a synchronous GET request for *every single playlist* to fetch
        details, which fails the entire batch if Tidal returns a 500 Server Error
        for any individual playlist.

        Results are cached for 5 minutes to avoid redundant API calls.
        """
        cached = self._cache.get("playlists")
        if cached is not None:
            return cached

        result: list[PlaylistInfo] = []
        try:
            # Fetch the raw JSON containing all playlists in one request
            user_id = self._session.user.id
            resp = self._session.request.request("GET", f"users/{user_id}/playlists")
            data = resp.json()
            
            if isinstance(data, dict) and "items" in data:
                for item in data["items"]:
                    result.append(
                        PlaylistInfo(
                            id=item.get("uuid", ""),
                            name=item.get("title", "Untitled"),
                            num_tracks=item.get("numberOfTracks", 0),
                            description=item.get("description", ""),
                        )
                    )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch playlists: {exc}") from exc

        self._cache.set("playlists", result, self._PLAYLISTS_TTL)
        return result

    # -- Tracks ---------------------------------------------------------------

    def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        """Fetch all tracks for a given playlist (cached 3 min)."""
        cache_key = f"playlist_tracks:{playlist_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: list[TrackInfo] = []
        try:
            playlist = self._get_playlist(playlist_id)
            raw_tracks = self._get_tracks_from_playlist(playlist)
            for i, track in enumerate(raw_tracks, start=1):
                result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch tracks: {exc}") from exc

        self._cache.set(cache_key, result, self._PLAYLIST_TRACKS_TTL)
        return result

    def search_tracks(self, query: str, limit: int = 50) -> list[TrackInfo]:
        """Search for tracks matching the query."""
        if not query:
            return []
        
        result: list[TrackInfo] = []
        try:
            search_result = self._session.search(query, models=[tidalapi.media.Track], limit=limit)
            raw_tracks = search_result.get("tracks", []) if isinstance(search_result, dict) else getattr(search_result, "tracks", [])
            for i, track in enumerate(raw_tracks, start=1):
                result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Search failed: {exc}") from exc
        return result

    def search_artists(self, query: str, limit: int = 30) -> list[ArtistInfo]:
        """Search for artists matching the query."""
        if not query:
            return []

        result: list[ArtistInfo] = []
        try:
            search_result = self._session.search(
                query, models=[tidal_artist.Artist], limit=limit
            )
            raw_artists = (
                search_result.get("artists", [])
                if isinstance(search_result, dict)
                else getattr(search_result, "artists", [])
            )
            for artist in raw_artists:
                result.append(
                    ArtistInfo(
                        id=str(getattr(artist, "id", "")),
                        name=getattr(artist, "name", "Unknown"),
                    )
                )
        except Exception as exc:
            raise RuntimeError(f"Artist search failed: {exc}") from exc
        return result

    def search_albums(self, query: str, limit: int = 30) -> list[AlbumInfo]:
        """Search for albums matching the query."""
        if not query:
            return []

        result: list[AlbumInfo] = []
        try:
            search_result = self._session.search(
                query, models=[tidal_album.Album], limit=limit
            )
            raw_albums = (
                search_result.get("albums", [])
                if isinstance(search_result, dict)
                else getattr(search_result, "albums", [])
            )
            for album in raw_albums:
                result.append(self._album_to_info(album))
        except Exception as exc:
            raise RuntimeError(f"Album search failed: {exc}") from exc
        return result

    def search_all(
        self, query: str, limit: int = 20
    ) -> dict[str, list]:
        """Search across tracks, artists, and albums simultaneously.

        Returns a dict with keys 'tracks', 'artists', 'albums'.
        """
        if not query:
            return {"tracks": [], "artists": [], "albums": []}

        try:
            search_result = self._session.search(query, limit=limit)
            raw = search_result if isinstance(search_result, dict) else {}

            tracks: list[TrackInfo] = []
            for i, track in enumerate(raw.get("tracks", []), start=1):
                tracks.append(self._track_to_info(track, i))

            artists: list[ArtistInfo] = []
            for artist in raw.get("artists", []):
                artists.append(
                    ArtistInfo(
                        id=str(getattr(artist, "id", "")),
                        name=getattr(artist, "name", "Unknown"),
                    )
                )

            albums: list[AlbumInfo] = []
            for album in raw.get("albums", []):
                albums.append(self._album_to_info(album))

            return {"tracks": tracks, "artists": artists, "albums": albums}
        except Exception as exc:
            raise RuntimeError(f"Search failed: {exc}") from exc

    def get_artist_top_tracks(self, artist_id: str, limit: int = 50) -> list[TrackInfo]:
        """Fetch the top tracks for an artist (cached 5 min)."""
        cache_key = f"artist_tracks:{artist_id}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: list[TrackInfo] = []
        try:
            artist = self._session.artist(artist_id)
            raw_tracks = artist.get_top_tracks(limit=limit)
            for i, track in enumerate(raw_tracks, start=1):
                result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch artist tracks: {exc}") from exc

        self._cache.set(cache_key, result, self._ARTIST_TRACKS_TTL)
        return result

    def get_album_tracks(self, album_id: str) -> list[TrackInfo]:
        """Fetch all tracks from an album (cached 10 min)."""
        cache_key = f"album_tracks:{album_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: list[TrackInfo] = []
        try:
            album = self._session.album(album_id)
            raw_tracks = album.tracks()
            for i, track in enumerate(raw_tracks, start=1):
                result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch album tracks: {exc}") from exc

        self._cache.set(cache_key, result, self._ALBUM_TRACKS_TTL)
        return result

    def get_favorite_tracks(self) -> list[TrackInfo]:
        """Fetch user's favorite tracks (cached 2 min)."""
        cached = self._cache.get("favorites")
        if cached is not None:
            return cached

        result: list[TrackInfo] = []
        try:
            if hasattr(self._session.user, "favorites") and self._session.user.favorites:
                raw_tracks = self._session.user.favorites.tracks()
                for i, track in enumerate(raw_tracks, start=1):
                    result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch favorites: {exc}") from exc

        self._cache.set("favorites", result, self._FAVORITES_TTL)
        return result

    def toggle_favorite(self, track_id: str, is_favorite: bool) -> None:
        """Add or remove a track from favorites."""
        try:
            if not hasattr(self._session.user, "favorites") or not self._session.user.favorites:
                return
            if is_favorite:
                self._session.user.favorites.add_track(track_id)
            else:
                self._session.user.favorites.remove_track(track_id)
            # Invalidate favorites cache so next fetch reflects the change
            self._cache.invalidate("favorites")
        except Exception as exc:
            raise RuntimeError(f"Failed to toggle favorite: {exc}") from exc

    def clear_cache(self) -> None:
        """Drop all cached data (useful after account changes or errors)."""
        self._cache.clear()

    def _get_playlist(self, playlist_id: str):
        """Get a playlist object by ID, trying multiple APIs."""
        # Modern API
        if hasattr(self._session, "playlist"):
            try:
                return self._session.playlist(playlist_id)
            except Exception:
                pass
        # Legacy API
        try:
            pl = tidalapi.Playlist(self._session, playlist_id)
            if hasattr(pl, "load"):
                pl.load()
            return pl
        except TypeError:
            return tidalapi.Playlist(self._session, playlist_id=playlist_id)

    def _get_tracks_from_playlist(self, playlist) -> list:
        """Extract tracks from a playlist object (handles API variations)."""
        # Method: tracks()
        if hasattr(playlist, "tracks") and callable(playlist.tracks):
            try:
                tracks = list(playlist.tracks())
                if tracks:
                    return tracks
            except Exception:
                pass
        # Method: get_tracks()
        if hasattr(playlist, "get_tracks"):
            try:
                tracks = list(playlist.get_tracks())
                if tracks:
                    return tracks
            except Exception:
                pass
        # Attribute: items (might be iterable)
        if hasattr(playlist, "items") and not callable(playlist.items):
            try:
                return list(playlist.items)
            except Exception:
                pass
        return []

    @staticmethod
    def _track_to_info(track, index: int) -> TrackInfo:
        """Convert a tidalapi Track object to our TrackInfo model."""
        artist_name = ""
        if hasattr(track, "artist") and track.artist is not None:
            artist_name = getattr(track.artist, "name", str(track.artist))
        elif hasattr(track, "artists") and track.artists:
            try:
                artist_name = getattr(track.artists[0], "name", "")
            except (IndexError, TypeError):
                pass

        album_name = ""
        album_art_url = None
        if hasattr(track, "album") and track.album is not None:
            album_name = getattr(track.album, "name", "")
            try:
                if hasattr(track.album, "image"):
                    album_art_url = track.album.image(640, 640)
                elif hasattr(track.album, "picture"):
                    album_art_url = track.album.picture(640, 640)
            except Exception:
                pass

        duration = getattr(track, "duration", 0) or 0

        return TrackInfo(
            id=str(getattr(track, "id", "")),
            title=getattr(track, "name", "")
            or getattr(track, "title", "")
            or "Unknown",
            artist=artist_name,
            album=album_name,
            duration_seconds=float(duration),
            album_art_url=album_art_url,
            track_number=index,
        )

    @staticmethod
    def _album_to_info(album) -> AlbumInfo:
        """Convert a tidalapi Album object to our AlbumInfo model."""
        artist_name = ""
        if hasattr(album, "artist") and album.artist is not None:
            artist_name = getattr(album.artist, "name", str(album.artist))
        elif hasattr(album, "artists") and album.artists:
            try:
                artist_name = getattr(album.artists[0], "name", "")
            except (IndexError, TypeError):
                pass

        duration = getattr(album, "duration", 0) or 0
        num_tracks = getattr(album, "num_tracks", 0) or 0

        year = None
        if hasattr(album, "year") and album.year:
            year = album.year
        elif hasattr(album, "release_date") and album.release_date:
            year = album.release_date.year

        return AlbumInfo(
            id=str(getattr(album, "id", "")),
            name=getattr(album, "name", "") or "Unknown",
            artist=artist_name,
            num_tracks=num_tracks,
            duration_seconds=float(duration),
            year=year,
        )

    # -- Streaming ------------------------------------------------------------

    def resolve_stream_url(self, track_id: str) -> str | None:
        """Resolve a playable streaming URL for a track.

        Tries multiple APIs in order of preference, since tidalapi
        versions expose different methods.
        """
        try:
            track = self._session.track(int(track_id))
        except Exception:
            try:
                track = tidalapi.Track(self._session, track_id)
            except Exception:
                return None

        # 1) get_url() — returns direct URL string in some versions
        url = self._try_method(track, "get_url")
        if url:
            return url

        # 2) get_stream() — returns Stream object with .url
        if hasattr(track, "get_stream"):
            try:
                stream = track.get_stream()
                if hasattr(stream, "url") and stream.url:
                    return stream.url
            except Exception:
                pass

        # 3) get_stream_url() — legacy method
        url = self._try_method(track, "get_stream_url")
        if url:
            return url

        # 4) Direct attributes
        for attr in ("stream_url", "url"):
            val = getattr(track, attr, None)
            if isinstance(val, str) and val:
                return val

        return None

    @staticmethod
    def _try_method(obj, method_name: str) -> str | None:
        """Try calling a method and return its string result, or None."""
        method = getattr(obj, method_name, None)
        if method is None or not callable(method):
            return None
        try:
            result = method()
            if isinstance(result, str):
                return result
            if hasattr(result, "url"):
                return result.url
        except Exception:
            pass
        return None

    @property
    def session(self) -> tidalapi.Session:
        """Expose the raw session for advanced use."""
        return self._session
