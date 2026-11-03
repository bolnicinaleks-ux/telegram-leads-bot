"""Сквозной прогон бота без Telegram и без Google: апдейты подаются в Dispatcher,
ответы Telegram перехватывает фейковая сессия, таблицу заменяет FakeSheets.

Запуск: python -m tests.test_flow
"""
import asyncio
import csv
import io
import itertools
import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendDocument, SendMessage, SendPhoto
from aiogram.types import CallbackQuery, Chat, Contact, Document, Message, PhotoSize, Update, User

from bot.__main__ import build_dispatcher
from bot.config import Config
from bot.db import Database
from bot.form import FormError, load_form
from bot.keyboards import RESERVED
from bot.sheets import parse_row
from bot.sync import SheetSync

ADMIN, CLIENT, CLIENT2, STRANGER, GROUP = 1000, 2000, 3000, 4000, -100500
FORM_PATH = os.path.join(os.path.dirname(__file__), "..", "form.toml")
_ids = itertools.count(1)


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText, SendPhoto, SendDocument)):
            return Message(
                message_id=getattr(method, "message_id", None) or next(_ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=getattr(method, "text", None),
            )
        return True

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    def of(self, *types, chat_id=None):
        return [c for c in self.calls if isinstance(c, types) and (chat_id is None or c.chat_id == chat_id)]

    def last_text(self, chat_id: int) -> str:
        return self.of(SendMessage, EditMessageText, chat_id=chat_id)[-1].text

    def alerts(self) -> list[str]:
        return [c.text for c in self.of(AnswerCallbackQuery) if c.text]


class FakeSheets:
    def __init__(self) -> None:
        self.header: list | None = None
        self.rows: dict[int, list] = {}
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("Google недоступен")

    async def set_header(self, header):
        self._check()
        self.header = header

    async def append(self, values):
        self._check()
        row = len(self.rows) + 2
        self.rows[row] = values
        return row

    async def update(self, row, values):
        self._check()
        self.rows[row] = values


def user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"U{uid}", username="ivan" if uid == CLIENT else None)


def msg(uid: int, text: str | None = None, *, chat: int | None = None, **extra) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids), date=datetime.now(), chat=Chat(id=chat or uid, type="private"),
            from_user=user(uid), text=text, **extra,
        ),
    )


def press(uid: int, data: str, *, chat: int | None = None) -> Update:
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=str(next(_ids)), from_user=user(uid), chat_instance="ci", data=data,
            message=Message(message_id=next(_ids), date=datetime.now(),
                            chat=Chat(id=chat or uid, type="private"), text="-"),
        ),
    )


PHOTO = [PhotoSize(file_id="small", file_unique_id="s", width=90, height=90),
         PhotoSize(file_id="big", file_unique_id="b", width=800, height=800)]


