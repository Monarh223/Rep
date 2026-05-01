
import asyncio, os, sqlite3, time, re, json, hmac, hashlib
from contextlib import closing
from urllib.parse import parse_qsl
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN missing")
ADMIN_IDS={int(x) for x in os.getenv("ADMIN_IDS","").replace(" ","").split(",") if x}
ADMIN_GROUP_ID=int(os.getenv("ADMIN_GROUP_ID","0") or 0)
WEBAPP_URL=os.getenv("WEBAPP_URL","").strip()
DB_PATH=os.getenv("DB_PATH","market.db")
PORT=int(os.getenv("PORT","8080"))
BOT_USERNAME=""
router=Router()

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c
def now(): return int(time.time())
def money(x):
    try: return f"{float(x):.2f}".rstrip("0").rstrip(".")
    except Exception: return str(x)
def init_db():
    sql = (
    "CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, balance REAL DEFAULT 0, deals INTEGER DEFAULT 0, registered_at INTEGER NOT NULL, seller INTEGER DEFAULT 0);"
    "CREATE TABLE IF NOT EXISTS seller_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'pending', created_at INTEGER);"
    "CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, phone TEXT, price REAL, description TEXT, status TEXT DEFAULT 'moderation', created_at INTEGER);"
    "CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, seller_id INTEGER, item_id INTEGER, phone TEXT, price REAL, code TEXT, status TEXT DEFAULT 'awaiting_code', created_at INTEGER);"
    )
    with closing(db()) as c: c.executescript(sql); c.commit()
def ensure_user(u):
    with closing(db()) as c:
        c.execute("INSERT INTO users(user_id,username,full_name,registered_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",(u.id,u.username or "",u.full_name or "",now())); c.commit()
def user(uid):
    with closing(db()) as c: return c.execute("SELECT * FROM users WHERE user_id=?",(uid,)).fetchone()
def is_admin(uid): return uid in ADMIN_IDS
def is_seller(uid):
    u=user(uid); return bool(u and u["seller"])
def norm_phone(t):
    s=re.sub(r"[^0-9+]","",t or "")
    if s.startswith("+7") and len(s)==12: return s
    if s.startswith("8") and len(s)==11: return "+7"+s[1:]
    if s.startswith("7") and len(s)==11: return "+"+s
    return ""
