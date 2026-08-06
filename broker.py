#!/usr/bin/env python3
"""
broker.py — Claude Code から Bash 経由で叩かれる「証券会社」役。

米国株ブック(USD) と 日本株ブック(JPY) を独立管理し、それぞれ SPY / TOPIX と比較する。
実注文は一切出さない。すべてローカルの state.json 上の出来事。

判断はしない。検証と記録だけをする。判断は Claude Code 側の仕事。

    python broker.py init --us 50000 --jp 20000000
    python broker.py status              # 両ブックの現状
    python broker.py quote AAPL 7203.T   # 現在値
    python broker.py buy AAPL 10 --reason "決算good"
    python broker.py sell 7203.T 100 --reason "目標到達"
    python broker.py journal --days 7    # 過去の判断と約定
    python broker.py snapshot            # 日次の資産記録(日報前に実行)

    BROKER_OFFLINE=1 python broker.py ...   # ダミー価格で動作確認
"""

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 日本語Windowsの既定文字コード(cp932)では "¥"(U+00A5) と "✓"(U+2713) を
# 表現できず、日本株の表示や journal で UnicodeEncodeError になる。
# 出力もファイルI/Oも UTF-8 に固定しておく。
ENC = "utf-8"
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding=ENC)
    except AttributeError:      # 3.6以前 / 差し替え済みストリーム
        pass

JST = timezone(timedelta(hours=9))
STATE = Path("state.json")
JOURNAL = Path("journal.jsonl")
EQUITY_LOG = Path("equity_log.csv")

# ---- ユニバース: ここに無い銘柄は全部拒否 ----
# ベンチマーク自身(SPY / 1306.T)は意図的に入れていない。買った分はベンチと同じ
# 動きになりアルファが出ないため。QQQ も中身が個別銘柄と重複し、25%上限を
# 迂回する抜け穴になるので除外している。
US_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA",
    "JPM", "V", "UNH", "XOM", "COST", "LLY", "AMD", "NFLX",
]
# 日本株は単元100株なので、1株の値段が「ブック総資産 x MAX_POSITION_PCT / 100」を
# 超える銘柄は一度も約定できない。JP元本2,000万円なら1株50,000円が上限。
# キーエンス(6861)と東京エレクトロン(8035)はこれを超えるため、同業のファナック
# (6954)とアドバンテスト(6857)に置き換えた。銘柄を足すときは必ずこの計算をすること。
JP_UNIVERSE = [
    "7203.T", "6758.T", "8306.T", "9984.T", "6954.T", "7974.T", "8058.T",
    "6501.T", "4063.T", "9433.T", "6098.T", "6857.T", "7267.T",
    "4568.T", "2914.T", "9020.T",   # 内需ディフェンシブ: 第一三共 / JT / JR東日本
]
BENCH = {"us": "SPY", "jp": "1306.T"}   # 1306 = TOPIX連動ETF。比較用で売買はできない
LOT = {"us": 1, "jp": 100}              # 日本株は単元100株

# ---- ガードレール ----
MAX_POSITION_PCT = 0.25    # 1銘柄あたりブック総資産の25%まで
MIN_CASH_PCT = 0.02        # 常に2%は現金
MAX_BUYS_PER_DAY = 4       # ブックごとの1日の「買い」上限。売りは対象外
COOLDOWN_HOURS = 20        # 同一銘柄を再度売買するまでの待ち時間
SLIPPAGE_BPS = 5


def book_of(ticker: str) -> str:
    return "jp" if ticker.upper().endswith(".T") else "us"


def universe(book: str) -> list:
    return JP_UNIVERSE if book == "jp" else US_UNIVERSE


def cur(book: str) -> str:
    return "¥" if book == "jp" else "$"


def now() -> datetime:
    return datetime.now(JST)


# =========================================================
# 状態
# =========================================================

def load() -> dict:
    if not STATE.exists():
        sys.exit("state.json が無い。先に `init` を実行して。")
    return json.loads(STATE.read_text(encoding=ENC))


