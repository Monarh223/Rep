import os
import asyncio
import aiohttp
import json
import base64
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
QUEUE_FILE = "queue.json"

def load_json(path, default):
    if Path(path).exists():
        return json.load(open(path, "r", encoding="utf-8"))
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_json(DATA_FILE, {"target_group": None, "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}})
queue = load_json(QUEUE_FILE, [])

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
    if message.chat.id != ADMIN_CHAT_ID:
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁️ Слежу за группой: {message.chat.title}")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.chat.id != ADMIN_CHAT_ID:
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
    if message.chat.id != ADMIN_CHAT_ID:
        return
    data["stats"] = {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
    save_json(DATA_FILE, data)
    await message.reply("♻️ Статистика сброшена")

@dp.message(Command("get_apk"))
async def get_apk(message: Message):
    await message.reply("📱 Скачай APK: https://github.com/Monarh223/Rep/releases")

@dp.message(Command("ping"))
async def ping(message: Message):
    await message.reply("🟢 Бот работает")

@dp.message(Command("mychatid"))
async def mychatid(message: Message):
    await message.reply(f"Твой Chat ID: `{message.chat.id}`", parse_mode="Markdown")

# ---------- Команда для телефона ----------
@dp.message(Command("get_task"))
async def get_task(message: Message):
    global queue
    if not queue:
        return
    cmd = queue.pop(0)
    save_json(QUEUE_FILE, queue)
    await message.reply(f"/send {cmd['phone']} {cmd['template']}")

# ---------- Приём скриншотов от телефона ----------
@dp.message()
async def handle_message(message: Message):
    global data

    # Если сообщение из целевой группы — парсим номер
    if message.chat.id == data.get("target_group"):
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

        # Добавляем в очередь
        queue.append({
            "phone": phone,
            "template": template,
            "time": datetime.now().strftime("%H:%M:%S")
        })
        save_json(QUEUE_FILE, queue)

        await message.reply(f"🔄 В очереди\n📱 {phone}\n📝 {template[:100]}")

        entry = {"phone": phone, "template": template, "time": datetime.now().strftime("%H:%M:%S"), "status": "pending"}
        data["stats"]["total"] += 1
        data["stats"]["pending"] += 1
        data["stats"]["history"].append(entry)
        save_json(DATA_FILE, data)
        return

    # Если сообщение из лички (от телефона) с фото — это скриншот
    if message.chat.type == "private" and message.photo:
        caption = message.caption or ""
        # Ищем телефон в подписи
        phone = None
        for word in caption.split():
            p = clean_phone(word)
            if p:
                phone = p
                break

        if phone:
            # Обновляем статистику
            for h in reversed(data["stats"]["history"]):
                if h["phone"] == phone and h["status"] == "pending":
                    h["status"] = "success"
                    data["stats"]["pending"] -= 1
                    data["stats"]["success"] += 1
                    save_json(DATA_FILE, data)
                    break

            # Пересылаем в группу
            if data.get("target_group"):
                await bot.send_photo(
                    data["target_group"],
                    photo=message.photo[-1].file_id,
                    caption=f"✅ Доставлено: {phone}"
                )

    # Если из лички текст "✅ Доставлено: ..." (без скрина)
    if message.chat.type == "private" and message.text and message.text.startswith("✅ Доставлено:"):
        parts = message.text.split(":")
        if len(parts) > 1:
            phone = clean_phone(parts[1].strip())
            if phone:
                for h in reversed(data["stats"]["history"]):
                    if h["phone"] == phone and h["status"] == "pending":
                        h["status"] = "success"
                        data["stats"]["pending"] -= 1
                        data["stats"]["success"] += 1
                        save_json(DATA_FILE, data)
                        break
                if data.get("target_group"):
                    await bot.send_message(data["target_group"], f"✅ Доставлено: {phone}\n⚠ Без скрина")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
