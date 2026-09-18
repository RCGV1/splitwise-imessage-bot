"""
Splitwise client wrapper for fetching group details, member balances,
itemized expenses, simplified debts graph, and OAuth web onboarding.
Includes mock fallback data for immediate demoing.
"""

from typing import Dict, List, Optional, Any, Tuple
from splitwise import Splitwise
import config

class SplitwiseClient:
    def __init__(self):
        self.s = None
        self.is_mock = True
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
                self.is_mock = False
            except Exception as e:
                print(f"Error initializing Splitwise client: {e}")
                self.s = None
                self.is_mock = True
        else:
            self.s = None
            self.is_mock = True

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
        if self.is_mock or not self.s:
            return {
                "id": 999,
                "name": "Demo Host",
                "email": "demo@example.com",
                "avatar": "https://s3.amazonaws.com/splitwise/uploads/user/avatar/999/medium_avatar.png",
                "is_mock": True
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
                "is_mock": False
            }
        except Exception as e:
            print(f"Error fetching current user: {e}")
            return {
                "id": 0,
                "name": "Connected User",
                "email": "",
                "avatar": "",
                "is_mock": False
            }

    def get_groups(self) -> List[Dict[str, Any]]:
        """List groups with their IDs and names."""
        if self.is_mock or not self.s:
            return [{"id": 101, "name": "Tahoe Ski Trip (Demo Group)"}]
        
        try:
            groups = self.s.getGroups()
            return [{"id": g.getId(), "name": g.getName()} for g in groups]
        except Exception as e:
            print(f"Error retrieving groups: {e}")
            return [{"id": 101, "name": "Tahoe Ski Trip (Demo Group)"}]

    def get_group_details(self, group_id: int) -> Dict[str, Any]:
        """Fetch group members, balances, simplified debts, and expenses."""
        if self.is_mock or not self.s or group_id == 101 or group_id == 0:
            return self._get_mock_group_details()

        try:
            group = self.s.getGroup(group_id)
            if not group:
                return self._get_mock_group_details()

            members_map = {}
            for member in group.getMembers():
                net_balance = 0.0
                for b in member.getBalances():
                    net_balance += float(b.getAmount())
                
                phone_num = getattr(member, "phone_number", None) or getattr(member, "phone", "")
                full_name = f"{member.getFirstName() or ''} {member.getLastName() or ''}".strip()
                
                members_map[member.getId()] = {
                    "id": member.getId(),
                    "name": full_name or f"User {member.getId()}",
                    "email": member.getEmail() or "",
                    "phone": phone_num or "",
                    "net_balance": round(net_balance, 2)
                }

            simplified_debts = []
            for debt in group.getSimplifiedDebts():
                from_id = debt.getFrom()
                to_id = debt.getTo()
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
                "simplified_debts": simplified_debts,
                "expenses": parsed_expenses
            }
        except Exception as e:
            print(f"Error fetching group {group_id}: {e}")
            return self._get_mock_group_details()

    def get_user_debt_context(self, group_id: int, user_query: str) -> Optional[Dict[str, Any]]:
        """
        Finds a user by phone or name in the group and produces a clean,
        compact summary context specifically tailored for AI debt explanation.
        """
        data = self.get_group_details(group_id)
        members = data["members"]

        target_member = None
        cleaned_query = user_query.strip().lower().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        
        for m in members.values():
            m_name = m["name"].lower()
            m_phone = str(m["phone"]).replace("-", "").replace(" ", "")
            if cleaned_query in m_name or (m_phone and cleaned_query in m_phone):
                target_member = m
                break

        if not target_member:
            return None

        u_id = target_member["id"]
        u_name = target_member["name"]
        net_balance = target_member["net_balance"]

        settlements_to_pay = [
            d for d in data["simplified_debts"] if d["from_id"] == u_id
        ]
        settlements_to_receive = [
            d for d in data["simplified_debts"] if d["to_id"] == u_id
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

        return {
            "group_name": data["group_name"],
            "user_name": u_name,
            "user_id": u_id,
            "net_balance": net_balance,
            "simplified_settlements": settlements_to_pay,
            "incoming_settlements": settlements_to_receive,
            "consumed_items": consumed_items,
            "paid_items": paid_items,
            "all_members_balances": {
                m["name"]: m["net_balance"] for m in members.values()
            },
            "simplified_debts_graph": [
                f"{d['from_name']} pays {d['to_name']} ${d['amount']:.2f}"
                for d in data["simplified_debts"]
            ]
        }

    def _get_mock_group_details(self) -> Dict[str, Any]:
        """Realistic mock group demonstrating a confusing simplified-debt scenario."""
        members = {
            1: {"id": 1, "name": "Alex", "phone": "+14085551234", "email": "alex@example.com", "net_balance": -250.00},
            2: {"id": 2, "name": "Sarah", "phone": "+14085552345", "email": "sarah@example.com", "net_balance": 350.00},
            3: {"id": 3, "name": "Bob", "phone": "+14085553456", "email": "bob@example.com", "net_balance": -10.00},
            4: {"id": 4, "name": "Chloe", "phone": "+14085554567", "email": "chloe@example.com", "net_balance": -90.00}
        }
        
        simplified_debts = [
            {"from_id": 1, "from_name": "Alex", "to_id": 2, "to_name": "Sarah", "amount": 250.00, "currency": "USD"},
            {"from_id": 3, "from_name": "Bob", "to_id": 2, "to_name": "Sarah", "amount": 10.00, "currency": "USD"},
            {"from_id": 4, "from_name": "Chloe", "to_id": 2, "to_name": "Sarah", "amount": 90.00, "currency": "USD"}
        ]

        expenses = [
            {
                "id": 1001,
                "description": "Airbnb Cabin Rental",
                "cost": 400.00,
                "date": "2026-09-12",
                "paid_by": [{"user_id": 2, "name": "Sarah", "paid": 400.00}],
                "shares": [
                    {"user_id": 1, "name": "Alex", "owed": 100.00},
                    {"user_id": 2, "name": "Sarah", "owed": 100.00},
                    {"user_id": 3, "name": "Bob", "owed": 100.00},
                    {"user_id": 4, "name": "Chloe", "owed": 100.00}
                ]
            },
            {
                "id": 1002,
                "description": "Costco Groceries & Snacks",
                "cost": 120.00,
                "date": "2026-09-13",
                "paid_by": [{"user_id": 3, "name": "Bob", "paid": 120.00}],
                "shares": [
                    {"user_id": 1, "name": "Alex", "owed": 30.00},
                    {"user_id": 2, "name": "Sarah", "owed": 30.00},
                    {"user_id": 3, "name": "Bob", "owed": 30.00},
                    {"user_id": 4, "name": "Chloe", "owed": 30.00}
                ]
            },
            {
                "id": 1003,
                "description": "Gas & Bridge Tolls",
                "cost": 60.00,
                "date": "2026-09-13",
                "paid_by": [{"user_id": 4, "name": "Chloe", "paid": 60.00}],
                "shares": [
                    {"user_id": 1, "name": "Alex", "owed": 20.00},
                    {"user_id": 2, "name": "Sarah", "owed": 20.00},
                    {"user_id": 4, "name": "Chloe", "owed": 20.00}
                ]
            },
            {
                "id": 1004,
                "description": "Ski Pass / Lift Tickets",
                "cost": 200.00,
                "date": "2026-09-14",
                "paid_by": [{"user_id": 2, "name": "Sarah", "paid": 200.00}],
                "shares": [
                    {"user_id": 1, "name": "Alex", "owed": 100.00},
                    {"user_id": 2, "name": "Sarah", "owed": 100.00}
                ]
            }
        ]

        return {
            "group_id": 101,
            "group_name": "Tahoe Ski Trip (Demo)",
            "members": members,
            "simplified_debts": simplified_debts,
            "expenses": expenses
        }
