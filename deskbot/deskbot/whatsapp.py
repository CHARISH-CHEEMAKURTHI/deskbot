"""Two-way WhatsApp chat, via the official WhatsApp Business Cloud API.

This is deliberately a *different* mechanism from commands.py's
send_whatsapp (a plain wa.me "click to chat" link): that one only ever
sends, so an unofficial link is fine. This one needs to *receive* your
messages too, and unofficial WhatsApp Web automation for that carries
real ToS/ban risk on a personal number -- so this uses Meta's real API
instead, at the cost of a one-time developer setup (see README).

Off by default (`whatsapp_business_enabled`). When on, main.py starts a
small local webhook server on a background thread; incoming messages are
matched against `whatsapp_allowed_numbers` (anyone else is ignored),
classified the same way "Ask deskbot..." classifies text, and either
dispatched as an action (via the GUI-thread bridge, so a confirmation
dialog can still show for anything risky) or answered as plain
conversation, with a rolling per-sender history kept on disk for context.
"""

from __future__ import annotations

import http.server
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import intent as intent_mod
from .config import CONFIG_DIR

HISTORY_PATH = CONFIG_DIR / "whatsapp_history.json"

_history_lock = threading.Lock()


def _load_all_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all_history(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(json.dumps(data, indent=2))
    except OSError as exc:
        print(f"[deskbot] could not save WhatsApp chat history: {exc}")


def load_history(sender: str) -> list[tuple[str, str]]:
    with _history_lock:
        data = _load_all_history()
    return [tuple(turn) for turn in data.get(sender, [])]


def append_history(cfg, sender: str, user_text: str, bot_text: str) -> None:
    turns = int(getattr(cfg, "chat_memory_turns", 20))
    with _history_lock:
        data = _load_all_history()
        data.setdefault(sender, [])
        data[sender].append(["user", user_text])
        data[sender].append(["bot", bot_text])
        data[sender] = data[sender][-turns * 2 :]
        _save_all_history(data)


def send_message(cfg, to: str, text: str) -> bool:
    token = getattr(cfg, "whatsapp_access_token", "") or os.environ.get(
        "DESKBOT_WHATSAPP_ACCESS_TOKEN", ""
    )
    phone_id = getattr(cfg, "whatsapp_phone_number_id", "")
    base = getattr(cfg, "whatsapp_api_base", "https://graph.facebook.com/v20.0")
    if not token or not phone_id:
        print("[deskbot] WhatsApp send skipped -- access token/phone_number_id not configured")
        return False

    url = f"{base}/{phone_id}/messages"
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096]},
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"[deskbot] WhatsApp send failed: {exc}")
        return False


def handle_incoming(cfg, bridge, sender: str, text: str) -> None:
    """Runs on the webhook server's background thread. `bridge` is
    PetWindow's _WhatsAppBridge -- the only thread-safe way to reach the
    GUI thread for a confirmation dialog or the desktop bot's own mood."""
    allowed = [str(n).strip() for n in getattr(cfg, "whatsapp_allowed_numbers", []) or []]
    if allowed and sender not in allowed:
        return  # a stranger messaging the business number -- not answering

    try:
        parsed = intent_mod.classify(cfg, text)
    except Exception as exc:
        send_message(cfg, sender, f"something went wrong: {exc}")
        return

    threshold = float(getattr(cfg, "chat_action_confidence", 0.6))
    if parsed is not None and parsed.intent != "unknown" and parsed.confidence >= threshold:
        reply = bridge.run_action_blocking(parsed, via="WhatsApp")
    else:
        history = load_history(sender)
        try:
            reply = intent_mod.chat(cfg, history, text)
        except Exception as exc:
            reply = f"something went wrong: {exc}"
        bridge.say_async(reply)

    append_history(cfg, sender, text, reply)
    send_message(cfg, sender, reply)


class _Handler(http.server.BaseHTTPRequestHandler):
    cfg = None
    bridge = None

    def do_GET(self) -> None:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        token = qs.get("hub.verify_token", [""])[0]
        challenge = qs.get("hub.challenge", [""])[0]
        if token and token == getattr(self.cfg, "whatsapp_verify_token", ""):
            body = challenge.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(403)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        # Ack immediately -- Meta expects a fast 200 and will retry (and
        # eventually give up) on a slow one, so do the real work after.
        self.send_response(200)
        self.end_headers()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        threading.Thread(target=self._process, args=(payload,), daemon=True).start()

    def _process(self, payload: dict) -> None:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    sender = msg.get("from")
                    text = msg.get("text", {}).get("body")
                    if sender and text:
                        handle_incoming(self.cfg, self.bridge, sender, text)

    def log_message(self, fmt, *args) -> None:  # quiet -- deskbot has its own logging
        pass


def start(cfg, bridge) -> http.server.ThreadingHTTPServer | None:
    """Starts the webhook server on a daemon thread if enabled. Returns
    the server (call .shutdown() to stop it) or None if disabled."""
    if not getattr(cfg, "whatsapp_business_enabled", False):
        return None

    _Handler.cfg = cfg
    _Handler.bridge = bridge
    port = int(getattr(cfg, "whatsapp_webhook_port", 8765))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[deskbot] WhatsApp webhook listening on :{port}")
    return server
