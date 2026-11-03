from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.answers import parse_answer
from bot.config import Config
from bot.db import Database
from bot.delivery import deliver_lead
from bot.form import Form
from bot.states import LeadForm
from bot.sync import SheetSync
from bot.utils import answers_text, lead_short, now_local

router = Router(name="client")


async def _ask(message: Message, state: FSMContext, form: Form, idx: int) -> None:
    q = form.questions[idx]
    await state.update_data(idx=idx)
    await state.set_state(LeadForm.answering)
    optional = "" if q.required else "\n<i>Можно пропустить</i>"
    await message.answer(
        f"<b>{idx + 1}/{len(form.questions)}.</b> {escape(q.text)}{optional}",
        reply_markup=kb.question_kb(q, first=idx == 0),
    )


async def _show_summary(message: Message, state: FSMContext, form: Form) -> None:
    data = await state.get_data()
    await state.set_state(LeadForm.confirm)
    await message.answer("Проверьте заявку 👇", reply_markup=kb.main_menu())
    await message.answer(
        f"<b>{escape(form.title)}</b>\n\n{answers_text(form, data['answers'])}",
        reply_markup=kb.confirm_kb(),
    )


async def _limit_reached(db: Database, cfg: Config, user_id: int) -> bool:
    since = now_local(cfg) - timedelta(hours=1)
    return await db.count_since(user_id, since) >= cfg.rate_limit_per_hour


# --- Меню ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, form: Form) -> None:
    await state.clear()
    intro = f"\n\n{escape(form.intro)}" if form.intro else ""
    await message.answer(
        f"Здравствуйте! Здесь можно оставить заявку: <b>{escape(form.title)}</b>.{intro}",
        reply_markup=kb.main_menu(),
    )


@router.message(Command("new"))
@router.message(F.text == kb.BTN_NEW)
async def cmd_new(message: Message, state: FSMContext, db: Database, cfg: Config, form: Form) -> None:
    await state.clear()
    if await _limit_reached(db, cfg, message.from_user.id):
        await message.answer("Вы уже отправили несколько заявок за последний час. Попробуйте позже.")
        return
    await state.update_data(answers={})
    await _ask(message, state, form, 0)


@router.message(Command("my"))
@router.message(F.text == kb.BTN_MY)
async def cmd_my(message: Message, state: FSMContext, db: Database, form: Form) -> None:
    await state.clear()
    leads = await db.user_leads(message.from_user.id)
    if not leads:
        await message.answer("У вас пока нет заявок.", reply_markup=kb.main_menu())
        return
    text = "<b>Ваши заявки</b>\n\n" + "\n\n".join(lead_short(lead, form) for lead in leads)
    await message.answer(text, reply_markup=kb.main_menu())


# --- Анкета ---

@router.message(LeadForm.answering)
async def answer(message: Message, state: FSMContext, form: Form) -> None:
    data = await state.get_data()
    idx: int = data["idx"]
    answers: dict = data["answers"]
    q = form.questions[idx]

    if message.text == kb.BTN_CANCEL:
        await state.clear()
        await message.answer("Заявка отменена.", reply_markup=kb.main_menu())
        return

    if message.text == kb.BTN_BACK and idx > 0:
        answers.pop(q.key, None)
        answers.pop(form.questions[idx - 1].key, None)
        await state.update_data(answers=answers)
        await _ask(message, state, form, idx - 1)
        return

    if message.text == kb.BTN_BACK:  # уже на первом вопросе
        await _ask(message, state, form, idx)
        return

    if message.text == kb.BTN_SKIP:
        if q.required:
            await message.answer("Этот вопрос обязательный.")
            return
        answers.pop(q.key, None)
    else:
        value, error = parse_answer(q, message)
        if error:
            await message.answer(error)
            return
        answers[q.key] = value

    await state.update_data(answers=answers)
    if idx + 1 < len(form.questions):
        await _ask(message, state, form, idx + 1)
    else:
        await _show_summary(message, state, form)


@router.message(LeadForm.confirm)
async def confirm_hint(message: Message) -> None:
    await message.answer("Нажмите «✅ Отправить» под заявкой или «✏️ Заново».")


@router.callback_query(LeadForm.confirm, kb.ConfirmCb.filter(F.action == "send"))
async def send_lead(
    cb: CallbackQuery, state: FSMContext, db: Database, cfg: Config, form: Form, bot: Bot, sync: SheetSync
) -> None:
    user = cb.from_user
    if await _limit_reached(db, cfg, user.id):
        await state.clear()
        await cb.message.edit_text("Слишком много заявок за последний час. Попробуйте позже.")
        await cb.answer()
        return

    data = await state.get_data()
    lead_id = await db.create_lead(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        answers=data["answers"],
        now=now_local(cfg),
    )
    await state.clear()
    await cb.message.edit_text(
        f"✅ <b>Заявка #{lead_id} отправлена</b>\n\n{answers_text(form, data['answers'])}\n\n{escape(form.done)}"
    )
    await cb.answer()

    await deliver_lead(bot, db, form, await db.get_lead(lead_id), cfg.lead_targets)
    sync.poke()


@router.callback_query(LeadForm.confirm, kb.ConfirmCb.filter(F.action == "restart"))
async def restart(cb: CallbackQuery, state: FSMContext, form: Form) -> None:
    await cb.message.edit_text("Заполняем заново.")
    await cb.answer()
    await state.update_data(answers={})
    await _ask(cb.message, state, form, 0)


@router.callback_query(kb.ConfirmCb.filter(F.action == "cancel"))
async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Заявка отменена.")
    await cb.answer()


@router.callback_query(kb.ConfirmCb.filter())
async def stale_confirm(cb: CallbackQuery) -> None:
    await cb.answer("Кнопка устарела. Начните заново: /new", show_alert=True)
