"""Playlist browser widget — sidebar listing all user playlists."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from tidal_tui.models import PlaylistInfo


class PlaylistBrowser(Widget):
    """Sidebar that displays the user's Tidal playlists.

    Emits ``PlaylistSelected`` when the user picks a playlist.
    """

    class PlaylistSelected(Message):
        """Fired when a playlist is chosen from the list."""

        def __init__(self, playlist_id: str, playlist_name: str) -> None:
            self.playlist_id = playlist_id
            self.playlist_name = playlist_name
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._playlists: dict[str, PlaylistInfo] = {}

    def compose(self) -> ComposeResult:
        yield Static("  PLAYLISTS", id="sidebar-title")
        yield ListView(id="playlist-list")

    def load_playlists(self, playlists: list[PlaylistInfo]) -> None:
        """Populate the list with playlists from Tidal."""
        lv = self.query_one("#playlist-list", ListView)
        lv.clear()
        self._playlists.clear()

        for pl in playlists:
            item_id = f"pl-{pl.id}"
            self._playlists[item_id] = pl
            count = f"  ({pl.num_tracks})" if pl.num_tracks else ""
            lv.append(
                ListItem(Label(f"▪ {pl.name}{count}"), id=item_id)
            )

    # -- Events ---------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Translate ListView selection into a domain-specific message."""
        item_id = event.item.id
        if item_id and item_id in self._playlists:
            pl = self._playlists[item_id]
            self.post_message(self.PlaylistSelected(pl.id, pl.name))
