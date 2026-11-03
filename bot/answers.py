from typing import Any

from aiogram.types import Message

from bot.form import Question
from bot.utils import normalize_phone


def _fmt_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def parse_answer(q: Question, message: Message) -> tuple[Any, str | None]:
    """Проверяет ответ на вопрос. Возвращает (значение, None) или (None, текст ошибки)."""
    if q.type == "file":
        if message.photo:
            return {"kind": "photo", "file_id": message.photo[-1].file_id}, None
        if message.document:
            return {"kind": "document", "file_id": message.document.file_id, "name": message.document.file_name}, None
        return None, "Пришлите фото или файл."

    if q.type == "phone" and message.contact:
        raw = message.contact.phone_number
    elif message.text:
        raw = message.text.strip()
    else:
        return None, "Ответьте текстом."

    if raw.startswith("/"):
        return None, "Ответ не может начинаться с «/». Чтобы выйти, нажмите «Отмена»."

    if q.type == "phone":
        phone = normalize_phone(raw)
        return (phone, None) if phone else (None, "Не похоже на номер телефона. Пример: +7 701 123 45 67")

    if q.type == "choice":
        return (raw, None) if raw in q.options else (None, "Выберите вариант кнопкой ниже.")

    if q.type == "number":
        try:
            value = float(raw.replace(" ", "").replace(",", "."))
        except ValueError:
            return None, "Введите число."
        if value != value or value in (float("inf"), float("-inf")):
            return None, "Введите число."
        if q.min is not None and value < q.min:
            return None, f"Число должно быть не меньше {_fmt_number(float(q.min))}."
        if q.max is not None and value > q.max:
            return None, f"Число должно быть не больше {_fmt_number(float(q.max))}."
        return _fmt_number(value), None

    if not q.min_length <= len(raw) <= q.max_length:
        return None, f"Ответ должен быть от {q.min_length} до {q.max_length} символов."
    return raw, None
