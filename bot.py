import os
import logging
import asyncio
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from storage import init_db, get_role, set_role, list_users, stats, log_user
from generators import make_story, make_prompt, ai_reply

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

def is_staff(user_id: int) -> bool:
    return get_role(user_id) in ("owner", "deputy", "admin")

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID and OWNER_ID != 0

def main_menu():
    kb = InlineKeyboardBuilder()
    for label, data in [
        ("🎲 Создать сюжет", "story"),
        ("🧟 Зомби-апокалипсис", "genre:zombie"),
        ("⚡ Блэкаут", "genre:blackout"),
        ("🕵️ Расследование", "genre:detective"),
        ("✍️ Создать промт", "prompt"),
        ("🤖 ИИ-чат", "ai"),
        ("👤 Мой профиль", "profile"),
    ]:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="👥 Пользователи", callback_data="adm:users")
    kb.button(text="⬅️ Главное меню", callback_data="home")
    kb.adjust(2, 1)
    return kb.as_markup()

@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    log_user(user.id, user.username or "", user.full_name or "")
    role = get_role(user.id)
    role_label = {"owner": "👑 Владелец", "deputy": "💎 Заместитель", "admin": "🛡️ Администратор"}.get(role, "👤 Пользователь")
    await message.answer(
        f"✨ <b>NEBULA AI</b>\n\nПривет, {user.mention_html()}!\nТвоя роль: {role_label}\n\n"
        "Создавай сюжеты, промты и общайся с ИИ. Выбирай действие ниже.",
        reply_markup=main_menu()
    )

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_staff(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к админ-панели.")
        return
    await message.answer(
        "🛡️ <b>Панель управления NEBULA AI</b>\n\n"
        "Назначение ролей (только владелец):\n"
        "<code>/deputy TELEGRAM_ID</code> — заместитель\n"
        "<code>/grantadmin TELEGRAM_ID</code> — администратор\n"
        "<code>/removeadmin TELEGRAM_ID</code> — снять роль",
        reply_markup=admin_menu()
    )

@dp.message(Command("id"))
async def get_id(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text("✨ <b>NEBULA AI</b>\nВыбери действие:", reply_markup=main_menu())
    await call.answer()

@dp.callback_query(F.data == "story")
async def story_random(call: CallbackQuery):
    await call.message.answer("🎲 <b>Твой сюжет:</b>\n\n" + make_story())
    await call.answer()

@dp.callback_query(F.data.startswith("genre:"))
async def story_genre(call: CallbackQuery):
    genre = call.data.split(":", 1)[1]
    await call.message.answer("🎬 <b>Сюжет:</b>\n\n" + make_story(genre))
    await call.answer()

@dp.callback_query(F.data == "prompt")
async def prompt(call: CallbackQuery):
    await call.message.answer("✍️ <b>Промт для истории:</b>\n\n" + make_prompt())
    await call.answer()

@dp.callback_query(F.data == "ai")
async def ai_info(call: CallbackQuery):
    await call.message.answer(
        "🤖 Напиши сообщение, начиная с <code>/ask</code>.\n"
        "Например: <code>/ask Придумай необычный сюжет для игры</code>\n\n"
        "Для настоящих ответов ИИ добавь AI_API_KEY в переменные окружения. Без ключа бот предложит демо-режим."
    )
    await call.answer()

@dp.message(Command("ask"))
async def ask(message: Message):
    prompt_text = (message.text or "").partition(" ")[2].strip()
    if not prompt_text:
        await message.answer("Напиши вопрос после команды: <code>/ask твой вопрос</code>")
        return
    answer = await ai_reply(prompt_text, AI_API_KEY, AI_MODEL, AI_BASE_URL)
    await message.answer(answer)

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    role = get_role(call.from_user.id)
    label = {"owner": "👑 Владелец", "deputy": "💎 Заместитель", "admin": "🛡️ Администратор"}.get(role, "👤 Пользователь")
    await call.message.answer(f"👤 <b>Профиль</b>\nID: <code>{call.from_user.id}</code>\nРоль: {label}")
    await call.answer()

@dp.callback_query(F.data == "adm:stats")
async def admin_stats(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    data = stats()
    await call.message.answer(f"📊 <b>Статистика</b>\nПользователей: {data['users']}\nАктивных сегодня: {data['today']}")
    await call.answer()

@dp.callback_query(F.data == "adm:users")
async def admin_users(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    users = list_users(15)
    lines = [f"• <code>{u['user_id']}</code> — {u['name'] or 'без имени'} ({u['role']})" for u in users]
    await call.message.answer("👥 <b>Последние пользователи</b>\n" + ("\n".join(lines) if lines else "Пока пусто"))
    await call.answer()

async def role_action(message: Message, action: str):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Назначать и снимать роли может только владелец.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: команда и Telegram ID. Например: <code>/deputy 123456789</code>")
        return
    target = int(parts[1])
    if target == OWNER_ID:
        await message.answer("Нельзя менять роль владельца.")
        return
    role = {"deputy": "deputy", "admin": "admin", "remove": "user"}[action]
    set_role(target, role)
    await message.answer(f"✅ Для <code>{target}</code> установлена роль: <b>{role}</b>")

@dp.message(Command("deputy"))
async def deputy(message: Message): await role_action(message, "deputy")

@dp.message(Command("grantadmin"))
async def grantadmin(message: Message): await role_action(message, "admin")

@dp.message(Command("removeadmin"))
async def removeadmin(message: Message): await role_action(message, "remove")

@dp.message()
async def fallback(message: Message):
    await message.answer("Выбери функцию в меню или используй /ask для ИИ-чата.", reply_markup=main_menu())

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to environment variables.")
    await init_db(OWNER_ID)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
