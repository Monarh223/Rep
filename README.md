# Diamond Market Bot + Mini App

Одна архитектура без папок. Все в корне репозитория.

## Railway Variables

```env
BOT_TOKEN=токен_бота
ADMIN_IDS=твой_id,второй_id
ADMIN_GROUP_ID=-100xxxxxxxxxx
WEBAPP_URL=https://твой-проект.up.railway.app
CRYPTO_PAY_TOKEN=токен_CryptoBot_CryptoPay
CRYPTO_ASSET=USDT
DB_PATH=/data/market.db
```

## Запуск

1. Загрузи файлы в GitHub в корень репозитория.
2. Railway → New Project → Deploy from GitHub.
3. Добавь Variables.
4. Для сохранения базы подключи Railway Volume на `/data` и поставь `DB_PATH=/data/market.db`.

## Есть

- Маркет / Покупки / Профиль / Режим продавца.
- Категории Фиш и Саморег.
- Заявки продавцов через админ-группу.
- Модерация товаров.
- Покупка с заморозкой баланса.
- Покупки и продажи.
- Закрытие сделки.
- Споры и арбитраж.
- Решение спора админом.
- Пополнение и вывод через CryptoBot API.
- Mini App сайт внутри `main.py`.
