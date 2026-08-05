#!/usr/bin/env python3
"""
update_prices.py — PWA 用に、保有銘柄の値動きを取り直す。

セッション（1日5回）とは別に、市場が開いている間だけ15分ごとに走らせる。
Claude は使わないので利用枠を消費しない。

    python update_prices.py        # docs/data/prices.json を書き出す

出すもの:
  - 保有銘柄とベンチマークの現在値・前日終値・前日比
  - 1日(5分足) / 1ヶ月(日足) / 1年(日足) の系列
  - その時点の資産・ベンチ比較（現在値で計算し直したもの）

yfinance の値は数分遅れる。加えて GitHub のスケジュール実行自体が5〜20分ずれる
ことがあるので、実際の粒度は15〜30分と考えること。「今この瞬間」ではない。
"""

import json
import math
import sys
from pathlib import Path

import broker

OUT = Path("docs/data/prices.json")


def _col(df, key, ticker):
    """1銘柄と複数銘柄で列の形が変わるのを吸収する。"""
    sub = df[key]
    if hasattr(sub, "columns"):
        return sub[ticker] if ticker in sub.columns else None
    return sub


def series(df, ticker, as_date=False):
    """欠損を落として [時刻, 値] の2本の配列にする。JSONを小さく保つため丸める。"""
    s = _col(df, "Close", ticker)
    if s is None:
        return None
    s = s.dropna()
    if s.empty:
        return None
    t = [str(i.date()) if as_date else int(i.timestamp()) for i in s.index]
    v = [round(float(x), 2) for x in s]
    return {"t": t, "v": v}


def main() -> int:
    if not broker.STATE.exists():
        sys.exit("state.json が無い。先に broker.py init を実行して。")

    state = broker.load()
    held = sorted({t for b in state["books"].values() for t in b["positions"]})
    tickers = sorted(set(held) | set(broker.BENCH.values()))

    import yfinance as yf

    # 1年の日足（現在値・前日終値・1ヶ月・1年ぶんをここから作る）
    daily = yf.download(tickers, period="1y", interval="1d",
                        progress=False, auto_adjust=True)
    # 当日の5分足。休場中は空になることがある
    try:
        intra = yf.download(tickers, period="1d", interval="5m",
                            progress=False, auto_adjust=True)
    except Exception as e:
        print(f"5分足を取得できなかった: {e}", file=sys.stderr)
        intra = None

    quotes, ser = {}, {}
    for tk in tickers:
        d = series(daily, tk, as_date=True)
        if not d:
            print(f"{tk}: 日足を取得できない", file=sys.stderr)
            continue

        i = series(intra, tk) if intra is not None and not intra.empty else None

        # 現在値は5分足の最後を優先。無ければ日足の最後
        price = i["v"][-1] if i and i["v"] else d["v"][-1]
        prev = d["v"][-2] if len(d["v"]) >= 2 else d["v"][-1]
        # 日足の最終が「本日」なら前日終値はその1つ前、そうでなければ最終足が前日終値
        quotes[tk] = {
            "price": price,
            "prev_close": prev,
            "chg_pct": round((price / prev - 1) * 100, 2) if prev else 0.0,
        }
        ser[tk] = {
            "1d": i or {"t": [], "v": []},
            "1m": {"t": d["t"][-22:], "v": d["v"][-22:]},
            "1y": d,
        }

    if not quotes:
        sys.exit("価格を1件も取得できなかった。書き出しを中止する。")

    px = {t: q["price"] for t, q in quotes.items()}
    books = {}
    for b in ("us", "jp"):
        bk = state["books"][b]
        eq = broker.equity(bk, px)
        bm = broker.bench_value(bk, px, b)
        books[b] = {
            "equity": round(eq, 2),
            "cash": round(bk["cash"], 2),
            "cash_pct": round(bk["cash"] / eq * 100, 2) if eq else 100.0,
            "ret_pct": round((eq / bk["start_equity"] - 1) * 100, 3),
            "bench_pct": round((bm / bk["start_equity"] - 1) * 100, 3),
            "diff_pt": round((eq / bm - 1) * 100, 3) if bm else 0.0,
            "positions": [
                {
                    "ticker": t,
                    "shares": p["shares"],
                    "avg_cost": round(p["avg_cost"], 2),
                    "price": px.get(t, p["avg_cost"]),
                    "value": round(p["shares"] * px.get(t, p["avg_cost"]), 2),
                    "weight_pct": round(p["shares"] * px.get(t, p["avg_cost"]) / eq * 100, 2) if eq else 0.0,
                    "pnl_pct": round((px.get(t, p["avg_cost"]) / p["avg_cost"] - 1) * 100, 2) if p["avg_cost"] else 0.0,
                    "day_pct": quotes.get(t, {}).get("chg_pct", 0.0),
                }
                for t, p in sorted(bk["positions"].items())
            ],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated_at": broker.now().isoformat(timespec="minutes"),
        "bench": broker.BENCH,
        "quotes": quotes,
        "series": ser,
        "books": books,
    }, ensure_ascii=False, separators=(",", ":")), encoding=broker.ENC)

    kb = OUT.stat().st_size / 1024
    intraday = sum(1 for t in ser if ser[t]["1d"]["v"])
    print(f"{OUT}: {len(quotes)}銘柄 / 5分足あり {intraday}銘柄 / {kb:,.0f}KB")
    for b in ("us", "jp"):
        c = broker.cur(b)
        print(f"  {b}: {c}{books[b]['equity']:,.0f} "
              f"({books[b]['ret_pct']:+.2f}% / ベンチ差 {books[b]['diff_pt']:+.2f}pt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
