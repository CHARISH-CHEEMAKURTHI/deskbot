"""Tunable settings for the desktop bot.

Values live in ~/.config/deskbot/config.json so you can tweak the bot's
personality without touching code. Missing keys fall back to defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "deskbot"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    # --- rendering -------------------------------------------------
    fps: int = 30
    bot_size: int = 110          # px, the bot's drawn box
    window_w: int = 260          # room for the speech bubble
    window_h: int = 230
    always_on_top: bool = True
    bypass_wm: bool = False      # try True if your WM refuses to keep it on top

    # --- colours (Celebi-ish graphite + warm orange) ---------------
    body_light: str = "#3a3f47"
    body_dark: str = "#22262c"
    accent: str = "#ff8b3d"
    visor: str = "#12151a"
    glow: str = "#ffd7b0"

    # --- movement --------------------------------------------------
    follow_speed: float = 5.0        # higher = snappier
    max_speed: float = 620.0         # px/sec
    stop_distance: float = 95.0      # how close it parks next to the cursor
    trail_distance: float = 80.0     # how far behind the cursor it walks

    # --- behaviour timings (seconds) -------------------------------
    cursor_idle_before_wander: float = 10.0
    cursor_idle_before_sleep: float = 75.0
    wander_interval: float = 8.0
    blink_interval: float = 4.5
    speech_duration: float = 3.5
    fast_cursor_speed: float = 1400.0   # px/sec that counts as "whoa"

    # --- personality ------------------------------------------------
    chatty: bool = True           # occasional speech bubbles
    follow_cursor: bool = True

    # --- phase 2: activity awareness --------------------------------
    activity_aware: bool = True        # watch system + foreground app, react
    activity_poll_interval: float = 3.0   # seconds between activity checks
    busy_cpu_percent: float = 60.0        # foreground app CPU%% counted as "working"
    system_busy_percent: float = 85.0     # overall CPU%% counted as "under load"
    loading_after_seconds: float = 6.0    # how long before that counts as "loading"
    stuck_after_seconds: float = 25.0     # how long before the bot gets impatient
    low_battery_percent: float = 20.0
    low_memory_percent: float = 90.0

    # --- phase 3: actions --------------------------------------------
    ollama_model: str = "llama3.1:8b"   # doubles as the intent classifier
    ollama_url: str = "http://localhost:11434"

    # SMTP creds for send_email -- leave blank and set DESKBOT_SMTP_USER /
    # DESKBOT_SMTP_PASSWORD instead if you'd rather not put a password in
    # this file. An app password, not your real one, if the provider offers it.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # send_whatsapp only ever messages people listed here -- lowercase name
    # -> phone number with country code, no "+" or spaces, e.g.
    # {"mom": "15551234567"}. Anyone not in this list is refused.
    whatsapp_contacts: dict = field(default_factory=dict)

    # --- two-way WhatsApp chat (official Business Cloud API) ----------
    # Off by default -- needs a one-time Meta Developer setup (see README).
    # This is separate from send_whatsapp above: that only ever sends
    # (via a plain wa.me link); this can also *receive*, which is why it
    # needs Meta's real API rather than an unofficial WhatsApp Web hack.
    whatsapp_business_enabled: bool = False
    whatsapp_access_token: str = ""     # or DESKBOT_WHATSAPP_ACCESS_TOKEN env var
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""     # a token *you* choose; must match Meta's webhook config
    whatsapp_webhook_port: int = 8765
    whatsapp_api_base: str = "https://graph.facebook.com/v20.0"
    # Only numbers in this list can chat with the bot at all -- anyone
    # else messaging your business number is silently ignored. Same
    # phone-number format as whatsapp_contacts (country code, no "+").
    whatsapp_allowed_numbers: list = field(default_factory=list)
    # How many past turns (per sender) to keep and feed back as context.
    chat_memory_turns: int = 20
    # How confident the intent classifier must be to treat an incoming
    # WhatsApp message as an action rather than plain conversation.
    chat_action_confidence: float = 0.6

    extra: dict = field(default_factory=dict)

    # ---------------------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                for key, value in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[deskbot] could not read config: {exc}")
        return cfg

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))
        except OSError as exc:
            print(f"[deskbot] could not save config: {exc}")
