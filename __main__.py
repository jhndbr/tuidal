"""Entry point for the Tidal TUI player.

Run with:
    uv run tidal-tui
    uv run python -m tidal_tui
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tidal-tui",
        description="🎵 Tidal TUI Player — Browse and play Tidal playlists in your terminal",
    )
    parser.add_argument(
        "--quality",
        choices=["low", "high", "lossless", "max"],
        default="high",
        help="Audio streaming quality (default: high / AAC 320kbps)",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Clear saved session tokens and re-authenticate",
    )
    args = parser.parse_args()

    # -- Dependency checks ----------------------------------------------------

    try:
        import mpv  # noqa: F401
    except (ImportError, OSError) as exc:
        print(f"❌ python-mpv / libmpv not available: {exc}")
        print("   Install mpv:        sudo pacman -S mpv")
        print("   (python-mpv is installed via uv sync)")
        sys.exit(1)

    try:
        import tidalapi  # noqa: F401
    except ImportError as exc:
        print(f"❌ tidalapi not available: {exc}")
        print("   Run: uv sync")
        sys.exit(1)

    # -- Logout ---------------------------------------------------------------

    if args.logout:
        from tidal_tui.config import clear_session

        clear_session()
        print("🗑️  Session cleared.")

    # -- Authenticate before launching TUI ------------------------------------

    from tidal_tui.services.tidal_service import TidalService

    print("🔐 Connecting to Tidal...")
    service = TidalService(quality=args.quality)
    try:
        service.authenticate()
    except Exception as exc:
        print(f"❌ Authentication failed: {exc}")
        sys.exit(1)

    print("✅ Authenticated!")
    print("🎵 Launching player...")

    # -- Launch TUI -----------------------------------------------------------

    from tidal_tui.app import TidalTUI

    app = TidalTUI(tidal_service=service, quality=args.quality)
    app.run()


if __name__ == "__main__":
    main()
