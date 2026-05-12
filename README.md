# SyncPulse Platform

リアルタイムデータパイプラインオーケストレータ。複数言語で実装されたマイクロサービスを組み合わせ、メトリクス収集 → 変換 → ダッシュボード配信までを担う。

## 構成

| サービス | 言語 | 役割 |
| --- | --- | --- |
| `metrics-collector` | Python | 各種ソースからメトリクスを収集 |
| `transformer` | Go | 受信データの変換・集約 |
| `dashboard-api` | TypeScript | ダッシュボード向け REST API の提供 |

## アーキテクチャ概要

```
+-------------------+      +---------------+      +-----------------+
| metrics-collector | ---> |  transformer  | ---> |  dashboard-api  |
|     (Python)      |      |     (Go)      |      |  (TypeScript)   |
+-------------------+      +---------------+      +-----------------+
        |                          |                       |
   外部メトリクス源              データ変換・集約         ブラウザ / クライアント
```

各サービスは HTTP / JSON で疎結合に通信する想定。サービス間の連携は `docker-compose` で起動した内部ネットワーク経由で行う。

## 前提条件

- Docker 24+
- Docker Compose v2
- ローカル開発時のみ:
  - Python 3.12+（`metrics-collector`）
  - Go 1.22+（`transformer`）
  - Node.js 22+（`dashboard-api`）

## ローカルセットアップ

> 注: 一部のサービスは初期実装段階です。実装済み / 未実装の状況は本 README 下部の「ロードマップ」を参照してください。コントリビュート方法は [`CONTRIBUTING.md`](./CONTRIBUTING.md) を参照。
>
> 現時点で実装済みのサービス:
>
> - [`services/metrics-collector/`](./services/metrics-collector/) （Python / Flask）

```bash
# 1. リポジトリをクローン
git clone https://github.com/mohadayo/syncpulse-platform.git
cd syncpulse-platform

# 2. 環境変数のサンプルをコピーし、必要に応じてポート等を編集
cp .env.example .env

# 3. すべてのサービスを起動
docker compose up --build
```

起動後、以下のポートで各サービスにアクセスできる予定:

| サービス | ポート | エンドポイント |
| --- | --- | --- |
| `metrics-collector` | 8000 | `http://localhost:8000` |
| `transformer` | 8080 | `http://localhost:8080` |
| `dashboard-api` | 3000 | `http://localhost:3000` |

## API（予定）

### metrics-collector (Python)

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `POST` | `/api/metrics` | メトリクスの取り込み |

### transformer (Go)

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `POST` | `/api/transform` | 受信データの変換 |

### dashboard-api (TypeScript)

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `GET` | `/api/dashboard/metrics` | 集計済みメトリクスの取得 |

具体的なリクエスト / レスポンススキーマは実装時に各サービスの README で定義する。

## ディレクトリ構成（予定）

```
syncpulse-platform/
├── README.md
├── docker-compose.yml          # 全サービスの起動定義（追加予定）
├── .env.example                # 環境変数のサンプル
├── services/
│   ├── metrics-collector/      # Python サービス（追加予定）
│   ├── transformer/            # Go サービス（追加予定）
│   └── dashboard-api/          # TypeScript サービス（追加予定）
└── .github/
    └── workflows/              # CI 設定（追加予定）
```

## 開発ガイドライン

- 各サービスは独立してビルド・テスト可能な構造を維持する
- 共通の通信規約は JSON over HTTP（将来的に gRPC / メッセージング基盤への移行を検討）
- ログは構造化ログ（key=value または JSON）で出力
- 設定は環境変数経由で渡し、ハードコードしない

ブランチ運用・コミットメッセージ・PR ルールは [`CONTRIBUTING.md`](./CONTRIBUTING.md) を参照してください。

## ロードマップ

- [x] `metrics-collector` (Python) の初期実装（[`services/metrics-collector/`](./services/metrics-collector/) — `/health`, `POST /api/metrics`, `GET /api/metrics`）
- [ ] `transformer` (Go) の初期実装
- [ ] `dashboard-api` (TypeScript) の初期実装
- [ ] `docker-compose.yml` でのオーケストレーション
- [ ] CI（lint / test）整備
- [ ] エンドツーエンドの結合テスト

## コミュニティ

- 行動規範: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- コントリビュート方法・ブランチ運用: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- 脆弱性報告: [`SECURITY.md`](./SECURITY.md)

## セキュリティ

脆弱性の報告手順・スコープ・応答 SLA は [`SECURITY.md`](./SECURITY.md) を参照してください。公開 Issue ではなく GitHub の Private vulnerability reporting を利用してください。

## ライセンス

[MIT License](./LICENSE) の下で公開しています。
