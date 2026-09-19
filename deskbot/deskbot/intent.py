"""Phase 3: turns a typed sentence into one of commands.py's actions.

Ask deskbot something via the right-click menu's "Ask deskbot..." dialog
(or whatsapp.py's two-way chat) and this classifies it with a local Ollama
model (the same one config.py's ollama_url/ollama_model already point at)
into a small, fixed set of intents, then commands.py carries it out. The
`ollama` package is only imported inside classify()/chat() so a deskbot
install that never uses this feature doesn't need it at startup.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from pydantic import BaseModel

from . import commands

SYSTEM_PROMPT = """You are deskbot's intent classifier.

Understand the user's request and return ONLY valid JSON of the form:
{"intent": "", "target": "", "query": "", "location": "", "confidence": 0}

Known intents:
- open_application: target = app name (e.g. "firefox", "code")
- search_web: target = site ("google"/"youtube"/"github"/"reddit", default
  "google" if none is implied), query = search text
- search_image: query = what to look for
- play_music: query = song or artist to search for on YouTube
- get_time: no fields needed
- send_email: target = recipient email address, query = message body
- send_whatsapp: target = contact name, MUST be exactly one name from the
  "Known WhatsApp contacts" list below (case-insensitive) -- never invent
  one or use a phone number directly; query = message body
- shutdown: no fields needed
- restart: no fields needed

Never leave target or query empty if the request implies one. If nothing
matches, or a send_whatsapp target isn't in the known contacts list, use
intent "unknown"."""

# Anything that messages a real person or touches the machine's power
# state gets a confirmation dialog before it runs -- see pet.py.
CONFIRM_INTENTS = {"shutdown", "restart", "send_email", "send_whatsapp"}


class Intent(BaseModel):
    intent: str
    target: str | None = None
    location: str | None = None
    query: str | None = None
    confidence: float = 0.0


_announced_fallback: str | None = None

# Reasoning models (qwen3, deepseek-r1, ...) wrap their scratchpad in
# <think>...</think> and emit it as part of the reply. Left in, it breaks
# JSON parsing for classify() and gets read aloud verbatim by voice.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Drop a reasoning model's <think> scratchpad from its reply."""
    text = _THINK_BLOCK.sub("", text or "")
    text = _OPEN_THINK.sub("", text)  # truncated/unclosed block
    return text.strip()


def _first_json_object(text: str) -> str:
    """The first balanced {...} in `text`. Even with Ollama's schema
    enforcement, a reasoning model can wrap or prefix its JSON, so find the
    object rather than trusting the whole string to parse."""
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = escaped = False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def available_models(cfg) -> list[str]:
    """Model names Ollama actually has pulled."""
    url = cfg.ollama_url.rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read())
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def resolve_model(cfg) -> str:
    """The configured model if Ollama has it, otherwise the closest thing
    it does have. A fresh Ollama install rarely has exactly the model
    config defaults to, and dying with a 404 while a perfectly usable
    model sits right there isn't helpful."""
    global _announced_fallback
    want = cfg.ollama_model
    try:
        models = available_models(cfg)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return want  # can't tell -- let the real call report the real error

    if not models:
        raise RuntimeError(f"Ollama has no models pulled yet -- run: ollama pull {want}")
    if want in models:
        return want

    base = want.split(":")[0]
    chosen = next((m for m in models if m.split(":")[0] == base), models[0])
    if _announced_fallback != chosen:
        _announced_fallback = chosen
        print(
            f"[deskbot] model {want!r} isn't pulled; using {chosen!r} instead. "
            f"Run `ollama pull {want}` or set \"ollama_model\": \"{chosen}\" in config.json."
        )
    return chosen


def classify(cfg, text: str) -> Intent | None:
    import ollama

    contacts = getattr(cfg, "whatsapp_contacts", {}) or {}
    prompt = SYSTEM_PROMPT
    if contacts:
        prompt += "\n\nKnown WhatsApp contacts: " + ", ".join(sorted(contacts))

    client = ollama.Client(host=cfg.ollama_url)
    response = client.chat(
        model=resolve_model(cfg),
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        format=Intent.model_json_schema(),
        options={"temperature": 0},
    )
    content = strip_thinking(response.message.content or "")
    return Intent.model_validate_json(_first_json_object(content))


def needs_confirmation(parsed: Intent) -> bool:
    return parsed.intent in CONFIRM_INTENTS


def confirmation_text(cfg, parsed: Intent) -> str:
    if parsed.intent == "shutdown":
        return "Shut down the computer now?"
    if parsed.intent == "restart":
        return "Restart the computer now?"
    if parsed.intent == "send_email":
        return f"Send an email to {parsed.target}?\n\n{parsed.query}"
    if parsed.intent == "send_whatsapp":
        number = commands.resolve_whatsapp_contact(cfg, parsed.target)
        who = f"{parsed.target} ({number})" if number else str(parsed.target)
        return f"Open WhatsApp to {who} with this message?\n\n{parsed.query}"
    return f"Go ahead with {parsed.intent}?"


CHAT_SYSTEM_PROMPT = """You are deskbot, a small friendly desktop companion,
chatting with your owner over WhatsApp. Keep replies short and casual --
one to three sentences, like a text message, not an essay.

Actions (opening apps, searching, playing music, email, WhatsApp, shutdown/
restart) are handled by a separate system before your reply is ever
requested, so you're only ever seeing messages that weren't one of those --
just have a normal conversation."""


def chat(cfg, history: list[tuple[str, str]], text: str) -> str:
    """A plain conversational reply (no JSON schema), with `history` --
    a list of (role, text) pairs, oldest first, role "user" or "bot" --
    folded in as context. Used for WhatsApp messages that classify() didn't
    recognize as an action."""
    import ollama

    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    turns = int(getattr(cfg, "chat_memory_turns", 20))
    for role, content in history[-turns:]:
        messages.append({"role": "user" if role == "user" else "assistant", "content": content})
    messages.append({"role": "user", "content": text})

    client = ollama.Client(host=cfg.ollama_url)
    response = client.chat(
        model=resolve_model(cfg), messages=messages, options={"temperature": 0.7}
    )
    return strip_thinking(response.message.content or "")


def run(cfg, parsed: Intent) -> commands.CommandResult:
    if parsed.intent == "open_application":
        return commands.open_application(parsed.target)
    if parsed.intent == "search_web":
        return commands.search_web(parsed.target, parsed.query)
    if parsed.intent == "search_image":
        return commands.search_image(parsed.query)
    if parsed.intent == "play_music":
        return commands.play_music(parsed.query)
    if parsed.intent == "get_time":
        return commands.get_time()
    if parsed.intent == "send_email":
        return commands.send_email(parsed.target, parsed.query, cfg)
    if parsed.intent == "send_whatsapp":
        return commands.send_whatsapp(parsed.target, parsed.query, cfg)
    if parsed.intent == "shutdown":
        return commands.shutdown()
    if parsed.intent == "restart":
        return commands.restart()
    return commands.CommandResult("not sure what you meant by that.", ok=False)
