import os
import logging
import asyncio
import html

from aiogram import Bot, Dispatcher, F, BaseMiddleware
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
AI_MODEL = os.getenv("AI_MODEL", "openrouter/free").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@logovoznani").strip()
CHANNEL_URL = "https://t.me/logovoznani"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()
awaiting_ai = set()
chat_history = {}


def is_staff(user_id: int) -> bool:
    return get_role(user_id) in ("owner", "deputy", "admin")


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID and OWNER_ID != 0


def main_menu(user_id: int | None = None):
    """Main menu. The admin entry is rendered only for users with staff roles."""
    kb = InlineKeyboardBuilder()
    for label, data in [
        ("🧠 ИИ-ассистент", "ai"),
        ("📜 Генератор историй", "story"),
        ("🌑 БЛЭКАУТ", "genre:blackout"),
        ("🧟 Зомби-апокалипсис", "genre:zombie"),
        ("🔎 Детектив", "genre:detective"),
        ("⚡ Создать промпт", "prompt"),
        ("👤 Мой профиль", "profile"),
    ]:
        kb.button(text=label, callback_data=data)
    kb.adjust(2, 1, 2, 2, 2)
    if user_id is not None and is_staff(user_id):
        kb.button(text="🛡️ Панель администратора", callback_data="adm:open")
        kb.adjust(2, 1, 2, 2, 1)
    return kb.as_markup()


def subscription_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="✦ Подписаться на канал", url=CHANNEL_URL)
    kb.button(text="✓ Проверить доступ", callback_data="sub:check")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu(user_id: int | None = None):
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="adm:stats")
    kb.button(text="👥 Пользователи", callback_data="adm:users")
    if user_id is not None and is_owner(user_id):
        kb.button(text="👑 Управление ролями", callback_data="adm:roles")
    kb.button(text="⬅️ Главное меню", callback_data="home")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
    if member.status in ("creator", "administrator", "member"):
        return True
    return bool(getattr(member, "is_member", False))


async def send_subscription_prompt(message: Message):
    await message.answer(
        "☾ <b>ЛОГОВО ЗНАНИЙ ИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔐 <b>Доступ пока закрыт</b>\n\n"
        "Чтобы открыть ИИ-чат, истории и инструменты, подпишись на наш канал, "
        "а затем нажми «Проверить доступ».\n\n"
        "<i>Твой путь в мир идей начинается здесь.</i>",
        reply_markup=subscription_menu(),
    )


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data or "").startswith("sub:"):
            return await handler(event, data)
        bot = data["bot"]
        try:
            subscribed = await is_subscribed(bot, user.id)
        except Exception:
            logging.exception("Could not check channel membership")
            if isinstance(event, Message):
                await event.answer("⚠️ Не удалось проверить подписку. Убедись, что бот остаётся администратором канала @logovoznani, и попробуй ещё раз.")
            else:
                await event.answer("Не удалось проверить подписку. Попробуй ещё раз позже.", show_alert=True)
            return
        if not subscribed:
            if isinstance(event, Message):
                await send_subscription_prompt(event)
            else:
                await event.answer("Сначала подпишись на канал @logovoznani.", show_alert=True)
            return
        return await handler(event, data)


dp.message.outer_middleware(SubscriptionMiddleware())
dp.callback_query.outer_middleware(SubscriptionMiddleware())


