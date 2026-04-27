import asyncio
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# =========================================================
# DIAMOND REPUTATION BOT — ONE FILE ARCHITECTURE
# GitHub + Railway ready
# =========================================================

# Можно оставить токен внутри файла, но безопаснее на Railway задать BOT_TOKEN в Variables.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8452616761:AAE7E-cadqGwikNwn44b-evrzdSCdFsN8Zw").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "626387429") or 626387429)
DB_PATH = os.getenv("DB_PATH", "reputation_bot.db").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

router = Router()
dp = Dispatcher()
dp.include_router(router)

USERNAME_RE = re.compile(r"@([A-Za-z0-9_]{5,32})")
ID_RE = re.compile(r"(?:id|айди|uid)?\s*(\d{5,20})", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_db_parent():
    db_file = Path(DB_PATH)
    if db_file.parent and str(db_file.parent) not in ("", "."):
        db_file.parent.mkdir(parents=True, exist_ok=True)


def db_connect():
    ensure_db_parent()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db_connect()) as conn, conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            current_username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            is_bot INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_seen_chat_id INTEGER,
            last_seen_chat_title TEXT,
            messages_seen INTEGER DEFAULT 0,
            reputation_score INTEGER DEFAULT 0
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS username_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            changed_at TEXT NOT NULL,
            chat_id INTEGER,
            chat_title TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            username TEXT,
            type TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            messages_seen INTEGER DEFAULT 0
        )
        """)


        conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            channel_title TEXT,
            channel_username TEXT,
            message_id INTEGER,
            sender_chat_id INTEGER,
            sender_chat_title TEXT,
            author_signature TEXT,
            text_preview TEXT,
            seen_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS reputation_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER,
            target_query TEXT NOT NULL,
            target_username_at_request TEXT,
            reporter_user_id INTEGER NOT NULL,
            reporter_username TEXT,
            chat_id INTEGER NOT NULL,
            chat_title TEXT,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            proof_type TEXT,
            proof_file_id TEXT,
            proof_message_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_id INTEGER,
            admin_comment TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS reputation_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            reporter_user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT NOT NULL,
            proof_type TEXT,
            proof_file_id TEXT,
            created_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(current_username)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_username_history_username ON username_history(username)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rep_req_status ON reputation_requests(status)
        """)


def html_escape(text: Optional[str]) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_username(username: Optional[str]) -> str:
    return f"@{username}" if username else "без username"


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def upsert_chat_from_message(message: Message):
    chat = message.chat
    now = utc_now()
    title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or "ЛС"
    username = getattr(chat, "username", None)

    with closing(db_connect()) as conn, conn:
        row = conn.execute("SELECT chat_id FROM chats WHERE chat_id=?", (chat.id,)).fetchone()
        if row:
            conn.execute("""
                UPDATE chats
                SET title=?, username=?, type=?, last_seen_at=?, messages_seen=messages_seen+1
                WHERE chat_id=?
            """, (title, username, chat.type, now, chat.id))
        else:
            conn.execute("""
                INSERT INTO chats(chat_id, title, username, type, first_seen_at, last_seen_at, messages_seen)
                VALUES(?, ?, ?, ?, ?, ?, 1)
            """, (chat.id, title, username, chat.type, now, now))


