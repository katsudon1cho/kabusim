#!/usr/bin/env python3
"""
build_site.py — docs/ 配下の PWA が読むデータを生成する。

state.json / equity_log.csv / journal.jsonl / reports/*.md を読んで
docs/data/summary.json と docs/data/reports/<date>.json を書き出す。

静的サイトはディレクトリ一覧を取得できないので、この索引生成が必須になる。

セッションの直後に GitHub Actions から呼ばれる想定。単体でも動く:

    python build_site.py
"""

import csv
import html
import json
import re
import sys
from pathlib import Path

import broker

DOCS = Path("docs")
DATA = DOCS / "data"
REPORTS_SRC = Path("reports")
REPORTS_OUT = DATA / "reports"

BOOK_NAMES = {"us": "米国株ブック", "jp": "日本株ブック"}
BOOK_CCY = {"us": "USD", "jp": "JPY"}


# =========================================================
# Markdown → HTML
# =========================================================

_INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2" rel="noopener">\1</a>'),
]


def _inline(text: str) -> str:
    out = html.escape(text)
    for pat, rep in _INLINE:
        out = pat.sub(rep, out)
    return out


def md_to_html(md: str) -> str:
    """日報で実際に使われる範囲だけを訳す小さな変換器。

    見出し / 箇条書き / 番号付き / 表 / 引用 / 水平線 / コードブロック / 段落。
    外部ライブラリを足したくないので自前で持つ。
    """
    lines = md.replace("\r\n", "\n").split("\n")
    out, i = [], 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # コードブロック
        if stripped.startswith("```"):
            i += 1
            body = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(html.escape(lines[i]))
                i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(body) + "</code></pre>")
            continue

        # 空行
        if not stripped:
            i += 1
            continue

        # 水平線
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            out.append("<hr>")
            i += 1
            continue

        # 見出し
        m = re.match(r"(#{1,6})\s+(.*)", stripped)
        if m:
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1
            continue

        # 表（2行目が区切り行のときだけ表として扱う）
        if stripped.startswith("|") and i + 1 < len(lines) \
                and re.fullmatch(r"\|[\s:|-]+\|?", lines[i + 1].strip()):
            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]

            head = cells(stripped)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(cells(lines[i].strip()))
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            trs = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
                for row in body
            )
            out.append(f'<div class="tw"><table><thead><tr>{th}</tr></thead>'
                       f"<tbody>{trs}</tbody></table></div>")
            continue

        # 引用
        if stripped.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(body)) + "</blockquote>")
            continue

        # 箇条書き / 番号付き
        m = re.match(r"([-*+]|\d+\.)\s+(.*)", stripped)
        if m:
            ordered = not m.group(1) in ("-", "*", "+")
            items = []
            while i < len(lines):
                mm = re.match(r"\s*([-*+]|\d+\.)\s+(.*)", lines[i])
                if not mm:
                    break
                items.append(f"<li>{_inline(mm.group(2))}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue

        # 段落（続く行をまとめる）
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||```)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
        else:
            i += 1

    return "\n".join(out)


# =========================================================
# データ収集
# =========================================================

def load_prices(state):
    """現在値を取る。取れなくてもサイト生成は止めない。"""
    try:
        return broker.get_prices(broker.all_tickers(state)), True
    except Exception as e:                     # ネットワーク断・API変更など
        print(f"価格を取得できなかったので簿価で代用する: {e}", file=sys.stderr)
        return {}, False


def book_summary(state, px, b):
    bk = state["books"][b]
    eq = broker.equity(bk, px)
    bm = broker.bench_value(bk, px, b)
    positions = []
    for t, p in sorted(bk["positions"].items()):
        q = px.get(t, p["avg_cost"])
        mv = p["shares"] * q
        positions.append({
            "ticker": t,
            "shares": p["shares"],
            "avg_cost": round(p["avg_cost"], 2),
            "price": round(q, 2),
            "value": round(mv, 2),
            "weight_pct": round(mv / eq * 100, 2) if eq else 0.0,
            "pnl_pct": round((q / p["avg_cost"] - 1) * 100, 2) if p["avg_cost"] else 0.0,
        })
    return {
        "name": BOOK_NAMES[b],
        "currency": broker.cur(b),
        "ccy_code": BOOK_CCY[b],
        "bench": broker.BENCH[b],
        "start_equity": bk["start_equity"],
        "equity": round(eq, 2),
        "cash": round(bk["cash"], 2),
        "cash_pct": round(bk["cash"] / eq * 100, 2) if eq else 100.0,
        "ret_pct": round((eq / bk["start_equity"] - 1) * 100, 3),
        "bench_pct": round((bm / bk["start_equity"] - 1) * 100, 3),
        "diff_pt": round((eq / bm - 1) * 100, 3) if bm else 0.0,
        "buys_today": broker.buys_today(bk),
        "max_buys": broker.MAX_BUYS_PER_DAY,
        "universe": broker.universe(b),
        "positions": positions,
    }


def read_series():
    series = {"us": [], "jp": []}
    if not broker.EQUITY_LOG.exists():
        return series
    with broker.EQUITY_LOG.open(newline="", encoding=broker.ENC) as f:
        for row in csv.DictReader(f):
            b = row.get("book")
            if b in series:
                series[b].append({
                    "date": row["date"],
                    "ret": float(row["ret_pct"]),
                    "bench": float(row["bench_pct"]),
                })
    for b in series:
        series[b].sort(key=lambda r: r["date"])
    return series


def read_trades(limit=400):
    """注文とセッションの結論を、時系列でひとまとめに返す。

    売買しなかったセッションも SESSION 行として入っているので、
    「調べたうえで見送った」も履歴に残る。
    """
    if not broker.JOURNAL.exists():
        return []
    out = []
    for line in broker.JOURNAL.read_text(encoding=broker.ENC).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("status") == "SESSION":
            # 要約は Markdown で書かれてくるので、日報と同じ変換をかける
            e["html"] = md_to_html(e.get("summary") or "")
        else:
            e["book"] = broker.book_of(e.get("ticker", ""))
        out.append(e)
    out.reverse()                              # 新しい順
    return out[:limit]


def write_reports():
    REPORTS_OUT.mkdir(parents=True, exist_ok=True)
    dates = []
    for md in sorted(REPORTS_SRC.glob("*.md")) if REPORTS_SRC.exists() else []:
        date = md.stem
        dates.append(date)
        (REPORTS_OUT / f"{date}.json").write_text(
            json.dumps({"date": date, "html": md_to_html(md.read_text(encoding=broker.ENC))},
                       ensure_ascii=False),
            encoding=broker.ENC)
    dates.sort(reverse=True)                   # 新しい順
    return dates


def main():
    if not broker.STATE.exists():
        sys.exit("state.json が無い。先に broker.py init を実行して。")

    state = broker.load()
    px, prices_ok = load_prices(state)

    DATA.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": broker.now().isoformat(timespec="minutes"),
        "start_date": state.get("start_date"),
        "prices_ok": prices_ok,
        "books": {b: book_summary(state, px, b) for b in ("us", "jp")},
        "series": read_series(),
        "trades": read_trades(),
        "reports": write_reports(),
    }
    (DATA / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding=broker.ENC)

    print(f"生成した: {DATA/'summary.json'}  "
          f"（日報 {len(summary['reports'])}件 / 売買記録 {len(summary['trades'])}件 / "
          f"価格取得 {'成功' if prices_ok else '失敗→簿価で代用'}）")


if __name__ == "__main__":
    main()
