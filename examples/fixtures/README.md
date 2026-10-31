# オフラインフィクスチャ

すべて架空の `demo` ユーザーのデータです。`./scripts/demo.sh` または `uv run gh-daily-digest --fixtures examples/fixtures` で実行できます。実行時に外部通信は行いません。

- `user.json`: `gh api user` の応答。
- `repositories-N.json`: GraphQL のリポジトリ一覧（1 始まりのページ番号）。
- `<owner>/<repo>/prs-N.json`: GraphQL の開いている PR 一覧。
- `<owner>/<repo>/todo.json`: Contents API の base64 応答。
- `<owner>/<repo>/runs.json`: 既定ブランチの最新 Actions 実行。
- `<owner>/<repo>/workflows.json`: 実行がない場合のワークフロー件数。
- `<owner>/<repo>/checks.json`: 失敗実行の補足チェック。
- `<owner>/<repo>/annotations-<id>.json`: 注釈がある失敗チェックの補足（必要時のみ）。

API 失敗は `{"_error": "日本語のエラー", "status": 404}` で表現します。404 の TODO はファイルなしとして扱います。アーカイブ除外、任意のフォーク除外、Draft、古い PR、p1、Actions なし、課金制限の推定を試せます。フィクスチャは `uv run python scripts/create_fixtures.py` で再生成できます。
