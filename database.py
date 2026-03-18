import aiosqlite
import os
from datetime import datetime, timezone

DB_PATH = os.getenv(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.db")
)

async def init_db():
    """Создание таблиц при первом запуске."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS poll_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_requests_user_id
            ON user_requests (user_id, timestamp)
        """)
        await db.commit()


async def get_user_requests_today(user_id: int) -> int:
    """Получить количество запросов пользователя за сегодня (по UTC)."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM user_requests WHERE user_id = ? AND timestamp >= ?",
            (user_id, today_start),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def add_user_request(user_id: int):
    """Записать новый запрос пользователя."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_requests (user_id, timestamp) VALUES (?, ?)",
            (user_id, now),
        )
        await db.commit()


async def add_poll(question: str, topic: str):
    """Сохранить отправленный опрос в историю."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO poll_history (question, topic, created_at) VALUES (?, ?, ?)",
            (question, topic, now),
        )
        await db.commit()


async def get_recent_polls(limit: int = 20) -> list[str]:
    """Получить последние N вопросов (для защиты от повторов)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT question FROM poll_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_stats_today() -> dict:
    """Получить статистику запросов за сегодня."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT user_id), COUNT(*) FROM user_requests WHERE timestamp >= ?",
            (today_start,),
        )
        row = await cursor.fetchone()
        return {
            "users_count": row[0] if row else 0,
            "requests_count": row[1] if row else 0
        }


async def reset_all_requests_today():
    """Сбросить лимиты (удалить запросы) всех пользователей за сегодня."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_requests WHERE timestamp >= ?",
            (today_start,),
        )
        await db.commit()


async def reset_user_requests_today(user_id: int):
    """Сбросить лимит одного конкретного пользователя за сегодня."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_requests WHERE user_id = ? AND timestamp >= ?",
            (user_id, today_start),
        )
        await db.commit()

