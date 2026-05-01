import asyncio, hashlib, hmac, json, logging, os, re, sqlite3, time
from contextlib import closing
from datetime import datetime
from urllib.parse import parse_qsl

from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN missing')
ADMIN_IDS = {int(x) for x in os.getenv('ADMIN_IDS', '').replace(' ', '').split(',') if x}
ADMIN_GROUP_ID = int(os.getenv('ADMIN_GROUP_ID', '0') or 0)
WEBAPP_URL = os.getenv('WEBAPP_URL', '').strip()
DB_PATH = os.getenv('DB_PATH', 'market.db')
PORT = int(os.getenv('PORT', '8080'))
CRYPTO_PAY_TOKEN = os.getenv('CRYPTO_PAY_TOKEN', '').strip()
CRYPTO_ASSET = os.getenv('CRYPTO_ASSET', 'USDT').strip().upper()
DEPOSIT_FEE_PERCENT = float(os.getenv('DEPOSIT_FEE_PERCENT', '6') or 6)
CRYPTO_PAY_TESTNET = os.getenv('CRYPTO_PAY_TESTNET', '0').strip() == '1'
CRYPTO_API_HOST = 'testnet-pay.crypt.bot' if CRYPTO_PAY_TESTNET else 'pay.crypt.bot'
CRYPTO_API = f'https://{CRYPTO_API_HOST}/api'
BOT_USERNAME = ''

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('diamond-market-v3')
router = Router()

PHONE_RE = re.compile(r'^(?:\+7|7|8)\d{10}$')
CODE_RE = re.compile(r'^\d{6}$')

def ts(): return int(time.time())
def dtime(x): return datetime.fromtimestamp(x).strftime('%d.%m.%Y %H:%M') if x else '-'
def cash(x):
    try: return f'{float(x):.2f}'.rstrip('0').rstrip('.')
    except: return str(x)
def is_admin(uid:int): return uid in ADMIN_IDS

