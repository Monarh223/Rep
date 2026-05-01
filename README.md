# Diamond Market Bot v11

Одна архитектура без папок: весь бот и Mini App находятся в `main.py`.

## Что изменено в v11

Теперь в Railway Variables не надо держать простые настройки. В коде уже прописано:

```python
ADMIN_IDS = {626387429, 713807432}
CRYPTO_ASSET = 'USDT'
DEPOSIT_FEE_PERCENT = 6.0
MIN_WITHDRAW_DEFAULT = 1.01
MARKET_FEE_DEFAULT = 5.0
CRYPTO_PAY_TESTNET = False
```

Комиссию маркета и минимальный вывод можно менять через `/admin`; они сохраняются в БД.

## В Railway Variables нужны только

```env
BOT_TOKEN=реальный_токен_бота
CRYPTO_PAY_TOKEN=токен_cryptobot
WEBAPP_URL=https://твой-проект.up.railway.app
ADMIN_GROUP_ID=-100xxxxxxxxxx
DB_PATH=/data/market.db
```

`ADMIN_GROUP_ID` можно не ставить, если не нужна админ-группа, но лучше поставить.

## Файлы

- `main.py` — бот + Mini App + SQLite
- `requirements.txt` — зависимости
- `Procfile` — запуск Railway
- `.env.example` — подсказка по Railway Variables
- `README.md` — инструкция

## Railway

1. Загрузи файлы в GitHub в корень репозитория.
2. Railway → Deploy from GitHub.
3. Добавь Variables из `.env.example`.
4. Лучше подключи Volume и поставь `DB_PATH=/data/market.db`, чтобы база не слетала.
5. Нажми Redeploy.

## БД

Есть команды/кнопки:

- `/db_export` — выгрузить полную БД
- `/db_import` — загрузить БД
- также кнопки в `/admin`

После импорта данные поднимаются без перезапуска.
