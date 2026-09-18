"""
Interactive Test & Demo CLI for the Splitwise iMessage Bot.
Run with:
    source .venv/bin/activate
    python test_demo.py
"""

import sys
import config
from splitwise_client import SplitwiseClient
from ai_explainer import AIExplainer
from imessage import IMessageBridge

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def test_permissions_and_config():
    print_header("1. CONFIGURATION & PERMISSION STATUS")
    print(f"Splitwise API Connected: {'YES (Live)' if config.has_splitwise_creds() else 'NO (Using Mock Demo Data)'}")
    print(f"AI Provider Configured:  {config.AI_PROVIDER.upper()} - {'YES (Live)' if config.has_ai_creds() else 'NO (Using Demo AI Explainer)'}")
    
    bridge = IMessageBridge(dry_run=True)
    has_perm, msg = bridge.check_permissions()
    print(f"\nAppleScript (Outbound iMessage): {'READY' if 'AppleScript' not in msg or has_perm else 'NEEDS PERMISSION'}")
    print(f"Full Disk Access (Inbound iMessage): {'READY' if has_perm else 'ACTION REQUIRED'}")
    if not has_perm:
        print(f"\n[Note] {msg}")

def test_group_and_simplified_debts():
    print_header("2. SPLITWISE GROUP & SIMPLIFIED DEBTS")
    sw = SplitwiseClient()
    groups = sw.get_groups()
    print(f"Available Groups ({len(groups)}):")
    for g in groups:
        print(f"  • ID {g['id']}: {g['name']}")

    sample_id = groups[0]["id"]
    details = sw.get_group_details(sample_id)
    print(f"\nInspecting Group: '{details['group_name']}'")
    print("\nMembers & Balances:")
    for m in details["members"].values():
        status = f"+${m['net_balance']:.2f} (Owed)" if m['net_balance'] > 0 else f"-${abs(m['net_balance']):.2f} (Owes)" if m['net_balance'] < 0 else "$0.00 (Settled)"
        print(f"  • {m['name']:<10} -> {status}")

    print("\nSimplified Debts (Who settles with whom):")
    for d in details["simplified_debts"]:
        print(f"  • {d['from_name']} pays {d['to_name']} ${d['amount']:.2f}")

def test_ai_explanation():
    print_header("3. AI DEBT EXPLANATION SIMULATION")
    sw = SplitwiseClient()
    ai = AIExplainer()

    groups = sw.get_groups()
    sample_id = groups[0]["id"]

    # Test with Alex (owes $250 to Sarah in the demo scenario)
    debtor_name = "Alex"
    print(f"Target User: '{debtor_name}'")
    context = sw.get_user_debt_context(sample_id, debtor_name)

    if not context:
        print(f"Could not find context for {debtor_name}.")
        return

    simulated_question = "Why am I paying Sarah $250? I thought I only shared the cabin and lift ticket with her, Bob bought groceries!"
    print(f"\nSimulated User iMessage:\n\"{simulated_question}\"")
    print("\nGenerating AI explanation (optimized for minimal tokens)...")
    
    explanation = ai.explain_debt(context, user_question=simulated_question)
    
    print("\n" + "-" * 50)
    print("AI RESPONSE (Sent via iMessage):")
    print("-" * 50)
    print(explanation)
    print("-" * 50)

def test_send_real_imessage():
    print_header("4. LIVE iMESSAGE SEND TEST")
    target = input("Enter your phone number or Apple ID email to receive a test message (or press Enter to skip): ").strip()
    if not target:
        print("Skipped live iMessage test.")
        return

    bridge = IMessageBridge(dry_run=False)
    test_text = "🎉 Hello from your Splitwise Bot on your Mac! iMessage automation is working."
    print(f"Sending test iMessage to {target}...")
    success = bridge.send_message(target, test_text)
    if success:
        print("Message sent successfully! Check your Messages app.")
    else:
        print("Failed to send message. Please check Messages.app permissions.")

def main():
    while True:
        print_header("SPLITWISE iMESSAGE BOT - DEMO & TEST MENU")
        print("1. Check Config & macOS Permissions")
        print("2. View Splitwise Group Balances & Simplified Debts")
        print("3. Simulate AI Debt Explanation ('Why do I owe $X?')")
        print("4. Send a Real Test iMessage to your Phone")
        print("5. Run Automated Reminders (Dry Run)")
        print("6. Exit")
        
        choice = input("\nSelect an option (1-6): ").strip()
        if choice == "1":
            test_permissions_and_config()
        elif choice == "2":
            test_group_and_simplified_debts()
        elif choice == "3":
            test_ai_explanation()
        elif choice == "4":
            test_send_real_imessage()
        elif choice == "5":
            from bot import SplitwiseBot
            bot = SplitwiseBot(dry_run=True)
            bot.send_reminders()
        elif choice == "6":
            print("\nExiting. Happy splitting!")
            break
        else:
            print("Invalid choice. Please enter 1-6.")

if __name__ == "__main__":
    main()
