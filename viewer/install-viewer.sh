#!/usr/bin/env bash
# Install the Foundational Memory live viewer.
# A tiny always-on control server (localhost) with Start/Stop + the live dashboard,
# password-protected (Basic Auth), serving on-demand. Runs as a LaunchAgent.
#
#   ./install-viewer.sh
#   HERMES_HOME=~/.hermes-b FM_CTRL_PORT=8748 FM_BASE_PATH=/memory ./install-viewer.sh
#
# Remote access is a separate, per-machine step (cloudflared) — see PLAYBOOK.md §Viewer.

set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${FM_CTRL_PORT:-8748}"
BASE="${FM_BASE_PATH:-/memory}"
BANK="$HERMES_HOME/foundational_memory"
DEST="$HERMES_HOME/viewer"
LABEL="com.hermes.fmviewer"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$HERMES_HOME/hermes-agent/venv/bin/python3"; [ -x "$PY" ] || PY="$(command -v python3)"

say(){ printf '\033[1;36m==>\033[0m %s\n' "$*"; }

[ -d "$HERMES_HOME" ] || { echo "HERMES_HOME not found: $HERMES_HOME"; exit 1; }
say "installing viewer -> $DEST"
mkdir -p "$DEST"
cp -a "$BUNDLE_DIR/app.py" "$BUNDLE_DIR/app.html" "$DEST/"

say "writing LaunchAgent $LABEL"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>$PY</string><string>$DEST/app.py</string></array>
    <key>WorkingDirectory</key><string>$DEST</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>FM_CTRL_PORT</key><string>$PORT</string>
        <key>FM_BANK</key><string>$BANK</string>
        <key>FM_BASE_PATH</key><string>$BASE</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HERMES_HOME/logs/fmviewer.out.log</string>
    <key>StandardErrorPath</key><string>$HERMES_HOME/logs/fmviewer.err.log</string>
</dict>
</plist>
PLIST

UID_NUM=$(id -u)
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
sleep 2

if launchctl list | grep -q "$LABEL"; then
  say "viewer control running."
else
  echo "WARN: LaunchAgent not listed — check $HERMES_HOME/logs/fmviewer.err.log"
fi

echo
say "DONE."
echo "  Local:    http://127.0.0.1:$PORT$BASE/"
echo "  Password: cat $HERMES_HOME/.fm_token   (username = anything)"
echo "  Remote:   add a cloudflared path route  <your-host>$BASE  ->  http://localhost:$PORT"
echo "            (ingress rule with  path: ^$BASE  ABOVE your main host rule; see PLAYBOOK.md)"
