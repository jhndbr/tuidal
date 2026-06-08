"""Layout builder — composes all panels into the full-screen UI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.layout import Layout
from rich.panel import Panel
from rich import box
from rich.text import Text

from tidal_tui.ui.now_playing import render_now_playing
from tidal_tui.ui.playlist_panel import render_playlist_panel
from tidal_tui.ui.track_panel import render_track_table

if TYPE_CHECKING:
    from tidal_tui.models import AppState


def _render_header(state: AppState) -> Text:
    """Render the header line."""
    header = Text()
    header.append(" ", style="header")
    header.append("Tidal CLI", style="header")
    
    if state.input_mode == "search":
        # Show search type selector
        type_labels = {"all": "All", "tracks": "Tracks", "artists": "Artists", "albums": "Albums"}
        type_name = type_labels.get(state.search_type.value, state.search_type.value)
        header.append("   [ ", style="bold yellow")
        header.append(f"{type_name}", style="bold magenta")
        header.append(" │ ", style="bold yellow")
        header.append(state.search_query, style="bold white")
        header.append("█", style="blink bold yellow")
        header.append(" ]", style="bold yellow")
        header.append("  Tab", style="bold cyan")
        header.append("=type", style="dim white")
    elif state.status_message:
        header.append(f"   {state.status_message}", style="dim white")
        
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
        ("/", "search"),
        ("f", "fav"),
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
        Layout(name="footer", size=1),
    )

    # -- Header
    layout["header"].update(_render_header(state))

    # -- Body: sidebar + content
    layout["body"].split_row(
        Layout(name="sidebar", size=30),
        Layout(name="content"),
    )

    # Split Sidebar
    layout["sidebar"].split_column(
        Layout(name="playlists"),
        Layout(name="album_art", size=16),
    )

    # Split Content
    layout["content"].split_column(
        Layout(name="track_list"),
        Layout(name="now_playing", size=5),
    )

    # -- Playlists
    playlist_content = render_playlist_panel(
        playlists=state.playlists,
        cursor=state.playlist_cursor,
        active=state.active_panel == "sidebar",
        error=state.sidebar_error,
    )
    layout["playlists"].update(
        Panel(
            playlist_content,
            title="Playlists",
            title_align="left",
            border_style="sidebar.title" if state.active_panel == "sidebar" else "border",
            box=box.ROUNDED,
            padding=(1, 0),
        )
    )

    # -- Album Art
    art = Text.from_ansi(state.album_art_text) if state.album_art_text else Text("\n" * 6 + " " * 8 + "No Art")
    layout["album_art"].update(
        Panel(
            art,
            border_style="border",
            box=box.ROUNDED,
            padding=(0, 0),
        )
    )

    # -- Track List
    body_height = max(5, term_height - 8)  # header(1) + footer(1) + np(5) + borders(~1)
    track_table = render_track_table(
        tracks=state.tracks,
        playlist_name=state.playlist_name,
        cursor=state.track_cursor,
        playing_id=state.playing_id,
        active=state.active_panel == "content",
        favorite_track_ids=state.favorite_track_ids,
        max_rows=body_height - 4,
        search_results_mode=state.search_results_mode,
        search_results_artists=state.search_results_artists,
        search_results_albums=state.search_results_albums,
    )
    layout["track_list"].update(
        Panel(
            track_table,
            border_style="track.header" if state.active_panel == "content" else "border",
            box=box.ROUNDED,
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
            box=box.ROUNDED,
            padding=(0, 0),
        )
    )

    # -- Footer
    layout["footer"].update(_render_footer(
        shuffle=state.shuffle,
        repeat=state.repeat_label,
    ))

    return layout
