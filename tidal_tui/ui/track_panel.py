"""Track panel renderer — table of tracks with playing indicator.

Also handles rendering artist and album search results.
"""
from __future__ import annotations

from rich.table import Table
from rich.text import Text

from tidal_tui.models import AlbumInfo, ArtistInfo, TrackInfo


def _render_artist_table(
    artists: list[ArtistInfo],
    playlist_name: str,
    cursor: int,
    active: bool,
    max_rows: int | None = None,
) -> Table:
    """Render artist search results as a Rich Table."""
    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=True,
        padding=(0, 1),
        header_style="track.column",
        title=f"{playlist_name}" if playlist_name else None,
        title_style="track.header",
        title_justify="left",
    )

    table.add_column("#", width=4, justify="right", style="track.number")
    table.add_column("", width=3)
    table.add_column("Artist", ratio=4, no_wrap=True)
    table.add_column("", ratio=2, no_wrap=True)
    table.add_column("", width=6, justify="right")

    if not artists:
        return table

    # Viewport scrolling
    if max_rows and len(artists) > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, len(artists) - max_rows)
        end = start + max_rows
        visible = list(enumerate(artists))[start:end]
    else:
        visible = list(enumerate(artists))

    for i, artist in visible:
        is_selected = i == cursor and active

        num = Text(str(i + 1))
        icon = Text("🎤", style="bold")

        if is_selected:
            style = "track.selected"
        else:
            style = "track.normal"

        table.add_row(
            num,
            icon,
            Text(artist.name, style=style, overflow="ellipsis"),
            Text("Enter to browse", style="dim" if not is_selected else style),
            Text(""),
            style=style,
        )

    return table


def _render_album_table(
    albums: list[AlbumInfo],
    playlist_name: str,
    cursor: int,
    active: bool,
    max_rows: int | None = None,
) -> Table:
    """Render album search results as a Rich Table."""
    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=True,
        padding=(0, 1),
        header_style="track.column",
        title=f"{playlist_name}" if playlist_name else None,
        title_style="track.header",
        title_justify="left",
    )

    table.add_column("#", width=4, justify="right", style="track.number")
    table.add_column("Album", ratio=3, no_wrap=True)
    table.add_column("Artist", ratio=2, no_wrap=True)
    table.add_column("Year", width=6, justify="right")
    table.add_column("Tracks", width=6, justify="right", style="track.number")

    if not albums:
        return table

    # Viewport scrolling
    if max_rows and len(albums) > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, len(albums) - max_rows)
        end = start + max_rows
        visible = list(enumerate(albums))[start:end]
    else:
        visible = list(enumerate(albums))

    for i, album in visible:
        is_selected = i == cursor and active

        num = Text(str(i + 1))

        if is_selected:
            style = "track.selected"
        else:
            style = "track.normal"

        year_str = str(album.year) if album.year else ""
        tracks_str = str(album.num_tracks) if album.num_tracks else ""

        table.add_row(
            num,
            Text(f"💿 {album.name}", style=style, overflow="ellipsis"),
            Text(album.artist, style=style, overflow="ellipsis"),
            Text(year_str),
            Text(tracks_str),
            style=style,
        )

    return table


def _render_all_results_table(
    artists: list[ArtistInfo],
    albums: list[AlbumInfo],
    tracks: list[TrackInfo],
    playlist_name: str,
    cursor: int,
    playing_id: str | None,
    active: bool,
    favorite_track_ids: set[str],
    max_rows: int | None = None,
) -> Table:
    """Render combined search results (artists + albums + tracks) as a Rich Table."""
    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=True,
        padding=(0, 1),
        header_style="track.column",
        title=f"{playlist_name}" if playlist_name else None,
        title_style="track.header",
        title_justify="left",
    )

    table.add_column("#", width=4, justify="right", style="track.number")
    table.add_column("Type", width=8)
    table.add_column("Title / Name", ratio=3, no_wrap=True)
    table.add_column("Artist", ratio=2, no_wrap=True)
    table.add_column("Info", width=10, justify="right", style="track.number")

    # Build a combined list of rows
    rows: list[tuple[str, str, str, str, str, str | None]] = []
    # type, label, display_name, artist_or_info, extra, track_id_or_none

    for artist in artists:
        rows.append(("🎤", "Artist", artist.name, "", "→ browse", None))

    for album in albums:
        year_str = str(album.year) if album.year else ""
        rows.append(("💿", "Album", album.name, album.artist, year_str, None))

    for track in tracks:
        title_text = f"♥ {track.title}" if track.id in favorite_track_ids else track.title
        rows.append(("♪", "Track", title_text, track.artist, track.duration_display, track.id))

    if not rows:
        return table

    # Viewport scrolling
    if max_rows and len(rows) > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, len(rows) - max_rows)
        end = start + max_rows
        visible = list(enumerate(rows))[start:end]
    else:
        visible = list(enumerate(rows))

    for i, (icon, type_label, name, artist, extra, track_id) in visible:
        is_playing = track_id is not None and track_id == playing_id
        is_selected = i == cursor and active

        # Number column
        if is_playing:
            num = Text("▶", style="np.icon.play")
        else:
            num = Text(str(i + 1))

        # Row style
        if is_selected:
            style = "track.selected"
        elif is_playing:
            style = "track.playing"
        else:
            style = "track.normal"

        type_text = Text(f"{icon} {type_label}", style="bold magenta" if type_label != "Track" else style)

        table.add_row(
            num,
            type_text,
            Text(name, style=style, overflow="ellipsis"),
            Text(artist, style=style, overflow="ellipsis"),
            Text(extra),
            style=style,
        )

    return table


