from __future__ import annotations

import json
import logging
import random

import httpx

import config

logger = logging.getLogger(__name__)

# Переиспользуемый HTTP-клиент (создаётся один раз)
_http_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Возвращает переиспользуемый HTTP-клиент."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60)
    return _http_client


async def close_client():
    """Закрывает HTTP-клиент (вызывается при завершении бота)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


async def _call_ai(messages: list[dict], temperature: float = 0.8) -> str | None:
    """
    Универсальный вызов OpenAI-совместимого API.
    Работает с любым провайдером: OpenRouter, Gemini, OpenAI и др.
    Все настройки берутся из .env через config.py.
    """
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config.AI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    try:
        client = await _get_client()
        response = await client.post(
            config.AI_BASE_URL,
            headers=headers,
            json=payload,
        )

        if response.status_code != 200:
            logger.error(
                "AI API ошибка %d: %s",
                response.status_code,
                response.text,
            )
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.error("Ошибка при вызове AI API: %s", e)
        return None


async def generate_poll(topic: str, recent_questions: list[str]) -> dict | None:
    """
    Генерирует вопрос для горячей дискуссии.

    Возвращает dict:
        {
            "question": "Текст вопроса",
            "options": ["Вариант 1", "Вариант 2"]
        }
    или None при ошибке.
    """
    recent_text = ""
    if recent_questions:
        recent_text = "\n\nНЕ ПОВТОРЯЙ эти вопросы, они уже были заданы:\n" + "\n".join(
            f"- {q}" for q in recent_questions
        )

    prompt = (
        f"По теме: «{topic}».\n"
        f"Придумай спорное утверждение или вопрос для опроса в чате.\n"
        f"Текст должен быть завлекающим, острым, провокационным.\n"
        f"Дай 2 или 3 самых ярких варианта ответа "
        f"(например: 'Обожаю', 'Ненавижу').\n"
        f"{recent_text}\n\n"
        f"Ответь СТРОГО в формате JSON без markdown-обёртки:\n"
        f'{{"question": "текст вопроса", '
        f'"options": ["вариант1", "вариант2"]}}\n\n'
    )

    messages = [
        {"role": "system", "content": config.POLL_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    text = await _call_ai(messages, temperature=0.9)
    if text is None:
        return None

    try:
        clean = text.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1]).strip()

        data = json.loads(clean)

        if "question" in data and "options" in data and 2 <= len(data["options"]) <= 4:
            return data
        else:
            logger.error("Некорректная структура ответа: %s", data)
            return None

    except json.JSONDecodeError as e:
        logger.error("Ошибка парсинга JSON: %s | Текст: %s", e, text)
        return None


async def chat_response(user_message: str, history: list[dict] | None = None) -> str:
    """
    Генерирует ответ на сообщение пользователя.

    Args:
        user_message: текст сообщения пользователя
        history: список предыдущих сообщений

    Returns:
        Текстовый ответ от ИИ.
    """
    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]

    # Добавляем историю диалога (последние 10 сообщений)
    if history:
        for msg in history[-10:]:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            messages.append({"role": role, "content": msg["text"]})

    messages.append({"role": "user", "content": user_message})

    result = await _call_ai(messages, temperature=0.8)

    if result:
        return result
    else:
        return "⚠️ Произошла ошибка при обращении к ИИ. Попробуйте позже."


def get_random_topic() -> str:
    """Возвращает случайную тему из списка."""
    return random.choice(config.POLL_TOPICS)