def save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding=ENC)


def cmd_init(args) -> None:
    if STATE.exists():
        sys.exit("state.json が既にある。消してからやり直して。")
    s = {"start_date": now().date().isoformat(), "books": {}}
    for b, cap in (("us", args.us), ("jp", args.jp)):
        s["books"][b] = {
            "start_equity": cap, "cash": cap, "positions": {},
            "bench_shares": None, "last_trade": {}, "buys_today": {},
        }
    save(s)
    print(f"初期化: 米国株 ${args.us:,.0f} / 日本株 ¥{args.jp:,.0f}")
    print(f"日本株の1銘柄上限 ¥{args.jp * MAX_POSITION_PCT:,.0f} "
          f"→ 1株 ¥{args.jp * MAX_POSITION_PCT / LOT['jp']:,.0f} を超える銘柄は買えない")


# =========================================================
# 価格
# =========================================================

def get_prices(tickers) -> dict:
    tickers = sorted(set(t.upper() for t in tickers))
    if os.environ.get("BROKER_OFFLINE"):
        return {t: round(random.uniform(1000, 4000) if t.endswith(".T")
                         else random.uniform(50, 500), 2) for t in tickers}
    import yfinance as yf
    df = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
    close = df["Close"] if len(tickers) > 1 else df["Close"].to_frame(tickers[0])
    last = close.ffill().iloc[-1]
    return {t: float(last[t]) for t in tickers if t in last and last[t] == last[t]}


def all_tickers(s: dict) -> list:
    ts = set(US_UNIVERSE) | set(JP_UNIVERSE) | set(BENCH.values())
    for b in s["books"].values():
        ts |= set(b["positions"])
    return sorted(ts)


# =========================================================
# 評価
# =========================================================

def equity(bk: dict, px: dict) -> float:
    return bk["cash"] + sum(p["shares"] * px.get(t, p["avg_cost"])
                            for t, p in bk["positions"].items())


def bench_value(bk: dict, px: dict, b: str) -> float:
    if bk["bench_shares"] is None:
        return bk["start_equity"]
    return bk["bench_shares"] * px[BENCH[b]]


def fmt_book(s: dict, px: dict, b: str) -> str:
    bk, c = s["books"][b], cur(b)
    eq, bm = equity(bk, px), bench_value(bk, px, b)
    name = "米国株ブック (USD)" if b == "us" else "日本株ブック (JPY)"
    out = [
        f"=== {name} ===",
        f"総資産 {c}{eq:,.0f}  ({(eq / bk['start_equity'] - 1) * 100:+.2f}%)   "
        f"ベンチ({BENCH[b]}) {(bm / bk['start_equity'] - 1) * 100:+.2f}%   "
        f"差 {(eq / bm - 1) * 100:+.2f}pt",
        f"現金 {c}{bk['cash']:,.0f} ({bk['cash'] / eq * 100:.1f}%)   "
        f"本日の買い {buys_today(bk)}/{MAX_BUYS_PER_DAY}件（売りは上限なし）",
        "保有:",
    ]
    if not bk["positions"]:
        out.append("  なし")
    for t, p in sorted(bk["positions"].items()):
        q = px.get(t, p["avg_cost"])
        mv = p["shares"] * q
        out.append(f"  {t:<8}{p['shares']:>6}株 @{c}{p['avg_cost']:,.1f} → {c}{q:,.1f}  "
                   f"{c}{mv:,.0f} ({mv / eq * 100:4.1f}%)  {(q / p['avg_cost'] - 1) * 100:+.1f}%")
    return "\n".join(out)


def buys_today(bk: dict) -> int:
    return bk["buys_today"].get(now().date().isoformat(), 0)


# =========================================================
# コマンド
# =========================================================

