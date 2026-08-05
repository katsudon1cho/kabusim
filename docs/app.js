/* 仮想運用記録 — 表示側。
   data/summary.json  … 台帳・日報・判断の履歴（セッションごとに更新）
   data/prices.json   … 四本値と出来高（市場が開いている間は15分ごとに更新）
   価格側があればそちらを優先して資産を計算し直します。 */

const $ = (s) => document.querySelector(s);
const nf = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const money = (c, v) => c + nf.format(v);
const pct = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
const ptv = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "pt";
// しきい値は表示の丸めと揃えます。0.005 は "+0.01%" と表示されるので上げ扱い
const dir = (v) => (v >= 0.005 ? "up" : v <= -0.005 ? "down" : "flat");
const cls = (v) => ({ up: "up", down: "dn", flat: "flat" }[dir(v)]);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const vol = (v) => v >= 1e9 ? (v / 1e9).toFixed(2) + "B"
  : v >= 1e6 ? (v / 1e6).toFixed(2) + "M"
  : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : String(v || 0);

// SPY は SPDR S&P 500 ETF。米国ブックは最初から S&P500 を相手にしています
const BENCH_LABEL = { "SPY": "S&P500", "1306.T": "TOPIX" };
const benchName = (t) => (BENCH_LABEL[t] ? `${BENCH_LABEL[t]}（${t}）` : t);

let DATA = null, PX = null, RANGE = "1d", CURRENT = null, logFilter = "all";

/* 台帳側と価格側を合成します。価格側のほうが新しいのでそちらを優先 */
function book(b) {
  const base = DATA.books[b];
  const live = PX && PX.books && PX.books[b];
  return live ? { ...base, ...live, key: b } : { ...base, key: b };
}

/* ---------------- ローソク足 ---------------- */

function candleChart(s, fmtT) {
  const n = s.c.length;
  if (!n) return `<p class="empty">この期間の値動きをまだ取得できていません。市場が開くと入ります。</p>`;

  const W = 340, H = 132, VH = 30, pad = { l: 2, r: 40, t: 8, b: 12 };
  const lo = Math.min(...s.l), hi = Math.max(...s.h);
  const span = hi - lo || 1;
  const bw = (W - pad.l - pad.r) / n;
  const x = (i) => pad.l + i * bw + bw / 2;
  const y = (v) => pad.t + ((hi - v) / span) * (H - pad.t - pad.b);
  const rise = s.c[n - 1] >= s.c[0];

  let body;
  if (n > 120) {
    // 本数が多すぎるとローソクが1px未満になるので線に切り替えます
    const d = s.c.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
    body = `<path class="ln mine ${rise ? "" : "dn"}" d="${d}"/>`;
  } else {
    const w = Math.max(1, bw * 0.62);
    body = s.c.map((c, i) => {
      const up = c >= s.o[i];
      const col = up ? "var(--up)" : "var(--dn)";
      const top = y(Math.max(s.o[i], c)), bot = y(Math.min(s.o[i], c));
      return `<line x1="${x(i).toFixed(1)}" y1="${y(s.h[i]).toFixed(1)}" x2="${x(i).toFixed(1)}" y2="${y(s.l[i]).toFixed(1)}" stroke="${col}" stroke-width=".8"/>` +
        `<rect x="${(x(i) - w / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(1, bot - top).toFixed(1)}" fill="${col}"/>`;
    }).join("");
  }

  const vmax = Math.max(...s.v, 1);
  const bars = s.v.some((v) => v) ? s.v.map((v, i) => {
    const h = (v / vmax) * VH;
    const col = s.c[i] >= s.o[i] ? "var(--up)" : "var(--dn)";
    return `<rect x="${(x(i) - Math.max(1, bw * .62) / 2).toFixed(1)}" y="${(H + VH - h).toFixed(1)}"
      width="${Math.max(1, bw * .62).toFixed(1)}" height="${h.toFixed(1)}" fill="${col}" opacity=".4"/>`;
  }).join("") : "";

  const last = s.c[n - 1];
  return `
  <div class="chart">
    <svg viewBox="0 0 ${W} ${H + VH}" role="img" aria-label="値動き">
      <text class="tick" x="${W - pad.r + 4}" y="${y(hi).toFixed(1)}" dominant-baseline="hanging">${nf1.format(hi)}</text>
      <text class="tick" x="${W - pad.r + 4}" y="${y(lo).toFixed(1)}">${nf1.format(lo)}</text>
      <text class="tick" x="${W - pad.r + 4}" y="${y(last).toFixed(1)}" dominant-baseline="middle"
            fill="${rise ? "var(--up)" : "var(--dn)"}">${nf1.format(last)}</text>
      ${body}${bars}
      <text class="tick" x="${pad.l}" y="${H + VH - 1}">${esc(fmtT(s.t[0]))}</text>
      <text class="tick" x="${(W - pad.r).toFixed(0)}" y="${H + VH - 1}" text-anchor="end">${esc(fmtT(s.t[n - 1]))}</text>
    </svg>
  </div>`;
}

