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
from aiogram.types import (
    Message, BufferedInputFile, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery, FSInputFile
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_FILE = "data.json"
processed_ids = set()          # для статусов
processed_screenshots = set()  # для скриншотов

def load_data():
    if Path(DATA_FILE).exists():
        return json.load(open(DATA_FILE, "r", encoding="utf-8"))
    return {
        "admin_ids": [int(os.getenv("ADMIN_CHAT_ID", "0"))],
        "target_groups": {}
    }

def save_data(d):
    json.dump(d, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

data = load_data()

def is_admin(user_id: int) -> bool:
    return user_id in data.get("admin_ids", [])

def clean_phone(raw):
    digits = ''.join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == '9':
        return "+7" + digits
    return None

# ---------- Клавиатуры (без изменений) ----------
def admin_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Управление группами", callback_data="groups_menu")],
        [InlineKeyboardButton(text="👑 Администраторы", callback_data="admins_menu"),
         InlineKeyboardButton(text="📊 Отчёты", callback_data="reports_menu")],
        [InlineKeyboardButton(text="🛠 Сброс статистики", callback_data="reset_menu")],
    ])

def groups_menu_keyboard():
    kb = [
        [InlineKeyboardButton(text="➕ Включить слежение", callback_data="group_add")],
        [InlineKeyboardButton(text="➖ Отключить слежение", callback_data="group_remove")],
        [InlineKeyboardButton(text="📋 Список групп", callback_data="group_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admins_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def reports_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Полный отчёт", callback_data="report_full")],
        [InlineKeyboardButton(text="📅 За сегодня", callback_data="report_today")],
        [InlineKeyboardButton(text="📆 За дату", callback_data="report_date")],
        [InlineKeyboardButton(text="✅ Только успешные", callback_data="report_success")],
        [InlineKeyboardButton(text="📥 Выгрузить TXT", callback_data="export_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def export_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 За всё время", callback_data="export_all")],
        [InlineKeyboardButton(text="📄 За сегодня", callback_data="export_today")],
        [InlineKeyboardButton(text="📄 Успешные", callback_data="export_success")],
        [InlineKeyboardButton(text="📄 За дату", callback_data="export_date_prompt")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="reports_menu")]
    ])

def reset_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♻ Сбросить всё", callback_data="reset_all")],
        [InlineKeyboardButton(text="♻ Сбросить за сегодня", callback_data="reset_today")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

# ---------- /start ----------
@dp.message(Command("start"))
async def start_command(message: Message):
    if is_admin(message.from_user.id):
        await message.reply("🔐 Админ-панель:", reply_markup=admin_main_keyboard())
    else:
        text = (
            "👋 <b>SMS-рассылка через Telegram-бота</b>\n\n"
            "📲 <b>Как установить приложение на телефон:</b>\n"
            "1. Скачай APK-файл и установи его\n"
            "2. Обязательно выдай все запрашиваемые разрешения (SMS, запись экрана)\n"
            "3. Нажми «📸 Разрешить скриншоты» и прими системный диалог\n"
            "4. Нажми «🚀 Запустить сервис»\n"
            "5. Если нужно выключить – нажми «🛑 Остановить сервис»\n\n"
            "🤖 <b>Как добавить бота в группу:</b>\n"
            "– Добавь бота в группу\n"
            "– Напиши <code>/look</code> (только для администраторов)\n"
            "– После этого все номера в группе будут обрабатываться автоматически"
        )
        await message.reply(text, parse_mode="HTML")

# ---------- /look ----------
@dp.message(Command("look"))
async def look_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.chat.type not in ["group", "supergroup"]:
        await message.reply("Эту команду можно использовать только в группе.")
        return
    gid = str(message.chat.id)
    if gid in data["target_groups"]:
        del data["target_groups"][gid]
        save_data(data)
        await message.reply("🛑 Слежение за группой отключено.")
    else:
        data["target_groups"][gid] = message.chat.title or "Без названия"
        save_data(data)
        await message.reply("👁 Слежение за группой включено.")

# ---------- Callback-обработчики (без изменений) ----------
# ... (весь код callback_handler остаётся как в предыдущей версии)

# ---------- Обработка сообщений в группах ----------
@dp.message()
async def handle_any_message(message: Message):
    text = message.text.strip() if message.text else ""

    if str(message.chat.id) not in data.get("target_groups", {}):
        return

    phone = None
    for word in text.split():
        p = clean_phone(word.strip().replace(",", "").replace(".", "").replace(")", "").replace("(", ""))
        if p:
            phone = p
            break
    if not phone:
        return

    pattern = re.escape(phone) + r'|' + re.escape(phone[1:]) + r'|' + re.escape('8' + phone[2:])
    template = re.sub(pattern, '', text, count=1).strip() or "Сообщение"

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

# ---------- Фоновый опрос результатов (ИСПРАВЛЕН) ----------
async def check_completed_tasks():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                # Проверяем задачи со скриншотами (screenshot не null)
                async with session.get(
                    f"{SUPABASE_URL}/rest/v1/tasks?select=*&screenshot=not.is.null&order=created_at.desc&limit=5",
                    headers=headers
                ) as resp:
                    if resp.status == 200:
                        tasks = await resp.json()
                        for task in tasks:
                            tid = task["id"]
                            if tid in processed_screenshots:
                                continue
                            processed_screenshots.add(tid)
                            phone = task["phone"]
                            status = task["status"]
                            screenshot_b64 = task.get("screenshot")
                            for gid in data.get("target_groups", {}):
                                if screenshot_b64:
                                    scr = base64.b64decode(screenshot_b64)
                                    cap = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой: {phone}"
                                    await bot.send_photo(int(gid), BufferedInputFile(scr, "screen.jpg"), caption=cap)
                                    # После отправки скриншота удаляем его из задачи для экономии места
                                    async with session.patch(
                                        f"{SUPABASE_URL}/rest/v1/tasks?id=eq.{tid}",
                                        headers={**headers, "Content-Type": "application/json"},
                                        json={"screenshot": None}
                                    ) as _:
                                        pass
                # Также проверяем статусы для текстовых уведомлений
                async with session.get(
                    f"{SUPABASE_URL}/rest/v1/tasks?select=*&status=in.(success,failed)&order=created_at.desc&limit=5",
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
                            if screenshot_b64:
                                continue  # пропускаем, уже обработано выше
                            for gid in data.get("target_groups", {}):
                                txt = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой: {phone}"
                                await bot.send_message(int(gid), txt)
        except Exception as e:
            print("Checker error:", e)
        await asyncio.sleep(3)

async def main():
    asyncio.create_task(check_completed_tasks())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
