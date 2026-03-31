import aiosqlite
import os
from datetime import datetime, timezone

DB_PATH = os.getenv(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.db"),
)


async def init_db():
    """Создание таблиц при первом запуске."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS poll_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_approved INTEGER DEFAULT 1,
                request_sent INTEGER DEFAULT 0
            )
        """
        )
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER DEFAULT 1")
            await db.execute("ALTER TABLE users ADD COLUMN request_sent INTEGER DEFAULT 0")
        except Exception:
            pass
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_requests_user_id
            ON user_requests (user_id, timestamp)
        """
        )
        await db.commit()


async def get_user_requests_today(user_id: int) -> int:
    """Получить количество запросов пользователя за сегодня (по UTC)."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    query = (
        "SELECT COUNT(*) FROM user_requests "
        "WHERE user_id = ? AND timestamp >= ?"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, (user_id, today_start))
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
    query = (
        "INSERT INTO poll_history (question, topic, created_at) "
        "VALUES (?, ?, ?)"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, (question, topic, now))
        await db.commit()


async def get_recent_polls(limit: int = 20) -> list[str]:
    """Получить последние N вопросов (для защиты от повторов)."""
    query = (
        "SELECT question FROM poll_history " "ORDER BY created_at DESC LIMIT ?"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, (limit,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_stats_today() -> dict:
    """Получить статистику запросов за сегодня."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    query = (
        "SELECT COUNT(DISTINCT user_id), COUNT(*) "
        "FROM user_requests WHERE timestamp >= ?"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, (today_start,))
        row = await cursor.fetchone()
        return {
            "users_count": row[0] if row else 0,
            "requests_count": row[1] if row else 0,
        }

async def get_active_users_list_today(limit: int = 10) -> list[dict]:
    """Получить список самых активных пользователей за сегодня."""
    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00")
    query = """
        SELECT r.user_id, u.username, COUNT(r.id) as req_count, u.is_approved
        FROM user_requests r
        LEFT JOIN users u ON r.user_id = u.user_id
        WHERE r.timestamp >= ?
        GROUP BY r.user_id
        ORDER BY req_count DESC
        LIMIT ?
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, (today_start, limit))
        rows = await cursor.fetchall()
        
    return [
        {"user_id": row[0], "username": row[1], "count": row[2], "is_approved": row[3] if len(row) > 3 else 1}
        for row in rows
    ]


async def get_total_users_count() -> int:
    """Получить общее количество пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_users_paginated(limit: int, offset: int) -> list[dict]:
    """Получить список пользователей с пагинацией."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, username, is_approved FROM users ORDER BY user_id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [
            {"user_id": row[0], "username": row[1], "is_approved": row[2]}
            for row in rows
        ]


async def get_banned_users() -> list[dict]:
    """Получить список всех забаненных пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, username, is_approved FROM users WHERE is_approved = -1 ORDER BY user_id DESC"
        )
        rows = await cursor.fetchall()
        return [
            {"user_id": row[0], "username": row[1], "is_approved": row[2]}
            for row in rows
        ]


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


async def save_user(user_id: int, username: str | None):
    """Записать или обновить юзернейм пользователя (устарело, лучше использовать create_or_get_user)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, is_approved, request_sent) VALUES (?, ?, 0, 0)",
            (user_id, username if username else None),
        )
        await db.execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (username if username else None, user_id),
        )
        await db.commit()

async def create_or_get_user(user_id: int, username: str | None) -> tuple[int, int]:
    """Создает пользователя (pending=0) или возвращает его текущий статус (is_approved, request_sent)."""
    await save_user(user_id, username)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT is_approved, request_sent FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row if row else (0, 0)

async def update_user_approval(user_id: int, is_approved: int):
    """Обновить статус одобрения пользователя (1 = одобрен, 0 = ожидает, -1 = отклонен)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_approved = ? WHERE user_id = ?", (is_approved, user_id))
        await db.commit()

async def get_user_approval(user_id: int) -> int:
    """Получить статус одобрения: 1=Одобрен, 0=Новый, -1=Отклонен."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT is_approved FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

async def update_user_request_sent(user_id: int, request_sent: int):
    """Отметить, был ли запрос администраторам уже отправлен."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET request_sent = ? WHERE user_id = ?", (request_sent, user_id))
        await db.commit()


async def get_user_id_by_username(username: str) -> int | None:
    """Найти user_id по username (без @)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_username_by_user_id(user_id: int) -> str | None:
    """Найти username по user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT username FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_setting(key: str, default: str) -> str:
    """Получить значение настройки из БД с фолбеком."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    """Записать или обновить настройку в БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()


async def block_user_today(user_id: int, limit: int):
    """Заблокировать пользователя на сегодня (завершить лимит)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        # Вставляем искусственные запросы до лимита
        data = [(user_id, now)] * limit
        await db.executemany(
            "INSERT INTO user_requests (user_id, timestamp) VALUES (?, ?)",
            data,
        )
        await db.commit()


async def get_poll_topics() -> list[str]:
    """Получить список тем для опросов из БД."""
    topics_str = await get_setting(
        "poll_topics", "история, кулинария, игры, кино"
    )
    return [t.strip() for t in topics_str.split(",") if t.strip()]
