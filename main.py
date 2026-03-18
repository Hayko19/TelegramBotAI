from __future__ import annotations

import asyncio
import html
import logging
import re
from collections import defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BotCommand,
    BotCommandScopeChat,
)

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

# Планировщик (для доступа из админки)
scheduler: AsyncIOScheduler | None = None


async def notify_admins(text: str):
    """Отправляет уведомление всем администраторам."""
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Ошибка уведомления админа {admin_id}: {e}")


# ========== ОБРАБОТЧИКИ КОМАНД ==========


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Приветствие при первом запуске."""
    await database.save_user(message.from_user.id, message.from_user.username)
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
    await database.save_user(message.from_user.id, message.from_user.username)
    topics = await database.get_poll_topics()
    topics_text = ", ".join(f"«{t}»" for t in topics)
    await message.answer(
        "📖 <b>Справка по боту</b>\n\n"
        "<b>🗳 Опросы-дискуссии</b>\n"
        f"Каждый день в 10:00 и 20:00 (МСК) я публикую опросы "
        f"на темы: {topics_text}.\n"
        "Голосуй и спорь в чате!\n\n"
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
    await database.save_user(message.from_user.id, message.from_user.username)
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


# ========== ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ==========


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора."""
    if message.from_user.id not in config.ADMIN_IDS:
        return  # Игнорируем обычных пользователей

    # Используем maxsplit=2, чтобы аргументы с пробелами
    # (например, расписание) не ломались
    args = message.text.split(None, 2)

    if len(args) == 1:
        # Главное меню админки
        limit = await database.get_setting(
            "daily_limit", str(config.DAILY_USER_LIMIT)
        )
        schedule = await database.get_setting("poll_hours", config.POLL_HOURS)
        topics = await database.get_setting(
            "poll_topics", "история, кулинария, игры, кино"
        )

        msg_text = (
            "🛠 <b>Панель администратора</b>\n\n"
            f"📊 <b>Текущие настройки:</b>\n"
            f"• Дневной лимит ИИ: <code>{limit}</code>\n"
            f"• Расписание опросов: <code>{schedule}</code>\n"
            f"• Темы опросов: <code>{topics}</code>\n\n"
            "Управляйте настройками кнопками или "
            "командами (см. <code>/adminhelp</code>)."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Статистика", callback_data="admin_stats"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Сбросить все лимиты",
                        callback_data="admin_reset_confirm",
                    )
                ],
            ]
        )
        await message.answer(
            msg_text, reply_markup=keyboard, parse_mode="HTML"
        )
    elif len(args) == 2:
        sub_cmd = args[1].lower()
        if sub_cmd == "backup":
            from aiogram.types import FSInputFile

            try:
                db_file = FSInputFile(database.DB_PATH, filename="bot_data.db")
                await message.answer_document(
                    db_file, caption="💾 Бэкап базы данных (SQLite)"
                )
            except Exception as e:
                await message.answer(f"❌ Ошибка выгрузки бэкапа: {e}")
            return
    elif len(args) == 3:
        sub_cmd = args[1].lower()
        target_arg = args[2]

        # 1. Глобальный лимит
        if sub_cmd == "setlimit":
            try:
                val = int(target_arg)
                await database.set_setting("daily_limit", str(val))
                await message.answer(
                    f"✅ Общий лимит установлен на <b>{val}</b>",
                    parse_mode="HTML",
                )
            except ValueError:
                await message.answer("❌ Лимит должен быть числом.")
            return

        # 2. Расписание опросов
        if sub_cmd == "schedule":
            # Валидация: формат HH:MM, HH:MM
            import re

            time_pattern = re.compile(r"^(\d{2}:\d{2})(,\s*\d{2}:\d{2})*$")
            if not time_pattern.match(target_arg.strip()):
                await message.answer(
                    "❌ Неверный формат времени.\n"
                    "Пример: <code>09:00, 15:30</code>",
                    parse_mode="HTML",
                )
                return

            await database.set_setting("poll_hours", target_arg)
            await message.answer(
                f"✅ Расписание опросов обновлено на <b>{target_arg}</b>",
                parse_mode="HTML",
            )
            if scheduler:
                await setup_poll_jobs(scheduler)
            else:
                await message.answer(
                    "⚠️ Планировщик не инициализирован, изменения "
                    "вступят после рестарта."
                )
            return

        # 3. Темы опросов
        if sub_cmd == "topics":
            if not target_arg.strip():
                await message.answer("❌ Темы не могут быть пустыми.")
                return

            await database.set_setting("poll_topics", target_arg)
            await message.answer(
                f"✅ Темы опросов обновлены на: <b>{target_arg}</b>",
                parse_mode="HTML",
            )
            return

        # --- Для команд ниже нужен target_id ---
        if target_arg.startswith("@"):
            username = target_arg[1:]
            target_id = await database.get_user_id_by_username(username)
            if not target_id:
                await message.answer(
                    f"❌ Пользователь <code>@{username}</code> "
                    "не найден в базе данных.",
                    parse_mode="HTML",
                )
                return
        else:
            try:
                target_id = int(target_arg)
            except ValueError:
                await message.answer(
                    "❌ ID пользователя должен быть числом или начинаться с @."
                )
                return

        if sub_cmd == "limit":
            used = await database.get_user_requests_today(target_id)
            limit_str = await database.get_setting(
                "daily_limit", str(config.DAILY_USER_LIMIT)
            )
            current_limit = int(limit_str)
            remaining = max(0, current_limit - used)
            await message.answer(
                f"👤 <b>Пользователь</b> <code>{target_id}</code>\n"
                f"Использовано: {used}/{current_limit}\n"
                f"Осталось: <b>{remaining}</b>",
                parse_mode="HTML",
            )
        elif sub_cmd == "reset":
            await database.reset_user_requests_today(target_id)
            await message.answer(
                f"✅ Лимит для <code>{target_id}</code> сброшен.",
                parse_mode="HTML",
            )
        elif sub_cmd == "block":
            limit_str = await database.get_setting(
                "daily_limit", str(config.DAILY_USER_LIMIT)
            )
            current_limit = int(limit_str)
            await database.block_user_today(target_id, current_limit)
            await message.answer(
                f"🛑 Лимит для <code>{target_id}</code> исчерпан "
                "(заблокирован до завтра).",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "❓ Неизвестная команда.\n"
                "Использование:\n"
                "/admin limit <id|@тег>\n"
                "/admin reset <id|@тег>\n"
                "/admin block <id|@тег>\n"
                "/admin setlimit <число>\n"
                "/admin schedule <часы>"
            )
    else:
        await message.answer(
            "❓ Неверный формат команды.\n"
            "Использование:\n"
            "/admin\n"
            "/admin limit <id|@тег>\n"
            "/admin reset <id|@тег>\n"
            "/admin block <id|@тег>\n"
            "/admin setlimit <число>\n"
            "/admin schedule <часы>"
        )


