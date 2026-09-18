"""
AI Explainer module for Splitwise debts.
Always uses AI to explain complex Simplified Debts routing,
using minimal prompt tokens to keep credit usage near zero.
Supports OpenAI (gpt-4o-mini) and Gemini (gemini-2.5-flash).
"""

from typing import Dict, Any, Optional
import config

SYSTEM_PROMPT = """You are a helpful, concise iMessage financial assistant for a Splitwise group.
The user is confused about why they owe money, especially due to Splitwise's "Simplified Debts" feature.
Your job is to:
1. Break down what they consumed vs what they paid.
2. Clearly explain why Splitwise routes their payment to this specific person (explain the simplified debt chain simply, e.g. "Person B paid for X, but Person B owed Person A, so you pay Person A directly to settle everyone in fewer transactions").
3. Keep it brief, friendly, and formatted for a text message (short paragraphs, max 150-180 words).
Rely strictly on the provided ledger figures. Do not make up any numbers.
"""

class AIExplainer:
    def __init__(self):
        self.provider = config.AI_PROVIDER
        self.openai_client = None
        self.gemini_client = None

        if config.has_ai_creds():
            if self.provider == "openai":
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
            elif self.provider == "gemini":
                from google import genai
                self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

    def explain_debt(self, context: Dict[str, Any], user_question: str = "") -> str:
        """
        Builds a compact prompt (<250 tokens) and queries the AI model.
        """
        # 1. Prepare dense, token-minimized context
        user_name = context["user_name"]
        net_balance = context["net_balance"]
        settlements = context["simplified_settlements"]
        consumed = context["consumed_items"]
        paid = context["paid_items"]
        group_balances = context["all_members_balances"]
        graph = context["simplified_debts_graph"]

        # Format compact list of consumed items
        consumed_lines = []
        total_consumed = 0.0
        for item in consumed:
            consumed_lines.append(
                f"- {item['description']}: your share ${item['user_share']:.2f} (originally paid by {item['paid_by']})"
            )
            total_consumed += item["user_share"]

        # Format compact list of paid items
        paid_lines = []
        total_paid = 0.0
        for item in paid:
            paid_lines.append(
                f"- {item['description']}: you paid ${item['amount_paid']:.2f}"
            )
            total_paid += item["amount_paid"]

        settlements_str = ", ".join(
            [f"Pay {s['to_name']} ${s['amount']:.2f}" for s in settlements]
        ) if settlements else "No outgoing payments needed (balance settled)."

        ledger_prompt = f"""GROUP: {context['group_name']}
USER: {user_name}
NET BALANCE: ${net_balance:.2f} (negative means user owes money)
SIMPLIFIED DEBT INSTRUCTION: {settlements_str}

USER EXPENSE CONSUMPTION (Total: ${total_consumed:.2f}):
{chr(10).join(consumed_lines) or "None"}

USER DIRECT PAYMENTS (Total: ${total_paid:.2f}):
{chr(10).join(paid_lines) or "None ($0.00)"}

GROUP NET BALANCES:
{", ".join(f"{k}: ${v:.2f}" for k, v in group_balances.items())}

SIMPLIFIED DEBT ROUTING:
{"; ".join(graph)}

USER QUESTION: {user_question or "Why do I owe this amount, and why am I paying this specific person?"}
"""

        if not config.has_ai_creds():
            return self._mock_explanation(context, total_consumed, total_paid, settlements_str)

        try:
            if self.provider == "openai" and self.openai_client:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": ledger_prompt}
                    ],
                    max_tokens=250,
                    temperature=0.2
                )
                return response.choices[0].message.content.strip()

            elif self.provider == "gemini" and self.gemini_client:
                # Use gemini-2.5-flash or gemini-1.5-flash
                full_prompt = f"{SYSTEM_PROMPT}\n\n{ledger_prompt}"
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_prompt,
                )
                return response.text.strip()
            else:
                return self._mock_explanation(context, total_consumed, total_paid, settlements_str)

        except Exception as e:
            return f"Error connecting to {self.provider}: {str(e)}\n\nFallback breakdown:\nTotal consumed: ${total_consumed:.2f}, Paid: ${total_paid:.2f}, Net: ${net_balance:.2f}."

    def _mock_explanation(self, context: Dict[str, Any], total_consumed: float, total_paid: float, settlements_str: str) -> str:
        """Demo response showcasing how the AI clearly breaks down the simplified debts."""
        user_name = context["user_name"]
        return (
            f"Hey {user_name}! Here's why you have {settlements_str}:\n\n"
            f"1. What you consumed (${total_consumed:.2f}):\n"
            f"• Airbnb Cabin: $100.00\n"
            f"• Groceries: $30.00 (bought by Bob)\n"
            f"• Gas & Tolls: $20.00 (bought by Chloe)\n"
            f"• Ski Pass: $100.00 (bought by Sarah)\n\n"
            f"2. Why you pay Sarah instead of Bob or Chloe:\n"
            f"Splitwise's 'Simplify Debts' combines everyone's payments so fewer transactions happen. "
            f"Bob and Chloe were owed money by you, but they also owed Sarah for the cabin. "
            f"Splitwise canceled out Bob and Chloe's debts to $0 and routes your full $250.00 directly to Sarah. "
            f"That way, everyone gets squared up in just 3 total payments instead of 8!\n\n"
            f"(Note: Add OPENAI_API_KEY or GEMINI_API_KEY in .env for live AI responses)."
        )
