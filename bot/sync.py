import asyncio
import logging

from bot.db import Database
from bot.form import Form
from bot.sheets import SheetsBackend
from bot.utils import sheet_header, sheet_row

log = logging.getLogger(__name__)


class SheetSync:
    """Фоновая выгрузка заявок в Google Sheets. Без backend — ничего не делает."""

    def __init__(self, db: Database, form: Form, backend: SheetsBackend | None, interval: int = 60) -> None:
        self.db = db
        self.form = form
        self.backend = backend
        self.interval = interval
        self._event = asyncio.Event()
        self._header_ok = False

    def poke(self) -> None:
        """Попросить выгрузить изменения прямо сейчас."""
        self._event.set()

    async def sync_once(self) -> int:
        if self.backend is None:
            return 0
        if not self._header_ok:
            await self.backend.set_header(sheet_header(self.form))
            self._header_ok = True
        done = 0
        for lead in await self.db.unsynced():
            values = sheet_row(lead, self.form)
            if lead["sheet_row"] is None:
                row = await self.backend.append(values)
            else:
                row = lead["sheet_row"]
                await self.backend.update(row, values)
            await self.db.mark_synced(lead["id"], lead["version"], row)
            done += 1
        return done

    async def run(self) -> None:
        if self.backend is None:
            return
        while True:
            self._event.clear()
            try:
                synced = await self.sync_once()
                if synced:
                    log.info("Google Sheets: выгружено %s", synced)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Google Sheets недоступен, повтор через %s с", self.interval)
            try:
                await asyncio.wait_for(self._event.wait(), timeout=self.interval)
            except TimeoutError:
                pass