def norm_phone(s:str):
    s = (s or '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if not PHONE_RE.match(s): return None
    if s.startswith('8'): s = '+7' + s[1:]
    elif s.startswith('7'): s = '+' + s
    return s

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with closing(conn()) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
            balance REAL DEFAULT 0, frozen REAL DEFAULT 0, total_deposit REAL DEFAULT 0,
            registered_at INTEGER, deals_count INTEGER DEFAULT 0, seller INTEGER DEFAULT 0,
            seller_at INTEGER, earned REAL DEFAULT 0, sold_count INTEGER DEFAULT 0, disputes INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS seller_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, status TEXT DEFAULT 'pending', created_at INTEGER);
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, phone TEXT UNIQUE, price REAL,
            description TEXT, status TEXT DEFAULT 'moderation', created_at INTEGER, approved_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, seller_id INTEGER, product_id INTEGER,
            phone TEXT, price REAL, description TEXT, deal_code TEXT, status TEXT DEFAULT 'waiting_code',
            created_at INTEGER, closed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS balance_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, admin_id INTEGER, amount REAL, reason TEXT, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS withdraws(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, details TEXT, status TEXT DEFAULT 'pending', created_at INTEGER);
        CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, asset TEXT, invoice_id TEXT UNIQUE, pay_url TEXT, status TEXT DEFAULT 'created', created_at INTEGER, paid_at INTEGER);
        ''')
        db.commit()

def ensure_user(u):
    with closing(conn()) as db:
        db.execute('''INSERT INTO users(user_id,username,full_name,registered_at) VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name''',
        (u.id, u.username or '', u.full_name or '', ts()))
        db.commit()

def user(uid):
    with closing(conn()) as db:
        return db.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()

def link(u):
    if isinstance(u, sqlite3.Row):
        uid, name, username = u['user_id'], u['full_name'] or 'Пользователь', u['username'] or ''
    else:
        uid, name, username = u.id, u.full_name or 'Пользователь', u.username or ''
    return '@'+username if username else f"<a href='tg://user?id={uid}'>{name}</a>"

def ik(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t,d in r] for r in rows])

def buyer_kb():
    rows = [[InlineKeyboardButton(text='🛍 Маркет', callback_data='market')],
            [InlineKeyboardButton(text='👤 Профиль', callback_data='profile'), InlineKeyboardButton(text='📦 Покупки', callback_data='purchases')],
            [InlineKeyboardButton(text='💼 Режим продавца', callback_data='seller_mode')]]
    if WEBAPP_URL: rows.append([InlineKeyboardButton(text='✨ Mini App', web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def seller_kb():
    return ik([[('➕ Выставить номер','add_product')],[('👤 Профиль продавца','seller_profile'),('📊 Продажи','sales')],[('🛒 Режим покупателя','buyer_home')]])

def admin_kb():
    return ik([[('💰 Добавить баланс','admin_add_balance')],[('📦 Товары на модерации','admin_products')],[('👥 Заявки продавцов','admin_sellers')]])

class AddProduct(StatesGroup): phone=State(); price=State(); desc=State()
class Buy(StatesGroup): confirm=State()
class SellerApply(StatesGroup): pass
class CodeState(StatesGroup): code=State()
class AddBal(StatesGroup): user_id=State(); amount=State(); reason=State()
class Deposit(StatesGroup): amount=State()
class Withdraw(StatesGroup): amount=State(); details=State()

async def crypto_call(method: str, payload: dict):
    if not CRYPTO_PAY_TOKEN:
        raise RuntimeError('CRYPTO_PAY_TOKEN не указан в Railway Variables')
    headers = {'Crypto-Pay-API-Token': CRYPTO_PAY_TOKEN, 'Content-Type': 'application/json'}
    async with ClientSession() as session:
        async with session.post(f'{CRYPTO_API}/{method}', headers=headers, json=payload, timeout=25) as resp:
            data = await resp.json(content_type=None)
            if not data.get('ok'):
                raise RuntimeError(str(data))
            return data.get('result')

async def create_crypto_invoice(user_id: int, credit_amount: float):
    fee_amount = round(credit_amount * DEPOSIT_FEE_PERCENT / 100, 2)
    pay_amount = round(credit_amount + fee_amount, 2)
    result = await crypto_call('createInvoice', {
        'asset': CRYPTO_ASSET,
        'amount': str(pay_amount),
        'description': f'Diamond Market top-up: {credit_amount} + {DEPOSIT_FEE_PERCENT}% fee',
        'payload': f'deposit:{user_id}:{int(time.time())}',
        'allow_comments': False,
        'allow_anonymous': False,
        'expires_in': 3600,
    })
    invoice_id = str(result.get('invoice_id'))
    pay_url = result.get('bot_invoice_url') or result.get('mini_app_invoice_url') or result.get('web_app_invoice_url') or ''
    return invoice_id, pay_url, pay_amount, fee_amount

async def create_crypto_transfer(user_id: int, amount: float):
    result = await crypto_call('transfer', {
        'user_id': user_id,
        'asset': CRYPTO_ASSET,
        'amount': str(amount),
        'spend_id': f'withdraw:{user_id}:{int(time.time())}:{amount}',
        'comment': 'Diamond Market withdraw',
    })
    return result

async def invoice_is_paid(invoice_id: str) -> bool:
    result = await crypto_call('getInvoices', {'invoice_ids': invoice_id})
    items = result.get('items') if isinstance(result, dict) else []
    return bool(items and items[0].get('status') == 'paid')

async def home_msg(msg):
    await msg.answer('''💎 <b>Diamond Market</b>\n\nДобро пожаловать в маркет с гарантом.\n\n💰 Баланс — в профиле\n📦 Покупки — купленные товары\n💼 Режим продавца — выставление товаров''', reply_markup=buyer_kb())

@router.message(CommandStart())
async def start(m:Message, state:FSMContext):
    await state.clear(); ensure_user(m.from_user)
    payload = (m.text or '').split(maxsplit=1)
    if len(payload)>1 and payload[1].startswith('buy_'):
        pid = int(payload[1].split('_')[1])
        await show_product_message(m, pid)
        return
    await home_msg(m)

@router.callback_query(F.data=='buyer_home')
async def buyer_home(c:CallbackQuery, state:FSMContext):
    await state.clear(); ensure_user(c.from_user)
    await c.message.edit_text('💎 <b>Главное меню покупателя</b>\n\nВыберите раздел:', reply_markup=buyer_kb()); await c.answer()

@router.callback_query(F.data=='market')
async def market(c:CallbackQuery):
    with closing(conn()) as db:
        rows = db.execute('''SELECT p.*,u.full_name,u.username FROM products p JOIN users u ON u.user_id=p.seller_id
                             WHERE p.status='active' ORDER BY p.id DESC LIMIT 80''').fetchall()
    kbrows=[]
    for p in rows:
        seller = p['full_name'] or p['username'] or str(p['seller_id'])
        kbrows.append([(f'📱 {p["phone"]} • {cash(p["price"])}$ • {seller}', f'product:{p["id"]}')])
    kbrows.append([('🏠 Главное меню','buyer_home')])
    text='🛍 <b>Маркет номеров</b>\n\nВыберите товар:' if rows else '🛍 <b>Маркет</b>\n\nПока нет активных товаров.'
    await c.message.edit_text(text, reply_markup=ik(kbrows)); await c.answer()

async def show_product_message(target, pid:int):
    with closing(conn()) as db:
        p = db.execute('SELECT p.*,u.full_name,u.username,u.user_id FROM products p JOIN users u ON u.user_id=p.seller_id WHERE p.id=?', (pid,)).fetchone()
    if not p or p['status']!='active':
        await target.answer('❌ Товар недоступен'); return
    text = f'''📱 <b>Карточка товара</b>\n\n<b>Номер:</b> <code>{p['phone']}</code>\n<b>Цена:</b> {cash(p['price'])}$\n<b>Продавец:</b> {p['full_name'] or p['username'] or p['seller_id']}\n\n<b>Описание:</b>\n{p['description']}\n\n🛡 Деньги замораживаются до подтверждения покупателем.'''
    await target.answer(text, reply_markup=ik([[('💳 Купить','buy:'+str(pid))],[('⬅️ Маркет','market')]]))

@router.callback_query(F.data.startswith('product:'))
async def product(c:CallbackQuery):
    await c.message.delete()
    await show_product_message(c.message, int(c.data.split(':')[1])); await c.answer()

@router.callback_query(F.data.startswith('buy:'))
async def buy(c:CallbackQuery):
    ensure_user(c.from_user); pid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        p=db.execute('SELECT * FROM products WHERE id=? AND status="active"',(pid,)).fetchone(); u=user(c.from_user.id)
    if not p: return await c.answer('Товар недоступен', show_alert=True)
    if float(u['balance']) < float(p['price']):
        return await c.answer('Недостаточно средств. Пополните баланс через профиль.', show_alert=True)
    await c.message.edit_text(f'''💳 <b>Подтверждение покупки</b>\n\nТовар: <code>{p['phone']}</code>\nЦена: <b>{cash(p['price'])}$</b>\nВаш баланс: <b>{cash(u['balance'])}$</b>\n\nПосле покупки продавец отправит внутренний 6-значный код сделки.''', reply_markup=ik([[('✅ Купить','buy_confirm:'+str(pid))],[('❌ Отмена','market')]])); await c.answer()

@router.callback_query(F.data.startswith('buy_confirm:'))
async def buy_confirm(c:CallbackQuery):
    ensure_user(c.from_user); pid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        p=db.execute('SELECT * FROM products WHERE id=? AND status="active"',(pid,)).fetchone(); u=db.execute('SELECT * FROM users WHERE user_id=?',(c.from_user.id,)).fetchone()
        if not p: return await c.answer('Товар уже купили', show_alert=True)
        if float(u['balance']) < float(p['price']): return await c.answer('Недостаточно средств', show_alert=True)
        db.execute('UPDATE users SET balance=balance-?, frozen=frozen+?, deals_count=deals_count+1 WHERE user_id=?',(p['price'],p['price'],c.from_user.id))
        db.execute('UPDATE products SET status="sold" WHERE id=?',(pid,))
        cur=db.execute('''INSERT INTO orders(buyer_id,seller_id,product_id,phone,price,description,status,created_at)
                          VALUES(?,?,?,?,?,?,?,?)''',(c.from_user.id,p['seller_id'],pid,p['phone'],p['price'],p['description'],'waiting_code',ts()))
        oid=cur.lastrowid; db.commit()
    await c.message.edit_text(f'✅ <b>Покупка создана</b>\n\nЗаказ №{oid}\nДеньги заморожены гарантом. Ожидаем код сделки от продавца.', reply_markup=ik([[('📦 Покупки','purchases')]]))
    await c.bot.send_message(p['seller_id'], f'🆕 <b>У вас купили товар</b>\n\nЗаказ №{oid}\nНомер: <code>{p["phone"]}</code>\nСумма: {cash(p["price"])}$\n\nОтправьте внутренний код сделки: 6 цифр.', reply_markup=ik([[('🔢 Отправить код','seller_send_code:'+str(oid))]]))
    await c.answer()

@router.callback_query(F.data.startswith('seller_send_code:'))
async def seller_send_code(c:CallbackQuery, state:FSMContext):
    oid=int(c.data.split(':')[1])
    with closing(conn()) as db: o=db.execute('SELECT * FROM orders WHERE id=? AND seller_id=?',(oid,c.from_user.id)).fetchone()
    if not o or o['status']!='waiting_code': return await c.answer('Код уже отправлен или заказ не найден', show_alert=True)
    await state.set_state(CodeState.code); await state.update_data(order_id=oid)
    await c.message.answer('Введите внутренний код сделки. Ровно 6 цифр:'); await c.answer()

@router.message(CodeState.code)
async def save_code(m:Message, state:FSMContext):
    code=(m.text or '').strip()
    if not CODE_RE.match(code): return await m.answer('❌ Код должен быть ровно из 6 цифр. Пример: 483920')
    data=await state.get_data(); oid=int(data['order_id'])
    with closing(conn()) as db:
        o=db.execute('SELECT * FROM orders WHERE id=? AND seller_id=?',(oid,m.from_user.id)).fetchone()
        if not o or o['status']!='waiting_code': await state.clear(); return await m.answer('Заказ не найден или уже обработан.')
        db.execute('UPDATE orders SET deal_code=?, status="active" WHERE id=?',(code,oid)); db.commit()
    await state.clear(); await m.answer('✅ Код отправлен покупателю. Ожидаем подтверждение сделки.')
    await m.bot.send_message(o['buyer_id'], f'''📦 <b>Ваш товар по заказу №{oid}</b>\n\nНомер: <code>{o['phone']}</code>\nКод сделки: <code>{code}</code>\n\nПроверьте товар и подтвердите сделку.''', reply_markup=ik([[('✅ Подтвердить','confirm_order:'+str(oid)),('⚠️ Спор','dispute:'+str(oid))]]))

@router.callback_query(F.data=='purchases')
async def purchases(c:CallbackQuery):
    with closing(conn()) as db: rows=db.execute('SELECT * FROM orders WHERE buyer_id=? ORDER BY id DESC LIMIT 50',(c.from_user.id,)).fetchall()
    kbrows=[[(f'#{o["id"]} • {o["phone"]} • {o["status"]}', 'order:'+str(o['id']))] for o in rows]
    kbrows.append([('🏠 Главное меню','buyer_home')])
    await c.message.edit_text('📦 <b>Мои покупки</b>' if rows else '📦 Покупок пока нет.', reply_markup=ik(kbrows)); await c.answer()

@router.callback_query(F.data.startswith('order:'))
async def order_view(c:CallbackQuery):
    oid=int(c.data.split(':')[1])
    with closing(conn()) as db: o=db.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone()
    if not o: return await c.answer('Не найдено', show_alert=True)
    buttons=[]
    if o['status']=='active': buttons.append([('✅ Подтвердить','confirm_order:'+str(oid)),('⚠️ Спор','dispute:'+str(oid))])
    buttons.append([('⬅️ Покупки','purchases')])
    await c.message.edit_text(f'''📦 <b>Заказ №{oid}</b>\n\nНомер: <code>{o['phone']}</code>\nЦена: {cash(o['price'])}$\nКод сделки: <code>{o['deal_code'] or 'ожидается'}</code>\nСтатус: <b>{o['status']}</b>''', reply_markup=ik(buttons)); await c.answer()

@router.callback_query(F.data.startswith('confirm_order:'))
async def confirm_order(c:CallbackQuery):
    oid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        o=db.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone()
        if not o or o['status']!='active': return await c.answer('Сделку нельзя подтвердить', show_alert=True)
        db.execute('UPDATE orders SET status="closed", closed_at=? WHERE id=?',(ts(),oid))
        db.execute('UPDATE users SET frozen=frozen-? WHERE user_id=?',(o['price'],o['buyer_id']))
        db.execute('UPDATE users SET balance=balance+?, earned=earned+?, sold_count=sold_count+1, deals_count=deals_count+1 WHERE user_id=?',(o['price'],o['price'],o['seller_id']))
        db.commit()
    await c.message.edit_text('✅ Сделка закрыта. Деньги отправлены продавцу.', reply_markup=ik([[('🏠 Главное меню','buyer_home')]]))
    await c.bot.send_message(o['seller_id'], f'✅ Сделка №{oid} подтверждена. На баланс зачислено {cash(o["price"])}$')
    await c.answer()

@router.callback_query(F.data.startswith('dispute:'))
async def dispute(c:CallbackQuery):
    oid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        o=db.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(oid,c.from_user.id)).fetchone()
        if not o or o['status'] not in ('active','waiting_code'): return await c.answer('Спор нельзя открыть', show_alert=True)
        db.execute('UPDATE orders SET status="dispute" WHERE id=?',(oid,)); db.execute('UPDATE users SET disputes=disputes+1 WHERE user_id=?',(o['seller_id'],)); db.commit()
    text=f'⚠️ <b>Открыт спор</b>\n\nЗаказ №{oid}\nПокупатель: {link(c.from_user)} / <code>{c.from_user.id}</code>\nПродавец: <code>{o["seller_id"]}</code>\nНомер: <code>{o["phone"]}</code>\nСумма: {cash(o["price"])}$'
    if ADMIN_GROUP_ID: await c.bot.send_message(ADMIN_GROUP_ID,text)
    else:
        for aid in ADMIN_IDS: await c.bot.send_message(aid,text)
    await c.message.edit_text('⚠️ Спор открыт. Администрация получила уведомление.', reply_markup=ik([[('📦 Покупки','purchases')]])); await c.answer()

@router.callback_query(F.data=='profile')
async def profile(c:CallbackQuery):
    ensure_user(c.from_user); u=user(c.from_user.id)
    await c.message.edit_text(f'''👤 <b>Профиль</b>\n\n🪪 Никнейм: <b>{u['full_name']}</b>\n🆔 ID: <code>{u['user_id']}</code>\n💰 Баланс: <b>{cash(u['balance'])}$</b>\n🧊 Заморожено: <b>{cash(u['frozen'])}$</b>\n📦 Сделок: <b>{u['deals_count']}</b>\n➕ Всего пополнено: <b>{cash(u['total_deposit'])}$</b>\n📅 Регистрация: {dtime(u['registered_at'])}''', reply_markup=ik([[('➕ Пополнить','deposit'),('➖ Вывести','withdraw')],[('🏠 Главное меню','buyer_home')]])); await c.answer()

@router.callback_query(F.data=='deposit')
async def deposit(c:CallbackQuery, state:FSMContext):
    ensure_user(c.from_user)
    if not CRYPTO_PAY_TOKEN:
        await c.message.edit_text('⚠️ <b>CryptoBot не настроен</b>\n\nДобавь в Railway Variables:\n<code>CRYPTO_PAY_TOKEN=токен_cryptobot</code>\n<code>CRYPTO_ASSET=USDT</code>', reply_markup=ik([[('👤 Профиль','profile')]]))
        await c.answer(); return
    await state.set_state(Deposit.amount)
    await c.message.answer(f'➕ <b>Пополнение баланса</b>\n\nКомиссия пополнения: <b>{cash(DEPOSIT_FEE_PERCENT)}%</b>\nВведите сумму, которую нужно зачислить на баланс, например: <code>10</code>')
    await c.answer()

@router.message(Deposit.amount)
async def deposit_amount(m:Message, state:FSMContext):
    ensure_user(m.from_user)
    try:
        amount=float((m.text or '').replace(',','.'))
        if amount <= 0: raise ValueError
    except Exception:
        return await m.answer('❌ Введите сумму числом больше 0. Пример: <code>10</code>')
    try:
        invoice_id, pay_url, pay_amount, fee_amount = await create_crypto_invoice(m.from_user.id, amount)
    except Exception as e:
        await state.clear()
        return await m.answer(f'❌ Не удалось создать счет CryptoBot:
<code>{str(e)[:700]}</code>')
    with closing(conn()) as db:
        # amount здесь — сумма, которая будет зачислена на баланс. Пользователь оплачивает amount + комиссию.
        db.execute('INSERT INTO invoices(user_id,amount,asset,invoice_id,pay_url,created_at) VALUES(?,?,?,?,?,?)',(m.from_user.id,amount,CRYPTO_ASSET,invoice_id,pay_url,ts()))
        db.commit()
    await state.clear()
    await m.answer(f'💳 <b>Счет на пополнение создан</b>

💰 К зачислению: <b>{cash(amount)} {CRYPTO_ASSET}</b>
🧾 Комиссия {cash(DEPOSIT_FEE_PERCENT)}%: <b>{cash(fee_amount)} {CRYPTO_ASSET}</b>
💎 К оплате: <b>{cash(pay_amount)} {CRYPTO_ASSET}</b>
Счет: <code>{invoice_id}</code>

После оплаты нажмите «Проверить оплату».', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='💎 Оплатить через CryptoBot', url=pay_url)], [InlineKeyboardButton(text='🔄 Проверить оплату', callback_data='check_invoice:'+invoice_id)], [InlineKeyboardButton(text='👤 Профиль', callback_data='profile')]]))

@router.callback_query(F.data.startswith('check_invoice:'))
async def check_invoice(c:CallbackQuery):
    invoice_id = c.data.split(':',1)[1]
    with closing(conn()) as db:
        inv=db.execute('SELECT * FROM invoices WHERE invoice_id=? AND user_id=?',(invoice_id,c.from_user.id)).fetchone()
        if not inv:
            return await c.answer('Счет не найден', show_alert=True)
        if inv['status']=='paid':
            return await c.answer('Этот счет уже зачислен', show_alert=True)
    try:
        paid = await invoice_is_paid(invoice_id)
    except Exception as e:
        return await c.answer(f'Ошибка проверки: {str(e)[:150]}', show_alert=True)
    if not paid:
        return await c.answer('Оплата пока не найдена', show_alert=True)
    with closing(conn()) as db:
        db.execute('UPDATE invoices SET status="paid", paid_at=? WHERE invoice_id=?',(ts(),invoice_id))
        db.execute('UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE user_id=?',(inv['amount'],inv['amount'],c.from_user.id))
        db.commit()
    await c.message.edit_text(f'✅ <b>Оплата найдена</b>\n\nБаланс пополнен на <b>{cash(inv["amount"])} {inv["asset"]}</b>.', reply_markup=ik([[('👤 Профиль','profile')],[('🏠 Главное меню','buyer_home')]]))
    await c.answer('Баланс пополнен')

@router.callback_query(F.data=='withdraw')
async def withdraw_start(c:CallbackQuery, state:FSMContext):
    ensure_user(c.from_user)
    if not CRYPTO_PAY_TOKEN:
        await c.message.edit_text('⚠️ <b>CryptoBot не настроен</b>

Добавь в Railway Variables:
<code>CRYPTO_PAY_TOKEN=токен_cryptobot</code>
<code>CRYPTO_ASSET=USDT</code>', reply_markup=ik([[('👤 Профиль','profile')]]))
        await c.answer(); return
    u=user(c.from_user.id)
    await state.set_state(Withdraw.amount)
    await c.message.answer(f'➖ <b>Автоматический вывод</b>

Средства будут отправлены через CryptoBot на ваш Telegram ID.
Ваш баланс: <b>{cash(u["balance"])} {CRYPTO_ASSET}</b>

Введите сумму вывода:')
    await c.answer()

@router.message(Withdraw.amount)
async def withdraw_amount(m:Message, state:FSMContext):
    ensure_user(m.from_user)
    try:
        amount=float((m.text or '').replace(',','.'))
        if amount<=0: raise ValueError
    except Exception:
        return await m.answer('❌ Введите сумму числом больше 0.')
    u=user(m.from_user.id)
    if float(u['balance'])<amount:
        return await m.answer('❌ Недостаточно средств.')
    with closing(conn()) as db:
        db.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(amount,m.from_user.id))
        cur=db.execute('INSERT INTO withdraws(user_id,amount,details,status,created_at) VALUES(?,?,?,?,?)',(m.from_user.id,amount,'CryptoBot auto transfer','processing',ts()))
        wid=cur.lastrowid
        db.commit()
    try:
        result = await create_crypto_transfer(m.from_user.id, amount)
        transfer_id = str(result.get('transfer_id') or result.get('id') or 'ok') if isinstance(result, dict) else 'ok'
        with closing(conn()) as db:
            db.execute('UPDATE withdraws SET status=?, details=? WHERE id=?',('completed',f'CryptoBot transfer_id: {transfer_id}',wid))
            db.commit()
        await state.clear()
        await m.answer(f'✅ <b>Вывод выполнен автоматически</b>

Сумма: <b>{cash(amount)} {CRYPTO_ASSET}</b>
Transfer ID: <code>{transfer_id}</code>', reply_markup=ik([[('👤 Профиль','profile')],[('🏠 Главное меню','buyer_home')]]))
        if ADMIN_GROUP_ID:
            await m.bot.send_message(ADMIN_GROUP_ID, f'✅ Автовывод #{wid} выполнен
Пользователь: {link(m.from_user)} / <code>{m.from_user.id}</code>
Сумма: {cash(amount)} {CRYPTO_ASSET}
Transfer ID: <code>{transfer_id}</code>')
    except Exception as e:
        with closing(conn()) as db:
            db.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(amount,m.from_user.id))
            db.execute('UPDATE withdraws SET status=?, details=? WHERE id=?',('failed',str(e)[:500],wid))
            db.commit()
        await state.clear()
        await m.answer(f'❌ <b>Вывод не прошел</b>

Деньги возвращены на баланс.
Ошибка CryptoBot:
<code>{str(e)[:700]}</code>')

@router.callback_query(F.data=='seller_mode')
async def seller_mode(c:CallbackQuery):
    ensure_user(c.from_user); u=user(c.from_user.id)
    if u['seller']:
        await c.message.edit_text('💼 <b>Режим продавца</b>\n\nВыберите действие:', reply_markup=seller_kb())
    else:
        await c.message.edit_text('💼 <b>Вход пока запрещен…</b>\n\nЧтобы получить доступ, отправьте заявку:', reply_markup=ik([[('📨 Отправить заявку','seller_apply')],[('🏠 Главное меню','buyer_home')]]))
    await c.answer()

@router.callback_query(F.data=='seller_apply')
async def seller_apply(c:CallbackQuery):
    ensure_user(c.from_user)
    with closing(conn()) as db:
        cur=db.execute('INSERT INTO seller_requests(user_id,created_at) VALUES(?,?)',(c.from_user.id,ts())); rid=cur.lastrowid; db.commit()
    text=f'🆕 <b>Новая заявка продавца</b>\n\nНик: {c.from_user.full_name}\nЮзер: {link(c.from_user)}\nID: <code>{c.from_user.id}</code>'
    markup=ik([[('✅ Одобрить','seller_ok:'+str(rid)),('❌ Отказать','seller_no:'+str(rid))]])
    if ADMIN_GROUP_ID: await c.bot.send_message(ADMIN_GROUP_ID,text,reply_markup=markup)
    else:
        for aid in ADMIN_IDS: await c.bot.send_message(aid,text,reply_markup=markup)
    await c.message.edit_text('✅ Заявка отправлена.', reply_markup=ik([[('🏠 Главное меню','buyer_home')]])); await c.answer()

@router.callback_query(F.data.startswith('seller_ok:') | F.data.startswith('seller_no:'))
async def seller_decision(c:CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    ok=c.data.startswith('seller_ok:'); rid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        r=db.execute('SELECT * FROM seller_requests WHERE id=?',(rid,)).fetchone()
        if not r or r['status']!='pending': return await c.answer('Уже обработано',show_alert=True)
        db.execute('UPDATE seller_requests SET status=? WHERE id=?',('approved' if ok else 'rejected',rid))
        if ok: db.execute('UPDATE users SET seller=1,seller_at=? WHERE user_id=?',(ts(),r['user_id']))
        db.commit()
    await c.bot.send_message(r['user_id'], '✅ Доступ продавца открыт!' if ok else '❌ Вход в режим продавца отказан.')
    await c.message.edit_text(c.message.html_text + ('\n\n✅ Одобрено' if ok else '\n\n❌ Отказано')); await c.answer()

@router.callback_query(F.data=='add_product')
async def add_product(c:CallbackQuery,state:FSMContext):
    u=user(c.from_user.id)
    if not u or not u['seller']: return await c.answer('Нет доступа',show_alert=True)
    await state.set_state(AddProduct.phone); await c.message.answer('📱 Отправьте номер товара. Формат: +79001234567'); await c.answer()

@router.message(AddProduct.phone)
async def add_phone(m:Message,state:FSMContext):
    phone=norm_phone(m.text)
    if not phone: return await m.answer('❌ Неверный формат. Пример: +79001234567')
    await state.update_data(phone=phone); await state.set_state(AddProduct.price); await m.answer('💰 Введите цену товара в $:')

@router.message(AddProduct.price)
async def add_price(m:Message,state:FSMContext):
    try:
        price=float((m.text or '').replace(',','.'))
        if price<=0: raise ValueError
    except: return await m.answer('Введите цену числом.')
    await state.update_data(price=price); await state.set_state(AddProduct.desc); await m.answer('📝 Введите описание товара:')

@router.message(AddProduct.desc)
async def add_desc(m:Message,state:FSMContext):
    desc=(m.text or '').strip()
    if len(desc)<5: return await m.answer('Описание слишком короткое.')
    data=await state.get_data()
    with closing(conn()) as db:
        try:
            cur=db.execute('INSERT INTO products(seller_id,phone,price,description,created_at) VALUES(?,?,?,?,?)',(m.from_user.id,data['phone'],data['price'],desc,ts()))
            pid=cur.lastrowid; db.commit()
        except sqlite3.IntegrityError:
            await state.clear(); return await m.answer('❌ Такой номер уже есть в базе.')
    await state.clear(); await m.answer('✅ Товар отправлен на модерацию.', reply_markup=seller_kb())
    text=f'📦 <b>Товар на модерации</b>\n\nID: {pid}\nПродавец: {link(m.from_user)} / <code>{m.from_user.id}</code>\nНомер: <code>{data["phone"]}</code>\nЦена: {cash(data["price"])}$\nОписание:\n{desc}'
    markup=ik([[('✅ Принять','prod_ok:'+str(pid)),('❌ Отклонить','prod_no:'+str(pid))]])
    if ADMIN_GROUP_ID: await m.bot.send_message(ADMIN_GROUP_ID,text,reply_markup=markup)
    else:
        for aid in ADMIN_IDS: await m.bot.send_message(aid,text,reply_markup=markup)

@router.callback_query(F.data.startswith('prod_ok:') | F.data.startswith('prod_no:'))
async def prod_decision(c:CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    ok=c.data.startswith('prod_ok:'); pid=int(c.data.split(':')[1])
    with closing(conn()) as db:
        p=db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
        if not p or p['status']!='moderation': return await c.answer('Уже обработано',show_alert=True)
        db.execute('UPDATE products SET status=?, approved_at=? WHERE id=?',('active' if ok else 'rejected',ts() if ok else None,pid)); db.commit()
    await c.bot.send_message(p['seller_id'], f'✅ Товар №{pid} принят и выставлен.' if ok else f'❌ Товар №{pid} отклонен.')
    await c.message.edit_text(c.message.html_text + ('\n\n✅ Принято' if ok else '\n\n❌ Отклонено')); await c.answer()

@router.callback_query(F.data=='seller_profile')
async def seller_profile(c:CallbackQuery):
    u=user(c.from_user.id)
    await c.message.edit_text(f'''👑 <b>Профиль продавца</b>\n\nИмя: {u['full_name']}\nID: <code>{u['user_id']}</code>\nБаланс: <b>{cash(u['balance'])}$</b>\nЗаработано: <b>{cash(u['earned'])}$</b>\nПродаж: <b>{u['sold_count']}</b>\nСпоров: <b>{u['disputes']}</b>\nДата продавца: {dtime(u['seller_at'])}''', reply_markup=ik([[('➖ Вывести','withdraw')],[('🏠 Главное меню','seller_mode')]])); await c.answer()

@router.callback_query(F.data=='sales')
async def sales(c:CallbackQuery):
    with closing(conn()) as db: rows=db.execute('SELECT * FROM orders WHERE seller_id=? ORDER BY id DESC LIMIT 50',(c.from_user.id,)).fetchall()
    kbrows=[[(f'#{o["id"]} • {o["phone"]} • {o["status"]}', 'sale:'+str(o['id']))] for o in rows]
    kbrows.append([('🏠 Главное меню','seller_mode')])
    await c.message.edit_text('📊 <b>Продажи</b>' if rows else '📊 Продаж пока нет.', reply_markup=ik(kbrows)); await c.answer()

@router.callback_query(F.data.startswith('sale:'))
async def sale(c:CallbackQuery):
    oid=int(c.data.split(':')[1])
    with closing(conn()) as db: o=db.execute('SELECT * FROM orders WHERE id=? AND seller_id=?',(oid,c.from_user.id)).fetchone()
    if not o: return await c.answer('Не найдено',show_alert=True)
    await c.message.edit_text(f'📊 <b>Продажа №{oid}</b>\n\nНомер: <code>{o["phone"]}</code>\nСумма: {cash(o["price"])}$\nСтатус: <b>{o["status"]}</b>', reply_markup=ik([[('⬅️ Продажи','sales')]])); await c.answer()

@router.message(Command('admin'))
async def admin(m:Message):
    ensure_user(m.from_user)
    if not is_admin(m.from_user.id): return await m.answer('⛔️ Нет доступа')
    with closing(conn()) as db:
        users=db.execute('SELECT COUNT(*) c FROM users').fetchone()['c']; products=db.execute('SELECT COUNT(*) c FROM products WHERE status="moderation"').fetchone()['c']; sellers=db.execute('SELECT COUNT(*) c FROM seller_requests WHERE status="pending"').fetchone()['c']
    await m.answer(f'🛡 <b>Админ-панель</b>\n\n👥 Пользователей: {users}\n📦 Товаров на модерации: {products}\n💼 Заявок продавцов: {sellers}', reply_markup=admin_kb())

@router.callback_query(F.data=='admin_add_balance')
async def admin_add_bal(c:CallbackQuery,state:FSMContext):
    if not is_admin(c.from_user.id): return await c.answer('Нет доступа',show_alert=True)
    await state.set_state(AddBal.user_id); await c.message.answer('Введите Telegram ID пользователя:'); await c.answer()

@router.message(AddBal.user_id)
async def admin_bal_uid(m:Message,state:FSMContext):
    if not is_admin(m.from_user.id): return
    try: uid=int((m.text or '').strip())
    except: return await m.answer('Введите ID числом.')
    await state.update_data(uid=uid); await state.set_state(AddBal.amount); await m.answer('Введите сумму пополнения, например 10:')

@router.message(AddBal.amount)
async def admin_bal_amount(m:Message,state:FSMContext):
    if not is_admin(m.from_user.id): return
    try: amount=float((m.text or '').replace(',','.'))
    except: return await m.answer('Введите сумму числом.')
    await state.update_data(amount=amount); await state.set_state(AddBal.reason); await m.answer('Комментарий/причина пополнения:')

@router.message(AddBal.reason)
async def admin_bal_reason(m:Message,state:FSMContext):
    if not is_admin(m.from_user.id): return
    data=await state.get_data(); uid=int(data['uid']); amount=float(data['amount']); reason=(m.text or '').strip()
    with closing(conn()) as db:
        db.execute('INSERT OR IGNORE INTO users(user_id,username,full_name,registered_at) VALUES(?,?,?,?)',(uid,'','',ts()))
        db.execute('UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE user_id=?',(amount,amount if amount>0 else 0,uid))
        db.execute('INSERT INTO balance_logs(user_id,admin_id,amount,reason,created_at) VALUES(?,?,?,?,?)',(uid,m.from_user.id,amount,reason,ts()))
        db.commit()
    await state.clear(); await m.answer(f'✅ Баланс пользователя <code>{uid}</code> изменен на {cash(amount)}$.')
    try: await m.bot.send_message(uid, f'💰 Баланс пополнен на <b>{cash(amount)}$</b>\nКомментарий: {reason}')
    except Exception: pass

# Mini App secure auth

def validate_init_data(init_data: str):
    if not init_data: return None
    pairs = dict(parse_qsl(init_data, strict_parsing=False))
    recv_hash = pairs.pop('hash', None)
    if not recv_hash: return None
    check = '\n'.join(f'{k}={v}' for k,v in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash): return None
    try: return json.loads(pairs.get('user','{}'))
    except: return None

HTML = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><script src="https://telegram.org/js/telegram-web-app.js"></script><title>Diamond Market</title><style>
*{box-sizing:border-box}body{margin:0;background:#050505;color:white;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial;overflow-x:hidden}.bg{position:fixed;inset:0;background:radial-gradient(circle at 20% 10%,rgba(245,197,66,.25),transparent 25%),radial-gradient(circle at 90% 0%,rgba(214,31,65,.25),transparent 22%),linear-gradient(180deg,#060606,#111);z-index:-2}.orb{position:fixed;width:160px;height:160px;border-radius:50%;background:rgba(245,197,66,.12);filter:blur(25px);animation:float 5s ease-in-out infinite;z-index:-1}.orb.o2{right:-60px;top:210px;background:rgba(214,31,65,.15);animation-delay:1.2s}@keyframes float{50%{transform:translateY(30px) scale(1.15)}}.wrap{padding:18px 14px 95px;max-width:760px;margin:auto}.hero{border:1px solid rgba(245,197,66,.35);border-radius:28px;padding:20px;background:linear-gradient(135deg,rgba(255,215,90,.15),rgba(255,255,255,.04));box-shadow:0 20px 80px #000;animation:pop .45s ease}.logo{font-size:29px;font-weight:950}.logo span{color:#f5c542;text-shadow:0 0 18px rgba(245,197,66,.7)}.sub{color:#aaa;margin-top:8px;line-height:1.35}.card{margin-top:14px;padding:15px;border-radius:22px;background:linear-gradient(180deg,#181818,#0d0d0d);border:1px solid #292929;animation:up .35s ease}.row{display:flex;justify-content:space-between;gap:12px}.phone{font-size:19px;font-weight:900}.price{color:#f5c542;font-weight:950;font-size:20px}.muted{color:#aaa;font-size:13px;margin-top:5px}.desc{margin-top:10px;line-height:1.35;color:#eee}.btn{width:100%;border:0;border-radius:15px;margin-top:13px;padding:14px;font-weight:950;background:linear-gradient(90deg,#f5c542,#fff0a3);color:#111;box-shadow:0 0 22px rgba(245,197,66,.25)}.btn:active{transform:scale(.98)}.top{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.pill{background:#101010;border:1px solid #292929;border-radius:16px;padding:13px;text-align:center;font-weight:800}.empty{text-align:center;color:#aaa;border:1px dashed #333;border-radius:22px;padding:26px;margin-top:16px}@keyframes pop{from{opacity:0;transform:scale(.96)}to{opacity:1}}@keyframes up{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}.toast{position:fixed;left:14px;right:14px;bottom:18px;background:#fff;color:#111;padding:14px;border-radius:18px;text-align:center;font-weight:900;display:none}
</style></head><body><div class="bg"></div><div class="orb"></div><div class="orb o2"></div><div class="wrap"><div class="hero"><div class="logo">💎 Diamond <span>Market</span></div><div class="sub">Красивый mini app маркет. Покупка прямо внутри приложения, гарантия через баланс бота.</div></div><div class="top"><div class="pill" id="bal">Баланс: —</div><div class="pill" id="cnt">Товаров: —</div></div><div id="list"></div></div><div class="toast" id="toast"></div><script>
const tg=window.Telegram?.WebApp; tg?.expand(); tg?.setHeaderColor('#050505'); tg?.setBackgroundColor('#050505');
function toast(t){let x=document.getElementById('toast');x.textContent=t;x.style.display='block';setTimeout(()=>x.style.display='none',2600)}
async function api(path,body){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,initData:tg?.initData||''})});return await r.json()}
async function load(){let r=await fetch('/api/products?initData='+encodeURIComponent(tg?.initData||''));let d=await r.json();document.getElementById('cnt').textContent='Товаров: '+d.items.length;document.getElementById('bal').textContent='Баланс: '+(d.balance??'—')+'$';let list=document.getElementById('list');list.innerHTML='';if(!d.items.length){list.innerHTML='<div class="empty">Пока нет активных товаров</div>';return}d.items.forEach(p=>{let el=document.createElement('div');el.className='card';el.innerHTML=`<div class="row"><div><div class="phone">📱 ${p.phone}</div><div class="muted">Продавец: ${p.seller}</div></div><div class="price">${p.price}$</div></div><div class="desc">${p.description}</div><button class="btn">Купить</button>`;el.querySelector('button').onclick=async()=>{let res=await api('/api/buy',{product_id:p.id});toast(res.message||'Готово');if(res.ok) setTimeout(load,800)};list.appendChild(el)})}
load();
</script></body></html>'''

