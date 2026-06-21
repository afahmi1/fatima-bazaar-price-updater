#!/bin/bash
# Double-click to build a clean .zip of this app, ready to copy to another Mac.
# It leaves out the machine-specific environment (.venv) and scratch files so
# the new Mac rebuilds them cleanly. Your inventory list and item memory ARE
# included.

cd "$(dirname "$0")" || exit 1

STAMP=$(date +%Y%m%d_%H%M%S)
ZIP="$HOME/Desktop/Fatima_Bazaar_Price_Updater_$STAMP.zip"

echo "Building transfer package…"
# Zip the whole folder but exclude the venv, caches and scratch data.
zip -r -X "$ZIP" . \
  -x "*/.venv/*" ".venv/*" \
  -x "*/__pycache__/*" "__pycache__/*" \
  -x "data/uploads/*" "data/exports/*" "data/batches/*" \
  -x "*.pyc" "*.DS_Store" >/dev/null

echo ""
echo "✅ Created:"
echo "   $ZIP"
echo ""
echo "Copy that .zip to the other Mac (AirDrop / USB / Drive), unzip it,"
echo "then double-click 'setup.command' once, then 'Start.command'."
echo ""
read -p "Press Return to close." _
