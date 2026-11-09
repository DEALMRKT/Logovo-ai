import os
import httpx

GENRES = {
    "zombie": "зомби-апокалипсис без натуралистичных подробностей, с упором на тайну, командную работу и выбор",
    "blackout": "масштабное отключение электричества, загадки, неизвестные сигналы и атмосфера напряжения",
    "detective": "детективная загадка с честными уликами, несколькими подозреваемыми и логичным раскрытием",
    "survival": "приключение о выживании после природной катастрофы, взаимопомощи и трудных решениях",
}

HF_API_URL = "https://router.huggingface.co/v1/chat/completions"


async def ai_reply(messages, api_key, model, base_url=None):
    if not api_key:
        return None, "🔑 ИИ не подключён: добавь HF_TOKEN в Render → Environment."
    if not model:
        return None, "⚙️ Не задана модель. Укажи HF_MODEL в Render → Environment."
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0)) as client:
            response = await client.post(
                HF_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.85,
                    "max_tokens": 1600,
                    "stream": False,
                },
            )
        if response.status_code == 401:
            return None, "🔐 Hugging Face отклонил токен. Проверь HF_TOKEN и разрешение Inference Providers."
        if response.status_code == 403:
            return None, "⛔ У токена нет доступа к Inference Providers или модели. Проверь разрешения токена."
        if response.status_code == 402:
            return None, "💳 Для этого запроса недостаточно доступного лимита Inference Providers. Проверь Usage/Billing в Hugging Face."
        if response.status_code == 429:
            return None, "⏳ Лимит запросов Hugging Face временно исчерпан. Попробуй позже."
        if response.status_code == 404:
            return None, "🔎 Hugging Face не нашёл модель. Проверь HF_MODEL и доступность модели у Inference Providers."
        if response.status_code >= 500:
            return None, f"🌐 Сервис модели временно недоступен (HTTP {response.status_code}). Попробуй позже."
        if response.is_error:
            try:
                details = response.json().get("error", response.text)
            except Exception:
                details = response.text
            return None, f"⚠️ Hugging Face: {str(details)[:350]}"
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None, "⚠️ Модель не вернула ответ. Попробуй ещё раз."
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not content:
            return None, "⚠️ Модель вернула пустой ответ. Попробуй ещё раз."
        return str(content).strip()[:3900], None
    except httpx.TimeoutException:
        return None, "⌛ ИИ не успел ответить. Попробуй ещё раз."
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return None, f"⚠️ Не удалось связаться с Hugging Face ({type(exc).__name__}). Проверь настройки Render."


def make_prompt():
    return (
        "Создай оригинальную интерактивную историю на русском языке. "
        "Раздели её на 5 сцен, добавь 3 персонажей с разными целями, "
        "неожиданный, но логичный поворот и выбор из 2–3 вариантов в конце. "
        "Не используй шаблонные клише; сохраняй последовательность событий."
    )


async def generate_story(genre, api_key, model, previous_story=None):
    genre_description = GENRES.get(genre, GENRES["survival"])
    system = (
        "Ты профессиональный автор интерактивных приключений. Пиши по-русски, ярко и связно. "
        "Создавай оригинальные сюжеты, не повторяй одинаковые вступления и развязки. "
        "Без графических сцен, жестоких подробностей и опасных инструкций. "
        "Оставляй игроку осмысленный выбор."
    )
    if previous_story:
        user_prompt = (
            "Продолжи эту историю в том же стиле и с сохранением всех фактов. "
            "Не пересказывай уже написанное. Добавь 2–3 новые сцены, развитие персонажей, "
            "новую улику или проблему и закончи новым выбором.\n\nИстория:\n" + previous_story[-6500:]
        )
    else:
        user_prompt = (
            f"Создай совершенно новую интерактивную историю в жанре: {genre_description}. "
            "Дай цепляющее название, короткую завязку, 3 персонажей с разными целями, "
            "5 последовательных сцен, неожиданный логичный поворот и выбор из 2–3 вариантов в конце. "
            "Каждый новый запрос должен давать другой сюжет."
        )
    return await ai_reply(
        [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}],
        api_key, model,
    )