async def index(request): return web.Response(text=HTML, content_type='text/html')
async def api_products(request):
    uid=None; balance=None
    init=request.query.get('initData','')
    u=validate_init_data(init) if init else None
    if u:
        uid=u.get('id'); row=user(uid); balance=cash(row['balance']) if row else '0'
    with closing(conn()) as db:
        rows=db.execute('SELECT p.*,u.full_name,u.username FROM products p JOIN users u ON u.user_id=p.seller_id WHERE p.status="active" ORDER BY p.id DESC').fetchall()
    return web.json_response({'items':[{'id':r['id'],'phone':r['phone'],'price':cash(r['price']),'description':r['description'],'seller':r['full_name'] or r['username'] or str(r['seller_id'])} for r in rows], 'balance': balance})
async def api_buy(request):
    bot=request.app['bot']; data=await request.json(); u=validate_init_data(data.get('initData',''))
    if not u: return web.json_response({'ok':False,'message':'Открой Mini App из Telegram-бота'})
    uid=int(u['id']); pseudo=type('U',(),{'id':uid,'username':u.get('username',''),'full_name':(u.get('first_name','')+' '+u.get('last_name','')).strip()})
    ensure_user(pseudo); pid=int(data.get('product_id',0))
    with closing(conn()) as db:
        p=db.execute('SELECT * FROM products WHERE id=? AND status="active"',(pid,)).fetchone(); usr=db.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
        if not p: return web.json_response({'ok':False,'message':'Товар уже недоступен'})
        if float(usr['balance'])<float(p['price']): return web.json_response({'ok':False,'message':'Недостаточно средств'})
        db.execute('UPDATE users SET balance=balance-?, frozen=frozen+?, deals_count=deals_count+1 WHERE user_id=?',(p['price'],p['price'],uid))
        db.execute('UPDATE products SET status="sold" WHERE id=?',(pid,))
        cur=db.execute('INSERT INTO orders(buyer_id,seller_id,product_id,phone,price,description,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(uid,p['seller_id'],pid,p['phone'],p['price'],p['description'],'waiting_code',ts()))
        oid=cur.lastrowid; db.commit()
    await bot.send_message(uid, f'✅ Покупка создана через Mini App. Заказ №{oid}. Ожидаем код сделки от продавца.', reply_markup=ik([[('📦 Покупки','purchases')]]))
    await bot.send_message(p['seller_id'], f'🆕 У вас купили товар через Mini App\nЗаказ №{oid}\nНомер: <code>{p["phone"]}</code>\nСумма: {cash(p["price"])}$\nОтправьте внутренний код сделки: 6 цифр.', reply_markup=ik([[('🔢 Отправить код','seller_send_code:'+str(oid))]]))
    return web.json_response({'ok':True,'message':'Покупка создана. Проверьте бота.'})
async def health(request): return web.json_response({'ok':True})

async def start_web(bot):
    app=web.Application(); app['bot']=bot
    app.add_routes([web.get('/',index),web.get('/api/products',api_products),web.post('/api/buy',api_buy),web.get('/health',health)])
    runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',PORT).start()
    log.info('Mini App started on port %s',PORT)

async def main():
    global BOT_USERNAME
    init_db()
    bot=Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me=await bot.get_me(); BOT_USERNAME=me.username or ''; log.info('Bot @%s started',BOT_USERNAME)
    await start_web(bot)
    dp=Dispatcher(storage=MemoryStorage()); dp.include_router(router)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
if __name__=='__main__': asyncio.run(main())
