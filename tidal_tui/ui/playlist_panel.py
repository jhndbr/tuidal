"""Playlist panel renderer — list of playlists with cursor."""
from __future__ import annotations

from rich.text import Text

from tidal_tui.models import PlaylistInfo


def render_playlist_panel(
    playlists: list[PlaylistInfo],
    cursor: int,
    active: bool,
) -> Text:
    """Render the playlist list with cursor highlighting.

    Args:
        playlists: Available playlists.
        cursor: Currently highlighted index.
        active: Whether this panel has focus.
    """
    result = Text()

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
