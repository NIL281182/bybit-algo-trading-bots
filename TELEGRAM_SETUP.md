# Подробная инструкция: Telegram-алерты для торговых ботов

Это руководство пошагово объясняет, как создать Telegram-бота, получить Chat ID и настроить отправку уведомлений из торговых ботов (`bot_donchian_v3.py`, `bot_ema_pullback_eth.py`).

---

## Шаг 1. Создание бота через @BotFather

@BotFather — это официальный бот Telegram для управления ботами.

### 1.1 Открой Telegram и найди @BotFather

- В поиске Telegram введи: `@BotFather`
- Нажми на результат с галочкой (официальный бот Telegram)

```
┌─────────────────────────────┐
│  🔍 Поиск: @BotFather       │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━  │
│  🤖 BotFather  ✓            │
│  @BotFather                 │
│  Бот для создания ботов     │
└─────────────────────────────┘
```

### 1.2 Отправь команду `/newbot`

В чате с @BotFather напиши:
```
/newbot
```

BotFather ответит:
```
Alright, a new bot. How are we going to call it? 
Please choose a name for your bot.
```

### 1.3 Придумай имя бота

Это **отображаемое имя** (не обязательно уникальное).

Например, отправь:
```
My Trade Alerts
```

### 1.4 Придумай username бота

Это техническое имя, которое должно:
- Заканчиваться на `bot` или `_bot`
- Быть уникальным во всём Telegram
- Состоять только из латинских букв, цифр, подчёркиваний

Например, отправь:
```
my_trade_alerts_bot
```

Если имя занято, BotFather скажет:
```
Sorry, this username is already taken. Please try something else.
```

Попробуй добавить цифры или своё имя:
```
my_trade_alerts_2026_bot
```

### 1.5 Получи токен

Если username свободен, BotFather отправит сообщение:

```
Done! Congratulations on your new bot. 
You will find it at t.me/my_trade_alerts_2026_bot.

Use this token to access the HTTP API:
123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890

Keep your token secure and store it safely, it can be used by anyone to control your bot.
```

**Важно:** строка `123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890` — это твой **BOT_TOKEN**. Скопируй её и сохрани.

> ⚠️ **Токен показывается только один раз!** Если потеряешь — придётся перевыпускать через `/revoke`.

---

## Шаг 2. Получение Chat ID

Chat ID — это уникальный номер твоего аккаунта (или группы), куда бот будет слать сообщения.

### 2.1 Личный аккаунт (рекомендуется)

Найди бота **@userinfobot**:

- В поиске Telegram введи: `@userinfobot`
- Нажми на него и отправь любое сообщение (например, `hello`)

Бот мгновенно ответит:
```
Id: 123456789
First: Иван
Last: Петров
Username: @ivan_petrov
Lang: ru
```

**Число после `Id:`** — это твой **CHAT_ID** (в данном примере `123456789`).

### 2.2 Групповой чат (опционально)

Если хочешь получать алерты в группу (например, с друзьями или коллегами):

1. Добавь своего бота в группу
2. Отправь в группу любое сообщение
3. Открой в браузере:
   ```
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```
   Например:
   ```
   https://api.telegram.org/bot123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890/getUpdates
   ```
4. Найди в ответе `"chat":{"id":-1234567890` — это **Chat ID группы** (со знаком минус).

> 💡 **Полезно:** Chat ID группы начинается с `-` (например, `-1234567890`). Личный Chat ID всегда положительный.

---

## Шаг 3. Запись в .env

Открой файл `.env` в папке `trade` (создай из `.env.example`, если ещё не сделал).

Добавь две строки в конец:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890
TELEGRAM_CHAT_ID=123456789
```

> ⚠️ **Важно:** не используй кавычки и не оставляй пробелов после значений.

Пример полного `.env`:
```
# Bybit Testnet API Keys
BYBIT_API_KEY=yZnhUftzdeVkOsq9H0
BYBIT_API_SECRET=rTl5XtpWDIl9Ft3eWSwGrXosw97r7UIdXTdt

# Telegram Alerts
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890
TELEGRAM_CHAT_ID=123456789
```

---

## Шаг 4. Проверка — отправь тестовое сообщение

Прежде чем запускать торгового бота, убедись, что Telegram работает.

### 4.1 Запусти Python в папке `trade`

```bash
# Windows (PowerShell / CMD)
cd C:\Users\nil28\trade
python
```

### 4.2 Выполни тестовый скрипт

```python
import os
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

print(f"Token: {BOT_TOKEN[:20]}...")
print(f"Chat ID: {CHAT_ID}")

# Отправляем тестовое сообщение
import json
from urllib import request

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "✅ Тестовое сообщение из торгового бота!\n\nЕсли ты видишь это — Telegram настроен правильно.",
    "parse_mode": "Markdown",
}
data = json.dumps(payload).encode("utf-8")

