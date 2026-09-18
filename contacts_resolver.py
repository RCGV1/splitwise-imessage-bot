"""
Phone number resolution module for Splitwise group members.
Combines 3 resolution tiers:
1. Saved overrides in contacts_directory.json (custom phone book)
2. macOS Contacts.app auto-resolution via AppleScript (matches by email or name)
3. Splitwise profile phone number
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any

DIRECTORY_FILE = Path(__file__).resolve().parent / "contacts_directory.json"

def clean_phone(phone: str) -> str:
    """Cleans phone numbers into a standard format."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d+]", "", phone.strip())
    # If 10 digits without leading +1, add +1
    if len(digits) == 10 and not digits.startswith("+"):
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return digits

class ContactsResolver:
    def __init__(self):
        self.directory: Dict[str, str] = {}
        self._load_directory()

    def _load_directory(self):
        if DIRECTORY_FILE.exists():
            try:
                with open(DIRECTORY_FILE, "r") as f:
                    self.directory = json.load(f)
            except Exception as e:
                print(f"Error reading {DIRECTORY_FILE}: {e}")
                self.directory = {}
        else:
            self.directory = {}

    def _save_directory(self):
        try:
            with open(DIRECTORY_FILE, "w") as f:
                json.dump(self.directory, f, indent=2)
        except Exception as e:
            print(f"Error saving {DIRECTORY_FILE}: {e}")

    def lookup_mac_contacts(self, name: str, email: str = "") -> Optional[str]:
        """Queries macOS Contacts.app to find phone number by email or name."""
        clean_name = name.strip().replace('"', '\\"')
        clean_email = email.strip().replace('"', '\\"')

        applescript = f'''
        tell application "Contacts"
            -- 1. Try matching by email
            if "{clean_email}" is not "" then
                try
                    set matchedByEmail to (every person whose value of emails contains "{clean_email}")
                    if (count of matchedByEmail) > 0 then
                        set thePerson to item 1 of matchedByEmail
                        return value of 1st phone of thePerson
                    end if
                end try
            end if

            -- 2. Try matching by exact or partial name
            if "{clean_name}" is not "" then
                try
                    set matchedByName to (every person whose name contains "{clean_name}")
                    if (count of matchedByName) > 0 then
                        set thePerson to item 1 of matchedByName
                        return value of 1st phone of thePerson
                    end if
                end try
                -- Try first name only if multiple words
                try
                    set firstName to word 1 of "{clean_name}"
                    set matchedByFirst to (every person whose name contains firstName)
                    if (count of matchedByFirst) > 0 then
                        set thePerson to item 1 of matchedByFirst
                        return value of 1st phone of thePerson
                    end if
                end try
            end if

            return "NOT_FOUND"
        end tell
        '''

        try:
            res = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                text=True,
                timeout=4
            )
            if res.returncode == 0:
                output = res.stdout.strip()
                if output and output != "NOT_FOUND":
                    return clean_phone(output)
        except Exception as e:
            # Contacts not available or timed out
            pass

        return None

    def resolve_member_phone(self, member_id: Any, name: str, email: str = "", splitwise_phone: str = "") -> Dict[str, Any]:
        """
        Resolves the best phone number for a member using:
        1. Local directory override (contacts_directory.json)
        2. Splitwise profile phone
        3. macOS Contacts.app resolution
        """
        str_id = str(member_id)

        # 1. Check local directory override
        if str_id in self.directory and self.directory[str_id]:
            return {
                "phone": clean_phone(self.directory[str_id]),
                "source": "Saved Directory",
                "is_resolved": True
            }

        # 2. Check Splitwise profile phone
        if splitwise_phone and splitwise_phone.strip():
            cleaned = clean_phone(splitwise_phone)
            self.directory[str_id] = cleaned
            self._save_directory()
            return {
                "phone": cleaned,
                "source": "Splitwise Profile",
                "is_resolved": True
            }

        # 3. Auto-resolve from macOS Contacts
        mac_phone = self.lookup_mac_contacts(name, email)
        if mac_phone:
            cleaned = clean_phone(mac_phone)
            self.directory[str_id] = cleaned
            self._save_directory()
            return {
                "phone": cleaned,
                "source": "Mac Contacts (Auto-Resolved)",
                "is_resolved": True
            }

        return {
            "phone": "",
            "source": "Missing Phone",
            "is_resolved": False
        }

    def set_member_phone(self, member_id: Any, phone: str) -> str:
        """Saves a manual phone number override for a member."""
        cleaned = clean_phone(phone)
        self.directory[str(member_id)] = cleaned
        self._save_directory()
        return cleaned
