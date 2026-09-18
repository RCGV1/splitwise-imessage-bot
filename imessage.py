"""
macOS iMessage integration module.
- Sends outbound iMessages via AppleScript.
- Polls incoming messages from ~/Library/Messages/chat.db (requires Full Disk Access).
- Supports dry-run mode for safe testing.
"""

import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"

class IMessageBridge:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        # Timestamp offset for Apple's Cocoa epoch (Jan 1, 2001) in nanoseconds
        # 1 Cocoa second = 1,000,000,000 nanoseconds.
        # Unix epoch to Cocoa epoch is 978307200 seconds.
        self.last_checked_date = self._get_current_cocoa_timestamp()

    @staticmethod
    def _get_current_cocoa_timestamp() -> int:
        """Returns current time in nanoseconds since 2001-01-01."""
        unix_now = time.time()
        cocoa_seconds = unix_now - 978307200
        return int(cocoa_seconds * 1_000_000_000)

    def send_message(self, recipient: str, message: str) -> bool:
        """
        Sends an iMessage to a recipient (phone number or Apple ID email).
        """
        clean_recipient = recipient.strip()
        if not clean_recipient:
            print("Error: Recipient cannot be empty.")
            return False

        if self.dry_run:
            print(f"\n[DRY RUN] Would send iMessage to {clean_recipient}:")
            print("-" * 50)
            print(message)
            print("-" * 50)
            return True

        # Clean string for AppleScript
        safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')

        # AppleScript to send to buddy or existing chat
        applescript = f'''
        tell application "Messages"
            try
                set targetService to 1st service whose service type = iMessage
                set targetBuddy to buddy "{clean_recipient}" of targetService
                send "{safe_msg}" to targetBuddy
                return "OK"
            on error errMsg
                -- Fallback: try sending by chat ID or phone search
                try
                    repeat with c in chats
                        if id of c contains "{clean_recipient}" then
                            send "{safe_msg}" to c
                            return "OK_CHAT"
                        end if
                    end repeat
                end try
                error errMsg
            end try
        end tell
        '''

        try:
            res = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                text=True,
                check=True
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to send iMessage to {clean_recipient}: {e.stderr.strip()}")
            return False

    def check_permissions(self) -> Tuple[bool, str]:
        """Checks if Messages AppleScript and chat.db access are available."""
        # 1. Test AppleScript
        try:
            res = subprocess.run(
                ["osascript", "-e", 'tell application "Messages" to get (count of chats)'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode != 0:
                return False, f"AppleScript error: {res.stderr.strip()}"
        except Exception as e:
            return False, f"AppleScript execution failed: {e}"

        # 2. Test chat.db access
        if not CHAT_DB_PATH.exists():
            return False, f"Messages database not found at {CHAT_DB_PATH}"

        try:
            conn = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM message LIMIT 1;")
            cursor.fetchone()
            conn.close()
            return True, "All permissions (AppleScript & Full Disk Access) verified!"
        except sqlite3.OperationalError as e:
            if "authorization denied" in str(e).lower() or "unable to open database" in str(e).lower():
                return False, (
                    "Full Disk Access is REQUIRED to read incoming iMessages.\n"
                    "How to enable it:\n"
                    "1. Open System Settings -> Privacy & Security -> Full Disk Access.\n"
                    "2. Toggle ON your Terminal app (e.g. Terminal, iTerm, or VS Code / IDE).\n"
                    "3. Rerun this script."
                )
            return False, f"SQLite error: {e}"

    def get_new_messages(self) -> List[Dict[str, Any]]:
        """
        Polls for newly arrived incoming messages.
        Requires Full Disk Access.
        """
        if not CHAT_DB_PATH.exists():
            return []

        try:
            conn = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
            cursor = conn.cursor()

            query = """
            SELECT 
                m.ROWID,
                m.date,
                m.text,
                h.id AS sender_handle,
                m.is_from_me
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.date > ? AND m.is_from_me = 0 AND m.text IS NOT NULL
            ORDER BY m.date ASC;
            """

            cursor.execute(query, (self.last_checked_date,))
            rows = cursor.fetchall()

            new_msgs = []
            for row in rows:
                row_id, date, text, sender, is_from_me = row
                if date > self.last_checked_date:
                    self.last_checked_date = date
                new_msgs.append({
                    "id": row_id,
                    "date": date,
                    "text": text,
                    "sender": sender or "Unknown",
                    "is_from_me": bool(is_from_me)
                })

            conn.close()
            return new_msgs

        except sqlite3.OperationalError:
            return []
