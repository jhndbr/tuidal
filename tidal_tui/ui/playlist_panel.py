"""Playlist panel renderer — scrollable list of playlists with cursor highlight."""
from __future__ import annotations

from rich.text import Text

from tidal_tui.models import PlaylistInfo


def render_playlist_panel(
    playlists: list[PlaylistInfo],
    cursor: int,
    active: bool,
    error: str = "",
    max_rows: int | None = None,
) -> Text:
    """Render the playlist list with cursor highlighting and scrollbar.

    Args:
        playlists: Available playlists.
        cursor:    Currently highlighted index.
        active:    Whether this panel has focus.
        error:     Error message to display when playlists failed to load.
        max_rows:  Maximum rows to use for the list.  When set the list
                   scrolls to keep the cursor visible.
    """
    result = Text()

    if not playlists and error:
        result.append("  ⚠ Error\n", style="warning")
        short = error if len(error) <= 70 else error[:67] + "..."
        result.append(f"  {short}\n\n", style="dim")
        result.append("  Press ", style="dim")
        result.append("/", style="bold cyan")
        result.append(" to search\n", style="dim")
        result.append("  Press ", style="dim")
        result.append("R", style="bold cyan")
        result.append(" to retry", style="dim")
        return result

    if not playlists:
        result.append("  Loading...", style="dim")
        return result

    # -- Viewport: scroll to keep cursor in view ------------------------------
    total_len = len(playlists)
    if max_rows is not None and total_len > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, total_len - max_rows)
        visible = list(enumerate(playlists))[start : start + max_rows]

        # Calculate scrollbar details
        thumb_height = max(1, int(max_rows * max_rows / total_len))
        max_start = total_len - max_rows
        if max_start > 0:
            thumb_start = int(start * (max_rows - thumb_height) / max_start)
        else:
            thumb_start = 0
    else:
        visible = list(enumerate(playlists))
        start = 0
        max_rows = total_len

    for idx_in_visible, (i, pl) in enumerate(visible):
        count = f" ({pl.num_tracks})" if pl.num_tracks else ""
        label = f"  {'▸' if i == cursor else '◦'} {pl.name}{count}"

        line = Text()
        if i == cursor and active:
            line.append(label, style="sidebar.selected")
        elif i == cursor:
            line.append(label, style="sidebar.hover")
        else:
            line.append(label, style="sidebar.item")

        # Sidebar width is 30. Inner width is 28 (borders).
        # We pad the label to 26 cells to leave 1 cell for scrollbar and 1 cell for padding.
        line.truncate(26)
        line.pad_right(26)

        # Append scrollbar or spacing
        if max_rows is not None and total_len > max_rows:
            is_thumb = (thumb_start <= idx_in_visible < thumb_start + thumb_height)
            if is_thumb:
                line.append("█", style="bold cyan")
            else:
                line.append("│", style="bright_black")
        else:
            line.append(" ")

        result.append(line)
        if idx_in_visible < len(visible) - 1:
            result.append("\n")

    return result
