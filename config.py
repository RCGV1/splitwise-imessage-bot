import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

def reload_env():
    global SPLITWISE_CONSUMER_KEY, SPLITWISE_CONSUMER_SECRET, SPLITWISE_API_KEY
    global SPLITWISE_ACCESS_TOKEN, SPLITWISE_GROUP_ID, AI_PROVIDER, OPENAI_API_KEY
    global GEMINI_API_KEY, REMINDER_INTERVAL_DAYS, AUTO_REMIND_ENABLED, DRY_RUN
    
    load_dotenv(ENV_PATH, override=True)
    SPLITWISE_CONSUMER_KEY = os.getenv("SPLITWISE_CONSUMER_KEY", "").strip()
    SPLITWISE_CONSUMER_SECRET = os.getenv("SPLITWISE_CONSUMER_SECRET", "").strip()
    SPLITWISE_API_KEY = os.getenv("SPLITWISE_API_KEY", "").strip()
    SPLITWISE_ACCESS_TOKEN = os.getenv("SPLITWISE_ACCESS_TOKEN", "").strip()

    try:
        SPLITWISE_GROUP_ID = int(os.getenv("SPLITWISE_GROUP_ID", "0"))
    except ValueError:
        SPLITWISE_GROUP_ID = 0

    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

    REMINDER_INTERVAL_DAYS = int(os.getenv("REMINDER_INTERVAL_DAYS", "7"))
    AUTO_REMIND_ENABLED = os.getenv("AUTO_REMIND_ENABLED", "false").strip().lower() == "true"
    DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

reload_env()

def has_splitwise_creds() -> bool:
    has_oauth_token = bool(SPLITWISE_ACCESS_TOKEN and SPLITWISE_ACCESS_TOKEN != "your_access_token_here")
    has_api_key = bool(SPLITWISE_API_KEY and SPLITWISE_API_KEY != "your_api_key_here")
    return has_oauth_token or has_api_key

def has_ai_creds() -> bool:
    if AI_PROVIDER == "openai":
        return bool(OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here")
    elif AI_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here")
    return False

def save_env_updates(updates: dict):
    """Safely updates or adds keys in .env file and reloads config."""
    lines = []
    if ENV_PATH.exists():
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()

    keys_to_update = set(updates.keys())
    new_lines = []
    seen_keys = set()

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in keys_to_update:
                val = str(updates[key])
                new_lines.append(f"{key}={val}\n")
                seen_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in seen_keys:
            new_lines.append(f"{key}={val}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(new_lines)

    reload_env()
