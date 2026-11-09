import os
import hmac
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bot import BOT_TOKEN, dp, startup, load_custom_emojis
from generators import init_http_client, close_http_client


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("logovo.webhook")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://logovo-ai.onrender.com"
).strip().rstrip("/")

if RENDER_URL and not RENDER_URL.startswith(("https://", "http://")):
    RENDER_URL = "https://" + RENDER_URL

bot: Bot | None = None
emoji_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, emoji_task

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing in Render Environment")

    if (
        not WEBHOOK_SECRET
        or len(WEBHOOK_SECRET) > 256
        or not all(c.isalnum() or c in "_-" for c in WEBHOOK_SECRET)
    ):
        raise RuntimeError("Invalid WEBHOOK_SECRET")

    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    await init_http_client()
    await startup(bot)

    # Register Telegram webhook
    webhook_url = f"{RENDER_URL}/telegram"

    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False
    )

    info = await bot.get_webhook_info()

    log.info("Webhook configured at %s/telegram", RENDER_URL)
    log.info(
        "Webhook state: pending=%s, last_error=%s",
        info.pending_update_count,
        info.last_error_message or "none"
    )

    emoji_task = asyncio.create_task(
        load_custom_emojis(bot),
        name="load-custom-emojis"
    )

    try:
        yield

    finally:
        if emoji_task and not emoji_task.done():
            emoji_task.cancel()

            try:
                await emoji_task
            except asyncio.CancelledError:
                pass

        await close_http_client()

        if bot:
            # Не удаляем вебхук при перезапуске Render!
            await bot.session.close()
            bot = None


app = FastAPI(title="Логово Знаний ИИ", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "service": "Логово Знаний ИИ",
        "status": "ok"
    }


@app.head("/")
async def root_head():
    return {
        "service": "Логово Знаний ИИ",
        "status": "ok"
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bot_initialized": bot is not None
    }


@app.post("/telegram")
async def telegram_webhook(request: Request):

    if bot is None:
        raise HTTPException(
            status_code=503,
            detail="Bot is starting"
        )

    header_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        ""
    )

    if not hmac.compare_digest(header_secret, WEBHOOK_SECRET):
        raise HTTPException(
            status_code=403,
            detail="Invalid Telegram secret token"
        )

    try:
        payload = await request.json()

        update = Update.model_validate(
            payload,
            context={"bot": bot}
        )

        update_type = next(
            (
                key for key in payload
                if key.endswith("_update")
                or key in (
                    "message",
                    "callback_query",
                    "edited_message",
                    "channel_post"
                )
            ),
            "unknown"
        )

        log.info(
            "Telegram webhook update received: %s id=%s",
            update_type,
            update.update_id
        )

        await dp.feed_update(bot, update)

    except Exception:
        log.exception("Failed to process Telegram update")

        raise HTTPException(
            status_code=500,
            detail="Update processing failed"
        )

    return {"ok": True}
