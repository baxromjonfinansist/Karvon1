from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AppSetting

# Faza 6 — bot instruksiyasi (video/matn) `app_settings` jadvalida shu
# key'lar bilan saqlanadi.
_INSTRUCTION_VIDEO_KEY = "instruction_video"
_INSTRUCTION_TEXT_KEY = "instruction_text"


async def _get_setting(session: AsyncSession, key: str) -> Optional[AppSetting]:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    return result.scalar_one_or_none()


async def get_instruction(session: AsyncSession) -> dict:
    """Hozirgi instruksiya video file_id va matnini qaytaradi (ikkalasi ham
    None bo'lishi mumkin — hali sozlanmagan)."""
    video = await _get_setting(session, _INSTRUCTION_VIDEO_KEY)
    text = await _get_setting(session, _INSTRUCTION_TEXT_KEY)
    return {
        "video_file_id": video.file_id if video else None,
        "text": text.value if text else None,
    }


async def save_instruction_video(session: AsyncSession, file_id: str) -> None:
    setting = await _get_setting(session, _INSTRUCTION_VIDEO_KEY)
    if setting is None:
        setting = AppSetting(key=_INSTRUCTION_VIDEO_KEY)
        session.add(setting)
    setting.file_id = file_id
    await session.commit()


async def save_instruction_text(session: AsyncSession, text: str) -> None:
    setting = await _get_setting(session, _INSTRUCTION_TEXT_KEY)
    if setting is None:
        setting = AppSetting(key=_INSTRUCTION_TEXT_KEY)
        session.add(setting)
    setting.value = text
    await session.commit()
