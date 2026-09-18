#!/bin/bash
# Enables native macOS automatic reminders every Sunday at 6:00 PM via launchd

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.splitwise.imessagebot.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/$PLIST_NAME"

mkdir -p "$TARGET_DIR"
mkdir -p "$BOT_DIR/logs"

# Copy plist to LaunchAgents
cp "$SCRIPT_DIR/$PLIST_NAME" "$TARGET_PLIST"

# Unload previous instance if loaded, then load
launchctl unload "$TARGET_PLIST" 2>/dev/null || true
launchctl load "$TARGET_PLIST"

echo "=========================================================="
echo "  ✅ Splitwise Bot Sunday 6:00 PM Schedule is now ACTIVE!"
echo "  📅 Frequency: Every Sunday at 18:00 (6:00 PM)"
echo "  📁 Plist installed at: $TARGET_PLIST"
echo "  📋 Logs will be written to: $BOT_DIR/logs/scheduler.log"
echo "=========================================================="
