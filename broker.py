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
# S&P500 の上位構成に寄せると指数から乖離しようがないので、意図的に
# 業種を散らしてある。テックは45銘柄中13（29%）に抑えた。
US_UNIVERSE = [
    # 情報技術・通信サービス
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA",
    "AMD", "NFLX", "ORCL", "CRM", "TXN", "DIS", "TMUS",
    # ヘルスケア
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ISRG",
    # 生活必需品・一般消費財
    "COST", "PG", "KO", "PEP", "WMT", "HD", "MCD", "NKE",
    # 金融
    "JPM", "V", "BAC", "GS", "BLK", "SPGI",
    # 資本財・運輸
    "CAT", "HON", "UNP", "GE",
    # エネルギー・素材・公益・不動産
    "XOM", "CVX", "LIN", "NEE", "AMT",
]
# 日本株は単元100株なので、1株の値段が「ブック総資産 x MAX_POSITION_PCT / 100」を
# 超える銘柄は一度も約定できない。JP元本2,000万円なら1株50,000円が上限。
# キーエンス(6861)と東京エレクトロン(8035)はこれを超えるため、同業のファナック
# (6954)とアドバンテスト(6857)に置き換えた。銘柄を足すときは必ずこの計算をすること。
# 全銘柄が「1株 ≤ 総資産×25%÷100」を満たすことを確認済み（`universe` で再確認できる）。
# キーエンス(6861) / 東京エレクトロン(8035) / ディスコ(6146) / SMC(6273) は
# 1単元が上限を超えるため入れていない。
JP_UNIVERSE = [
    # 自動車・機械
    "7203.T", "7267.T", "6954.T",
    # 電機・精密・電子部品
    "6758.T", "6501.T", "6981.T", "6702.T", "6503.T", "7751.T",
    # 半導体
    "6857.T", "6963.T", "6723.T", "6920.T",
    # 銀行・保険
    "8306.T", "8316.T", "8411.T", "8766.T", "8750.T",
    # 商社・投資
    "8058.T", "8031.T", "8001.T", "9984.T",
    # 医薬
    "4568.T", "4502.T", "4519.T",
    # 素材・化学・鉄鋼
    "4063.T", "4452.T", "4901.T", "5401.T",
    # 通信・IT・サービス
    "9433.T", "9432.T", "9434.T", "6098.T", "4661.T", "7974.T",
    # 小売・食品
    "3382.T", "8267.T", "9843.T", "2914.T", "2802.T", "2502.T",
    # 運輸・不動産・公益
    "9020.T", "9022.T", "9101.T", "8801.T", "9531.T",
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


def daily(tickers, period="5d"):
    """日足の終値を DataFrame（列=銘柄）で返す。前日比や騰落率の計算に使う。"""
    tickers = sorted(set(t.upper() for t in tickers))
    if os.environ.get("BROKER_OFFLINE"):
        import pandas as pd
        n = 300
        return pd.DataFrame(
            {t: [round(random.uniform(1000, 4000) if t.endswith(".T")
                       else random.uniform(50, 500), 2) for _ in range(n)]
             for t in tickers},
            index=pd.date_range(end=now().date(), periods=n, freq="D"))
    import yfinance as yf
    df = yf.download(tickers, period=period, interval="1d",
                     progress=False, auto_adjust=True)
    # ここで ffill してはいけない。まだ値の無い当日の行が前日値で埋まり、
    # 前日比がゼロになる。欠損は使う側が列ごとに dropna して落とす。
    return df["Close"] if hasattr(df["Close"], "columns") else df["Close"].to_frame(tickers[0])


def earnings_dates(tickers) -> dict:
    """次の決算日を {銘柄: date} で返す。取れないものは None。

    1銘柄あたり0.25秒ほどかかるので、ユニバース全体で10〜20秒。
    """
    if os.environ.get("BROKER_OFFLINE"):
        return {t: None for t in tickers}
    import yfinance as yf
    out = {}
    for t in tickers:
        d = None
        try:
            cal = yf.Ticker(t).calendar or {}
            v = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if isinstance(v, (list, tuple)) and v:
                d = v[0]
            elif v is not None:
                d = v
            if hasattr(d, "date"):
                d = d.date()
        except Exception:
            d = None
        out[t] = d
    return out


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
    df = daily(args.tickers, "5d")
    for t in sorted(df.columns):
        s = df[t].dropna()
        if s.empty:
            continue
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) >= 2 else last
        chg = (last / prev - 1) * 100 if prev else 0.0
        b = book_of(t)
        note = "" if t in universe(b) else "   ※ユニバース外（売買できない）"
        print(f"{t:<9}{cur(b)}{last:>11,.2f}  前日比 {chg:+6.2f}%{note}")
    for t in args.tickers:
        if t.upper() not in df.columns:
            print(f"{t:<9}取得失敗")


