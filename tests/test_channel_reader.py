"""Kanal o'quvchi — xabar tayyorlash va reader hayot tsikli testlari.

DB kerak emas: `prepare_message` sof funksiya (faqat in-process blocklist
keshiga qaraydi). Shu sabab har bir drop sababi alohida test qilinadi —
"bitta ham yuk tushmayapti" holati qaytsa, qaysi bosqich buzilgani darhol
ko'rinadi.
"""
from __future__ import annotations

import asyncio

import pytest
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    SessionRevokedError,
)

from bot.services import channel_reader as cr
from bot.services import logist_service as ls
from bot.services import reader_status as rs
from bot.services.session_manager import get_script_session_path, get_session_path

FORUM_MAP = {5: "Andijon"}


# ---------------------------------------------------------------------------
# prepare_message — drop sabablari
# ---------------------------------------------------------------------------

def test_short_text_dropped():
    parsed, reason = cr.prepare_message("Salom", None, None)
    assert parsed is None
    assert reason == rs.NO_TEXT


def test_forum_unknown_topic_dropped():
    """Viloyat mavzusi bo'lmagan topic (General/Premium) — tashlanadi."""
    text = "Andijon ➡️ Toshkent\n20 tonna\n901234567"
    parsed, reason = cr.prepare_message(text, FORUM_MAP, 999)
    assert parsed is None
    assert reason == rs.NO_TOPIC


def test_forum_topic_gives_origin():
    text = "Andijon ➡️ Toshkent\n20 tonna paxta\n📞 901234567"
    parsed, reason = cr.prepare_message(text, FORUM_MAP, 5)
    assert reason == rs.OK
    assert parsed.origin == "Andijon"
    assert parsed.destination == "Toshkent"
    assert parsed.contact == "+998901234567"
    assert parsed.confidence == 1.0


def test_plain_group_route_from_text_and_viloyat():
    """Oddiy guruh: yo'nalish matndan, origin viloyatga aylanadi."""
    text = "Chortoqdan Toshkentga yuk bor, 20 tonna, 90 123 45 67"
    parsed, reason = cr.prepare_message(text, None, None)
    assert reason == rs.OK
    assert parsed.origin == "Namangan"   # Chortoq -> Namangan
    assert parsed.destination == "Toshkent"


def test_no_phone_dropped():
    parsed, reason = cr.prepare_message("Andijon ➡️ Toshkent\n20 tonna", FORUM_MAP, 5)
    assert parsed is None
    assert reason == rs.NO_PHONE


def test_no_route_dropped():
    parsed, reason = cr.prepare_message("Yuk kerak, tez, 901234567", None, None)
    assert parsed is None
    assert reason == rs.NO_ROUTE


def test_blocklisted_phone_dropped():
    ls._blocklist_cache.add("+998901234567")
    try:
        text = "Andijon ➡️ Toshkent\n901234567"
        parsed, reason = cr.prepare_message(text, FORUM_MAP, 5)
        assert parsed is None
        assert reason == rs.BLOCKLIST
    finally:
        ls._blocklist_cache.discard("+998901234567")


# ---------------------------------------------------------------------------
# Fatal auth xatolari — retry foydasiz, qayta login kerak
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc_cls", [
    AuthKeyDuplicatedError, AuthKeyUnregisteredError, SessionRevokedError,
])
def test_auth_errors_are_fatal(exc_cls):
    assert cr.is_fatal_auth_error(exc_cls(request=None)) is True


def test_network_error_is_not_fatal():
    assert cr.is_fatal_auth_error(ConnectionError("timeout")) is False


def test_unauthorized_session_is_fatal():
    """Avtorizatsiyadan o'tmagan sessiya — interaktiv kod so'ramaslik uchun fatal.

    `client.start()` bunday holatda terminalda kod so'raydi va systemd ostida
    EOFError bilan har 30 soniyada takrorlanardi.
    """
    assert cr.is_fatal_auth_error(cr.ReaderNeedsLogin("sessiya yaroqsiz")) is True


def test_backoff_grows_and_is_capped():
    delays = [cr.next_backoff(i) for i in range(1, 12)]
    assert delays[0] < delays[1] < delays[2]          # o'sadi
    assert max(delays) <= cr.BACKOFF_MAX              # cheklangan
    assert all(d > 0 for d in delays)


# ---------------------------------------------------------------------------
# Supervisor — xatoni jim yutmaydi, sessiya o'lsa xabar beradi
# ---------------------------------------------------------------------------

