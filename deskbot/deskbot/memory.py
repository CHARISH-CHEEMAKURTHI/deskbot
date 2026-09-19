"""Rolling conversation memory, shared by every chat channel.

Keyed by "who you're talking to" -- a phone number for WhatsApp, the
literal "voice" for spoken conversation -- so each channel keeps its own
thread without knowing anything about the others. Kept on disk so the bot
still remembers yesterday's conversation after a restart.
"""

from __future__ import annotations

import json
import threading

from .config import CONFIG_DIR

HISTORY_PATH = CONFIG_DIR / "chat_history.json"

_lock = threading.Lock()


def _load_all() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(data, indent=2))
    except OSError as exc:
        print(f"[deskbot] could not save chat history: {exc}")


def load(who: str) -> list[tuple[str, str]]:
    """Past turns as (role, text) pairs, oldest first; role is user/bot."""
    with _lock:
        data = _load_all()
    return [tuple(turn) for turn in data.get(who, [])]


def append(cfg, who: str, user_text: str, bot_text: str) -> None:
    turns = int(getattr(cfg, "chat_memory_turns", 20))
    with _lock:
        data = _load_all()
        data.setdefault(who, [])
        data[who].append(["user", user_text])
        data[who].append(["bot", bot_text])
        data[who] = data[who][-turns * 2 :]
        _save_all(data)
