"""Rich theme for Tidal CLI — ANSI terminal-native colors.

Uses color_system="256" which emits standard 256-color ANSI escape codes.
Colors 0-15 in the 256-color cube are identical to the terminal's 16 basic
ANSI colors, so theme colors like "cyan" / "bold yellow" / "bright_black"
still render through the terminal's own palette (Catppuccin, Dracula, etc.).
Using "256" (not "standard") is required to correctly display chafa's
256-color album art without color degradation.
"""
from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

PLAYER_THEME = Theme(
    {
        # -- Header
        "header": "bold cyan",
        "header.icon": "magenta",
        # -- Sidebar (playlists)
        "sidebar.title": "bold magenta",
        "sidebar.item": "bright_black",
        "sidebar.selected": "bold cyan",
        "sidebar.hover": "white",
        # -- Track list
        "track.header": "bold blue",
        "track.column": "bold cyan",
        "track.normal": "default",
        "track.playing": "bold yellow",
        "track.selected": "bold white on blue",
        "track.number": "bright_black",
        # -- Now playing
        "np.title": "bold white",
        "np.icon.play": "green",
        "np.icon.pause": "yellow",
        "np.time": "bright_black",
        "np.bar": "cyan",
        "np.bar.bg": "bright_black",
        "np.volume": "bright_black",
        # -- General
        "border": "bright_black",
        "dim": "bright_black",
        "footer": "bright_black",
        "footer.key": "bold cyan",
        "footer.sep": "bright_black",
        "success": "green",
        "error": "bold red",
        "warning": "yellow",
    }
)

console = Console(
    theme=PLAYER_THEME,
    highlight=False,
    color_system="256",  # 256-color: required for chafa art + palette-compatible basic colors
)
