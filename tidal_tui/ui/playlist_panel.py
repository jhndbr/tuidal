"""Playlist panel renderer — scrollable list of playlists with cursor highlight."""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from tidal_tui.models import PlaylistInfo

# Usable cell width inside the sidebar panel.
# Sidebar column = 30, minus 2 border chars (ROUNDED box) = 28 inner cells.
_INNER_WIDTH = 28


def _strip_wide(text: str) -> str:
    """Remove any character that occupies more than 1 terminal cell (emoji, CJK…)."""
    return "".join(ch for ch in text if cell_len(ch) == 1)


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
        max_rows:  Maximum rows to use for the list.
    """
    result = Text()

    if not playlists and error:
        result.append("  ⚠ Error\n", style="warning")
        short = error[:60] + "…" if len(error) > 60 else error
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

    # -- Viewport: line-by-line scroll -----------------------------------------
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

        # Strip wide chars so len() == display width for the rest of the row
        name = _strip_wide(pl.name)

        # Count badge (pure ASCII, len == display width)
        count_str = f" {pl.num_tracks}" if pl.num_tracks else ""
        count_w = len(count_str)

        # " ▶ " or "   " → 3 cells (all single-width)
        prefix_w = 3
        max_name = _INNER_WIDTH - prefix_w - count_w

        if len(name) > max_name:
            name = name[: max_name - 1] + "…"

        # Pad name to fill exactly max_name cells
        name = name.ljust(max_name)

        line = Text(no_wrap=True)

        if is_cursor and active:
            line.append(" ▶ ", style="bold cyan")
            line.append(name, style="bold white")
            if count_str:
                line.append(count_str, style="bold bright_black")
        elif is_cursor:
            line.append(" ▶ ", style="white")
            line.append(name, style="white")
            if count_str:
                line.append(count_str, style="bright_black")
        else:
            line.append("   ")
            line.append(name, style="bright_black")
            if count_str:
                line.append(count_str, style="bright_black")

        result.append(line)
        if idx_in_visible < len(visible) - 1:
            result.append("\n")

    return result
