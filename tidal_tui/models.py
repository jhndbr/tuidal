"""Data models for the Tidal TUI player.

Pure data containers with no dependency on external libraries.
This keeps the domain model clean, testable, and decoupled from
both tidalapi and Textual.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


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


class SearchType(Enum):
    """Type of search to perform."""

    ALL = "all"
    TRACKS = "tracks"
    ARTISTS = "artists"
    ALBUMS = "albums"


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


@dataclass(frozen=True)
class ArtistInfo:
    """Immutable representation of a search result artist."""

    id: str
    name: str

    @property
    def display_label(self) -> str:
        return self.name


@dataclass(frozen=True)
class AlbumInfo:
    """Immutable representation of a search result album."""

    id: str
    name: str
    artist: str
    num_tracks: int = 0
    duration_seconds: float = 0.0
    year: int | None = None

    @property
    def duration_display(self) -> str:
        """Format duration as M:SS for display."""
        total = int(self.duration_seconds)
        minutes, seconds = divmod(total, 60)
        return f"{minutes}:{seconds:02d}"

    @property
    def display_label(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.name}"
        return self.name


# Union type for search results that can appear in the content panel
SearchResultItem = Union[TrackInfo, ArtistInfo, AlbumInfo]


@dataclass
class QueueState:
    """Mutable playback queue with shuffle and repeat support.

    Manages track ordering and navigation (next/prev/select).
    Shuffle is implemented via a pre-generated shuffled index list,
    so every track plays exactly once before any repeats.
    Designed to be owned by the app layer and queried by widgets.
    """

    tracks: list[TrackInfo] = field(default_factory=list)
    current_index: int = -1  # position index into _play_order
    shuffle: bool = False
    repeat: RepeatMode = RepeatMode.OFF

    # Internal: the order in which tracks will be played.
    # In normal mode: [0, 1, 2, ..., N-1]
    # In shuffle mode: a random permutation of the above
    _play_order: list[int] = field(default_factory=list, repr=False)

    # -- Current track --

    @property
    def current_track(self) -> TrackInfo | None:
        """Currently active track, or None if queue is empty/unstarted."""
        if not self._play_order or not (0 <= self.current_index < len(self._play_order)):
            return None
        track_idx = self._play_order[self.current_index]
        if 0 <= track_idx < len(self.tracks):
            return self.tracks[track_idx]
        return None

    @property
    def current_track_real_index(self) -> int:
        """Real index into self.tracks for the current track (-1 if none)."""
        if not self._play_order or not (0 <= self.current_index < len(self._play_order)):
            return -1
        return self._play_order[self.current_index]

    # -- Navigation helpers --

    @property
    def has_next(self) -> bool:
        return self.next_index is not None

    @property
    def has_prev(self) -> bool:
        return self.prev_index is not None

    @property
    def next_index(self) -> int | None:
        """Order-position index of the next track, respecting repeat mode.

        Returns a position index into _play_order (NOT a direct track index).
        """
        if not self._play_order:
            return None
        if self.repeat == RepeatMode.ONE:
            return self.current_index
        nxt = self.current_index + 1
        if nxt >= len(self._play_order):
            return 0 if self.repeat == RepeatMode.ALL else None
        return nxt

    @property
    def prev_index(self) -> int | None:
        """Order-position index of the previous track, respecting repeat mode."""
        if not self._play_order:
            return None
        if self.repeat == RepeatMode.ONE:
            return self.current_index
        prev = self.current_index - 1
        if prev < 0:
            return len(self._play_order) - 1 if self.repeat == RepeatMode.ALL else None
        return prev

    @property
    def next_track(self) -> TrackInfo | None:
        """Peek at the next track without advancing the queue."""
        idx = self.next_index
        if idx is None:
            return None
        track_idx = self._play_order[idx]
        if 0 <= track_idx < len(self.tracks):
            return self.tracks[track_idx]
        return None

    # -- Internal helpers --

    def _rebuild_play_order(self) -> None:
        """Rebuild _play_order based on current shuffle setting."""
        n = len(self.tracks)
        order = list(range(n))
        if self.shuffle:
            random.shuffle(order)
        self._play_order = order

    def _order_index_for_track(self, track_real_index: int) -> int:
        """Find the position in _play_order for a given real track index."""
        try:
            return self._play_order.index(track_real_index)
        except ValueError:
            return 0

    # -- Mutations --

    def set_tracks(self, tracks: list[TrackInfo]) -> None:
        """Replace the entire queue with new tracks."""
        self.tracks = list(tracks)
        self.current_index = -1
        self._rebuild_play_order()

    def select(self, real_index: int) -> TrackInfo | None:
        """Jump to a specific track by its real index in self.tracks."""
        if 0 <= real_index < len(self.tracks):
            self.current_index = self._order_index_for_track(real_index)
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
        """Toggle shuffle on/off.

        When enabling shuffle, rebuilds the play order as a random permutation
        starting from the current track to preserve continuity.
        When disabling, reverts to sequential order preserving the current track.
        """
        self.shuffle = not self.shuffle
        current_real = self.current_track_real_index
        self._rebuild_play_order()
        # Re-anchor current_index to the same real track after reordering
        if current_real >= 0:
            self.current_index = self._order_index_for_track(current_real)
        return self.shuffle
