"""
Splitwise client wrapper for fetching group details, member balances,
itemized expenses, simplified debts graph, and OAuth web onboarding.
Uses purely real Splitwise API data.
"""

from typing import Dict, List, Optional, Any, Tuple
from splitwise import Splitwise
import config

class SplitwiseClient:
    def __init__(self):
        self.s = None
        self._init_client()

    def _init_client(self):
        config.reload_env()
        if config.has_splitwise_creds():
            try:
                c_key = config.SPLITWISE_CONSUMER_KEY if (config.SPLITWISE_CONSUMER_KEY and config.SPLITWISE_CONSUMER_KEY != "your_consumer_key_here") else "direct_api"
                c_sec = config.SPLITWISE_CONSUMER_SECRET if (config.SPLITWISE_CONSUMER_SECRET and config.SPLITWISE_CONSUMER_SECRET != "your_consumer_secret_here") else "direct_api"
                
                self.s = Splitwise(
                    consumer_key=c_key,
                    consumer_secret=c_sec,
                    api_key=config.SPLITWISE_API_KEY if (config.SPLITWISE_API_KEY and config.SPLITWISE_API_KEY != "your_api_key_here") else None
                )
                if config.SPLITWISE_ACCESS_TOKEN and config.SPLITWISE_ACCESS_TOKEN != "your_access_token_here":
                    token_dict = {
                        "access_token": config.SPLITWISE_ACCESS_TOKEN,
                        "token_type": "bearer"
                    }
                    self.s.setOAuth2AccessToken(token_dict)
            except Exception as e:
                print(f"Error initializing Splitwise client: {e}")
                self.s = None
        else:
            self.s = None

    def is_connected(self) -> bool:
        """Returns True if authenticated with Splitwise."""
        return self.s is not None

    def get_oauth_url(self, redirect_uri: str) -> Tuple[Optional[str], Optional[str]]:
        """Generates Splitwise OAuth2 authorize URL."""
        if not config.SPLITWISE_CONSUMER_KEY or not config.SPLITWISE_CONSUMER_SECRET:
            return None, "Missing SPLITWISE_CONSUMER_KEY or SPLITWISE_CONSUMER_SECRET"
        try:
            temp_client = Splitwise(config.SPLITWISE_CONSUMER_KEY, config.SPLITWISE_CONSUMER_SECRET)
            url, state = temp_client.getOAuth2AuthorizeURL(redirect_uri)
            return url, None
        except Exception as e:
            return None, str(e)

    def handle_oauth_callback(self, code: str, redirect_uri: str) -> Tuple[bool, str]:
        """Exchanges OAuth code for access token and saves it."""
        try:
            temp_client = Splitwise(config.SPLITWISE_CONSUMER_KEY, config.SPLITWISE_CONSUMER_SECRET)
            token_data = temp_client.getOAuth2AccessToken(code, redirect_uri)
            if not token_data or "access_token" not in token_data:
                return False, "Failed to retrieve access token from Splitwise."
            
            access_token = token_data["access_token"]
            config.save_env_updates({"SPLITWISE_ACCESS_TOKEN": access_token})
            self._init_client()
            return True, "Successfully logged in with Splitwise!"
        except Exception as e:
            return False, f"OAuth error: {e}"

    def get_current_user_profile(self) -> Dict[str, Any]:
        """Returns authenticated user's profile info."""
        if not self.s:
            return {
                "id": 0,
                "name": "",
                "email": "",
                "avatar": "",
                "connected": False
            }
        try:
            u = self.s.getCurrentUser()
            full_name = f"{u.getFirstName() or ''} {u.getLastName() or ''}".strip()
            picture = u.getPicture()
            avatar_url = picture.getMedium() if picture else ""
            return {
                "id": u.getId(),
                "name": full_name or "Splitwise User",
                "email": u.getEmail() or "",
                "avatar": avatar_url,
                "connected": True
            }
        except Exception as e:
            print(f"Error fetching current user: {e}")
            return {
                "id": 0,
                "name": "",
                "email": "",
                "avatar": "",
                "connected": False,
                "error": str(e)
            }

    def get_groups(self) -> List[Dict[str, Any]]:
        """List groups with their IDs and names from real Splitwise account."""
        if not self.s:
            return []
        
        try:
            groups = self.s.getGroups()
            return [{"id": g.getId(), "name": g.getName()} for g in groups]
        except Exception as e:
            print(f"Error retrieving groups: {e}")
            return []

    def get_group_details(self, group_id: int) -> Dict[str, Any]:
        """Fetch real group members, balances, simplified debts, and expenses."""
        empty_group = {
            "group_id": group_id,
            "group_name": "No Group Selected",
            "members": {},
            "simplified_debts": [],
            "expenses": []
        }

        if not self.s or not group_id:
            return empty_group

        try:
            group = self.s.getGroup(group_id)
            if not group:
                return empty_group

            from contacts_resolver import ContactsResolver
            resolver = ContactsResolver()

            members_map = {}
            for member in group.getMembers():
                net_balance = 0.0
                for b in member.getBalances():
                    net_balance += float(b.getAmount())
                
                sp_phone = getattr(member, "phone_number", None) or getattr(member, "phone", "")
                full_name = f"{member.getFirstName() or ''} {member.getLastName() or ''}".strip()
                email = member.getEmail() or ""
                
                # Auto-resolve phone from Contacts / Directory / Splitwise
                phone_info = resolver.resolve_member_phone(member.getId(), full_name, email=email, splitwise_phone=sp_phone)

                members_map[member.getId()] = {
                    "id": member.getId(),
                    "name": full_name or f"User {member.getId()}",
                    "email": email,
                    "phone": phone_info["phone"],
                    "phone_source": phone_info["source"],
                    "net_balance": round(net_balance, 2)
                }

            simplified_debts = []
            for debt in (group.getSimplifiedDebts() or []):
                from_id = debt.getFromUser() if hasattr(debt, "getFromUser") else debt.getFrom()
                to_id = debt.getToUser() if hasattr(debt, "getToUser") else debt.getTo()
                from_name = members_map.get(from_id, {}).get("name", f"User {from_id}")
                to_name = members_map.get(to_id, {}).get("name", f"User {to_id}")
                simplified_debts.append({
                    "from_id": from_id,
                    "from_name": from_name,
                    "to_id": to_id,
                    "to_name": to_name,
                    "amount": float(debt.getAmount()),
                    "currency": debt.getCurrencyCode()
                })

            original_debts = []
            for debt in (group.getOriginalDebts() or []):
                from_id = debt.getFromUser() if hasattr(debt, "getFromUser") else debt.getFrom()
                to_id = debt.getToUser() if hasattr(debt, "getToUser") else debt.getTo()
                from_name = members_map.get(from_id, {}).get("name", f"User {from_id}")
                to_name = members_map.get(to_id, {}).get("name", f"User {to_id}")
                original_debts.append({
                    "from_id": from_id,
                    "from_name": from_name,
                    "to_id": to_id,
                    "to_name": to_name,
                    "amount": float(debt.getAmount()),
                    "currency": debt.getCurrencyCode()
                })

            simplify_by_default = getattr(group, "simplify_by_default", True)
            # If simplify_by_default is False or simplified_debts is empty, use original debts
            simplify_debts_enabled = bool(simplify_by_default and simplified_debts)
            active_debts = simplified_debts if simplify_debts_enabled else original_debts

            expenses = self.s.getExpenses(group_id=group_id, limit=50)
            parsed_expenses = []
            for exp in expenses:
                if exp.getDeletedAt() is not None:
                    continue
                
                shares = []
                paid_by = []
                for u in exp.getUsers():
                    u_id = u.getId()
                    u_name = members_map.get(u_id, {}).get("name", f"User {u_id}")
                    paid = float(u.getPaidShare() or 0.0)
                    owed = float(u.getOwedShare() or 0.0)
                    if paid > 0:
                        paid_by.append({"user_id": u_id, "name": u_name, "paid": paid})
                    if owed > 0:
                        shares.append({"user_id": u_id, "name": u_name, "owed": owed})

                parsed_expenses.append({
                    "id": exp.getId(),
                    "description": exp.getDescription(),
                    "cost": float(exp.getCost() or 0.0),
                    "date": exp.getDate(),
                    "paid_by": paid_by,
                    "shares": shares
                })

            return {
                "group_id": group_id,
                "group_name": group.getName(),
                "members": members_map,
                "simplify_debts_enabled": simplify_debts_enabled,
                "simplify_by_default": bool(simplify_by_default),
                "simplified_debts": simplified_debts,
                "original_debts": original_debts,
                "active_debts": active_debts,
                "expenses": parsed_expenses
            }
        except Exception as e:
            print(f"Error fetching group {group_id}: {e}")
            return empty_group

    def get_user_debt_context(self, group_id: int, user_query: str) -> Optional[Dict[str, Any]]:
        """
        Finds a user by phone or name in the real group and produces a clean,
        compact summary context specifically tailored for AI debt explanation.
        """
        data = self.get_group_details(group_id)
        members = data["members"]

        if not members:
            return None

        target_member = None
        raw_query = user_query.strip().lower()
        cleaned_query = "".join(c for c in raw_query if c.isalnum())
        
        # 1. Try matching by exact numeric user ID
        if raw_query.isdigit() and int(raw_query) in members:
            target_member = members[int(raw_query)]

        # 2. Match by normalized name, email, phone, or name tokens
        if not target_member:
            for m in members.values():
                m_name = m["name"].lower()
                clean_m_name = "".join(c for c in m_name if c.isalnum())
                m_email = m.get("email", "").lower()
                m_phone = "".join(c for c in str(m.get("phone", "")) if c.isalnum())
                
                # Direct normalized name match (e.g. 'elibraswell' in 'elibraswell')
                if cleaned_query and (cleaned_query in clean_m_name or clean_m_name in cleaned_query):
                    target_member = m
                    break
                
                # Email match
                if raw_query and m_email and (raw_query in m_email or m_email in raw_query):
                    target_member = m
                    break

                # Phone match
                if cleaned_query and m_phone and (cleaned_query in m_phone or m_phone.endswith(cleaned_query)):
                    target_member = m
                    break

                # Name tokens (e.g. 'Eli' matches 'Eli Braswell')
                name_tokens = [t for t in m_name.split() if t]
                if any(t == raw_query or t in raw_query for t in name_tokens):
                    target_member = m
                    break

        if not target_member:
            return None

        u_id = target_member["id"]
        u_name = target_member["name"]
        net_balance = target_member["net_balance"]

        is_simplified = data.get("simplify_debts_enabled", True)
        active_debts = data.get("active_debts") or data.get("simplified_debts") or []

        settlements_to_pay = [
            d for d in active_debts if d["from_id"] == u_id
        ]
        settlements_to_receive = [
            d for d in active_debts if d["to_id"] == u_id
        ]

        consumed_items = []
        paid_items = []
        for exp in data["expenses"]:
            for share in exp["shares"]:
                if share["user_id"] == u_id:
                    payers_str = ", ".join(p["name"] for p in exp["paid_by"])
                    consumed_items.append({
                        "description": exp["description"],
                        "total_expense": exp["cost"],
                        "user_share": share["owed"],
                        "paid_by": payers_str
                    })
            for payer in exp["paid_by"]:
                if payer["user_id"] == u_id:
                    consumed_by_str = ", ".join(s["name"] for s in exp["shares"])
                    paid_items.append({
                        "description": exp["description"],
                        "amount_paid": payer["paid"],
                        "split_among": consumed_by_str
                    })

        graph_descriptor = "pays" if is_simplified else "owes directly to"
        return {
            "group_name": data["group_name"],
            "user_name": u_name,
            "user_id": u_id,
            "net_balance": net_balance,
            "is_simplified": is_simplified,
            "simplified_settlements": settlements_to_pay,
            "incoming_settlements": settlements_to_receive,
            "consumed_items": consumed_items,
            "paid_items": paid_items,
            "all_members_balances": {
                m["name"]: m["net_balance"] for m in members.values()
            },
            "simplified_debts_graph": [
                f"{d['from_name']} {graph_descriptor} {d['to_name']} ${d['amount']:.2f}"
                for d in active_debts
            ]
        }
