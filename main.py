import asyncio, os, time, sqlite3, logging, uuid
from datetime import datetime
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN=os.getenv('BOT_TOKEN','').strip(); ADMIN_GROUP_ID=int(os.getenv('ADMIN_GROUP_ID','0') or 0)
ADMIN_IDS={int(x) for x in os.getenv('ADMIN_IDS','').replace(' ','').split(',') if x}
WEBAPP_URL=os.getenv('WEBAPP_URL','').strip(); DB_PATH=os.getenv('DB_PATH','market.db'); PORT=int(os.getenv('PORT','8080'))
CRYPTO_PAY_TOKEN=os.getenv('CRYPTO_PAY_TOKEN','').strip(); CRYPTO_ASSET=os.getenv('CRYPTO_ASSET','USDT').upper(); CRYPTO_HOST='testnet-pay.crypt.bot' if os.getenv('CRYPTO_PAY_TESTNET','0')=='1' else 'pay.crypt.bot'
if not BOT_TOKEN: raise RuntimeError('BOT_TOKEN missing')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
BOT_USERNAME=''

def ts(): return int(time.time())
def dt(x): return datetime.fromtimestamp(x).strftime('%d.%m.%Y %H:%M') if x else '-'
def cash(x): return (f'{float(x):.2f}').rstrip('0').rstrip('.')
def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    with db() as c:
        c.executescript('''
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, balance REAL DEFAULT 0, frozen REAL DEFAULT 0, total_deposit REAL DEFAULT 0, deals INTEGER DEFAULT 0, reg_at INTEGER);
CREATE TABLE IF NOT EXISTS sellers(user_id INTEGER PRIMARY KEY, approved INTEGER DEFAULT 0, approved_at INTEGER, earned REAL DEFAULT 0, sold_qty INTEGER DEFAULT 0, deals INTEGER DEFAULT 0, disputes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS seller_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'pending', created_at INTEGER);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, category TEXT, price REAL, qty INTEGER, description TEXT, content_type TEXT, content_value TEXT, status TEXT DEFAULT 'moderation', created_at INTEGER);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, seller_id INTEGER, product_id INTEGER, category TEXT, qty INTEGER, price REAL, total REAL, description TEXT, content_type TEXT, content_value TEXT, status TEXT DEFAULT 'active', created_at INTEGER, arbitration_sent_at INTEGER);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, invoice_id TEXT, pay_url TEXT, status TEXT DEFAULT 'created');
''')

def ensure(u):
    with db() as c: c.execute('INSERT INTO users(user_id,username,name,reg_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,name=excluded.name',(u.id,u.username or '',u.full_name or '',ts()))
def user(uid):
    with db() as c: return c.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
def admin(uid): return uid in ADMIN_IDS
def seller(uid):
    with db() as c:
        r=c.execute('SELECT approved FROM sellers WHERE user_id=?',(uid,)).fetchone(); return bool(r and r['approved'])
def link(x):
    uid=x['user_id'] if isinstance(x,sqlite3.Row) else x.id; un=x['username'] if isinstance(x,sqlite3.Row) else x.username; nm=x['name'] if isinstance(x,sqlite3.Row) else x.full_name
    return '@'+un if un else f"<a href='tg://user?id={uid}'>{nm}</a>"
