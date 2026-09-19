# deskbot v0.1

A small animated bot that lives on your Linux desktop, walks after your cursor,
pulls faces, notices when your machine is busy, and can now do a few things
for you. Phase 1: **movement + expressions**. Phase 2: **activity awareness**.
Phase 3: **actions**. Voice control and a fuller AI agent are still ahead —
see below.

## Run it

```bash
cd deskbot
./run.sh          # makes a venv, installs PyQt6, starts the bot
```

Or manually:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m deskbot
```

## Controls

| Action | Result |
|---|---|
| Move your cursor | bot walks after you, parks beside you |
| Left-drag the bot | pick it up and drop it anywhere on the desktop |
| Double-click | it laughs |
| Right-click | menu: follow on/off, chatty on/off, force any mood, save settings, quit |
| Leave cursor still | ~10s → it wanders and thinks; ~75s → it falls asleep |
| Uncheck "Follow cursor" in the right-click menu | bot stops chasing you and just roams the desktop on its own |
| Uncheck "Notice what I'm doing" in the right-click menu | turns off activity awareness (Phase 2) |
| "Ask deskbot…" in the right-click menu | type a request ("open firefox", "search cats on youtube", "what time is it") and it does it (Phase 3) |

## Expressions (11)

neutral, happy, laughing, thinking, sad, crying, angry, cheering, surprised,
sleeping, love — all drawn in code with QPainter, so there are **zero image
assets to make right now**. See `deskbot-expressions.png` for the full set.

## Layout

```
deskbot/
  config.py       tunables → ~/.config/deskbot/config.json
  expressions.py  Expression enum + VectorRenderer (all the drawing)
                  SpriteRenderer stub for when you draw real art
  behavior.py     Brain: modes (FOLLOW/WANDER/REST/SLEEP/DRAGGED), targets, moods
  activity.py     ActivityWatcher: polls CPU/memory/battery/foreground app,
                   nudges the brain's mood (phase 2)
  intent.py       classifies a typed sentence into an intent via Ollama (phase 3)
  commands.py     the actions themselves: open app, search, play music,
                   send email, send WhatsApp, shutdown/restart (phase 3)
  pet.py          PetWindow: transparent always-on-top window, physics, menu
  main.py         entry point
```

## Activity awareness (phase 2)

Every few seconds (`activity_poll_interval`) `ActivityWatcher.poll()` checks:

- **Foreground app pegging the CPU** (`busy_cpu_percent`) → after
  `loading_after_seconds` the bot goes THINKING ("hmm, loading..."); if it's
  still going after `stuck_after_seconds` the bot gets ANGRY ("still going??").
  Needs an X11 connection to know which window is focused (via `python-xlib`)
  — it has one automatically since deskbot runs under XWayland, but on a setup
  where that's unavailable this one signal just quietly drops out.
- **Overall system load** (`system_busy_percent`) → same THINKING nudge, as a
  fallback that doesn't need to know which window is focused (e.g. a build
  running in an unfocused terminal).
- **Low battery** (`low_battery_percent`, unplugged) → SAD, once per discharge.
- **High memory pressure** (`low_memory_percent`) → SURPRISED.

All of it is a suggestion layered on top of normal behaviour (same
`brain.set_mood()` hook the menu's "force mood" uses) and can be switched off
entirely from the right-click menu or by setting `"activity_aware": false` in
the config. Tune the thresholds in `~/.config/deskbot/config.json`.

## Actions (phase 3)

Right-click → "Ask deskbot…" and type a request. `intent.py` sends it to a
local Ollama model (`ollama_url`/`ollama_model` in config) asking for a small,
fixed JSON shape (intent/target/query), then `commands.py` carries it out —
opening an app, searching the web, playing something on YouTube, telling the
time, sending an email, messaging a WhatsApp contact, or shutting
down/restarting. The Ollama call runs on a background thread so the bot keeps
animating while it thinks; the action itself always runs back on the GUI
thread afterward, since anything risky (see below) needs a dialog.

Needs [Ollama](https://ollama.com) running locally with `ollama_model` pulled
(`ollama pull llama3.1:8b`, or point `ollama_model` at whatever you have).
`send_email` additionally needs `smtp_user`/`smtp_password` in config (or the
`DESKBOT_SMTP_USER`/`DESKBOT_SMTP_PASSWORD` env vars) — an app password, not
your real one, if your provider offers it. `send_whatsapp` needs
`whatsapp_contacts` in config: a lowercase-name → phone-number map, e.g.
`{"mom": "15551234567"}` (country code, no "+" or spaces) — it will only ever
message people on this list, and refuses (with the list of who it *does* know)
for anyone else. Without email/WhatsApp set up, those features just report
they're not configured instead of failing silently.

Examples: *"open vs code"*, *"search kali linux on github"*, *"play believer
by imagine dragons"*, *"what time is it"*, *"email jo@example.com saying I'll
be 10 minutes late"*, *"whatsapp mom that I'll be late"*, *"shutdown"*.

### Confirmation before anything risky

`shutdown`, `restart`, `send_email`, and `send_whatsapp` never run straight
off a classification — deskbot always shows a Yes/No dialog first (defaulting
to No) naming exactly what it's about to do (who it's emailing/WhatsApping and
what it'll say, or that it's about to shut down/restart), and only acts on
"Yes". A misheard or misclassified request can't silently email someone,
message a contact, or touch your machine's power state.

`send_whatsapp` is also deliberately **not** fully automatic even after you
confirm: it opens a `wa.me` "click to chat" link (WhatsApp's own supported
mechanism, not a scripted/unofficial send) with your message pre-filled — you
still hit send yourself in WhatsApp. That's intentional: it avoids GUI-automation
dependencies and any risk of WhatsApp treating the account as running an
unofficial bot.

**Real sprites.** Implement `SpriteRenderer.draw()` with the same signature as
`VectorRenderer.draw()` and swap the one line in `main.py`.

## Where voice + a fuller agent plug in

The intent/command split above is deliberately the same shape a voice
frontend would use: swap "Ask deskbot…"'s text dialog for a wake-word
listener + speech-to-text, keep calling `intent.classify()` /
`intent.run()` exactly as-is, and speak `CommandResult.message` back
instead of (or alongside) the speech bubble.

## Notes for your setup

- Built and tested against **X11** (Mint/Cinnamon). Cursor polling via
  `QCursor.pos()` and always-on-top both work there.
- On **Wayland** (Hyprland/Plasma), `QCursor.pos()` returns stale coordinates
  and windows can't position themselves, which breaks cursor-following,
  always-on-top, and dragging the bot around. `deskbot` now detects a Wayland
  session automatically and runs itself under XWayland
  (`QT_QPA_PLATFORM=xcb`) so all three keep working, with no setup needed. If
  you'd rather try native Wayland anyway, `export QT_QPA_PLATFORM=wayland`
  before launching.
- If the bot hides behind other windows, set `"bypass_wm": true` in
  `~/.config/deskbot/config.json`.

## Autostart

Save as `~/.config/autostart/deskbot.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=deskbot
Exec=/full/path/to/deskbot/run.sh
X-GNOME-Autostart-enabled=true
```