class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def test_supervisor_stops_and_alerts_on_dead_session(monkeypatch):
    """Sessiya bekor -> retry qilmaydi, NEEDS_LOGIN va adminga xabar."""
    async def boom():
        raise AuthKeyDuplicatedError(request=None)

    monkeypatch.setattr(cr, "start_reader", boom)
    monkeypatch.setattr(cr, "status", rs.ReaderStatus())
    monkeypatch.setattr(
        type(cr.settings), "admin_ids_list", property(lambda self: [111, 222])
    )
    bot = _FakeBot()

    asyncio.run(cr.run_reader_forever(bot))    # qaytadi — cheksiz aylanmaydi

    assert cr.status.state == rs.NEEDS_LOGIN
    assert cr.status.attempts == 1              # foydasiz retry qilinmadi
    assert len(bot.sent) == 2                   # ikki adminga xabar ketdi
    assert "telethon_login" in bot.sent[0][1]


def test_supervisor_retries_temporary_error(monkeypatch):
    """Vaqtinchalik xato -> backoff bilan qayta ulanadi."""
    calls = {"n": 0}
    slept: list = []

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("dc unreachable")
        return  # 3-urinishda ulandi va normal tugadi

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(cr, "start_reader", flaky)
    monkeypatch.setattr(cr, "status", rs.ReaderStatus())
    monkeypatch.setattr(cr.asyncio, "sleep", fake_sleep)

    asyncio.run(cr.run_reader_forever(None))

    assert calls["n"] == 3
    assert slept == [cr.next_backoff(1), cr.next_backoff(2)]
    assert cr.status.state == rs.STOPPED


# ---------------------------------------------------------------------------
# Polling sikli — uzilgan client "tirik o'lik" holatda qolmasligi kerak
#
# Prod hodisasi (2026-08-04 20:35 → 2026-08-05 05:40, ~9 soat): Telethon
# client uzilib qoldi, `get_messages` har kanal uchun
# `ConnectionError: Cannot send requests while disconnected` berdi. Polling
# sikli bu xatoni KANALGA XOS deb hisoblab jim yutdi va aylanaverdi —
# supervisor hech qachon xato ko'rmadi, qayta ulanmadi. Protsess "active",
# bazaga esa bitta ham yangi yuk tushmadi (open yuklar 0 ga tushdi).
# ---------------------------------------------------------------------------

class _FakePollClient:
    """`is_connected` va `get_messages` ni taqlid qiladi."""

    def __init__(self, connected=True, exc=None):
        self._connected = connected
        self._exc = exc
        self.calls: list = []

    def is_connected(self):
        return self._connected

    async def get_messages(self, cid, **kw):
        self.calls.append(cid)
        if self._exc:
            raise self._exc
        return []


def test_connection_error_is_recognized():
    """Ulanish xatosi — clientga tegishli, kanalga emas."""
    assert cr.is_connection_error(
        ConnectionError("Cannot send requests while disconnected")
    ) is True
    assert cr.is_connection_error(asyncio.TimeoutError()) is True
    assert cr.is_connection_error(ValueError("entity topilmadi")) is False


def test_poll_once_raises_when_client_disconnected():
    """Client uzilgan bo'lsa — so'rov urinmasdan supervisorga ko'tariladi."""
    client = _FakePollClient(connected=False)
    with pytest.raises(ConnectionError):
        asyncio.run(cr._poll_once(client, [-100111], {-100111: None}, {}))
    assert client.calls == []          # uzilgan clientga so'rov yuborilmadi


def test_poll_once_reraises_connection_error():
    """AYNAN prod bug'i: uzilish xatosi jim yutilmaydi — supervisor ko'radi."""
    client = _FakePollClient(
        exc=ConnectionError("Cannot send requests while disconnected")
    )
    with pytest.raises(ConnectionError):
        asyncio.run(
            cr._poll_once(client, [-100111, -100222], {-100111: None, -100222: None}, {})
        )
    # Birinchi kanaldayoq to'xtaydi — qolganini urinish ma'nosiz.
    assert client.calls == [-100111]


def test_poll_once_skips_channel_specific_error(monkeypatch):
    """Kanalga xos xato — log qilinadi, qolgan kanallar o'qilaveradi."""
    class _PerChannel(_FakePollClient):
        async def get_messages(self, cid, **kw):
            self.calls.append(cid)
            if cid == -100999:
                raise ValueError("Could not find the input entity")
            return []

    client = _PerChannel()
    asyncio.run(
        cr._poll_once(
            client, [-100999, -100222], {-100999: None, -100222: None}, {}
        )
    )
    assert client.calls == [-100999, -100222]   # ikkinchi kanal o'qildi


def test_poll_once_reraises_fatal_auth_error():
    """Sessiya bekor — polling siklida ham fatal bo'lib qoladi."""
    client = _FakePollClient(exc=AuthKeyDuplicatedError(request=None))
    with pytest.raises(AuthKeyDuplicatedError):
        asyncio.run(cr._poll_once(client, [-100111], {-100111: None}, {}))


# ---------------------------------------------------------------------------
# Topic map — bo'sh xarita 100% drop qilmasligi kerak
# ---------------------------------------------------------------------------