def cmd_status(args) -> None:
    s = load()
    px = get_prices(all_tickers(s))
    for b in ("us", "jp"):
        if s["books"][b]["bench_shares"] is None and BENCH[b] in px:
            s["books"][b]["bench_shares"] = s["books"][b]["start_equity"] / px[BENCH[b]]
    save(s)
    print(f"時刻: {now():%Y-%m-%d %H:%M} JST\n")
    for b in ("us", "jp"):
        if args.book in (None, b):
            print(fmt_book(s, px, b), "\n")


def cmd_quote(args) -> None:
    px = get_prices(args.tickers)
    for t in sorted(px):
        b = book_of(t)
        note = "" if t in universe(b) else "   ※ユニバース外（売買できない）"
        print(f"{t:<8}{cur(b)}{px[t]:,.2f}{note}")
    for t in args.tickers:
        if t.upper() not in px:
            print(f"{t:<8}取得失敗")


def cmd_trade(args, side: str) -> None:
    s = load()
    t = args.ticker.upper()
    b = book_of(t)
    bk = s["books"][b]

    def die(msg):
        record(side, t, args.shares, None, args.reason, "REJECTED", msg)
        sys.exit(f"却下: {msg}")

    if t not in universe(b):
        die(f"{t} はユニバース外")
    if args.shares <= 0 or args.shares % LOT[b] != 0:
        die(f"株数は{LOT[b]}の倍数で指定すること（0以下は不可）")
    # 上限は「買い」だけに掛ける。売りまで止めると損切りができなくなるため。
    # 売りの乱発は COOLDOWN_HOURS と保有銘柄数が事実上の歯止めになっている。
    if side == "BUY" and buys_today(bk) >= MAX_BUYS_PER_DAY:
        die(f"本日の買い上限{MAX_BUYS_PER_DAY}件に到達（売りは可能）")

    last = bk["last_trade"].get(t)
    if last:
        elapsed = (now() - datetime.fromisoformat(last)).total_seconds() / 3600
        if elapsed < COOLDOWN_HOURS:
            die(f"{t} はクールダウン中（あと{COOLDOWN_HOURS - elapsed:.1f}時間）")

    px = get_prices(all_tickers(s))
    if t not in px:
        die(f"{t} の価格を取得できない")
    raw, eq, c = px[t], equity(bk, px), cur(b)

    if side == "BUY":
        fill = raw * (1 + SLIPPAGE_BPS / 10_000)
        cost = fill * args.shares
        held = bk["positions"].get(t, {"shares": 0})["shares"]
        # 新規分はスリッページ込みの実際の支払額で評価する（約定直後の上限超えを防ぐ）
        if held * raw + cost > eq * MAX_POSITION_PCT:
            die(f"1銘柄上限{MAX_POSITION_PCT:.0%}({c}{eq * MAX_POSITION_PCT:,.0f})を超える")
        if bk["cash"] - cost < eq * MIN_CASH_PCT:
            die(f"現金不足（必要 {c}{cost:,.0f} / 使える {c}{bk['cash'] - eq * MIN_CASH_PCT:,.0f}）")
        p = bk["positions"].setdefault(t, {"shares": 0, "avg_cost": 0.0})
        p["avg_cost"] = (p["avg_cost"] * p["shares"] + fill * args.shares) / (p["shares"] + args.shares)
        p["shares"] += args.shares
        bk["cash"] -= cost
    else:
        p = bk["positions"].get(t)
        if not p or p["shares"] < args.shares:
            die(f"保有{p['shares'] if p else 0}株では足りない（空売り不可）")
        fill = raw * (1 - SLIPPAGE_BPS / 10_000)
        bk["cash"] += fill * args.shares
        p["shares"] -= args.shares
        if p["shares"] == 0:
            del bk["positions"][t]

    d = now().date().isoformat()
    if side == "BUY":
        bk["buys_today"][d] = bk["buys_today"].get(d, 0) + 1
    bk["last_trade"][t] = now().isoformat()
    save(s)
    record(side, t, args.shares, fill, args.reason, "FILLED", None)
    tail = (f"本日の買い{bk['buys_today'][d]}/{MAX_BUYS_PER_DAY}件"
            if side == "BUY" else "売りは上限対象外")
    print(f"約定 {side} {t} {args.shares}株 @{c}{fill:,.2f}  "
          f"（残現金 {c}{bk['cash']:,.0f} / {tail}）")


