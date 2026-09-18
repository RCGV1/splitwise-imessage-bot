#!/bin/bash
# Disables macOS automatic reminders schedule

PLIST_NAME="com.splitwise.imessagebot.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"

if [ -f "$TARGET_PLIST" ]; then
    launchctl unload "$TARGET_PLIST" 2>/dev/null || true
    rm -f "$TARGET_PLIST"
    echo "✅ Splitwise Bot automated schedule has been UNLOADED and removed."
else
    echo "Notice: No active schedule found at $TARGET_PLIST."
fi
