"""Data models for the Tidal TUI player.

Pure data containers with no dependency on external libraries.
This keeps the domain model clean, testable, and decoupled from
both tidalapi and Textual.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PlayerState(Enum):
    """Current state of the audio player."""

    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    LOADING = "loading"


class RepeatMode(Enum):
    """Repeat mode for the playback queue."""

    OFF = "off"
    ALL = "all"
    ONE = "one"


@dataclass(frozen=True)
class TrackInfo:
    """Immutable representation of a single track.

    Decoupled from tidalapi — constructed from API responses
    but usable anywhere without importing tidalapi.
    """

    id: str
    title: str
    artist: str
    album: str
    duration_seconds: float
    album_art_url: str | None = None
    track_number: int = 0

    @property
    def duration_display(self) -> str:
        """Format duration as M:SS for display."""
        total = int(self.duration_seconds)
        minutes, seconds = divmod(total, 60)
        return f"{minutes}:{seconds:02d}"

    @property
    def display_label(self) -> str:
        """Short label: 'Artist — Title'."""
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title


@dataclass(frozen=True)
class PlaylistInfo:
    """Immutable representation of a playlist."""

    id: str
    name: str
    num_tracks: int
    description: str = ""
    image_url: str | None = None


@dataclass
class QueueState:
    """Mutable playback queue with shuffle and repeat support.

    Manages track ordering and navigation (next/prev/select).
    Designed to be owned by the app layer and queried by widgets.
    """

    tracks: list[TrackInfo] = field(default_factory=list)
    current_index: int = -1
    shuffle: bool = False
    repeat: RepeatMode = RepeatMode.OFF

    # -- Current track --

    @property
    def current_track(self) -> TrackInfo | None:
        """Currently active track, or None if queue is empty/unstarted."""
        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    # -- Navigation helpers --

    @property
    def has_next(self) -> bool:
        return self.next_index is not None

    @property
    def has_prev(self) -> bool:
        return self.prev_index is not None

    @property
    def next_index(self) -> int | None:
        """Index of the next track, respecting repeat mode."""
        if not self.tracks:
            return None
        if self.repeat == RepeatMode.ONE:
            return self.current_index
        nxt = self.current_index + 1
        if nxt >= len(self.tracks):
            return 0 if self.repeat == RepeatMode.ALL else None
        return nxt

    @property
    def prev_index(self) -> int | None:
        """Index of the previous track, respecting repeat mode."""
        if not self.tracks:
            return None
        if self.repeat == RepeatMode.ONE:
            return self.current_index
        prev = self.current_index - 1
        if prev < 0:
            return len(self.tracks) - 1 if self.repeat == RepeatMode.ALL else None
        return prev

    # -- Mutations --

    def set_tracks(self, tracks: list[TrackInfo]) -> None:
        """Replace the entire queue with new tracks."""
        self.tracks = list(tracks)
        self.current_index = -1

    def select(self, index: int) -> TrackInfo | None:
        """Jump to a specific track by index."""
        if 0 <= index < len(self.tracks):
            self.current_index = index
            return self.current_track
        return None

    def advance(self) -> TrackInfo | None:
        """Move to the next track and return it."""
        idx = self.next_index
        if idx is not None:
            self.current_index = idx
            return self.current_track
        return None

    def go_back(self) -> TrackInfo | None:
        """Move to the previous track and return it."""
        idx = self.prev_index
        if idx is not None:
            self.current_index = idx
            return self.current_track
        return None

    def toggle_repeat(self) -> RepeatMode:
        """Cycle: OFF → ALL → ONE → OFF."""
        cycle = [RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE]
        current = cycle.index(self.repeat)
        self.repeat = cycle[(current + 1) % len(cycle)]
        return self.repeat

    def toggle_shuffle(self) -> bool:
        """Toggle shuffle on/off."""
        self.shuffle = not self.shuffle
        return self.shuffle
