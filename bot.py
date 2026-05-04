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
DEFAULT_ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
DEFAULT_PHONE_GATEWAY_URL = os.getenv("PHONE_GATEWAY_URL", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
QUEUE_FILE = "queue.json"

# ------------------------------------------------------------
# Загрузка / сохранение
# ------------------------------------------------------------
def load_json(path, default):
    if Path(path).exists():
        return json.load(open(path, "r", encoding="utf-8"))
    return default

def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# Начальные данные
data = load_json(DATA_FILE, {
    "target_group": None,
    "admin_chat_id": DEFAULT_ADMIN_CHAT_ID,
    "phone_gateway_url": DEFAULT_PHONE_GATEWAY_URL,
    "stats": {"total": 0, "success": 0, "failed": 0, "pending": 0, "history": []}
})

queue = load_json(QUEUE_FILE, [])

# Текущие настройки из data (с приоритетом над .env)
def get_admin_id():
    return data.get("admin_chat_id", DEFAULT_ADMIN_CHAT_ID)

def get_gateway_url():
    return data.get("phone_gateway_url", DEFAULT_PHONE_GATEWAY_URL)

# ------------------------------------------------------------
# Вспомогательные функции
# ------------------------------------------------------------
def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

async def send_sms_via_phone(phone, template):
    """Отправка SMS через HTTP-шлюз (телефон). Возвращает (успех, скриншот_bytes)."""
    gw = get_gateway_url()
    if not gw:
        return False, None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{gw}/send",
                json={"phone": phone, "message": template},
                timeout=30
            ) as resp:
                if resp.status == 200:
                    data_resp = await resp.json()
                    screenshot_b64 = data_resp.get("screenshot")
                    if screenshot_b64:
                        import base64
                        screenshot = base64.b64decode(screenshot_b64)
                        return True, screenshot
                    return True, None
                return False, None
    except:
        return False, None

# ------------------------------------------------------------
# Команды управления настройками
# ------------------------------------------------------------
@dp.message(Command("settings"))
async def settings(message: Message):
    """Показывает текущие настройки (только для админа)."""
    if message.chat.id != get_admin_id():
        return
    text = (
        f"⚙️ Текущие настройки:\n"
        f"• ADMIN_CHAT_ID: `{get_admin_id()}`\n"
        f"• PHONE_GATEWAY_URL: `{get_gateway_url() or 'не задан'}`\n"
    )
    await message.reply(text, parse_mode="Markdown")

@dp.message(Command("setgateway"))
async def set_gateway(message: Message):
    """Установить PHONE_GATEWAY_URL. Использование: /setgateway http://..."""
    if message.chat.id != get_admin_id():
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("❌ Укажите URL: `/setgateway http://12.34.56.78:9090`", parse_mode="Markdown")
        return
    new_url = parts[1].strip()
    data["phone_gateway_url"] = new_url
    save_json(DATA_FILE, data)
    await message.reply(f"✅ PHONE_GATEWAY_URL обновлён: `{new_url}`", parse_mode="Markdown")

@dp.message(Command("resetgateway"))
async def reset_gateway(message: Message):
    """Сбросить PHONE_GATEWAY_URL на значение из переменной окружения."""
    if message.chat.id != get_admin_id():
        return
    data["phone_gateway_url"] = DEFAULT_PHONE_GATEWAY_URL
    save_json(DATA_FILE, data)
    await message.reply(f"✅ PHONE_GATEWAY_URL сброшен: `{DEFAULT_PHONE_GATEWAY_URL or 'пусто'}`", parse_mode="Markdown")

@dp.message(Command("setadmin"))
async def set_admin(message: Message):
    """Передать админские права другому Chat ID. Использование: /setadmin 123456789"""
    if message.chat.id != get_admin_id():
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply("❌ Укажите новый Chat ID: `/setadmin 123456789`", parse_mode="Markdown")
        return
    try:
        new_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Chat ID должен быть числом.")
        return
    data["admin_chat_id"] = new_id
    save_json(DATA_FILE, data)
    await message.reply(f"✅ ADMIN_CHAT_ID изменён на `{new_id}`. Теперь команды принимаются от него.", parse_mode="Markdown")

# ------------------------------------------------------------
# Основные команды бота
# ------------------------------------------------------------
@dp.message(Command("worklook"))
async def worklook(message: Message):
    if message.chat.id != get_admin_id():
        return
    if message.chat.type in ["group", "supergroup"]:
        data["target_group"] = message.chat.id
        save_json(DATA_FILE, data)
        await message.reply(f"👁️ Слежу за группой: {message.chat.title}")

@dp.message(Command("stoplook"))
async def stoplook(message: Message):
    if message.chat.id != get_admin_id():
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
    if message.chat.id != get_admin_id():
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

# ------------------------------------------------------------
# Очередь для телефона
# ------------------------------------------------------------
@dp.message(Command("get_task"))
async def get_task(message: Message):
    """Телефон запрашивает задание."""
    global queue
    if not queue:
        return
    cmd = queue.pop(0)
    save_json(QUEUE_FILE, queue)
    await message.reply(f"/send {cmd['phone']} {cmd['template']}")

# ------------------------------------------------------------
# Обработка сообщений группы (заказы) и ответов от телефона
# ------------------------------------------------------------
@dp.message()
async def handle_message(message: Message):
    global data

    # Если сообщение из целевой группы — парсим номер и кладём в очередь
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

        # Статистика
        entry = {"phone": phone, "template": template, "time": datetime.now().strftime("%H:%M:%S"), "status": "pending"}
        data["stats"]["total"] += 1
        data["stats"]["pending"] += 1
        data["stats"]["history"].append(entry)
        save_json(DATA_FILE, data)
        return

    # Обработка ответов от телефона (личка)
    if message.chat.type == "private":
        # Фото со скриншотом
        if message.photo:
            caption = message.caption or ""
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
                # Пересылаем скрин в группу
                if data.get("target_group"):
                    await bot.send_photo(
                        data["target_group"],
                        photo=message.photo[-1].file_id,
                        caption=f"✅ Доставлено: {phone}"
                    )
        # Текстовый ответ "✅ Доставлено: ..." без скрина
        elif message.text and message.text.startswith("✅ Доставлено:"):
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

# ------------------------------------------------------------
# Запуск
# ------------------------------------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