def unit_checks() -> None:
    assert parse_row("'Заявки'!A5:J5") == 5
    assert parse_row("Sheet1!A12:B12") == 12
    tmp = tempfile.mkdtemp()
    bad = os.path.join(tmp, "bad.toml")
    for content, err in [
        ('[[questions]]\nkey="a"\ntext="?"\ntype="xxx"', "неизвестный type"),
        ('[[questions]]\nkey="a"\ntext="?"\ntype="choice"', "нужен список options"),
        ('[[questions]]\nkey="a"\ntext="?"\n[[questions]]\nkey="a"\ntext="?"', "повторяющийся key"),
        ('[[questions]]\nkey="a"\ntext="?"\ntype="choice"\noptions=["✖️ Отмена"]', "служебными"),
        ('title="x"', "нет вопросов"),
        ('title = ', "синтаксиса"),
    ]:
        with open(bad, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            load_form(bad, RESERVED)
        except FormError as e:
            assert err in str(e), (err, e)
        else:
            raise AssertionError(f"ожидалась ошибка: {err}")
    print("✔ разбор диапазона Sheets и валидация form.toml")


async def main() -> None:
    unit_checks()

    tmp = tempfile.mkdtemp()
    cfg = Config(
        bot_token="123456:" + "A" * 35,
        admin_ids=frozenset({ADMIN}),
        leads_chat_id=None,
        db_path=os.path.join(tmp, "test.db"),
        form_path=FORM_PATH,
        tz=ZoneInfo("Asia/Almaty"),
        rate_limit_per_hour=2,
        google_credentials="",
        google_sheet_id="test",
        google_worksheet="Заявки",
        sync_interval=60,
    )
    db = Database(cfg.db_path)
    await db.connect()
    try:
        await run_scenario(cfg, db)
    finally:
        await db.close()
    print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


async def run_scenario(cfg: Config, db: Database) -> None:
    form = load_form(cfg.form_path, RESERVED)
    sheets = FakeSheets()
    sync = SheetSync(db, form, sheets)
    session = FakeSession()
    bot = Bot(cfg.bot_token, session=session)
    dp = build_dispatcher(db, cfg, form, sync)
    feed = lambda upd: dp.feed_update(bot, upd)  # noqa: E731

    # 1. Полная анкета с ошибками ввода
    await feed(msg(CLIENT, "/start"))
    assert "Заявка на ремонт" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "📝 Оставить заявку"))
    assert "1/6" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "⏭ Пропустить"))
    assert "обязательный" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "И"))
    assert "от 2 до 50" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "/help"))
    assert "«/»" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "Иван"))
    await feed(msg(CLIENT, "123"))
    assert "Не похоже" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "8 (701) 123-45-67"))
    await feed(msg(CLIENT, "Крыша"))
    assert "кнопкой" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "Сантехника"))
    await feed(msg(CLIENT, "много"))
    assert "Введите число" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "0"))
    assert "не меньше 1" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "42,5"))
    await feed(msg(CLIENT, "без фото"))
    assert "фото или файл" in session.last_text(CLIENT)
    await feed(msg(CLIENT, photo=PHOTO))
    await feed(msg(CLIENT, "Течёт кран <на кухне>"))
    summary = session.last_text(CLIENT)
    for part in ("Иван", "+77011234567", "Сантехника", "42.5", "📎 фото", "&lt;на кухне&gt;"):
        assert part in summary, part
    await feed(press(CLIENT, "cf:send"))
    assert "Заявка #1 отправлена" in session.last_text(CLIENT)

    card = session.of(SendMessage, chat_id=ADMIN)[-1]
    assert "Заявка #1" in card.text and "@ivan" in card.text and "🆕 Новая" in card.text
    photo = session.of(SendPhoto, chat_id=ADMIN)[-1]
    assert photo.photo == "big" and photo.reply_parameters.message_id is not None
    print("✔ анкета: валидация всех типов, подтверждение, карточка и фото админу")

    # 2. Выгрузка в Google Sheets
    assert await sync.sync_once() == 1
    assert sheets.header == ["ID", "Создана", "Статус", "Telegram", "Имя", "Телефон", "Услуга",
                             "Площадь, м²", "Фото", "Комментарий", "Обновлена"]
    row = sheets.rows[2]
    assert row[0] == 1 and row[2] == "Новая" and row[3] == "@ivan" and row[5] == "+77011234567" and row[8] == "фото"
    assert await sync.sync_once() == 0
    print("✔ Google Sheets: заголовок и строка заявки")

    # 3. Смена статуса админом: карточка, клиент, таблица
    await feed(press(STRANGER, "ld:1:work"))
    assert session.alerts()[-1] == "Нет доступа"
    await feed(press(ADMIN, "ld:1:work"))
    edit = session.of(EditMessageText, chat_id=ADMIN)[-1]
    assert "🔧 В работе" in edit.text and "Заявка #1" in edit.text
    assert "взята в работу" in session.last_text(CLIENT)
    await feed(press(ADMIN, "ld:1:work"))
    assert session.alerts()[-1] == "Статус уже установлен"
    assert await sync.sync_once() == 1
    assert sheets.rows[2][2] == "В работе" and len(sheets.rows) == 1
    print("✔ статусы: доступ, обновление карточки, уведомление клиента, строка в таблице")

    # 4. Назад, пропуск, отмена, контакт-кнопкой, документ
    await feed(msg(CLIENT2, "/new"))
    await feed(msg(CLIENT2, "◀️ Назад"))  # на первом вопросе — просто повтор
    assert "1/6" in session.last_text(CLIENT2)
    await feed(msg(CLIENT2, "Анна"))
    await feed(msg(CLIENT2, "◀️ Назад"))
    assert "1/6" in session.last_text(CLIENT2)
    await feed(msg(CLIENT2, "Анна Ли"))
    await feed(msg(CLIENT2, contact=Contact(phone_number="77770001122", first_name="Анна", user_id=CLIENT2)))
    await feed(msg(CLIENT2, "Электрика"))
    await feed(msg(CLIENT2, "⏭ Пропустить"))
    await feed(msg(CLIENT2, document=Document(file_id="doc1", file_unique_id="d1", file_name="смета.pdf")))
    await feed(msg(CLIENT2, "⏭ Пропустить"))
    summary = session.last_text(CLIENT2)
    assert "Анна Ли" in summary and "+77770001122" in summary and "смета.pdf" in summary and "Площадь" not in summary
    await feed(press(CLIENT2, "cf:restart"))
    assert "1/6" in session.last_text(CLIENT2)
    await feed(msg(CLIENT2, "✖️ Отмена"))
    assert "отменена" in session.last_text(CLIENT2)
    assert len(await db.all_leads()) == 1
    print("✔ навигация: назад, пропуск, заново, отмена; контакт и документ")

    # 5. Лимит заявок в час (2)
    async def quick_lead(uid: int) -> None:
        await feed(msg(uid, "/new"))
        for text in ("Пётр", "+7 777 000 00 00", "Другое", "⏭ Пропустить", "⏭ Пропустить", "⏭ Пропустить"):
            await feed(msg(uid, text))
        await feed(press(uid, "cf:send"))

    await quick_lead(CLIENT)
    assert "Заявка #2 отправлена" in session.last_text(CLIENT)
    await feed(msg(CLIENT, "/new"))
    assert "Попробуйте позже" in session.last_text(CLIENT)
    print("✔ ограничение заявок в час")

    # 6. Google недоступен -> заявка в очереди, потом догружается
    sheets.fail = True
    try:
        await sync.sync_once()
    except ConnectionError:
        pass
    assert len(await db.unsynced()) == 1
    sheets.fail = False
    assert await sync.sync_once() == 1 and len(sheets.rows) == 2 and not await db.unsynced()
    print("✔ очередь выгрузки при недоступном Google")

    # 7. Админ-команды и «Мои заявки»
    await feed(msg(CLIENT, "/leads"))
    assert not any("Подробнее" in t.text for t in session.of(SendMessage, chat_id=CLIENT))
    await feed(msg(ADMIN, "/admin"))
    assert "Админ-панель" in session.last_text(ADMIN)
    await feed(msg(ADMIN, "/leads"))
    assert "#2" in session.last_text(ADMIN) and "#1" in session.last_text(ADMIN)
    await feed(msg(ADMIN, "/leads work"))
    assert "#1" in session.last_text(ADMIN) and "#2" not in session.last_text(ADMIN)
    await feed(msg(ADMIN, "/leads xxx"))
    assert "Статусы" in session.last_text(ADMIN)
    await feed(msg(ADMIN, "/lead 1"))
    assert "Заявка #1" in session.last_text(ADMIN)
    assert len(await db.lead_messages(1)) == 2
    await feed(msg(ADMIN, "/lead 99"))
    assert "не найдена" in session.last_text(ADMIN)

    await feed(msg(ADMIN, "/export"))
    doc = session.of(SendDocument, chat_id=ADMIN)[-1]
    content = doc.document.data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(content), delimiter=";"))
    assert rows[0][0] == "ID" and len(rows) == 3 and rows[1][4] == "Иван"

    await feed(msg(CLIENT, "📂 Мои заявки"))
    my = session.last_text(CLIENT)
    assert "#1" in my and "🔧 В работе" in my and "#2" in my
    print("✔ /admin, /leads, /lead, /export (CSV), «Мои заявки»")

    # 8. Рабочая группа: кнопки статуса доступны её участникам
    cfg_group = Config(**{**{f: getattr(cfg, f) for f in cfg.__slots__}, "leads_chat_id": GROUP})
    await dp.feed_update(bot, press(STRANGER, "ld:2:done", chat=GROUP), cfg=cfg_group)
    assert (await db.get_lead(2))["status"] == "done"
    assert cfg_group.lead_targets == [GROUP]
    print("✔ рабочая группа: смена статуса участником")

    # 9. Устаревшая кнопка подтверждения
    await feed(press(CLIENT2, "cf:send"))
    assert "устарела" in session.alerts()[-1]
    print("✔ устаревшие кнопки")


if __name__ == "__main__":
    asyncio.run(main())
