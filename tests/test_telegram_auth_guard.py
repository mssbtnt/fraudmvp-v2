from __future__ import annotations

import asyncio

import pytest

import services.scraper.telegram_scraper as telegram_scraper


class _UnauthorizedClient:
    def __init__(self):
        self.connected = False
        self.disconnected = False

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return False

    async def disconnect(self):
        self.disconnected = True


def test_connect_authorized_client_fails_fast_without_prompt(monkeypatch):
    fake_client = _UnauthorizedClient()
    monkeypatch.setattr(telegram_scraper, "_get_client", lambda: fake_client)

    with pytest.raises(RuntimeError, match="Telegram session is not authorized"):
        asyncio.run(telegram_scraper._connect_authorized_client())

    assert fake_client.connected is True
    assert fake_client.disconnected is True
