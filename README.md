# 🍎 Self-Hosted Splitwise iMessage Bot

An automated macOS bot that keeps your group paying their Splitwise debts, sends automated reminders via **iMessage**, and **always uses AI to clearly explain complex "Simplified Debts"** while using minimal token credits.

---

## 🌐 Easy Web Onboarding (Recommended)

The easiest way to onboard and connect accounts is through the local web dashboard:

1. **Start the Web Dashboard**:
   ```bash
   source .venv/bin/activate
   python web.py
   ```

2. **Open Your Browser**:
   Navigate to **[http://localhost:8000](http://localhost:8000)**.

3. **In the Web UI, you can**:
   - **1-Click Login with Splitwise** (or paste your Splitwise API Key).
   - **Select your group** from an automatic dropdown list.
   - **Configure your AI key** (OpenAI `gpt-4o-mini` or Google Gemini `gemini-2.5-flash`) and click **Test** to verify immediately.
   - **Verify macOS permissions** with live status badges.
   - **Send a real test iMessage** to your phone with one click.
   - **Interact with the AI Debt Explainer Sandbox** to see how it explains confusing simplified debt paths.
   - **Preview or dispatch automated group reminders**.

---

## 💻 Terminal CLI Mode

If you prefer using the terminal:

```bash
# Run interactive CLI menu
python test_demo.py

# Send automated reminders (Dry run preview)
python bot.py --remind

# Send live iMessages to debtors
python bot.py --remind --live

# Run background listener for incoming iMessages
python bot.py --listen --live
```

---

## 🔑 Splitwise & AI Credentials

You can set these in the Web UI or directly in [.env](file:///.env):

### 1. Splitwise API Keys
1. Go to **[Splitwise Applications](https://secure.splitwise.com/apps)** and click **"Register your application"**.
2. Set the redirect URL to `http://localhost:8000/oauth/callback`.
3. Copy:
   - `SPLITWISE_CONSUMER_KEY`
   - `SPLITWISE_CONSUMER_SECRET`
   - `SPLITWISE_API_KEY` (Your personal API key from the app page)

### 2. AI Model (Minimal Credits)
* **OpenAI (Codex / ChatGPT Plus)**:
  ```env
  AI_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  ```
  Uses `gpt-4o-mini`. The prompt is compact (<250 tokens), costing less than **$0.00005 per query**.
* **Google Gemini (Antigravity)**:
  ```env
  AI_PROVIDER=gemini
  GEMINI_API_KEY=AIzaSy...
  ```
  Uses `gemini-3.6-flash` (free tier eligible, essentially $0.00).

---

## 🔒 macOS Permissions

### 1. Sending iMessages (Outbound)
* Outbound iMessages use macOS AppleScript.
* Your Mac is already authorized for AppleScript control of `Messages.app`!
* Messages are sent as **blue bubbles** to iPhone users and **green bubbles** to Android users (if you have "Text Message Forwarding" enabled on your iPhone).

### 2. Reading Inbound Messages (Inbound)
To let the bot automatically read incoming texts from your friends:
1. Open **System Settings** on your Mac.
2. Go to **Privacy & Security** -> **Full Disk Access**.
3. Click the `+` button and add your **Terminal** app (or iTerm2 / VS Code / Cursor).
4. Toggle it **ON**.

---

## 🌙 Keeping your Mac awake 24/7:
To run the bot continuously without your Mac sleeping when idle:
```bash
caffeinate -d -i -m -u python bot.py --listen --live
```
