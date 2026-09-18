# deskbot v0.1

A small animated bot that lives on your Linux desktop, walks after your cursor,
and pulls faces. Phase 1 of the plan: **movement + expressions**. No AI, no app
control yet — those hook into the places marked below.

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
| Left-drag the bot | pick it up and drop it anywhere |
| Double-click | it laughs |
| Right-click | menu: follow on/off, chatty on/off, force any mood, save settings, quit |
| Leave cursor still | ~10s → it wanders and thinks; ~75s → it falls asleep |

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
  pet.py          PetWindow: transparent always-on-top window, physics, menu
  main.py         entry point
```

## Where phase 2 and 3 plug in

**Phase 2 — context-aware emotions.** Write a watcher that polls the active
window / CPU / process list, then call:

```python
pet.brain.set_mood(Expression.THINKING, seconds=5)
pet.brain.set_mood(Expression.ANGRY, 4, say="come on, load already!")
```

That's the whole interface. The brain treats it as a temporary override and
goes back to normal behaviour afterwards.

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
  and windows can't position themselves. If you're on Wayland, either run it
  under XWayland (`QT_QPA_PLATFORM=xcb ./run.sh`) or we swap the cursor source
  for a libinput / compositor-specific one later.
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
