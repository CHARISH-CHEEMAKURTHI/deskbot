# deskbot v0.1

A small animated bot that lives on your Linux desktop, walks after your cursor,
pulls faces, notices when your machine is busy, and can now do a few things
for you. Phase 1: **movement + expressions**. Phase 2: **activity awareness**.
Phase 3: **actions**, including chat over WhatsApp and **voice** ("hey
celebi").

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
| Say "hey celebi", then your request | same thing by voice, spoken back to you (needs the voice extras) |
| Tick "Listen for \"hey celebi\"" in the right-click menu | mutes/unmutes wake-word listening live |

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
  intent.py       classifies a typed sentence into an intent via Ollama (phase 3);
                   also intent.chat() for open-ended conversation
  commands.py     the actions themselves: open app, search, play music,
                   send email, send WhatsApp, shutdown/restart (phase 3)
  whatsapp.py     two-way WhatsApp chat over the official Business API:
                   webhook server, per-sender history, dispatch (phase 3)
  memory.py       rolling per-channel conversation history on disk
  voice.py        "hey celebi": wake word -> speech-to-text -> the same
                   actions/chat as everything else -> spoken reply
  assets/         hey_celebi.onnx (the trained wake-word model)
  doctor.py       `--doctor` self-check: session/cursor/Ollama/X11/voice/config
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

### Two-way chat over WhatsApp itself

Everything above is *you* talking to deskbot on the desktop. `whatsapp.py`
instead lets you message deskbot in WhatsApp directly, from anywhere, and it
answers back in the same chat — free-form conversation (with memory of the
last `chat_memory_turns` turns) that falls back to the same intent system
above for anything actionable, and Ollama for a plain reply otherwise.

This is a **different mechanism** from `send_whatsapp` above. That one only
ever *sends* (a `wa.me` link), so an unofficial approach is fine. This one has
to *receive* your messages too, and unofficial WhatsApp Web automation for
that carries real risk of your number getting banned — so this uses the
official **WhatsApp Business Cloud API** instead, which means a one-time setup
through Meta, but no ToS/ban risk and no fragile browser scripting:

1. Off by default (`whatsapp_business_enabled: false`) — nothing listens on
   any port unless you turn it on.
2. Create a free [Meta Developer](https://developers.facebook.com) account,
   add the **WhatsApp** product to an app. Meta gives you a free test number,
   an access token, and a phone number ID.
3. Put those in config: `whatsapp_business_enabled: true`,
   `whatsapp_access_token` (or the `DESKBOT_WHATSAPP_ACCESS_TOKEN` env var),
   `whatsapp_phone_number_id`.
4. Pick your own `whatsapp_verify_token` (any string you make up) and put the
   same value in both config and Meta's webhook setup page.
5. deskbot needs to be reachable from Meta's servers at
   `http://<your-address>:<whatsapp_webhook_port>/` (default port `8765`) —
   easiest for testing is something like `ngrok http 8765` and pasting the
   `https://...ngrok...` URL into Meta's webhook config; for a permanent setup
   you'd want a real domain/port-forward instead.
6. **Set `whatsapp_allowed_numbers`** to your own phone number(s) (same
   format as `whatsapp_contacts`, e.g. `["15551234567"]`). This is the most
   important field: deskbot silently ignores anyone messaging that business
   number who isn't on this list, so a stranger who finds the number can't
   chat with your bot (or, worse, trigger an action's confirmation dialog).

Chat history is kept per-sender in `~/.config/deskbot/whatsapp_history.json`
(capped at `chat_memory_turns` each) purely as conversation context — it
isn't used for anything else.

**The confirmation dialogs still show on your desktop, not in WhatsApp** —
there's no way to show a native dialog inside a WhatsApp chat, so if a
WhatsApp message resolves to `shutdown`/`restart`/`send_email`/`send_whatsapp`,
deskbot pops the same Yes/No dialog on your screen (labeled "requested via
WhatsApp") and simply doesn't reply until it's answered there, up to a 2
minute timeout. That means these four actions only actually happen while
you're at your desk to confirm them — asking "shut down the pc" from your
phone while you're out won't do anything until you're back to click Yes.

**Real sprites.** Implement `SpriteRenderer.draw()` with the same signature as
`VectorRenderer.draw()` and swap the one line in `main.py`.

## Voice: "hey celebi"

Say **"hey celebi"**, then your request. deskbot transcribes it and runs it
through the *same* pipeline as a typed "Ask deskbot…" — so actions, the
confirmation dialogs, and the conversational fallback all behave identically
no matter how you asked — then speaks the answer back (and shows it in the
speech bubble).

Ported from the celebi prototype: openWakeWord for the wake word (the trained
`hey_celebi.onnx` model ships in `deskbot/assets/`, no copying needed),
Whisper for speech-to-text, pyttsx3 for the reply.

**Off by default**, because the extras are a heavy dependency tree:

```bash
sudo apt install portaudio19-dev python3-dev espeak-ng ffmpeg
./.venv/bin/pip install -r requirements-voice.txt     # ~2GB: pulls in PyTorch
```

Then set `"voice_enabled": true` in `~/.config/deskbot/config.json`, or tick
**Listen for "hey celebi"** in the right-click menu (which also mutes/unmutes
it live without a restart). `python -m deskbot --doctor` reports exactly
what's missing, including whether a microphone is visible.

Tuning knobs: `wake_threshold` (0–1, lower triggers more eagerly),
`stt_whisper_model` (`tiny`/`base`/`small`/…), `listen_timeout`,
`speak_replies` (false keeps replies in the bubble only), `tts_rate`,
`tts_voice_index`, and `wake_word_model` to point at a different `.onnx`.

Spoken conversation keeps its own memory thread (`chat_history.json`, key
`voice`), separate from each WhatsApp sender's.

Risky actions still confirm on the desktop: saying "shut down the pc" pops the
same Yes/No dialog rather than just doing it.

## Notes for your setup

- Built and tested against **X11** (Mint/Cinnamon). Cursor polling via
  `QCursor.pos()` and always-on-top both work there.
- On **Wayland** (Pop!_OS COSMIC, GNOME Wayland, Hyprland, Plasma), windows
  can't position themselves at all, so deskbot detects a Wayland session and
  runs itself under XWayland (`QT_QPA_PLATFORM=xcb`). That fixes
  **always-on-top and dragging**. Pass `QT_QPA_PLATFORM=wayland` yourself to
  opt out.
- **Cursor-following cannot work on Wayland**, XWayland or not: XWayland only
  sees the pointer while it is over one of deskbot's own windows, and Wayland
  deliberately provides no protocol for a client to ask where the global
  pointer is. deskbot notices the frozen cursor, says so, and **roams the
  desktop on its own** instead of standing still or falling asleep. For real
  cursor-following, log out and pick the **Xorg / X11** session at the login
  screen (gear icon) — everything works there.
- **Something not working? Run the doctor first:**

  ```bash
  ./.venv/bin/python -m deskbot --doctor
  ```

  It checks session type, whether cursor data is actually live, the X11
  connection phase 2 needs, whether Ollama is reachable and which models are
  really pulled, and what's configured for email/WhatsApp — and prints the fix
  for whatever is wrong.
- If the configured `ollama_model` isn't pulled, deskbot **falls back to a
  model you do have** (and says which) rather than failing — so a fresh Ollama
  install works without editing config. `ollama pull llama3.1:8b` if you want
  the default.
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
