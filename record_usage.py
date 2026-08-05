#!/usr/bin/env python3
"""
record_usage.py — セッション1回分の消費量を usage_log.csv に追記する。

session.sh が `claude -p --output-format json` の出力を渡してくる。
このスクリプトは2つのことをする:

  1. 応答本文を標準出力に流す（ログを人が読める状態に保つため）
  2. トークン数・Web検索回数・所要時間を usage_log.csv に1行追記する

    python record_usage.py <セッション名> <claudeのJSON出力ファイル>

total_cost_usd は Claude が返す「API換算の目安額」で、サブスクリプションで
動かしている限り実際に請求される金額ではない。枠の消費量を比べるための
相対的な物差しとして見ること。
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

HEADER = [
    "ts", "session", "ok", "turns", "duration_s",
    "input_tokens", "cache_create", "cache_read", "output_tokens",
    "web_search", "web_fetch", "cost_usd_equiv", "models",
]


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit("使い方: python record_usage.py <セッション名> <JSONファイル>")
    session, path = sys.argv[1], Path(sys.argv[2])

    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        # claude が途中で落ちると JSON にならない。計測できないだけで
        # セッションの成否とは別問題なので、ここでは失敗させない。
        print("（消費量を記録できなかった: 出力がJSONではない）", file=sys.stderr)
        if raw.strip():
            print(raw)
        return 0

    # 応答本文はログに残す
    if d.get("result"):
        print(d["result"])

    u = d.get("usage") or {}
    st = u.get("server_tool_use") or {}
    models = d.get("modelUsage") or {}

    row = [
        datetime.now(JST).isoformat(timespec="seconds"),
        session,
        "ok" if not d.get("is_error") else f"error:{d.get('subtype', '?')}",
        d.get("num_turns", ""),
        round((d.get("duration_ms") or 0) / 1000, 1),
        u.get("input_tokens", ""),
        u.get("cache_creation_input_tokens", ""),
        u.get("cache_read_input_tokens", ""),
        u.get("output_tokens", ""),
        st.get("web_search_requests", ""),
        st.get("web_fetch_requests", ""),
        round(d.get("total_cost_usd") or 0, 4),
        "|".join(sorted(models)) if isinstance(models, dict) else str(models),
    ]

    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow(row)

    print(
        f"[消費] {session}: {row[3]}ターン / {row[4]}秒 / "
        f"入力{row[5]:,}+キャッシュ読み{row[7]:,} 出力{row[8]:,}トークン / "
        f"Web検索{row[9]}回 / API換算 ${row[11]}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
