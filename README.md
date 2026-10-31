# gh-daily-digest

自分の GitHub リポジトリにある開いている PR、未完了の HUMAN TODO、既定ブランチの最新 CI を、日本語の Markdown / JSON に集約するローカル CLI です。アーカイブは常に除外し、フォークは任意で除外できます。

## 必要なもの

- Python 3.11 以上（Asia/Tokyo のタイムゾーン情報が利用できる環境）
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI](https://cli.github.com/) をインストールし、`gh auth login` 済みであること
- 対象リポジトリを参照できる GitHub アカウント

GitHub へのアクセスには `gh` の認証を使います。アプリがトークンを読み取ったり保存したりすることはありません。ランタイム依存は Python 標準ライブラリのみです。

## インストール

```sh
uv tool install git+https://github.com/Y-Kanekoo/gh-daily-digest
```

## 使い方

```sh
# gh api user のログインユーザーが所有するリポジトリ
# ./digests/YYYY-MM-DD.md と .json を作成（日付は Asia/Tokyo）
gh-daily-digest

# ユーザーまたは組織を指定、フォークを除外
gh-daily-digest --owner Y-Kanekoo --exclude-forks

# ローカルの HUMAN_TODO.md も統合
gh-daily-digest --local-root ~/Projects --output-dir ./reports --no-discord

# ソースからの実行
uv sync
uv run python -m gh_daily_digest --no-discord
```

`--workers 4` で並列リポジトリ数、`--timeout 30` で各 gh 呼び出しのタイムアウト秒数、`--stale-days 14` で古い PR を強調する日数を変更できます。いずれも 1 以上です。同日・同じ出力先のファイルは上書きします。

### HUMAN TODO の形式

各リポジトリの既定ブランチ直下に置きます。ファイルが存在しない場合は正常な「項目なし」です。

```markdown
# HUMAN TODO
- [ ] Webhook を設定 #p1 #discord
- [ ] 文言を確認 #p3 #docs
- [x] 完了した作業 #p2
```

`- [ ]` の行のみ集計し、コードフェンス内の例は無視します。優先度未指定は p3 です。同一リポジトリ内でタグ・連続空白を除いた本文が一致する項目は統合し、最も高い優先度とすべてのタグ・取得元を残します。大小文字や句読点は同一視しません。

`--local-root` は `<root>/<repo>/HUMAN_TODO.md` と `<root>/<owner>/<repo>/HUMAN_TODO.md` を探します。`.git` ディレクトリまたはファイルがあるチェックアウトが対象です。他リポジトリへの書き込みはしません。

### 出力例

以下は架空のデータによるデモ抜粋です。p1 のあるリポジトリから表示し、各節内の TODO も p1 → p3 の順に並べます。

```markdown
# GitHub 日次ダイジェスト 2026-11-01 / demo
リポジトリ 3 件・PR 1 件・未完了 TODO 2 件（p1: 1 件）・取得失敗 0 リポジトリ

## demo/app

CI: 成功

[最新実行](https://github.com/demo/app/actions/runs/1) / 更新: 2026-10-31T12:00:00Z

### HUMAN TODO

- [ ] **p1** Webhook を設定 #discord
- [ ] **p3** 文言を確認 #docs

### 開いている PR

- [#12 日次レポートを追加](https://github.com/demo/app/pull/12) / Draft / 作成: 2026-10-01T00:00:00Z / **長期滞留: 31日経過** / レビュー: レビュー待ち / チェック: 成功

## demo/limited

CI: 課金/無料枠制限の可能性
```

JSON は `date`、`owner`、`summary`、`repositories` を持ちます。各リポジトリに `prs`、`todos`、`ci`、`errors` があり、PR は作成日時・経過日数・Draft・URL・レビュー状態・チェック状態、TODO は本文・優先度・タグ・取得元、CI は取得可能な実行 URL・更新日時・推定フラグを含みます。

## オフラインデモと開発

```sh
./scripts/demo.sh --exclude-forks
./scripts/check.sh
```

`--fixtures examples/fixtures` は gh を実行せず、環境変数にかかわらず Discord にも接続しません。日付・PR 経過日数は実行日から計算します。フィクスチャの形式は [examples/fixtures/README.md](examples/fixtures/README.md) を参照してください。

`check.sh` は `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy --strict src`、`uv run pytest` を実行します。テストはネットワークと実 subprocess の起動を禁止し、85% 以上のカバレッジを要求します。開発用依存と uv キャッシュは作業ディレクトリ内に置きます。GitHub Actions のワークフローは設置していません。

## Discord 設定（任意）

Discord のサーバー設定で Webhook を作成し、起動するプロセスの環境変数 `DISCORD_WEBHOOK_URL` に設定してください。URL はシークレットなので、ソースやコマンド履歴、公開する plist に貼り付けないでください。このリポジトリに `.env` を作る必要はありません。

未設定ならファイル出力のみで正常終了します。`--no-discord` で明示的に無効化できます。要約を 2000 字以内（UTF-16 単位でも上限内）に分割し、意図しないメンションを抑止します。429 は `retry_after` に従い最大 3 回再試行します。待機時間が不正または 300 秒超の場合は送信失敗として終了します。送信失敗でも Markdown / JSON は保存済みです。途中のチャンクまで届く場合があります。

## 定期実行

[macOS launchd と cron の設定例](docs/scheduling.md) を参照してください。自動インストールは行いません。定期実行時には `gh` の認証状態と PATH、出力先を確認してください。

## 制限と終了コード

- 対象は指定ユーザー/組織が所有し、ログイン中の `gh` が閲覧できるリポジトリです。所属組織全体や共同作業者として参加しているだけのリポジトリは自動では含めません。
- リポジトリ一覧と PR は GraphQL で 100 件ずつページングします。通常は各リポジトリにつき PR・TODO・CI の 3 呼び出しです。CI 履歴なしの場合はワークフロー確認、失敗時は課金制限の補足情報取得が追加されます。
- CI は既定ブランチでの最新の実行 1 件です。全ワークフローの総合判定や最新コミットへの実行保証ではありません。更新日時とリンクも併せて確認してください。
- Actions なし、履歴なし、成功、失敗、実行中などを区別します。課金/無料枠制限は取得エラーや失敗チェックの本文・先頭 100 件の注釈からの推定です。チェック自体も先頭 100 件まで参照します。履歴のない状態だけでは、無料枠切れやワークフロー無効化を判定できません。
- 権限不足とファイル不存在がともに HTTP 404 になる場合は区別できません。リポジトリ一覧の取得失敗時は全体を終了し、リポジトリ個別の取得失敗は `errors` に記載して他の取得を続けます。
- ローカル探索は上記 2 種類のディレクトリ配置のみです。Git の origin URL は検証しないため、同名の別 owner のチェックアウトが混在する場合は `<root>/<owner>/<repo>` 配置を使い、`<root>/<repo>` 側に別 owner のチェックアウトを置かないでください。再帰探索は行いません。
- 作成からの経過日数は経過時間の 24 時間単位です。PR の個別チェック一覧は出さず、最新コミットのロールアップ状態を表示します。
- 非公開リポジトリの内容も出力・通知対象になります。出力ファイルの共有範囲と Discord の通知先を確認してください。
- 終了コード: `0` = 成功、`1` = 全体の取得・出力または Discord の失敗、`2` = リポジトリ単位の一部取得失敗（ファイルは出力）。

参照: [GitHub GraphQL リポジトリ API](https://docs.github.com/en/graphql/reference/repos)、[Actions 実行 API](https://docs.github.com/en/rest/actions/workflow-runs)、[Discord レート制限](https://docs.discord.com/developers/topics/rate-limits)。
