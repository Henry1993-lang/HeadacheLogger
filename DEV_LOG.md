# プロジェクト開発記録: HeadacheLogger (HPL v2.0)

## 1. プロジェクト概要
気圧変化と頭痛の記録・分析を行うStreamlitアプリケーション。
CSVによるローカル管理から始まり、現在はSupabaseを利用したクラウドデータベース連携版へと進化しました。

## 2. 実装履歴

### フェーズ1: CSVデータベース版 (HeadacheLogger_originals)
*   **特徴**: 
    *   データ保存先: ローカルCSV (`headache_log.csv`)
    *   外部API: Open-Meteo (気圧データ取得)
    *   主な機能:
        *   気圧データの自動取得 (現在、1h/3h/12h/24h前との差分、12h最低値)
        *   記録入力 (痛みレベル、場所、要因、メモ)
        *   履歴の表示・削除
*   **ファイル**: `HeadacheLogger_originals/app.py`

### フェーズ2: Supabase連携版 (Current Version)
*   **特徴**:
    *   データ保存先: Supabase (`headache_logs` テーブル)
    *   UI改善: 「記録入力」と「分析ダッシュボード」のタブ切り替え式に変更
    *   設定: `.streamlit/secrets.toml` で認証情報を管理
*   **ファイル**: `app.py` (ルートディレクトリ)
*   **主な機能追加**:
    *   **分析ダッシュボード**:
        *   KPIカード (総記録数、平均痛み、最大気圧低下)
        *   散布図 (気圧低下 vs 痛み) + 警戒ライン (-1.0 hPa)
        *   ヒートマップ (曜日 × 時間帯の発生パターン)

### フェーズ2.1: 過去日付の記録 (バックフィル)
*   日付・時刻を過去に遡って入力できるように修正 (以前は再描画のたびに時刻が現在時刻へリセットされていた)
*   「今日 / 昨日 / 一昨日」のショートカットボタンを追加、未来日時は記録不可
*   約3か月より古い日付は Open-Meteo Archive API (1940年〜) から気圧を取得。失敗時はもう一方の API にフォールバック

## 3. バージョン管理 (Git/GitHub)
*   **リポジトリ**: `Henry1993-lang/HeadacheLogger`
*   **管理方針**:
    *   機密情報 (`secrets.toml`, `.env` 等) は `.gitignore` で除外
    *   個人データ (`headache_log.csv`) も除外
    *   `setup_supabase.sql` などのセットアップ用スクリプトもリポジトリから除外

## 4. 環境構築・実行方法
### 必須要件
*   Python 3.13+
*   `requirements.txt` のパッケージ (streamlit, pandas, plotly, supabase, etc.)
*   `.streamlit/secrets.toml` (Supabase接続情報)

### コマンド
```bash
# 仮想環境の有効化
source venv/bin/activate

# アプリケーションの実行 (Supabase版)
cd HeadacheLogger
streamlit run app.py

# アプリケーションの実行 (CSV版)
streamlit run HeadacheLogger_originals/app.py
```

## 5. 今後のTodo (メモ)
*   [ ] 分析機能の強化 (要因別の分析など)
*   [ ] モバイル向けUIの最適化
*   [ ] LINE Bot連携の検討 (通知機能など)
