"""Entry point for the Tidal CLI player.

Run with:
    uv run tidal-tui
    uv run python -m tidal_tui
"""
from __future__ import annotations

import argparse
import sys
import os

from tidal_tui.daemon import is_daemon_running, stop_daemon, PID_FILE


def _daemonize():
    """Fork and detach to run as a background daemon."""
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "r") as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(os.devnull, "a+") as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tidal-tui",
        description="🎵 Tidal CLI Player — Client-Server architecture",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["daemon", "stop", "status"],
        help="Command to execute (default: run TUI client)",
    )
    parser.add_argument(
        "--quality",
        choices=["low", "high", "lossless", "max"],
        default="high",
        help="Audio streaming quality (default: high)",
    )
    parser.add_argument(
        "-d", "--detach",
        action="store_true",
        help="Run daemon in background (only valid for 'daemon' command)",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Clear saved session tokens",
    )
    args = parser.parse_args()

    # -- Logout ---------------------------------------------------------------

    if args.logout:
        from tidal_tui.config import clear_session
        clear_session()
        print("🗑️  Session cleared.")
        if args.command is None:
            sys.exit(0)

    # -- Commands -------------------------------------------------------------

    if args.command == "status":
        if is_daemon_running():
            print(f"✅ Daemon is running (PID: {PID_FILE.read_text().strip()})")
        else:
            print("❌ Daemon is not running.")
        sys.exit(0)

    elif args.command == "stop":
        stop_daemon()
        sys.exit(0)

    elif args.command == "daemon":
        if is_daemon_running():
            print("❌ Daemon is already running.")
            sys.exit(1)

        try:
            import mpv  # noqa: F401
        except (ImportError, OSError) as exc:
            print(f"❌ python-mpv / libmpv not available: {exc}", file=sys.stderr)
            sys.exit(1)
            
        try:
            import tidalapi  # noqa: F401
        except ImportError as exc:
            print(f"❌ tidalapi not available: {exc}", file=sys.stderr)
            sys.exit(1)

        if args.detach:
            _daemonize()

        from tidal_tui.daemon import TuidalDaemon
        import asyncio
        daemon = TuidalDaemon(quality=args.quality)
        asyncio.run(daemon.start())
        sys.exit(0)

    else:
        # Default: Run TUI Client
        from tidal_tui.app import TidalCLI
        app = TidalCLI(quality=args.quality)
        app.run()


if __name__ == "__main__":
    main()
