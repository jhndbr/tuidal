"""Layout builder — composes all panels into the full-screen UI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.layout import Layout
from rich.panel import Panel
from rich import box
from rich.text import Text

from tidal_tui.theme import console
from tidal_tui.ui.now_playing import render_now_playing
from tidal_tui.ui.playlist_panel import render_playlist_panel
from tidal_tui.ui.track_panel import render_track_table
from tidal_tui.ui.art_panel import render_art_panel_content

if TYPE_CHECKING:
    from tidal_tui.app import AppState

# Rows dedicated to album art inside the sidebar (must match _ART_HEIGHT in app.py)
_ART_HEIGHT = 12
# Minimum terminal height required to show art alongside playlists
_MIN_TERM_FOR_ART = 30


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
        state:       Current application state.
        term_height: Terminal height for viewport calculations.
    """
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="main"),
        Layout(name="footer", size=1),
    )

    # -- Header
    layout["header"].update(_render_header(state))

    # Split main body horizontally into left (sidebar) and right (content) columns
    layout["main"].split_row(
        Layout(name="left_col", size=30),
        Layout(name="right_col"),
    )

    # Split Left Column vertically (Playlists on top, Cover on bottom)
    show_art = term_height >= _MIN_TERM_FOR_ART
    if show_art:
        layout["left_col"].split_column(
            Layout(name="playlists"),
            Layout(name="cover", size=14),
        )
    else:
        layout["left_col"].split_column(
            Layout(name="playlists"),
        )

    # Split Right Column vertically (Tracks on top, Now Playing on bottom)
    layout["right_col"].split_column(
        Layout(name="tracks"),
        Layout(name="now_playing", size=4),
    )

    # Calculate exact heights for viewport scrollable lists
    main_height = max(5, term_height - 2)

    if show_art:
        playlists_layout_height = max(2, main_height - 14)
    else:
        playlists_layout_height = main_height

    # Panel overhead: top-border(1) + padding-top(1) + padding-bottom(1) + bottom-border(1) = 4
    max_playlist_rows = max(1, playlists_layout_height - 4)

    playlist_content = render_playlist_panel(
        playlists=state.playlists,
        cursor=state.playlist_cursor,
        active=state.active_panel == "sidebar",
        error=state.sidebar_error,
        max_rows=max_playlist_rows,
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

    # Render Cover Panel if terminal height allows it
    if show_art:
        art_content = render_art_panel_content(
            art_text=state.art_text,
            width=26,  # 30 column width - 2 borders - 2 padding
            height=12,
            is_loading=(state.playing_id is not None and state.art_text is None),
        )
        layout["cover"].update(
            Panel(
                art_content,
                title="Cover",
                title_align="left",
                border_style="border",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

    # -- Content panel
    tracks_layout_height = max(2, main_height - 4)
    # Deduct panel borders (2), table headers/separators (2), and optional title (1)
    overhead = 5 if state.playlist_name else 4
    max_track_rows = max(1, tracks_layout_height - overhead)

    track_table = render_track_table(
        tracks=state.tracks,
        playlist_name=state.playlist_name,
        cursor=state.track_cursor,
        playing_id=state.playing_id,
        active=state.active_panel == "content",
        favorite_track_ids=state.favorite_track_ids,
        max_rows=max_track_rows,
        search_results_mode=state.search_results_mode,
        search_results_artists=state.search_results_artists,
        search_results_albums=state.search_results_albums,
    )
    layout["tracks"].update(
        Panel(
            track_table,
            border_style="track.header" if state.active_panel == "content" else "border",
            box=box.ROUNDED,
            padding=(0, 0),
        )
    )

    # -- Now Playing Panel (aligned with the track list)
    right_col_width = max(40, console.width - 30)
    np_bar_width = max(15, right_col_width - 32)

    np_content = render_now_playing(
        track_title=state.track_title,
        position=state.position,
        duration=state.duration,
        volume=state.volume,
        is_paused=state.is_paused,
        bar_width=np_bar_width,
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
