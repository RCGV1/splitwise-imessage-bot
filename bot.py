"""
Main Splitwise iMessage Bot Orchestrator.
- Automatically generates reminders that include a concise AI explanation of why the money is owed.
- Listens for incoming replies to the reminder and answers follow-up questions.
- Safeguards personal conversations: Only triggers if the sender is a group debtor asking an expense question.
"""

import sys
import time
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, List

import config
from splitwise_client import SplitwiseClient
from ai_explainer import AIExplainer
from imessage import IMessageBridge

REMINDER_STATE_FILE = Path(__file__).resolve().parent / "last_reminded.json"

class SplitwiseBot:
    def __init__(self, dry_run: bool = config.DRY_RUN):
        self.dry_run = dry_run
        self.sw = SplitwiseClient()
        self.ai = AIExplainer()
        self.imessage = IMessageBridge(dry_run=self.dry_run)
        self.group_id = config.SPLITWISE_GROUP_ID
        # Tracks active reminder sessions: phone -> {"name": ..., "timestamp": ...}
        self.active_reminder_sessions: Dict[str, Dict[str, Any]] = {}
        # Rate-limiting tracking: phone -> [timestamps of replies]
        self.reply_history: Dict[str, List[float]] = {}

    def send_reminders(self, group_id: Optional[int] = None, force: bool = False):
        """Checks for all members with unpaid balances and sends reminders WITH an AI explanation."""
        target_group_id = group_id or self.group_id
        if not target_group_id:
            print("[Bot] No active group ID selected. Please select a group first.")
            return

        print(f"\n[Bot] Checking balances for group ID: {target_group_id}...")
        group_data = self.sw.get_group_details(target_group_id)
        group_name = group_data["group_name"]

        # Anti-spam safeguard: Prevent sending live reminders more than once per 24 hours
        if not self.dry_run and not force:
            if REMINDER_STATE_FILE.exists():
                try:
                    with open(REMINDER_STATE_FILE, "r") as f:
                        state = json.load(f)
                    last_time = state.get(str(target_group_id), 0)
                    elapsed = time.time() - last_time
                    if elapsed < 86400: # 24 hours
                        hrs_left = (86400 - elapsed) / 3600
                        print(f"\n🛡️ [Anti-Spam Safeguard Active]")
                        print(f"Live reminders for '{group_name}' were already sent {elapsed/3600:.1f} hours ago.")
                        print(f"Cooldown active for {hrs_left:.1f} more hours to prevent duplicate messages.")
                        print("To override this safeguard and send anyway, pass --force (or click Send again in web).")
                        return
                except Exception:
                    pass

        simplify_debts_enabled = group_data.get("simplify_debts_enabled", True)
        active_debts = group_data.get("active_debts") or group_data.get("simplified_debts") or group_data.get("original_debts") or []

        if not active_debts:
            print("All balances are settled! No reminders needed.")
            return

        mode_str = "simplified" if simplify_debts_enabled else "direct (unsimplified)"
        print(f"Found {len(active_debts)} outstanding {mode_str} debt settlements:\n")
        for debt in active_debts:
            from_name = debt["from_name"]
            to_name = debt["to_name"]
            amount = debt["amount"]
            from_id = debt["from_id"]
            
            member_info = group_data["members"].get(from_id, {})
            recipient_phone = member_info.get("phone") or member_info.get("email")

            if not recipient_phone:
                print(f"-> [Notice] No phone number resolved for {from_name}. Reminder skipped.")
                continue

            # Generate concise AI explanation of why this debt is owed
            context = self.sw.get_user_debt_context(target_group_id, from_name)
            ai_summary = ""
            if context and self.ai.is_configured():
                print(f"   Generating concise AI debt breakdown for {from_name}...")
                if simplify_debts_enabled:
                    prompt_text = (
                        "Give a 2-3 sentence simple explanation of what I consumed vs paid, "
                        "and why Splitwise routes my payment to this person, to include directly in my friendly reminder text."
                    )
                else:
                    prompt_text = (
                        "Give a 2-3 sentence simple explanation of what I consumed vs paid directly with this person, "
                        "and explain this direct balance to include in my friendly reminder text."
                    )
                ai_summary = self.ai.explain_debt(context, user_question=prompt_text)

            explanation_section = f"\n💡 Why this amount:\n{ai_summary}\n" if ai_summary else ""
            settle_phrase = f"with {to_name} (via simplified debts)" if simplify_debts_enabled else f"directly with {to_name}"

            nudge_msg = (
                f"Hey {from_name}! Splitwise reminder for '{group_name}':\n"
                f"You have an open balance of ${amount:.2f} to settle {settle_phrase}.\n"
                f"{explanation_section}\n"
                f"👉 (Tip: Swipe right or tap & hold to 'Reply' to this message with any questions or for an expense breakdown!)"
            )

            print(f"-> Debtor: {from_name} owes {to_name} ${amount:.2f}")
            print(f"   Dispatching iMessage to: {recipient_phone}")
            self.imessage.send_message(recipient_phone, nudge_msg)

            # Record active reminder session
            clean_digits = "".join(c for c in recipient_phone if c.isdigit())
            self.active_reminder_sessions[clean_digits] = {
                "name": from_name,
                "timestamp": time.time(),
                "amount": amount
            }

        # Also notify creditors (the people the money is owed to so they know)
        creditor_debts: Dict[int, List[Dict[str, Any]]] = {}
        for debt in active_debts:
            to_id = debt["to_id"]
            if to_id not in creditor_debts:
                creditor_debts[to_id] = []
            creditor_debts[to_id].append(debt)

        print(f"\nNotifying {len(creditor_debts)} creditor(s) of incoming settlements:")
        for to_id, debts in creditor_debts.items():
            to_member = group_data["members"].get(to_id, {})
            to_name = to_member.get("name", f"Member {to_id}")
            to_phone = to_member.get("phone") or to_member.get("email")

            if not to_phone:
                print(f"-> [Notice] No phone number resolved for creditor {to_name}. Heads-up skipped.")
                continue

            total_owed = sum(d["amount"] for d in debts)
            settle_type = "via simplified debts" if simplify_debts_enabled else "directly"

            if len(debts) == 1:
                d = debts[0]
                creditor_msg = (
                    f"Hey {to_name}! Splitwise heads-up for '{group_name}':\n"
                    f"{d['from_name']} owes you ${d['amount']:.2f} ({settle_type}).\n\n"
                    f"A friendly automated reminder with an expense breakdown has been sent to {d['from_name']} to settle up with you!\n"
                    f"👉 (Tip: Swipe right or tap & hold to 'Reply' to this message if you have questions or to see a breakdown!)"
                )
            else:
                lines = [f"• {d['from_name']}: ${d['amount']:.2f}" for d in debts]
                creditor_msg = (
                    f"Hey {to_name}! Splitwise heads-up for '{group_name}':\n"
                    f"You are owed a total of ${total_owed:.2f} ({settle_type}) from {len(debts)} roommates:\n"
                    f"{chr(10).join(lines)}\n\n"
                    f"Friendly automated reminders with expense breakdowns have been sent to each person to settle up with you!\n"
                    f"👉 (Tip: Swipe right or tap & hold to 'Reply' to this message if you have questions or to see a breakdown!)"
                )

            print(f"-> Creditor: {to_name} is owed ${total_owed:.2f}")
            print(f"   Dispatching heads-up iMessage to: {to_phone}")
            self.imessage.send_message(to_phone, creditor_msg)

            clean_digits = "".join(c for c in to_phone if c.isdigit())
            self.active_reminder_sessions[clean_digits] = {
                "name": to_name,
                "timestamp": time.time(),
                "amount": total_owed,
                "is_creditor": True
            }

        # Record live reminder timestamp to prevent accidental duplicate dispatch
        if not self.dry_run:
            try:
                state = {}
                if REMINDER_STATE_FILE.exists():
                    with open(REMINDER_STATE_FILE, "r") as f:
                        state = json.load(f)
                state[str(target_group_id)] = time.time()
                with open(REMINDER_STATE_FILE, "w") as f:
                    json.dump(state, f, indent=2)
            except Exception as e:
                print(f"Notice: Could not save reminder state: {e}")

    def handle_incoming_question(self, sender: str, question_text: str):
        """Processes an incoming iMessage question using the AI Explainer with rate limiting."""
        print(f"\n[Inbound iMessage] From: {sender} | Question: {question_text}")

        # Rate limiting safeguard: prevent rapid-fire or looping replies
        clean_sender = "".join(c for c in sender if c.isdigit())
        now = time.time()
        history = self.reply_history.get(clean_sender, [])
        history = [t for t in history if now - t < 300] # within 5 minutes
        if len(history) >= 5:
            print(f"[Anti-Spam] Sender {sender} reached rate limit (5 replies / 5 min). Throttling.")
            return
        if history and (now - history[-1] < 3):
            print(f"[Anti-Spam] Ignoring rapid duplicate text from {sender}.")
            return
        history.append(now)
        self.reply_history[clean_sender] = history
        
        target_group_id = self.group_id or config.SPLITWISE_GROUP_ID
        context = self.sw.get_user_debt_context(target_group_id, sender)

        if not context:
            print(f"[Bot] Sender {sender} not matched to a debtor in group {target_group_id}. Ignoring.")
            return

        print(f"[AI] Generating explanation for {context['user_name']}...")
        ai_reply = self.ai.explain_debt(context, user_question=question_text)
        
        formatted_reply = f"[Splitwise Bot]\n{ai_reply}"
        print(f"[Outbound iMessage] Replying to {sender}...")
        self.imessage.send_message(sender, formatted_reply)

    def is_reply_to_bot(self, msg: Dict[str, Any]) -> bool:
        """
        Determines whether an incoming text is a genuine reply to the bot.
        Uses native Apple Messages inline thread reply detection (thread_originator_guid)
        so personal chats are 100% protected and casual texts are ignored.
        """
        # 1. Native iMessage inline thread reply (swiped or tapped 'Reply' on the reminder bubble)
        if msg.get("is_thread_reply"):
            return True

        # 2. Check if thread_originator_guid directly matches any bot sent GUID
        thread_root = msg.get("thread_originator_guid")
        if thread_root and thread_root in self.imessage.sent_bot_guids:
            return True

        # 3. Explicit bot command tag (e.g. "@bot", "bot:", "bot ") for non-iMessage/SMS fallbacks
        raw_text = msg.get("text", "").strip()
        lower_text = raw_text.lower()
        if lower_text.startswith("@bot") or lower_text.startswith("bot:") or lower_text.startswith("bot "):
            return True

        # All other messages (casual texts, questions without thread reply or @bot) are strictly ignored!
        return False

    def run_listener_loop(self, poll_interval: int = 3):
        """Continuously polls for incoming iMessages and replies only to genuine thread replies."""
        has_perm, perm_msg = self.imessage.check_permissions()
        if not has_perm:
            print("\n" + "!" * 60)
            print("PERMISSIONS WARNING:")
            print(perm_msg)
            print("!" * 60 + "\n")

        print(f"\n[Bot] Listening for incoming iMessage replies (Polling every {poll_interval}s)...")
        print("Personal Chat Protection: ACTIVE (Uses native Apple Messages thread replies; no keywords).")
        print("Press Ctrl+C to stop.\n")

        try:
            while True:
                new_messages = self.imessage.get_new_messages()
                for msg in new_messages:
                    sender = msg["sender"]
                    text = msg["text"].strip()
                    
                    if self.is_reply_to_bot(msg):
                        self.handle_incoming_question(sender, text)
                    else:
                        # Protect personal conversation
                        print(f"[Personal Chat Preserved] Ignored casual message from {sender}.")

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nBot stopped by user.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Splitwise iMessage Bot")
    parser.add_argument("--remind", action="store_true", help="Send automated reminders to all debtors (Dry Run)")
    parser.add_argument("--listen", action="store_true", help="Start continuous incoming iMessage listener")
    parser.add_argument("--live", action="store_true", help="Disable dry-run and send real iMessages")
    parser.add_argument("--force", action="store_true", help="Bypass 24-hour reminder cooldown")
    args = parser.parse_args()

    dry_run = not args.live
    bot = SplitwiseBot(dry_run=dry_run)

    if args.remind:
        bot.send_reminders(force=args.force)
    elif args.listen:
        bot.run_listener_loop()
    else:
        print("Usage:")
        print("  python bot.py --remind          # Preview reminders with AI explanation (Dry Run)")
        print("  python bot.py --remind --live   # Dispatch real iMessages")
        print("  python bot.py --listen          # Run background listener for incoming texts")
        print("  python test_demo.py             # Run interactive test suite")
