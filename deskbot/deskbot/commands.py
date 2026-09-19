"""Phase 3: things deskbot can actually do, dispatched from intent.py.

Every function here is a plain, synchronous action -- opening a URL,
spawning a process, sending mail -- and returns a CommandResult rather
than speaking for itself, so the caller decides how (and whether) to tell
you about it.
"""

from __future__ import annotations

import datetime as dt
import os
import smtplib
import subprocess
import urllib.parse
import webbrowser
from dataclasses import dataclass
from email.message import EmailMessage

WEB_APPS = {
    "youtube": "https://www.youtube.com",
    "gpt": "https://www.chatgpt.com",
    "chatgpt": "https://www.chatgpt.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://www.twitter.com",
    "google": "https://www.google.com",
    "instagram": "https://www.instagram.com",
    "gmail": "https://www.gmail.com",
    "outlook": "https://www.outlook.com",
    "github": "https://www.github.com",
    "spotify": "https://www.spotify.com",
}

SEARCH_URLS = {
    "youtube": "https://www.youtube.com/results?search_query={}",
    "google": "https://www.google.com/search?q={}",
    "github": "https://github.com/search?q={}",
    "reddit": "https://www.reddit.com/search/?q={}",
    "spotify": "https://open.spotify.com/search/{}",
}


@dataclass
class CommandResult:
    message: str
    ok: bool = True


def open_application(app: str | None) -> CommandResult:
    if not app:
        return CommandResult("didn't catch which app you wanted.", ok=False)
    key = app.lower().strip()
    if key in WEB_APPS:
        webbrowser.open(WEB_APPS[key])
        return CommandResult(f"opening {app}")
    found = subprocess.run(["which", key], capture_output=True, text=True)
    if found.returncode == 0:
        subprocess.Popen([key])
        return CommandResult(f"opening {app}")
    return CommandResult(f"couldn't find {app} anywhere.", ok=False)


def search_web(target: str | None, query: str | None) -> CommandResult:
    if not query:
        return CommandResult("didn't catch what to search for.", ok=False)
    site = (target or "google").lower().strip()
    url_fmt = SEARCH_URLS.get(site, SEARCH_URLS["google"])
    webbrowser.open(url_fmt.format(urllib.parse.quote(query)))
    return CommandResult(f"searching for {query}")


def search_image(query: str | None) -> CommandResult:
    if not query:
        return CommandResult("didn't catch what to look for.", ok=False)
    url = f"https://www.google.com/search?tbm=isch&q={urllib.parse.quote(query)}"
    webbrowser.open(url)
    return CommandResult(f"showing images of {query}")


def play_music(query: str | None) -> CommandResult:
    # A plain YouTube search rather than a GUI-automation autoplay hack --
    # no extra dependency, and it works the same on every desktop.
    if not query:
        return CommandResult("didn't catch what to play.", ok=False)
    result = search_web("youtube", query)
    return CommandResult(f"queued up {query} on YouTube", ok=result.ok)


def get_time() -> CommandResult:
    return CommandResult(f"it's {dt.datetime.now().strftime('%I:%M %p')}")


def send_email(to: str | None, body: str | None, cfg) -> CommandResult:
    if not to or not body:
        return CommandResult("need a recipient and a message to send an email.", ok=False)

    user = getattr(cfg, "smtp_user", "") or os.environ.get("DESKBOT_SMTP_USER", "")
    password = getattr(cfg, "smtp_password", "") or os.environ.get("DESKBOT_SMTP_PASSWORD", "")
    host = getattr(cfg, "smtp_host", "smtp.gmail.com")
    port = getattr(cfg, "smtp_port", 587)
    if not user or not password:
        return CommandResult(
            "email isn't set up -- add smtp_user/smtp_password to "
            "config.json (or the DESKBOT_SMTP_USER/DESKBOT_SMTP_PASSWORD "
            "env vars).",
            ok=False,
        )

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = "Message from deskbot"
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        return CommandResult(f"couldn't send that email: {exc}", ok=False)
    return CommandResult(f"sent to {to}")


def resolve_whatsapp_contact(cfg, name: str | None) -> str | None:
    """Looks up `name` in the configured allow-list. Returns the phone
    number, or None if `name` is missing or not on the list -- deskbot
    will only ever WhatsApp people you've explicitly added."""
    if not name:
        return None
    contacts = getattr(cfg, "whatsapp_contacts", {}) or {}
    return contacts.get(name.strip().lower())


def send_whatsapp(contact: str | None, message: str | None, cfg) -> CommandResult:
    if not contact or not message:
        return CommandResult("need a contact and a message to send a WhatsApp.", ok=False)

    number = resolve_whatsapp_contact(cfg, contact)
    if not number:
        contacts = getattr(cfg, "whatsapp_contacts", {}) or {}
        known = ", ".join(sorted(contacts)) or "nobody yet"
        return CommandResult(
            f"{contact} isn't in your WhatsApp contacts -- known contacts: {known}. "
            "Add them to whatsapp_contacts in config.json.",
            ok=False,
        )

    # A wa.me "click to chat" link, not a scripted send -- it's WhatsApp's
    # own supported mechanism (no unofficial automation, no risk to the
    # account), but it only pre-fills the chat; you still hit send yourself.
    url = f"https://wa.me/{number}?text={urllib.parse.quote(message)}"
    webbrowser.open(url)
    return CommandResult(f"opened WhatsApp with your message to {contact} -- hit send to confirm")


def shutdown() -> CommandResult:
    subprocess.Popen(["systemctl", "poweroff"])
    return CommandResult("shutting down, goodbye boss")


def restart() -> CommandResult:
    subprocess.Popen(["systemctl", "reboot"])
    return CommandResult("restarting")