/* 概要の資産推移。自分とベンチの2本 */
function equityChart(series, label, key) {
  if (!series || !series.length) {
    return `<p class="empty">まだ日次の記録がありません。最初の日報セッションで記録が始まります。</p>`;
  }
  const W = 340, H = 96, pad = { l: 2, r: 38, t: 8, b: 12 };
  const vals = series.flatMap((d) => [d.ret, d.bench]).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { const m = (hi + lo) / 2; lo = m - .5; hi = m + .5; }
  const n = series.length;
  const x = (i) => pad.l + (n === 1 ? (W - pad.l - pad.r) / 2 : (i * (W - pad.l - pad.r)) / (n - 1));
  const y = (v) => pad.t + ((hi - v) / (hi - lo)) * (H - pad.t - pad.b);
  const p = (k) => series.map((d, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(d[k]).toFixed(1)).join(" ");
  const last = series[n - 1], down = last.ret < 0;

  return `
  <div class="chart">
    <svg viewBox="0 0 ${W} ${H}" role="img"
         aria-label="資産推移。自分 ${pct(last.ret)}、ベンチマーク ${pct(last.bench)}">
      <line class="zero" x1="${pad.l}" y1="${y(0).toFixed(1)}" x2="${W - pad.r}" y2="${y(0).toFixed(1)}"/>
      <text class="tick" x="${W - pad.r + 4}" y="${y(0).toFixed(1)}" dominant-baseline="middle">0%</text>
      <path class="ln bench" d="${p("bench")}"/>
      <path class="ln mine ${down ? "dn" : ""}" d="${p("ret")}"/>
      <text class="tick" x="${pad.l}" y="${H - 2}">${esc(series[0].date.slice(5))}</text>
      <text class="tick" x="${W - pad.r}" y="${H - 2}" text-anchor="end">${esc(last.date.slice(5))}</text>
    </svg>
    <div class="legend">
      <span class="k1 ${down ? "dn" : ""}"><i></i>自分</span>
      <span class="k2"><i></i>${esc(label)}</span>
      <span class="sp">${n}営業日</span>
    </div>
  </div>`;
}

/* ---------------- 銘柄行 ---------------- */

function rows(bk, tappable) {
  if (!bk.positions.length) {
    return `<p class="empty">保有はありません。全額現金で待機しています。</p>`;
  }
  return bk.positions.map((p) => `
    <div class="tr${tappable ? " tap" : ""}"${tappable ? ` data-tk="${esc(p.ticker)}" data-bk="${bk.key}"` : ""}>
      <span class="s"><b>${esc(p.ticker)}</b><small>${nf.format(p.shares)}株 · ${p.weight_pct.toFixed(1)}%</small></span>
      <span class="p">${money(bk.currency, p.value)}<small>${bk.currency}${nf1.format(p.price)}</small></span>
      <span class="chip ${cls(p.pnl_pct)}">${pct(p.pnl_pct)}</span>
    </div>`).join("") + `
    <div class="tr">
      <span class="s"><b>現金</b><small>${bk.cash_pct.toFixed(1)}%</small></span>
      <span class="p">${money(bk.currency, bk.cash)}</span>
      <span class="chip flat">—</span>
    </div>`;
}

/* ---------------- 概要 ---------------- */

function bookBlock(bk) {
  return `
  <div class="blk">
    <div class="blk-head">
      <span class="t">${esc(bk.name)}</span>
      <span class="s">${esc(bk.ccy_code)} · 買い枠 ${bk.buys_today}/${bk.max_buys}</span>
    </div>
    <div class="big">
      <span class="n">${money(bk.currency, bk.equity)}</span>
      <span class="c ${cls(bk.ret_pct)}-t">${pct(bk.ret_pct)}</span>
    </div>
    ${equityChart(DATA.series[bk.key], BENCH_LABEL[bk.bench] || bk.bench, bk.key)}
    <div class="grid">
      <div class="cell"><div class="k">${esc(benchName(bk.bench))}</div>
        <div class="v ${cls(bk.bench_pct)}-t">${pct(bk.bench_pct)}</div></div>
      <div class="cell"><div class="k">これとの差</div>
        <div class="v ${cls(bk.diff_pt)}-t">${ptv(bk.diff_pt)}</div></div>
      <div class="cell"><div class="k">現金比率</div><div class="v">${bk.cash_pct.toFixed(1)}%</div></div>
    </div>
  </div>
  <div class="sect">保有 ${bk.positions.length}銘柄 / ユニバース ${bk.universe.length}</div>
  ${rows(bk, false)}`;
}

/* ---------------- 保有一覧 ---------------- */

function holdingsView() {
  const books = ["us", "jp"].map(book);
  if (!books.reduce((n, b) => n + b.positions.length, 0)) {
    return `<p class="empty">まだ1銘柄も保有していません。全額現金で待機しています。</p>`;
  }
  return books.map((bk) => `
    <div class="sect">${esc(bk.name)} · ${bk.positions.length}銘柄</div>
    ${rows(bk, true)}`).join("");
}

/* ---------------- 個別銘柄 ---------------- */

const RANGES = [["1d", "1D"], ["1m", "1M"], ["1y", "1Y"]];

function reasonFor(tk) {
  const t = DATA.trades.find((x) => x.ticker === tk && x.status === "FILLED" && x.side === "BUY");
  return t ? { when: t.ts.slice(0, 16).replace("T", " "), why: t.reason } : null;
}

function detailView(tk, bkey) {
  const bk = book(bkey);
  const p = bk.positions.find((x) => x.ticker === tk);
  if (!p) return `<p class="empty">${esc(tk)} は保有していません。</p>`;

  const q = (PX && PX.quotes && PX.quotes[tk]) || {};
  const s = PX && PX.series && PX.series[tk] && PX.series[tk][RANGE];
  const c = bk.currency;
  const has = s && s.c && s.c.length;

  const fmtT = (v) => RANGE === "1d"
    ? new Date(v * 1000).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })
    : RANGE === "1y" ? String(v).slice(0, 7) : String(v).slice(5);

  const rangeChg = has ? (s.c[s.c.length - 1] / s.c[0] - 1) * 100 : null;
  const r = reasonFor(tk);

  return `
  <div class="dhead">
    <div class="tk">${esc(tk)}</div>
    <div class="nm">${esc(bk.name)} · ${esc(bk.ccy_code)}</div>
    <div class="dpx">
      <span class="n ${cls(q.chg_pct || 0)}-t">${c}${nf2.format(p.price)}</span>
      <span class="c ${cls(q.chg_pct || 0)}-t">${q.chg_pct != null
        ? `${pct(q.chg_pct)}（前日比）` : ""}</span>
    </div>
    <div class="dsub">保有 ${nf.format(p.shares)}株 · 簿価 ${c}${nf2.format(p.avg_cost)} · 評価 ${money(c, p.value)}</div>
  </div>

  <div class="ivs" id="rangebar">
    ${RANGES.map(([k, l]) => `<button data-r="${k}" class="${k === RANGE ? "on" : ""}">${l}</button>`).join("")}
    ${rangeChg != null ? `<span class="rchg ${cls(rangeChg)}-t">${pct(rangeChg)}</span>` : ""}
  </div>

  ${has ? candleChart(s, fmtT) : `<p class="empty">この期間の値動きをまだ取得できていません。市場が開くと入ります。</p>`}

  <div class="grid">
    <div class="cell"><div class="k">始値</div><div class="v">${q.open != null ? nf2.format(q.open) : "—"}</div></div>
    <div class="cell"><div class="k">高値</div><div class="v up-t">${q.high != null ? nf2.format(q.high) : "—"}</div></div>
    <div class="cell"><div class="k">安値</div><div class="v dn-t">${q.low != null ? nf2.format(q.low) : "—"}</div></div>
    <div class="cell"><div class="k">出来高</div><div class="v">${vol(q.volume)}</div></div>
    <div class="cell"><div class="k">52週高</div><div class="v">${q.w52h != null ? nf1.format(q.w52h) : "—"}</div></div>
    <div class="cell"><div class="k">52週安</div><div class="v">${q.w52l != null ? nf1.format(q.w52l) : "—"}</div></div>
    <div class="cell"><div class="k">評価損益</div><div class="v ${cls(p.pnl_pct)}-t">${pct(p.pnl_pct)}</div></div>
    <div class="cell"><div class="k">比率</div><div class="v">${p.weight_pct.toFixed(1)}%</div></div>
    <div class="cell"><div class="k">上限まで</div><div class="v">${Math.max(0, 25 - p.weight_pct).toFixed(1)}pt</div></div>
  </div>

  ${r ? `<div class="sect">買った理由</div>
    <div class="reason"><p class="rwhen">${esc(r.when)}</p><p class="rwhy">${esc(r.why)}</p></div>` : ""}`;
}