def track_channel_post(message: Message):
    """
    Каналы работают иначе, чем группы. В обычном посте канала Telegram чаще всего
    НЕ передает личный from_user админа, поэтому бот сохраняет канал, sender_chat,
    подпись автора и текст-превью. Если from_user пришел — сохраняем его как пользователя.
    """
    upsert_chat_from_message(message)
    chat = message.chat
    now = utc_now()
    channel_title = getattr(chat, "title", None) or "Канал"
    channel_username = getattr(chat, "username", None)
    sender_chat = getattr(message, "sender_chat", None)
    sender_chat_id = getattr(sender_chat, "id", None) if sender_chat else None
    sender_chat_title = getattr(sender_chat, "title", None) if sender_chat else None
    author_signature = getattr(message, "author_signature", None)
    text_raw = message.text or message.caption or ""
    text_preview = text_raw[:500]

    with closing(db_connect()) as conn, conn:
        conn.execute("""
            INSERT INTO channel_posts(
                channel_id, channel_title, channel_username, message_id,
                sender_chat_id, sender_chat_title, author_signature, text_preview, seen_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat.id, channel_title, channel_username, message.message_id,
            sender_chat_id, sender_chat_title, author_signature, text_preview, now
        ))

    if message.from_user:
        return track_user(message.from_user, chat.id, channel_title)
    return None


def track_user(user, chat_id: Optional[int] = None, chat_title: Optional[str] = None) -> Optional[dict]:
    if not user:
        return None

    now = utc_now()
    username = user.username.lower() if getattr(user, "username", None) else None
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    full_name = getattr(user, "full_name", None) or ""
    is_bot_v = 1 if getattr(user, "is_bot", False) else 0

    with closing(db_connect()) as conn, conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user.id,)).fetchone()
        if not row:
            conn.execute("""
                INSERT INTO users(
                    user_id, current_username, first_name, last_name, full_name, is_bot,
                    first_seen_at, last_seen_at, last_seen_chat_id, last_seen_chat_title, messages_seen, reputation_score
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
            """, (user.id, username, first_name, last_name, full_name, is_bot_v, now, now, chat_id, chat_title))
            conn.execute("""
                INSERT INTO username_history(user_id, username, changed_at, chat_id, chat_title)
                VALUES(?, ?, ?, ?, ?)
            """, (user.id, username, now, chat_id, chat_title))
            logging.info("NEW USER | id=%s username=%s name=%s", user.id, username, full_name)
            return {"new_user": True, "changed": False, "old": None, "new": username}

        old_username = row["current_username"]
        conn.execute("""
            UPDATE users
            SET current_username=?, first_name=?, last_name=?, full_name=?, is_bot=?,
                last_seen_at=?, last_seen_chat_id=?, last_seen_chat_title=?, messages_seen=messages_seen+1
            WHERE user_id=?
        """, (username, first_name, last_name, full_name, is_bot_v, now, chat_id, chat_title, user.id))

        if old_username != username:
            conn.execute("""
                INSERT INTO username_history(user_id, username, changed_at, chat_id, chat_title)
                VALUES(?, ?, ?, ?, ?)
            """, (user.id, username, now, chat_id, chat_title))
            logging.info("USERNAME CHANGE | id=%s %s -> %s", user.id, old_username, username)
            return {"new_user": False, "changed": True, "old": old_username, "new": username}

        return {"new_user": False, "changed": False, "old": old_username, "new": username}


def track_message_people(message: Message):
    upsert_chat_from_message(message)
    chat_title = getattr(message.chat, "title", None) or "ЛС"
    result = track_user(message.from_user, message.chat.id, chat_title) if message.from_user else None

    if message.reply_to_message and message.reply_to_message.from_user:
        track_user(message.reply_to_message.from_user, message.chat.id, chat_title)

    if message.new_chat_members:
        for member in message.new_chat_members:
            track_user(member, message.chat.id, chat_title)

    if message.left_chat_member:
        track_user(message.left_chat_member, message.chat.id, chat_title)

    return result


def find_user_by_query(query: str) -> Optional[sqlite3.Row]:
    q = query.strip()
    if not q:
        return None

    # ID
    if q.isdigit():
        with closing(db_connect()) as conn:
            return conn.execute("SELECT * FROM users WHERE user_id=?", (int(q),)).fetchone()

    # @username
    m = USERNAME_RE.search(q)
    username = None
    if m:
        username = m.group(1).lower()
    elif q.startswith("@"):
        username = q[1:].lower()
    else:
        username = q.lower()

    username = username.strip()
    if not username:
        return None

    with closing(db_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE current_username=?", (username,)).fetchone()
        if row:
            return row
        return conn.execute("""
            SELECT u.*
            FROM username_history h
            JOIN users u ON u.user_id=h.user_id
            WHERE h.username=?
            ORDER BY h.id DESC
            LIMIT 1
        """, (username,)).fetchone()


def extract_target_and_reason(text: str, prefix: str) -> Tuple[Optional[str], str]:
    raw = (text or "").strip()
    lower = raw.lower()
    p = prefix.lower()
    if lower.startswith(p):
        rest = raw[len(prefix):].strip()
    else:
        rest = raw

    if not rest:
        return None, ""

    parts = rest.split(maxsplit=1)
    target = parts[0].strip() if parts else None
    reason = parts[1].strip() if len(parts) > 1 else ""
    return target, reason


def get_proof_from_message(message: Message) -> Tuple[Optional[str], Optional[str]]:
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.document:
        return "document", message.document.file_id
    if message.video:
        return "video", message.video.file_id
    if message.animation:
        return "animation", message.animation.file_id
    return None, None


def create_rep_request(
    target_user_id: Optional[int],
    target_query: str,
    target_username_at_request: Optional[str],
    reporter_user_id: int,
    reporter_username: Optional[str],
    chat_id: int,
    chat_title: str,
    delta: int,
    reason: str,
    proof_type: Optional[str],
    proof_file_id: Optional[str],
    proof_message_id: Optional[int],
) -> int:
    with closing(db_connect()) as conn, conn:
        cur = conn.execute("""
            INSERT INTO reputation_requests(
                target_user_id, target_query, target_username_at_request,
                reporter_user_id, reporter_username, chat_id, chat_title, delta,
                reason, proof_type, proof_file_id, proof_message_id,
                status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            target_user_id, target_query, target_username_at_request,
            reporter_user_id, reporter_username, chat_id, chat_title, delta,
            reason, proof_type, proof_file_id, proof_message_id, utc_now()
        ))
        return cur.lastrowid


def get_rep_request(req_id: int) -> Optional[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("SELECT * FROM reputation_requests WHERE id=?", (req_id,)).fetchone()


def approve_request(req_id: int, admin_id: int) -> Tuple[bool, str]:
    with closing(db_connect()) as conn, conn:
        req = conn.execute("SELECT * FROM reputation_requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            return False, "Заявка не найдена."
        if req["status"] != "pending":
            return False, f"Заявка уже обработана: {req['status']}"
        if not req["target_user_id"]:
            return False, "Нельзя одобрить: цель не найдена в базе. Пусть пользователь сначала попадется боту или делай репорт reply-сообщением."

        conn.execute("""
            UPDATE reputation_requests
            SET status='approved', admin_id=?, decided_at=?
            WHERE id=?
        """, (admin_id, utc_now(), req_id))

        conn.execute("""
            INSERT INTO reputation_entries(
                request_id, target_user_id, reporter_user_id, delta, reason,
                proof_type, proof_file_id, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req_id, req["target_user_id"], req["reporter_user_id"], req["delta"], req["reason"],
            req["proof_type"], req["proof_file_id"], utc_now()
        ))

        conn.execute("""
            UPDATE users
            SET reputation_score = reputation_score + ?
            WHERE user_id=?
        """, (req["delta"], req["target_user_id"]))
        return True, "Заявка одобрена. Репутация обновлена."


def reject_request(req_id: int, admin_id: int) -> Tuple[bool, str]:
    with closing(db_connect()) as conn, conn:
        req = conn.execute("SELECT * FROM reputation_requests WHERE id=?", (req_id,)).fetchone()
        if not req:
            return False, "Заявка не найдена."
        if req["status"] != "pending":
            return False, f"Заявка уже обработана: {req['status']}"
        conn.execute("""
            UPDATE reputation_requests
            SET status='rejected', admin_id=?, decided_at=?
            WHERE id=?
        """, (admin_id, utc_now(), req_id))
        return True, "Заявка отклонена."


def pending_requests(limit: int = 10) -> List[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT * FROM reputation_requests
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT ?
        """, (limit,)).fetchall()


def user_card_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def reputation_entries(user_id: int, limit: int = 10) -> List[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT * FROM reputation_entries
            WHERE target_user_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()


def username_history(user_id: int, limit: int = 20) -> List[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT * FROM username_history
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()


def stats_full_text() -> str:
    with closing(db_connect()) as conn:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        chats = conn.execute("SELECT COUNT(*) c FROM chats").fetchone()["c"]
        req_all = conn.execute("SELECT COUNT(*) c FROM reputation_requests").fetchone()["c"]
        req_pending = conn.execute("SELECT COUNT(*) c FROM reputation_requests WHERE status='pending'").fetchone()["c"]
        req_approved = conn.execute("SELECT COUNT(*) c FROM reputation_requests WHERE status='approved'").fetchone()["c"]
        req_rejected = conn.execute("SELECT COUNT(*) c FROM reputation_requests WHERE status='rejected'").fetchone()["c"]
        changes = conn.execute("SELECT COUNT(*) c FROM username_history").fetchone()["c"]
        channel_posts = conn.execute("SELECT COUNT(*) c FROM channel_posts").fetchone()["c"]
        plus_entries = conn.execute("SELECT COUNT(*) c FROM reputation_entries WHERE delta > 0").fetchone()["c"]
        minus_entries = conn.execute("SELECT COUNT(*) c FROM reputation_entries WHERE delta < 0").fetchone()["c"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        active_today = conn.execute("SELECT COUNT(*) c FROM users WHERE last_seen_at LIKE ?", (today + "%",)).fetchone()["c"]
        top_plus = conn.execute("SELECT * FROM users ORDER BY reputation_score DESC LIMIT 5").fetchall()
        top_minus = conn.execute("SELECT * FROM users ORDER BY reputation_score ASC LIMIT 5").fetchall()

    def top_lines(rows):
        out = []
        for u in rows:
            name = html_escape(u["full_name"] or u["first_name"] or "Без имени")
            out.append(f"• <b>{u['reputation_score']}</b> — {name} / {fmt_username(u['current_username'])} / <code>{u['user_id']}</code>")
        return "\n".join(out) if out else "—"

    return (
        "📊 <b>Статистика Reputation Bot</b>\n\n"
        f"👥 Пользователей в базе: <b>{users}</b>\n"
        f"💬 Чатов/каналов замечено: <b>{chats}</b>\n"
        f"🟢 Активных сегодня: <b>{active_today}</b>\n"
        f"🔁 Записей истории username: <b>{changes}</b>\n"
        f"📣 Постов каналов записано: <b>{channel_posts}</b>\n\n"
        f"📝 Всего заявок: <b>{req_all}</b>\n"
        f"⏳ На проверке: <b>{req_pending}</b>\n"
        f"✅ Одобрено: <b>{req_approved}</b>\n"
        f"❌ Отклонено: <b>{req_rejected}</b>\n\n"
        f"➕ Плюсов репутации: <b>{plus_entries}</b>\n"
        f"➖ Минусов репутации: <b>{minus_entries}</b>\n\n"
        "🏆 <b>Топ плюс:</b>\n" + top_lines(top_plus) + "\n\n"
        "⚠️ <b>Топ минус:</b>\n" + top_lines(top_minus)
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Заявки", callback_data="admin:pending:0"), InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Последние пользователи", callback_data="admin:users"), InlineKeyboardButton(text="🔁 Смены юзов", callback_data="admin:changes")],
        [InlineKeyboardButton(text="📣 Каналы", callback_data="admin:channels")],
    ])


def request_keyboard(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"rep:approve:{req_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rep:reject:{req_id}")]
    ])


