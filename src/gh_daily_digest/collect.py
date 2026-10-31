"""リポジトリごとの取得と状態の正規化。"""

from __future__ import annotations

import base64
import binascii
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .source import FetchError, Json, Source, items, obj

REPOSITORIES = """query($owner:String!,$cursor:String) {
  repositoryOwner(login:$owner) { repositories(first:100,after:$cursor, ownerAffiliations:OWNER) {
    nodes { name nameWithOwner isArchived isFork defaultBranchRef { name } }
    pageInfo { hasNextPage endCursor }
  } }
}"""
PULL_REQUESTS = """query($owner:String!,$name:String!,$cursor:String) {
  repository(owner:$owner,name:$name) { pullRequests(first:100,after:$cursor,states:OPEN,
    orderBy:{field:CREATED_AT,direction:ASC}) {
    nodes { number title isDraft createdAt url reviewDecision
      commits(last:1) { nodes { commit { statusCheckRollup { state } } } }
    }
    pageInfo { hasNextPage endCursor }
  } }
}"""


def graphql(source: Source, key: str, query: str, fields: dict[str, str]) -> dict[str, Json]:
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in fields.items():
        args.extend(["-f", f"{name}={value}"])
    data = obj(source.get(key, args))
    if data.get("errors"):
        raise FetchError("GraphQL の取得失敗（権限・対象・API 制限を確認してください）")
    return obj(data.get("data"))


def repositories(source: Source, owner: str, exclude_forks: bool) -> list[dict[str, Json]]:
    result: list[dict[str, Json]] = []
    fields = {"owner": owner}
    page = 1
    while True:
        data = graphql(source, f"repositories-{page}", REPOSITORIES, fields)
        connection = obj(obj(data.get("repositoryOwner")).get("repositories"))
        for value in items(connection.get("nodes")):
            repo = obj(value)
            if not repo.get("isArchived") and not (exclude_forks and repo.get("isFork")):
                result.append(repo)
        info = obj(connection.get("pageInfo"))
        if not info.get("hasNextPage"):
            return result
        fields["cursor"] = str(info["endCursor"])
        page += 1


def pull_requests(source: Source, full_name: str, now: datetime) -> list[Json]:
    owner, name = full_name.split("/", 1)
    fields = {"owner": owner, "name": name}
    result: list[Json] = []
    page = 1
    while True:
        data = graphql(source, f"{full_name}/prs-{page}", PULL_REQUESTS, fields)
        connection = obj(obj(data.get("repository")).get("pullRequests"))
        for value in items(connection.get("nodes")):
            pr = obj(value)
            created = datetime.fromisoformat(str(pr["createdAt"]).replace("Z", "+00:00"))
            commits = items(obj(pr.get("commits")).get("nodes"))
            rollup = (
                obj(obj(commits[-1]).get("commit")).get("statusCheckRollup") if commits else None
            )
            result.append(
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "draft": pr["isDraft"],
                    "created_at": pr["createdAt"],
                    "age_days": max(0, (now - created).days),
                    "url": pr["url"],
                    "review": pr.get("reviewDecision") or "未レビュー",
                    "checks": obj(rollup).get("state") if rollup else "チェックなし",
                }
            )
        info = obj(connection.get("pageInfo"))
        if not info.get("hasNextPage"):
            return result
        fields["cursor"] = str(info["endCursor"])
        page += 1


def parse_todos(text: str, origin: str) -> list[dict[str, Json]]:
    result: list[dict[str, Json]] = []
    in_fence = False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        match = re.match(r"^\s*- \[ \]\s+(.+?)\s*$", line)
        if not match or in_fence:
            continue
        raw = match[1]
        priority = re.search(r"(?<!\S)#p([123])\b", raw)
        tags = re.findall(r"(?<!\S)#([^\s#]+)", raw)
        content = re.sub(r"(?<!\S)#[^\s#]+", "", raw).strip()
        content = " ".join(content.split())
        result.append(
            {
                "text": content,
                "priority": int(priority[1]) if priority else 3,
                "tags": sorted(t for t in tags if t not in {"p1", "p2", "p3"}),
                "sources": [origin],
            }
        )
    return result


def merge_todos(values: list[dict[str, Json]]) -> list[Json]:
    merged: dict[str, dict[str, Json]] = {}
    for todo in values:
        key = str(todo["text"])
        if key in merged:
            previous = merged[key]
            previous["priority"] = min(int(str(previous["priority"])), int(str(todo["priority"])))
            for field in ("sources", "tags"):
                previous[field] = [
                    str(v)
                    for v in sorted(set(map(str, items(previous[field]) + items(todo[field]))))
                ]
        else:
            merged[key] = todo.copy()
    return [
        v for v in sorted(merged.values(), key=lambda t: (int(str(t["priority"])), str(t["text"])))
    ]


def remote_todos(source: Source, full_name: str, branch: str) -> list[dict[str, Json]]:
    try:
        data = obj(
            source.get(
                f"{full_name}/todo",
                ["api", f"repos/{full_name}/contents/HUMAN_TODO.md?ref={quote(branch, safe='')}"],
            )
        )
    except FetchError as exc:
        if exc.status == 404:
            return []
        raise
    if data.get("encoding") != "base64":
        raise ValueError("HUMAN_TODO.md のエンコードが不正です")
    return parse_todos(base64.b64decode(str(data["content"])).decode("utf-8"), "remote")


