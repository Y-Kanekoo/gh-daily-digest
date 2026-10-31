# 定期実行の設定例

設定は手動で行います。以下の絶対パスは自分の環境に置き換えてください。Webhook 未設定のファイル出力だけでも利用できます。

## macOS launchd

[com.example.gh-daily-digest.plist](com.example.gh-daily-digest.plist) は毎朝 9 時に実行する例です。launchd の時刻は Mac のローカル時刻に従います。日本時間 9 時に実行したい場合は Mac のタイムゾーンも確認してください。ダイジェストの日付自体は常に Asia/Tokyo です。

1. `command -v gh-daily-digest` と `command -v gh` でパスを確認します。
2. plist の `__HOME__`、`ProgramArguments`、`WorkingDirectory`、`PATH`、ログパスを置き換えます。作業先・ログ先ディレクトリを事前に作成します。
3. 自分で確認した plist を `~/Library/LaunchAgents/` に配置し、`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.gh-daily-digest.plist` を実行します。
4. 必要なら `launchctl kickstart gui/$(id -u)/com.example.gh-daily-digest` で動作確認します。

無効化は `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.example.gh-daily-digest.plist` です。plist はシークレットの保管先にしないでください。例は通知なしです。通知する場合は秘密情報を公開せず起動環境へ渡す方法を自分の環境に合わせて用意し、`--no-discord` を外してください。

## cron

`crontab -e` で、パスを調整した以下を登録できます。cron の実行時刻もホストのタイムゾーンに従います。作業先・ログ先ディレクトリは事前に作成してください。

```cron
PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin
0 9 * * * cd $HOME/gh-daily-digest && $HOME/.local/bin/gh-daily-digest --output-dir $HOME/gh-daily-digest/digests --no-discord >> $HOME/gh-daily-digest/digest.log 2>&1
```

定期実行は対話シェルの設定を読み込みません。同じユーザーでの `gh auth status`、必要なリポジトリへの参照権限、PATH、出力先の書き込み権限を確認してください。スリープ中の動作はスケジューラーと端末設定に依存します。同時実行を避けるようにスケジュールを設定してください。