function paintDetail() {
  $("#detail").innerHTML = detailView(CURRENT.tk, CURRENT.bkey);
  const bar = $("#rangebar");
  if (bar) bar.onclick = (e) => {
    const b = e.target.closest("button");
    if (b) { RANGE = b.dataset.r; paintDetail(); }
  };
}

function openDetail(tk, bkey) {
  CURRENT = { tk, bkey };
  RANGE = "1d";
  showPanel("view-detail");
  paintDetail();
}

/* ---------------- 履歴 ---------------- */

function renderLog() {
  const list = DATA.trades.filter((t) => logFilter === "all" || t.status === logFilter);
  if (!list.length) { $("#ledger").innerHTML = `<p class="empty">該当する記録がありません。</p>`; return; }
  $("#ledger").innerHTML = list.map((t) => {
    const ok = t.status === "FILLED";
    return `
    <li class="${ok ? "ok" : "ng"}">
      <div class="f-r1">
        <span class="f-side ${esc(t.side)}">${esc(t.side)}</span>
        <span class="f-tk">${esc(t.ticker)}</span>
        <span class="f-qty">${nf.format(t.shares)}株${t.price ? ` @${nf1.format(t.price)}` : ""}</span>
        <span class="f-when">${esc(t.ts.slice(5, 16).replace("T", " "))}</span>
      </div>
      <p class="f-why ${ok ? "" : "ng"}">${esc((ok ? t.reason : t.error) || "—")}</p>
    </li>`;
  }).join("");
}

