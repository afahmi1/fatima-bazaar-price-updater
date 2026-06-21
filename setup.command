#!/bin/bash
# Double-click this ONCE on a new Mac to install everything the app needs.
# It creates a private Python environment inside this folder.

cd "$(dirname "$0")" || exit 1

echo "============================================="
echo "  Setting up Fatima Bazaar Price Updater"
echo "============================================="

# Find a usable python3
PY=""
for c in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo ""
  echo "Python 3 was not found. Install it from https://www.python.org/downloads/"
  echo "then double-click this Setup file again."
  echo ""
  read -p "Press Return to close." _
  exit 1
fi

echo "Using Python: $($PY --version)"
echo "Creating virtual environment (.venv)…"
"$PY" -m venv .venv || { echo "Failed to create venv"; read -p "Press Return." _; exit 1; }

echo "Installing required packages…"
./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -r requirements.txt || {
  echo "Package install failed."; read -p "Press Return." _; exit 1;
}

echo ""
echo "✅ Setup complete!"
echo "   Now double-click 'Start.command' to run the app."
echo ""
read -p "Press Return to close." _
