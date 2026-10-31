"""公開用の架空データを作る開発用スクリプト。"""

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "examples" / "fixtures"


def write(key: str, value: object) -> None:
    path = ROOT / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def connection(nodes: list[object]) -> dict[str, object]:
    return {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}


write("user", {"login": "demo"})
write(
    "repositories-1",
    {
        "data": {
            "repositoryOwner": {
                "repositories": connection(
                    [
                        {
                            "name": name,
                            "nameWithOwner": f"demo/{name}",
                            "isArchived": name == "archive",
                            "isFork": name == "fork",
                            "defaultBranchRef": {"name": "main"},
                        }
                        for name in ("app", "notes", "limited", "fork", "archive")
                    ]
                )
            }
        }
    },
)
for name in ("app", "notes", "limited", "fork"):
    full = f"demo/{name}"
    write(
        f"{full}/prs-1",
        {
            "data": {
                "repository": {
                    "pullRequests": connection(
                        [
                            {
                                "number": 12,
                                "title": "日次レポートを追加",
                                "isDraft": True,
                                "createdAt": "2026-10-01T00:00:00Z",
                                "url": "https://github.com/demo/app/pull/12",
                                "reviewDecision": "REVIEW_REQUIRED",
                                "commits": {
                                    "nodes": [
                                        {"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}
                                    ]
                                },
                            }
                        ]
                        if name == "app"
                        else []
                    )
                }
            }
        },
    )
    if name == "app":
        write(
            f"{full}/todo",
            {
                "encoding": "base64",
                "content": base64.b64encode(
                    (
                        "# HUMAN TODO\n- [ ] Webhook を設定 #p1 #discord\n"
                        "- [ ] 文言を確認 #p3 #docs\n- [x] 完了項目 #p2\n"
                    ).encode()
                ).decode(),
            },
        )
    else:
        write(f"{full}/todo", {"_error": "ファイルなし", "status": 404})
    run: list[object] = []
    if name in {"app", "limited"}:
        run = [
            {
                "id": 1,
                "status": "completed",
                "conclusion": "success" if name == "app" else "startup_failure",
                "check_suite_id": 123,
                "html_url": f"https://github.com/{full}/actions/runs/1",
                "updated_at": "2026-10-31T12:00:00Z",
            }
        ]
    write(f"{full}/runs", {"workflow_runs": run})
    write(f"{full}/workflows", {"total_count": 0})
write(
    "demo/limited/checks",
    {
        "check_runs": [
            {
                "output": {
                    "title": "実行を開始できません",
                    "summary": "The spending limit has been reached.",
                }
            }
        ]
    },
)