/* ---------------- 日報 ---------------- */

const reportCache = new Map();

async function showReport(date) {
  const body = $("#report-body");
  [...document.querySelectorAll("#daterail button")].forEach((b) =>
    b.classList.toggle("on", b.dataset.date === date));
  if (!date) { body.innerHTML = `<p class="empty">まだ日報がありません。最初の report セッションで書かれます。</p>`; return; }
  if (reportCache.has(date)) { body.innerHTML = reportCache.get(date); return; }
  body.innerHTML = `<p class="loading">読み込み中…</p>`;
  try {
    const r = await fetch(`data/reports/${date}.json`);
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    reportCache.set(date, j.html);
    body.innerHTML = j.html;
  } catch {
    body.innerHTML = `<p class="empty">${esc(date)} の日報を読み込めませんでした。オフラインで未取得かもしれません。</p>`;
  }
}

/* ---------------- 画面の切替 ---------------- */

const PANELS = ["view-overview", "view-holdings", "view-reports", "view-log", "view-detail"];

function showPanel(id) {
  PANELS.forEach((p) => { document.getElementById(p).hidden = p !== id; });
  window.scrollTo({ top: 0, behavior: "instant" });
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab) => {
    tab.onclick = () => {
      tabs.forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      showPanel(tab.getAttribute("aria-controls"));
    };
  });
  $("#back").onclick = () => document.getElementById("tab-holdings").click();

  $("#log-filters").onclick = (e) => {
    const b = e.target.closest("[data-filter]");
    if (!b) return;
    [...$("#log-filters").children].forEach((x) => x.classList.toggle("on", x === b));
    logFilter = b.dataset.filter;
    renderLog();
  };

  $("#holdings").onclick = (e) => {
    const row = e.target.closest(".tr.tap");
    if (row) openDetail(row.dataset.tk, row.dataset.bk);
  };
}