def pending_keyboard(rows: List[sqlite3.Row]) -> InlineKeyboardMarkup:
    buttons = []
    for r in rows:
        sign = "+" if r["delta"] > 0 else "-"
        buttons.append([InlineKeyboardButton(text=f"{sign} реп #{r['id']} — {r['target_query']}", callback_data=f"rep:view:{r['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_request(req: sqlite3.Row) -> str:
    sign = "➕ +реп" if req["delta"] > 0 else "➖ -реп"
    return (
        f"📝 <b>Заявка #{req['id']}</b>\n"
        f"Тип: <b>{sign}</b>\n"
        f"Статус: <b>{req['status']}</b>\n\n"
        f"🎯 Цель: <b>{html_escape(req['target_query'])}</b>\n"
        f"Target ID: <code>{req['target_user_id'] or 'не найден в базе'}</code>\n"
        f"Юзер на момент заявки: <b>{fmt_username(req['target_username_at_request'])}</b>\n\n"
        f"👤 Кто подал: <code>{req['reporter_user_id']}</code> / {fmt_username(req['reporter_username'])}\n"
        f"💬 Чат: {html_escape(req['chat_title'])} / <code>{req['chat_id']}</code>\n"
        f"🕒 Создано: <code>{req['created_at']}</code>\n\n"
        f"📌 <b>Причина:</b>\n{html_escape(req['reason'])}\n\n"
        f"🖼 Доказательство: <b>{req['proof_type'] or 'нет'}</b>"
    )


async def send_request_to_admin(bot: Bot, req_id: int):
    req = get_rep_request(req_id)
    if not req:
        return
    text = format_request(req)
    try:
        if req["proof_type"] == "photo" and req["proof_file_id"]:
            await bot.send_photo(ADMIN_ID, req["proof_file_id"], caption=text, reply_markup=request_keyboard(req_id))
        elif req["proof_type"] == "document" and req["proof_file_id"]:
            await bot.send_document(ADMIN_ID, req["proof_file_id"], caption=text, reply_markup=request_keyboard(req_id))
        elif req["proof_type"] == "video" and req["proof_file_id"]:
            await bot.send_video(ADMIN_ID, req["proof_file_id"], caption=text, reply_markup=request_keyboard(req_id))
        else:
            await bot.send_message(ADMIN_ID, text, reply_markup=request_keyboard(req_id))
    except Exception as e:
        logging.warning("send_request_to_admin failed: %s", e)


async def notify_admin_username_change(bot: Bot, message: Message, result: Optional[dict]):
    if not result or not result.get("changed"):
        return
    user = message.from_user
    if not user:
        return
    old_u = fmt_username(result.get("old"))
    new_u = fmt_username(result.get("new"))
    chat_title = getattr(message.chat, "title", None) or "ЛС"
    try:
        await bot.send_message(
            ADMIN_ID,
            "🔁 <b>Смена username</b>\n"
            f"Пользователь: <b>{html_escape(user.full_name)}</b>\n"
            f"ID: <code>{user.id}</code>\n"
            f"Было: <b>{old_u}</b>\n"
            f"Стало: <b>{new_u}</b>\n"
            f"Где замечен: {html_escape(chat_title)} / <code>{message.chat.id}</code>"
        )
    except Exception as e:
        logging.warning("username change notify failed: %s", e)


# =========================================================
# CHANNEL POSTS
# =========================================================

@router.channel_post()
async def channel_post_router(message: Message, bot: Bot):
    result = track_channel_post(message)
    await notify_admin_username_change(bot, message, result)


@router.edited_channel_post()
async def edited_channel_post_router(message: Message, bot: Bot):
    result = track_channel_post(message)
    await notify_admin_username_change(bot, message, result)


# =========================================================
# COMMANDS
# =========================================================

@router.message(CommandStart())
async def cmd_start(message: Message):
    track_message_people(message)
    await message.answer(
        "💎 <b>Diamond Reputation Bot</b>\n\n"
        "Бот записывает пользователей, которых видит в чатах, хранит ID и историю username.\n"
        "Если добавить бота админом в канал — он также будет записывать канал и посты.\n\n"
        "<b>Команды:</b>\n"
        "<code>/rep</code> или <code>реп</code> — карточка пользователя reply-сообщением\n"
        "<code>/rep @username</code> — поиск по базе\n"
        "<code>+реп @username причина</code> — заявка на плюс репутации\n"
        "<code>-реп @username причина</code> — заявка на минус репутации\n"
        "<code>/history @username</code> — история юзов\n"
        "<code>/stats</code> — статистика\n\n"
        "⚠️ Репутация принимается только со скрином/фото/файлом-доказательством."
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    track_message_people(message)
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Нет доступа.")
        return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_keyboard())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    track_message_people(message)
    if message.chat.type != ChatType.PRIVATE and not is_admin(message.from_user.id):
        # в группах можно всем показывать кратко, но оставим полную только админу
        await message.answer("📊 Статистика доступна в ЛС или админу.")
        return
    await message.answer(stats_full_text())


@router.message(Command("history"))
async def cmd_history(message: Message):
    track_message_people(message)
    text = message.text or ""
    parts = text.split(maxsplit=1)

    target_row = None
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        track_user(u, message.chat.id, getattr(message.chat, "title", None) or "ЛС")
        target_row = user_card_by_id(u.id)
    elif len(parts) > 1:
        target_row = find_user_by_query(parts[1].strip())

    if not target_row:
        await message.answer("Не нашел пользователя. Используй reply или <code>/history @username</code>.")
        return

    rows = username_history(target_row["user_id"], 30)
    if not rows:
        await message.answer("История username пустая.")
        return
    lines = []
    for r in rows:
        lines.append(f"• {fmt_username(r['username'])} — <code>{r['changed_at']}</code>")
    await message.answer(
        f"🔁 <b>История username</b>\n"
        f"ID: <code>{target_row['user_id']}</code>\n"
        f"Текущий: <b>{fmt_username(target_row['current_username'])}</b>\n\n" + "\n".join(lines)
    )


@router.message(Command("rep"))
async def cmd_rep_slash(message: Message):
    await handle_rep_lookup(message)


async def handle_rep_lookup(message: Message):
    track_message_people(message)
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)

    target_row = None
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        track_user(u, message.chat.id, getattr(message.chat, "title", None) or "ЛС")
        target_row = user_card_by_id(u.id)
    elif len(parts) > 1:
        target_row = find_user_by_query(parts[1].strip())

    if not target_row:
        await message.answer("Не нашел пользователя. Используй reply, <code>/rep @username</code> или <code>реп @username</code>.")
        return

    entries = reputation_entries(target_row["user_id"], 10)
    hist = username_history(target_row["user_id"], 5)

    rep_lines = []
    if entries:
        for e in entries:
            sign = "+" if e["delta"] > 0 else ""
            rep_lines.append(f"• <b>{sign}{e['delta']}</b> — {html_escape(e['reason'])} / <code>{e['created_at']}</code>")
    else:
        rep_lines.append("• Одобренной репутации пока нет")

    hist_lines = []
    for h in hist:
        hist_lines.append(f"• {fmt_username(h['username'])} — <code>{h['changed_at']}</code>")
    if not hist_lines:
        hist_lines.append("• История пустая")

    await message.answer(
        "👤 <b>Карточка репутации</b>\n"
        f"Имя: <b>{html_escape(target_row['full_name'] or target_row['first_name'] or 'Без имени')}</b>\n"
        f"ID: <code>{target_row['user_id']}</code>\n"
        f"Username: <b>{fmt_username(target_row['current_username'])}</b>\n"
        f"Репутация: <b>{target_row['reputation_score']}</b>\n"
        f"Первый раз замечен: <code>{target_row['first_seen_at']}</code>\n"
        f"Последний раз замечен: <code>{target_row['last_seen_at']}</code>\n"
        f"Где последний раз: {html_escape(target_row['last_seen_chat_title'] or '-')}\n"
        f"Сообщений/появлений замечено: <b>{target_row['messages_seen']}</b>\n\n"
        "📌 <b>Последняя репутация:</b>\n" + "\n".join(rep_lines) + "\n\n"
        "🔁 <b>Последние username:</b>\n" + "\n".join(hist_lines)
    )


async def handle_rep_request(message: Message, delta: int):
    track_message_people(message)

    raw_text = message.caption or message.text or ""
    prefix = "+реп" if delta > 0 else "-реп"

    proof_type, proof_file_id = get_proof_from_message(message)
    if not proof_type:
        await message.answer(
            "🖼 Заявка на репутацию принимается только со скрином/фото/файлом.\n\n"
            f"Отправь фото/скрин с подписью:\n<code>{prefix} @username причина</code>\n\n"
            "Или ответь фото/скрином на сообщение человека с подписью:\n"
            f"<code>{prefix} причина</code>"
        )
        return

    target_query = None
    reason = ""
    target_user_id = None
    target_username_at_request = None

    # Вариант: заявка reply-сообщением на пользователя
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        track_user(target, message.chat.id, getattr(message.chat, "title", None) or "ЛС")
        target_user_id = target.id
        target_query = str(target.id)
        target_username_at_request = target.username.lower() if target.username else None
        clean = raw_text.strip()
        # убираем +реп/-реп из начала и считаем остаток причиной
        if clean.lower().startswith(prefix):
            reason = clean[len(prefix):].strip()
        else:
            reason = clean
    else:
        target_query, reason = extract_target_and_reason(raw_text, prefix)
        if target_query:
            row = find_user_by_query(target_query)
            if row:
                target_user_id = row["user_id"]
                target_username_at_request = row["current_username"]

    if not target_query:
        await message.answer(
            f"Не указана цель. Пример подписи к фото:\n<code>{prefix} @username причина</code>"
        )
        return

    if not reason or len(reason) < 5:
        await message.answer("Укажи нормальную причину минимум 5 символов: за что ставится репутация.")
        return

    chat_title = getattr(message.chat, "title", None) or "ЛС"
    req_id = create_rep_request(
        target_user_id=target_user_id,
        target_query=target_query,
        target_username_at_request=target_username_at_request,
        reporter_user_id=message.from_user.id,
        reporter_username=message.from_user.username.lower() if message.from_user.username else None,
        chat_id=message.chat.id,
        chat_title=chat_title,
        delta=delta,
        reason=reason,
        proof_type=proof_type,
        proof_file_id=proof_file_id,
        proof_message_id=message.message_id,
    )

    await message.answer(
        f"✅ <b>Заявка #{req_id} отправлена на проверку</b>\n"
        f"Тип: <b>{'+реп' if delta > 0 else '-реп'}</b>\n"
        f"Цель: <b>{html_escape(target_query)}</b>\n"
        f"ID в базе: <code>{target_user_id or 'пока не найден'}</code>\n"
        f"Причина: {html_escape(reason)}"
    )
    await send_request_to_admin(message.bot, req_id)


# =========================================================
# TEXT/CAPTION HANDLERS
# =========================================================

@router.message(F.text)
async def text_router(message: Message, bot: Bot):
    result = track_message_people(message)
    await notify_admin_username_change(bot, message, result)

    text = (message.text or "").strip()
    lower = text.lower()

    # реп / rep без учета регистра
    if lower == "реп" or lower.startswith("реп ") or lower == "rep" or lower.startswith("rep "):
        await handle_rep_lookup(message)
        return

    # +реп / -реп без фото не принимаем, но объясняем
    if lower.startswith("+реп"):
        await handle_rep_request(message, +1)
        return
    if lower.startswith("-реп"):
        await handle_rep_request(message, -1)
        return


@router.message(F.caption)
async def caption_router(message: Message, bot: Bot):
    result = track_message_people(message)
    await notify_admin_username_change(bot, message, result)

    caption = (message.caption or "").strip().lower()
    if caption.startswith("+реп"):
        await handle_rep_request(message, +1)
        return
    if caption.startswith("-реп"):
        await handle_rep_request(message, -1)
        return
    if caption == "реп" or caption.startswith("реп ") or caption == "rep" or caption.startswith("rep "):
        await handle_rep_lookup(message)
        return


@router.message()
async def all_other_messages(message: Message, bot: Bot):
    result = track_message_people(message)
    await notify_admin_username_change(bot, message, result)


# =========================================================
# CALLBACKS ADMIN
# =========================================================

@router.callback_query(F.data == "admin:home")
async def cb_admin_home(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text("🛠 <b>Админ-панель</b>", reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(stats_full_text(), reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:pending"))
async def cb_admin_pending(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rows = pending_requests(15)
    if not rows:
        await callback.message.edit_text("⏳ Заявок на проверку нет.", reply_markup=admin_keyboard())
    else:
        await callback.message.edit_text(
            f"⏳ <b>Заявки на проверку: {len(rows)}</b>\nВыбери заявку:",
            reply_markup=pending_keyboard(rows)
        )
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with closing(db_connect()) as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY last_seen_at DESC LIMIT 15").fetchall()
    if not rows:
        text = "👥 Пользователей пока нет."
    else:
        lines = []
        for u in rows:
            lines.append(
                f"• {html_escape(u['full_name'] or 'Без имени')} / {fmt_username(u['current_username'])} / "
                f"ID <code>{u['user_id']}</code> / реп <b>{u['reputation_score']}</b> / <code>{u['last_seen_at']}</code>"
            )
        text = "👥 <b>Последние пользователи</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:changes")
async def cb_admin_changes(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with closing(db_connect()) as conn:
        rows = conn.execute("""
            SELECT h.*, u.full_name
            FROM username_history h
            LEFT JOIN users u ON u.user_id=h.user_id
            ORDER BY h.id DESC
            LIMIT 20
        """).fetchall()
    if not rows:
        text = "🔁 История юзов пока пустая."
    else:
        lines = []
        for r in rows:
            lines.append(
                f"• {html_escape(r['full_name'] or 'Без имени')} / {fmt_username(r['username'])} / "
                f"ID <code>{r['user_id']}</code> / <code>{r['changed_at']}</code>"
            )
        text = "🔁 <b>Последние записи username</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:channels")
async def cb_admin_channels(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    with closing(db_connect()) as conn:
        channels = conn.execute("""
            SELECT c.*, COUNT(p.id) AS posts_count
            FROM chats c
            LEFT JOIN channel_posts p ON p.channel_id=c.chat_id
            WHERE c.type='channel'
            GROUP BY c.chat_id
            ORDER BY c.last_seen_at DESC
            LIMIT 15
        """).fetchall()
        last_posts = conn.execute("""
            SELECT * FROM channel_posts
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    lines = []
    if channels:
        lines.append("📣 <b>Каналы, где бот видел посты</b>\n")
        for c in channels:
            username = fmt_username(c["username"])
            lines.append(
                f"• {html_escape(c['title'] or 'Канал')} / {username} / "
                f"ID <code>{c['chat_id']}</code> / постов <b>{c['posts_count']}</b> / <code>{c['last_seen_at']}</code>"
            )
    else:
        lines.append("📣 Каналов пока нет. Добавь бота админом в канал и опубликуй пост.")

    if last_posts:
        lines.append("\n🕒 <b>Последние посты каналов</b>")
        for p in last_posts:
            author = p["author_signature"] or p["sender_chat_title"] or "без автора"
            preview = html_escape((p["text_preview"] or "").replace("\n", " ")[:80])
            lines.append(
                f"• {html_escape(p['channel_title'] or 'Канал')} / автор: {html_escape(author)} / "
                f"msg <code>{p['message_id']}</code> / <code>{p['seen_at']}</code>"
                + (f"\n  {preview}" if preview else "")
            )

    await callback.message.edit_text("\n".join(lines), reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("rep:view:"))
async def cb_rep_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    req_id = int(callback.data.split(":")[-1])
    req = get_rep_request(req_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await callback.message.edit_text(format_request(req), reply_markup=request_keyboard(req_id))
    await callback.answer()


@router.callback_query(F.data.startswith("rep:approve:"))
async def cb_rep_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    req_id = int(callback.data.split(":")[-1])
    ok, msg = approve_request(req_id, callback.from_user.id)
    req = get_rep_request(req_id)
    text = ("✅ " if ok else "⚠️ ") + html_escape(msg)
    if req:
        text += "\n\n" + format_request(req)
    await callback.message.edit_text(text, reply_markup=admin_keyboard())
    await callback.answer(msg, show_alert=not ok)


@router.callback_query(F.data.startswith("rep:reject:"))
async def cb_rep_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    req_id = int(callback.data.split(":")[-1])
    ok, msg = reject_request(req_id, callback.from_user.id)
    req = get_rep_request(req_id)
    text = ("❌ " if ok else "⚠️ ") + html_escape(msg)
    if req:
        text += "\n\n" + format_request(req)
    await callback.message.edit_text(text, reply_markup=admin_keyboard())
    await callback.answer(msg, show_alert=not ok)


# =========================================================
# STARTUP
# =========================================================

async def on_startup(bot: Bot):
    me = await bot.get_me()
    logging.info("Bot started as @%s | id=%s", me.username, me.id)
    logging.info("DB_PATH=%s", DB_PATH)
    try:
        await bot.send_message(
            ADMIN_ID,
            f"✅ <b>Diamond Reputation Bot запущен</b>\n"
            f"Бот: @{me.username}\n"
            f"ID: <code>{me.id}</code>\n"
            f"DB: <code>{html_escape(DB_PATH)}</code>\n\n"
            "Открой /admin для панели."
        )
    except Exception as e:
        logging.warning("startup notify failed: %s", e)


async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await on_startup(bot)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
