import os
import httpx

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GENRES = {
    "zombie": "зомби-апокалипсис без натуралистичных подробностей, с упором на тайну, командную работу и выбор",
    "blackout": "масштабное отключение электричества, загадки, неизвестные сигналы и атмосфера напряжения",
    "detective": "детективная загадка с честными уликами, несколькими подозреваемыми и логичным раскрытием",
    "survival": "приключение о выживании после природной катастрофы, взаимопомощи и трудных решениях",
}


def make_prompt():
    return (
        "Создай оригинальную интерактивную историю на русском языке. "
        "Раздели её на 5 сцен, добавь 3 персонажей с разными целями, "
        "неожиданный, но логичный поворот и выбор из 2–3 вариантов в конце. "
        "Не используй шаблонные клише; сохраняй последовательность событий."
    )


async def ai_reply(messages, api_key, model):
    if not api_key:
        return None, "🔑 ИИ не подключён: добавь GROQ_API_KEY в Render → Environment."
    if not model:
        return None, "⚙️ Не задана модель. Укажи GROQ_MODEL в Render → Environment."

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=15.0)) as client:
            response = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.85,
                    "max_completion_tokens": 1800,
                    "stream": False,
                },
            )

        if response.status_code == 401:
            return None, "🔐 Groq не принял ключ. Проверь GROQ_API_KEY в Render."
        if response.status_code == 403:
            return None, "⛔ Groq запретил запрос для этого ключа или модели. Проверь настройки аккаунта."
        if response.status_code == 404:
            return None, "🔎 Groq не нашёл модель. Проверь GROQ_MODEL."
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            suffix = f" Повтори примерно через {retry_after} сек." if retry_after else " Попробуй позже — лимиты Groq временные."
            return None, "⏳ Достигнут лимит Groq." + suffix
        if response.status_code >= 500:
            return None, f"🌐 Groq временно недоступен (HTTP {response.status_code}). Попробуй позже."
        if response.is_error:
            try:
                details = response.json().get("error", {}).get("message") or response.text
            except Exception:
                details = response.text
            return None, f"⚠️ Ошибка Groq: {str(details)[:260]}"

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None, "⚠️ Модель не вернула ответ. Попробуй ещё раз."
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content or not str(content).strip():
            return None, "⚠️ Модель вернула пустой ответ. Попробуй ещё раз."
        return str(content).strip()[:3900], None

    except httpx.TimeoutException:
        return None, "⌛ Groq отвечает слишком долго. Попробуй ещё раз."
    except httpx.HTTPError as exc:
        return None, f"⚠️ Не удалось связаться с Groq ({type(exc).__name__}). Попробуй позже."
    except (ValueError, KeyError, TypeError):
        return None, "⚠️ Groq вернул ответ в неожиданном формате. Попробуй ещё раз."


async def generate_story(genre, api_key, model, previous_story=None):
    genre_description = GENRES.get(genre, GENRES["survival"])
    system = (
        "Ты — профессиональный автор интерактивных приключений проекта «Логово Знаний ИИ». "
        "Пиши по-русски, выразительно, атмосферно и связно. Каждый сюжет должен быть новым: "
        "меняй места, имена, тип загадки, конфликт, начало и развязку. Не копируй готовые шаблоны. "
        "Соблюдай причинно-следственную связь и характеры персонажей. "
        "Без графических сцен, жестоких подробностей и опасных инструкций."
    )
    if previous_story:
        user_prompt = (
            "Продолжи именно эту историю. Не пересказывай предыдущие события и не начинай заново. "
            "Сохрани имена, факты, атмосферу и незакрытые сюжетные линии. Добавь 2–3 новые сцены, "
            "новую улику или неожиданное осложнение и закончи выбором из 2–3 вариантов. "
            "Не повторяй формулировки предыдущей части.\n\nПредыдущая история:\n" + previous_story[-6500:]
        )
    else:
        user_prompt = (
            f"Создай совершенно новую интерактивную историю в жанре: {genre_description}. "
            "Структура: необычное название; короткая завязка; 3 персонажа с разными целями; "
            "5 последовательных сцен; логичный неожиданный поворот; выбор из 2–3 вариантов в конце. "
            "Избегай банальных вступлений вроде «Однажды» и повторяющихся клише."
        )
    return await ai_reply(
        [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        api_key,
        model,
    )
