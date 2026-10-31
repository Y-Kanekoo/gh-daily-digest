"""差し替え可能な gh 呼び出しと JSON フィクスチャ。"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Protocol, TypeAlias, cast

Json: TypeAlias = "dict[str, Json] | list[Json] | str | int | float | bool | None"


def obj(value: Json) -> dict[str, Json]:
    if not isinstance(value, dict):
        raise ValueError("JSON オブジェクトが必要です")
    return value


def items(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise ValueError("JSON 配列が必要です")
    return value


def decode(value: str) -> Json:
    return cast(Json, json.loads(value))


class FetchError(Exception):
    """安全に表示できる取得エラー。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Source(Protocol):
    def get(self, key: str, args: list[str]) -> Json: ...


class GhSource:
    def __init__(self, timeout: float = 30) -> None:
        self.timeout = timeout

    def get(self, key: str, args: list[str]) -> Json:
        try:
            result = subprocess.run(
                ["gh", *args], capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise FetchError("gh のタイムアウト") from exc
        except OSError as exc:
            raise FetchError("gh を起動できません。インストールを確認してください") from exc
        if result.returncode:
            # stderr には URL 等が含まれうるため、そのまま出力しない。
            match = re.search(r"HTTP (\d{3})", result.stderr)
            status = int(match[1]) if match else None
            billing = re.search(
                r"billing|spending limit|minutes quota|payment|included minutes",
                result.stderr,
                re.I,
            )
            message = "課金/無料枠制限の可能性" if billing else "gh の実行失敗"
            raise FetchError(message, status)
        try:
            return decode(result.stdout)
        except ValueError as exc:
            raise FetchError("gh の応答が不正な JSON です") from exc


class FixtureSource:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def get(self, key: str, args: list[str]) -> Json:
        # キーのパス成分は固定プレフィックスと GitHub の識別子のみ。
        path = self.directory / f"{key}.json"
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise FetchError("フィクスチャのパスが不正です")
        try:
            value = decode(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FetchError(f"フィクスチャを読み込めません: {key}") from exc
        if isinstance(value, dict) and "_error" in value:
            status = value.get("status")
            raise FetchError(str(value["_error"]), int(status) if isinstance(status, int) else None)
        return value
