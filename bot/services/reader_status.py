"""Kanal o'quvchi holati — "jim o'lim" ni ko'rinadigan qiladi.

Muammo tarixi: reader `asyncio.create_task(start_reader())` bilan ishga
tushirilgan, xato bo'lsa exception hech kimga ko'rinmagan. Bot normal
ishlaganda ham reader o'lik bo'lib qolgan va yuklar bazasiga tushmagan.

Bu modul jarayon ichida (in-memory) yagona `status` obyektini saqlaydi:
kim ulangan, oxirgi poll qachon, qancha xabar ko'rilgan va HAR BIR drop
sababi nechta. Admin `/reader` buyrug'i shuni ko'rsatadi.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# --- Holatlar -------------------------------------------------------------
STOPPED = "stopped"
CONNECTING = "connecting"
RUNNING = "running"
NEEDS_LOGIN = "needs_login"      # sessiya bekor — qayta login SHART
ERROR = "error"                  # vaqtinchalik xato, retry davom etadi

BROKEN_STATES = (NEEDS_LOGIN, ERROR, STOPPED)

# --- Drop sabablari (xabar nima uchun bazaga tushmadi) -------------------
NO_TEXT = "no_text"          # matn yo'q / juda qisqa
NO_TOPIC = "no_topic"        # forum mavzusi viloyat emas
NO_ROUTE = "no_route"        # yo'nalish aniqlanmadi
NO_PHONE = "no_phone"        # telefon yo'q
BLOCKLIST = "blocklist"      # qo'lda-logist ro'yxatida
LOGIST = "logist"            # algoritm logist deb topdi
DUPLICATE = "duplicate"      # repost (bir xil matn)
OK = "ok"                    # parse muvaffaqiyatli
SAVED = "saved"              # bazaga yozildi

_STATE_ICON = {
    STOPPED: "⚪️", CONNECTING: "🟡", RUNNING: "🟢",
    NEEDS_LOGIN: "🔴", ERROR: "🟠",
}


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%d.%m %H:%M:%S") if dt else "—"


@dataclass
class ReaderStatus:
    state: str = STOPPED
    detail: str = ""
    attempts: int = 0                       # ulanish urinishlari soni
    started_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    last_poll_at: Optional[datetime] = None
    last_saved_at: Optional[datetime] = None
    channels: dict = field(default_factory=dict)   # cid -> tavsif
    seen: int = 0                                  # ko'rilgan xabar (sabab yozilgan)
    reasons: Counter = field(default_factory=Counter)

    # --- holat o'zgarishlari ---
    def mark_connecting(self) -> None:
        self.state = CONNECTING
        self.attempts += 1
        self.started_at = self.started_at or datetime.utcnow()
        self.detail = ""

    def mark_running(self) -> None:
        self.state = RUNNING
        self.connected_at = datetime.utcnow()
        self.detail = ""

    def mark_error(self, detail: str) -> None:
        self.state = ERROR
        self.detail = detail[:300]

    def mark_needs_login(self, detail: str) -> None:
        """Sessiya bekor qilingan — retry foydasiz, qayta login kerak."""
        self.state = NEEDS_LOGIN
        self.detail = detail[:300]

    def mark_stopped(self) -> None:
        self.state = STOPPED

    def mark_poll(self) -> None:
        self.last_poll_at = datetime.utcnow()

    def note(self, reason: str) -> None:
        """Xabar taqdirini qayd etadi (drop sababi yoki ok/saved)."""
        self.reasons[reason] += 1
        self.seen += 1
        if reason == SAVED:
            self.last_saved_at = datetime.utcnow()

    def note_channel(self, cid, description: str) -> None:
        self.channels[cid] = description

    @property
    def is_broken(self) -> bool:
        return self.state in BROKEN_STATES

    def render(self) -> str:
        """Admin uchun qisqa hisobot (HTML emas — oddiy matn)."""
        lines = [
            f"{_STATE_ICON.get(self.state, '❔')} Kanal o'quvchi: {self.state}",
        ]
        if self.detail:
            lines.append(f"⚠️ {self.detail}")
        lines.append(f"Urinish: {self.attempts} | ulandi: {_fmt(self.connected_at)}")
        lines.append(f"Oxirgi poll: {_fmt(self.last_poll_at)}")
        lines.append(f"Oxirgi saqlangan yuk: {_fmt(self.last_saved_at)}")
        if self.channels:
            lines.append("Kanallar:")
            for cid, desc in self.channels.items():
                lines.append(f"  • {cid} — {desc}")
        lines.append(f"Ko'rilgan xabar: {self.seen}")
        if self.reasons:
            lines.append("Taqdiri:")
            for reason, count in self.reasons.most_common():
                lines.append(f"  • {reason}: {count}")
        if self.state == NEEDS_LOGIN:
            lines.append(
                "\n❗️ Sessiya bekor qilingan. Serverda qayta login kerak:\n"
                "   python3 scripts/telethon_login.py"
            )
        return "\n".join(lines)


status = ReaderStatus()   # jarayon ichida yagona nusxa
