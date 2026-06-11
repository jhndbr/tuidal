"""Album art panel renderer — produces the content for the fixed Cover panel."""
from __future__ import annotations

from rich.text import Text


def render_art_panel_content(
    art_text: Text | None,
    width: int = 26,
    height: int = 14,
    is_loading: bool = False,
) -> Text:
    """Render album art or a placeholder into the Cover panel.

    Args:
        art_text:   Rendered art from chafa (Rich Text), or None.
        width:      Inner content width of the panel in columns.
        height:     Inner content height of the panel in rows.
        is_loading: True while the art download / chafa render is in progress.
    """
    if art_text is not None:
        return art_text

    # --- Placeholder ---------------------------------------------------------
    result = Text()
    mid = height // 2

    for row in range(height):
        if row == mid - 1:
            if is_loading:
                msg = "⏳ loading..."
                pad = (width - len(msg)) // 2
                result.append(" " * max(0, pad) + msg + "\n", style="dim")
            else:
                result.append("\n")
        elif row == mid:
            icon = "🎵"
            # emoji occupies 2 terminal cells
            pad_l = (width - 2) // 2
            pad_r = width - 2 - pad_l
            result.append(" " * pad_l + icon + " " * pad_r + "\n", style="dim magenta")
        elif row == mid + 1:
            if is_loading:
                result.append("\n")
            else:
                msg = "play a track"
                pad = (width - len(msg)) // 2
                result.append(" " * max(0, pad) + msg + "\n", style="dim")
        else:
            result.append("\n")

    return result
