"""
Web Onboarding and Management Dashboard for Splitwise iMessage Bot.
- Real Splitwise API data only (Zero mock/fake data)
- Custom Connectors for Google Gemini and OpenAI with 1-Click Link Authorization
- Group selector & real debts ledger
- macOS permissions checker & live iMessage test
- Interactive AI debt explainer chat simulator
- Automated reminder dispatch
"""

import os
import subprocess
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel

import config
from splitwise_client import SplitwiseClient
from ai_explainer import AIExplainer
from imessage import IMessageBridge
from bot import SplitwiseBot

app = FastAPI(title="Splitwise iMessage Bot Dashboard")

sw_client = SplitwiseClient()
ai_client = AIExplainer()
imessage_bridge = IMessageBridge(dry_run=config.DRY_RUN)

# ---------------------------------------------------------------------------
# API Models
# ---------------------------------------------------------------------------
class SplitwiseCredsRequest(BaseModel):
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    api_key: Optional[str] = None

class AIConfigRequest(BaseModel):
    provider: str
    api_key: str

class GroupSelectRequest(BaseModel):
    group_id: int

class TestIMessageRequest(BaseModel):
    recipient: str
    message: Optional[str] = None

class AskAIRequest(BaseModel):
    user_name_or_phone: str
    question: str

class TriggerRemindRequest(BaseModel):
    live: bool = False

class UpdatePhoneRequest(BaseModel):
    member_id: int
    phone: str

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/status")
def get_status():
    config.reload_env()
    sw = SplitwiseClient()
    user_profile = sw.get_current_user_profile()
    
    bridge = IMessageBridge(dry_run=True)
    has_perm, perm_msg = bridge.check_permissions()

    ai = AIExplainer()
    has_ai = ai.is_configured()

    return {
        "splitwise": {
            "connected": user_profile.get("connected", False),
            "user": user_profile,
            "group_id": config.SPLITWISE_GROUP_ID,
            "has_consumer_keys": bool(config.SPLITWISE_CONSUMER_KEY and config.SPLITWISE_CONSUMER_SECRET)
        },
        "ai": {
            "provider": config.AI_PROVIDER,
            "connected": has_ai,
            "has_openai": bool(config.OPENAI_API_KEY and config.OPENAI_API_KEY != "your_openai_api_key_here"),
            "has_gemini": bool(config.GEMINI_API_KEY and config.GEMINI_API_KEY != "your_gemini_api_key_here")
        },
        "permissions": {
            "applescript": "AppleScript" not in perm_msg or has_perm,
            "full_disk_access": has_perm,
            "message": perm_msg
        },
        "bot": {
            "reminder_days": config.REMINDER_INTERVAL_DAYS,
            "auto_remind_enabled": config.AUTO_REMIND_ENABLED,
            "dry_run": config.DRY_RUN
        }
    }

