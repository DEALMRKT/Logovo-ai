import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import dp, BOT_TOKEN, OWNER_ID
from storage import init_db

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
WEBHOOK_PATH = "/telegram-webhook"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET is missing. Set a long random secret in Render.")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(OWNER_ID)
    if RENDER_EXTERNAL_URL:
        await bot.set_webhook(
            url=f"https://{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}",
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=False
        )
        logging.info("Telegram webhook configured.")
    else:
        logging.warning("RENDER_EXTERNAL_URL is missing; set it in Render or set webhook manually.")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "NEBULA AI"}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}
