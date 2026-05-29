"""Now-playing bar — shows current track, progress, and volume."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ProgressBar, Static


class NowPlaying(Widget):
    """Bottom bar displaying playback status and progress.

    Reactive properties are set by the app layer (from mpv callbacks)
    and the watchers automatically update the child widgets.
    """

    track_title: reactive[str] = reactive("No track playing")
    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)
    volume_level: reactive[int] = reactive(75)
    is_paused: reactive[bool] = reactive(True)

    def compose(self) -> ComposeResult:
        yield Static("  ♫ No track playing", id="np-track-info")
        with Horizontal(id="np-progress-row"):
            yield Static(" 0:00 ", id="np-time-current")
            yield ProgressBar(
                total=100,
                show_eta=False,
                show_percentage=False,
                id="np-progress",
            )
            yield Static(" 0:00 ", id="np-time-total")
            yield Static(" 🔊 75% ", id="np-volume")

    # -- Reactive watchers ----------------------------------------------------

    def watch_track_title(self, value: str) -> None:
        icon = "⏸" if self.is_paused else "▶"
        try:
            self.query_one("#np-track-info", Static).update(
                f"  {icon}  {value}"
            )
        except Exception:
            pass

    def watch_is_paused(self, value: bool) -> None:
        icon = "⏸" if value else "▶"
        try:
            self.query_one("#np-track-info", Static).update(
                f"  {icon}  {self.track_title}"
            )
        except Exception:
            pass

    def watch_position(self, value: float) -> None:
        try:
            self.query_one("#np-time-current", Static).update(
                f" {self._fmt(value)} "
            )
        except Exception:
            pass
        if self.duration > 0:
            pct = min(100.0, (value / self.duration) * 100)
            try:
                self.query_one("#np-progress", ProgressBar).update(
                    progress=pct
                )
            except Exception:
                pass

    def watch_duration(self, value: float) -> None:
        try:
            self.query_one("#np-time-total", Static).update(
                f" {self._fmt(value)} "
            )
        except Exception:
            pass

    def watch_volume_level(self, value: int) -> None:
        try:
            self.query_one("#np-volume", Static).update(f" 🔊 {value}% ")
        except Exception:
            pass

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _fmt(seconds: float) -> str:
        """Format seconds as M:SS."""
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        return f"{m}:{s:02d}"
