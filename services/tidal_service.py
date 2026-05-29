"""Tidal API service — wraps tidalapi with a clean interface.

All Tidal interactions go through this class so the rest of the app
never imports tidalapi directly. This makes it easy to mock for tests
or swap to a different backend.
"""
from __future__ import annotations

import tidalapi

from tidal_tui.config import load_session_tokens, save_session_tokens
from tidal_tui.models import PlaylistInfo, TrackInfo


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

    def __init__(self, quality: str = "high") -> None:
        tidal_quality = _QUALITY_MAP.get(quality, _DEFAULT_QUALITY)
        config = tidalapi.Config(quality=tidal_quality)
        self._session = tidalapi.Session(config)

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
        """Fetch all playlists for the authenticated user."""
        result: list[PlaylistInfo] = []
        try:
            for pl in self._session.user.playlists():
                result.append(
                    PlaylistInfo(
                        id=str(getattr(pl, "id", "")),
                        name=getattr(pl, "name", "Untitled"),
                        num_tracks=getattr(pl, "num_tracks", 0) or 0,
                        description=getattr(pl, "description", "") or "",
                    )
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch playlists: {exc}") from exc
        return result

    # -- Tracks ---------------------------------------------------------------

    def get_playlist_tracks(self, playlist_id: str) -> list[TrackInfo]:
        """Fetch all tracks for a given playlist."""
        result: list[TrackInfo] = []
        try:
            playlist = self._get_playlist(playlist_id)
            raw_tracks = self._get_tracks_from_playlist(playlist)
            for i, track in enumerate(raw_tracks, start=1):
                result.append(self._track_to_info(track, i))
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch tracks: {exc}") from exc
        return result

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
        if hasattr(track, "album") and track.album is not None:
            album_name = getattr(track.album, "name", "")

        duration = getattr(track, "duration", 0) or 0

        return TrackInfo(
            id=str(getattr(track, "id", "")),
            title=getattr(track, "name", "")
            or getattr(track, "title", "")
            or "Unknown",
            artist=artist_name,
            album=album_name,
            duration_seconds=float(duration),
            track_number=index,
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
