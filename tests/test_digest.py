"""フィクスチャによる集計・CLI・表示の検証。"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gh_daily_digest import cli
from gh_daily_digest.collect import (
    ci_status,
    collect,
    collect_repo,
    graphql,
    local_todos,
    merge_todos,
    parse_todos,
    pull_requests,
    remote_todos,
    repositories,
)
from gh_daily_digest.render import markdown, notification
from gh_daily_digest.source import FetchError, FixtureSource, decode, items, obj

FIXTURES = Path(__file__).resolve().parents[1] / "examples/fixtures"
NOW = datetime(2026, 11, 1, 9, tzinfo=ZoneInfo("Asia/Tokyo"))


def read(key):
    return json.loads((FIXTURES / f"{key}.json").read_text())


class MemorySource:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def get(self, key, args):
        self.calls.append((key, args))
        value = self.values[key]
        if isinstance(value, Exception):
            raise value
        return value


def test_demo():
    data = collect(FixtureSource(FIXTURES), "demo", NOW, exclude_forks=True)
    assert data["summary"] == {
        "repositories": 3,
        "prs": 1,
        "todos": 2,
        "p1": 1,
        "failed_repositories": 0,
    }
    repos = items(data["repositories"])
    assert obj(repos[0])["name"] == "demo/app"
    pr = obj(items(obj(repos[0])["prs"])[0])
    assert pr["age_days"] == 31 and pr["draft"] is True
    assert obj(obj(repos[1])["ci"])["state"] == "課金/無料枠制限の可能性"
    output = markdown(data)
    assert "**長期滞留: 31日経過**" in output
    assert "レビュー待ち" in output and "チェック: 成功" in output
    assert output.index("**p1**") < output.index("**p3**")
    assert "Actions なし" in output
    assert "p1: Webhook を設定" in notification(data)


def test_pagination():
    page = read("repositories-1")
    page["data"]["repositoryOwner"]["repositories"]["pageInfo"] = {
        "hasNextPage": True,
        "endCursor": "next",
    }
    last = read("repositories-1")
    last["data"]["repositoryOwner"]["repositories"]["nodes"] = []
    source = MemorySource({"repositories-1": page, "repositories-2": last})
    assert len(repositories(source, "demo", False)) == 4
    assert "cursor=next" in source.calls[1][1]
    prs = read("demo/app/prs-1")
    prs["data"]["repository"]["pullRequests"]["pageInfo"] = {
        "hasNextPage": True,
        "endCursor": "more",
    }
    second = read("demo/fork/prs-1")
    source = MemorySource({"demo/app/prs-1": prs, "demo/app/prs-2": second})
    assert len(pull_requests(source, "demo/app", NOW)) == 1
    assert "cursor=more" in source.calls[1][1]


def test_pr_without_checks():
    data = read("demo/app/prs-1")
    pr = data["data"]["repository"]["pullRequests"]["nodes"][0]
    pr["commits"]["nodes"] = []
    pr["reviewDecision"] = None
    result = pull_requests(MemorySource({"demo/app/prs-1": data}), "demo/app", NOW)
    assert result[0]["checks"] == "チェックなし"
    assert result[0]["review"] == "未レビュー"


def test_todos_and_local(tmp_path):
    text = """# HUMAN TODO
- [ ] 重複 #p2 #test
- [x] 完了 #p1
```markdown
- [ ] コード例 #p1
```
  - [ ] その他