def cmd_history(args) -> None:
    """騰落率と52週レンジの中での位置を出す。

    「動いた理由を調べてから判断する」ためには、まず動いたかどうかが
    分からないといけない。現在値だけでは推測になる。
    """
    df = daily(args.tickers, "1y")
    for t in sorted(df.columns):
        s = df[t].dropna()
        if s.empty:
            continue
        last, c = float(s.iloc[-1]), cur(book_of(t))
        hi, lo = float(s.max()), float(s.min())

        def ret(n):
            return (last / float(s.iloc[-1 - n]) - 1) * 100 if len(s) > n else None

        spans = [("1日", 1), ("1週", 5), ("1月", 21), ("3月", 63), ("1年", 251)]
        parts = [f"{lab} {r:+.1f}%" for lab, n in spans if (r := ret(n)) is not None]
        pos = (last - lo) / (hi - lo) * 100 if hi > lo else 50.0
        print(f"{t}  {c}{last:,.2f}")
        print(f"  騰落率  " + " / ".join(parts))
        print(f"  52週    安 {c}{lo:,.2f} 〜 高 {c}{hi:,.2f}（現在は下から{pos:.0f}%の位置）")
        recent = " ".join(f"{float(v):,.1f}" for v in s.iloc[-10:])
        print(f"  直近10日 {recent}\n")
    for t in args.tickers:
        if t.upper() not in df.columns:
            print(f"{t:<9}取得失敗")


def cmd_screen(args) -> None:
    """手順4の条件に当てはまる銘柄だけを絞り込む。

    ユニバースが各ブック45銘柄あるので、全部を個別に調べることはできない。
    条件をコード側で判定して、調べるべきものだけを出す。
    """
    s = load()
    books = [args.book] if args.book else ["us", "jp"]
    today = now().date()

    for b in books:
        u = universe(b)
        held = set(s["books"][b]["positions"])
        name = "米国株" if b == "us" else "日本株"
        print(f"=== {name}ブック {len(u)}銘柄を絞り込み ===")

        df = daily(u, "5d")
        moves = {}
        for t in u:
            if t not in df.columns:
                continue
            col = df[t].dropna()
            if len(col) < 2:
                continue
            moves[t] = (float(col.iloc[-1]),
                        (float(col.iloc[-1]) / float(col.iloc[-2]) - 1) * 100)

        eds = earnings_dates(u)
        hits = []
        for t, (px, chg) in moves.items():
            flags = []
            if abs(chg) >= args.move:
                flags.append(f"値動き{chg:+.1f}%")
            d = eds.get(t)
            if d is not None:
                days = (d - today).days
                if 0 <= days <= 7:
                    flags.append(f"決算{days}日後")
                elif -3 <= days < 0:
                    flags.append(f"決算{-days}日前に発表済")
            if t in held:
                flags.append("保有中")
            if flags:
                hits.append((abs(chg), t, px, chg, flags))

        if not hits:
            print(f"  条件に該当なし（値動き±{args.move}% / 決算が前後）\n")
            continue

        hits.sort(reverse=True)
        for _, t, px, chg, flags in hits[:args.limit]:
            print(f"  {t:<9}{cur(b)}{px:>11,.2f} {chg:+6.2f}%  {' / '.join(flags)}")
        if len(hits) > args.limit:
            print(f"  （該当 {len(hits)}件のうち値動きの大きい {args.limit}件を表示）")
        print()


def cmd_clock(args) -> None:
    """いま各市場が開いているかを出す。

    定時実行は数時間ずれることがあり、セッション名（寄り付き後／引け前）と
    実際の市場の状態が食い違う。名前ではなく事実を渡すためのもの。
    祝日は見ていないので、休場日は値が動かないことで気づくしかない。
    """
    t = now()
    wd = "月火水木金土日"[t.weekday()]
    print(f"現在 {t:%Y-%m-%d %H:%M} JST（{wd}）")

    mins = t.hour * 60 + t.minute

    def span(label, phases):
        for lo, hi, name, closing in phases:
            if lo <= mins < hi:
                tail = f"（引けまで{hi - mins}分）" if closing else ""
                return f"  {label}: {name}{tail}"
        return None

    # 曜日は市場ごとに見る。以前は JST の曜日で両市場をまとめて休場と判定して
    # 早期 return していたが、夏時間の米国市場は JST 22:30〜翌05:00 なので
    # 「JST 土曜の未明」は金曜の立会中にあたる。us-close は 04:08 JST（火〜土）に
    # 走るため、この枠が毎回「休場」と誤報されていた。
    jp_open_day = t.weekday() < 5
    # 米国は JST 05:00 までが前日の立会の続き。その時間帯は前日の曜日で判定する。
    us_day = (t - timedelta(days=1)).weekday() if mins < 5 * 60 else t.weekday()
    us_open_day = us_day < 5

    jp = span("日本市場", [
        (0, 9 * 60, "寄り付き前", False),
        (9 * 60, 11 * 60 + 30, "前場", False),
        (11 * 60 + 30, 12 * 60 + 30, "昼休み", False),
        (12 * 60 + 30, 15 * 60 + 30, "後場", True),
        (15 * 60 + 30, 24 * 60, "引け後", False),
    ]) if jp_open_day else "  日本市場: 休場（土日）"

    # 夏時間の米国市場は JST 22:30〜翌05:00。冬は1時間後ろ
    us = span("米国市場", [
        (0, 5 * 60, "取引時間中", True),
        (5 * 60, 21 * 60, "閉場", False),
        (21 * 60, 22 * 60 + 30, "寄り付き前", False),
        (22 * 60 + 30, 24 * 60, "取引時間中", False),
    ]) if us_open_day else "  米国市場: 休場（週末）"

    for line in (jp, us):
        if line:
            print(line)


