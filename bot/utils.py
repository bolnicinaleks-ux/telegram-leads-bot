import json
import re
from datetime import datetime
from html import escape
from typing import Any

from bot.form import Form

DT_FMT = "%Y-%m-%d %H:%M"

STATUSES = {
    "new": "🆕 Новая",
    "work": "🔧 В работе",
    "done": "✅ Выполнена",
    "reject": "❌ Отказ",
}
STATUS_PLAIN = {"new": "Новая", "work": "В работе", "done": "Выполнена", "reject": "Отказ"}
CLIENT_STATUS_TEXT = {"work": "взята в работу", "done": "выполнена", "reject": "отклонена"}


def now_local(cfg) -> datetime:
    return datetime.now(cfg.tz).replace(tzinfo=None, second=0, microsecond=0)


def dt_to_str(dt: datetime) -> str:
    return dt.strftime(DT_FMT)


def fmt_created(value: str) -> str:
    return datetime.strptime(value, DT_FMT).strftime("%d.%m.%Y %H:%M")


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not 10 <= len(digits) <= 15:
        return None
    return "+" + digits


def fmt_value(value: Any) -> str:
    if isinstance(value, dict):
        return "📎 фото" if value.get("kind") == "photo" else f"📎 {value.get('name') or 'файл'}"
    return str(value)


def plain_value(value: Any) -> str:
    """Значение для таблицы/CSV (без эмодзи)."""
    if isinstance(value, dict):
        return "фото" if value.get("kind") == "photo" else f"файл: {value.get('name') or ''}".strip()
    return str(value)


def answers_text(form: Form, answers: dict) -> str:
    lines = []
    for q in form.questions:
        if q.key in answers:
            lines.append(f"<b>{escape(q.label)}:</b> {escape(fmt_value(answers[q.key]))}")
    return "\n".join(lines) or "—"


def tg_contact(lead) -> str:
    if lead["username"]:
        return f"@{lead['username']}"
    return f'<a href="tg://user?id={lead["user_id"]}">{escape(lead["full_name"])}</a>'


def tg_plain(lead) -> str:
    return f"@{lead['username']}" if lead["username"] else f"id {lead['user_id']}"


def lead_answers(lead) -> dict:
    return json.loads(lead["answers"])


def lead_card(lead, form: Form) -> str:
    return (
        f"<b>Заявка #{lead['id']}</b> · {STATUSES[lead['status']]}\n"
        f"{fmt_created(lead['created_at'])} · {tg_contact(lead)}\n\n"
        f"{answers_text(form, lead_answers(lead))}"
    )


def lead_short(lead, form: Form) -> str:
    answers = lead_answers(lead)
    preview = ", ".join(
        plain_value(answers[q.key]) for q in form.questions[:3] if q.key in answers and q.type != "file"
    )
    return f"#{lead['id']} · {fmt_created(lead['created_at'])} · {STATUSES[lead['status']]}\n{escape(preview)}"


def sheet_header(form: Form) -> list[str]:
    return ["ID", "Создана", "Статус", "Telegram", *form.labels, "Обновлена"]


def sheet_row(lead, form: Form) -> list[str | int]:
    answers = lead_answers(lead)
    return [
        lead["id"],
        fmt_created(lead["created_at"]),
        STATUS_PLAIN[lead["status"]],
        tg_plain(lead),
        *(plain_value(answers[q.key]) if q.key in answers else "" for q in form.questions),
        fmt_created(lead["updated_at"]),
    ]
