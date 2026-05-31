"""Rich theme for Tidal CLI — ANSI terminal-native colors.

Uses color_system="standard" to emit pure ANSI escape codes.
This means 'cyan' becomes \\033[36m which the terminal renders
using its own palette (Catppuccin, Dracula, Gruvbox, etc.).
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
        "track.header": "bold green",
        "track.column": "bold bright_black italic",
        "track.normal": "default",
        "track.playing": "bold cyan",
        "track.selected": "bold cyan",
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
    color_system="standard",
)