def cmd_universe(args) -> None:
    """ユニバースの銘柄が実際に買えるか点検する。

    日本株は単元100株なので、株価が上がると「候補に載っているのに必ず却下される」
    銘柄が静かに増える。定期的にこれで確認すること。
    """
    s = load()
    px = get_prices(all_tickers(s))
    for b in ("us", "jp"):
        bk, c, lot = s["books"][b], cur(b), LOT[b]
        cap = equity(bk, px) * MAX_POSITION_PCT
        limit = cap / lot
        u = universe(b)
        name = "米国株" if b == "us" else "日本株"
        print(f"=== {name}ブック {len(u)}銘柄 ===")
        print(f"1銘柄上限 {c}{cap:,.0f} / 単元{lot}株 → 1株 {c}{limit:,.0f} まで")
        bad = [(t, px.get(t)) for t in sorted(u)
               if px.get(t) is None or px[t] > limit]
        if not bad:
            print("  全銘柄が購入可能\n")
            continue
        print(f"  買えない銘柄 {len(bad)}件:")
        for t, p in bad:
            tail = f"{c}{p:,.0f}（1単元 {c}{p * lot:,.0f}）" if p else "価格を取得できない"
            print(f"    {t:<9}{tail}")
        print()


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


def verdict(summary: str, width: int = 88) -> str:
    """セッション要約から結論の一行を取り出す。

    結論は末尾に来ることが多いので、「判断」「結論」を含む行を優先し、
    無ければ最後の実質的な行を使う。見出しと箇条書きの記号は落とす。
    """
    lines = [ln.strip().lstrip("#-*> ").strip()
             for ln in summary.splitlines() if ln.strip()]
    lines = [ln for ln in lines if len(ln) > 4]
    if not lines:
        return "（要約なし）"
    pick = next((ln for ln in reversed(lines)
                 if "判断" in ln or "結論" in ln), lines[-1])
    pick = pick.replace("**", "")
    return pick if len(pick) <= width else pick[:width - 1] + "…"


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

        # セッションの結論。売買しなかった回もここに残る。
        # 既定では1行に畳む。5回/日×7日=35件を全文で出すと1万トークンを超え、
        # 肝心の注文の理由がその中に埋もれる。全文が要るときだけ --full。
        if e["status"] == "SESSION":
            head = f"{e['ts'][:16]} ◆ {e.get('session', '?'):<9}"
            if args.full:
                print(f"{head}（{e.get('turns', '?')}ターン）")
                for ln in (e.get("summary") or "").splitlines():
                    print(f"    {ln}")
                print()
            else:
                print(f"{head}{verdict(e.get('summary') or '')}")
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
    h = sub.add_parser("history"); h.add_argument("tickers", nargs="+")

    sc = sub.add_parser("screen")
    sc.add_argument("--book", choices=["us", "jp"])
    sc.add_argument("--move", type=float, default=3.0, help="値動きのしきい値（%）")
    sc.add_argument("--limit", type=int, default=8, help="表示する最大件数")

    for name in ("buy", "sell"):
        t = sub.add_parser(name)
        t.add_argument("ticker"); t.add_argument("shares", type=int)
        t.add_argument("--reason", required=True, help="判断理由。必須。")

    j = sub.add_parser("journal")
    j.add_argument("--days", type=int, default=7)
    j.add_argument("--full", action="store_true", help="セッション要約を全文表示する")
    sub.add_parser("snapshot")
    sub.add_parser("universe")
    sub.add_parser("clock")

    a = p.parse_args()
    {"init": cmd_init, "status": cmd_status, "quote": cmd_quote,
     "history": cmd_history, "screen": cmd_screen, "clock": cmd_clock,
     "journal": cmd_journal, "snapshot": cmd_snapshot,
     "universe": cmd_universe}.get(
        a.cmd, lambda x: cmd_trade(x, a.cmd.upper()))(a)
