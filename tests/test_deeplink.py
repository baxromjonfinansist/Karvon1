"""Deep-link (yuk raqamini ko'rsatish uchun /start payload) — sof funksiyalar."""
from __future__ import annotations

import pytest

from bot.services import deeplink as dl


def test_build_load_deeplink_requires_username():
    dl.set_bot_username(None)  # reset
    with pytest.raises(RuntimeError):
        dl.build_load_deeplink(42)


def test_build_load_deeplink_with_username():
    dl.set_bot_username("Yukchibrat_bot")
    assert dl.build_load_deeplink(42) == "https://t.me/Yukchibrat_bot?start=load_42"


def test_parse_load_start_payload_valid():
    assert dl.parse_load_start_payload("load_42") == 42


def test_parse_load_start_payload_none():
    assert dl.parse_load_start_payload(None) is None


def test_parse_load_start_payload_empty():
    assert dl.parse_load_start_payload("") is None


def test_parse_load_start_payload_wrong_prefix():
    assert dl.parse_load_start_payload("ref_42") is None


def test_parse_load_start_payload_non_numeric():
    assert dl.parse_load_start_payload("load_abc") is None
