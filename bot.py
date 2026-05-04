import os
import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"

def load_data():
    if Path(DATA_FILE).exists():
        return json.load(open(DATA_FILE, "r", encoding="utf-8"))
    return {
        "target_group": None,
        "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
    }

def save_data(d):
    json.dump(d, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_data()

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_data(data)
        await message.reply(f"👁 Слежу: {message.chat.title}")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    data["target_group"] = None
    save_data(data)
    await message.reply("🛑 Отключено")

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
    if message.chat.id != ADMIN_CHAT_ID:
        return
    data["stats"] = {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
    save_data(data)
    await message.reply("♻ Сброшено")

@dp.message(Command("build"))
async def build_apk(message: Message):
    if message.chat.id != ADMIN_CHAT_ID:
        return
    await message.reply("🔨 Заглушка сборки. APK собирай через Android Studio или github actions")

@dp.message()
async def handle_message(message: Message):
    if message.chat.id != data.get("target_group"):
        return
    text = message.text or message.caption or ""
    if not text.strip() or text.startswith("/"):
        return

    words = text.strip().split()
    phone = None
    for word in words:
        p = clean_phone(word.strip().replace(",", "").replace(".", ""))
        if p:
            phone = p
            break
    if not phone:
        return

    template = text.replace(phone, "").replace("+7", "").replace("8", "", 1).strip()
    if not template:
        parts = text.split()
        try:
            idx = next(i for i, w in enumerate(parts) if clean_phone(w))
            template = " ".join(parts[idx+1:]) if idx+1 < len(parts) else "Сообщение"
        except:
            template = "Сообщение"

    await message.reply(f"🔄 Делаю\n📱 {phone}\n📝 {template[:100]}")

    entry = {"phone": phone, "template": template, "time": datetime.now().strftime("%H:%M:%S"), "status": "pending"}
    data["stats"]["total"] += 1
    data["stats"]["pending"] += 1
    data["stats"]["history"].append(entry)
    save_data(data)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
