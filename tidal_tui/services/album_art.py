"""Album art rendering using chafa."""
from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path


CACHE_DIR = Path.home() / ".cache" / "tuidal" / "art"


def render_album_art(image_url: str, width: int = 20, height: int = 10) -> str:
    """Download album art and render it as terminal text using chafa CLI.
    
    Downloads are cached locally to avoid hitting the network repeatedly.
    Requires 'chafa' binary installed on the system.
    """
    if not image_url:
        return _render_fallback(width, height, "No Art")

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.md5(image_url.encode()).hexdigest()
        cached_path = CACHE_DIR / f"{cache_key}.jpg"

        if not cached_path.exists():
            urllib.request.urlretrieve(image_url, cached_path)

        result = subprocess.run(
            [
                "chafa",
                "--format", "symbols",
                "--symbols", "block",
                "--size", f"{width}x{height}",
                "--colors", "truecolor",
                "--dither", "ordered",
                str(cached_path),
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip("\n")
    except Exception:
        pass

    return _render_fallback(width, height, "No Art")


def _render_fallback(width: int, height: int, text: str) -> str:
    """Render a text box when art is unavailable or chafa is not installed."""
    lines = []
    # Adjust width to account for char aspect ratio (usually 2:1)
    w = max(4, width * 2)
    h = max(3, height)
    
    top = "┌" + "─" * (w - 2) + "┐"
    bottom = "└" + "─" * (w - 2) + "┘"
    empty = "│" + " " * (w - 2) + "│"
    
    text = text[: w - 4]
    padding = (w - 2 - len(text)) // 2
    text_line = "│" + " " * padding + text + " " * (w - 2 - padding - len(text)) + "│"
    
    lines.append(top)
    mid_idx = h // 2
    for i in range(1, h - 1):
        if i == mid_idx:
            lines.append(text_line)
        else:
            lines.append(empty)
    lines.append(bottom)
    
    return "\n".join(lines)
