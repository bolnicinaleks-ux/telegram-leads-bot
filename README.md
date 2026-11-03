# Telegram-бот приёма заявок + Google Sheets

aiogram 3 · SQLite (aiosqlite) · gspread · Docker

## Возможности

**Клиент**
- Анкета из `form.toml` — вопросы меняются без правки кода
- Типы вопросов: текст, телефон (кнопкой или текстом), выбор из кнопок, число, фото/документ
- Проверка каждого ответа, «Назад», «Пропустить» для необязательных, «Отмена»
- Итоговая проверка заявки перед отправкой, «Заполнить заново»
- «Мои заявки» со статусами, уведомления о смене статуса
- Ограничение: не больше N заявок в час от одного пользователя

**Администратор**
- Заявка приходит в личку каждому админу или в рабочую группу (`LEADS_CHAT_ID`); фото и файлы — ответами на карточку
- Кнопки статуса «В работе / Выполнена / Отказ» прямо в карточке; все копии карточки обновляются, клиент получает уведомление
- В рабочей группе статус может менять любой её участник
- `/leads [статус]`, `/lead ID`, `/export` — CSV для Excel

**Google Sheets**
- Новая заявка — новая строка, смена статуса — обновление этой же строки
- Если Google недоступен, изменения копятся в очереди и догружаются автоматически
- Без Google бот полностью работает: всё хранится в SQLite

## Запуск

```bash
cp .env.example .env   # заполнить BOT_TOKEN и ADMIN_IDS
```

Docker:
```bash
docker compose up -d --build
```

Без Docker (Python 3.11+):
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m bot
```

## Подключение Google Sheets

1. https://console.cloud.google.com → создать проект.
2. «APIs & Services» → «Library» → включить **Google Sheets API** и **Google Drive API**.
3. «IAM & Admin» → «Service Accounts» → создать сервисный аккаунт → вкладка «Keys» → «Add key» → JSON. Сохранить файл как `credentials.json` в папке бота.
4. Создать Google-таблицу и открыть к ней доступ **редактора** для email сервисного аккаунта (`...@...iam.gserviceaccount.com`).
5. В `.env` указать `GOOGLE_SHEET_ID` — часть ссылки на таблицу между `/d/` и `/edit`.
6. Для Docker раскомментировать строку с `credentials.json` в `docker-compose.yml`.

Лист `GOOGLE_WORKSHEET` (по умолчанию «Заявки») создаётся автоматически, заголовки колонок берутся из `label` вопросов.

## Настройка анкеты (`form.toml`)

```toml
title = "Заявка на ремонт"
intro = "Ответьте на несколько вопросов."
done = "Спасибо! Мы свяжемся с вами."

[[questions]]
key = "service"          # уникальный, не меняйте у существующих вопросов
type = "choice"          # text | phone | choice | number | file
label = "Услуга"         # колонка в таблице
text = "Что нужно сделать?"
options = ["Ремонт", "Сантехника"]
required = true          # false — можно пропустить
```

Для `text`: `min_length`, `max_length`. Для `number`: `min`, `max`. Ошибки в файле показываются при старте с номером вопроса.

## Настройки (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен от @BotFather |
| `ADMIN_IDS` | — | ID администраторов через запятую |
| `LEADS_CHAT_ID` | — | ID рабочей группы (иначе — в личку админам) |
| `FORM_PATH` | `form.toml` | Файл анкеты |
| `TIMEZONE` | `Asia/Almaty` | Часовой пояс |
| `RATE_LIMIT_PER_HOUR` | `3` | Заявок в час на пользователя |
| `GOOGLE_CREDENTIALS` | `credentials.json` | Ключ сервисного аккаунта |
| `GOOGLE_SHEET_ID` | — | ID таблицы (пусто — выгрузка выключена) |
| `GOOGLE_WORKSHEET` | `Заявки` | Имя листа |
| `SYNC_INTERVAL_SECONDS` | `60` | Повтор выгрузки при ошибке |

## Структура

```
bot/
  __main__.py      точка входа
  config.py        настройки из .env
  form.py          загрузка и проверка form.toml
  answers.py       проверка ответов по типам вопросов
  db.py            SQLite: заявки, карточки в чатах, очередь выгрузки
  delivery.py      отправка и обновление карточек
  sheets.py        Google Sheets (gspread)
  sync.py          фоновая выгрузка с очередью
  keyboards.py     клавиатуры и CallbackData
  utils.py         форматирование, статусы
  handlers/
    client.py      анкета и «Мои заявки»
    admin.py       статусы и админ-команды
tests/test_flow.py сквозной тест без Telegram и Google
```

## Тест

```bash
python -m tests.test_flow
```
