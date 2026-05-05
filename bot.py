import os
import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WORKER_BOT_TOKEN = os.getenv("WORKER_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"

def load_json(path, default):
    if Path(path).exists():
        return json.load(open(path, "r", encoding="utf-8"))
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_json(DATA_FILE, {
    "target_group": None,
    "phone_chat_id": None,  # chat_id второго бота
    "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
})

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

async def send_to_worker(phone, template):
    """Отправка команды второму боту (на телефон)"""
    if not data.get("phone_chat_id"):
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": data["phone_chat_id"],
        "text": f"/send {phone} {template}"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return resp.status == 200

# Регистрация телефона
@dp.message(Command("hello"))
async def hello(message: Message):
    data["phone_chat_id"] = message.chat.id
    save_json(DATA_FILE, data)
    await message.reply("✅ Телефон зарегистрирован")

@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁 Слежу за группой: {message.chat.title}")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    data["target_group"] = None
    save_json(DATA_FILE, data)
    await message.reply("🛑 Слежение отключено")

@dp.message(Command("stats"))
async def stats(message: Message):
    s = data["stats"]
    text = f"📊 Всего: {s['total']} | ✅ {s['success']} | ❌ {s['failed']} | ⏳ {s['pending']}\n\nПоследние 10:\n"
    for h in s["history"][-10:]:
        icon = "✅" if h["status"] == "success" else "❌" if h["status"] == "failed" else "⏳"
        text += f"{icon} {h['phone']} — {h['template'][:30]} — {h['time']}\n"
    await message.reply(text)

@dp.message(Command("resetstats"))
async def resetstats(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    data["stats"] = {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
    save_json(DATA_FILE, data)
    await message.reply("♻ Сброшено")

@dp.message(Command("get_apk"))
async def get_apk(message: Message):
    await message.reply("📱 Скачай APK: https://github.com/Monarh223/Rep/releases")

# Обработка сообщений в группе
@dp.message()
async def handle_message(message: Message):
    if message.chat.id == data.get("target_group"):
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

        success = await send_to_worker(phone, template)
        if success:
            await message.reply(f"✅ Команда отправлена на телефон: {phone}")
        else:
            await message.reply("❌ Телефон не подключён. Убедитесь, что APK запущен и отправил /hello")

        entry = {"phone": phone, "template": template, "time": datetime.now().strftime("%H:%M:%S"), "status": "pending"}
        data["stats"]["total"] += 1
        data["stats"]["pending"] += 1
        data["stats"]["history"].append(entry)
        save_json(DATA_FILE, data)

    # Приём скриншотов от телефона
    if message.chat.id == data.get("phone_chat_id") and message.photo:
        caption = message.caption or ""
        phone = None
        for word in caption.split():
            p = clean_phone(word)
            if p:
                phone = p
                break
        if phone:
            for h in reversed(data["stats"]["history"]):
                if h["phone"] == phone and h["status"] == "pending":
                    h["status"] = "success"
                    data["stats"]["pending"] -= 1
                    data["stats"]["success"] += 1
                    save_json(DATA_FILE, data)
                    break
            if data.get("target_group"):
                await bot.send_photo(data["target_group"], message.photo[-1].file_id,
                                     caption=f"✅ Доставлено: {phone}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