/* ---------------- 組み立て ---------------- */

function render() {
  $("#books").innerHTML = ["us", "jp"].map((b) => bookBlock(book(b))).join("");
  $("#holdings").innerHTML = holdingsView();

  const live = !!(PX && PX.updated_at);
  const stamp = (live ? PX.updated_at : DATA.generated_at).replace("T", " ").slice(0, 16);
  $("#updated").textContent = stamp;
  $("#freshness").textContent = live ? "LIVE" : (DATA.prices_ok ? "台帳" : "簿価");
  if (!live) $("#pulse").classList.add("stale");
  $("#stamp").textContent = `ledger ${DATA.generated_at}${live ? ` / prices ${PX.updated_at}` : ""}`;

  const rail = $("#daterail");
  rail.innerHTML = DATA.reports.map((d) => `<button data-date="${d}">${d.slice(5)}</button>`).join("");
  rail.onclick = (e) => { const b = e.target.closest("button"); if (b) showReport(b.dataset.date); };
  showReport(DATA.reports[0]);

  renderLog();
}

async function boot() {
  setupTabs();
  const get = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const [s, p] = await Promise.all([get("data/summary.json"), get("data/prices.json")]);
  if (!s) {
    $("#books").innerHTML =
      `<p class="empty">データを読み込めませんでした。まだ一度もセッションが走っていないか、オフラインで未取得です。</p>`;
    $("#updated").textContent = "データがありません";
    $("#pulse").classList.add("stale");
    return;
  }
  DATA = s; PX = p;
  render();
}

boot();

// 前面に戻ったら価格を取り直します（市場が動いている間に開き直したとき用）
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !DATA) return;
  const p = await fetch("data/prices.json", { cache: "reload" })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (p && (!PX || p.updated_at !== PX.updated_at)) {
    PX = p;
    render();
    if (CURRENT && !document.getElementById("view-detail").hidden) paintDetail();
  }
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));

  // 新しい Service Worker が主導権を取ったら1度だけ読み直します。
  // これが無いと、外殻を更新しても端末には古い画面が出たままになります。
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    location.reload();
  });
}