@dp.callback_query(F.data == "admin_stats")
async def process_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("🔒 Доступ запрещен", show_alert=True)
        return

    stats = await database.get_stats_today()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data="admin_stats_back"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        f"📊 <b>Статистика за сегодня:</b>\n\n"
        f"👥 Активных пользователей: <b>{stats['users_count']}</b>\n"
        f"💬 Всего запросов: <b>{stats['requests_count']}</b>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_reset_confirm")
async def process_admin_reset_confirm(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("🔒 Доступ запрещен", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, сбросить всё", callback_data="admin_reset_all"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data="admin_stats_back"
                )
            ],
        ]
    )
    await callback.message.edit_text(
        "⚠️ <b>Вы уверены, что хотите сбросить лимиты "
        "ВСЕХ пользователей за сегодня?</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_reset_all")
async def process_admin_reset_all(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("🔒 Доступ запрещен", show_alert=True)
        return

    await database.reset_all_requests_today()
    await callback.message.edit_text(
        "✅ <b>Все лимиты за сегодня успешно сброшены!</b>", parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_stats_back")
async def process_admin_stats_back(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("🔒 Доступ запрещен", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика", callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить все лимиты",
                    callback_data="admin_reset_confirm",
                )
            ],
        ]
    )
    await callback.message.edit_text(
        "🛠 <b>Панель администратора</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(Command("adminhelp"))
async def cmd_admin_help(message: Message):
    """Справка по командам администратора."""
    if message.from_user.id not in config.ADMIN_IDS:
        return  # Игнорируем обычных пользователей

    await message.answer(
        "📖 <b>Справка по админ-панели</b>\n\n"
        "Вы можете управлять лимитами и расписанием.\n\n"
        "📋 <b>Команды:</b>\n"
        "• <code>/admin</code> — Открыть меню (статистика, сброс всех).\n"
        "• <code>/admin limit &lt;ID|@тег&gt;</code> — Посмотреть "
        "лимит пользователя.\n"
        "• <code>/admin reset &lt;ID|@тег&gt;</code> — Сбросить "
        "лимит пользователя.\n"
        "• <code>/admin block &lt;ID|@тег&gt;</code> — Завершить "
        "лимит (заблокировать).\n"
        "• <code>/admin setlimit &lt;число&gt;</code> — Изменить "
        "общий лимит для всех.\n"
        "• <code>/admin schedule &lt;часы&gt;</code> — Изменить "
        "расписание опросов.\n"
        "• <code>/admin topics &lt;темы&gt;</code> — Изменить "
        "список тем.\n"
        "• <code>/admin backup</code> — Скачать бэкап базы данных.\n\n"
        "💡 <i>Пример:</i> <code>/admin limit @nickname</code>",
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
                entity.offset: entity.offset + entity.length
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
    await database.save_user(user_id, message.from_user.username)

    # В групповых чатах отвечаем только если бот упомянут или ему reply
    is_private = message.chat.type == ChatType.PRIVATE
    if not is_private:
        if not _is_bot_mentioned(message) and not _is_reply_to_bot(message):
            return  # Игнорируем сообщения, не адресованные боту

    # Проверяем лимит
    used = await database.get_user_requests_today(user_id)
    limit_str = await database.get_setting(
        "daily_limit", str(config.DAILY_USER_LIMIT)
    )
    current_limit = int(limit_str)

    if used >= current_limit:
        await message.answer(
            "🔴 <b>Дневной лимит исчерпан!</b>\n"
            f"Вы использовали все {current_limit} "
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
    remaining = current_limit - new_used
    footer = ""
    if remaining <= 5:
        footer = (
            f"\n\n⚠️ <i>Осталось сообщений: "
            f"{remaining}/{current_limit}</i>"
        )

    # Экранируем HTML-символы в ответе ИИ, чтобы Telegram не крашился
    safe_response = html.escape(response_text)
    safe_response = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", safe_response)
    await message.answer(safe_response + footer, parse_mode="HTML")


# ========== ФУНКЦИЯ ОТПРАВКИ ОПРОСА ==========


async def send_scheduled_poll():
    """Генерирует и отправляет опрос в чат."""
    topic = await ai.get_random_topic()
    recent_questions = await database.get_recent_polls(20)

    logger.info("Генерация опроса на тему: %s", topic)

    poll_data = await ai.generate_poll(topic, recent_questions)

    if poll_data is None:
        logger.error("Не удалось сгенерировать опрос. Пропускаем.")
        await notify_admins("⚠️ <b>Не удалось сгенерировать опрос ИИ.</b>")
        return

    try:
        await bot.send_poll(
            chat_id=config.CHAT_ID,
            question=poll_data["question"],
            options=[{"text": option} for option in poll_data["options"]],
            type="regular",
            is_anonymous=False,
        )

        # Сохраняем в историю
        await database.add_poll(poll_data["question"], topic)
        logger.info("Опрос успешно отправлен: %s", poll_data["question"])

    except Exception as e:
        logger.error("Ошибка при отправке опроса: %s", e)
        await notify_admins(
            f"⚠️ <b>Ошибка отправки опроса:</b>\n<code>{e}</code>"
        )


# ========== ЗАПУСК ==========


async def setup_poll_jobs(scheduler: AsyncIOScheduler):
    """Настройка задач опроса в планировщике из БД."""
    hours_str = await database.get_setting("poll_hours", config.POLL_HOURS)
    logger.info(f"Загрузка расписания опросов: {hours_str}")

    schedule_list = []
    try:
        for h_m in hours_str.split(","):
            if ":" in h_m:
                h, m = h_m.strip().split(":")
                schedule_list.append({"hour": int(h), "minute": int(m)})
    except Exception as e:
        logger.error(f"Ошибка парсинга расписания: {e}")
        schedule_list = [{"hour": 7, "minute": 0}, {"hour": 17, "minute": 0}]

    scheduler.remove_all_jobs()
    for schedule in schedule_list:
        scheduler.add_job(
            send_scheduled_poll,
            CronTrigger(
                hour=schedule["hour"],
                minute=schedule["minute"],
                timezone="Europe/Moscow",
            ),
            id=f"poll_{schedule['hour']}_{schedule['minute']}",
            replace_existing=True,
        )
        logger.info(
            f"Опрос запланирован на "
            f"{schedule['hour']:02d}:{schedule['minute']:02d} МСК"
        )


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

    # ⬇️ НАСТРОЙКА МЕНЮ КОМАНД ⬇️
    user_commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="limit", description="Проверить лимит"),
    ]
    await bot.set_my_commands(user_commands)

    admin_commands = user_commands + [
        BotCommand(command="admin", description="🛠 Панель админа"),
        BotCommand(command="adminhelp", description="❓ Справка по админке"),
    ]
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            pass
    # ⬆️ КОНЕЦ НАСТРОЙКИ КОМАНД ⬆️

    global scheduler

    # Настройка планировщика
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    await setup_poll_jobs(scheduler)

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
