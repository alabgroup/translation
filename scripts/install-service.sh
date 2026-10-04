#!/bin/bash
# Install Passage as a login service: it starts when this Mac logs in and
# restarts itself if it stops. Run once; after that nobody needs a terminal.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.alabgroup.passage"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"

if [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "No virtualenv at $REPO/.venv — run the setup steps in README.md first." >&2
  exit 1
fi

mkdir -p "$AGENTS" "$REPO/logs"
sed "s|__REPO__|$REPO|g" "$REPO/scripts/$LABEL.plist" > "$PLIST"

# Replace any previous copy so re-running this is safe.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/$LABEL"

echo "Installed $LABEL"
echo "  logs:    $REPO/logs/passage.log"
echo "  control: http://localhost:8000/"
echo
echo "It starts at login and restarts if it stops."
echo "Stop for now:   launchctl bootout gui/$UID/$LABEL"
echo "Remove it:      $REPO/scripts/uninstall-service.sh"
echo
echo "IMPORTANT, once only: macOS must grant microphone access to"
echo "  $REPO/.venv/bin/python"
echo "Run 'python run.py' by hand once and allow the prompt, or add it under"
echo "System Settings > Privacy & Security > Microphone. Without this the"
echo "service runs but the level meter stays at zero."
