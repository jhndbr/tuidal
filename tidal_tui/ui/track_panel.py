"""Track panel renderer — table of tracks with playing indicator."""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from tidal_tui.models import TrackInfo


def render_track_table(
    tracks: list[TrackInfo],
    playlist_name: str,
    cursor: int,
    playing_id: str | None,
    active: bool,
    max_rows: int | None = None,
) -> Table:
    """Render tracks as a Rich Table.

    Args:
        tracks: Tracks to display.
        playlist_name: Name of the current playlist (shown in header).
        cursor: Currently highlighted row index.
        playing_id: Track ID currently playing (gets ▶ indicator).
        active: Whether this panel has focus.
        max_rows: Maximum rows to display (for viewport scrolling).
    """
    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=True,
        padding=(0, 1),
        header_style="track.column",
        title=f"♫ {playlist_name}" if playlist_name else None,
        title_style="track.header",
        title_justify="left",
    )

    table.add_column("#", width=4, justify="right", style="track.number")
    table.add_column("Title", ratio=3, no_wrap=True)
    table.add_column("Artist", ratio=2, no_wrap=True)
    table.add_column("Album", ratio=2, no_wrap=True)
    table.add_column("Time", width=6, justify="right", style="track.number")

    if not tracks:
        return table

    # Viewport scrolling: show a window of tracks around the cursor
    if max_rows and len(tracks) > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, len(tracks) - max_rows)
        end = start + max_rows
        visible = list(enumerate(tracks))[start:end]
    else:
        visible = list(enumerate(tracks))

    # Remove duplicate tracks for display
    seen: set[str] = set()
    for i, track in visible:
        if track.id in seen:
            continue
        seen.add(track.id)

        is_playing = track.id == playing_id
        is_selected = i == cursor and active

        # Number column
        if is_playing:
            num = Text("▶", style="np.icon.play")
        else:
            num = Text(str(track.track_number))

        # Row style
        if is_selected:
            style = "track.selected"
        elif is_playing:
            style = "track.playing"
        else:
            style = "track.normal"

        table.add_row(
            num,
            Text(track.title, style=style, overflow="ellipsis"),
            Text(track.artist, style=style, overflow="ellipsis"),
            Text(track.album, style=style, overflow="ellipsis"),
            Text(track.duration_display),
            style=style,
        )

    return table
