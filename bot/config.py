import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def _parse_ints(value: str) -> frozenset[int]:
    return frozenset(int(v) for v in value.replace(" ", "").split(",") if v)


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    leads_chat_id: int | None
    db_path: str
    form_path: str
    tz: ZoneInfo
    rate_limit_per_hour: int
    google_credentials: str
    google_sheet_id: str
    google_worksheet: str
    sync_interval: int

    @property
    def sheets_enabled(self) -> bool:
        return bool(self.google_sheet_id)

    @property
    def lead_targets(self) -> list[int]:
        """Куда отправлять заявки: рабочая группа или каждый админ в личку."""
        return [self.leads_chat_id] if self.leads_chat_id else sorted(self.admin_ids)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан (см. .env.example)")
    leads_chat = os.getenv("LEADS_CHAT_ID", "").strip()

    cfg = Config(
        bot_token=token,
        admin_ids=_parse_ints(os.getenv("ADMIN_IDS", "")),
        leads_chat_id=int(leads_chat) if leads_chat else None,
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        form_path=os.getenv("FORM_PATH", "form.toml"),
        tz=ZoneInfo(os.getenv("TIMEZONE", "Asia/Almaty")),
        rate_limit_per_hour=int(os.getenv("RATE_LIMIT_PER_HOUR", "3")),
        google_credentials=os.getenv("GOOGLE_CREDENTIALS", "credentials.json"),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
        google_worksheet=os.getenv("GOOGLE_WORKSHEET", "Заявки"),
        sync_interval=int(os.getenv("SYNC_INTERVAL_SECONDS", "60")),
    )
    if not cfg.lead_targets:
        raise RuntimeError("Задайте ADMIN_IDS или LEADS_CHAT_ID — иначе заявки некуда отправлять")
    if cfg.sheets_enabled and not os.path.isfile(cfg.google_credentials):
        raise RuntimeError(f"GOOGLE_SHEET_ID задан, но нет файла ключа {cfg.google_credentials}")
    return cfg
