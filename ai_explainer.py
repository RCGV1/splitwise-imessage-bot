"""
AI Explainer module for Splitwise debts.
Uses AI to explain complex Simplified Debts routing,
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
        self.openai_client = None
        self.gemini_client = None
        self._init_clients()

    def _init_clients(self):
        config.reload_env()
        self.provider = config.AI_PROVIDER
        if config.has_ai_creds():
            try:
                if self.provider == "openai":
                    from openai import OpenAI
                    self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
                elif self.provider == "gemini":
                    from google import genai
                    self.gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
            except Exception as e:
                print(f"Error initializing AI client ({self.provider}): {e}")

    def is_configured(self) -> bool:
        self._init_clients()
        return config.has_ai_creds()

    def explain_debt(self, context: Dict[str, Any], user_question: str = "") -> str:
        """
        Builds a compact prompt (<250 tokens) and queries the AI model.
        """
        self._init_clients()

        if not config.has_ai_creds():
            return "⚠️ AI model not connected. Please connect OpenAI or Google Gemini in the dashboard to generate live debt explanations."

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

        is_simplified = context.get("is_simplified", True)
        if is_simplified:
            active_system_prompt = SYSTEM_PROMPT
            debt_header = "SIMPLIFIED DEBT INSTRUCTION"
            graph_header = "SIMPLIFIED DEBT ROUTING GRAPH"
            default_question = "Why do I owe this amount, and why am I paying this specific person?"
        else:
            active_system_prompt = """You are a helpful, concise iMessage financial assistant for a Splitwise group.
The group has "Simplify Debts" turned OFF. All debts are direct, 1-to-1 unsimplified balances between members.
Your job is to:
1. Break down what they consumed vs what they paid for shared expenses.
2. Clearly explain why they owe this specific person directly based on direct shared transactions. Do NOT mention debt simplification or routing chains.
3. Keep it brief, friendly, and formatted for a text message (short paragraphs, max 150-180 words).
Rely strictly on the provided ledger figures. Do not make up any numbers.
"""
            debt_header = "DIRECT UN-SIMPLIFIED DEBTS TO SETTLE"
            graph_header = "DIRECT MEMBER-TO-MEMBER DEBTS"
            default_question = "Why do I owe this amount directly to this person?"

        settlements_str = ", ".join(
            [f"Pay {s['to_name']} ${s['amount']:.2f}" for s in settlements]
        ) if settlements else "No outgoing payments needed (balance settled)."

        ledger_prompt = f"""GROUP: {context['group_name']}
USER: {user_name}
NET BALANCE: ${net_balance:.2f} (negative means user owes money)
MODE: {"Simplified Debts Enabled" if is_simplified else "Direct Unsimplified Debts (Simplify Debts OFF)"}
{debt_header}: {settlements_str}

USER EXPENSE CONSUMPTION (Total: ${total_consumed:.2f}):
{chr(10).join(consumed_lines) or "None"}

USER DIRECT PAYMENTS (Total: ${total_paid:.2f}):
{chr(10).join(paid_lines) or "None ($0.00)"}

GROUP NET BALANCES:
{", ".join(f"{k}: ${v:.2f}" for k, v in group_balances.items())}

{graph_header}:
{"; ".join(graph)}

USER QUESTION: {user_question or default_question}
"""

        try:
            if self.provider == "openai" and self.openai_client:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": active_system_prompt},
                        {"role": "user", "content": ledger_prompt}
                    ],
                    max_tokens=250,
                    temperature=0.2
                )
                return response.choices[0].message.content.strip()

            elif self.provider == "gemini" and self.gemini_client:
                full_prompt = f"{active_system_prompt}\n\n{ledger_prompt}"
                # Try gemini-3.6-flash, fallback to gemini-2.0-flash / gemini-1.5-flash if needed
                last_err = None
                for m in ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                    try:
                        response = self.gemini_client.models.generate_content(
                            model=m,
                            contents=full_prompt,
                        )
                        return response.text.strip()
                    except Exception as err:
                        last_err = err
                if last_err:
                    raise last_err
            else:
                return "⚠️ Selected AI provider is not available or credentials missing."

        except Exception as e:
            return f"Error connecting to {self.provider}: {str(e)}\n\nFallback breakdown:\nTotal consumed: ${total_consumed:.2f}, Paid: ${total_paid:.2f}, Net balance: ${net_balance:.2f}."
