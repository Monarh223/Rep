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
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
QUEUE_FILE = "queue.json"

# WebSocket-клиенты (телефоны)
ws_clients = {}

def load_json(path, default):
    if Path(path).exists():
        return json.load(open(path, "r", encoding="utf-8"))
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_json(DATA_FILE, {
    "target_group": None,
    "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
})
queue = load_json(QUEUE_FILE, [])

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

# ---------- Telegram команды ----------
@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁️ Слежу за группой: {message.chat.title}")

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
    text = f"📊 Всего: {s['total']} | ✅ {s['success']} | ❌ {s['failed']}\nПоследние 10:\n"
    for h in s["history"][-10:]:
        icon = "✅" if h["status"] == "success" else "❌"
        text += f"{icon} {h['phone']} — {h['template'][:30]} — {h['time']}\n"
    await message.reply(text)

@dp.message(Command("get_apk"))
async def get_apk(message: Message):
    await message.reply("📱 Скачай APK: https://github.com/Monarh223/Rep/releases")

@dp.message(Command("ping"))
async def ping(message: Message):
    await message.reply("🟢 Бот работает")

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

    # Отправляем задание на телефон через WebSocket
    if ws_clients:
        task = {
            "type": "send_sms",
            "phone": phone,
            "message": template
        }
        # Отправляем первому подключенному телефону
        client = list(ws_clients.values())[0]
        await client.send_json(task)
        await message.reply(f"⚡ Команда отправлена на телефон: {phone}")
    else:
        await message.reply("❌ Телефон не подключён. Запустите приложение на телефоне.")

    # Статистика
    data["stats"]["total"] += 1
    data["stats"]["history"].append({
        "phone": phone,
        "template": template,
        "time": datetime.now().strftime("%H:%M:%S"),
        "status": "pending"
    })
    save_json(DATA_FILE, data)

# ---------- WebSocket сервер ----------
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    client_id = id(ws)
    ws_clients[client_id] = ws
    print(f"Телефон подключён: {client_id}")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                # Обработка ответа от телефона (скриншот/текст)
                if data.get("type") == "sms_result":
                    phone = data.get("phone")
                    status = data.get("status")
                    screenshot_b64 = data.get("screenshot")  # base64
                    # Обновляем статистику
                    for h in reversed(data["stats"]["history"]):
                        if h["phone"] == phone and h["status"] == "pending":
                            h["status"] = status
                            data["stats"]["success" if status == "success" else "failed"] += 1
                            save_json(DATA_FILE, data)
                            break
                    # Пересылаем в группу
                    target = data.get("target_group")
                    if target and screenshot_b64:
                        screenshot_bytes = base64.b64decode(screenshot_b64)
                        await bot.send_photo(target, photo=types.BufferedInputFile(screenshot_bytes, filename="screen.jpg"),
                                             caption=f"✅ Доставлено: {phone}")
                    elif target:
                        await bot.send_message(target, f"✅ Доставлено: {phone} (без скрина)")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        del ws_clients[client_id]
        print(f"Телефон отключён: {client_id}")
    return ws

# ---------- Запуск ----------
async def main():
    # Запускаем Telegram-бота
    asyncio.create_task(dp.start_polling(bot))

    # Запускаем WebSocket сервер
    app = web.Application()
    app.router.add_get("/ws", websocket_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", "8080")))
    await site.start()

    # Держим процесс
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
