"""外部プロセスと HTTP の境界はすべてモックする。"""

import io
import json
import subprocess
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from gh_daily_digest import discord
from gh_daily_digest.source import FetchError, GhSource


def test_gh_success(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"login":"demo"}', ""))
    monkeypatch.setattr(subprocess, "run", run)
    assert GhSource(12).get("user", ["api", "user"]) == {"login": "demo"}
    assert run.call_args.args[0] == ["gh", "api", "user"]
    assert run.call_args.kwargs["timeout"] == 12


@pytest.mark.parametrize(
    "error,message",
    [
        (subprocess.TimeoutExpired("gh", 1), "タイムアウト"),
        (FileNotFoundError(), "起動できません"),
    ],
)
def test_gh_process_error(monkeypatch, error, message):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=error))
    with pytest.raises(FetchError, match=message):
        GhSource().get("user", [])


@pytest.mark.parametrize(
    "stderr,status,message",
    [
        ("HTTP 403 confidential", 403, "gh の実行失敗"),
        ("billing spending limit confidential", None, "課金/無料枠"),
        ("confidential", None, "gh の実行失敗"),
    ],
)
def test_gh_redaction(monkeypatch, stderr, status, message):
    monkeypatch.setattr(
        subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 1, "", stderr))
    )
    with pytest.raises(FetchError, match=message) as captured:
        GhSource().get("user", [])
    assert captured.value.status == status
    assert "confidential" not in str(captured.value)


def test_gh_bad_json(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, "broken", ""))
    )
    with pytest.raises(FetchError, match="JSON"):
        GhSource().get("user", [])


def http_error(code, body=b"{}"):
    return HTTPError("秘密のURL", code, "通信失敗", {}, io.BytesIO(body))


URL = "https://discord.com/api/webhooks/fixture/redacted"


def test_discord_split_retry(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock(side_effect=[http_error(429, b'{"retry_after":0.25}'), response, response])
    sleeper = Mock()
    monkeypatch.setattr(discord, "urlopen", opener)
    monkeypatch.setattr(discord.time, "sleep", sleeper)
    text = "あ" * 2000 + "😀"
    discord.send(URL, text)
    assert opener.call_count == 3
    sleeper.assert_called_once_with(0.25)
    parts = []
    for call in opener.call_args_list[1:]:
        body = json.loads(call.args[0].data)
        assert body["allowed_mentions"] == {"parse": []}
        assert len(body["content"].encode("utf-16-le")) // 2 <= 2000
        parts.append(body["content"])
    assert "".join(parts) == text
    assert discord.chunks("") == []
    assert len(discord.chunks("😀" * 1001)) == 2


@pytest.mark.parametrize(
    "error",
    [
        http_error(500),
        URLError("秘密のURL"),
        OSError("秘密のURL"),
        http_error(429, b'{"retry_after": -1}'),
        http_error(429, b'{"retry_after": 301}'),
        http_error(429, b'{"retry_after": "nan"}'),
        http_error(429, b"bad"),
        http_error(429, b"{}"),
    ],
)
def test_discord_failures(monkeypatch, error):
    monkeypatch.setattr(discord, "urlopen", Mock(side_effect=error))
    with pytest.raises(discord.NotifyError) as captured:
        discord.send(URL, "通知")
    assert "秘密" not in str(captured.value)


def test_discord_retry_limit(monkeypatch):
    opener = Mock(side_effect=[http_error(429, b'{"retry_after":0}') for _ in range(4)])
    monkeypatch.setattr(discord, "urlopen", opener)
    monkeypatch.setattr(discord.time, "sleep", Mock())
    with pytest.raises(discord.NotifyError, match="429"):
        discord.send(URL, "通知")
    assert opener.call_count == 4


@pytest.mark.parametrize(
    "url",
    ["http://discord.com/api/webhooks/x/y", "https://example.com", "https://discord.com/elsewhere"],
)
def test_invalid_webhook(url):
    with pytest.raises(discord.NotifyError, match="URL が不正"):
        discord.send(url, "通知")
