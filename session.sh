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

# 暴走時の上限。ここで打ち切られると判断の途中で終わり、しかもそこまでの
# 約定は state.json に確定済みという中途半端な状態が残る。
# 実測は16銘柄・Sonnet で26ターン。45銘柄に増えたぶん余裕を持たせてある。
MAX_TURNS="${MAX_TURNS:-60}"

# 評価期間が1年あるので、途中でモデルが入れ替わると判断の記録を横並びで
# 比較できなくなる。エイリアス(opus)ではなく正式名で固定しておく。
MODEL="${MODEL:-claude-opus-5}"
EFFORT="${EFFORT:-high}"

# ${1:?メッセージ} は使わないこと。メッセージ中に { } があると bash が最初の }
# で展開を打ち切り、余った } が値に連結される（"us-open}" になって全部落ちた）。
SESSION="${1-}"
if [ -z "$SESSION" ]; then
  echo "使い方: ./session.sh {jp-open|jp-close|us-open|us-close|report}" >&2
  exit 1
fi
mkdir -p logs reports

# 時刻は Python で出す。環境によっては bash の date が Asia/Tokyo を解決できず
# UTC を返す（Git Bash がそうで、9時間ずれる）。
read -r TODAY HHMM NOW_MIN <<EOF
$("$PYTHON" -c "from datetime import datetime, timezone, timedelta
t = datetime.now(timezone(timedelta(hours=9)))
print(t.strftime('%Y-%m-%d'), t.strftime('%H:%M'), t.hour * 60 + t.minute)")
EOF
NOW="$TODAY $HHMM"
STAMP="${TODAY}_${HHMM/:/}"

# セッション名だけ渡しても、実際に何時に走ったかが分からない。
# GitHub のスケジュールは数時間ずれることがあり、jp-open が12:45に走った例もある。
# 予定時刻と実測のずれを渡して、モデル側で状況を補正できるようにする。
case "$SESSION" in
  jp-open)  SCHED="09:08"; BOOK="日本株ブック"; WHEN="寄り付き後"
            FOCUS="前場の値動きと朝方のニュースを確認し、保有の前提が崩れていないかを最優先で見てください。" ;;
  jp-close) SCHED="14:38"; BOOK="日本株ブック"; WHEN="引け前"
            FOCUS="本日の値動きの理由を確認し、翌日以降に持ち越すべきでないポジションがないか判断してください。" ;;
  us-open)  SCHED="22:52"; BOOK="米国株ブック"; WHEN="寄り付き後"
            FOCUS="寄り付きの反応と、前日引け後の決算・ガイダンス発表を確認してください。" ;;
  us-close) SCHED="04:08"; BOOK="米国株ブック"; WHEN="引け前"
            FOCUS="本日の総括と、引け後に予定されているイベント（決算発表など）への備えを判断してください。" ;;
  report)   SCHED="05:53"; BOOK="両ブック"; WHEN="日報"
            FOCUS="" ;;
  *) echo "不明なセッション: $SESSION" >&2; exit 1 ;;
esac

# 予定との差を分で出す。日付をまたぐセッションがあるので折り返す
sch_min=$(( 10#${SCHED%%:*} * 60 + 10#${SCHED##*:} ))
DELAY=$(( NOW_MIN - sch_min ))
[ "$DELAY" -lt -720 ] && DELAY=$(( DELAY + 1440 ))
[ "$DELAY" -gt 720 ] && DELAY=$(( DELAY - 1440 ))

# セッション名（寄り付き後／引け前）は予定であって事実ではない。
# 実際に市場が開いているかを渡して、名前ではなく現実に合わせて判断させる。
MARKET=$("$PYTHON" broker.py clock 2>/dev/null || echo "現在 ${NOW} JST")

if [ "$DELAY" -ge 20 ]; then
  TIMING="予定 ${SCHED} に対して実際は ${NOW}（約${DELAY}分の遅れ）。
${MARKET}
**セッション名が示す市場の状態は当てになりません。** 上の実際の状態に合わせて
判断してください。値動きは \`broker.py history\` で確かめること。"
else
  TIMING="予定 ${SCHED} / 実行 ${NOW}。
${MARKET}"
fi

if [ "$SESSION" = "report" ]; then
  "$PYTHON" broker.py snapshot
  PROMPT="日報セッション（--session report）。${TIMING}
両ブックが対象です。日報の書き込み先は reports/${TODAY}.md です。
売買しなかった理由と、自分の判断の誤りについて必ず触れてください。"
else
  PROMPT="${BOOK}の${WHEN}セッション（--session ${SESSION}）。${TIMING}
${FOCUS}"
fi

echo "=== $SESSION @ $STAMP ===" | tee -a "logs/${SESSION}.log"

# 消費量を測るため JSON で受け取る。応答本文は record_usage.py が取り出して
# ログに流し直すので、logs/ の読みやすさは今までどおり。
RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT

set +e
# Write(reports/*) だけだとパターンが一致せず、日報の書き込みで許可を求めて
# 止まっていた（無人なので誰も答えられない）。再帰形も並べておく。
claude -p "$PROMPT" \
  --allowedTools "Bash($PYTHON broker.py:*)" "WebSearch" "WebFetch" "Read" \
                 "Write(reports/**)" "Write(reports/*)" "Edit(reports/**)" \
  --model "$MODEL" \
  --effort "$EFFORT" \
  --max-turns "$MAX_TURNS" \
  --output-format json \
  >"$RAW" 2>>"logs/${SESSION}.log"
STATUS=$?
set -e

# 計測に失敗してもセッションの成否は claude 側の終了コードで判断する
"$PYTHON" record_usage.py "$SESSION" "$RAW" 2>&1 | tee -a "logs/${SESSION}.log"

exit "$STATUS"
