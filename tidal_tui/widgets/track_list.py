"""Track list widget — DataTable showing tracks for the selected playlist."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from tidal_tui.models import TrackInfo


class TrackList(Widget):
    """Central panel displaying tracks in a tabular format.

    Emits ``TrackSelected`` when the user activates a row.
    """

    class TrackSelected(Message):
        """Fired when a track row is activated (Enter / click)."""

        def __init__(self, track_id: str) -> None:
            self.track_id = track_id
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tracks: list[TrackInfo] = []
        self._playing_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("  Select a playlist to begin", id="track-header")
        yield DataTable(id="track-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#track-table", DataTable)
        table.add_column("#", width=4, key="num")
        table.add_column("Title", width=None, key="title")
        table.add_column("Artist", width=None, key="artist")
        table.add_column("Album", width=None, key="album")
        table.add_column("Time", width=6, key="dur")
        table.cursor_type = "row"

    def load_tracks(
        self, tracks: list[TrackInfo], playlist_name: str
    ) -> None:
        """Replace the table contents with tracks from a new playlist."""
        self._tracks = list(tracks)
        self.query_one("#track-header", Static).update(
            f"  ♫ {playlist_name}  ({len(tracks)} tracks)"
        )

        table = self.query_one("#track-table", DataTable)
        table.clear()
        
        # Remove duplicate tracks (keep first occurrence)
        seen = set()
        unique_tracks = []
        for track in tracks:
            if track.id not in seen:
                seen.add(track.id)
                unique_tracks.append(track)
        
        for track in unique_tracks:
            indicator = (
                " ▶" if track.id == self._playing_id else str(track.track_number)
            )
            table.add_row(
                indicator,
                track.title,
                track.artist,
                track.album,
                track.duration_display,
                key=track.id,
            )

    def set_playing(self, track_id: str | None) -> None:
        """Update the '#' column to show ▶ next to the playing track."""
        table = self.query_one("#track-table", DataTable)
        old_id = self._playing_id
        self._playing_id = track_id

        # Reset the previous playing indicator
        if old_id:
            old_track = next((t for t in self._tracks if t.id == old_id), None)
            if old_track:
                try:
                    table.update_cell(old_id, "num", str(old_track.track_number))
                except Exception:
                    pass

        # Set the new playing indicator
        if track_id:
            try:
                table.update_cell(track_id, "num", " ▶")
            except Exception:
                pass

    # -- Events ---------------------------------------------------------------

    def on_data_table_row_selected(
        self, event: DataTable.RowSelected
    ) -> None:
        """Translate DataTable row activation into a domain message."""
        row_key = event.row_key
        track_id = str(row_key.value)
        self.post_message(self.TrackSelected(track_id=track_id))
