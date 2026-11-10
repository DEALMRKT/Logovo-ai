import os
import httpx

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Shared HTTP client managed by app.py lifespan.
_http_client: httpx.AsyncClient | None = None


async def init_http_client():
    """Create the shared HTTP client during application startup."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=15.0))


async def close_http_client():
    """Close the shared HTTP client during application shutdown."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None

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
        client = _http_client
        if client is None or client.is_closed:
            # Fallback keeps ai_reply usable in local scripts/tests too.
            async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=15.0)) as temporary_client:
                response = await temporary_client.post(
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
        else:
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


async def generate_story(genre, api_key, model, previous_story=None, selected_choice=None):
    genre_description = GENRES.get(genre, GENRES["survival"])
    system = (
        "Ты — автор интерактивных приключений проекта «Логово Знаний ИИ». "
        "Пиши по-русски, атмосферно и последовательно. Сохраняй имена, характеры, "
        "факты и причинно-следственные связи. Не начинай историю заново при продолжении. "
        "Без графических сцен, жестоких подробностей и опасных инструкций. "
        "В КОНЦЕ КАЖДОЙ ЧАСТИ ОБЯЗАТЕЛЬНО выведи ровно 2 или 3 доступных решения "
        "в отдельном блоке строго такого формата, без Markdown и без текста после него:\n"
        "ВЫБОРЫ:\n1) Название решения — конкретное действие героя.\n"
        "2) Название решения — конкретное действие героя.\n"
        "3) Название решения — конкретное действие героя.\n"
        "Обязательно выведи заголовок ВЫБОРЫ: отдельной строкой. Не помещай варианты в середину рассказа. "
        "Не нумеруй сцены как варианты. Каждый вариант должен быть реальным действием читателя "
        "и вести к отличающемуся развитию событий. Это правило действует для каждого жанра и каждой части."
    )
    if previous_story:
        choice_instruction = (
            f"\n\nРЕШЕНИЕ ЧИТАТЕЛЯ: {selected_choice or 'Пользователь нажал продолжить без выбора.'}\n"
            "Обязательно покажи последствия именно этого решения в следующей части. "
            "Не игнорируй и не заменяй его другим вариантом. Если решение меняет ситуацию, "
            "отрази это в событиях, диалогах и состоянии персонажей."
        )
        user_prompt = (
            "Продолжи именно эту историю с места остановки. Не пересказывай предыдущие события "
            "и не начинай заново. Сохрани все имена, факты, атмосферу и незакрытые линии. "
            "Добавь 2–3 последовательные сцены, покажи последствия выбора читателя и закончи "
            "новыми 2–3 решениями в формате ВЫБОРЫ.\n\nПредыдущая история:\n"
            + previous_story[-8500:] + choice_instruction
        )
    else:
        user_prompt = (
            f"Создай совершенно новую интерактивную историю в жанре: {genre_description}. "
            "Дай необычное название, завязку, 3 персонажей с разными целями, несколько "
            "последовательных сцен и логичный неожиданный поворот. В конце обязательно "
            "предложи 2 или 3 разных решения в точном формате ВЫБОРЫ."
        )
    return await ai_reply(
        [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        api_key,
        model,
    )


async def generate_story_choices(story_text, api_key, model):
    """Generate parseable interactive choices when the story response omitted them."""
    if not story_text:
        return [], "Пустой текст истории."
    prompt = (
        "Прочитай последнюю часть интерактивной истории. Не переписывай её и не продолжай сюжет. "
        "Придумай ровно 3 разных, логичных и безопасных действия, которые читатель может выбрать сейчас. "
        "Каждое действие должно соответствовать текущей ситуации и менять дальнейший сюжет. "
        "Верни ТОЛЬКО формат без Markdown и пояснений:\n"
        "ВЫБОРЫ:\n1) Короткое название — конкретное действие.\n"
        "2) Короткое название — конкретное действие.\n"
        "3) Короткое название — конкретное действие.\n\nПоследняя часть истории:\n"
        + str(story_text)[-5000:]
    )
    answer, error = await ai_reply(
        [{"role": "system", "content": "Ты создаёшь варианты выбора для интерактивных историй. Соблюдай строгий формат."},
         {"role": "user", "content": prompt}], api_key, model
    )
    if error:
        return [], error
    import re
    choices = []
    for line in answer.splitlines():
        match = re.match(r"^\s*(?:[-*]\s*)?(?:[1-3][.)])\s*(.+)$", line.strip())
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            if value:
                choices.append(value[:180])
    return choices[:3], None if len(choices) >= 2 else "Модель не вернула варианты в нужном формате."
