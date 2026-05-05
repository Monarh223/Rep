import os
import asyncio
import aiohttp
import base64
import json
import re
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
processed_ids = set()

def load_json(path, default):
    if Path(path).exists():
        return json.load(open(path, "r", encoding="utf-8"))
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_json(DATA_FILE, {
    "target_group": None,
    "admin_chat_id": DEFAULT_ADMIN_CHAT_ID,
    "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
})

def get_admin_id():
    return data.get("admin_chat_id", DEFAULT_ADMIN_CHAT_ID)

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

# ---------- Клавиатуры ----------
def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Следить за группой", callback_data="worklook")],
        [InlineKeyboardButton(text="🛑 Отключить слежение", callback_data="stoplook")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="📋 Детальный отчёт", callback_data="report")],
        [InlineKeyboardButton(text="♻ Сбросить статистику", callback_data="resetstats")],
        [InlineKeyboardButton(text="👑 Сменить админа", callback_data="setadmin")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ])

def user_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="📋 Отчёт за сегодня", callback_data="today")],
        [InlineKeyboardButton(text="🟢 Пинг", callback_data="ping")]
    ])

# ---------- Команды ----------
@dp.message(Command("start"))
async def start(message: Message):
    if message.from_user.id == get_admin_id():
        await message.reply("🔐 Админ-панель:", reply_markup=admin_keyboard())
    else:
        await message.reply("👋 Привет! Я бот для рассылки SMS.", reply_markup=user_keyboard())

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != get_admin_id():
        return
    await message.reply("🔐 Админ-панель:", reply_markup=admin_keyboard())

# ---------- Callback-обработчики ----------
@dp.callback_query()
async def callback_handler(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    cmd = callback.data

    if cmd == "worklook":
        if uid != get_admin_id(): return
        if callback.message.chat.type in ["group", "supergroup"]:
            data["target_group"] = callback.message.chat.id
            save_json(DATA_FILE, data)
            await callback.message.reply(f"👁 Слежу за группой: {callback.message.chat.title}")
        else:
            await callback.message.reply("❌ Эту команду нужно выполнять в группе")

    elif cmd == "stoplook":
        if uid != get_admin_id(): return
        data["target_group"] = None
        save_json(DATA_FILE, data)
        await callback.message.reply("🛑 Слежение отключено")

    elif cmd == "stats":
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SUPABASE_URL}/rest/v1/tasks?select=status", headers=headers) as resp:
                if resp.status == 200:
                    tasks = await resp.json()
                    total = len(tasks)
                    success = sum(1 for t in tasks if t["status"] == "success")
                    failed = sum(1 for t in tasks if t["status"] == "failed")
                    pending = total - success - failed
                    await callback.message.reply(
                        f"📊 Статистика:\n"
                        f"├ Всего: {total}\n"
                        f"├ ✅ Успешно: {success}\n"
                        f"├ ❌ Сбой: {failed}\n"
                        f"└ ⏳ В ожидании: {pending}"
                    )

    elif cmd == "today":
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        today_str = date.today().isoformat()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SUPABASE_URL}/rest/v1/tasks?select=*&created_at=gte.{today_str}&order=created_at.desc",
                headers=headers
            ) as resp:
                if resp.status == 200:
                    tasks = await resp.json()
                    if not tasks:
                        await callback.message.reply("📋 За сегодня нет задач")
                        return
                    total = len(tasks)
                    success = sum(1 for t in tasks if t["status"] == "success")
                    failed = sum(1 for t in tasks if t["status"] == "failed")
                    text = f"📋 Отчёт за {today_str}:\n├ Всего: {total}\n├ ✅ Успешно: {success}\n├ ❌ Сбой: {failed}\n\n"
                    for t in tasks[:10]:
                        icon = "✅" if t["status"] == "success" else "❌"
                        text += f"{icon} {t['phone']} — {t['template'][:30]}\n"
                    await callback.message.reply(text)

    elif cmd == "report":
        if uid != get_admin_id(): return
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        today_str = date.today().isoformat()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{SUPABASE_URL}/rest/v1/tasks?select=*&order=created_at.desc&limit=50",
                headers=headers
            ) as resp:
                if resp.status == 200:
                    tasks = await resp.json()
                    if not tasks:
                        await callback.message.reply("Нет данных")
                        return
                    total = len(tasks)
                    success = sum(1 for t in tasks if t["status"] == "success")
                    failed = sum(1 for t in tasks if t["status"] == "failed")
                    today_tasks = [t for t in tasks if t["created_at"].startswith(today_str)]
                    today_total = len(today_tasks)
                    today_success = sum(1 for t in today_tasks if t["status"] == "success")
                    today_failed = sum(1 for t in today_tasks if t["status"] == "failed")

                    text = (
                        f"📊 Детальный отчёт:\n\n"
                        f"За всё время:\n├ Всего: {total}\n├ ✅ {success}\n└ ❌ Сбой: {failed}\n\n"
                        f"За сегодня ({today_str}):\n├ Всего: {today_total}\n├ ✅ {today_success}\n└ ❌ Сбой: {today_failed}\n\n"
                        f"Последние 10 задач:\n"
                    )
                    for t in tasks[:10]:
                        icon = "✅" if t["status"] == "success" else "❌"
                        status_text = " — Сбой (Не доставлено)" if t["status"] == "failed" else ""
                        text += f"{icon} {t['phone']} — {t['template'][:30]}{status_text}\n"
                    await callback.message.reply(text)

    elif cmd == "resetstats":
        if uid != get_admin_id(): return
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"{SUPABASE_URL}/rest/v1/tasks?status=neq.null", headers=headers) as resp:
                if resp.status == 200:
                    await callback.message.reply("♻ Статистика сброшена")

    elif cmd == "ping":
        await callback.message.reply("🟢 Бот работает")

    elif cmd == "settings":
        if uid != get_admin_id(): return
        text = f"⚙️ Настройки:\n• Целевая группа: {data.get('target_group', 'не задана')}\n• Админ ID: {get_admin_id()}"
        await callback.message.reply(text)

    elif cmd == "setadmin":
        await callback.message.reply("Используй команду: /setadmin [новый ID]")

