from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.form import Question
from bot.utils import STATUSES

BTN_NEW = "📝 Оставить заявку"
BTN_MY = "📂 Мои заявки"
BTN_BACK = "◀️ Назад"
BTN_SKIP = "⏭ Пропустить"
BTN_CANCEL = "✖️ Отмена"
BTN_CONTACT = "📱 Отправить мой номер"
RESERVED = {BTN_NEW, BTN_MY, BTN_BACK, BTN_SKIP, BTN_CANCEL, BTN_CONTACT}


class ConfirmCb(CallbackData, prefix="cf"):
    action: str  # send | restart | cancel


class LeadCb(CallbackData, prefix="ld"):
    id: int
    status: str


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_MY)]],
        resize_keyboard=True,
    )


def question_kb(q: Question, first: bool) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    if q.type == "choice":
        opts = [KeyboardButton(text=o) for o in q.options]
        rows.extend(opts[i:i + 2] for i in range(0, len(opts), 2))
    if q.type == "phone":
        rows.append([KeyboardButton(text=BTN_CONTACT, request_contact=True)])
    nav = []
    if not first:
        nav.append(KeyboardButton(text=BTN_BACK))
    if not q.required:
        nav.append(KeyboardButton(text=BTN_SKIP))
    if nav:
        rows.append(nav)
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data=ConfirmCb(action="send").pack())],
        [
            InlineKeyboardButton(text="✏️ Заново", callback_data=ConfirmCb(action="restart").pack()),
            InlineKeyboardButton(text=BTN_CANCEL, callback_data=ConfirmCb(action="cancel").pack()),
        ],
    ])


def status_kb(lead_id: int, current: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for status in ("work", "done", "reject"):
        label = STATUSES[status]
        b.button(text=f"• {label} •" if status == current else label, callback_data=LeadCb(id=lead_id, status=status))
    b.adjust(3)
    return b.as_markup()
