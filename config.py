import os
from dotenv import load_dotenv

load_dotenv()

# === Telegram ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]


# === ИИ Провайдер (настраивается через .env — без изменений кода) ===
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

# === Лимиты ===
DAILY_USER_LIMIT = int(os.getenv("DAILY_LIMIT", "15"))

# === Темы для опросов ===
POLL_TOPICS = ["история", "кулинария", "игры", "кино"]

# === Расписание опросов (UTC) ===
POLL_HOURS = os.getenv("POLL_HOURS", "07:00, 17:00")
POLL_SCHEDULE = []
try:
    for h_m in POLL_HOURS.split(","):
        if ":" in h_m:
            h, m = h_m.strip().split(":")
            POLL_SCHEDULE.append({"hour": int(h), "minute": int(m)})
except Exception:
    # Фолбек на случай ошибки парсинга
    POLL_SCHEDULE = [{"hour": 7, "minute": 0}, {"hour": 17, "minute": 0}]

# === Системный промпт для чата ===
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT")

# === Системный промпт для генерации опросов ===
POLL_SYSTEM_PROMPT = os.getenv("POLL_SYSTEM_PROMPT")
