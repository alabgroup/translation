#!/bin/bash
# Remove the Passage login service. The app and its data are left alone.
set -euo pipefail
LABEL="com.alabgroup.passage"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Removed $LABEL. Start it by hand with: python run.py"
