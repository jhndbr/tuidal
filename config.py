"""Configuration and session persistence for Tidal TUI.

Stores settings and OAuth tokens in ~/.config/tidal-tui/.
Tokens are saved as plain JSON — if security is a concern,
this can be extended with keyring or encryption later.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


CONFIG_DIR = Path.home() / ".config" / "tidal-tui"
SESSION_FILE = CONFIG_DIR / "session.json"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class AppConfig:
    """User-facing application settings."""

    audio_quality: str = "HIGH"
    volume: int = 75

    @classmethod
    def load(cls) -> AppConfig:
        """Load config from disk, or return defaults."""
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                valid = {
                    k: v for k, v in data.items() if k in cls.__dataclass_fields__
                }
                return cls(**valid)
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        return cls()

    def save(self) -> None:
        """Persist config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Session token management
# ---------------------------------------------------------------------------


def _serialize_expiry_time(expiry_time: datetime | float | None) -> str | float | None:
    if isinstance(expiry_time, datetime):
        return expiry_time.isoformat()
    return expiry_time


def _parse_expiry_time(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def save_session_tokens(
    token_type: str,
    access_token: str,
    refresh_token: str | None,
    expiry_time: datetime | float | None,
) -> None:
    """Save OAuth session tokens to disk for later restoration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "token_type": token_type,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expiry_time": _serialize_expiry_time(expiry_time),
    }
    SESSION_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_session_tokens() -> dict | None:
    """Load saved session tokens, or None if unavailable/corrupt."""
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data["expiry_time"] = _parse_expiry_time(data.get("expiry_time"))
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def clear_session() -> None:
    """Remove saved session tokens (logout)."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
