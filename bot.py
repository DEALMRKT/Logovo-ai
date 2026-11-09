import os
import logging
import html
import asyncio
import time
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, MessageEntity, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from storage import init_db, get_role, set_role, list_users, stats, log_user
from generators import make_prompt, ai_reply, generate_story

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@logovoznani").strip()
CHANNEL_URL = "https://t.me/" + CHANNEL_USERNAME.lstrip("@").split("/")[0]

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("logovo")
dp = Dispatcher()
awaiting_ai: set[int] = set()
chat_history: dict[int, list[dict[str, str]]] = defaultdict(list)
last_stories: dict[int, tuple[str, str]] = {}

# Sticker-set names from the user's selected t.me/addemoji links.
EMOJI_PACKS = (
    "blackrandom",
    "MagicRustEmoji",
    "LoveApphinov_by_TgEmodziBot",
    "Chernye666",
    "emojis_prem_blood",
)
CUSTOM_EMOJI_IDS: dict[str, str] = {}
CUSTOM_EMOJI_BY_ALT: dict[str, list[str]] = {}
CUSTOM_EMOJI_POOL: list[str] = []
_MEMBERSHIP_CACHE: dict[int, tuple[bool, float]] = {}
_MEMBERSHIP_CACHE_TTL = 120.0


def _normalise_emoji(value: str) -> str:
    return value.replace("\ufe0f", "").replace("\ufe0e", "").strip()


