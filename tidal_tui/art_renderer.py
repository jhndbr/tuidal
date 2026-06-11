"""Album art renderer — downloads cover art and renders it as Unicode block art via chafa.

Requires chafa to be installed:
    Arch:           sudo pacman -S chafa
    Debian/Ubuntu:  sudo apt install chafa
    Fedora:         sudo dnf install chafa

Two art sources (tried in order):
1. Tidal CDN URL (from track metadata, if populated).
2. iTunes Search API (https://itunes.apple.com/search) — always available,
   high-resolution (600×600), no authentication required.

Downloaded images are cached in ~/.config/tidal-tui/art/ so they are
reused across sessions without re-downloading.

Rendered ANSI text is cached in memory (per session) keyed by
(url_hash, width, height) so re-rendering the same panel is free.

WHY --colors 256 (NOT 16)
--------------------------
chafa --colors 16 opens /dev/tty directly to send OSC 4 queries
(``\x1b]4;n;?``) to ask the terminal what its 16 palette colors are.
The terminal responds with ``\x1b]4;n;rgb:RRRR/GGGG/BBBB\x07`` sequences
that end up in our process's stdin, which readchar picks up as garbage
"key presses". Using --colors 256 avoids all palette queries because the
256-color ANSI cube is fixed and standardized.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from rich.text import Text

_ART_CACHE_DIR = Path.home() / ".config" / "tidal-tui" / "art"

# In-memory render cache: (url_hash, width, height) -> Text
_RENDER_CACHE: dict[tuple[str, int, int], Text] = {}
_RENDER_LOCK = threading.Lock()

# Sentinel stored in cache when rendering failed so we don't retry
_FAILED = Text("__FAILED__")

# In-memory iTunes URL cache: "artist||album" -> art_url | None
_ITUNES_CACHE: dict[str, str | None] = {}
_ITUNES_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_itunes_art_url(artist: str, album: str, title: str = "") -> str | None:
    """Query the iTunes Search API for a high-resolution album cover URL.

    Tries "artist album" first, then "artist title" as fallback.
    Returns a 600×600 JPEG URL or None if nothing was found.
    """
    cache_key = f"{artist.lower()}||{album.lower() or title.lower()}"
    with _ITUNES_LOCK:
        if cache_key in _ITUNES_CACHE:
            return _ITUNES_CACHE[cache_key]

    url = _itunes_lookup(artist, album) or _itunes_lookup(artist, title)

    with _ITUNES_LOCK:
        _ITUNES_CACHE[cache_key] = url
    return url


def render_art(url: str | None, width: int = 26, height: int = 14) -> Text | None:
    """Render album art from a URL as a Rich Text object with ANSI 256-color blocks.

    Downloads the image (caching to disk) and renders it through chafa as
    256-color ANSI Unicode block art.  Uses 256-color mode to avoid OSC 4
    terminal palette queries that corrupt readchar's stdin.

    Args:
        url:    Direct URL to the album art image (JPEG or PNG).
        width:  Desired width in terminal columns.
        height: Desired height in terminal rows.

    Returns:
        A Rich ``Text`` object ready to embed in a panel, or ``None`` if the
        image could not be downloaded or rendered.
    """
    if not url:
        return None

    url_hash = hashlib.sha1(url.encode()).hexdigest()
    cache_key = (url_hash, width, height)

    with _RENDER_LOCK:
        cached = _RENDER_CACHE.get(cache_key)
        if cached is not None:
            return None if cached is _FAILED else cached

    img_path = _download_image(url, url_hash)
    if img_path is None:
        with _RENDER_LOCK:
            _RENDER_CACHE[cache_key] = _FAILED
        return None

    rendered = _chafa_render(img_path, width, height)

    with _RENDER_LOCK:
        _RENDER_CACHE[cache_key] = rendered if rendered is not None else _FAILED

    return rendered


def clear_render_cache() -> None:
    """Evict all in-memory rendered art (call on terminal resize)."""
    with _RENDER_LOCK:
        _RENDER_CACHE.clear()


# ---------------------------------------------------------------------------
# iTunes API helpers
# ---------------------------------------------------------------------------


def _itunes_lookup(artist: str, search_term: str) -> str | None:
    """Search iTunes for a track or album and return the art URL."""
    if not search_term.strip():
        return None
    query = f"{artist} {search_term}".strip()
    params = urllib.parse.urlencode({
        "term": query,
        "media": "music",
        "entity": "song",
        "limit": 5,
    })
    api_url = f"https://itunes.apple.com/search?{params}"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "tidal-tui/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        for r in results:
            art = r.get("artworkUrl100", "")
            if art:
                # Upscale: 100×100bb → 600×600bb for sharp rendering
                return art.replace("100x100bb", "600x600bb")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _download_image(url: str, url_hash: str) -> Path | None:
    """Download image to local cache and return its path, or None on failure."""
    _ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ext = ".png" if ".png" in url.lower() else ".jpg"
    img_path = _ART_CACHE_DIR / f"{url_hash}{ext}"

    if img_path.exists() and img_path.stat().st_size > 0:
        return img_path

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "tidal-tui/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp, open(img_path, "wb") as f:
            f.write(resp.read())
        return img_path
    except Exception:
        if img_path.exists():
            img_path.unlink(missing_ok=True)
        return None


# ---------------------------------------------------------------------------
# chafa rendering
# ---------------------------------------------------------------------------


def _chafa_render(img_path: Path, width: int, height: int) -> Text | None:
    """Call chafa to render an image as ANSI 256-color Unicode block art.

    --colors 256 uses the fixed 256-color ANSI cube.
    --probe off disables querying the terminal for its capabilities/OSC.
    --polite on inhibits escape sequences that might confuse other programs.
    --stretch fills the whole WxH area.
    --work 9 uses maximum quality detail level.
    """
    try:
        result = subprocess.run(
            [
                "chafa",
                "--size", f"{width}x{height}",
                "--format", "symbols",
                "--colors", "256",
                "--stretch",
                "--work", "9",
                "--probe", "off",
                "--polite", "on",
                str(img_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=8,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Text.from_ansi(result.stdout.rstrip("\n"))
    except FileNotFoundError:
        return _placeholder_no_chafa(width, height)
    except subprocess.TimeoutExpired:
        pass
    return None


def _placeholder_no_chafa(width: int, height: int) -> Text:
    """Render a placeholder when chafa is not installed."""
    t = Text()
    mid = height // 2
    t.append("╭" + "─" * (width - 2) + "╮\n", style="bright_black")
    for row in range(1, height - 1):
        if row == mid - 1:
            icon = "🎵"
            pad_l = (width - 4) // 2
            pad_r = width - 4 - pad_l
            t.append("│" + " " * pad_l + icon + " " * pad_r + "│\n", style="bright_black")
        elif row == mid:
            msg = "install chafa"
            pad_l = (width - 2 - len(msg)) // 2
            pad_r = width - 2 - len(msg) - pad_l
            t.append("│" + " " * pad_l, style="bright_black")
            t.append(msg, style="dim italic")
            t.append(" " * pad_r + "│\n", style="bright_black")
        elif row == mid + 1:
            msg = "for cover art"
            pad_l = (width - 2 - len(msg)) // 2
            pad_r = width - 2 - len(msg) - pad_l
            t.append("│" + " " * pad_l, style="bright_black")
            t.append(msg, style="dim italic")
            t.append(" " * pad_r + "│\n", style="bright_black")
        else:
            t.append("│" + " " * (width - 2) + "│\n", style="bright_black")
    t.append("╰" + "─" * (width - 2) + "╯", style="bright_black")
    return t