def local_todos(root: Path, full_name: str) -> list[dict[str, Json]]:
    owner, name = full_name.split("/", 1)
    result: list[dict[str, Json]] = []
    # 直下のチェックアウトと owner/repo 形式の両方に対応。
    for checkout in (root / name, root / owner / name):
        if (checkout / ".git").exists() and (checkout / "HUMAN_TODO.md").is_file():
            result.extend(
                parse_todos(
                    (checkout / "HUMAN_TODO.md").read_text(encoding="utf-8"), f"local:{checkout}"
                )
            )
    return result


def ci_status(source: Source, full_name: str, branch: str) -> dict[str, Json]:
    prefix = f"repos/{full_name}/actions"
    try:
        data = obj(
            source.get(
                f"{full_name}/runs",
                ["api", f"{prefix}/runs?branch={quote(branch, safe='')}&per_page=1"],
            )
        )
    except FetchError as exc:
        if "課金/無料枠" in str(exc):
            return {"state": "課金/無料枠制限の可能性", "estimated": True}
        raise
    runs = items(data.get("workflow_runs"))
    if not runs:
        workflows = obj(
            source.get(f"{full_name}/workflows", ["api", f"{prefix}/workflows?per_page=1"])
        )
        return {
            "state": "Actions なし"
            if workflows.get("total_count") == 0
            else "実行履歴なし（課金/無料枠制限の有無は不明）",
            "estimated": False,
        }
    run = obj(runs[0])
    conclusion = str(run.get("conclusion") or "")
    state = (
        "実行中"
        if run.get("status") != "completed"
        else {
            "success": "成功",
            "failure": "失敗",
            "startup_failure": "起動失敗",
            "cancelled": "キャンセル",
            "skipped": "スキップ",
            "timed_out": "タイムアウト",
            "action_required": "操作待ち",
            "neutral": "中立",
            "stale": "期限切れ",
        }.get(conclusion, "不明")
    )
    result: dict[str, Json] = {
        "state": state,
        "conclusion": conclusion,
        "url": run.get("html_url"),
        "updated_at": run.get("updated_at"),
        "estimated": False,
    }
    if conclusion in {"failure", "startup_failure"} and run.get("check_suite_id"):
        try:
            checks = obj(
                source.get(
                    f"{full_name}/checks",
                    [
                        "api",
                        f"repos/{full_name}/check-suites/{run['check_suite_id']}/check-runs?per_page=100",
                    ],
                )
            )
            for value in items(checks.get("check_runs")):
                check = obj(value)
                output = obj(check.get("output") or {})
                evidence = " ".join(str(output.get(k) or "") for k in ("title", "summary", "text"))
                if output.get("annotations_count") and check.get("id"):
                    annotations = items(
                        source.get(
                            f"{full_name}/annotations-{check['id']}",
                            [
                                "api",
                                f"repos/{full_name}/check-runs/{check['id']}/annotations?per_page=100",
                            ],
                        )
                    )
                    evidence += " " + " ".join(
                        str(obj(annotation).get("message") or "") for annotation in annotations
                    )
                if re.search(
                    r"billing|spending limit|payment|included minutes|minutes quota", evidence, re.I
                ):
                    result.update(state="課金/無料枠制限の可能性", estimated=True)
                    break
        except (FetchError, ValueError) as exc:
            result["warning"] = f"課金制限の補足取得失敗: {exc}"
    return result


def collect_repo(
    source: Source, repo: dict[str, Json], now: datetime, local_root: Path | None
) -> dict[str, Json]:
    full_name = str(repo["nameWithOwner"])
    result: dict[str, Json] = {"name": full_name, "prs": [], "todos": [], "ci": {}, "errors": []}
    errors: list[Json] = []
    todos: list[dict[str, Json]] = []
    branch_ref = repo.get("defaultBranchRef")
    branch = str(obj(branch_ref)["name"]) if branch_ref else ""
    try:
        result["prs"] = pull_requests(source, full_name, now)
    except (FetchError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"PR: 取得失敗（{exc}）")
    if branch:
        try:
            todos.extend(remote_todos(source, full_name, branch))
        except (FetchError, ValueError, KeyError, UnicodeError, binascii.Error) as exc:
            errors.append(f"HUMAN_TODO: 取得失敗（{exc}）")
        try:
            result["ci"] = ci_status(source, full_name, branch)
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            result["ci"] = {"state": "取得失敗"}
            errors.append(f"CI: 取得失敗（{exc}）")
    else:
        result["ci"] = {"state": "既定ブランチなし"}
    if local_root:
        try:
            todos.extend(local_todos(local_root, full_name))
        except (OSError, UnicodeError) as exc:
            errors.append(f"ローカル TODO: 取得失敗（{exc}）")
    result["todos"] = merge_todos(todos)
    result["errors"] = errors
    return result


def collect(
    source: Source,
    owner: str,
    now: datetime,
    exclude_forks: bool = False,
    local_root: Path | None = None,
    workers: int = 4,
) -> dict[str, Json]:
    repos = repositories(source, owner, exclude_forks)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda r: collect_repo(source, r, now, local_root), repos))
    results.sort(
        key=lambda r: (
            min((int(str(obj(t)["priority"])) for t in items(r["todos"])), default=4),
            str(r["name"]),
        )
    )
    return {
        "date": now.date().isoformat(),
        "owner": owner,
        "repositories": [r for r in results],
        "summary": {
            "repositories": len(results),
            "prs": sum(len(items(r["prs"])) for r in results),
            "todos": sum(len(items(r["todos"])) for r in results),
            "p1": sum(obj(t)["priority"] == 1 for r in results for t in items(r["todos"])),
            "failed_repositories": sum(bool(r["errors"]) for r in results),
        },
    }
