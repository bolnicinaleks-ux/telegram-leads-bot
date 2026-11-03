import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ReplyParameters

from bot import keyboards as kb
from bot.db import Database
from bot.form import Form
from bot.utils import lead_answers, lead_card

log = logging.getLogger(__name__)


async def send_card(bot: Bot, db: Database, form: Form, lead, chat_id: int) -> bool:
    """Карточка заявки с кнопками статуса + вложения ответами на неё."""
    try:
        card = await bot.send_message(chat_id, lead_card(lead, form), reply_markup=kb.status_kb(lead["id"], lead["status"]))
    except TelegramAPIError as e:
        log.warning("Не удалось отправить заявку #%s в чат %s: %s", lead["id"], chat_id, e)
        return False
    await db.add_message(lead["id"], chat_id, card.message_id)

    answers = lead_answers(lead)
    for q in form.questions:
        value = answers.get(q.key)
        if not isinstance(value, dict):
            continue
        caption = f"Заявка #{lead['id']} · {q.label}"
        reply = ReplyParameters(message_id=card.message_id, allow_sending_without_reply=True)
        try:
            if value["kind"] == "photo":
                await bot.send_photo(chat_id, value["file_id"], caption=caption, reply_parameters=reply)
            else:
                await bot.send_document(chat_id, value["file_id"], caption=caption, reply_parameters=reply)
        except TelegramAPIError as e:
            log.warning("Не удалось отправить вложение заявки #%s: %s", lead["id"], e)
    return True


async def deliver_lead(bot: Bot, db: Database, form: Form, lead, targets: list[int]) -> int:
    delivered = 0
    for chat_id in targets:
        delivered += await send_card(bot, db, form, lead, chat_id)
    return delivered


async def refresh_cards(bot: Bot, db: Database, form: Form, lead) -> None:
    text = lead_card(lead, form)
    markup = kb.status_kb(lead["id"], lead["status"])
    for m in await db.lead_messages(lead["id"]):
        try:
            await bot.edit_message_text(text=text, chat_id=m["chat_id"], message_id=m["message_id"], reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                log.info("Карточка %s/%s не обновлена: %s", m["chat_id"], m["message_id"], e)
        except TelegramAPIError as e:
            log.warning("Карточка %s/%s не обновлена: %s", m["chat_id"], m["message_id"], e)


async def notify_user(bot: Bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text)
        return True
    except TelegramAPIError as e:
        log.warning("Не удалось написать пользователю %s: %s", user_id, e)
        return False