def mask(p): return p[:3]+"****"+p[-4:] if p and len(p)>8 else p
def kb(rows): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a,callback_data=b) for a,b in r] for r in rows])
def menu():
    rows=[[InlineKeyboardButton(text="🛒 Маркет",callback_data="market")],
          [InlineKeyboardButton(text="👤 Профиль",callback_data="profile"), InlineKeyboardButton(text="📦 Покупки",callback_data="purchases")],
          [InlineKeyboardButton(text="💼 Режим продавца",callback_data="seller")]]
    if WEBAPP_URL: rows.append([InlineKeyboardButton(text="🌐 Mini App",web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def sell_menu(): return kb([[("➕ Загрузить номер","add_item")],[("📊 Продажи","sales"),("🛒 Режим покупателя","home")]])
async def notify_admin(bot,text,markup=None):
    if ADMIN_GROUP_ID: await bot.send_message(ADMIN_GROUP_ID,text,reply_markup=markup)
    else:
        for a in ADMIN_IDS: await bot.send_message(a,text,reply_markup=markup)

class AddItem(StatesGroup): phone=State(); price=State(); desc=State()
class Code(StatesGroup): code=State()
class AddBal(StatesGroup): uid=State(); amount=State()

@router.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); ensure_user(m.from_user)
    await m.answer("💎 <b>Diamond Market</b>\n\nГлавное меню:",reply_markup=menu())

@router.callback_query(F.data=="home")
async def home(c:CallbackQuery,state:FSMContext):
    await state.clear(); ensure_user(c.from_user)
    await c.message.edit_text("💎 <b>Diamond Market</b>\n\nГлавное меню:",reply_markup=menu()); await c.answer()

@router.message(Command("admin"))
async def admin(m:Message):
    ensure_user(m.from_user)
    if not is_admin(m.from_user.id): return await m.answer("⛔ Нет доступа")
    await m.answer("🛡 <b>Админ-панель</b>",reply_markup=kb([[("➕ Добавить баланс","admin_bal")]]))

@router.callback_query(F.data=="admin_bal")
async def admin_bal(c:CallbackQuery,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.set_state(AddBal.uid); await c.message.answer("Введите Telegram ID пользователя:"); await c.answer()

@router.message(AddBal.uid)
async def admin_uid(m:Message,state:FSMContext):
    if not is_admin(m.from_user.id): return
    try: uid=int(m.text.strip())
    except Exception: return await m.answer("ID должен быть числом")
    await state.update_data(uid=uid); await state.set_state(AddBal.amount); await m.answer("Введите сумму:")

@router.message(AddBal.amount)
async def admin_amount(m:Message,state:FSMContext):
    if not is_admin(m.from_user.id): return
    try: amount=float(m.text.replace(",","."))
    except Exception: return await m.answer("Сумма должна быть числом")
    uid=(await state.get_data())["uid"]
    with closing(db()) as c:
        if not c.execute("SELECT 1 FROM users WHERE user_id=?",(uid,)).fetchone():
            await state.clear(); return await m.answer("Пользователь должен сначала нажать /start")
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(amount,uid)); c.commit()
    await state.clear(); await m.answer(f"✅ Добавлено {money(amount)}$ пользователю {uid}")

@router.callback_query(F.data=="profile")
async def profile(c:CallbackQuery):
    ensure_user(c.from_user); u=user(c.from_user.id)
    await c.message.edit_text(f"👤 <b>Профиль</b>\n\nID: <code>{u['user_id']}</code>\nБаланс: <b>{money(u['balance'])}$</b>\nСделок: {u['deals']}",reply_markup=kb([[("🏠 Главное меню","home")]])); await c.answer()

@router.callback_query(F.data=="seller")
async def seller(c:CallbackQuery):
    ensure_user(c.from_user)
    if is_seller(c.from_user.id):
        await c.message.edit_text("💼 <b>Режим продавца</b>",reply_markup=sell_menu())
    else:
        await c.message.edit_text("Вход пока запрещен…\n\nЧтобы получить доступ отправьте заявку:",reply_markup=kb([[("📨 Отправить заявку","seller_apply")],[("🏠 Главное меню","home")]]))
    await c.answer()

@router.callback_query(F.data=="seller_apply")
async def seller_apply(c:CallbackQuery):
    ensure_user(c.from_user)
    with closing(db()) as con:
        cur=con.execute("INSERT INTO seller_requests(user_id,created_at) VALUES(?,?)",(c.from_user.id,now())); rid=cur.lastrowid; con.commit()
    await notify_admin(c.bot,f"🆕 Новый запрос на пост продавца\n\nИмя: {c.from_user.full_name}\nID: <code>{c.from_user.id}</code>",kb([[("✅ Одобрить",f"seller_ok:{rid}"),("❌ Отказать",f"seller_no:{rid}")]]))
    await c.message.edit_text("✅ Заявка отправлена.",reply_markup=kb([[("🏠 Главное меню","home")]])); await c.answer()

@router.callback_query(F.data.startswith("seller_ok:") | F.data.startswith("seller_no:"))
async def seller_dec(c:CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    action,rid=c.data.split(":"); ok=action=="seller_ok"
    with closing(db()) as con:
        r=con.execute("SELECT * FROM seller_requests WHERE id=?",(int(rid),)).fetchone()
        if not r: return await c.answer("Не найдено",show_alert=True)
        con.execute("UPDATE seller_requests SET status=? WHERE id=?",("approved" if ok else "rejected",rid))
        if ok: con.execute("UPDATE users SET seller=1 WHERE user_id=?",(r["user_id"],))
        con.commit()
    await c.message.edit_text(c.message.html_text+("\n\n✅ Одобрено" if ok else "\n\n❌ Отказано"))
    await c.bot.send_message(r["user_id"],"✅ Режим продавца открыт." if ok else "❌ Заявка отклонена."); await c.answer()

@router.callback_query(F.data=="add_item")
async def add_item(c:CallbackQuery,state:FSMContext):
    if not is_seller(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    await state.set_state(AddItem.phone); await c.message.answer("Отправьте номер: +79001234567 / 79001234567 / 89001234567"); await c.answer()

@router.message(AddItem.phone)
async def add_phone(m:Message,state:FSMContext):
    p=norm_phone(m.text)
    if not p: return await m.answer("❌ Неверный формат номера.")
    await state.update_data(phone=p); await state.set_state(AddItem.price); await m.answer("Введите цену в $:")

@router.message(AddItem.price)
async def add_price(m:Message,state:FSMContext):
    try:
        price=float(m.text.replace(",","."))
        if price<=0: raise ValueError
    except Exception: return await m.answer("Введите число больше 0")
    await state.update_data(price=price); await state.set_state(AddItem.desc); await m.answer("Введите описание:")

@router.message(AddItem.desc)
async def add_desc(m:Message,state:FSMContext):
    d=await state.get_data(); desc=(m.text or "")[:1000]
    with closing(db()) as con:
        cur=con.execute("INSERT INTO items(seller_id,phone,price,description,status,created_at) VALUES(?,?,?,?,?,?)",(m.from_user.id,d["phone"],d["price"],desc,"moderation",now())); iid=cur.lastrowid; con.commit()
    await state.clear()
    await notify_admin(m.bot,f"🆕 Товар на модерации\n\nID: {iid}\nПродавец: {m.from_user.id}\nНомер: <code>{d['phone']}</code>\nЦена: {money(d['price'])}$\nОписание: {desc}",kb([[("✅ Принять",f"item_ok:{iid}"),("❌ Отклонить",f"item_no:{iid}")]]))
    await m.answer("✅ Отправлено на модерацию.",reply_markup=sell_menu())

@router.callback_query(F.data.startswith("item_ok:") | F.data.startswith("item_no:"))
async def item_dec(c:CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    action,iid=c.data.split(":"); ok=action=="item_ok"
    with closing(db()) as con:
        it=con.execute("SELECT * FROM items WHERE id=?",(iid,)).fetchone()
        if not it: return await c.answer("Не найдено",show_alert=True)
        con.execute("UPDATE items SET status=? WHERE id=?",("active" if ok else "rejected",iid)); con.commit()
    await c.message.edit_text(c.message.html_text+("\n\n✅ Принято" if ok else "\n\n❌ Отклонено"))
    await c.bot.send_message(it["seller_id"],f"✅ Товар №{iid} выставлен." if ok else f"❌ Товар №{iid} отклонен."); await c.answer()

@router.callback_query(F.data=="market")
async def market(c:CallbackQuery):
    with closing(db()) as con:
        items=con.execute("SELECT * FROM items WHERE status='active' ORDER BY id DESC LIMIT 50").fetchall()
    rows=[[InlineKeyboardButton(text=f"{mask(i['phone'])} • {money(i['price'])}$",callback_data=f"item:{i['id']}")] for i in items]
    rows.append([InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")])
    await c.message.edit_text("🛒 <b>Маркет номеров</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()

@router.callback_query(F.data.startswith("item:"))
async def item(c:CallbackQuery):
    iid=int(c.data.split(":")[1])
    with closing(db()) as con: it=con.execute("SELECT * FROM items WHERE id=?",(iid,)).fetchone()
    if not it or it["status"]!="active": return await c.answer("Недоступно",show_alert=True)
    await c.message.edit_text(f"🧾 Товар №{iid}\n\nНомер: <code>{mask(it['phone'])}</code>\nЦена: <b>{money(it['price'])}$</b>\nОписание:\n{it['description']}",reply_markup=kb([[("🛒 Купить",f"buy:{iid}")],[("🏠 Главное меню","home")]])); await c.answer()

async def create_purchase(bot,buyer_id,iid):
    with closing(db()) as con:
        u=con.execute("SELECT * FROM users WHERE user_id=?",(buyer_id,)).fetchone()
        it=con.execute("SELECT * FROM items WHERE id=?",(iid,)).fetchone()
        if not u: return False,"Сначала нажмите /start"
        if not it or it["status"]!="active": return False,"Товар недоступен"
        if float(u["balance"])<float(it["price"]): return False,"Недостаточно средств"
        con.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(it["price"],buyer_id))
        con.execute("UPDATE items SET status='sold' WHERE id=?",(iid,))
        cur=con.execute("INSERT INTO orders(buyer_id,seller_id,item_id,phone,price,status,created_at) VALUES(?,?,?,?,?,?,?)",(buyer_id,it["seller_id"],iid,it["phone"],it["price"],"awaiting_code",now()))
        oid=cur.lastrowid; con.commit()
    await bot.send_message(it["seller_id"],f"🛒 У вас купили товар №{iid}.\nОтправьте внутренний код сделки: 6 цифр.",reply_markup=kb([[("🔐 Отправить код",f"send_code:{oid}")]]))
    await bot.send_message(buyer_id,f"✅ Покупка создана. Ожидаем код продавца.\nЗаказ №{oid}")
    return True,f"Покупка создана. Заказ №{oid}"

@router.callback_query(F.data.startswith("buy:"))
async def buy(c:CallbackQuery):
    ok,msg=await create_purchase(c.bot,c.from_user.id,int(c.data.split(":")[1]))
    await c.answer(msg,show_alert=not ok)
    if ok: await c.message.edit_text("✅ Покупка создана. Ожидайте код продавца.",reply_markup=kb([[("📦 Покупки","purchases")]]))

@router.callback_query(F.data.startswith("send_code:"))
async def send_code(c:CallbackQuery,state:FSMContext):
    oid=int(c.data.split(":")[1])
    with closing(db()) as con: o=con.execute("SELECT * FROM orders WHERE id=? AND seller_id=? AND status='awaiting_code'",(oid,c.from_user.id)).fetchone()
    if not o: return await c.answer("Заказ не найден",show_alert=True)
    await state.set_state(Code.code); await state.update_data(order_id=oid); await c.message.answer("Введите код: строго 6 цифр"); await c.answer()

@router.message(Code.code)
async def save_code(m:Message,state:FSMContext):
    code=(m.text or "").strip()
    if not re.fullmatch(r"\d{6}",code): return await m.answer("❌ Код должен быть ровно 6 цифр.")
    oid=(await state.get_data())["order_id"]
    with closing(db()) as con:
        o=con.execute("SELECT * FROM orders WHERE id=? AND seller_id=?",(oid,m.from_user.id)).fetchone()
        if not o: await state.clear(); return await m.answer("Заказ не найден")
        con.execute("UPDATE orders SET code=?,status='active' WHERE id=?",(code,oid)); con.commit()
    await state.clear(); await m.answer("✅ Код отправлен покупателю.")
    await m.bot.send_message(o["buyer_id"],f"📦 Заказ №{oid}\n\nНомер: <code>{o['phone']}</code>\nКод сделки: <code>{code}</code>",reply_markup=kb([[("✅ Подтвердить",f"confirm:{oid}"),("⚠️ Спор",f"dispute:{oid}")]]))

@router.callback_query(F.data=="purchases")
async def purchases(c:CallbackQuery):
    with closing(db()) as con: orders=con.execute("SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC LIMIT 50",(c.from_user.id,)).fetchall()
    rows=[[InlineKeyboardButton(text=f"#{o['id']} • {money(o['price'])}$ • {o['status']}",callback_data=f"order:{o['id']}")] for o in orders]
    rows.append([InlineKeyboardButton(text="🏠 Главное меню",callback_data="home")])
    await c.message.edit_text("📦 Покупки",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()

@router.callback_query(F.data.startswith("confirm:"))
async def confirm(c:CallbackQuery):
    oid=int(c.data.split(":")[1])
    with closing(db()) as con:
        o=con.execute("SELECT * FROM orders WHERE id=? AND buyer_id=? AND status='active'",(oid,c.from_user.id)).fetchone()
        if not o: return await c.answer("Нельзя подтвердить",show_alert=True)
        con.execute("UPDATE orders SET status='closed' WHERE id=?",(oid,))
        con.execute("UPDATE users SET balance=balance+?, deals=deals+1 WHERE user_id=?",(o["price"],o["seller_id"]))
        con.execute("UPDATE users SET deals=deals+1 WHERE user_id=?",(o["buyer_id"],)); con.commit()
    await c.message.edit_text("✅ Сделка закрыта. Деньги отправлены продавцу.",reply_markup=kb([[("🏠 Главное меню","home")]]))
    await c.bot.send_message(o["seller_id"],f"✅ Заказ №{oid} подтвержден. Зачислено {money(o['price'])}$"); await c.answer()

@router.callback_query(F.data.startswith("dispute:"))
async def dispute(c:CallbackQuery):
    oid=int(c.data.split(":")[1])
    with closing(db()) as con:
        o=con.execute("SELECT * FROM orders WHERE id=? AND buyer_id=?",(oid,c.from_user.id)).fetchone()
        if not o: return await c.answer("Не найдено",show_alert=True)
        con.execute("UPDATE orders SET status='dispute' WHERE id=?",(oid,)); con.commit()
    await notify_admin(c.bot,f"⚠️ Спор по заказу №{oid}\nПокупатель: {o['buyer_id']}\nПродавец: {o['seller_id']}\nСумма: {money(o['price'])}$",kb([[("✅ Продавец",f"win_seller:{oid}"),("↩️ Покупатель",f"win_buyer:{oid}")]]))
    await c.message.edit_text("⚠️ Спор открыт.",reply_markup=kb([[("🏠 Главное меню","home")]])); await c.answer()

@router.callback_query(F.data.startswith("win_seller:") | F.data.startswith("win_buyer:"))
async def win(c:CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer("Нет доступа",show_alert=True)
    act,oid=c.data.split(":"); seller_win=act=="win_seller"
    with closing(db()) as con:
        o=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
        if not o or o["status"]!="dispute": return await c.answer("Уже закрыто",show_alert=True)
        con.execute("UPDATE orders SET status='closed' WHERE id=?",(oid,))
        con.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(o["price"],o["seller_id"] if seller_win else o["buyer_id"])); con.commit()
    await c.message.edit_text(c.message.html_text+("\n\n✅ В сторону продавца" if seller_win else "\n\n✅ Возврат покупателю")); await c.answer()

@router.callback_query(F.data=="sales")
async def sales(c:CallbackQuery):
    with closing(db()) as con: orders=con.execute("SELECT * FROM orders WHERE seller_id=? ORDER BY id DESC",(c.from_user.id,)).fetchall()
    rows=[[InlineKeyboardButton(text=f"#{o['id']} • {o['status']}",callback_data="seller")] for o in orders]
    rows.append([InlineKeyboardButton(text="🏠 Назад",callback_data="seller")])
    await c.message.edit_text("📊 Продажи",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()

def verify_init_data(init_data):
    if not init_data: return False,{}
    data=dict(parse_qsl(init_data,keep_blank_values=True)); h=data.pop("hash","")
    if not h: return False,{}
    check="\n".join(f"{k}={v}" for k,v in sorted(data.items()))
    secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest()
    calc=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc,h): return False,{}
    return True,json.loads(data.get("user","{}") or "{}")

HTML="""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><script src="https://telegram.org/js/telegram-web-app.js"></script><style>
body{margin:0;background:radial-gradient(circle at 20% 0,#3b3009,transparent 35%),#070707;color:white;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial}.wrap{padding:18px 14px}.hero{border:1px solid #5c4a13;border-radius:24px;padding:20px;background:linear-gradient(135deg,#171203,#111);box-shadow:0 0 50px #000;animation:p 2.5s infinite}@keyframes p{50%{box-shadow:0 0 45px #493b12}}.logo{font-size:29px;font-weight:900}.gold{color:#ffd85a}.card{margin-top:12px;border:1px solid #262626;background:#121212;border-radius:20px;padding:15px;animation:u .4s forwards;opacity:0;transform:translateY(10px)}@keyframes u{to{opacity:1;transform:none}}.row{display:flex;justify-content:space-between}.price{color:#ffd85a;font-weight:900}.btn{width:100%;margin-top:12px;padding:14px;border:0;border-radius:15px;background:linear-gradient(90deg,#ffd85a,#fff0a0);font-weight:900}.muted{color:#aaa;font-size:13px}.toast{position:fixed;left:12px;right:12px;bottom:14px;background:white;color:#111;border-radius:15px;padding:14px;text-align:center;font-weight:900;display:none}</style></head><body><div class="wrap"><div class="hero"><div class="logo">💎 Diamond <span class="gold">Market</span></div><div class="muted">Покупка прямо в Mini App. Код сделки — внутренние 6 цифр продавца.</div></div><div id="list"></div></div><div id="toast" class="toast"></div><script>
const tg=window.Telegram?.WebApp; tg?.expand(); function toast(t){toastEl=document.getElementById('toast');toastEl.textContent=t;toastEl.style.display='block';setTimeout(()=>toastEl.style.display='none',2500)}
async function load(){let r=await fetch('/api/items');let d=await r.json();let l=document.getElementById('list');l.innerHTML='';if(!d.items.length){l.innerHTML='<div class="card muted">Пока нет товаров</div>';return}d.items.forEach((p,i)=>{let e=document.createElement('div');e.className='card';e.style.animationDelay=(i*.05)+'s';e.innerHTML=`<div class="row"><b>${p.phone}</b><span class="price">${p.price}$</span></div><div class="muted">${p.description||''}</div><button class="btn" onclick="buy(${p.id})">Купить</button>`;l.appendChild(e)})}
async function buy(id){if(!tg?.initData){location.href='https://t.me/BOT_USERNAME_PLACEHOLDER?start=buy_'+id;return}let r=await fetch('/api/buy',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({initData:tg.initData,item_id:id})});let d=await r.json();toast(d.message||'Готово');if(d.ok)load()} load();
</script></body></html>"""

async def index(req): return web.Response(text=HTML.replace("BOT_USERNAME_PLACEHOLDER",BOT_USERNAME),content_type="text/html")
async def api_items(req):
    with closing(db()) as con: items=con.execute("SELECT * FROM items WHERE status='active' ORDER BY id DESC").fetchall()
    return web.json_response({"items":[{"id":i["id"],"phone":mask(i["phone"]),"price":money(i["price"]),"description":i["description"]} for i in items]})
async def api_buy(req):
    bot=req.app["bot"]; data=await req.json(); ok,u=verify_init_data(data.get("initData",""))
    if not ok: return web.json_response({"ok":False,"message":"Ошибка Mini App авторизации"})
    class U: pass
    x=U(); x.id=int(u["id"]); x.username=u.get("username",""); x.full_name=(u.get("first_name","")+" "+u.get("last_name","")).strip()
    ensure_user(x)
    ok,msg=await create_purchase(bot,x.id,int(data["item_id"]))
    return web.json_response({"ok":ok,"message":msg})
async def health(req): return web.json_response({"ok":True,"bot":BOT_USERNAME})
async def start_web(bot):
    app=web.Application(); app["bot"]=bot
    app.add_routes([web.get("/",index),web.get("/api/items",api_items),web.post("/api/buy",api_buy),web.get("/health",health)])
    r=web.AppRunner(app); await r.setup(); await web.TCPSite(r,"0.0.0.0",PORT).start()

async def main():
    global BOT_USERNAME
    init_db()
    bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me=await bot.get_me(); BOT_USERNAME=me.username or ""
    dp=Dispatcher(storage=MemoryStorage()); dp.include_router(router)
    await start_web(bot)
    await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())

if __name__=="__main__": asyncio.run(main())