# ---------- Текстовые команды ----------
@dp.message(Command("setadmin"))
async def set_admin(message: Message):
    if message.from_user.id != get_admin_id(): return
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("Используй: /setadmin 123456789")
        return
    try:
        new_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Неверный ID")
        return
    data["admin_chat_id"] = new_id
    save_json(DATA_FILE, data)
    await message.reply(f"✅ ADMIN_CHAT_ID изменён на {new_id}")

@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.from_user.id != get_admin_id(): return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁 Слежу за группой: {message.chat.title}")

# ---------- Обработка сообщений группы ----------
@dp.message()
async def handle_message(message: Message):
    if message.chat.id != data.get("target_group"):
        return
    text = message.text or ""
    if not text.strip() or text.startswith("/"):
        return

    words = text.strip().split()
    phone = None
    for word in words:
        p = clean_phone(word.strip().replace(",", "").replace(".", "").replace(")", "").replace("(", ""))
        if p:
            phone = p
            break

    if not phone:
        return

    pattern = re.escape(phone) + r'|' + re.escape(phone[1:]) + r'|' + re.escape('8' + phone[2:])
    template = re.sub(pattern, '', text, count=1).strip()
    if not template:
        template = "Сообщение"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    payload = {"phone": phone, "template": template}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{SUPABASE_URL}/rest/v1/tasks", json=payload, headers=headers) as resp:
            if resp.status == 201:
                await message.reply(f"🔄 Задача добавлена: {phone}")
            else:
                await message.reply("❌ Ошибка добавления задачи")

# ---------- Фоновый опрос результатов ----------
async def check_completed_tasks():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{SUPABASE_URL}/rest/v1/tasks?status=in.(success,failed)&order=created_at.desc&limit=5",
                    headers=headers
                ) as resp:
                    if resp.status == 200:
                        tasks = await resp.json()
                        for task in tasks:
                            tid = task["id"]
                            if tid in processed_ids:
                                continue
                            processed_ids.add(tid)
                            phone = task["phone"]
                            status = task["status"]
                            screenshot_b64 = task.get("screenshot")
                            target = data.get("target_group")
                            if not target:
                                continue
                            if screenshot_b64:
                                screenshot_bytes = base64.b64decode(screenshot_b64)
                                caption = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой (Не доставлено): {phone}"
                                await bot.send_photo(target, photo=BufferedInputFile(screenshot_bytes, filename="screen.jpg"), caption=caption)
                            else:
                                text = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой (Не доставлено): {phone}"
                                await bot.send_message(target, text)
        except Exception as e:
            print(f"Check error: {e}")
        await asyncio.sleep(3)

async def main():
    asyncio.create_task(check_completed_tasks())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