def kb(rows): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t,callback_data=d) for t,d in r] for r in rows])
def buyer_kb():
    rows=[[InlineKeyboardButton(text='🛒 Маркет',callback_data='market')],[InlineKeyboardButton(text='👤 Профиль',callback_data='profile'),InlineKeyboardButton(text='📦 Покупки',callback_data='purchases')],[InlineKeyboardButton(text='💼 Режим продавца',callback_data='seller_mode')]]
    if WEBAPP_URL: rows.append([InlineKeyboardButton(text='🌐 Mini App',web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def seller_kb(): return kb([[('➕ Выставить товар','sell_add')],[('👤 Профиль','seller_profile'),('📊 Продажи','sales')],[('🛒 Режим покупателя','buyer_home')]])
def pname(p,s):
    n=s['name'] or s['username'] or str(s['user_id'])
    return f"({cash(p['price'])}$){n}({p['qty']})" if p['category']=='selfreg' else f"({p['qty']}){n}"

class Add(StatesGroup): cat=State(); price=State(); qty=State(); desc=State(); content=State()
class Buy(StatesGroup): qty=State()
class Dep(StatesGroup): amount=State()
class Wd(StatesGroup): amount=State()
class Adm(StatesGroup): link=State(); refund=State()

dp=Dispatcher(storage=MemoryStorage())
async def crypto(method,payload):
    if not CRYPTO_PAY_TOKEN: raise RuntimeError('CRYPTO_PAY_TOKEN не настроен')
    async with ClientSession() as s:
        async with s.post(f'https://{CRYPTO_HOST}/api/{method}',headers={'Crypto-Pay-API-Token':CRYPTO_PAY_TOKEN},json=payload) as r:
            data=await r.json(content_type=None)
            if not data.get('ok'): raise RuntimeError(str(data))
            return data['result']

@dp.message(CommandStart())
async def start(m:Message,state:FSMContext):
    await state.clear(); ensure(m.from_user); await m.answer('💎 <b>Diamond Market</b>\n\nВыберите раздел:',reply_markup=buyer_kb())
@dp.message(Command('admin'))
async def admcmd(m:Message):
    if not admin(m.from_user.id): return await m.answer('⛔️ Нет доступа')
    with db() as c:
        a=c.execute("SELECT COUNT(*) c FROM seller_requests WHERE status='pending'").fetchone()['c']; b=c.execute("SELECT COUNT(*) c FROM products WHERE status='moderation'").fetchone()['c']; d=c.execute("SELECT COUNT(*) c FROM orders WHERE status='dispute'").fetchone()['c']
    await m.answer(f'🛡 Админ-панель\n\nЗаявки продавцов: {a}\nТовары на модерации: {b}\nСпоры: {d}')

@dp.callback_query(F.data=='buyer_home')
async def bh(c:CallbackQuery,state:FSMContext): await state.clear(); await c.message.edit_text('💎 <b>Diamond Market</b>\n\nВыберите раздел:',reply_markup=buyer_kb()); await c.answer()
@dp.callback_query(F.data=='seller_home')
async def sh(c:CallbackQuery,state:FSMContext):
    await state.clear()
    if not seller(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    await c.message.edit_text('💼 <b>Режим продавца</b>\n\nВыберите действие:',reply_markup=seller_kb()); await c.answer()
@dp.callback_query(F.data=='seller_mode')
async def sm(c:CallbackQuery):
    ensure(c.from_user)
    if seller(c.from_user.id): await c.message.edit_text('💼 <b>Режим продавца</b>\n\nВыберите действие:',reply_markup=seller_kb())
    else: await c.message.edit_text('💼 <b>Вход пока запрещен…</b>\n\nЧтобы получить доступ отправьте заявку:',reply_markup=kb([[('📨 Отправить Заявку','seller_apply')],[('🏠 Главное меню','buyer_home')]]))
    await c.answer()
@dp.callback_query(F.data=='seller_apply')
async def apply(c:CallbackQuery):
    ensure(c.from_user)
    with db() as d:
        cur=d.execute('INSERT INTO seller_requests(user_id,created_at) VALUES(?,?)',(c.from_user.id,ts())); rid=cur.lastrowid
    text=f'🆕 Новый запрос на пост Продавца\n\n1. Никнейм: {c.from_user.full_name}\n2. Юзер: {link(c.from_user)}\n3. Айди: <code>{c.from_user.id}</code>'
    mark=kb([[('✅ Одобрить',f'seller_ok:{rid}'),('❌ Отказать',f'seller_no:{rid}')]])
    if ADMIN_GROUP_ID: await c.bot.send_message(ADMIN_GROUP_ID,text,reply_markup=mark)
    else:
        for a in ADMIN_IDS: await c.bot.send_message(a,text,reply_markup=mark)
    await c.message.edit_text('✅ Заявка отправлена.',reply_markup=kb([[('🏠 Главное меню','buyer_home')]])); await c.answer()
@dp.callback_query(F.data.startswith('seller_'))
async def seller_dec(c:CallbackQuery):
    if not admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    act,rid=c.data.split(':'); ok=act=='seller_ok'
    with db() as d:
        r=d.execute('SELECT * FROM seller_requests WHERE id=?',(rid,)).fetchone()
        if not r or r['status']!='pending': return await c.answer('Уже обработано',show_alert=True)
        d.execute('UPDATE seller_requests SET status=? WHERE id=?',('approved' if ok else 'rejected',rid))
        if ok: d.execute('INSERT OR REPLACE INTO sellers(user_id,approved,approved_at) VALUES(?,?,?)',(r['user_id'],1,ts()))
    await c.bot.send_message(r['user_id'],'✅ Вход в режим продавца открыт!' if ok else '❌ Вход отказан.'); await c.message.edit_text(c.message.html_text+('\n\n✅ Одобрено' if ok else '\n\n❌ Отказано')); await c.answer()

@dp.callback_query(F.data=='market')
async def market(c): await c.message.edit_text('🛒 Маркет\n\nВыберите категорию:',reply_markup=kb([[('🎣 Фиш','cat:fish'),('🧾 Саморег','cat:selfreg')],[('🏠 Главное меню','buyer_home')]])); await c.answer()
@dp.callback_query(F.data.startswith('cat:'))
async def cat(c):
    cat=c.data.split(':')[1]
    rows=[[InlineKeyboardButton(text='🔎 Фильтры',callback_data='filters')]]
    with db() as d: ps=d.execute("SELECT p.*,u.name,u.username,u.user_id FROM products p JOIN users u ON u.user_id=p.seller_id WHERE p.category=? AND p.status='active' AND p.qty>0",(cat,)).fetchall()
    for p in ps: rows.append([InlineKeyboardButton(text=pname(p,p),callback_data=f'prod:{p["id"]}')])
    rows.append([InlineKeyboardButton(text='⬅️ Назад',callback_data='market'),InlineKeyboardButton(text='🏠 Главное меню',callback_data='buyer_home')])
    await c.message.edit_text(('🎣 Фиш' if cat=='fish' else '🧾 Саморег'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()
@dp.callback_query(F.data=='filters')
async def filt(c): await c.answer('Показаны все активные товары.',show_alert=True)
@dp.callback_query(F.data.startswith('prod:'))
async def prod(c,state):
    pid=int(c.data.split(':')[1])
    with db() as d:
        p=d.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); s=d.execute('SELECT * FROM users WHERE user_id=?',(p['seller_id'],)).fetchone() if p else None
    if not p or p['status']!='active': return await c.answer('Товар недоступен',show_alert=True)
    await c.message.edit_text(f"🧾 <b>{pname(p,s)}</b>\n\nНикнейм: {s['name']}\nКоличество токенов: {p['qty']}\nЦена: {cash(p['price'])}$\nОписание:\n{p['description']}",reply_markup=kb([[('🛒 Купить',f'buy:{pid}')],[('⬅️ Назад',f'cat:{p["category"]}'),('🏠 Главное меню','buyer_home')]])); await c.answer()
@dp.callback_query(F.data.startswith('buy:'))
async def buy(c,state): await state.set_state(Buy.qty); await state.update_data(pid=int(c.data.split(':')[1])); await c.message.answer('Введите кол-во:'); await c.answer()
@dp.message(Buy.qty)
async def buy_qty(m,state):
    ensure(m.from_user)
    try: q=int(m.text); assert q>0
    except: return await m.answer('Введите число больше 0')
    data=await state.get_data(); pid=data['pid']
    with db() as d:
        p=d.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); u=d.execute('SELECT * FROM users WHERE user_id=?',(m.from_user.id,)).fetchone()
        if not p or p['qty']<q: await state.clear(); return await m.answer('Недостаточно товара')
        total=p['price']*q
        if u['balance']<total: return await m.answer(f'Недостаточно средств, пополните счет!\nСумма: {cash(total)}$\nВаш баланс: {cash(u["balance"])}$')
        d.execute('UPDATE users SET balance=balance-?,frozen=frozen+?,deals=deals+1 WHERE user_id=?',(total,total,m.from_user.id)); d.execute('UPDATE products SET qty=qty-? WHERE id=?',(q,pid))
        cur=d.execute('INSERT INTO orders(buyer_id,seller_id,product_id,category,qty,price,total,description,content_type,content_value,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(m.from_user.id,p['seller_id'],pid,p['category'],q,p['price'],total,p['description'],p['content_type'],p['content_value'],ts())); oid=cur.lastrowid
    await state.clear(); await m.answer(f'✅ Покупка создана. Деньги заморожены. Заказ №{oid}',reply_markup=kb([[('📦 Покупки','purchases')]])); await m.bot.send_message(p['seller_id'],f'У вас купили {q} на сумму {cash(total)}$ Ожидание подтверждения оплаты…')

@dp.callback_query(F.data=='purchases')
async def purchases(c):
    with db() as d: os_=d.execute('SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC',(c.from_user.id,)).fetchall()
    rows=[[InlineKeyboardButton(text=f"#{o['id']} • {cash(o['total'])}$ • {o['status']}",callback_data=f"order:{o['id']}")] for o in os_]; rows.append([InlineKeyboardButton(text='🏠 Главное меню',callback_data='buyer_home')])
    await c.message.edit_text('📦 Покупки',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()
async def send_item(bot,uid,o):
    if o['content_type']=='photo': await bot.send_photo(uid,o['content_value'],caption='📎 Проданный товар')
    elif o['content_type']=='document': await bot.send_document(uid,o['content_value'],caption='📎 Проданный товар')
    else: await bot.send_message(uid,'📎 Проданный товар:\n\n'+(o['content_value'] or 'Нет'))
@dp.callback_query(F.data.startswith('order:'))
async def order(c):
    oid=int(c.data.split(':')[1])
    with db() as d:
        o=d.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone(); s=d.execute('SELECT * FROM users WHERE user_id=?',(o['seller_id'],)).fetchone() if o else None
    if not o: return await c.answer('Не найдено',show_alert=True)
    await send_item(c.bot,c.from_user.id,o)
    rows=[]
    if o['status']=='active': rows.append([InlineKeyboardButton(text='✅ Закрыть сделку',callback_data=f'close:{oid}'),InlineKeyboardButton(text='⚠️ Открыть спор',callback_data=f'dispute:{oid}')])
    rows.append([InlineKeyboardButton(text='⬅️ Покупки',callback_data='purchases')])
    await c.message.answer(f"Сделка №{oid}\nПродавец: {s['name']}\nЦена: {cash(o['price'])}$\nКол-во: {o['qty']}\nСтатус: {o['status']}",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()
@dp.callback_query(F.data.startswith('close:'))
async def close(c):
    oid=int(c.data.split(':')[1])
    with db() as d:
        o=d.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone()
        if not o or o['status']!='active': return await c.answer('Нельзя закрыть',show_alert=True)
        d.execute("UPDATE orders SET status='closed' WHERE id=?",(oid,)); d.execute('UPDATE users SET frozen=frozen-? WHERE user_id=?',(o['total'],o['buyer_id'])); d.execute('UPDATE users SET balance=balance+?,deals=deals+1 WHERE user_id=?',(o['total'],o['seller_id'])); d.execute('UPDATE sellers SET earned=earned+?,sold_qty=sold_qty+?,deals=deals+1 WHERE user_id=?',(o['total'],o['qty'],o['seller_id']))
    await c.message.edit_text('✅ Сделка закрыта. Деньги отправлены продавцу.'); await c.bot.send_message(o['seller_id'],f'✅ Сделка №{oid} закрыта. Зачислено {cash(o["total"])}$'); await c.answer()
@dp.callback_query(F.data.startswith('dispute:'))
async def dispute(c):
    oid=int(c.data.split(':')[1])
    with db() as d:
        o=d.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone(); b=d.execute('SELECT * FROM users WHERE user_id=?',(o['buyer_id'],)).fetchone(); s=d.execute('SELECT * FROM users WHERE user_id=?',(o['seller_id'],)).fetchone(); d.execute("UPDATE orders SET status='dispute' WHERE id=?",(oid,)); d.execute('UPDATE sellers SET disputes=disputes+1 WHERE user_id=?',(o['seller_id'],))
    text=f"⚠️ Спор между Продавцом и Покупателем открыт, Ожидание ссылки\nПокупатель: {link(b)}\nПродавец: {link(s)}\nЗаказ №{oid}\nЦена: {cash(o['price'])}$\nКол-во токенов: {o['qty']}\nОписание:\n{o['description']}"
    mark=kb([[('🔗 Отправить ссылку',f'alink:{oid}')],[('✅ Продавец',f'rseller:{oid}'),('↩️ Покупатель',f'rbuyer:{oid}')]])
    if ADMIN_GROUP_ID: await c.bot.send_message(ADMIN_GROUP_ID,text,reply_markup=mark)
    else:
        for a in ADMIN_IDS: await c.bot.send_message(a,text,reply_markup=mark)
    await c.message.edit_text('⚠️ Спор открыт.'); await c.answer()
@dp.callback_query(F.data.startswith('alink:'))
async def alink(c,state):
    if not admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    await state.set_state(Adm.link); await state.update_data(oid=int(c.data.split(':')[1])); await c.message.answer('Отправьте ссылку на Арбитраж:'); await c.answer()
@dp.message(Adm.link)
async def save_link(m,state):
    data=await state.get_data(); oid=data['oid']; l=m.text.strip()
    with db() as d: o=d.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); d.execute('UPDATE orders SET arbitration_sent_at=? WHERE id=?',(ts(),oid))
    url=l if l.startswith('http') else 'https://'+l
    mark=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Войти',url=url)]])
    note='Вас пригласили в чат «Арбитраж» зайдите чтобы решить вашу проблему с Админами бота!\nПримечание: Если в течении 6 часов кто-то не зайдет, сделка будет закрыта автоматически, без права на апелляцию'
    await m.bot.send_message(o['buyer_id'],note,reply_markup=mark); await m.bot.send_message(o['seller_id'],note,reply_markup=mark); await state.clear(); await m.answer('✅ Ссылка отправлена')
@dp.callback_query(F.data.startswith('rseller:'))
async def rseller(c):
    if not admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    oid=int(c.data.split(':')[1])
    with db() as d:
        o=d.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); d.execute("UPDATE orders SET status='closed' WHERE id=?",(oid,)); d.execute('UPDATE users SET frozen=frozen-? WHERE user_id=?',(o['total'],o['buyer_id'])); d.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(o['total'],o['seller_id']))
    await c.message.edit_text(c.message.html_text+'\n\n✅ Решение: продавец'); await c.answer()
@dp.callback_query(F.data.startswith('rbuyer:'))
async def rbuyer(c,state):
    if not admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    await state.set_state(Adm.refund); await state.update_data(oid=int(c.data.split(':')[1])); await c.message.answer('Какую сумму вернуть покупателю?'); await c.answer()
@dp.message(Adm.refund)
async def refund(m,state):
    amount=float(m.text.replace(',','.')); data=await state.get_data(); oid=data['oid']
    with db() as d:
        o=d.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); amount=max(0,min(amount,o['total'])); d.execute("UPDATE orders SET status='closed' WHERE id=?",(oid,)); d.execute('UPDATE users SET frozen=frozen-?,balance=balance+? WHERE user_id=?',(o['total'],amount,o['buyer_id']))
    await state.clear(); await m.answer(f'✅ Покупателю возвращено {cash(amount)}$')

@dp.callback_query(F.data=='profile')
async def profile(c):
    ensure(c.from_user); u=user(c.from_user.id)
    await c.message.edit_text(f"👤 Профиль\nНикнейм: {u['name']}\nАйди: <code>{u['user_id']}</code>\nВсего сделок: {u['deals']}\nОбщая сумма пополнения: {cash(u['total_deposit'])}$\nДата регистрации: {dt(u['reg_at'])}\nБаланс: {cash(u['balance'])}$\nЗаморожено: {cash(u['frozen'])}$",reply_markup=kb([[('➕ Пополнить','deposit'),('➖ Вывести','withdraw')],[('🏠 Главное меню','buyer_home')]])); await c.answer()
@dp.callback_query(F.data=='deposit')
async def dep(c,state): await state.set_state(Dep.amount); await c.message.answer(f'Введите сумму пополнения в {CRYPTO_ASSET}:'); await c.answer()
@dp.message(Dep.amount)
async def dep_amount(m,state):
    amount=float(m.text.replace(',','.'))
    inv=await crypto('createInvoice',{'asset':CRYPTO_ASSET,'amount':str(amount),'payload':str(m.from_user.id),'description':'Diamond Market','expires_in':3600}); iid=str(inv['invoice_id']); url=inv.get('bot_invoice_url') or inv.get('web_app_invoice_url')
    with db() as d: d.execute('INSERT INTO invoices(user_id,amount,invoice_id,pay_url) VALUES(?,?,?,?)',(m.from_user.id,amount,iid,url))
    await state.clear(); await m.answer('✅ Счет создан',reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💳 Оплатить',url=url)],[InlineKeyboardButton(text='🔄 Проверить оплату',callback_data=f'check:{iid}')]]))
@dp.callback_query(F.data.startswith('check:'))
async def check(c):
    iid=c.data.split(':')[1]
    with db() as d: inv=d.execute('SELECT * FROM invoices WHERE invoice_id=?',(iid,)).fetchone()
    res=await crypto('getInvoices',{'invoice_ids':iid}); paid=bool(res.get('items') and res['items'][0].get('status')=='paid')
    if not paid: return await c.answer('Оплата пока не найдена',show_alert=True)
    with db() as d: d.execute("UPDATE invoices SET status='paid' WHERE invoice_id=?",(iid,)); d.execute('UPDATE users SET balance=balance+?,total_deposit=total_deposit+? WHERE user_id=?',(inv['amount'],inv['amount'],c.from_user.id))
    await c.message.edit_text('✅ Баланс пополнен'); await c.answer()
@dp.callback_query(F.data=='withdraw')
async def wd(c,state): await state.set_state(Wd.amount); await c.message.answer('Введите сумму вывода:'); await c.answer()
@dp.message(Wd.amount)
async def wd_amount(m,state):
    amount=float(m.text.replace(',','.')); u=user(m.from_user.id)
    if u['balance']<amount: return await m.answer('Недостаточно средств')
    with db() as d: d.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(amount,m.from_user.id))
    try: await crypto('transfer',{'user_id':m.from_user.id,'asset':CRYPTO_ASSET,'amount':str(amount),'spend_id':str(uuid.uuid4())})
    except Exception as e:
        with db() as d: d.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(amount,m.from_user.id))
        return await m.answer('Ошибка вывода, деньги возвращены: '+str(e)[:200])
    await state.clear(); await m.answer('✅ Вывод создан')

@dp.callback_query(F.data=='sell_add')
async def sell_add(c,state):
    if not seller(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    await state.set_state(Add.cat); await c.message.edit_text('Какой товар?',reply_markup=kb([[('Саморег','newcat:selfreg'),('Фиш','newcat:fish')],[('🏠 Главное меню','seller_home')]])); await c.answer()
@dp.callback_query(F.data.startswith('newcat:'),Add.cat)
async def newcat(c,state): await state.update_data(cat=c.data.split(':')[1]); await state.set_state(Add.price); await c.message.answer('Введите цену:'); await c.answer()
@dp.message(Add.price)
async def price(m,state): await state.update_data(price=float(m.text.replace(',','.'))); await state.set_state(Add.qty); await m.answer('Введите кол-во:')
@dp.message(Add.qty)
async def qty(m,state): await state.update_data(qty=int(m.text)); await state.set_state(Add.desc); await m.answer('Введите Описание товара:\nПримечание: Если в описании будет не указана или указана не полностью информация требующаяся для покупателя, открыв спор вы можете потерять деньги!')
@dp.message(Add.desc)
async def desc(m,state): await state.update_data(desc=m.text or ''); await state.set_state(Add.content); await m.answer('Отправьте товар: текст, фото или документ')
@dp.message(Add.content)
async def content(m,state):
    ctype='text'; val=m.text or ''
    if m.photo: ctype='photo'; val=m.photo[-1].file_id
    elif m.document: ctype='document'; val=m.document.file_id
    data=await state.get_data()
    with db() as d: cur=d.execute('INSERT INTO products(seller_id,category,price,qty,description,content_type,content_value,created_at) VALUES(?,?,?,?,?,?,?,?)',(m.from_user.id,data['cat'],data['price'],data['qty'],data['desc'],ctype,val,ts())); pid=cur.lastrowid
    txt=f"🆕 Новый товар на модерации\nID: {pid}\nПродавец: {link(m.from_user)}\nКатегория: {data['cat']}\nЦена: {cash(data['price'])}$\nКол-во: {data['qty']}\nОписание:\n{data['desc']}"
    mark=kb([[('✅ Принять',f'pok:{pid}'),('❌ Отклонить',f'pno:{pid}')]])
    if ADMIN_GROUP_ID: await m.bot.send_message(ADMIN_GROUP_ID,txt,reply_markup=mark)
    else:
        for a in ADMIN_IDS: await m.bot.send_message(a,txt,reply_markup=mark)
    await state.clear(); await m.answer('✅ Товар отправлен на модерацию.',reply_markup=seller_kb())
@dp.callback_query(F.data.startswith(('pok:','pno:')))
async def pdec(c):
    if not admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    ok=c.data.startswith('pok:'); pid=int(c.data.split(':')[1])
    with db() as d: p=d.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone(); d.execute('UPDATE products SET status=? WHERE id=?',('active' if ok else 'rejected',pid))
    await c.bot.send_message(p['seller_id'],f'✅ Ваш товар №{pid} принят.' if ok else 'Ваше объявление было отклонено администрацией, обратитесь в поддержку, либо под корректируйте объявление!')
    await c.message.edit_text(c.message.html_text+('\n\n✅ Принято' if ok else '\n\n❌ Отклонено')); await c.answer()
@dp.callback_query(F.data=='seller_profile')
async def sp(c):
    u=user(c.from_user.id)
    with db() as d: s=d.execute('SELECT * FROM sellers WHERE user_id=?',(c.from_user.id,)).fetchone()
    await c.message.edit_text(f"👤 Профиль продавца\nИмя: {u['name']}\nЮзер: {link(u)}\nАйди: {u['user_id']}\nБаланс: {cash(u['balance'])}$\nДата регистрации продавцом: {dt(s['approved_at'])}",reply_markup=kb([[('➖ Вывести','withdraw'),('📊 Статистика','seller_stats')],[('🏠 Главное меню','seller_home')]])); await c.answer()
@dp.callback_query(F.data=='seller_stats')
async def st(c):
    with db() as d: s=d.execute('SELECT * FROM sellers WHERE user_id=?',(c.from_user.id,)).fetchone()
    await c.message.edit_text(f"📊 Статистика\nКол-во сделок: {s['deals']}\nВсего заработано: {cash(s['earned'])}$\nКол-во проданных токенов: {s['sold_qty']}\nВсего споров: {s['disputes']}",reply_markup=kb([[('🏠 Главное меню','seller_home')]])); await c.answer()
@dp.callback_query(F.data=='sales')
async def sales(c):
    with db() as d: os_=d.execute('SELECT * FROM orders WHERE seller_id=?',(c.from_user.id,)).fetchall()
    rows=[[InlineKeyboardButton(text=f"#{o['id']} • статус: {o['status']}",callback_data=f"sale:{o['id']}")] for o in os_]; rows.append([InlineKeyboardButton(text='🏠 Главное меню',callback_data='seller_home')])
    await c.message.edit_text('📊 Продажи',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await c.answer()
@dp.callback_query(F.data.startswith('sale:'))
async def sale(c): await c.answer('В продажах показан только статус сделки.',show_alert=True)

async def auto_close(bot):
    while True:
        with db() as d:
            rows=d.execute("SELECT * FROM orders WHERE status='dispute' AND arbitration_sent_at IS NOT NULL AND arbitration_sent_at<?",(ts()-21600,)).fetchall()
            for o in rows:
                d.execute("UPDATE orders SET status='closed' WHERE id=?",(o['id'],)); d.execute('UPDATE users SET frozen=frozen-? WHERE user_id=?',(o['total'],o['buyer_id'])); d.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(o['total'],o['seller_id']))
        await asyncio.sleep(300)

HTML='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><script src="https://telegram.org/js/telegram-web-app.js"></script><style>body{background:#070707;color:#fff;font-family:-apple-system,Arial;margin:0}.wrap{padding:16px}.hero{background:linear-gradient(135deg,#2a2105,#111,#310a14);border:1px solid #f5c54255;border-radius:24px;padding:20px}.gold{color:#f5c542}.tab,.btn{border:0;border-radius:14px;padding:13px;font-weight:900}.tab{background:#111;color:#fff;border:1px solid #333}.btn{background:#f5c542;color:#111;width:100%}.card{background:#111;border:1px solid #292929;border-radius:18px;padding:14px;margin:10px 0}.muted{color:#aaa}</style></head><body><div class="wrap"><div class="hero"><h1>💎 Diamond <span class="gold">Market</span></h1><p class="muted">Маркет с гарантом и арбитражем.</p></div><p><button class="tab" onclick="cat='fish';load()">🎣 Фиш</button> <button class="tab" onclick="cat='selfreg';load()">🧾 Саморег</button></p><div id="list"></div></div><script>Telegram.WebApp?.expand();let cat='fish';async function load(){let r=await fetch('/api/products?category='+cat),d=await r.json(),l=document.getElementById('list');l.innerHTML='';if(!d.items.length)l.innerHTML='<p class=muted>Пока нет товаров</p>';d.items.forEach(p=>{l.innerHTML+=`<div class=card><b>${p.title}</b><p class=muted>${p.seller} • ${p.qty} шт • ${p.price}$</p><p>${p.description}</p><button class=btn onclick="Telegram.WebApp.openTelegramLink('https://t.me/${d.bot}?start=product_${p.id}')">Купить в боте</button></div>`})}load()</script></body></html>'''
async def index(r): return web.Response(text=HTML,content_type='text/html')
async def api(r):
    cat=r.query.get('category','fish')
    with db() as d: rows=d.execute("SELECT p.*,u.name,u.username,u.user_id FROM products p JOIN users u ON u.user_id=p.seller_id WHERE p.category=? AND p.status='active' AND p.qty>0",(cat,)).fetchall()
    return web.json_response({'bot':BOT_USERNAME,'items':[{'id':x['id'],'title':pname(x,x),'seller':x['name'] or x['username'],'price':cash(x['price']),'qty':x['qty'],'description':x['description']} for x in rows]})
async def start_web():
    app=web.Application(); app.add_routes([web.get('/',index),web.get('/api/products',api)]); runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',PORT).start()
async def main():
    global BOT_USERNAME
    init_db(); bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML)); me=await bot.get_me(); BOT_USERNAME=me.username or ''; await start_web(); asyncio.create_task(auto_close(bot)); await dp.start_polling(bot)
if __name__=='__main__': asyncio.run(main())
