"""
macOS iMessage integration module.
- Sends outbound iMessages via AppleScript.
- Polls incoming messages from ~/Library/Messages/chat.db (requires Full Disk Access).
- Supports dry-run mode for safe testing.
"""

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set

CHAT_DB_PATH = Path.home() / "Library/Messages/chat.db"
BOT_MESSAGES_FILE = Path(__file__).resolve().parent / "sent_bot_messages.json"

class IMessageBridge:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        # Timestamp offset for Apple's Cocoa epoch (Jan 1, 2001) in nanoseconds
        # 1 Cocoa second = 1,000,000,000 nanoseconds.
        # Unix epoch to Cocoa epoch is 978307200 seconds.
        self.last_checked_date = self._get_current_cocoa_timestamp()
        self.sent_bot_guids: Set[str] = set()
        self._load_sent_guids()

    def _load_sent_guids(self):
        """Loads known sent bot message GUIDs from disk."""
        if BOT_MESSAGES_FILE.exists():
            try:
                with open(BOT_MESSAGES_FILE, "r") as f:
                    self.sent_bot_guids = set(json.load(f))
            except Exception as e:
                print(f"Notice: Could not load {BOT_MESSAGES_FILE}: {e}")
                self.sent_bot_guids = set()

    def _save_sent_guids(self):
        """Persists known sent bot message GUIDs to disk."""
        try:
            with open(BOT_MESSAGES_FILE, "w") as f:
                json.dump(list(self.sent_bot_guids), f, indent=2)
        except Exception as e:
            print(f"Notice: Could not save {BOT_MESSAGES_FILE}: {e}")

    def record_bot_guid(self, guid: str):
        """Records a message GUID as having been sent by the bot."""
        if guid:
            self.sent_bot_guids.add(guid)
            self._save_sent_guids()

    def _fetch_and_record_latest_sent_guid(self):
        """Finds the most recently sent message in chat.db and records its GUID."""
        if not CHAT_DB_PATH.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT guid FROM message 
                WHERE is_from_me = 1 
                ORDER BY date DESC LIMIT 1;
            """)
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                self.record_bot_guid(row[0])
                return row[0]
        except Exception:
            pass
        return None

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
            mock_guid = f"dryrun-bot-{int(time.time()*1000)}"
            self.record_bot_guid(mock_guid)
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
            # Give macOS Messages a brief moment to write the message to chat.db
            time.sleep(0.5)
            self._fetch_and_record_latest_sent_guid()
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
        Includes thread reply metadata (reply_to_guid and thread_originator_guid).
        Filters out tapback reactions. Requires Full Disk Access.
        """
        if not CHAT_DB_PATH.exists():
            return []

        try:
            conn = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
            cursor = conn.cursor()

            query = """
            SELECT 
                m.ROWID,
                m.guid,
                m.date,
                m.text,
                h.id AS sender_handle,
                m.is_from_me,
                m.reply_to_guid,
                m.thread_originator_guid
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.date > ? 
              AND m.is_from_me = 0 
              AND m.text IS NOT NULL
              AND (m.associated_message_type IS NULL OR m.associated_message_type = 0)
            ORDER BY m.date ASC;
            """

            cursor.execute(query, (self.last_checked_date,))
            rows = cursor.fetchall()

            new_msgs = []
            for row in rows:
                row_id, guid, date, text, sender, is_from_me, reply_to_guid, thread_originator_guid = row
                if date > self.last_checked_date:
                    self.last_checked_date = date

                is_reply = bool(
                    (reply_to_guid and reply_to_guid in self.sent_bot_guids) or
                    (thread_originator_guid and thread_originator_guid in self.sent_bot_guids)
                )

                new_msgs.append({
                    "id": row_id,
                    "guid": guid,
                    "date": date,
                    "text": text,
                    "sender": sender or "Unknown",
                    "is_from_me": bool(is_from_me),
                    "reply_to_guid": reply_to_guid,
                    "thread_originator_guid": thread_originator_guid,
                    "is_thread_reply": is_reply
                })

            conn.close()
            return new_msgs

        except sqlite3.OperationalError:
            return []
