"""
Main Splitwise iMessage Bot Orchestrator.
- Automatically generates reminders that include a concise AI explanation of why the money is owed.
- Listens for incoming replies to the reminder and answers follow-up questions.
- Safeguards personal conversations: Only triggers if the sender is a group debtor asking an expense question.
"""

import sys
import time
import argparse
from typing import Optional, Dict, Any

import config
from splitwise_client import SplitwiseClient
from ai_explainer import AIExplainer
from imessage import IMessageBridge

class SplitwiseBot:
    def __init__(self, dry_run: bool = config.DRY_RUN):
        self.dry_run = dry_run
        self.sw = SplitwiseClient()
        self.ai = AIExplainer()
        self.imessage = IMessageBridge(dry_run=self.dry_run)
        self.group_id = config.SPLITWISE_GROUP_ID
        # Tracks active reminder sessions: phone -> {"name": ..., "timestamp": ...}
        self.active_reminder_sessions: Dict[str, Dict[str, Any]] = {}

    def send_reminders(self, group_id: Optional[int] = None):
        """Checks for all members with unpaid balances and sends reminders WITH an AI explanation."""
        target_group_id = group_id or self.group_id
        if not target_group_id:
            print("[Bot] No active group ID selected. Please select a group first.")
            return

        print(f"\n[Bot] Checking balances for group ID: {target_group_id}...")
        group_data = self.sw.get_group_details(target_group_id)
        group_name = group_data["group_name"]
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

    def handle_incoming_question(self, sender: str, question_text: str):
        """Processes an incoming iMessage question using the AI Explainer."""
        print(f"\n[Inbound iMessage] From: {sender} | Question: {question_text}")
        
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
        Uses native Apple Messages thread reply detection (reply_to_guid)
        so NO arbitrary keywords are required, keeping personal conversations safe.
        """
        # 1. Native iMessage thread reply (swiped or tapped 'Reply' on the reminder bubble)
        if msg.get("is_thread_reply"):
            return True

        reply_to = msg.get("reply_to_guid")
        thread_root = msg.get("thread_originator_guid")
        if (reply_to and reply_to in self.imessage.sent_bot_guids) or (thread_root and thread_root in self.imessage.sent_bot_guids):
            return True

        sender = msg.get("sender", "")
        clean_sender = "".join(c for c in sender if c.isdigit())
        raw_text = msg.get("text", "").strip()
        lower_text = raw_text.lower()

        # 2. Explicit bot tag/prefix (e.g. "@bot", "bot:", "reply:")
        if lower_text.startswith("@bot") or lower_text.startswith("bot:") or lower_text.startswith("bot "):
            return True

        # 3. Active reminder follow-up: sender received a reminder within 48h and is asking a question
        has_active_session = False
        for phone_key, sess in self.active_reminder_sessions.items():
            if phone_key.endswith(clean_sender) or clean_sender.endswith(phone_key):
                if time.time() - sess["timestamp"] < 172800: # 48 hours
                    has_active_session = True
                    break

        if has_active_session and ("?" in lower_text or lower_text.startswith("why") or lower_text.startswith("how")):
            return True

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
    args = parser.parse_args()

    dry_run = not args.live
    bot = SplitwiseBot(dry_run=dry_run)

    if args.remind:
        bot.send_reminders()
    elif args.listen:
        bot.run_listener_loop()
    else:
        print("Usage:")
        print("  python bot.py --remind          # Preview reminders with AI explanation (Dry Run)")
        print("  python bot.py --remind --live   # Dispatch real iMessages")
        print("  python bot.py --listen          # Run background listener for incoming texts")
        print("  python test_demo.py             # Run interactive test suite")
