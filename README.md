# Diamond Market Bot v2

Одна архитектура без папок.

- Telegram bot + Mini App в `main.py`
- Mini App с анимациями
- Покупка прямо в Mini App
- Админ-панель `/admin`
- Добавление баланса пользователю
- Загрузка только товара типа “номер”
- Проверка формата номера
- После покупки продавец отправляет внутренний код сделки — 6 цифр
- Покупатель получает номер + код и кнопки подтверждения / спора

Railway Variables минимум:

```env
BOT_TOKEN=токен_бота
ADMIN_IDS=твой_telegram_id
DB_PATH=market.db
```

Для Mini App:

```env
WEBAPP_URL=https://твой-проект.up.railway.app
```

Реальный токен добавляй только в Railway Variables, не в GitHub.
