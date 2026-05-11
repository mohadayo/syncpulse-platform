# コントリビューションガイド

SyncPulse Platform への貢献を歓迎します。本ドキュメントでは、ブランチ運用・コミットメッセージ・PR の作成方法・各サービス実装時の規約をまとめます。

## ブランチ命名規則

すべての変更はフィーチャーブランチで行い、以下のプレフィックスを使用してください。

| プレフィックス | 用途 |
| --- | --- |
| `feat/` | 新機能追加 |
| `fix/` | バグ修正 |
| `docs/` | ドキュメント変更のみ |
| `chore/` | ビルド・補助スクリプト・依存更新など |
| `refactor/` | 振る舞いを変えないリファクタ |
| `test/` | テストの追加・修正 |
| `perf/` | パフォーマンス改善 |

例: `feat/metrics-collector-bootstrap`、`fix/transformer-timeout`

`main` への直接 push は禁止です。常に PR 経由でマージします。

## コミットメッセージ規則

```
<type>: <短い要約（日本語可）>
```

- `<type>` はブランチプレフィックスと同じ語彙（`feat` / `fix` / `docs` / `chore` / `refactor` / `test` / `perf`）
- 1 コミットは 1 関心事に絞る
- 本文を付ける場合は空行で区切り、変更の理由（why）を中心に書く
- 影響範囲が広いコミットは分割を検討

例:

```
feat: metrics-collector に /api/metrics エンドポイントを追加

外部メトリクス源からの POST を受信し、内部キューに enqueue する。
バリデーション失敗時は 400 を返す。
```

## プルリクエスト規則

### タイトル

`<type>: <変更内容を端的に表す日本語タイトル>` の形式。

例: `feat: dashboard-api にメトリクス集計エンドポイントを追加`

### 本文テンプレート

```markdown
## 概要

- 変更点（箇条書き）
- 背景・目的（必要に応じて）

## 関連 Issue

Closes #N

## 動作確認

- [ ] 手動テスト手順 1
- [ ] 手動テスト手順 2
- [ ] ユニットテストが通ることを確認
```

### マージ要件

- CI（lint / test）が green
- レビュー観点: 仕様の妥当性、テスト充足、ログ・エラー処理、セキュリティ
- 1 PR は 1 関心事を保ち、レビュー可能な粒度に保つ

## 各サービス実装時の規約

各サービスは `services/<service-name>/` 配下に独立したディレクトリとして配置します。最小構成は以下:

```
services/<service-name>/
├── README.md            # サービス概要・API・起動方法
├── Dockerfile           # Production 用イメージ
├── (言語別の依存定義)    # requirements.txt / go.mod / package.json 等
├── (実装本体)            # main.py / main.go / src/index.ts 等
└── (テスト)              # test_*.py / *_test.go / *.test.ts 等
```

### 共通ガイドライン

- **HTTP / JSON 通信**: サービス間連携は HTTP + JSON を基本とする
- **環境変数**: 設定は環境変数経由で渡し、ハードコードを避ける。すべて `.env.example` に列挙
- **ログ**: 構造化ログ（key=value または JSON）で出力。`LOG_LEVEL` で出力レベルを制御
- **ヘルスチェック**: 各サービスは `/health` を実装し、200 OK + JSON で稼働状態を返す
- **タイムアウト**: 外部呼び出しには必ずタイムアウトを設定（デフォルト 5〜10 秒）
- **入力バリデーション**: API リクエストは型・長さ・範囲を検証し、不正値は 400 で拒否
- **テスト**: ユニットテストを必ず添付し、CI で実行できる状態にする

## ローカル開発

```bash
# 1. リポジトリをクローン
git clone https://github.com/mohadayo/syncpulse-platform.git
cd syncpulse-platform

# 2. 環境変数のサンプルをコピー
cp .env.example .env

# 3. フィーチャーブランチを作成
git checkout -b feat/<your-feature>

# 4. 変更をコミット
git commit -m "feat: <要約>"

# 5. リモートにプッシュして PR を作成
git push -u origin feat/<your-feature>
```

## 質問・相談

- 仕様の方向性に迷う場合は Issue で議論してから実装に着手してください
- セキュリティに関わる発見は公開 Issue ではなく [`SECURITY.md`](./SECURITY.md) に記載のフローで報告してください
- コミュニティでのやり取りはすべて [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) の行動規範に従ってください。違反の報告窓口も同ドキュメントに記載しています
