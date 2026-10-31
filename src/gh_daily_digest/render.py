"""日本語の Markdown と通知用要約。"""

from .source import Json, items, obj


def escape(value: Json) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    for char in "\\`*_<>{}[]|":
        text = text.replace(char, "\\" + char)
    return text


def summary(data: dict[str, Json]) -> str:
    counts = obj(data["summary"])
    return (
        f"GitHub 日次ダイジェスト {data['date']} / {data['owner']}\n"
        f"リポジトリ {counts['repositories']} 件・PR {counts['prs']} 件・"
        f"未完了 TODO {counts['todos']} 件（p1: {counts['p1']} 件）・"
        f"取得失敗 {counts['failed_repositories']} リポジトリ"
    )


def markdown(data: dict[str, Json], stale_days: int = 14) -> str:
    lines = [f"# {summary(data)}", ""]
    for value in items(data["repositories"]):
        repo = obj(value)
        lines.extend([f"## {repo['name']}", "", f"CI: {escape(obj(repo['ci']).get('state'))}", ""])
        ci = obj(repo["ci"])
        if ci.get("url"):
            lines.extend([f"[最新実行]({ci['url']}) / 更新: {ci.get('updated_at')}", ""])
        if ci.get("warning"):
            lines.extend([escape(ci["warning"]), ""])
        for error in items(repo["errors"]):
            lines.append(f"- {escape(error)}")
        lines.extend(["", "### HUMAN TODO", ""])
        for todo_value in items(repo["todos"]):
            todo = obj(todo_value)
            tags = " ".join(f"#{escape(t)}" for t in items(todo["tags"]))
            lines.append(f"- [ ] **p{todo['priority']}** {escape(todo['text'])} {tags}".rstrip())
        if not repo["todos"]:
            lines.append("未完了項目なし" if not repo["errors"] else "取得できた未完了項目なし")
        lines.extend(["", "### 開いている PR", ""])
        for pr_value in sorted(items(repo["prs"]), key=lambda p: -int(str(obj(p)["age_days"]))):
            pr = obj(pr_value)
            age = f"{pr['age_days']}日経過"
            if int(str(pr["age_days"])) >= stale_days:
                age = f"**長期滞留: {age}**"
            review = {
                "APPROVED": "承認済み",
                "CHANGES_REQUESTED": "変更要求",
                "REVIEW_REQUIRED": "レビュー待ち",
            }.get(str(pr["review"]), str(pr["review"]))
            checks = {
                "SUCCESS": "成功",
                "FAILURE": "失敗",
                "ERROR": "エラー",
                "PENDING": "実行中",
                "EXPECTED": "待機中",
            }.get(str(pr["checks"]), str(pr["checks"]))
            lines.append(
                f"- [#{pr['number']} {escape(pr['title'])}]({pr['url']})"
                f" / {'Draft' if pr['draft'] else 'Ready'} / 作成: {pr['created_at']}"
                f" / {age} / レビュー: {review} / チェック: {checks}"
            )
        if not repo["prs"]:
            lines.append("取得できた PR なし" if repo["errors"] else "開いている PR なし")
        lines.append("")
    return "\n".join(lines) + "\n"


def notification(data: dict[str, Json]) -> str:
    lines = [summary(data)]
    for value in items(data["repositories"]):
        repo = obj(value)
        lines.append(
            f"\n{repo['name']}: PR {len(items(repo['prs']))} 件 / "
            f"TODO {len(items(repo['todos']))} 件 / CI {obj(repo['ci']).get('state')}"
        )
        for todo_value in items(repo["todos"]):
            todo = obj(todo_value)
            if todo["priority"] == 1:
                lines.append(f"p1: {todo['text']}")
        lines.extend(str(e) for e in items(repo["errors"]))
    return "\n".join(lines)
