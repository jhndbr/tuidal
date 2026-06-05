"""Playlist panel renderer — list of playlists with cursor."""
from __future__ import annotations

from rich.text import Text

from tidal_tui.models import PlaylistInfo


def render_playlist_panel(
    playlists: list[PlaylistInfo],
    cursor: int,
    active: bool,
    error: str = "",
) -> Text:
    """Render the playlist list with cursor highlighting.

    Args:
        playlists: Available playlists.
        cursor: Currently highlighted index.
        active: Whether this panel has focus.
        error: Error message to display when playlists failed to load.
    """
    result = Text()

    if not playlists and error:
        # Show error with a helpful hint
        result.append("  ⚠ Error\n", style="warning")
        # Truncate long error messages for the sidebar
        short_error = error
        if len(short_error) > 80:
            short_error = short_error[:77] + "..."
        result.append(f"  {short_error}\n\n", style="dim")
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

    for i, pl in enumerate(playlists):
        count = f" ({pl.num_tracks})" if pl.num_tracks else ""

        if i == cursor and active:
            result.append(f"  ▸ {pl.name}{count}", style="sidebar.selected")
        elif i == cursor:
            result.append(f"  ▸ {pl.name}{count}", style="sidebar.hover")
        else:
            result.append(f"  ◦ {pl.name}{count}", style="sidebar.item")

        if i < len(playlists) - 1:
            result.append("\n")

    return result