async def answer_with_ai(message: Message, prompt_text: str):
    user_id = message.from_user.id
    history = chat_history.setdefault(user_id, [])
    messages = [{"role": "system", "content": "Ты — дружелюбный русскоязычный помощник проекта «Логово Знаний ИИ». Помогай с учёбой, творчеством, программированием и созданием безопасных историй. Отвечай понятно и по делу."}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": prompt_text})
    answer, error = await ai_reply(messages, AI_API_KEY, AI_MODEL, AI_BASE_URL)
    if error:
        await message.answer(error)
        return
    history.extend([{"role": "user", "content": prompt_text}, {"role": "assistant", "content": answer}])
    chat_history[user_id] = history[-10:]
    await message.answer(html.escape(answer))


@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    log_user(user.id, user.username or "", user.full_name or "")
    role = get_role(user.id)
    role_label = {"owner": "👑 Владелец", "deputy": "💎 Заместитель", "admin": "🛡️ Администратор"}.get(role, "👤 Пользователь")
    await message.answer(
        f"☾ <b>ЛОГОВО ЗНАНИЙ ИИ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Привет, {user.mention_html()}!\n"
        f"<i>Статус:</i> {role_label}\n\n"
        "Здесь идеи превращаются в истории, а вопросы — в знания.\n\n"
        "<b>Выбери раздел:</b>",
        reply_markup=main_menu(user.id),
    )


@dp.callback_query(F.data == "sub:check")
async def check_subscription(call: CallbackQuery, bot: Bot):
    try:
        subscribed = await is_subscribed(bot, call.from_user.id)
    except Exception:
        logging.exception("Subscription re-check failed")
        await call.answer("Не получилось проверить. Убедись, что бот — администратор канала.", show_alert=True)
        return
    if not subscribed:
        await call.answer("Подписка пока не найдена. Подпишись и проверь ещё раз.", show_alert=True)
        return
    log_user(call.from_user.id, call.from_user.username or "", call.from_user.full_name or "")
    await call.message.edit_text("✅ <b>Подписка подтверждена!</b>\nДобро пожаловать в «Логово Знаний ИИ».", reply_markup=main_menu(call.from_user.id))
    await call.answer("Доступ открыт!")


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_staff(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к админ-панели.")
        return
    await message.answer(
        "🛡️ <b>Панель управления</b>\n\nНазначение ролей (только владелец):\n"
        "<code>/deputy TELEGRAM_ID</code> — заместитель\n"
        "<code>/grantadmin TELEGRAM_ID</code> — администратор\n"
        "<code>/removeadmin TELEGRAM_ID</code> — снять роль",
        reply_markup=admin_menu(message.from_user.id),
    )


@dp.message(Command("id"))
async def get_id(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    awaiting_ai.discard(call.from_user.id)
    await call.message.edit_text(
        "☾ <b>ЛОГОВО ЗНАНИЙ ИИ</b>\n━━━━━━━━━━━━━━━━━━\nВыбери раздел:",
        reply_markup=main_menu(call.from_user.id),
    )
    await call.answer()


@dp.callback_query(F.data == "adm:open")
async def open_admin_panel(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("⛔ Панель доступна только владельцу, заместителю и администраторам.", show_alert=True)
        return
    role = get_role(call.from_user.id)
    role_label = {"owner": "Владелец", "deputy": "Заместитель", "admin": "Администратор"}.get(role, "Сотрудник")
    text = (
        "🛡️ <b>ЦЕНТР УПРАВЛЕНИЯ</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<i>Ваш уровень доступа:</i> <b>{role_label}</b>\n\n"
        "Выберите раздел управления. Действия с ролями доступны только владельцу."
    )
    await call.message.answer(text, reply_markup=admin_menu(call.from_user.id))
    await call.answer()


@dp.callback_query(F.data == "story")
async def story_random(call: CallbackQuery):
    await call.message.answer("✧ <b>НОВАЯ ИСТОРИЯ</b>\n━━━━━━━━━━━━━━━━━━\n\n" + make_story())
    await call.answer()


@dp.callback_query(F.data.startswith("genre:"))
async def story_genre(call: CallbackQuery):
    genre = call.data.split(":", 1)[1]
    await call.message.answer("☾ <b>ИСТОРИЯ ПО ЖАНРУ</b>\n━━━━━━━━━━━━━━━━━━\n\n" + make_story(genre))
    await call.answer()


@dp.callback_query(F.data == "prompt")
async def prompt(call: CallbackQuery):
    await call.message.answer("✎ <b>ТВОЙ ТВОРЧЕСКИЙ ПРОМТ</b>\n━━━━━━━━━━━━━━━━━━\n\n" + make_prompt())
    await call.answer()


@dp.callback_query(F.data == "ai")
async def ai_info(call: CallbackQuery):
    awaiting_ai.add(call.from_user.id)
    await call.message.answer(
        "✦ <b>ИИ-ЧАТ АКТИВЕН</b>\n━━━━━━━━━━━━━━━━━━\n"
        "Напиши свой вопрос или идею — я помогу разобраться, придумать или создать.\n\n"
        "<i>Контекст диалога сохраняется, пока бот работает.</i>\n"
        "Для выхода нажми «Главное меню».",
    )
    await call.answer()


@dp.message(Command("ask"))
async def ask(message: Message):
    prompt_text = (message.text or "").partition(" ")[2].strip()
    if not prompt_text:
        await message.answer("Напиши вопрос после команды: <code>/ask твой вопрос</code>")
        return
    await answer_with_ai(message, prompt_text)


@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    role = get_role(call.from_user.id)
    label = {"owner": "👑 Владелец", "deputy": "💎 Заместитель", "admin": "🛡️ Администратор"}.get(role, "👤 Пользователь")
    await call.message.answer(
        "♙ <b>ТВОЙ ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"ID: <code>{call.from_user.id}</code>\nРоль: {label}"
    )
    await call.answer()


@dp.callback_query(F.data == "adm:stats")
async def admin_stats(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    data = stats()
    await call.message.answer(f"📊 <b>Статистика</b>\nПользователей: {data['users']}\nАктивных сегодня: {data['today']}")
    await call.answer()


@dp.callback_query(F.data == "adm:users")
async def admin_users(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    users = list_users(15)
    lines = [f"• <code>{u['user_id']}</code> — {html.escape(u['name'] or 'без имени')} ({html.escape(u['role'])})" for u in users]
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
async def deputy(message: Message):
    await role_action(message, "deputy")


@dp.message(Command("grantadmin"))
async def grantadmin(message: Message):
    await role_action(message, "admin")


@dp.message(Command("removeadmin"))
async def removeadmin(message: Message):
    await role_action(message, "remove")


@dp.message()
async def fallback(message: Message):
    user_id = message.from_user.id
    if user_id in awaiting_ai and message.text and not message.text.startswith("/"):
        await answer_with_ai(message, message.text.strip())
        return
    await message.answer("Выбери функцию в меню или нажми «ИИ-чат», чтобы начать диалог.", reply_markup=main_menu(user_id))


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to environment variables.")
    await init_db(OWNER_ID)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
