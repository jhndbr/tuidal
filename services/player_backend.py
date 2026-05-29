"""Audio playback backend using python-mpv (libmpv).

Provides a clean callback-based interface for the UI layer.
All mpv property observers fire in mpv's internal thread,
so the app must use call_from_thread() when updating the UI.
"""
from __future__ import annotations

from typing import Callable

import mpv


class PlayerBackend:
    """Wraps mpv for audio-only playback with event callbacks.

    Usage::

        player = PlayerBackend()
        player.on_time_change(lambda pos: print(f"Position: {pos}"))
        player.on_track_end(lambda: print("Track ended"))
        player.play("https://stream-url.com/track.flac")
        player.volume = 80
        player.toggle_pause()
    """

    def __init__(self) -> None:
        self._player = mpv.MPV(
            video=False,
            ytdl=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
        )
        self._user_stopped = False

        # Callback registries
        self._on_time_change: list[Callable[[float], None]] = []
        self._on_duration_change: list[Callable[[float], None]] = []
        self._on_track_end: list[Callable[[], None]] = []

        self._setup_observers()

    # -- Observer setup -------------------------------------------------------

    def _setup_observers(self) -> None:
        """Wire up mpv property observers and event callbacks."""

        @self._player.property_observer("time-pos")
        def _on_time(_name: str, value: float | None) -> None:
            if value is not None:
                for cb in self._on_time_change:
                    try:
                        cb(value)
                    except Exception:
                        pass

        @self._player.property_observer("duration")
        def _on_duration(_name: str, value: float | None) -> None:
            if value is not None:
                for cb in self._on_duration_change:
                    try:
                        cb(value)
                    except Exception:
                        pass

        @self._player.event_callback("end-file")
        def _on_end_file(event) -> None:
            # Check if it ended naturally (EOF)
            try:
                ev_dict = event.as_dict()
                reason = ev_dict.get("reason")
                # 0 is MpvEventEndFile.EOF, b'eof' is the string representation
                if reason not in (0, b'eof'):
                    return
            except Exception:
                pass

            # Skip if the user explicitly stopped playback
            if self._user_stopped:
                self._user_stopped = False
                return
            for cb in self._on_track_end:
                try:
                    cb()
                except Exception:
                    pass

    # -- Playback controls ----------------------------------------------------

    def play(self, url: str) -> None:
        """Start playing a URL (replaces current track)."""
        self._user_stopped = False
        self._player.play(url)

    def stop(self) -> None:
        """Stop playback without triggering track-end callbacks."""
        self._user_stopped = True
        try:
            self._player.command("stop")
        except Exception:
            pass

    def toggle_pause(self) -> None:
        """Toggle between paused and playing."""
        try:
            self._player.pause = not self._player.pause
        except Exception:
            pass

    @property
    def paused(self) -> bool:
        """Whether playback is currently paused."""
        try:
            return bool(self._player.pause)
        except Exception:
            return True

    @paused.setter
    def paused(self, value: bool) -> None:
        try:
            self._player.pause = value
        except Exception:
            pass

    # -- Seeking --------------------------------------------------------------

    def seek(self, seconds: float, relative: bool = True) -> None:
        """Seek forward/backward in the current track.

        Args:
            seconds: Seconds to seek (negative for backward).
            relative: If True, seek relative to current position.
        """
        mode = "relative" if relative else "absolute"
        try:
            self._player.command("seek", seconds, mode)
        except Exception:
            pass

    # -- Volume ---------------------------------------------------------------

    @property
    def volume(self) -> float:
        """Current volume level (0–150)."""
        try:
            return self._player.volume or 75.0
        except Exception:
            return 75.0

    @volume.setter
    def volume(self, value: float) -> None:
        try:
            self._player.volume = max(0, min(150, value))
        except Exception:
            pass

    # -- Position / Duration --------------------------------------------------

    @property
    def position(self) -> float:
        """Current playback position in seconds."""
        try:
            return self._player.time_pos or 0.0
        except Exception:
            return 0.0

    @property
    def duration(self) -> float:
        """Duration of the current track in seconds."""
        try:
            return self._player.duration or 0.0
        except Exception:
            return 0.0

    # -- Callback registration ------------------------------------------------

    def on_time_change(self, callback: Callable[[float], None]) -> None:
        """Register a callback for playback position updates (~10/s)."""
        self._on_time_change.append(callback)

    def on_duration_change(self, callback: Callable[[float], None]) -> None:
        """Register a callback for when track duration is known."""
        self._on_duration_change.append(callback)

    def on_track_end(self, callback: Callable[[], None]) -> None:
        """Register a callback for when a track finishes naturally."""
        self._on_track_end.append(callback)

    # -- Lifecycle ------------------------------------------------------------

    def shutdown(self) -> None:
        """Release mpv resources. Call on app exit."""
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._player.terminate()
        except Exception:
            pass
