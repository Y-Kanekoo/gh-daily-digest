"""CLI エントリーポイント。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .collect import collect
from .discord import NotifyError, send
from .render import markdown, notification
from .source import FetchError, FixtureSource, GhSource, Source, obj


def positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("1 以上を指定してください")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="GitHub の PR・TODO・CI を日次集計します")
    result.add_argument("--owner", help="対象ユーザー/組織（既定: gh api user）")
    result.add_argument("--exclude-forks", action="store_true", help="フォークを除外")
    result.add_argument("--local-root", type=Path, help="ローカルチェックアウトの親ディレクトリ")
    result.add_argument("--output-dir", type=Path, default=Path("digests"), help="出力先")
    result.add_argument("--no-discord", action="store_true", help="Discord 通知を無効化")
    result.add_argument("--fixtures", type=Path, help="オフラインの JSON フィクスチャ")
    result.add_argument("--workers", type=positive, default=4, help="並列リポジトリ数（既定: 4）")
    result.add_argument(
        "--timeout", type=positive, default=30, help="gh のタイムアウト秒（既定: 30）"
    )
    result.add_argument(
        "--stale-days", type=positive, default=14, help="古い PR の強調日数（既定: 14）"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source: Source = FixtureSource(args.fixtures) if args.fixtures else GhSource(args.timeout)
    try:
        owner = args.owner or str(obj(source.get("user", ["api", "user"]))["login"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", owner):
            raise ValueError("owner の形式が不正です")
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        data = collect(
            source,
            owner,
            now,
            args.exclude_forks,
            args.local_root.expanduser() if args.local_root else None,
            args.workers,
        )
        directory = args.output_dir.expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        stem = directory / str(data["date"])
        stem.with_suffix(".md").write_text(markdown(data, args.stale_days), encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"出力しました: {stem}.md / {stem}.json")
    except (FetchError, OSError, ValueError, KeyError) as exc:
        print(f"実行失敗: {exc}", file=sys.stderr)
        return 1
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    # オフラインデモは環境変数の有無に関係なく外部通信しない。
    if url and not args.no_discord and not args.fixtures:
        try:
            send(url, notification(data))
        except NotifyError as exc:
            print(f"{exc}。ファイル出力は保存済みです", file=sys.stderr)
            return 1
    return 2 if obj(data["summary"])["failed_repositories"] else 0
