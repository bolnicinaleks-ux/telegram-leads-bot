import asyncio
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import Config, load_config
from bot.db import Database
from bot.form import Form, load_form
from bot.handlers import admin, client
from bot.keyboards import RESERVED
from bot.sheets import GoogleSheets
from bot.sync import SheetSync


def build_dispatcher(db: Database, cfg: Config, form: Form, sync: SheetSync) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), db=db, cfg=cfg, form=form, sync=sync)
    dp.include_routers(admin.router, client.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    form = load_form(cfg.form_path, reserved=RESERVED)
    logging.info("Анкета «%s»: вопросов %s", form.title, len(form.questions))

    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    db = Database(cfg.db_path)
    await db.connect()

    backend = (
        GoogleSheets(cfg.google_credentials, cfg.google_sheet_id, cfg.google_worksheet) if cfg.sheets_enabled else None
    )
    if backend is None:
        logging.info("Google Sheets выключен (GOOGLE_SHEET_ID пуст)")
    sync = SheetSync(db, form, backend, cfg.sync_interval)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(db, cfg, form, sync)
    sync_task = asyncio.create_task(sync.run())
    # Всё, что может упасть (например, нет сети при старте), — внутри try:
    # иначе открытая БД не даст процессу завершиться и супервизор не перезапустит бота.
    try:
        await bot.set_my_commands([
            BotCommand(command="new", description="Оставить заявку"),
            BotCommand(command="my", description="Мои заявки"),
            BotCommand(command="start", description="Главное меню"),
        ])
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
