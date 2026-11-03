import asyncio
import re
from typing import Protocol

_ROW_RE = re.compile(r"![A-Z]+(\d+)")


class SheetsBackend(Protocol):
    async def set_header(self, header: list[str]) -> None: ...
    async def append(self, values: list) -> int: ...
    async def update(self, row: int, values: list) -> None: ...


def parse_row(updated_range: str) -> int:
    """'Заявки'!A5:J5 -> 5"""
    match = _ROW_RE.search(updated_range)
    if not match:
        raise ValueError(f"Не удалось определить строку из {updated_range!r}")
    return int(match.group(1))


class GoogleSheets:
    """Обёртка над gspread (синхронной библиотекой) — вызовы уходят в отдельный поток."""

    def __init__(self, credentials_path: str, sheet_id: str, worksheet: str) -> None:
        self._credentials_path = credentials_path
        self._sheet_id = sheet_id
        self._worksheet_name = worksheet
        self._ws = None

    def _worksheet(self):
        if self._ws is None:
            import gspread

            client = gspread.service_account(filename=self._credentials_path)
            spreadsheet = client.open_by_key(self._sheet_id)
            try:
                self._ws = spreadsheet.worksheet(self._worksheet_name)
            except gspread.WorksheetNotFound:
                self._ws = spreadsheet.add_worksheet(title=self._worksheet_name, rows=1000, cols=26)
        return self._ws

    async def set_header(self, header: list[str]) -> None:
        await asyncio.to_thread(lambda: self._worksheet().update(values=[header], range_name="A1"))

    async def append(self, values: list) -> int:
        response = await asyncio.to_thread(
            lambda: self._worksheet().append_row(values, insert_data_option="INSERT_ROWS", table_range="A1")
        )
        return parse_row(response["updates"]["updatedRange"])

    async def update(self, row: int, values: list) -> None:
        await asyncio.to_thread(lambda: self._worksheet().update(values=[values], range_name=f"A{row}"))