def render_track_table(
    tracks: list[TrackInfo],
    playlist_name: str,
    cursor: int,
    playing_id: str | None,
    active: bool,
    favorite_track_ids: set[str],
    max_rows: int | None = None,
    search_results_mode: str = "",
    search_results_artists: list | None = None,
    search_results_albums: list | None = None,
) -> Table:
    """Render tracks as a Rich Table.

    When search_results_mode is set, renders the appropriate search results
    instead of (or in addition to) the track list.

    Args:
        tracks: Tracks to display.
        playlist_name: Name of the current playlist (shown in header).
        cursor: Currently highlighted row index.
        playing_id: Track ID currently playing (gets ▶ indicator).
        active: Whether this panel has focus.
        favorite_track_ids: Set of track IDs marked as favorite.
        max_rows: Maximum rows to display (for viewport scrolling).
        search_results_mode: "tracks", "artists", "albums", "all", or "" for normal.
        search_results_artists: Artist search results.
        search_results_albums: Album search results.
    """
    artists = search_results_artists or []
    albums = search_results_albums or []

    # Dispatch to specialized renderers for search results
    if search_results_mode == "artists" and artists:
        return _render_artist_table(
            artists=artists,
            playlist_name=playlist_name,
            cursor=cursor,
            active=active,
            max_rows=max_rows,
        )

    if search_results_mode == "albums" and albums:
        return _render_album_table(
            albums=albums,
            playlist_name=playlist_name,
            cursor=cursor,
            active=active,
            max_rows=max_rows,
        )

    if search_results_mode == "all" and (artists or albums):
        return _render_all_results_table(
            artists=artists,
            albums=albums,
            tracks=tracks,
            playlist_name=playlist_name,
            cursor=cursor,
            playing_id=playing_id,
            active=active,
            favorite_track_ids=favorite_track_ids,
            max_rows=max_rows,
        )

    # Default: plain track table
    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=True,
        padding=(0, 1),
        header_style="track.column",
        title=f"{playlist_name}" if playlist_name else None,
        title_style="track.header",
        title_justify="left",
    )

    table.add_column("#", width=4, justify="right", style="track.number")
    table.add_column("Title", ratio=3, no_wrap=True)
    table.add_column("Artist", ratio=2, no_wrap=True)
    table.add_column("Album", ratio=2, no_wrap=True)
    table.add_column("Time", width=6, justify="right", style="track.number")

    if not tracks:
        return table

    # Viewport scrolling: show a window of tracks around the cursor
    if max_rows and len(tracks) > max_rows:
        half = max_rows // 2
        start = max(0, cursor - half)
        start = min(start, len(tracks) - max_rows)
        end = start + max_rows
        visible = list(enumerate(tracks))[start:end]
    else:
        visible = list(enumerate(tracks))

    # Remove duplicate tracks for display
    seen: set[str] = set()
    for i, track in visible:
        if track.id in seen:
            continue
        seen.add(track.id)

        is_playing = track.id == playing_id
        is_selected = i == cursor and active

        # Number column
        if is_playing:
            num = Text("▶", style="np.icon.play")
        else:
            num = Text(str(track.track_number))

        # Row style
        if is_selected:
            style = "track.selected"
        elif is_playing:
            style = "track.playing"
        else:
            style = "track.normal"

        title_text = f"♥ {track.title}" if track.id in favorite_track_ids else track.title

        table.add_row(
            num,
            Text(title_text, style=style, overflow="ellipsis"),
            Text(track.artist, style=style, overflow="ellipsis"),
            Text(track.album, style=style, overflow="ellipsis"),
            Text(track.duration_display),
            style=style,
        )

    return table
