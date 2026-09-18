"""
Main Splitwise iMessage Bot Orchestrator.
- Sends automatic reminders for unpaid group debts.
- Listens for incoming iMessage questions ("Why do I owe $X?") and
  ALWAYS uses AI to explain the calculations and simplified debts.
"""

import sys
import time
import argparse
from typing import Optional

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

    def send_reminders(self, group_id: Optional[int] = None):
        """Checks for all members with unpaid balances and sends friendly nudges."""
        target_group_id = group_id or self.group_id
        print(f"\n[Bot] Checking balances for group ID: {target_group_id}...")
        group_data = self.sw.get_group_details(target_group_id)
        group_name = group_data["group_name"]
        simplified_debts = group_data["simplified_debts"]

        if not simplified_debts:
            print("All balances are settled! No reminders needed.")
            return

        print(f"Found {len(simplified_debts)} outstanding simplified debt settlements:\n")
        for debt in simplified_debts:
            from_name = debt["from_name"]
            to_name = debt["to_name"]
            amount = debt["amount"]
            from_id = debt["from_id"]
            
            member_info = group_data["members"].get(from_id, {})
            recipient_phone = member_info.get("phone") or member_info.get("email")

            nudge_msg = (
                f"Hey {from_name}! Friendly reminder from the {group_name} Splitwise bot: "
                f"you have an open balance of ${amount:.2f} to settle with {to_name}.\n\n"
                f"Reply to this message if you'd like a quick breakdown of why you owe this amount!"
            )

            print(f"-> Debtor: {from_name} owes {to_name} ${amount:.2f}")
            if recipient_phone:
                print(f"   Dispatching iMessage to: {recipient_phone}")
                self.imessage.send_message(recipient_phone, nudge_msg)
            else:
                print(f"   [Notice] No phone/email registered on Splitwise for {from_name}. Nudge skipped.")

    def handle_incoming_question(self, sender: str, question_text: str):
        """Processes an incoming iMessage question using the AI Explainer."""
        print(f"\n[Inbound iMessage] From: {sender} | Question: {question_text}")
        
        # Match sender with Splitwise group member
        context = self.sw.get_user_debt_context(self.group_id, sender)
        
        # If phone search didn't match directly, try finding the first debtor in mock mode
        if not context and self.sw.is_mock:
            context = self.sw.get_user_debt_context(self.group_id, "Alex")

        if not context:
            reply = (
                "Hi! I couldn't find your number associated with any open debts in this Splitwise group. "
                "Please make sure your phone number matches your Splitwise profile."
            )
            self.imessage.send_message(sender, reply)
            return

        print(f"[AI] Generating token-optimized explanation for {context['user_name']}...")
        # ALWAYS uses AI to explain the debt and simplified routing as requested
        ai_reply = self.ai.explain_debt(context, user_question=question_text)
        
        print(f"[Outbound iMessage] Replying to {sender}...")
        self.imessage.send_message(sender, ai_reply)

    def run_listener_loop(self, poll_interval: int = 3):
        """Continuously polls for incoming iMessages and replies."""
        has_perm, perm_msg = self.imessage.check_permissions()
        if not has_perm:
            print("\n" + "!" * 60)
            print("PERMISSIONS WARNING:")
            print(perm_msg)
            print("!" * 60 + "\n")
            print("Starting listener anyway (if Full Disk Access is missing, incoming messages won't be detected)...")

        print(f"\n[Bot] Listening for incoming iMessages (Polling every {poll_interval}s)...")
        print("Press Ctrl+C to stop.\n")

        try:
            while True:
                new_messages = self.imessage.get_new_messages()
                for msg in new_messages:
                    text = msg["text"].strip().lower()
                    sender = msg["sender"]
                    # Check if message is asking about debts
                    triggers = ["why", "owe", "splitwise", "pay", "balance", "cost", "breakdown", "who"]
                    if any(t in text for t in triggers):
                        self.handle_incoming_question(sender, msg["text"])
                    else:
                        print(f"[Ignored] Message from {sender} did not contain debt keywords.")

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\nBot stopped by user.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Splitwise iMessage Bot")
    parser.add_argument("--remind", action="store_true", help="Send automated reminders to all debtors")
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
        print("  python bot.py --remind          # Check and dispatch debt reminders (Dry Run)")
        print("  python bot.py --remind --live   # Dispatch real iMessages")
        print("  python bot.py --listen          # Run background listener for incoming texts")
        print("  python test_demo.py             # Run interactive test suite")
