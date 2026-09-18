"""Phase 3: turns a typed sentence into one of commands.py's actions.

Ask deskbot something via the right-click menu's "Ask deskbot..." dialog
and this classifies it with a local Ollama model (the same one
config.py's ollama_url/ollama_model already point at) into a small, fixed
set of intents, then commands.py carries it out. The `ollama` package is
only imported inside classify() so a deskbot install that never uses this
feature doesn't need it at startup.
"""

from __future__ import annotations

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
- shutdown: no fields needed
- restart: no fields needed

Never leave target or query empty if the request implies one. If nothing
matches, use intent "unknown"."""


class Intent(BaseModel):
    intent: str
    target: str | None = None
    location: str | None = None
    query: str | None = None
    confidence: float = 0.0


def classify(cfg, text: str) -> Intent | None:
    import ollama

    client = ollama.Client(host=cfg.ollama_url)
    response = client.chat(
        model=cfg.ollama_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        format=Intent.model_json_schema(),
        options={"temperature": 0},
    )
    return Intent.model_validate_json(response.message.content)


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
    if parsed.intent == "shutdown":
        return commands.shutdown()
    if parsed.intent == "restart":
        return commands.restart()
    return commands.CommandResult("not sure what you meant by that.", ok=False)
