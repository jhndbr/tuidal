"""Now-playing renderer — progress bar, track info, and volume."""
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
    """Render the complete now-playing section as Rich Text."""
    result = Text()

    # Line 1: play state + track title
    if is_paused:
        result.append("  ⏸ ", style="np.icon.pause")
    else:
        result.append("  ▶ ", style="np.icon.play")
    result.append(track_title, style="np.title")
    result.append("\n")

    # Line 2: time + progress bar + time + volume
    result.append(f"  {fmt_time(position)} ", style="np.time")
    result.append_text(render_progress_bar(position, duration, bar_width))
    result.append(f" {fmt_time(duration)}", style="np.time")
    result.append(f"   🔊 {volume}%", style="np.volume")

    return result
