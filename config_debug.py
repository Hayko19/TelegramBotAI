import os
import sys
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MARZBAN_URL = os.getenv("MARZBAN_URL", "https://45.93.9.197:8000")
MARZBAN_USERNAME = os.getenv("MARZBAN_USERNAME")
MARZBAN_PASSWORD = os.getenv("MARZBAN_PASSWORD")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "421240854"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
DEPLOY_ADMIN_USER = os.getenv("DEPLOY_ADMIN_USER", "")
DEPLOY_ADMIN_PASS = os.getenv("DEPLOY_ADMIN_PASS", "")
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db"))

# Validate required vars at startup
_required = {
    "BOT_TOKEN": BOT_TOKEN,
    "MARZBAN_USERNAME": MARZBAN_USERNAME,
    "MARZBAN_PASSWORD": MARZBAN_PASSWORD,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    print(f"FATAL: Missing required env vars: {', '.join(_missing)}")
    print("Copy .env.example to .env and fill in all values.")
    sys.exit(1)