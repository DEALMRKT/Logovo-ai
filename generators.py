import os
import httpx

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


async def ai_reply(messages, api_key, model, base_url):
    if not api_key:
        return None, "🔑 ИИ не подключён: добавь AI_API_KEY в Render → Environment."
    if not model:
        return None, "⚙️ Не задана модель. Укажи AI_MODEL в Render → Environment."
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv("RENDER_EXTERNAL_URL", "https://logovo-ai.onrender.com"),
                    "X-Title": "Логово Знаний ИИ",
                },
                json={"model": model, "messages": messages, "temperature": 0.85, "max_tokens": 1600},
            )
        if response.status_code == 429:
            return None, "⏳ OpenRouter временно ограничил запросы или закончился доступный лимит. Попробуй позже."
        if response.status_code in (401, 403):
            return None, "🔐 OpenRouter отклонил ключ или доступ к модели. Проверь AI_API_KEY и доступность AI_MODEL в Render."
        if response.status_code == 404:
            return None, "🔎 OpenRouter не нашёл модель. Проверь точное значение AI_MODEL."
        if response.status_code >= 500:
            return None, f"🌐 OpenRouter временно недоступен (ошибка {response.status_code}). Попробуй позже."
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            details = (data.get("error") or {}).get("message") or "Провайдер не вернул ответ."
            return None, "⚠️ " + str(details)[:300]
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            return None, "⚠️ Модель вернула пустой ответ. Попробуй ещё раз."
        return str(content).strip()[:3900], None
    except httpx.TimeoutException:
        return None, "⌛ ИИ не успел ответить за отведённое время. Попробуй ещё раз."
    except httpx.HTTPStatusError as exc:
        return None, f"⚠️ Ошибка OpenRouter: HTTP {exc.response.status_code}. Проверь настройки модели."
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return None, f"⚠️ Не удалось связаться с OpenRouter ({type(exc).__name__}). Проверь настройки Render."


async def generate_story(genre, api_key, model, base_url, previous_story=None):
    genre_description = GENRES.get(genre, GENRES["survival"])
    system = (
        "Ты профессиональный автор интерактивных приключений. Пиши по-русски, ярко и связно. "
        "Создавай оригинальные сюжеты, не повторяй одинаковые вступления и развязки. "
        "Без графических сцен, жестоких подробностей и опасных инструкций. "
        "Оставляй игроку осмысленный выбор."
    )
    if previous_story:
        user_prompt = (
            f"Продолжи эту историю в том же стиле и с сохранением всех фактов. "
            f"Не пересказывай уже написанное. Добавь 2–3 новые сцены, развитие персонажей, "
            f"новую улику или проблему и закончи новым выбором.\n\nИстория:\n{previous_story[-6500:]}"
        )
    else:
        user_prompt = (
            f"Создай совершенно новую интерактивную историю в жанре: {genre_description}. "
            "Дай цепляющее название, короткую завязку, 3 персонажей с разными целями, "
            "5 последовательных сцен, неожиданный логичный поворот и выбор из 2–3 вариантов в конце. "
            "Каждый новый запрос должен давать другой сюжет."
        )
    return await ai_reply([{"role": "system", "content": system}, {"role": "user", "content": user_prompt}], api_key, model, base_url)
