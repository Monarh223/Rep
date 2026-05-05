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
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
RAILWAY_PUBLIC_URL = os.getenv("RAILWAY_PUBLIC_URL", "https://rep-production-730f.up.railway.app")
WEBHOOK_PATH = "/webhook"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
QUEUE_FILE = "queue.json"

# ------------------------------------------------------------
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

queue = load_json(QUEUE_FILE, [])

def get_admin_id():
    return data.get("admin_chat_id", DEFAULT_ADMIN_CHAT_ID)

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

# ------------------------------------------------------------
# Команды
@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.from_user.id != get_admin_id():
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁️ Слежу за группой: {message.chat.title}")
    else:
        await message.reply("❌ Эту команду нужно отправить в нужной группе.")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.from_user.id != get_admin_id():
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
    if message.from_user.id != get_admin_id():
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

# Очередь для телефона
@dp.message(Command("get_task"))
async def get_task(message: Message):
    global queue
    if not queue:
        return
    cmd = queue.pop(0)
    save_json(QUEUE_FILE, queue)
    await message.reply(f"/send {cmd['phone']} {cmd['template']}")

# Обработка заказов в группе
@dp.message()
async def handle_message(message: Message):
    global data
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

    # Ответы от телефона (скриншоты)
    if message.chat.type == "private":
        if message.photo:
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
                    await bot.send_photo(
                        data["target_group"],
                        photo=message.photo[-1].file_id,
                        caption=f"✅ Доставлено: {phone}"
                    )

# ------------------------------------------------------------
async def on_startup(bot: Bot):
    webhook_url = f"{RAILWAY_PUBLIC_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    print(f"Webhook set to {webhook_url}")

async def main():
    app = web.Application()
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    await on_startup(bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", "8080")))
    await site.start()

    # Оставляем процесс живым
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
