from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import database
import ai

# === Логирование ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# === Инициализация ===
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Хранилище истории диалогов (в памяти, сбрасывается при перезапуске)
# {user_id: [{"role": "user"/"model", "text": "..."}]}
chat_histories: dict[int, list[dict]] = defaultdict(list)

# Имя бота (заполняется при запуске)
BOT_USERNAME: str = ""


# ========== ОБРАБОТЧИКИ КОМАНД ==========


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие при первом запуске."""
    await message.answer(
        "👋 <b>Привет!</b> Я — бот для дискуссий.\n\n"
        "🧠 <b>Что я умею:</b>\n"
        "• Автоматически создаю опросы-дискуссии 2 раза в день\n"
        "   (10:00 и 20:00 по МСК)\n"
        "• Общаюсь с тобой на любые темы (через ИИ)\n\n"
        "📋 <b>Команды:</b>\n"
        "/start — это сообщение\n"
        "/help — подробная помощь\n"
        "/limit — проверить оставшийся лимит\n\n"
        "💬 В ЛС — просто напиши мне.\n"
        f"💬 В группе — упомяни @{BOT_USERNAME} или ответь на моё сообщение.",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Подробная помощь."""
    topics_text = ", ".join(f"«{t}»" for t in config.POLL_TOPICS)
    await message.answer(
        "📖 <b>Справка по боту</b>\n\n"
        "<b>🗳 Опросы-дискуссии</b>\n"
        f"Каждый день в 10:00 и 20:00 (МСК) я публикую опросы "
        f"на темы: {topics_text}.\n"
        "Голосуй и спорь в комментариях!\n\n"
        "<b>💬 Чат с ИИ</b>\n"
        "• <b>В ЛС:</b> просто напиши любое сообщение — я отвечу.\n"
        f"• <b>В группе:</b> упомяни @{BOT_USERNAME} или ответь "
        f"(reply) на моё сообщение.\n"
        f"• Дневной лимит: <b>{config.DAILY_USER_LIMIT} сообщений</b> "
        f"на пользователя.\n\n"
        "<b>📋 Команды:</b>\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/limit — проверить оставшийся лимит сообщений",
        parse_mode="HTML",
    )


@dp.message(Command("limit"))
async def cmd_limit(message: Message):
    """Показывает оставшийся лимит запросов."""
    used = await database.get_user_requests_today(message.from_user.id)
    remaining = max(0, config.DAILY_USER_LIMIT - used)
    total = config.DAILY_USER_LIMIT

    if remaining > 0:
        if remaining > total * 0.5:
            emoji = "🟢"
        elif remaining > total * 0.2:
            emoji = "🟡"
        else:
            emoji = "🔴"
        await message.answer(
            f"{emoji} <b>Ваш лимит на сегодня:</b>\n"
            f"Использовано: {used}/{total}\n"
            f"Осталось: <b>{remaining}</b> сообщений",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🔴 <b>Лимит исчерпан!</b>\n"
            f"Использовано: {used}/{total}\n"
            "Лимит обновится завтра в 00:00 UTC (03:00 МСК).",
            parse_mode="HTML",
        )


# ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (ЧАТ) ==========


def _is_bot_mentioned(message: Message) -> bool:
    """Проверяет, упомянут ли бот в сообщении (через @username)."""
    if not message.entities:
        return False
    for entity in message.entities:
        if entity.type == "mention":
            mention_text = message.text[
                entity.offset : entity.offset + entity.length
            ]
            if mention_text.lower() == f"@{BOT_USERNAME.lower()}":
                return True
    return False


