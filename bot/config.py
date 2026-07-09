from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    BOT_TOKEN: str
    DATABASE_URL: str
    REDIS_URL: str
    DEBUG: bool = False
    ADMIN_ID: Optional[int] = None

    # Test rejimi: True bo'lsa obuna talab qilinmaydi (hamma yuklarni ko'radi).
    # Pulli qilish uchun .env da FREE_MODE=false qiling va botni qayta ishga tushiring.
    FREE_MODE: bool = False

    # Telethon — kanal o'qish uchun user-account
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_PHONE: str = ""

    # Kuzatiladigan kanal ID lari, vergul bilan: -1001234567,-1009876543
    CHANNEL_IDS: str = ""

    # LORRY (ichki tashuvlar) guruhi — logist aniqlash FAQAT shu kanallarda ishlaydi.
    # Boshqa kanallar: hamma real client -> yuklar to'g'ridan bazaga tushadi.
    # Bo'sh bo'lsa — logist aniqlash o'chiq.
    LORRY_CHANNEL_IDS: str = ""

    # OpenAI (ixtiyoriy — bo'sh bo'lsa faqat regex ishlatiladi)
    OPENAI_API_KEY: str = ""

    # Moderatsiyasiz auto-tasdiqlash chegarasi
    PARSER_AUTO_APPROVE_CONFIDENCE: float = 0.85

    @property
    def channel_ids_list(self) -> List[int]:
        if not self.CHANNEL_IDS:
            return []
        try:
            return [int(x.strip()) for x in self.CHANNEL_IDS.split(",") if x.strip()]
        except ValueError:
            return []

    @property
    def lorry_channel_ids_list(self) -> List[int]:
        if not self.LORRY_CHANNEL_IDS:
            return []
        try:
            return [int(x.strip()) for x in self.LORRY_CHANNEL_IDS.split(",") if x.strip()]
        except ValueError:
            return []


settings = Settings()