def add_premium_button(kb, text, *, callback_data=None, url=None):
    """Use a different Premium custom-emoji icon for each button in this keyboard."""
    first, separator, rest = text.partition(" ")
    normalised = _normalise_emoji(first)
    used = {
        getattr(button, "icon_custom_emoji_id", None)
        for row in kb.export()
        for button in row
        if getattr(button, "icon_custom_emoji_id", None)
    }
    candidates = CUSTOM_EMOJI_BY_ALT.get(normalised, [])
    emoji_id = next((item for item in candidates if item not in used), None)
    if emoji_id is None:
        emoji_id = next((item for item in CUSTOM_EMOJI_POOL if item not in used), None)

    button_text = (rest if separator else text) if emoji_id else text
    kwargs = {"text": button_text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    try:
        kb.add(InlineKeyboardButton(**kwargs))
    except (TypeError, ValueError):
        kwargs.pop("icon_custom_emoji_id", None)
        kwargs["text"] = text
        kb.add(InlineKeyboardButton(**kwargs))


def custom_emoji(key: str, fallback: str) -> str:
    emoji_id = CUSTOM_EMOJI_IDS.get(key)
    if not emoji_id:
        return fallback
    return f'<tg-emoji emoji-id="{html.escape(str(emoji_id), quote=True)}">{fallback}</tg-emoji>'


async def load_custom_emojis(bot: Bot) -> None:
    """Load emoji packs in parallel with strict timeouts; webhook startup must not wait minutes."""
    CUSTOM_EMOJI_IDS.clear()
    CUSTOM_EMOJI_BY_ALT.clear()
    CUSTOM_EMOJI_POOL.clear()
    by_alt: dict[str, list[tuple[str, str]]] = {}

    async def fetch_pack(pack_name: str):
        try:
            pack = await asyncio.wait_for(bot.get_sticker_set(name=pack_name), timeout=5.0)
            entries = []
            for sticker in pack.stickers:
                alt = getattr(sticker, "emoji", None)
                emoji_id = getattr(sticker, "custom_emoji_id", None)
                if alt and emoji_id:
                    entries.append((_normalise_emoji(alt), str(emoji_id)))
            log.info("Emoji set loaded: %s (%d custom emoji)", pack_name, len(entries))
            return pack_name, entries
        except asyncio.TimeoutError:
            log.warning("Timed out loading emoji set %s", pack_name)
        except Exception as exc:
            log.warning("Could not load emoji set %s: %s", pack_name, exc)
        return pack_name, []

    results = await asyncio.gather(*(fetch_pack(name) for name in EMOJI_PACKS))
    for pack_name, entries in results:
        for alt_key, eid in entries:
            by_alt.setdefault(alt_key, []).append((pack_name, eid))
            if eid not in CUSTOM_EMOJI_POOL:
                CUSTOM_EMOJI_POOL.append(eid)

    for alt, entries in by_alt.items():
        CUSTOM_EMOJI_BY_ALT[alt] = list(dict.fromkeys(eid for _, eid in entries))

    choices = {
        "moon": ("🌑", "🌙", "🌘"), "demon": ("😈", "👿"),
        "skull": ("💀",), "bat": ("🦇",), "black_heart": ("🖤",),
        "crown": ("👑",), "star": ("⭐", "🌟"), "lightning": ("⚡",),
        "sparkle": ("✨", "💫"), "eye": ("👁️", "👁", "👀"),
    }
    preferred = {
        "moon": ("emojis_prem_blood", "blackrandom", "Chernye666"),
        "demon": ("MagicRustEmoji", "blackrandom", "Chernye666"),
        "skull": ("emojis_prem_blood", "blackrandom", "MagicRustEmoji"),
        "bat": ("emojis_prem_blood", "Chernye666", "blackrandom"),
        "black_heart": ("emojis_prem_blood", "Chernye666", "blackrandom"),
        "crown": ("LoveApphinov_by_TgEmodziBot", "MagicRustEmoji"),
        "star": ("LoveApphinov_by_TgEmodziBot", "MagicRustEmoji"),
        "lightning": ("LoveApphinov_by_TgEmodziBot", "MagicRustEmoji"),
        "sparkle": ("LoveApphinov_by_TgEmodziBot", "blackrandom"),
        "eye": ("MagicRustEmoji", "Chernye666", "blackrandom"),
    }
    for key, alts in choices.items():
        for pack_name in preferred[key]:
            found = next((eid for alt in alts for source, eid in by_alt.get(_normalise_emoji(alt), []) if source == pack_name), None)
            if found:
                CUSTOM_EMOJI_IDS[key] = found
                break
    log.info("Premium emoji loaded: %d unique icons; semantic keys: %s", len(CUSTOM_EMOJI_POOL), ", ".join(CUSTOM_EMOJI_IDS) or "none")


def is_staff(user_id: int) -> bool:
    return get_role(user_id) in ("owner", "deputy", "admin")


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID and OWNER_ID != 0


def main_menu(user_id: int | None = None):
    kb = InlineKeyboardBuilder()
    buttons = [
        ("🧠 ИИ-ассистент", "ai"),
        ("📜 Новая история", "story"),
        ("🌑 БЛЭКАУТ", "genre:blackout"),
        ("🧟 Зомби-апокалипсис", "genre:zombie"),
        ("🔎 Детектив", "genre:detective"),
        ("🏕️ Выживание", "genre:survival"),
        ("⚡ Создать промпт", "prompt"),
        ("👤 Мой профиль", "profile"),
    ]
    for label, data in buttons:
        add_premium_button(kb, label, callback_data=data)
    kb.adjust(2, 2, 2, 2)
    if user_id is not None and is_staff(user_id):
        add_premium_button(kb, "🛡️ Панель администратора", callback_data="adm:open")
        kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


def subscription_menu():
    kb = InlineKeyboardBuilder()
    add_premium_button(kb, "✦ Подписаться на канал", url=CHANNEL_URL)
    add_premium_button(kb, "✓ Проверить доступ", callback_data="sub:check")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu(user_id: int):
    kb = InlineKeyboardBuilder()
    add_premium_button(kb, "📊 Статистика", callback_data="adm:stats")
    add_premium_button(kb, "👥 Пользователи", callback_data="adm:users")
    if is_owner(user_id):
        add_premium_button(kb, "👑 Управление ролями", callback_data="adm:roles")
    add_premium_button(kb, "⬅️ Главное меню", callback_data="home")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Cache successful/negative membership checks briefly and cap Telegram API wait time."""
    now = time.monotonic()
    cached = _MEMBERSHIP_CACHE.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
    try:
        member = await asyncio.wait_for(bot.get_chat_member(CHANNEL_USERNAME, user_id), timeout=8.0)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("Telegram getChatMember timed out after 8 seconds") from exc
    subscribed = member.status in ("creator", "administrator", "member") or bool(getattr(member, "is_member", False))
    # Cache only positive checks. A user who just subscribed must pass immediately
    # when pressing the "Проверить доступ" button.
    if subscribed:
        _MEMBERSHIP_CACHE[user_id] = (True, now + _MEMBERSHIP_CACHE_TTL)
    else:
        _MEMBERSHIP_CACHE.pop(user_id, None)
    return subscribed


async def send_subscription_prompt(message: Message):
    await message.answer(
        f"{custom_emoji('moon', '🌑')} <b>ЛОГОВО ЗНАНИЙ ИИ</b> {custom_emoji('demon', '😈')}\n"
        "━━━━━━━━━━━━━━━━━━\n🔐 <b>Доступ пока закрыт</b>\n\n"
        f"Подпишись на канал {html.escape(CHANNEL_USERNAME)}, затем нажми «Проверить доступ».\n\n"
        "<i>Твой путь в мир идей начинается здесь.</i>",
        reply_markup=subscription_menu(),
    )


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or (isinstance(event, CallbackQuery) and (event.data or "").startswith("sub:")):
            return await handler(event, data)
        try:
            subscribed = await is_subscribed(data["bot"], user.id)
        except Exception:
            log.exception("Channel membership check failed")
            msg = "Не удалось проверить подписку. Убедись, что бот — администратор канала @logovoznani."
            if isinstance(event, Message):
                await event.answer("⚠️ " + msg)
            else:
                await event.answer(msg, show_alert=True)
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
    history = chat_history[user_id]
    system = (
        "Ты — дружелюбный русскоязычный помощник проекта «Логово Знаний ИИ». "
        "Помогай с учёбой, творчеством и программированием. Отвечай ясно, честно и по делу. "
        "Если не уверен — прямо скажи об этом."
    )
    messages = [{"role": "system", "content": system}, *history[-10:], {"role": "user", "content": prompt_text}]
    answer, error = await ai_reply(messages, GROQ_API_KEY, GROQ_MODEL)
    if error:
        await message.answer(error)
        return
    history.extend([{"role": "user", "content": prompt_text}, {"role": "assistant", "content": answer}])
    chat_history[user_id] = history[-12:]
    await message.answer(html.escape(answer[:3900]))


async def send_story(message: Message, genre: str):
    labels = {"zombie": "ЗОМБИ-АПОКАЛИПСИС", "blackout": "БЛЭКАУТ", "detective": "ДЕТЕКТИВ", "survival": "ВЫЖИВАНИЕ"}
    await message.answer("✦ <b>Создаю уникальный сюжет…</b>")
    story, error = await generate_story(genre, GROQ_API_KEY, GROQ_MODEL)
    if error:
        await message.answer(error)
        return
    last_stories[message.from_user.id] = (genre, story)
    kb = InlineKeyboardBuilder()
    add_premium_button(kb, "➕ Продолжить историю", callback_data=f"story:continue:{genre}")
    add_premium_button(kb, "🔄 Новый сюжет", callback_data=f"genre:{genre}")
    add_premium_button(kb, "⬅️ В меню", callback_data="home")
    kb.adjust(1)
    heading = f"{custom_emoji('moon', '🌑')} <b>{labels.get(genre, 'НОВАЯ ИСТОРИЯ')}</b> {custom_emoji('sparkle', '✨')}\n━━━━━━━━━━━━━━━━━━\n\n"
    await message.answer(heading + html.escape(story[:3800]), reply_markup=kb.as_markup())


@dp.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    log_user(user.id, user.username or "", user.full_name or "")
    role = get_role(user.id)
    role_label = {"owner": "👑 Владелец", "deputy": "💎 Заместитель", "admin": "🛡️ Администратор"}.get(role, "👤 Пользователь")
    await message.answer(
        f"{custom_emoji('moon', '🌑')} <b>ЛОГОВО ЗНАНИЙ ИИ</b> {custom_emoji('demon', '😈')}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{custom_emoji('sparkle', '✨')} Привет, {user.mention_html()}!\n"
        f"<i>Статус:</i> {role_label}\n\n"
        "Здесь идеи превращаются в истории, а вопросы — в знания.\n\n<b>Выбери раздел:</b>",
        reply_markup=main_menu(user.id),
    )


@dp.callback_query(F.data == "sub:check")
async def check_subscription(call: CallbackQuery, bot: Bot):
    _MEMBERSHIP_CACHE.pop(call.from_user.id, None)
    try:
        subscribed = await is_subscribed(bot, call.from_user.id)
    except Exception:
        log.exception("Subscription re-check failed")
        await call.answer("Не получилось проверить. Убедись, что бот — администратор канала.", show_alert=True)
        return
    if not subscribed:
        await call.answer("Подписка пока не найдена. Подпишись и проверь ещё раз.", show_alert=True)
        return
    user = call.from_user
    log_user(user.id, user.username or "", user.full_name or "")
    await call.message.edit_text("✅ <b>Подписка подтверждена!</b>\nДобро пожаловать в «Логово Знаний ИИ».", reply_markup=main_menu(user.id))
    await call.answer("Доступ открыт!")


@dp.message(Command("id"))
async def get_id(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("clear"))
async def clear_chat(message: Message):
    chat_history.pop(message.from_user.id, None)
    await message.answer("🧹 Память текущего ИИ-диалога очищена.")


@dp.message(Command("emojiid"))
async def emoji_ids_command(message: Message):
    target = message.reply_to_message or message
    entities = target.entities or []
    found = [e.custom_emoji_id for e in entities if e.type == "custom_emoji" and e.custom_emoji_id]
    if not found:
        await message.answer("Отправь Premium Emoji отдельным сообщением или ответь командой /emojiid на сообщение с ним.")
        return
    await message.answer("<b>Найденные custom_emoji_id:</b>\n" + "\n".join(f"<code>{html.escape(str(eid))}</code>" for eid in found))


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_staff(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к админ-панели.")
        return
    await message.answer("🛡️ <b>ЦЕНТР УПРАВЛЕНИЯ</b>\nВыбери раздел:", reply_markup=admin_menu(message.from_user.id))


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    awaiting_ai.discard(call.from_user.id)
    await call.message.answer("☾ <b>ЛОГОВО ЗНАНИЙ ИИ</b>\n━━━━━━━━━━━━━━━━━━\nВыбери раздел:", reply_markup=main_menu(call.from_user.id))
    await call.answer()


@dp.callback_query(F.data == "adm:open")
async def open_admin_panel(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("⛔ Нет доступа.", show_alert=True)
        return
    await call.message.answer(f"{custom_emoji('crown', '👑')} <b>ЦЕНТР УПРАВЛЕНИЯ</b>\n━━━━━━━━━━━━━━━━━━\nДоступ: <b>{get_role(call.from_user.id)}</b>", reply_markup=admin_menu(call.from_user.id))
    await call.answer()


@dp.callback_query(F.data == "adm:roles")
async def admin_roles(call: CallbackQuery):
    if not is_owner(call.from_user.id):
        await call.answer("Только владелец может управлять ролями.", show_alert=True)
        return
    await call.message.answer("👑 <b>УПРАВЛЕНИЕ РОЛЯМИ</b>\n/deputy ID — назначить заместителя\n/grantadmin ID — назначить администратора\n/removeadmin ID — снять роль")
    await call.answer()


@dp.callback_query(F.data == "story")
async def story_random(call: CallbackQuery):
    import random
    await call.answer()
    await send_story(call.message, random.choice(["blackout", "zombie", "detective", "survival"]))


@dp.callback_query(F.data.startswith("genre:"))
async def story_genre(call: CallbackQuery):
    genre = call.data.split(":", 1)[1]
    if genre not in ("blackout", "zombie", "detective", "survival"):
        await call.answer("Неизвестный жанр", show_alert=True)
        return
    await call.answer()
    await send_story(call.message, genre)


@dp.callback_query(F.data.startswith("story:continue:"))
async def continue_story(call: CallbackQuery):
    genre = call.data.rsplit(":", 1)[-1]
    previous = last_stories.get(call.from_user.id)
    if not previous or previous[0] != genre:
        await call.answer("Сначала создай новую историю.", show_alert=True)
        return
    await call.answer()
    await call.message.answer("✦ <b>Продолжаю сюжет…</b>")
    continuation, error = await generate_story(genre, GROQ_API_KEY, GROQ_MODEL, previous[1])
    if error:
        await call.message.answer(error)
        return
    last_stories[call.from_user.id] = (genre, previous[1] + "\n\n" + continuation)
    kb = InlineKeyboardBuilder()
    add_premium_button(kb, "➕ Продолжить ещё", callback_data=f"story:continue:{genre}")
    add_premium_button(kb, "🔄 Новый сюжет", callback_data=f"genre:{genre}")
    kb.adjust(1)
    await call.message.answer(html.escape(continuation[:3800]), reply_markup=kb.as_markup())


@dp.callback_query(F.data == "prompt")
async def prompt(call: CallbackQuery):
    await call.message.answer(f"{custom_emoji('star', '⭐')} <b>ТВОЙ ТВОРЧЕСКИЙ ПРОМТ</b>\n━━━━━━━━━━━━━━━━━━\n\n<code>{html.escape(make_prompt())}</code>")
    await call.answer()


@dp.callback_query(F.data == "ai")
async def ai_info(call: CallbackQuery):
    awaiting_ai.add(call.from_user.id)
    kb = InlineKeyboardBuilder()
    add_premium_button(kb, "🧹 Очистить память", callback_data="ai:clear")
    add_premium_button(kb, "⬅️ Главное меню", callback_data="home")
    kb.adjust(1)
    await call.message.answer(
        f"{custom_emoji('sparkle', '✨')} <b>ИИ-ЧАТ АКТИВЕН</b> {custom_emoji('eye', '👁️')}\n━━━━━━━━━━━━━━━━━━\n"
        "Напиши вопрос или идею — я помогу разобраться, придумать или создать.\n\n"
        "Контекст диалога сохраняется, пока бот работает. Команда /clear тоже очищает память.",
        reply_markup=kb.as_markup(),
    )
    await call.answer()


@dp.callback_query(F.data == "ai:clear")
async def clear_chat_button(call: CallbackQuery):
    chat_history.pop(call.from_user.id, None)
    await call.answer("Память диалога очищена.", show_alert=True)


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
    username = f"@{html.escape(call.from_user.username)}" if call.from_user.username else "не указан"
    await call.message.answer(
        f"{custom_emoji('crown', '👑')} <b>ТВОЙ ПРОФИЛЬ</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Имя: {html.escape(call.from_user.full_name)}\nНик: {username}\n"
        f"ID: <code>{call.from_user.id}</code>\nРоль: {label}\n\n"
        f"ИИ-модель: <code>{html.escape(GROQ_MODEL)}</code>\nПровайдер: <code>Groq</code>"
    )
    await call.answer()


@dp.callback_query(F.data == "adm:stats")
async def admin_stats(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    data = stats()
    await call.message.answer(f"📊 <b>СТАТИСТИКА</b>\nПользователей: <b>{data['users']}</b>\nАктивных сегодня: <b>{data['today']}</b>")
    await call.answer()


@dp.callback_query(F.data == "adm:users")
async def admin_users(call: CallbackQuery):
    if not is_staff(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    users = list_users(15)
    lines = [f"• <code>{u['user_id']}</code> — {html.escape(u['name'] or 'без имени')} ({html.escape(u['role'])})" for u in users]
    await call.message.answer("👥 <b>ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ</b>\n" + ("\n".join(lines) if lines else "Пока пусто"))
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
    # If a custom emoji is sent directly, show its Telegram ID for easy setup.
    entities = message.entities or []
    emoji_ids = [e.custom_emoji_id for e in entities if e.type == "custom_emoji" and e.custom_emoji_id]
    if emoji_ids:
        await message.answer("<b>Premium Emoji ID:</b>\n" + "\n".join(f"<code>{html.escape(str(eid))}</code>" for eid in emoji_ids))
        return
    user_id = message.from_user.id
    if user_id in awaiting_ai and message.text and not message.text.startswith("/"):
        await answer_with_ai(message, message.text.strip())
        return
    await message.answer("Выбери функцию в меню или нажми «ИИ-чат», чтобы начать диалог.", reply_markup=main_menu(user_id))


async def startup(bot: Bot):
    # Keep startup fast: webhook must be registered before optional emoji-pack lookups.
    await init_db(OWNER_ID)