"""
    remote = parse_todos(text, "remote")
    assert len(remote) == 2
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /架空のパス")
    (repo / "HUMAN_TODO.md").write_text("- [ ] 重複 #p1 #local\n- [ ] 新規 #p3")
    merged = merge_todos(remote + local_todos(tmp_path, "demo/app"))
    assert len(merged) == 3
    assert merged[0]["priority"] == 1
    assert merged[0]["tags"] == ["local", "test"]
    assert len(merged[0]["sources"]) == 2
    assert local_todos(tmp_path, "demo/unknown") == []


def test_isolation_and_local_survives(tmp_path):
    repo = read("repositories-1")["data"]["repositoryOwner"]["repositories"]["nodes"][0]
    source = MemorySource(
        {
            "demo/app/prs-1": FetchError("権限なし"),
            "demo/app/todo": FetchError("応答失敗"),
            "demo/app/runs": FetchError("応答失敗"),
        }
    )
    checkout = tmp_path / "app"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    (checkout / "HUMAN_TODO.md").write_text("- [ ] ローカル項目 #p1")
    result = collect_repo(source, repo, NOW, tmp_path)
    assert len(result["errors"]) == 3 and len(result["todos"]) == 1
    assert result["ci"]["state"] == "取得失敗"
    data = collect(FixtureSource(FIXTURES), "demo", NOW)
    data["repositories"] = [result]
    assert "取得失敗" in markdown(data)
    assert "取得できた PR なし" in markdown(data)
    assert "取得失敗" in notification(data)
    source.values["demo/app/prs-1"] = read("demo/fork/prs-1")
    repo["defaultBranchRef"] = None
    result = collect_repo(source, repo, NOW, None)
    assert result["ci"]["state"] == "既定ブランチなし"


def test_local_read_error(tmp_path, monkeypatch):
    from gh_daily_digest import collect as module

    def fail(*args):
        raise OSError("読取不可")

    monkeypatch.setattr(module, "local_todos", fail)
    repo = read("repositories-1")["data"]["repositoryOwner"]["repositories"]["nodes"][1]
    result = collect_repo(FixtureSource(FIXTURES), repo, NOW, tmp_path)
    assert "ローカル TODO" in result["errors"][0]


@pytest.mark.parametrize(
    "state,conclusion,expected",
    [
        ("completed", "success", "成功"),
        ("in_progress", None, "実行中"),
        ("queued", None, "実行中"),
        ("completed", "failure", "失敗"),
        ("completed", "cancelled", "キャンセル"),
        ("completed", "skipped", "スキップ"),
        ("completed", "timed_out", "タイムアウト"),
        ("completed", "new_value", "不明"),
    ],
)
def test_ci_states(state, conclusion, expected):
    source = MemorySource(
        {"a/b/runs": {"workflow_runs": [{"status": state, "conclusion": conclusion}]}}
    )
    assert ci_status(source, "a/b", "release/a")["state"] == expected
    assert "branch=release%2Fa" in source.calls[0][1][1]


def test_ci_empty_and_billing():
    source = MemorySource({"a/b/runs": {"workflow_runs": []}, "a/b/workflows": {"total_count": 1}})
    assert "有無は不明" in ci_status(source, "a/b", "main")["state"]
    source.values["a/b/runs"] = FetchError("課金/無料枠制限の可能性", 403)
    assert ci_status(source, "a/b", "main")["estimated"] is True
    source.values["a/b/runs"] = {
        "workflow_runs": [{"status": "completed", "conclusion": "failure", "check_suite_id": 1}]
    }
    source.values["a/b/checks"] = FetchError("制限")
    assert "補足取得失敗" in ci_status(source, "a/b", "main")["warning"]
    source.values["a/b/checks"] = {"check_runs": [{"output": {"summary": "通常の失敗"}}]}
    assert ci_status(source, "a/b", "main")["state"] == "失敗"


def test_input_errors(tmp_path):
    with pytest.raises(ValueError):
        obj([])
    with pytest.raises(ValueError):
        items({})
    with pytest.raises(ValueError):
        decode("invalid")
    with pytest.raises(FetchError):
        FixtureSource(tmp_path).get("missing", [])
    with pytest.raises(FetchError):
        FixtureSource(tmp_path).get("../../outside", [])
    with pytest.raises(FetchError):
        graphql(MemorySource({"bad": {"errors": [{"message": "不明"}]}}), "bad", "", {})
    with pytest.raises(ValueError):
        remote_todos(MemorySource({"a/b/todo": {"encoding": "utf8"}}), "a/b", "main")
    with pytest.raises(FetchError):
        remote_todos(MemorySource({"a/b/todo": FetchError("権限不足", 403)}), "a/b", "main")


def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "外部通信禁止")
    assert cli.main(["--fixtures", str(FIXTURES), "--output-dir", str(tmp_path)]) == 0
    output = list(tmp_path.glob("*.json"))
    assert len(output) == 1 and len(list(tmp_path.glob("*.md"))) == 1
    data = json.loads(output[0].read_text())
    assert data["summary"]["repositories"] == 4
    assert data["date"] == datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    assert "出力しました" in capsys.readouterr().out
    assert cli.main(["--fixtures", str(tmp_path), "--output-dir", str(tmp_path)]) == 1
    assert cli.main(["--owner", "../bad", "--fixtures", str(FIXTURES)]) == 1
    with pytest.raises(SystemExit):
        cli.main(["--workers", "0"])
    with pytest.raises(SystemExit):
        cli.main(["--workers", "abc"])


def test_cli_notification_failure(tmp_path, monkeypatch):
    from gh_daily_digest.discord import NotifyError

    monkeypatch.setattr(cli, "GhSource", lambda timeout: FixtureSource(FIXTURES))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "架空")

    def fail(*args):
        raise NotifyError("送信失敗")

    monkeypatch.setattr(cli, "send", fail)
    assert cli.main(["--output-dir", str(tmp_path)]) == 1
    assert list(tmp_path.glob("*.json")) and list(tmp_path.glob("*.md"))
    assert cli.main(["--output-dir", str(tmp_path), "--no-discord"]) == 0


def test_cli_partial(tmp_path, monkeypatch):
    source = MemorySource({"user": {"login": "demo"}, "repositories-1": read("repositories-1")})
    for name in ("app", "notes", "limited", "fork"):
        source.values[f"demo/{name}/prs-1"] = FetchError("取得不可")
        source.values[f"demo/{name}/todo"] = FetchError("取得不可")
        source.values[f"demo/{name}/runs"] = FetchError("取得不可")
    monkeypatch.setattr(cli, "GhSource", lambda timeout: source)
    assert cli.main(["--output-dir", str(tmp_path), "--owner", "demo"]) == 2
    data = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert data["summary"]["failed_repositories"] == 4


def test_ci_billing_annotation():
    source = MemorySource(
        {
            "a/b/runs": {
                "workflow_runs": [
                    {"status": "completed", "conclusion": "failure", "check_suite_id": 1}
                ]
            },
            "a/b/checks": {"check_runs": [{"id": 99, "output": {"annotations_count": 1}}]},
            "a/b/annotations-99": [{"message": "Payments have failed; check billing settings"}],
        }
    )
    result = ci_status(source, "a/b", "main")
    assert result["estimated"] is True
    assert "無料枠" in result["state"]
