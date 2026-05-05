import os
import asyncio
import aiohttp
import base64
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
QUEUE_FILE = "queue.json"
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

# ---------- Команды управления ----------
@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.from_user.id != get_admin_id():
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁 Слежу за группой: {message.chat.title}")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.from_user.id != get_admin_id():
        return
    data["target_group"] = None
    save_json(DATA_FILE, data)
    await message.reply("🛑 Слежение отключено")

@dp.message(Command("stats"))
async def stats(message: Message):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{SUPABASE_URL}/rest/v1/tasks?select=status", headers=headers) as resp:
            if resp.status == 200:
                tasks = await resp.json()
                total = len(tasks)
                success = sum(1 for t in tasks if t["status"] == "success")
                failed = total - success
                pending = total - success - failed
                await message.reply(f"📊 Всего: {total}\n✅ Успешно: {success}\n❌ Ошибок: {failed}\n⏳ В ожидании: {pending}")
            else:
                await message.reply("❌ Ошибка получения статистики")

@dp.message(Command("resetstats"))
async def resetstats(message: Message):
    if message.from_user.id != get_admin_id():
        return
    # Удаляем все записи из таблицы tasks
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{SUPABASE_URL}/rest/v1/tasks?status=neq.null", headers=headers) as resp:
            if resp.status == 200:
                await message.reply("♻ Статистика сброшена")
            else:
                await message.reply("❌ Ошибка сброса")

@dp.message(Command("setadmin"))
async def set_admin(message: Message):
    if message.from_user.id != get_admin_id():
        return
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

@dp.message(Command("settings"))
async def settings(message: Message):
    if message.from_user.id != get_admin_id():
        return
    text = f"⚙️ Текущие настройки:\n• Целевая группа: {data.get('target_group', 'не задана')}\n• Админ: {get_admin_id()}"
    await message.reply(text)

@dp.message(Command("get_apk"))
async def get_apk(message: Message):
    await message.reply("📱 Скачай APK: https://github.com/Monarh223/Rep/releases")

@dp.message(Command("ping"))
async def ping(message: Message):
    await message.reply("🟢 Бот работает")

@dp.message(Command("mychatid"))
async def mychatid(message: Message):
    await message.reply(f"Твой Chat ID: `{message.chat.id}`", parse_mode="Markdown")

# ---------- Обработка сообщений группы ----------
@dp.message()
async def handle_message(message: Message):
    if message.chat.id != data.get("target_group"):
        return
    text = message.text or ""
    if not text.strip() or text.startswith("/"):
        return
    phone = None
    for word in text.split():
        p = clean_phone(word)
        if p:
            phone = p
            break
    if not phone:
        return
    template = text.replace(phone, "").replace("+7", "").replace("8", "", 1).strip()
    if not template:
        template = "Сообщение"

    # Запись задачи в Supabase
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
                # Берём недавно обновлённые задачи, которые мы ещё не обработали
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
                                caption = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Ошибка: {phone}"
                                await bot.send_photo(target, photo=BufferedInputFile(screenshot_bytes, filename="screen.jpg"), caption=caption)
                            else:
                                text = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Ошибка: {phone}"
                                await bot.send_message(target, text)
        except Exception as e:
            print(f"Check error: {e}")
        await asyncio.sleep(3)

async def main():
    asyncio.create_task(check_completed_tasks())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