class _FakeClient:
    """GetForumTopicsRequest ni taqlid qiladi."""

    def __init__(self, topics=None, exc=None):
        self._topics = topics or []
        self._exc = exc

    async def __call__(self, request):
        if self._exc:
            raise self._exc
        return type("Res", (), {"topics": self._topics})()


def _topic(tid, title):
    return type("T", (), {"id": tid, "title": title})()


def test_topic_map_reads_viloyat_topics():
    client = _FakeClient([_topic(5, "ANDIJON"), _topic(7, "Premium e'lonlar")])
    rmap = asyncio.run(cr._build_topic_map(client, -100123))
    assert rmap == {5: "Andijon"}          # Premium filtrlandi


def test_topic_map_without_viloyat_topics_falls_back_to_text():
    """Forum, lekin viloyat mavzusi yo'q -> None (yo'nalish matndan o'qiladi).

    Ilgari bo'sh dict qaytardi — natijada HAR BIR xabar 'no_topic' bo'lib
    tashlanardi (bazaga bitta ham yuk tushmasdi).
    """
    client = _FakeClient([_topic(1, "General"), _topic(2, "Elon berish")])
    assert asyncio.run(cr._build_topic_map(client, -100123)) is None


def test_one_bad_channel_does_not_stop_the_others(monkeypatch):
    """Bitta kanal yechilmasa — qolgan kanallardan yuk kelishi davom etadi."""
    async def fake_map(client, cid):
        if cid == -100999:
            raise ValueError("Could not find the input entity")
        return {5: "Andijon"}

    monkeypatch.setattr(cr, "_build_topic_map", fake_map)
    monkeypatch.setattr(cr, "status", rs.ReaderStatus())

    maps = asyncio.run(cr._build_topic_maps(None, [-100111, -100999, -100222]))

    assert list(maps.keys()) == [-100111, -100222]
    assert "XATO" in cr.status.channels[-100999]


def test_all_channels_failing_raises(monkeypatch):
    """Hamma kanal xato bo'lsa — supervisor qayta urishi uchun xato ko'tariladi."""
    async def fake_map(client, cid):
        raise ValueError("entity yo'q")

    monkeypatch.setattr(cr, "_build_topic_map", fake_map)
    monkeypatch.setattr(cr, "status", rs.ReaderStatus())

    with pytest.raises(RuntimeError):
        asyncio.run(cr._build_topic_maps(None, [-100111, -100222]))


def test_topic_map_error_raises_for_retry():
    """Kutilmagan xato -> ko'tariladi (supervisor qayta uradi), jim yutilmaydi."""
    client = _FakeClient(exc=ConnectionError("dc timeout"))
    with pytest.raises(ConnectionError):
        asyncio.run(cr._build_topic_map(client, -100123))


# ---------------------------------------------------------------------------
# Sessiya izolyatsiyasi — lokal skript serverning sessiyasini o'ldirmasin
# ---------------------------------------------------------------------------

def test_session_name_from_env(monkeypatch):
    monkeypatch.setenv("TELETHON_SESSION_NAME", "diag_session")
    assert get_session_path().endswith("diag_session")


def test_session_name_explicit_overrides_env(monkeypatch):
    monkeypatch.delenv("TELETHON_SESSION_NAME", raising=False)
    assert get_session_path("diag_session").endswith("diag_session")
    assert get_session_path().endswith("telethon_session")


def test_helper_scripts_use_separate_session(monkeypatch):
    """Yordamchi skript bot sessiyasini ISHLATMASLIGI kerak (auth key o'lmasin)."""
    monkeypatch.delenv("TELETHON_SESSION_NAME", raising=False)
    assert get_script_session_path() != get_session_path()
    assert get_script_session_path().endswith("helper_session")


# ---------------------------------------------------------------------------
# Reader status — jim o'lim ko'rinadigan bo'lishi kerak
# ---------------------------------------------------------------------------

def test_status_tracks_reasons_and_render():
    st = rs.ReaderStatus()
    st.mark_connecting()
    assert st.state == rs.CONNECTING
    st.mark_running()
    st.note(rs.OK)
    st.note(rs.SAVED)
    st.note(rs.LOGIST)
    st.note(rs.NO_TOPIC)
    st.note(rs.NO_TOPIC)
    assert st.reasons[rs.NO_TOPIC] == 2
    assert st.seen == 5
    text = st.render()
    assert rs.RUNNING in text
    assert "no_topic" in text


def test_status_needs_login_is_visible():
    st = rs.ReaderStatus()
    st.mark_needs_login("AuthKeyDuplicatedError: session ikki IP da")
    assert st.state == rs.NEEDS_LOGIN
    assert st.is_broken is True
    assert "AuthKeyDuplicatedError" in st.render()
