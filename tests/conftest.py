"""全テストでネットワークと実 gh の起動を禁止する。"""

import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("テストからの外部通信・外部プロセスは禁止です")

    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(subprocess, "run", reject)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
