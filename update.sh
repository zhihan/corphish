#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/corphish"
VENV_DIR="$INSTALL_DIR/.venv"
PLIST_LABEL="com.corphish.daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Require a prior full install (plist must exist with secrets already configured)
if [ ! -f "$PLIST_PATH" ]; then
  echo "Error: $PLIST_PATH not found. Run install.sh first to set up secrets." >&2
  exit 1
fi

echo "Updating corphish in $INSTALL_DIR ..."

# 1. Copy source files (exclude dev/build artifacts)
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'tests' \
  --exclude '.pytest_cache' \
  --exclude '.claude' \
  "$SCRIPT_DIR/" "$INSTALL_DIR/"

# 2. Create/update venv and install package
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "$INSTALL_DIR"

# 3. Restart daemon (plist with secrets is left untouched)
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Updated code and restarted daemon."
