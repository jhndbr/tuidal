"""Layout builder — composes all panels into the full-screen UI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from tidal_tui.ui.now_playing import render_now_playing
from tidal_tui.ui.playlist_panel import render_playlist_panel
from tidal_tui.ui.track_panel import render_track_table

if TYPE_CHECKING:
    from tidal_tui.app import AppState


def _render_header() -> Text:
    """Render the header line."""
    header = Text()
    header.append(" ♫ ", style="header.icon")
    header.append("Tidal CLI", style="header")
    return header


def _render_footer(shuffle: bool, repeat: str) -> Text:
    """Render the footer with keybindings and status."""
    footer = Text()
    footer.append("  ")
    keys = [
        ("space", "play/pause"),
        ("n", "next"),
        ("p", "prev"),
        ("s", f"shuffle {'on' if shuffle else 'off'}"),
        ("r", f"repeat {repeat}"),
        ("+/-", "vol"),
        ("[/]", "seek"),
        ("q", "quit"),
    ]
    for i, (key, desc) in enumerate(keys):
        footer.append(key, style="footer.key")
        footer.append(f" {desc}", style="footer")
        if i < len(keys) - 1:
            footer.append("  ·  ", style="footer.sep")
    return footer


def build_layout(state: AppState, term_height: int = 24) -> Layout:
    """Build the complete Rich Layout from the current app state.

    Args:
        state: Current application state.
        term_height: Terminal height for viewport calculations.
    """
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="body"),
        Layout(name="now_playing", size=5),
        Layout(name="footer", size=1),
    )

    # -- Header
    layout["header"].update(_render_header())

    # -- Body: sidebar + content
    layout["body"].split_row(
        Layout(name="sidebar", size=30),
        Layout(name="content"),
    )

    # Sidebar
    playlist_content = render_playlist_panel(
        playlists=state.playlists,
        cursor=state.playlist_cursor,
        active=state.active_panel == "sidebar",
    )
    layout["sidebar"].update(
        Panel(
            playlist_content,
            title="♫ Playlists",
            title_align="left",
            border_style="sidebar.title" if state.active_panel == "sidebar" else "border",
            padding=(1, 0),
        )
    )

    # Content
    body_height = max(5, term_height - 8)  # header(1) + np(5) + footer(1) + borders(~1)
    track_table = render_track_table(
        tracks=state.tracks,
        playlist_name=state.playlist_name,
        cursor=state.track_cursor,
        playing_id=state.playing_id,
        active=state.active_panel == "content",
        max_rows=body_height - 4,
    )
    layout["content"].update(
        Panel(
            track_table,
            border_style="track.header" if state.active_panel == "content" else "border",
            padding=(0, 0),
        )
    )

    # -- Now Playing
    bar_width = max(20, 50)  # reasonable default
    np_content = render_now_playing(
        track_title=state.track_title,
        position=state.position,
        duration=state.duration,
        volume=state.volume,
        is_paused=state.is_paused,
        bar_width=bar_width,
    )
    layout["now_playing"].update(
        Panel(
            np_content,
            border_style="border",
            padding=(0, 0),
        )
    )

    # -- Footer
    layout["footer"].update(_render_footer(
        shuffle=state.shuffle,
        repeat=state.repeat_label,
    ))

    return layout
