#!/usr/bin/env bash
# Convenience launcher: creates a venv on first run, then starts the bot.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/python -m deskbot
