import csv
import io

from aiogram import Bot, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot import keyboards as kb
from bot.config import Config
from bot.db import Database
from bot.delivery import notify_user, refresh_cards, send_card
from bot.form import Form
from bot.sync import SheetSync
from bot.utils import CLIENT_STATUS_TEXT, STATUSES, lead_short, now_local, sheet_header, sheet_row

HELP = (
    "<b>Админ-панель</b>\n\n"
    "/leads — последние 10 заявок\n"
    "/leads new|work|done|reject — по статусу\n"
    "/lead ID — карточка заявки с кнопками статуса\n"
    "/export — все заявки в CSV (Excel)"
)


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message, cfg: Config) -> bool:
        return message.from_user is not None and message.from_user.id in cfg.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("leads"))
async def cmd_leads(message: Message, command: CommandObject, db: Database, form: Form) -> None:
    status = (command.args or "").strip() or None
    if status and status not in STATUSES:
        await message.answer("Статусы: new, work, done, reject")
        return
    leads = await db.recent_leads(10, status)
    if not leads:
        await message.answer("Заявок нет.")
        return
    await message.answer("\n\n".join(lead_short(lead, form) for lead in leads) + "\n\nПодробнее: /lead ID")


@router.message(Command("lead"))
async def cmd_lead(message: Message, command: CommandObject, db: Database, form: Form, bot: Bot) -> None:
    try:
        lead_id = int((command.args or "").strip().lstrip("#"))
    except ValueError:
        await message.answer("Формат: /lead 12")
        return
    lead = await db.get_lead(lead_id)
    if lead is None:
        await message.answer(f"Заявка #{lead_id} не найдена.")
        return
    await send_card(bot, db, form, lead, message.chat.id)


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database, form: Form, cfg: Config) -> None:
    leads = await db.all_leads()
    if not leads:
        await message.answer("Заявок нет.")
        return
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(sheet_header(form))
    writer.writerows(sheet_row(lead, form) for lead in leads)
    filename = f"leads-{now_local(cfg):%Y%m%d-%H%M}.csv"
    await message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename=filename),
        caption=f"Заявок: {len(leads)}",
    )


# Кнопки статуса работают у админов и у всех участников рабочей группы
@router.callback_query(kb.LeadCb.filter())
async def change_status(
    cb: CallbackQuery, callback_data: kb.LeadCb, db: Database, cfg: Config, form: Form, bot: Bot, sync: SheetSync
) -> None:
    in_leads_chat = cfg.leads_chat_id is not None and cb.message is not None and cb.message.chat.id == cfg.leads_chat_id
    lead = await db.get_lead(callback_data.id)
    own_demo = cfg.demo_mode and lead is not None and lead["user_id"] == cb.from_user.id
    if cb.from_user.id not in cfg.admin_ids and not in_leads_chat and not own_demo:
        await cb.answer("Нет доступа", show_alert=True)
        return
    status = callback_data.status
    if status not in STATUSES:
        await cb.answer()
        return
    if not await db.set_status(callback_data.id, status, now_local(cfg)):
        await cb.answer("Статус уже установлен" if await db.get_lead(callback_data.id) else "Заявка не найдена")
        return

    lead = await db.get_lead(callback_data.id)
    await refresh_cards(bot, db, form, lead)
    sync.poke()
    await cb.answer(f"Статус: {STATUSES[status]}")

    if status in CLIENT_STATUS_TEXT:
        await notify_user(bot, lead["user_id"], f"Ваша заявка #{lead['id']} {CLIENT_STATUS_TEXT[status]}.")
