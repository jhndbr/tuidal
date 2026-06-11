"""Now-playing renderer — progress bar, track info, volume, and mode status."""
from __future__ import annotations

from rich.text import Text


def fmt_time(seconds: float) -> str:
    """Format seconds as M:SS."""
    total = max(0, int(seconds))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"


def render_progress_bar(
    position: float, duration: float, width: int = 40
) -> Text:
    """Build a custom progress bar using box-drawing characters."""
    if duration <= 0:
        pct = 0.0
    else:
        pct = min(1.0, position / duration)
    filled = int(width * pct)
    bar = Text()
    bar.append("━" * filled, style="np.bar")
    bar.append("━" * (width - filled), style="np.bar.bg")
    return bar


def render_now_playing(
    track_title: str,
    position: float,
    duration: float,
    volume: int,
    is_paused: bool,
    bar_width: int = 40,
) -> Text:
    """Render the complete now-playing section as Rich Text.

    Produces 2 lines:
      1. Play state icon + track title
      2. Time elapsed + progress bar + total time + volume
    """
    result = Text()

    # Line 1: play state + track title
    if is_paused:
        result.append("  ⏸ ", style="np.icon.pause")
    else:
        result.append("  ▶ ", style="np.icon.play")
    max_title_len = max(20, bar_width + 20)
    truncated_title = track_title if len(track_title) <= max_title_len else track_title[:max_title_len - 3] + "..."
    result.append(truncated_title, style="np.title")
    result.append("\n")

    # Line 2: time + progress bar + time + volume
    result.append(f"  {fmt_time(position)} ", style="np.time")
    result.append_text(render_progress_bar(position, duration, bar_width))
    result.append(f" {fmt_time(duration)}", style="np.time")
    result.append(f"   🔊 {volume}%", style="np.volume")

    return result
