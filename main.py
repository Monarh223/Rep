import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
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
            is_bot INTEGER DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS username_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            changed_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_user_id INTEGER NOT NULL,
            reporter_user_id INTEGER NOT NULL,
            reporter_chat_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            target_username_at_report TEXT,
            reporter_username_at_report TEXT,
            target_first_name TEXT,
            target_last_name TEXT,
            status TEXT NOT NULL DEFAULT 'new'
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            username TEXT,
            type TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """)


def upsert_chat(message: Message):
    chat = message.chat
    title = getattr(chat, "title", None)
    username = getattr(chat, "username", None)
    chat_type = chat.type
    now = utc_now()

    with closing(db_connect()) as conn, conn:
        row = conn.execute(
            "SELECT chat_id FROM chats WHERE chat_id = ?",
            (chat.id,)
        ).fetchone()

        if row:
            conn.execute("""
                UPDATE chats
                SET title = ?, username = ?, type = ?, last_seen_at = ?
                WHERE chat_id = ?
            """, (title, username, chat_type, now, chat.id))
        else:
            conn.execute("""
                INSERT INTO chats (chat_id, title, username, type, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat.id, title, username, chat_type, now, now))


def track_user(user) -> Optional[dict]:
    if not user:
        return None

    now = utc_now()
    current_username = user.username.lower() if user.username else None
    first_name = user.first_name
    last_name = user.last_name
    is_bot = 1 if user.is_bot else 0

    with closing(db_connect()) as conn, conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user.id,)
        ).fetchone()

        if row is None:
            conn.execute("""
                INSERT INTO users (
                    user_id, current_username, first_name, last_name, is_bot,
                    first_seen_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user.id, current_username, first_name, last_name, is_bot,
                now, now
            ))

            conn.execute("""
                INSERT INTO username_history (user_id, username, changed_at)
                VALUES (?, ?, ?)
            """, (user.id, current_username, now))

            return {"changed": False, "old": None, "new": current_username}

        old_username = row["current_username"]

        conn.execute("""
            UPDATE users
            SET current_username = ?, first_name = ?, last_name = ?, is_bot = ?, last_seen_at = ?
            WHERE user_id = ?
        """, (
            current_username, first_name, last_name, is_bot, now, user.id
        ))

        if old_username != current_username:
            conn.execute("""
                INSERT INTO username_history (user_id, username, changed_at)
                VALUES (?, ?, ?)
            """, (user.id, current_username, now))

            return {"changed": True, "old": old_username, "new": current_username}

        return {"changed": False, "old": old_username, "new": current_username}


def create_report(
    target_user_id: int,
    reporter_user_id: int,
    reporter_chat_id: int,
    reason: str,
    target_username_at_report: Optional[str],
    reporter_username_at_report: Optional[str],
    target_first_name: Optional[str],
    target_last_name: Optional[str],
) -> int:
    with closing(db_connect()) as conn, conn:
        cur = conn.execute("""
            INSERT INTO reports (
                target_user_id,
                reporter_user_id,
                reporter_chat_id,
                reason,
                created_at,
                target_username_at_report,
                reporter_username_at_report,
                target_first_name,
                target_last_name,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        """, (
            target_user_id,
            reporter_user_id,
            reporter_chat_id,
            reason.strip(),
            utc_now(),
            target_username_at_report.lower() if target_username_at_report else None,
            reporter_username_at_report.lower() if reporter_username_at_report else None,
            target_first_name,
            target_last_name,
        ))
        return cur.lastrowid


def get_user_card(user_id: int) -> Optional[sqlite3.Row]:
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT
                u.*,
                (SELECT COUNT(*) FROM reports r WHERE r.target_user_id = u.user_id) AS reports_count
            FROM users u
            WHERE u.user_id = ?
        """, (user_id,)).fetchone()


def get_last_reports(user_id: int, limit: int = 5):
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT *
            FROM reports
            WHERE target_user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()


def get_username_history(user_id: int, limit: int = 20):
    with closing(db_connect()) as conn:
        return conn.execute("""
            SELECT username, changed_at
            FROM username_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()


def stats_text() -> str:
    with closing(db_connect()) as conn:
        users_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        reports_count = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
        chats_count = conn.execute("SELECT COUNT(*) AS c FROM chats").fetchone()["c"]
        return (
            f"📊 <b>Статистика</b>\n"
            f"Пользователей в базе: <b>{users_count}</b>\n"
            f"Репортов: <b>{reports_count}</b>\n"
            f"Чатов замечено: <b>{chats_count}</b>"
        )


def resolve_target_from_message(message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None
    return message.reply_to_message.from_user


async def notify_admin(text: str, bot: Bot):
    if ADMIN_ID > 0:
        try:
            await bot.send_message(ADMIN_ID, text)
        except Exception as e:
            logging.warning("Admin notify failed: %s", e)


async def maybe_announce_username_change(message: Message, bot: Bot, result: Optional[dict]):
    if not result or not result.get("changed"):
        return

    user = message.from_user
    old_u = f"@{result['old']}" if result["old"] else "без username"
    new_u = f"@{result['new']}" if result["new"] else "без username"

    text = (
        f"🔄 <b>Смена username зафиксирована</b>\n"
        f"Пользователь: <b>{user.full_name}</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"Было: <b>{old_u}</b>\n"
        f"Стало: <b>{new_u}</b>\n"
        f"Чат: <code>{message.chat.id}</code>"
    )

    logging.info("USERNAME CHANGED | user_id=%s | %s -> %s", user.id, result["old"], result["new"])
    await notify_admin(text, bot)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    upsert_chat(message)
    track_user(message.from_user)

    text = (
        "👋 <b>Тестовый репутационный бот запущен</b>\n\n"
        "Что умеет сейчас:\n"
        "• фиксировать пользователей, которых видит\n"
        "• записывать смену username\n"
        "• принимать репорты по reply\n"
        "• показывать карточку и историю\n\n"
        "<b>Команды:</b>\n"
        "/help — помощь\n"
        "/report причина — ответом на сообщение пользователя\n"
        "/rep — ответом на сообщение пользователя\n"
        "/history — ответом на сообщение пользователя\n"
        "/stats — статистика\n\n"
        "Для нормальной слежки в группе добавь бота в группу и выключи privacy mode у BotFather."
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    upsert_chat(message)
    track_user(message.from_user)

    text = (
        "📘 <b>Как тестировать</b>\n\n"
        "1. Добавь бота в группу\n"
        "2. Выключи privacy mode в BotFather\n"
        "3. Пере-добавь бота в группу\n"
        "4. Пиши сообщения с разных аккаунтов\n"
        "5. Меняй username и снова пиши\n\n"
        "<b>Команды:</b>\n"
        "/report причина — репорт на пользователя reply-сообщением\n"
        "/rep — карточка пользователя reply-сообщением\n"
        "/history — история username reply-сообщением\n"
        "/stats — статистика\n\n"
        "<b>Пример:</b>\n"
        "Ответь на сообщение человека:\n"
        "<code>/report подозрение на скам</code>"
    )
    await message.answer(text)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    upsert_chat(message)
    track_user(message.from_user)
    await message.answer(stats_text())


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot):
    upsert_chat(message)
    track_user(message.from_user)

    target = resolve_target_from_message(message)
    if not target:
        await message.answer(
            "Нужно ответить на сообщение пользователя командой:\n"
            "<code>/report причина</code>"
        )
        return

    if target.is_bot:
        await message.answer("На бота репорт в этом тесте не принимается.")
        return

    parts = (message.text or "").split(maxsplit=1)
    reason = parts[1].strip() if len(parts) > 1 else ""

    if not reason:
        await message.answer("Укажи причину.\nПример:\n<code>/report обман при сделке</code>")
        return

    track_user(target)

    report_id = create_report(
        target_user_id=target.id,
        reporter_user_id=message.from_user.id,
        reporter_chat_id=message.chat.id,
        reason=reason,
        target_username_at_report=target.username,
        reporter_username_at_report=message.from_user.username,
        target_first_name=target.first_name,
        target_last_name=target.last_name,
    )

    text = (
        f"✅ <b>Репорт сохранен</b>\n"
        f"ID репорта: <code>{report_id}</code>\n"
        f"На: <b>{target.full_name}</b>\n"
        f"Username: <b>{('@' + target.username) if target.username else 'без username'}</b>\n"
        f"User ID: <code>{target.id}</code>\n"
        f"Причина: {reason}"
    )
    await message.answer(text)

    await notify_admin(
        f"📝 Новый репорт #{report_id}\n"
        f"На пользователя: {target.full_name} ({'@' + target.username if target.username else 'без username'})\n"
        f"ID: {target.id}\n"
        f"От: {message.from_user.full_name} ({'@' + message.from_user.username if message.from_user.username else 'без username'})\n"
        f"Причина: {reason}",
        bot
    )


@router.message(Command("rep"))
async def cmd_rep(message: Message):
    upsert_chat(message)
    track_user(message.from_user)

    target = resolve_target_from_message(message)
    if not target:
        await message.answer("Ответь этой командой на сообщение нужного пользователя.")
        return

    track_user(target)
    card = get_user_card(target.id)

    if not card:
        await message.answer("Пользователь еще не попадал в базу.")
        return

    last_reports = get_last_reports(target.id, limit=5)
    reports_block = []

    if last_reports:
        for r in last_reports:
            reports_block.append(f"• #{r['id']} [{r['created_at']}] — {r['reason']}")
    else:
        reports_block.append("• Репортов пока нет")

    text = (
        f"👤 <b>Карточка пользователя</b>\n"
        f"Имя: <b>{card['first_name'] or '-'} {card['last_name'] or ''}</b>\n"
        f"Текущий username: <b>{('@' + card['current_username']) if card['current_username'] else 'без username'}</b>\n"
        f"User ID: <code>{card['user_id']}</code>\n"
        f"Первый раз замечен: <code>{card['first_seen_at']}</code>\n"
        f"Последний раз замечен: <code>{card['last_seen_at']}</code>\n"
        f"Всего репортов: <b>{card['reports_count']}</b>\n\n"
        f"<b>Последние репорты:</b>\n" + "\n".join(reports_block)
    )
    await message.answer(text)


@router.message(Command("history"))
async def cmd_history(message: Message):
    upsert_chat(message)
    track_user(message.from_user)

    target = resolve_target_from_message(message)
    if not target:
        await message.answer("Ответь этой командой на сообщение нужного пользователя.")
        return

    track_user(target)
    history = get_username_history(target.id, limit=20)

    if not history:
        await message.answer("История username пока пустая.")
        return

    lines = []
    for row in history:
        uname = f"@{row['username']}" if row["username"] else "без username"
        lines.append(f"• {uname} — <code>{row['changed_at']}</code>")

    text = (
        f"🕓 <b>История username</b>\n"
        f"Пользователь: <b>{target.full_name}</b>\n"
        f"ID: <code>{target.id}</code>\n\n"
        + "\n".join(lines)
    )
    await message.answer(text)


@router.message(F.chat.type.in_({ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP}))
async def track_every_message(message: Message, bot: Bot):
    upsert_chat(message)
    result = track_user(message.from_user)

    if message.reply_to_message and message.reply_to_message.from_user:
        track_user(message.reply_to_message.from_user)

    await maybe_announce_username_change(message, bot, result)


async def on_startup(bot: Bot):
    me = await bot.get_me()
    logging.info("Bot started as @%s (%s)", me.username, me.id)
    logging.info("DB path: %s", DB_PATH)

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"✅ Бот запущен\n"
                f"Юзер: @{me.username}\n"
                f"ID: <code>{me.id}</code>\n"
                f"База: <code>{DB_PATH}</code>"
            )
        except Exception as e:
            logging.warning("Startup notify failed: %s", e)


async def main():
    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    await on_startup(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
