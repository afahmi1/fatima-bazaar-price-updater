#!/bin/bash
# Double-click to start the Price Updater. It opens in your web browser.
# Leave this window open while you use the app; close it (or press Control-C)
# to stop.

cd "$(dirname "$0")" || exit 1

if [ ! -x "./.venv/bin/python" ]; then
  echo "First-time setup hasn't been run yet."
  echo "Please double-click 'setup.command' first."
  read -p "Press Return to close." _
  exit 1
fi

echo "Starting Fatima Bazaar Price Updater…"
./.venv/bin/python app.py