# ---------------------------------------------------------------------------
# Direct Link Connectors for Google and OpenAI
# ---------------------------------------------------------------------------
@app.get("/connect/google")
def connect_google_via_link(key: str):
    """Direct link authorization for Google Gemini."""
    clean_key = key.strip()
    if clean_key:
        config.save_env_updates({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": clean_key})
        global ai_client
        ai_client = AIExplainer()
    return RedirectResponse("/?authorized=google")

@app.get("/connect/openai")
def connect_openai_via_link(key: str):
    """Direct link authorization for OpenAI."""
    clean_key = key.strip()
    if clean_key:
        config.save_env_updates({"AI_PROVIDER": "openai", "OPENAI_API_KEY": clean_key})
        global ai_client
        ai_client = AIExplainer()
    return RedirectResponse("/?authorized=openai")

@app.get("/oauth/login")
def oauth_login(request: Request):
    """Initiates Splitwise OAuth2 login flow."""
    config.reload_env()
    if not config.SPLITWISE_CONSUMER_KEY or config.SPLITWISE_CONSUMER_KEY == "your_consumer_key_here":
        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html>
            <head><title>Splitwise Setup</title><script src="https://cdn.tailwindcss.com"></script></head>
            <body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen p-4">
              <div class="max-w-md bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl space-y-4">
                <h2 class="text-lg font-bold text-amber-400">Splitwise API Key Recommended!</h2>
                <p class="text-sm text-slate-300">
                  Splitwise OAuth requires your app's Consumer Key first. 
                  <strong>The easiest way (takes 30 seconds)</strong> is to use your personal Splitwise API Key:
                </p>
                <ol class="text-xs text-slate-400 space-y-2 list-decimal list-inside bg-slate-950 p-3 rounded-xl border border-slate-800">
                  <li>Open <a href="https://secure.splitwise.com/apps/new" target="_blank" class="text-emerald-400 underline">secure.splitwise.com/apps/new</a></li>
                  <li>Type any app name (e.g. <code>My Bot</code>) and register</li>
                  <li>Copy <strong>"Your API Key"</strong> from that page</li>
                  <li>Paste it into the API Key box on the dashboard!</li>
                </ol>
                <a href="/" class="block text-center py-2 px-4 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-xs rounded-xl transition">
                  Return to Dashboard
                </a>
              </div>
            </body>
            </html>
            """
        )
    redirect_uri = f"{request.base_url}oauth/callback"
    url, err = sw_client.get_oauth_url(redirect_uri)
    if err:
        return HTMLResponse(f"<h3>Error starting OAuth:</h3><p>{err}</p><a href='/'>Go back</a>", status_code=400)
    return RedirectResponse(url)

@app.get("/oauth/callback")
def oauth_callback(code: str, request: Request):
    """Receives authorization code from Splitwise and saves token."""
    redirect_uri = f"{request.base_url}oauth/callback"
    success, msg = sw_client.handle_oauth_callback(code, redirect_uri)
    if not success:
        return HTMLResponse(f"<h3>Login Failed:</h3><p>{msg}</p><a href='/'>Try again</a>", status_code=400)
    return RedirectResponse("/")

@app.post("/api/config/splitwise")
def save_splitwise_creds(payload: SplitwiseCredsRequest):
    updates = {}
    if payload.consumer_key:
        updates["SPLITWISE_CONSUMER_KEY"] = payload.consumer_key.strip()
    if payload.consumer_secret:
        updates["SPLITWISE_CONSUMER_SECRET"] = payload.consumer_secret.strip()
    if payload.api_key:
        updates["SPLITWISE_API_KEY"] = payload.api_key.strip()

    if updates:
        config.save_env_updates(updates)
        sw_client._init_client()

    profile = sw_client.get_current_user_profile()
    return {"success": True, "profile": profile}

@app.get("/api/groups")
def list_groups():
    return {"groups": sw_client.get_groups()}

@app.post("/api/config/group")
def select_group(payload: GroupSelectRequest):
    config.save_env_updates({"SPLITWISE_GROUP_ID": str(payload.group_id)})
    details = sw_client.get_group_details(payload.group_id)
    return {"success": True, "group": details}

@app.get("/api/group/details")
def get_active_group_details(group_id: Optional[int] = None):
    config.reload_env()
    gid = group_id or config.SPLITWISE_GROUP_ID
    return sw_client.get_group_details(gid)

@app.post("/api/config/ai")
def save_ai_config(payload: AIConfigRequest):
    updates = {"AI_PROVIDER": payload.provider.strip().lower()}
    if payload.provider.lower() == "openai":
        updates["OPENAI_API_KEY"] = payload.api_key.strip()
    elif payload.provider.lower() == "gemini":
        updates["GEMINI_API_KEY"] = payload.api_key.strip()

    config.save_env_updates(updates)
    global ai_client
    ai_client = AIExplainer()
    return {"success": True, "configured": config.has_ai_creds()}

@app.post("/api/test/ai")
def test_ai_connection():
    if not config.has_ai_creds():
        return {"success": False, "error": "No AI credentials configured in .env."}
    try:
        if config.AI_PROVIDER == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Respond strictly with: 'OpenAI connected'"}],
                max_tokens=10
            )
            return {"success": True, "reply": resp.choices[0].message.content.strip()}
        elif config.AI_PROVIDER == "gemini":
            from google import genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            last_err = None
            for m in ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents="Respond strictly with: 'Gemini connected'",
                    )
                    return {"success": True, "reply": f"{resp.text.strip()} ({m})"}
                except Exception as err:
                    last_err = err
            if last_err:
                raise last_err
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/open/full-disk-access")
def open_full_disk_access_helper():
    import subprocess
    # 1. Open System Settings to Full Disk Access
    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
    # 2. Reveal Antigravity.app in Finder so user can drag and drop it
    if os.path.exists("/Applications/Antigravity.app"):
        subprocess.run(["open", "-R", "/Applications/Antigravity.app"])
    return {"success": True}

@app.post("/api/test/imessage")
def test_imessage(payload: TestIMessageRequest):
    bridge = IMessageBridge(dry_run=False)
    msg = payload.message or "🎉 Hello from your Splitwise Bot on your Mac! iMessage automation is working."
    success = bridge.send_message(payload.recipient, msg)
    return {"success": success}

@app.post("/api/ai/ask")
def ask_ai_explanation(payload: AskAIRequest):
    group_id = config.SPLITWISE_GROUP_ID
    if not group_id:
        return {"success": False, "error": "Please select a Splitwise group first."}

    context = sw_client.get_user_debt_context(group_id, payload.user_name_or_phone)
    if not context:
        return {"success": False, "error": f"Member '{payload.user_name_or_phone}' not found in group."}
    
    explanation = ai_client.explain_debt(context, user_question=payload.question)
    return {
        "success": True,
        "explanation": explanation,
        "context": {
            "user": context["user_name"],
            "net_balance": context["net_balance"],
            "simplified_settlements": context["simplified_settlements"]
        }
    }

@app.post("/api/members/phone")
def update_member_phone(payload: UpdatePhoneRequest):
    from contacts_resolver import ContactsResolver
    resolver = ContactsResolver()
    cleaned = resolver.set_member_phone(payload.member_id, payload.phone)
    return {"success": True, "phone": cleaned}

@app.post("/api/bot/remind")
def trigger_reminders(payload: TriggerRemindRequest):
    bot = SplitwiseBot(dry_run=not payload.live)
    group_id = config.SPLITWISE_GROUP_ID
    if not group_id:
        return {"success": False, "error": "Please select a Splitwise group first."}
    bot.send_reminders(group_id=group_id, force=payload.live)
    return {"success": True, "mode": "Live Messages Sent" if payload.live else "Dry Run Simulated"}

@app.get("/api/schedule/status")
def get_schedule_status():
    plist = Path.home() / "Library/LaunchAgents/com.splitwise.imessagebot.plist"
    return {"active": plist.exists(), "frequency": "Sundays at 6:00 PM"}

@app.post("/api/schedule/toggle")
def toggle_schedule(payload: dict):
    enable = payload.get("enable", True)
    script_dir = Path(__file__).resolve().parent / "scripts"
    cmd = [str(script_dir / ("enable_sunday_schedule.sh" if enable else "disable_schedule.sh"))]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"success": True, "active": enable, "output": res.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Single Page Dashboard UI
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_CONTENT

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Splitwise iMessage Bot - Real-Time Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    @keyframes pulse-slow { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    .animate-pulse-slow { animation: pulse-slow 3s infinite; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
  <!-- Top Navbar -->
  <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-50">
    <div class="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center text-slate-950 font-bold shadow-lg shadow-emerald-500/20">
          <i data-lucide="message-circle" class="w-6 h-6"></i>
        </div>
        <div>
          <h1 class="font-semibold text-lg leading-tight">Splitwise iMessage Bot</h1>
          <p class="text-xs text-slate-400">Live Production Dashboard (No Mock Data)</p>
        </div>
      </div>
      <div id="live-badges" class="flex items-center gap-3 text-xs">
        <span id="badge-splitwise" class="px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 flex items-center gap-1.5 border border-slate-700">
          <span class="w-2 h-2 rounded-full bg-slate-500"></span> Splitwise: Checking...
        </span>
        <span id="badge-ai" class="px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 flex items-center gap-1.5 border border-slate-700">
          <span class="w-2 h-2 rounded-full bg-slate-500"></span> AI: Checking...
        </span>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-6xl mx-auto px-4 py-8 space-y-8">
    
    <!-- Hero Banner -->
    <div class="bg-gradient-to-r from-slate-900 via-slate-850 to-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
      <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 class="text-2xl font-bold text-white mb-1">Splitwise Real-Time Control Center</h2>
          <p class="text-slate-400 text-sm max-w-xl">
            Live group sync, custom link connectors for Google Gemini & OpenAI, and real iMessage debt explanations.
          </p>
        </div>
        <div class="flex gap-2">
          <button onclick="triggerRemind(false)" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium rounded-lg border border-slate-700 transition flex items-center gap-2">
            <i data-lucide="eye" class="w-4 h-4 text-emerald-400"></i> Preview Reminders
          </button>
          <button onclick="triggerRemind(true)" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-semibold rounded-lg shadow-lg shadow-emerald-500/20 transition flex items-center gap-2">
            <i data-lucide="send" class="w-4 h-4"></i> Dispatch Live iMessages
          </button>
        </div>
      </div>
    </div>

    <!-- 3 Setup Columns -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">

      <!-- STEP 1: SPLITWISE LOGIN -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col justify-between shadow-lg">
        <div>
          <div class="flex items-center justify-between mb-4">
            <span class="text-xs font-semibold uppercase tracking-wider text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/60">Step 1</span>
            <div id="sw-status-indicator" class="text-slate-400 text-xs font-medium">Not Connected</div>
          </div>
          <h3 class="text-lg font-semibold mb-1 flex items-center gap-2">
            <i data-lucide="wallet" class="w-5 h-5 text-emerald-400"></i> Connect Splitwise
          </h3>
          <p class="text-slate-400 text-xs mb-3">
            Paste your free API Key from Splitwise (100% free, no Pro required).
          </p>

          <!-- Connected Profile Card -->
          <div id="sw-profile-card" class="hidden mb-4 p-3 bg-slate-800/80 rounded-xl border border-slate-700 flex items-center gap-3">
            <div id="sw-avatar" class="w-10 h-10 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold overflow-hidden">
              <i data-lucide="user" class="w-5 h-5"></i>
            </div>
            <div class="overflow-hidden">
              <p id="sw-name" class="font-medium text-sm text-white truncate"></p>
              <p id="sw-email" class="text-xs text-slate-400 truncate"></p>
            </div>
          </div>

          <!-- Quick API Key Connect -->
          <div class="space-y-2.5">
            <div class="p-2.5 bg-slate-950 rounded-xl border border-slate-800 text-[11px] text-slate-400 space-y-1">
              <p class="font-medium text-slate-300">How to get your free API Key:</p>
              <ol class="list-decimal list-inside space-y-0.5 text-slate-400">
                <li>Open <a href="https://secure.splitwise.com/apps/new" target="_blank" class="text-emerald-400 underline font-medium">Splitwise Apps (Click Here)</a></li>
                <li>Give it any name (e.g. <code class="text-slate-300">My Bot</code>) & submit</li>
                <li>Copy <strong>"Your API Key"</strong> on that page</li>
              </ol>
            </div>

            <input type="password" id="input-sw-api-key" placeholder="Paste Splitwise API Key here" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500">
            <button onclick="saveSplitwiseApiKey()" class="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl transition shadow-md flex items-center justify-center gap-1.5">
              <i data-lucide="check" class="w-4 h-4"></i> Connect Splitwise
            </button>
            <p id="sw-api-key-result" class="text-[11px] text-center text-slate-400"></p>

            <!-- Advanced OAuth -->
            <details class="text-xs text-slate-400 pt-2 border-t border-slate-800/80">
              <summary class="cursor-pointer hover:text-slate-300 text-[11px]">Or use Splitwise OAuth (Advanced)</summary>
              <div class="mt-2 space-y-2">
                <input type="text" id="input-sw-consumer-key" placeholder="Consumer Key" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-slate-200">
                <input type="password" id="input-sw-consumer-secret" placeholder="Consumer Secret" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-slate-200">
                <button onclick="saveSplitwiseOAuthCreds()" class="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs rounded-lg transition">Save Consumer Keys</button>
                <a href="/oauth/login" class="w-full py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-center block rounded-lg text-xs">Launch OAuth Login</a>
              </div>
            </details>
          </div>
        </div>
      </div>

      <!-- STEP 2: GROUP SELECTOR -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col justify-between shadow-lg">
        <div>
          <div class="flex items-center justify-between mb-4">
            <span class="text-xs font-semibold uppercase tracking-wider text-blue-400 bg-blue-950/60 px-2 py-0.5 rounded border border-blue-800/60">Step 2</span>
            <div id="group-count" class="text-slate-400 text-xs">0 Groups</div>
          </div>
          <h3 class="text-lg font-semibold mb-1 flex items-center gap-2">
            <i data-lucide="users" class="w-5 h-5 text-blue-400"></i> Select Your Group
          </h3>
          <p class="text-slate-400 text-xs mb-4">
            Select a live Splitwise group to monitor and explain.
          </p>

          <div class="space-y-3">
            <select id="select-group" onchange="onGroupChanged()" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2.5 text-slate-200 focus:outline-none focus:border-blue-500">
              <option value="">Connect Splitwise to view your groups</option>
            </select>
            <div id="active-group-summary" class="p-3 bg-slate-800/50 rounded-xl border border-slate-700/60 text-xs text-slate-300 space-y-1">
              <p>Active: <strong id="summary-group-name" class="text-white">None selected</strong></p>
              <p>Debtors: <span id="summary-debtors-count" class="text-slate-400">0 open debts</span></p>
            </div>
          </div>
        </div>
      </div>

      <!-- STEP 3: CUSTOM CONNECTORS (GOOGLE & OPENAI VIA LINK) -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 flex flex-col justify-between shadow-lg">
        <div>
          <div class="flex items-center justify-between mb-4">
            <span class="text-xs font-semibold uppercase tracking-wider text-purple-400 bg-purple-950/60 px-2 py-0.5 rounded border border-purple-800/60">Step 3</span>
            <div id="ai-status-indicator" class="text-slate-400 text-xs font-medium">Not Connected</div>
          </div>
          <h3 class="text-lg font-semibold mb-1 flex items-center gap-2">
            <i data-lucide="sparkles" class="w-5 h-5 text-purple-400"></i> AI Custom Connectors
          </h3>
          <p class="text-slate-400 text-xs mb-3">
            Authorize Google Gemini or OpenAI directly via 1-click authorization links.
          </p>

          <!-- Provider Tabs -->
          <div class="grid grid-cols-2 gap-2 text-xs mb-3">
            <button id="btn-provider-gemini" onclick="setProvider('gemini')" class="py-2 px-2.5 rounded-lg border border-purple-500 bg-purple-950/40 text-purple-300 font-medium flex items-center justify-center gap-1.5">
              <span>Google Gemini</span>
            </button>
            <button id="btn-provider-openai" onclick="setProvider('openai')" class="py-2 px-2.5 rounded-lg border border-slate-800 bg-slate-950 text-slate-400 font-medium flex items-center justify-center gap-1.5">
              <span>OpenAI (4o-mini)</span>
            </button>
          </div>

          <!-- Google Connector Box -->
          <div id="connector-gemini-box" class="space-y-2.5">
            <div class="p-2.5 bg-slate-950 rounded-xl border border-slate-800 text-[11px] text-slate-300 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="font-medium text-emerald-400 flex items-center gap-1">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Google Gemini 3.6 Flash
                </span>
                <span class="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">Free Tier</span>
              </div>
              <p class="text-slate-400 text-[10px]">Click below to create a Gemini key with 1 click in Google AI Studio:</p>
              <a href="https://aistudio.google.com/app/apikey" target="_blank" class="w-full py-1.5 bg-purple-600/30 hover:bg-purple-600/40 text-purple-300 border border-purple-500/40 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition">
                <i data-lucide="external-link" class="w-3.5 h-3.5"></i> 1-Click Authorize with Google
              </a>
            </div>
            <input type="password" id="input-gemini-key" placeholder="Paste Gemini Key (AIza...)" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-purple-500">
            <button onclick="saveAndTestAI('gemini')" class="w-full py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold rounded-xl transition shadow-md flex items-center justify-center gap-1.5">
              <i data-lucide="link-2" class="w-4 h-4"></i> Connect Google Gemini
            </button>
          </div>

          <!-- OpenAI Connector Box -->
          <div id="connector-openai-box" class="hidden space-y-2.5">
            <div class="p-2.5 bg-slate-950 rounded-xl border border-slate-800 text-[11px] text-slate-300 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="font-medium text-emerald-400 flex items-center gap-1">
                  <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> OpenAI gpt-4o-mini
                </span>
                <span class="text-[10px] bg-slate-800 px-1.5 py-0.5 rounded text-slate-400">&lt;$0.0001/req</span>
              </div>
              <p class="text-slate-400 text-[10px]">Click below to open your OpenAI API Keys dashboard:</p>
              <a href="https://platform.openai.com/api-keys" target="_blank" class="w-full py-1.5 bg-purple-600/30 hover:bg-purple-600/40 text-purple-300 border border-purple-500/40 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition">
                <i data-lucide="external-link" class="w-3.5 h-3.5"></i> 1-Click Authorize with OpenAI
              </a>
            </div>
            <input type="password" id="input-openai-key" placeholder="Paste OpenAI Key (sk-...)" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-purple-500">
            <button onclick="saveAndTestAI('openai')" class="w-full py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold rounded-xl transition shadow-md flex items-center justify-center gap-1.5">
              <i data-lucide="link-2" class="w-4 h-4"></i> Connect OpenAI
            </button>
          </div>

          <p id="ai-test-result" class="text-[11px] text-center text-slate-400 mt-2"></p>
        </div>
      </div>

    </div>

    <!-- Live Group Debts & iMessage Testing Section -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">

      <!-- LEFT: Live Group Debts Table (Simplified + Direct) -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-lg font-semibold flex items-center gap-2">
            <i data-lucide="arrow-right-left" class="w-5 h-5 text-emerald-400"></i> Group Debts
          </h3>
          <span id="badge-simplify-mode" class="text-[11px] px-2 py-0.5 rounded font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/80">Simplify Debts: ON</span>
        </div>

        <!-- Debts Mode Toggle Tabs -->
        <div class="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 mb-3 text-xs">
          <button id="tab-debts-simplified" onclick="setDebtsTab('simplified')" class="flex-1 py-1 px-2.5 rounded-lg bg-emerald-600/30 text-emerald-300 font-semibold transition flex items-center justify-center gap-1">
            <i data-lucide="shuffle" class="w-3.5 h-3.5"></i> Simplified Debts
            <span id="count-simplified-debts" class="ml-1 text-[10px] bg-emerald-900/60 px-1.5 py-0.2 rounded">0</span>
          </button>
          <button id="tab-debts-original" onclick="setDebtsTab('original')" class="flex-1 py-1 px-2.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center justify-center gap-1">
            <i data-lucide="list" class="w-3.5 h-3.5"></i> Direct Debts (Unsimplified)
            <span id="count-original-debts" class="ml-1 text-[10px] bg-slate-800 px-1.5 py-0.2 rounded text-slate-400">0</span>
          </button>
        </div>

        <div id="simplified-debts-list" class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          <p class="text-xs text-slate-500">Connect Splitwise in Step 1 to load active debts.</p>
        </div>

        <!-- Member Phone Directory -->
        <div class="mt-6 pt-4 border-t border-slate-800">
          <div class="flex items-center justify-between mb-3">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <i data-lucide="contact" class="w-4 h-4 text-blue-400"></i> Participant Phone Numbers
            </h4>
            <span class="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-emerald-400">Auto-Resolved from Mac Contacts</span>
          </div>
          <div id="members-phone-list" class="space-y-2">
            <!-- Populated by JS -->
          </div>
        </div>
      </div>

      <!-- RIGHT: Test Real iMessage & macOS Permissions -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold flex items-center gap-2">
            <i data-lucide="smartphone" class="w-5 h-5 text-blue-400"></i> macOS & iMessage Status
          </h3>
          <span class="text-xs text-slate-400">Self-Hosted Mac</span>
        </div>

        <div class="grid grid-cols-2 gap-3 text-xs">
          <div class="p-3 bg-slate-950 border border-slate-800 rounded-xl">
            <span class="text-slate-400">Outbound AppleScript</span>
            <div id="status-applescript" class="font-semibold text-emerald-400 mt-1 flex items-center gap-1">
              <i data-lucide="check-circle" class="w-4 h-4"></i> Ready
            </div>
          </div>
          <div class="p-3 bg-slate-950 border border-slate-800 rounded-xl">
            <span class="text-slate-400">Full Disk Access (chat.db)</span>
            <div id="status-fda" class="font-semibold text-amber-400 mt-1 flex items-center gap-1">
              <i data-lucide="alert-circle" class="w-4 h-4"></i> Inbound Listener
            </div>
          </div>
        </div>

        <!-- 1-Click FDA Helper -->
        <div class="p-3 bg-purple-950/30 border border-purple-800/50 rounded-xl text-xs space-y-2">
          <div class="flex items-center justify-between">
            <span class="font-medium text-purple-300 flex items-center gap-1">
              <i data-lucide="shield" class="w-3.5 h-3.5 text-purple-400"></i> Easy Full Disk Access Setup
            </span>
            <button onclick="openFullDiskAccessHelper()" class="py-1 px-2.5 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-lg transition text-[11px] flex items-center gap-1 shadow">
              <i data-lucide="external-link" class="w-3.5 h-3.5"></i> Open Settings & Reveal App
            </button>
          </div>
          <p class="text-[11px] text-slate-400 leading-tight">
            Click above to open <strong>System Settings</strong> and reveal <strong>Antigravity</strong> in Finder. Then just <strong>drag and drop</strong> the highlighted Antigravity app icon into the Settings list!
          </p>
          <p id="fda-helper-feedback" class="text-[11px] text-emerald-400 hidden font-medium"></p>
        </div>

        <div class="pt-2 border-t border-slate-800">
          <p class="text-xs text-slate-300 font-medium mb-2">Send a Real Test iMessage to Your Phone:</p>
          <div class="flex gap-2">
            <input type="text" id="test-imessage-recipient" placeholder="Your Phone Number or Apple ID" class="flex-1 text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500">
            <button onclick="sendTestIMessage()" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition flex items-center gap-1.5 shadow-md">
              <i data-lucide="send" class="w-3.5 h-3.5"></i> Send
            </button>
          </div>
          <p id="imessage-test-result" class="text-[11px] text-slate-400 mt-2"></p>
        </div>
      </div>

    </div>

    <!-- Live AI Debt Explainer Sandbox -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h3 class="text-lg font-semibold flex items-center gap-2">
            <i data-lucide="bot" class="w-5 h-5 text-purple-400"></i> Live AI Debt Explainer Sandbox
          </h3>
          <p class="text-xs text-slate-400">Test how the bot explains tricky simplified debts to your real group members.</p>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div>
          <label class="block text-xs text-slate-400 mb-1">Debtor Asking Question:</label>
          <select id="chat-debtor-select" class="w-full text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-purple-500">
            <option value="">No debtors found (Select a group first)</option>
          </select>
        </div>
        <div class="md:col-span-2">
          <label class="block text-xs text-slate-400 mb-1">Their Confused Question:</label>
          <div class="flex gap-2">
            <input type="text" id="chat-question-input" value="Why do I owe this amount and why am I paying this specific person?" class="flex-1 text-xs bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-purple-500">
            <button onclick="askAI()" id="btn-ask-ai" class="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold rounded-lg transition flex items-center gap-1.5 shadow-md">
              <i data-lucide="sparkles" class="w-3.5 h-3.5"></i> Ask AI
            </button>
          </div>
        </div>
      </div>

      <!-- iMessage Bubble Output -->
      <div class="p-4 bg-slate-950 rounded-xl border border-slate-800">
        <p class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Simulated iMessage Reply:</p>
        <div id="ai-response-bubble" class="bg-blue-600 text-white text-xs p-4 rounded-2xl max-w-xl whitespace-pre-line leading-relaxed shadow-lg">
          Connect your Splitwise group and AI key, then click "Ask AI" to generate a live explanation.
        </div>
      </div>
    </div>

  </main>

  <script>
    let currentProvider = 'gemini';
    let activeGroupId = 0;
    let cachedGroupData = null;
    let currentDebtsTab = 'simplified';

    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        if (data.splitwise && data.splitwise.group_id) {
          activeGroupId = parseInt(data.splitwise.group_id);
        }

        // Splitwise status
        const swBadge = document.getElementById('badge-splitwise');
        const swIndicator = document.getElementById('sw-status-indicator');
        if (data.splitwise.connected) {
          swBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400"></span> Splitwise: ' + (data.splitwise.user.name || 'Connected');
          swBadge.className = 'px-2.5 py-1 rounded-full bg-emerald-950/60 text-emerald-300 flex items-center gap-1.5 border border-emerald-800/60';
          swIndicator.innerText = 'Connected as ' + data.splitwise.user.name;
          swIndicator.className = 'text-emerald-400 text-xs font-medium';
          
          document.getElementById('sw-profile-card').classList.remove('hidden');
          document.getElementById('sw-name').innerText = data.splitwise.user.name;
          document.getElementById('sw-email').innerText = data.splitwise.user.email;
        } else {
          swBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-slate-500"></span> Splitwise: Not Connected';
          swBadge.className = 'px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 flex items-center gap-1.5 border border-slate-700';
          swIndicator.innerText = 'Not Connected';
          swIndicator.className = 'text-slate-400 text-xs font-medium';
          document.getElementById('sw-profile-card').classList.add('hidden');
        }

        // AI status
        const aiBadge = document.getElementById('badge-ai');
        const aiIndicator = document.getElementById('ai-status-indicator');
        if (data.ai.connected) {
          aiBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400"></span> AI: ' + data.ai.provider.toUpperCase();
          aiBadge.className = 'px-2.5 py-1 rounded-full bg-purple-950/60 text-purple-300 flex items-center gap-1.5 border border-purple-800/60';
          aiIndicator.innerText = 'Connected (' + data.ai.provider + ')';
          aiIndicator.className = 'text-purple-400 text-xs font-medium';
        } else {
          aiBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-slate-500"></span> AI: Not Connected';
          aiBadge.className = 'px-2.5 py-1 rounded-full bg-slate-800 text-slate-400 flex items-center gap-1.5 border border-slate-700';
          aiIndicator.innerText = 'Not Connected';
          aiIndicator.className = 'text-slate-400 text-xs font-medium';
        }

        // Permissions
        document.getElementById('status-applescript').innerHTML = data.permissions.applescript 
            ? '<i data-lucide="check-circle" class="w-4 h-4 text-emerald-400 inline"></i> Ready'
            : '<i data-lucide="x-circle" class="w-4 h-4 text-red-400 inline"></i> Error';

        document.getElementById('status-fda').innerHTML = data.permissions.full_disk_access
            ? '<i data-lucide="check-circle" class="w-4 h-4 text-emerald-400 inline"></i> Ready'
            : '<i data-lucide="alert-triangle" class="w-4 h-4 text-amber-400 inline"></i> FDA Required (System Settings)';

        lucide.createIcons();
      } catch (e) {
        console.error('Error loading status:', e);
      }
    }

    async function loadGroups() {
      try {
        const res = await fetch('/api/groups');
        const data = await res.json();
        const select = document.getElementById('select-group');
        select.innerHTML = '';
        
        if (!data.groups || data.groups.length === 0) {
          const opt = document.createElement('option');
          opt.value = '';
          opt.innerText = 'No groups found (Connect Splitwise first)';
          select.appendChild(opt);
          document.getElementById('group-count').innerText = '0 Groups';
          return;
        }

        // Determine saved active group ID (from server config or localStorage)
        let savedGid = activeGroupId;
        if (!savedGid || savedGid === 0) {
          const localSaved = localStorage.getItem('selected_splitwise_group_id');
          if (localSaved) savedGid = parseInt(localSaved);
        }

        let hasMatch = false;
        data.groups.forEach(g => {
          const opt = document.createElement('option');
          opt.value = g.id;
          opt.innerText = g.name;
          if (savedGid && g.id === savedGid) {
            opt.selected = true;
            hasMatch = true;
          }
          select.appendChild(opt);
        });

        if (hasMatch) {
          select.value = savedGid;
        } else if (data.groups.length > 0 && !savedGid) {
          select.value = data.groups[0].id;
        }

        document.getElementById('group-count').innerText = data.groups.length + ' Groups';
        await loadGroupDetails(select.value);
      } catch (e) {
        console.error('Error loading groups:', e);
      }
    }

    function setDebtsTab(tab) {
      currentDebtsTab = tab;
      const btnSimplified = document.getElementById('tab-debts-simplified');
      const btnOriginal = document.getElementById('tab-debts-original');

      if (tab === 'simplified') {
        btnSimplified.className = 'flex-1 py-1 px-2.5 rounded-lg bg-emerald-600/30 text-emerald-300 font-semibold transition flex items-center justify-center gap-1';
        btnOriginal.className = 'flex-1 py-1 px-2.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center justify-center gap-1';
      } else {
        btnOriginal.className = 'flex-1 py-1 px-2.5 rounded-lg bg-emerald-600/30 text-emerald-300 font-semibold transition flex items-center justify-center gap-1';
        btnSimplified.className = 'flex-1 py-1 px-2.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center justify-center gap-1';
      }
      renderDebtsList();
    }

    function renderDebtsList() {
      if (!cachedGroupData) return;
      const simplified = cachedGroupData.simplified_debts || [];
      const original = cachedGroupData.original_debts || [];
      const debts = currentDebtsTab === 'simplified' ? simplified : original;

      const debtsList = document.getElementById('simplified-debts-list');
      debtsList.innerHTML = '';

      if (debts.length === 0) {
        const msg = currentDebtsTab === 'simplified' 
          ? 'No simplified debts in this group! All balances settled or simplify debts is off.' 
          : 'No direct debts in this group! All balances settled.';
        debtsList.innerHTML = `<p class="text-xs text-slate-500">${msg}</p>`;
      } else {
        debts.forEach(d => {
          const div = document.createElement('div');
          div.className = 'p-3 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between text-xs';
          div.innerHTML = `
            <div class="flex items-center gap-2">
              <span class="font-semibold text-slate-200">${d.from_name}</span>
              <i data-lucide="arrow-right" class="w-3.5 h-3.5 text-slate-500"></i>
              <span class="font-semibold text-emerald-400">${d.to_name}</span>
            </div>
            <span class="font-mono font-bold text-amber-400">$${d.amount.toFixed(2)}</span>
          `;
          debtsList.appendChild(div);
        });
      }

      // Update AI Explainer Debtor dropdown to match currently viewed debts
      const debtorSelect = document.getElementById('chat-debtor-select');
      debtorSelect.innerHTML = '';
      if (debts.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.innerText = 'No debtors with open balances in this mode';
        debtorSelect.appendChild(opt);
      } else {
        debts.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d.from_name;
          const modeTag = currentDebtsTab === 'simplified' ? 'simplified' : 'direct';
          opt.innerText = `${d.from_name} (Owes $${d.amount.toFixed(2)} to ${d.to_name} [${modeTag}])`;
          debtorSelect.appendChild(opt);
        });
      }

      lucide.createIcons();
    }

    async function loadGroupDetails(groupId) {
      try {
        const gid = groupId || document.getElementById('select-group').value;
        const url = gid ? `/api/group/details?group_id=${gid}` : '/api/group/details';
        const res = await fetch(url);
        const data = await res.json();
        cachedGroupData = data;

        document.getElementById('summary-group-name').innerText = data.group_name || 'None selected';
        const simplified = data.simplified_debts || [];
        const original = data.original_debts || [];
        const activeDebts = data.active_debts || [];

        document.getElementById('summary-debtors-count').innerText = activeDebts.length + ' open debts';
        document.getElementById('count-simplified-debts').innerText = simplified.length;
        document.getElementById('count-original-debts').innerText = original.length;

        const badge = document.getElementById('badge-simplify-mode');
        if (data.simplify_by_default) {
          badge.innerText = 'Simplify Debts: ON';
          badge.className = 'text-[11px] px-2 py-0.5 rounded font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800/80';
        } else {
          badge.innerText = 'Simplify Debts: OFF (Direct Debts)';
          badge.className = 'text-[11px] px-2 py-0.5 rounded font-medium bg-amber-950/80 text-amber-300 border border-amber-800/80';
        }

        // Set active debts tab based on simplify_debts_enabled
        if (!data.simplify_debts_enabled && original.length > 0) {
          setDebtsTab('original');
        } else {
          setDebtsTab('simplified');
        }

        // Render Member Phone Directory
        const phoneList = document.getElementById('members-phone-list');
        if (phoneList && data.members) {
          phoneList.innerHTML = '';
          Object.values(data.members).forEach(m => {
            const div = document.createElement('div');
            div.className = 'p-2.5 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between text-xs';
            const phoneDisplay = m.phone ? m.phone : '<span class="text-amber-400 font-medium">Missing</span>';
            const sourceBadge = m.phone_source && m.phone_source.includes('Mac Contacts')
              ? '<span class="text-[10px] bg-emerald-950/60 text-emerald-400 px-1.5 py-0.5 rounded border border-emerald-800/60">Mac Contacts</span>'
              : m.phone ? '<span class="text-[10px] bg-slate-800 text-slate-300 px-1.5 py-0.5 rounded">Saved</span>' : '';

            div.innerHTML = `
              <div class="overflow-hidden">
                <p class="font-medium text-slate-200 truncate">${m.name}</p>
                <p class="text-[10px] text-slate-500 truncate">${m.email}</p>
              </div>
              <div class="flex items-center gap-2">
                <span class="font-mono text-slate-300 text-[11px]">${phoneDisplay}</span>
                ${sourceBadge}
                <button onclick="editMemberPhone(${m.id}, '${m.name}', '${m.phone || ''}')" class="p-1 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition" title="Edit phone number">
                  <i data-lucide="edit-2" class="w-3.5 h-3.5"></i>
                </button>
              </div>
            `;
            phoneList.appendChild(div);
          });
        }

        lucide.createIcons();
      } catch (e) {
        console.error('Error loading group details:', e);
      }
    }

    async function editMemberPhone(id, name, currentPhone) {
      const newPhone = prompt('Enter phone number for ' + name + ':', currentPhone);
      if (newPhone !== null && newPhone.trim() !== '') {
        const res = await fetch('/api/members/phone', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({member_id: id, phone: newPhone})
        });
        const data = await res.json();
        if (data.success) {
          loadGroupDetails();
        }
      }
    }

    async function onGroupChanged() {
      const gid = document.getElementById('select-group').value;
      if (!gid) return;
      activeGroupId = parseInt(gid);
      localStorage.setItem('selected_splitwise_group_id', gid);
      await fetch('/api/config/group', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group_id: parseInt(gid)})
      });
      await loadGroupDetails(gid);
    }

    function setProvider(p) {
      currentProvider = p;
      if (p === 'gemini') {
        document.getElementById('btn-provider-gemini').className = 'py-2 px-2.5 rounded-lg border border-purple-500 bg-purple-950/40 text-purple-300 font-medium flex items-center justify-center gap-1.5';
        document.getElementById('btn-provider-openai').className = 'py-2 px-2.5 rounded-lg border border-slate-800 bg-slate-950 text-slate-400 font-medium flex items-center justify-center gap-1.5';
        document.getElementById('connector-gemini-box').classList.remove('hidden');
        document.getElementById('connector-openai-box').classList.add('hidden');
      } else {
        document.getElementById('btn-provider-openai').className = 'py-2 px-2.5 rounded-lg border border-purple-500 bg-purple-950/40 text-purple-300 font-medium flex items-center justify-center gap-1.5';
        document.getElementById('btn-provider-gemini').className = 'py-2 px-2.5 rounded-lg border border-slate-800 bg-slate-950 text-slate-400 font-medium flex items-center justify-center gap-1.5';
        document.getElementById('connector-openai-box').classList.remove('hidden');
        document.getElementById('connector-gemini-box').classList.add('hidden');
      }
    }

    async function saveAndTestAI(provider) {
      const inputId = provider === 'gemini' ? 'input-gemini-key' : 'input-openai-key';
      const key = document.getElementById(inputId).value.trim();
      const el = document.getElementById('ai-test-result');

      if (!key) return alert('Please enter your ' + provider.toUpperCase() + ' API key.');

      el.innerText = 'Connecting and verifying key with ' + provider.toUpperCase() + '...';
      el.className = 'text-[11px] text-center text-slate-400 mt-2';

      // 1. Save
      const resSave = await fetch('/api/config/ai', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({provider: provider, api_key: key})
      });
      const dataSave = await resSave.json();

      // 2. Test
      const resTest = await fetch('/api/test/ai', {method: 'POST'});
      const dataTest = await resTest.json();

      if (dataTest.success) {
        el.className = 'text-[11px] text-center text-emerald-400 mt-2 font-medium';
        el.innerText = '✓ Success: Connected to ' + provider.toUpperCase() + ' (' + dataTest.reply + ')';
        loadStatus();
      } else {
        el.className = 'text-[11px] text-center text-red-400 mt-2';
        el.innerText = '✗ Error: ' + (dataTest.error || 'Connection failed');
      }
    }

    async function saveSplitwiseApiKey() {
      const key = document.getElementById('input-sw-api-key').value.trim();
      if (!key) return alert('Please enter your Splitwise API Key');
      const res = await fetch('/api/config/splitwise', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({api_key: key})
      });
      const data = await res.json();
      if (data.success && data.profile && data.profile.connected) {
        alert('Splitwise Connected! Welcome ' + data.profile.name);
        loadStatus();
        loadGroups();
      } else {
        alert('Could not verify API Key. Please ensure it is active on secure.splitwise.com/apps.');
      }
    }

    async function saveSplitwiseOAuthCreds() {
      const cKey = document.getElementById('input-sw-consumer-key').value.trim();
      const cSec = document.getElementById('input-sw-consumer-secret').value.trim();
      if (!cKey || !cSec) return alert('Enter both Consumer Key and Consumer Secret');
      const res = await fetch('/api/config/splitwise', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({consumer_key: cKey, consumer_secret: cSec})
      });
      const data = await res.json();
      if (data.success) {
        alert('Consumer Keys saved! You can now click Launch OAuth Login.');
        loadStatus();
      }
    }

    async function sendTestIMessage() {
      const recipient = document.getElementById('test-imessage-recipient').value.trim();
      if (!recipient) return alert('Enter a phone number or Apple ID email');
      const resultEl = document.getElementById('imessage-test-result');
      resultEl.innerText = 'Sending iMessage via AppleScript...';
      const res = await fetch('/api/test/imessage', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({recipient: recipient})
      });
      const data = await res.json();
      if (data.success) {
        resultEl.className = 'text-[11px] text-emerald-400 mt-2';
        resultEl.innerText = '✓ iMessage sent! Check your Messages app.';
      } else {
        resultEl.className = 'text-[11px] text-red-400 mt-2';
        resultEl.innerText = '✗ Failed to send. Make sure Messages.app is open.';
      }
    }

    async function askAI() {
      const debtor = document.getElementById('chat-debtor-select').value;
      if (!debtor) return alert('Please select a debtor from the dropdown first.');
      const question = document.getElementById('chat-question-input').value;
      const bubble = document.getElementById('ai-response-bubble');
      bubble.innerText = 'Querying AI and calculating Simplified Debts graph...';
      
      const res = await fetch('/api/ai/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_name_or_phone: debtor, question: question})
      });
      const data = await res.json();
      if (data.success) {
        bubble.innerText = data.explanation;
      } else {
        bubble.innerText = 'Error: ' + (data.error || 'Failed to explain');
      }
    }

    async function triggerRemind(live) {
      if (live && !confirm('Are you sure you want to dispatch real iMessages to everyone who owes money?')) return;
      const res = await fetch('/api/bot/remind', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({live: live})
      });
      const data = await res.json();
      if (data.success) {
        alert('Reminders dispatched: ' + data.mode);
      } else {
        alert('Error: ' + data.error);
      }
    }

    async function openFullDiskAccessHelper() {
      const fb = document.getElementById('fda-helper-feedback');
      fb.classList.remove('hidden');
      fb.innerText = 'Opened System Settings & Finder! Drag the highlighted Antigravity icon into the Full Disk Access list.';
      await fetch('/api/open/full-disk-access', {method: 'POST'});
      setTimeout(() => { loadStatus(); }, 4000);
    }

    // Sequential initialization
    async function init() {
      await loadStatus();
      await loadGroups();
    }
    init();
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("  🚀 Splitwise iMessage Bot Web Dashboard starting...")
    print("  👉 Open in your browser: http://localhost:8000 or http://127.0.0.1:8000")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
