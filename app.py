import os
import re
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import dp, BOT_TOKEN, OWNER_ID
from storage import init_db

logging.basicConfig(level=logging.INFO)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
WEBHOOK_PATH = "/telegram-webhook"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment.")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing. Add a 1-256 character secret using only letters, numbers, _ or -.")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET):
    raise RuntimeError("WEBHOOK_SECRET has invalid characters or length. Use 32-256 characters: A-Z, a-z, 0-9, _ or -.")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def make_webhook_url(raw_url: str) -> str:
    """Accept Render's full HTTPS URL or a bare hostname; avoid duplicate schemes."""
    value = raw_url.strip().rstrip("/")
    if not value:
        raise RuntimeError("RENDER_EXTERNAL_URL is missing. Set it to https://your-service.onrender.com")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("RENDER_EXTERNAL_URL must be a public HTTPS Render URL, e.g. https://logovo-ai.onrender.com")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise RuntimeError("RENDER_EXTERNAL_URL must contain only the service origin, without a path or query string.")
    return f"https://{parsed.netloc}{WEBHOOK_PATH}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(OWNER_ID)
    try:
        webhook_url = make_webhook_url(RENDER_EXTERNAL_URL)
        await bot.set_webhook(
            url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=False,
        )
        logging.info("Telegram webhook configured: %s", webhook_url)
        yield
    finally:
        await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Логово Знаний ИИ"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