req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
with request.urlopen(req, timeout=10) as resp:
    print(f"Ответ Telegram: {resp.status}")
    print(resp.read().decode())
```

Если всё правильно, в Telegram придёт сообщение:
```
✅ Тестовое сообщение из торгового бота!

Если ты видишь это — Telegram настроен правильно.
```

А в консоли Python:
```
Ответ Telegram: 200
{"ok":true,"result":{...}}
```

### 4.2 Альтернатива: curl

Если предпочитаешь командную строку:

**Windows (PowerShell):**
```powershell
$token = "123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890"
$chat = "123456789"
$body = @{
    chat_id = $chat
    text = "Тестовое сообщение"
    parse_mode = "Markdown"
} | ConvertTo-Json
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" -Method POST -ContentType "application/json" -Body $body
```

**Bash:**
```bash
BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxyz1234567890"
CHAT_ID="123456789"
curl -X POST \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"$CHAT_ID\",\"text\":\"Тестовое сообщение\",\"parse_mode\":\"Markdown\"}" \
  https://api.telegram.org/bot$BOT_TOKEN/sendMessage
```

---

## Шаг 5. Запуск торгового бота

Теперь, когда Telegram проверен, запускай бота как обычно:

```bash
python bot_donchian_v3.py
```

Если `.env` настроен правильно, бот при старте отправит в Telegram:
```
🤖 *Donchian v3 Bot* запущен!
Инструмент: `BTCUSDT`
```

---

## Частые ошибки и решения

### ❌ Ошибка: "Bad Request: chat not found"

**Причина:** Chat ID неверный или бот не начал диалог с пользователем.

**Решение:**
1. Найди своего бота в Telegram (по username, например `@my_trade_alerts_bot`)
2. Нажми **Start** (или отправь `/start`)
3. Повтори получение Chat ID через @userinfobot

### ❌ Ошибка: "Unauthorized"

**Причина:** Неверный или устаревший BOT_TOKEN.

**Решение:**
1. Вернись к @BotFather
2. Отправь `/mybots`
3. Выбери своего бота → **API Token** → **Revoke current token**
4. Скопируй новый токен и обнови `.env`

### ❌ Ошибка: нет ответа от Telegram вообще

**Причина:** возможно, блокировка API в вашей стране.

**Решение:**
- Попробуй открыть `https://api.telegram.org` в браузере
- Если не открывается — используй VPN
- В коде `alerts.py` таймаут = 10 секунд, если Telegram не отвечает — сообщение просто не уйдёт, но бот продолжит работать

### ❌ Бот не присылает сообщения, хотя всё настроено

**Причина:** переменные окружения не загрузились.

**Проверка:** добавь временно в `bot_donchian_v3.py` (перед `main()`):
```python
print(f"TG TOKEN: {os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET')[:20]}...")
print(f"TG CHAT: {os.environ.get('TELEGRAM_CHAT_ID', 'NOT SET')}")
```

Если выводит `NOT SET` — файл `.env` не найден. Убедись, что:
- `.env` находится в той же папке, откуда запускаешь бота
- Название файла точно `.env` (не `env.txt`)

### ❌ Сообщения приходят, но без форматирования

**Причина:** `parse_mode` не передаётся или Markdown невалиден.

**Решение:** в `alerts.py` используется `parse_mode="Markdown"`. Символы `_`, `*`, `[` могут ломать разметку. В коде используется экранирование `\` для спецсимволов.

---

## Резюме

| Что нужно | Где взять |
|-----------|-----------|
| BOT_TOKEN | @BotFather → `/newbot` |
| CHAT_ID | @userinfobot (личный) или `getUpdates` API (группа) |
| Проверка | Тестовый скрипт Python или curl |
| Хранение | `.env` файл (в `.gitignore`) |

---

## Дополнительно

### Как добавить ещё одного получателя
Telegram-бот может писать только тем, кто нажал **Start**. Если хочешь, чтобы алерты приходили тебе и, например, партнёру:

1. Партнёр находит твоего бота и нажимает **Start**
2. Партнёр получает свой Chat ID через @userinfobot
3. В коде `alerts.py` можно модифицировать `send_alert` для отправки в несколько chat_id:
   ```python
   CHAT_IDS = os.environ.get("TELEGRAM_CHAT_ID", "").split(",")
   for chat_id in CHAT_IDS:
       # отправить каждому
   ```
   И в `.env`:
   ```
   TELEGRAM_CHAT_ID=123456789,987654321
   ```

### Как временно отключить алерты
Просто закомментируй или удали строки в `.env`:
```
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```
Бот проверяет наличие переменных и, если они не заданы — молча не отправляет ничего.

---

Если что-то не работает — сделай скриншот ошибки из консоли или ответа Telegram API, и покажи мне.