def _is_reply_to_bot(message: Message) -> bool:
    """Проверяет, является ли сообщение ответом на сообщение бота."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id == bot.id
    return False


@dp.message(F.text)
async def handle_chat_message(message: Message):
    """Обработка текстовых сообщений — чат с ИИ."""
    user_id = message.from_user.id
    user_text = message.text

    # В групповых чатах отвечаем только если бот упомянут или ему reply
    is_private = message.chat.type == ChatType.PRIVATE
    if not is_private:
        if not _is_bot_mentioned(message) and not _is_reply_to_bot(message):
            return  # Игнорируем сообщения, не адресованные боту

    # Проверяем лимит
    used = await database.get_user_requests_today(user_id)
    if used >= config.DAILY_USER_LIMIT:
        await message.answer(
            "🔴 <b>Дневной лимит исчерпан!</b>\n"
            f"Вы использовали все {config.DAILY_USER_LIMIT} "
            f"сообщений на сегодня.\n"
            "Лимит обновится завтра в 00:00 UTC (03:00 МСК).\n\n"
            "А пока — ждите опрос! 🧠",
            parse_mode="HTML",
        )
        return

    # Убираем @username из текста, если он есть
    clean_text = user_text.replace(f"@{BOT_USERNAME}", "").strip()
    if not clean_text:
        clean_text = "Привет!"

    # Отправляем индикатор набора текста
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Получаем историю диалога
    history = chat_histories[user_id]

    # Генерируем ответ
    response_text = await ai.chat_response(clean_text, history)

    # Сохраняем в историю (ограничиваем 20 записей — 10 пар)
    chat_histories[user_id].append({"role": "user", "text": clean_text})
    chat_histories[user_id].append({"role": "model", "text": response_text})
    if len(chat_histories[user_id]) > 20:
        chat_histories[user_id] = chat_histories[user_id][-20:]

    # Записываем использование в БД
    await database.add_user_request(user_id)

    # Показываем оставшийся лимит, когда он заканчивается
    new_used = used + 1
    remaining = config.DAILY_USER_LIMIT - new_used
    footer = ""
    if remaining <= 5:
        footer = (
            f"\n\n⚠️ <i>Осталось сообщений: "
            f"{remaining}/{config.DAILY_USER_LIMIT}</i>"
        )

    # Экранируем HTML-символы в ответе ИИ, чтобы Telegram не крашился
    safe_response = html.escape(response_text)
    await message.answer(safe_response + footer, parse_mode="HTML")


# ========== ФУНКЦИЯ ОТПРАВКИ ОПРОСА ==========


async def send_scheduled_poll():
    """Генерирует и отправляет опрос в чат."""
    topic = ai.get_random_topic()
    recent_questions = await database.get_recent_polls(20)

    logger.info("Генерация опроса на тему: %s", topic)

    poll_data = await ai.generate_poll(topic, recent_questions)

    if poll_data is None:
        logger.error("Не удалось сгенерировать опрос. Пропускаем.")
        return

    try:
        await bot.send_poll(
            chat_id=config.CHAT_ID,
            question=poll_data["question"],
            options=[
                {"text": option} for option in poll_data["options"]
            ],
            type="regular",
            is_anonymous=False,
        )

        # Сохраняем в историю
        await database.add_poll(poll_data["question"], topic)
        logger.info("Опрос успешно отправлен: %s", poll_data["question"])

    except Exception as e:
        logger.error("Ошибка при отправке опроса: %s", e)


# ========== ЗАПУСК ==========


async def main():
    """Точка входа."""
    global BOT_USERNAME

    # Инициализация базы данных
    await database.init_db()
    logger.info("База данных инициализирована.")

    # Получаем username бота
    bot_info = await bot.get_me()
    BOT_USERNAME = bot_info.username
    logger.info("Бот: @%s", BOT_USERNAME)

    # Настройка планировщика
    scheduler = AsyncIOScheduler(timezone="UTC")
    for schedule in config.POLL_SCHEDULE:
        scheduler.add_job(
            send_scheduled_poll,
            CronTrigger(
                hour=schedule["hour"],
                minute=schedule["minute"],
                timezone="UTC",
            ),
            id=f"poll_{schedule['hour']}_{schedule['minute']}",
            replace_existing=True,
        )
        logger.info(
            "Опрос запланирован на %02d:%02d UTC",
            schedule["hour"],
            schedule["minute"],
        )

    scheduler.start()

    # Запуск бота
    logger.info("🤖 Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await ai.close_client()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
