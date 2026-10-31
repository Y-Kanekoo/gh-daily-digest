"""任意の Discord 通知。Webhook URL はログへ出さない。"""

import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .source import decode, obj


class NotifyError(Exception):
    """安全に表示できる通知失敗。"""


def chunks(text: str, limit: int = 2000) -> list[str]:
    # Discord の文字数上限を UTF-16 単位でも超えないように分割する。
    result: list[str] = []
    current = ""
    size = 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            result.append(current)
            current, size = "", 0
        current += char
        size += units
    if current:
        result.append(current)
    return result


def send(url: str, text: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"discord.com", "discordapp.com"}
        or not parsed.path.startswith("/api/webhooks/")
        or parsed.username
        or parsed.password
    ):
        raise NotifyError("Discord Webhook URL が不正です")
    for part in chunks(text):
        payload = json.dumps({"content": part, "allowed_mentions": {"parse": []}}).encode("utf-8")
        for attempt in range(4):
            request = Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "gh-daily-digest/0.1"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=30):
                    pass
                break
            except HTTPError as exc:
                if exc.code != 429 or attempt == 3:
                    raise NotifyError(f"Discord 送信失敗（HTTP {exc.code}）") from None
                try:
                    delay = float(str(obj(decode(exc.read().decode("utf-8")))["retry_after"]))
                    if not math.isfinite(delay) or delay < 0 or delay > 300:
                        raise ValueError
                except (ValueError, KeyError, UnicodeError):
                    raise NotifyError("Discord の再試行待機時間が不正です") from None
                time.sleep(delay)
            except (OSError, URLError, ValueError):
                raise NotifyError("Discord との通信に失敗しました") from None
