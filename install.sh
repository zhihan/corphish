#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/corphish"
VENV_DIR="$INSTALL_DIR/.venv"
PLIST_LABEL="com.corphish.daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.config/corphish"

# Require env vars
: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN before running install.sh}"
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY before running install.sh}"

echo "Installing corphish to $INSTALL_DIR ..."

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

# 3. Unload existing daemon (ignore errors if not loaded)
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# 4. Write plist pointing at installed venv
mkdir -p "$(dirname "$PLIST_PATH")"
mkdir -p "$LOG_DIR"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/python</string>
        <string>-m</string>
        <string>corphish</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>${TELEGRAM_BOT_TOKEN}</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>${ANTHROPIC_API_KEY}</string>
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/corphish.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/corphish.error.log</string>
</dict>
</plist>
EOF

# 5. Load daemon
launchctl load "$PLIST_PATH"

echo "Installed to $INSTALL_DIR and restarted daemon."
