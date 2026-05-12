# metrics-collector (Python)

SyncPulse Platform のメトリクス受信サービス（初期実装）。外部メトリクス源からの POST を受信し、インメモリストアに保持する。

## エンドポイント

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック (`status`, `service`, `uptime_seconds`) |
| `POST` | `/api/metrics` | メトリクスを受信して保存（`source` / `name` / `value` 必須、`timestamp` 省略可） |
| `GET` | `/api/metrics` | 保存済みメトリクスの一覧取得 |

### POST /api/metrics リクエストスキーマ

```json
{
  "source": "host-1",
  "name": "cpu.load",
  "value": 0.42,
  "timestamp": 1700000000.0
}
```

- `source` (string, 必須): 送信元識別子。空白のみ不可、`MAX_SOURCE_LENGTH` 以下
- `name` (string, 必須): メトリクス名。空白のみ不可、`MAX_NAME_LENGTH` 以下
- `value` (number, 必須): 数値。有限値、絶対値 `MAX_VALUE` 以下
- `timestamp` (number, 任意): Unix タイムスタンプ。省略時はサーバ時刻

不正な入力は `400` を返す。

## 環境変数

| 変数 | デフォルト | 説明 |
| --- | --- | --- |
| `METRICS_COLLECTOR_PORT` | `8000` | リッスンポート |
| `LOG_LEVEL` | `INFO` | ログ出力レベル |
| `MAX_METRICS` | `10000` | インメモリストアの上限件数（超過時は古いものから破棄） |
| `MAX_SOURCE_LENGTH` | `200` | `source` 文字列の最大長 |
| `MAX_NAME_LENGTH` | `200` | `name` 文字列の最大長 |
| `MAX_VALUE` | `1e12` | `value` の絶対値上限 |

## ローカル開発

```bash
pip install -r requirements-dev.txt
python main.py            # 開発サーバ (Flask)
pytest -v                 # テスト
flake8 --max-line-length=120 main.py
```

## Docker

```bash
docker build -t syncpulse-metrics-collector .
docker run --rm -p 8000:8000 syncpulse-metrics-collector
```

## 既知の制約

- ストアはインメモリのみ。再起動でデータは消失する
- 永続化・後段サービスへの転送は将来の PR で追加予定
