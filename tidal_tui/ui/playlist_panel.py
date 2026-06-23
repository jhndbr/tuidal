"""Playlist panel renderer — scrollable list of playlists with cursor highlight."""
from __future__ import annotations

from rich.text import Text

from tidal_tui.models import PlaylistInfo

# Inner usable width of the sidebar panel.
# Sidebar column = 30, minus 2 border chars = 28, minus 2 padding chars = 26.
_INNER_WIDTH = 26


def render_playlist_panel(
    playlists: list[PlaylistInfo],
    cursor: int,
    active: bool,
    error: str = "",
    max_rows: int | None = None,
) -> Text:
    """Render the playlist list with cursor highlighting (no scrollbar).

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
        short = error if len(error) <= 60 else error[:57] + "…"
        result.append(f"  {short}\n\n", style="dim")
        result.append("  Press ", style="dim")
        result.append("/", style="bold cyan")
        result.append(" to search\n", style="dim")
        result.append("  Press ", style="dim")
        result.append("R", style="bold cyan")
        result.append(" to retry", style="dim")
        return result

    if not playlists:
        result.append("  Loading…", style="dim")
        return result

    # -- Viewport: line-by-line scroll (cursor near bottom edge when scrolling down)
    total_len = len(playlists)
    if max_rows is not None and total_len > max_rows:
        start = max(0, cursor - max_rows + 1)
        start = min(start, total_len - max_rows)
    else:
        start = 0
        max_rows = total_len

    visible = list(enumerate(playlists))[start : start + max_rows]

    for idx_in_visible, (i, pl) in enumerate(visible):
        is_cursor = i == cursor

        # Build icon + name portion
        icon = "▶" if is_cursor else " "

        # Truncate name to leave room for count badge
        count_str = f" {pl.num_tracks}" if pl.num_tracks else ""
        # Max name length = inner width - icon(1) - space(1) - count(len) - margin(1)
        max_name = _INNER_WIDTH - 3 - len(count_str)
        name = pl.name if len(pl.name) <= max_name else pl.name[: max_name - 1] + "…"

        line = Text(overflow="crop", no_wrap=True)

        if is_cursor and active:
            # Active focus: bright highlight
            line.append(f" {icon} ", style="bold cyan")
            line.append(name, style="bold white")
            if count_str:
                line.append(count_str, style="bold bright_black")
        elif is_cursor:
            # Panel unfocused but cursor row
            line.append(f" {icon} ", style="white")
            line.append(name, style="white")
            if count_str:
                line.append(count_str, style="bright_black")
        else:
            # Normal row
            line.append("   ", style="")
            line.append(name, style="bright_black")
            if count_str:
                line.append(count_str, style="bright_black")

        # Pad to full inner width so the highlight bar fills the whole row
        line.pad_right(_INNER_WIDTH)

        result.append(line)
        if idx_in_visible < len(visible) - 1:
            result.append("\n")

    return result
