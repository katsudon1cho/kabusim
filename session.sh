#!/usr/bin/env bash
# session.sh — Claude Code を headless で起動して1セッション実行する
#
#   ./session.sh jp-open
#   ./session.sh us-close
#   ./session.sh report
#
# cron から呼ばれる想定。ログは logs/ に残る。
# Windows では動かない（bash / TZ / cron 前提）。run_session.ps1 を使うこと。

set -euo pipefail
cd "$(dirname "$0")"

# 環境によって python3 が無かったり、python と別バージョンを指すことがある。
# broker.py と yfinance が入っているほうを PYTHON に入れる。
PYTHON="${PYTHON:-python3}"
export PYTHONUTF8=1

# 暴走時の上限。CI では特に効かせておきたい。
MAX_TURNS="${MAX_TURNS:-40}"

# ${1:?メッセージ} は使わないこと。メッセージ中に { } があると bash が最初の }
# で展開を打ち切り、余った } が値に連結される（"us-open}" になって全部落ちた）。
SESSION="${1-}"
if [ -z "$SESSION" ]; then
  echo "使い方: ./session.sh {jp-open|jp-close|us-open|us-close|report}" >&2
  exit 1
fi
STAMP=$(TZ=Asia/Tokyo date +%Y-%m-%d_%H%M)
mkdir -p logs reports

case "$SESSION" in
  jp-open)
    PROMPT="日本株ブックの寄り付き後セッションです（--session jp-open）。
CLAUDE.md の手順に従ってください。前場の値動きと朝方のニュースを確認し、
保有の前提が崩れていないかを最優先で見てください。" ;;
  jp-close)
    PROMPT="日本株ブックの引け前セッションです（--session jp-close）。
CLAUDE.md の手順に従ってください。本日の値動きの理由を確認し、
翌日以降に持ち越すべきでないポジションがないか判断してください。" ;;
  us-open)
    PROMPT="米国株ブックの寄り付き後セッションです（--session us-open）。
CLAUDE.md の手順に従ってください。寄り付きの反応と前日引け後の決算・
ガイダンス発表を確認してください。" ;;
  us-close)
    PROMPT="米国株ブックの引け前セッションです（--session us-close）。
CLAUDE.md の手順に従ってください。本日の総括と、引け後に予定されている
イベント（決算発表など）への備えを判断してください。" ;;
  report)
    "$PYTHON" broker.py snapshot
    PROMPT="日報作成セッションです（--session report）。
broker.py status と broker.py journal --days 1 を実行し、CLAUDE.md の
「日報」の項に従って reports/$(TZ=Asia/Tokyo date +%F).md を作成してください。
売買しなかった理由と、自分の判断の誤りについて必ず触れてください。" ;;
  *) echo "不明なセッション: $SESSION" >&2; exit 1 ;;
esac

echo "=== $SESSION @ $STAMP ===" | tee -a "logs/${SESSION}.log"

# 消費量を測るため JSON で受け取る。応答本文は record_usage.py が取り出して
# ログに流し直すので、logs/ の読みやすさは今までどおり。
RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT

set +e
claude -p "$PROMPT" \
  --allowedTools "Bash($PYTHON broker.py:*)" "WebSearch" "WebFetch" "Read" "Write(reports/*)" \
  --max-turns "$MAX_TURNS" \
  --output-format json \
  >"$RAW" 2>>"logs/${SESSION}.log"
STATUS=$?
set -e

# 計測に失敗してもセッションの成否は claude 側の終了コードで判断する
"$PYTHON" record_usage.py "$SESSION" "$RAW" 2>&1 | tee -a "logs/${SESSION}.log"

exit "$STATUS"