def record(side, ticker, shares, price, reason, status, err) -> None:
    with JOURNAL.open("a", encoding=ENC) as f:
        f.write(json.dumps({
            "ts": now().isoformat(), "status": status, "side": side,
            "ticker": ticker, "shares": shares, "price": price,
            "reason": reason, "error": err,
        }, ensure_ascii=False) + "\n")


def cmd_journal(args) -> None:
    if not JOURNAL.exists():
        return print("記録なし")
    cutoff = now() - timedelta(days=args.days)
    for line in JOURNAL.read_text(encoding=ENC).splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if datetime.fromisoformat(e["ts"]) < cutoff:
            continue

        # セッションの結論。売買しなかった回もここに残る
        if e["status"] == "SESSION":
            head = f"{e['ts'][:16]} ◆ {e.get('session', '?')}"
            print(f"{head}  （{e.get('turns', '?')}ターン）")
            for ln in (e.get("summary") or "").splitlines():
                print(f"    {ln}")
            print()
            continue

        mark = "✓" if e["status"] == "FILLED" else "✗"
        px = f"@{e['price']:,.2f}" if e["price"] else ""
        tail = e["reason"] if e["status"] == "FILLED" else e["error"]
        print(f"{e['ts'][:16]} {mark} {e['side']:4} {e['ticker']:<8}{e['shares']:>5}株 {px:<12}{tail}")


HEADER = ["date", "book", "equity", "cash", "bench", "ret_pct", "bench_pct"]


def cmd_snapshot(args) -> None:
    s = load()
    px = get_prices(all_tickers(s))
    today = now().date().isoformat()

    # 同じ日に2回流しても行が重複しないよう、当日分は書き直す。
    # 重複するとドローダウンの計算が歪む。
    rows = []
    if EQUITY_LOG.exists():
        with EQUITY_LOG.open(newline="", encoding=ENC) as f:
            rows = [r for r in csv.reader(f) if r and r[0] not in (today, "date")]

    for b in ("us", "jp"):
        bk = s["books"][b]
        eq, bm = equity(bk, px), bench_value(bk, px, b)
        rows.append([today, b, round(eq, 2), round(bk["cash"], 2),
                     round(bm, 2), round((eq / bk["start_equity"] - 1) * 100, 3),
                     round((bm / bk["start_equity"] - 1) * 100, 3)])

    with EQUITY_LOG.open("w", newline="", encoding=ENC) as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    print("記録した")
    for b in ("us", "jp"):
        print(fmt_book(s, px, b))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init")
    i.add_argument("--us", type=float, default=50_000)
    # 日本株は単元100株のため、元本が小さいと値がさ株が構造的に買えなくなる。
    # 2,000万円で1株50,000円まで対応できる。
    i.add_argument("--jp", type=float, default=20_000_000)

    st = sub.add_parser("status"); st.add_argument("--book", choices=["us", "jp"])
    q = sub.add_parser("quote"); q.add_argument("tickers", nargs="+")

    for name in ("buy", "sell"):
        t = sub.add_parser(name)
        t.add_argument("ticker"); t.add_argument("shares", type=int)
        t.add_argument("--reason", required=True, help="判断理由。必須。")

    j = sub.add_parser("journal"); j.add_argument("--days", type=int, default=7)
    sub.add_parser("snapshot")

    a = p.parse_args()
    {"init": cmd_init, "status": cmd_status, "quote": cmd_quote,
     "journal": cmd_journal, "snapshot": cmd_snapshot}.get(
        a.cmd, lambda x: cmd_trade(x, a.cmd.upper()))(a)
