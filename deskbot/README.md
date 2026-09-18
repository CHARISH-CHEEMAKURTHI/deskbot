# deskbot v0.1

A small animated bot that lives on your Linux desktop, walks after your cursor,
pulls faces, and now notices when your machine is busy. Phase 1: **movement +
expressions**. Phase 2: **activity awareness**. No app control or AI yet —
those hook into the places marked below.

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

## Where phase 3 plugs in

**Phase 3 — actions.** Add a `commands.py` that maps intents to work
(`subprocess.Popen(["xdg-open", ...])`, email via smtplib, etc.), and let
Ollama turn your sentence into one of those intents. `config.py` already holds
`ollama_url` and `ollama_model`.

**Real sprites.** Implement `SpriteRenderer.draw()` with the same signature as
`VectorRenderer.draw()` and swap the one line in `main.py`.

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
