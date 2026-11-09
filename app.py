import os
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bot import BOT_TOKEN, dp, startup

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("logovo.webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://logovo-ai.onrender.com").strip().rstrip("/")
if RENDER_URL and not RENDER_URL.startswith(("https://", "http://")):
    RENDER_URL = "https://" + RENDER_URL

bot: Bot | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing in Render Environment")
    if not WEBHOOK_SECRET or len(WEBHOOK_SECRET) > 256 or not all(c.isalnum() or c in "_-" for c in WEBHOOK_SECRET):
        raise RuntimeError("WEBHOOK_SECRET must contain 1-256 characters: letters, digits, _ or -")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await startup(bot)
    webhook_url = f"{RENDER_URL}/telegram/{WEBHOOK_SECRET}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
    log.info("Webhook configured: %s/telegram/[hidden]", RENDER_URL)
    try:
        yield
    finally:
        if bot:
            try:
                await bot.delete_webhook()
            except Exception:
                log.exception("Could not delete webhook during shutdown")
            await bot.session.close()
            bot = None


app = FastAPI(title="Логово Знаний ИИ", lifespan=lifespan)


@app.get("/")
async def root():
    return {"service": "Логово Знаний ИИ", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if not hmac.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(header_secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid Telegram secret token")
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot is starting")
    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        log.exception("Failed to process Telegram update")
        raise HTTPException(status_code=500, detail="Update processing failed")
    return {"ok": True}
