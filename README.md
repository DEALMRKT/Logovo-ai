# Логово Знаний ИИ

Telegram-бот на aiogram 3 с webhook для Render.

## Возможности
- ИИ-чат с короткой памятью диалога до перезапуска процесса.
- Оригинальные интерактивные истории: блэкаут, зомби-апокалипсис, детектив, выживание.
- Продолжение истории и новый сюжет.
- Обязательная подписка на `@logovoznani`.
- Профиль, роли, статистика и админ-панель.
- Загрузка Premium Emoji из указанных наборов и использование custom emoji как иконок inline-кнопок. Для этого владелец бота должен иметь Telegram Premium; при недоступности ID кнопки остаются с обычными emoji.
- `/emojiid` показывает custom_emoji_id у сообщения, на которое ответили командой.

## Render Environment
- `BOT_TOKEN` — токен BotFather.
- `OWNER_ID` — числовой Telegram ID владельца.
- `WEBHOOK_SECRET` — секрет вебхука (1–256 символов, буквы/цифры/`_`/`-`).
- `HF_TOKEN` — токен Hugging Face с разрешением Inference Providers.
- `HF_MODEL` — по умолчанию `Qwen/Qwen2.5-7B-Instruct-1M:fastest`.
- `CHANNEL_USERNAME` — `@logovoznani`.
- `RENDER_EXTERNAL_URL` — `https://logovo-ai.onrender.com`.

ИИ теперь вызывается через официальный OpenAI-совместимый endpoint Hugging Face: `https://router.huggingface.co/v1/chat/completions`. OpenRouter-переменные больше не используются. Доступность конкретной модели и бесплатный лимит зависят от Inference Provider и аккаунта; проверь Usage/Billing в Hugging Face.

## Развёртывание
1. Замени файлы в GitHub-репозитории содержимым архива.
2. В Render → Environment добавь `HF_TOKEN` и удали старые `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`.
3. Убедись, что Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
4. Deploy latest commit.
5. Проверь `/health`.

Не публикуй `BOT_TOKEN`, `HF_TOKEN` и `WEBHOOK_SECRET`.
