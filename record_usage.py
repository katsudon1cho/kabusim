#!/usr/bin/env python3
"""
record_usage.py — セッション1回分の結果を記録する。

session.sh が `claude -p --output-format json` の出力を渡してくる。
このスクリプトは3つのことをする:

  1. 応答本文を標準出力に流す（ログを人が読める状態に保つため）
  2. その本文を journal.jsonl に SESSION 行として追記する
  3. 消費量を usage_log.csv に1行追記する

    python record_usage.py <セッション名> <claudeのJSON出力ファイル>

2 が肝心。journal.jsonl は注文があったときしか書かれないので、
売買しなかったセッションの判断が丸ごと消えていた。
「調べたうえで見送った」も判断であり、この実験で一番価値がある記録なので、
エージェント側の書き忘れに依存せず、ここで必ず残す。

total_cost_usd は Claude が返す「API換算の目安額」で、サブスクリプションで
動かしている限り実際に請求される金額ではない。
"""

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# broker.py と同じ理由。応答本文に cp932 に無い文字（✓ など）が混ざると
# Windows では print で落ちる。出力を UTF-8 に固定しておく。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

JST = timezone(timedelta(hours=9))
LOG = Path("usage_log.csv")
JOURNAL = Path("journal.jsonl")

# server_tool_use は Anthropic 側のサーバー検索の回数で、Claude Code の
# WebSearch は別経路のため常に0になる。実態を測れないので列から外した。
HEADER = [
    "ts", "session", "ok", "turns", "duration_s",
    "input_tokens", "cache_create", "cache_read", "output_tokens",
    "cost_usd_equiv", "models",
]


def record_session(ts, session, ok, turns, summary):
    """セッションの結論を journal.jsonl に残す。売買の有無に関わらず必ず書く。"""
    if not summary:
        summary = "（このセッションは要約を残さなかった）"
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": ts, "status": "SESSION", "session": session,
            "ok": ok, "turns": turns, "summary": summary,
        }, ensure_ascii=False) + "\n")


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit("使い方: python record_usage.py <セッション名> <JSONファイル>")
    session, path = sys.argv[1], Path(sys.argv[2])
    ts = datetime.now(JST).isoformat(timespec="seconds")

    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        # claude が途中で落ちると JSON にならない。計測できないだけで
        # セッションの成否とは別問題なので、ここでは失敗させない。
        print("（消費量を記録できなかった: 出力がJSONではない）", file=sys.stderr)
        if raw.strip():
            print(raw)
        record_session(ts, session, False, "", raw.strip()[:4000] or None)
        return 0

    if d.get("result"):
        print(d["result"])

    ok = not d.get("is_error")
    turns = d.get("num_turns", "")
    summary = (d.get("result") or "").strip()
    if not ok:
        # ターン上限などで打ち切られると、判断の途中で終わったのに
        # そこまでの約定は state.json に確定している。記録の先頭で明示する。
        why = {"error_max_turns": f"ターン上限({turns})に達して打ち切られました"}.get(
            d.get("subtype"), f"異常終了しました（{d.get('subtype')}）")
        summary = f"⚠ このセッションは{why}。判断が途中で終わっている可能性があります。\n\n{summary}"
    record_session(ts, session, ok, turns, summary)

    u = d.get("usage") or {}
    models = d.get("modelUsage") or {}
    # 数値は必ず数で持つ。欠けているときに空文字を入れると、下の桁区切り書式が
    # 例外を投げ、set -e でセッション全体が失敗扱いになる。
    n = lambda k: int(u.get(k) or 0)
    row = [
        ts, session,
        "ok" if ok else f"error:{d.get('subtype', '?')}",
        turns,
        round((d.get("duration_ms") or 0) / 1000, 1),
        n("input_tokens"),
        n("cache_creation_input_tokens"),
        n("cache_read_input_tokens"),
        n("output_tokens"),
        round(d.get("total_cost_usd") or 0, 4),
        "|".join(sorted(models)) if isinstance(models, dict) else str(models),
    ]

    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow(row)

    print(f"[消費] {session}: {turns}ターン / {row[4]}秒 / "
          f"入力{row[5]:,}+キャッシュ読み{row[7]:,} 出力{row[8]:,}トークン / "
          f"API換算 ${row[9]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
