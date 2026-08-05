/* 仮想運用記録 — 表示側。
   data/summary.json  … 台帳・日報・判断の履歴（セッションごとに更新）
   data/prices.json   … 現在値と値動き（市場が開いている間は15分ごとに更新）
   価格側があればそちらを優先して資産を計算し直す。 */

const $ = (s) => document.querySelector(s);
const nf = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const money = (c, v) => c + nf.format(v);
const pct = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
const ptv = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "pt";
// しきい値は表示の丸めと揃える。0.005 は "+0.01%" と表示されるので上げ扱い
const dir = (v) => (v >= 0.005 ? "up" : v <= -0.005 ? "down" : "flat");
// 変化ゼロで ▲ を出すと上がったように読めるので、横棒にする
const arrow = (v) => ({ up: "▲", down: "▼", flat: "—" }[dir(v)]);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// SPY は SPDR S&P 500 ETF。米国ブックは最初から S&P500 を相手にしている
const BENCH_LABEL = { "SPY": "S&P500", "1306.T": "TOPIX" };
const benchName = (t) => (BENCH_LABEL[t] ? `${BENCH_LABEL[t]}（${t}）` : t);

let DATA = null;   // summary.json
let PX = null;     // prices.json
let RANGE = "1d";
let CURRENT = null;

/* 台帳側と価格側を合成する。価格側のほうが新しいのでそちらを優先 */
function book(b) {
  const base = DATA.books[b];
  const live = PX && PX.books && PX.books[b];
  return live ? { ...base, ...live, key: b } : { ...base, key: b };
}

/* ---------------- 折れ線 ---------------- */

function linechart(values, opts = {}) {
  const { h = 132, labels = [], id = "c", zero = false } = opts;
  const n = values.length;
  if (!n) return `<p class="empty">${opts.emptyMsg || "データがありません。"}</p>`;

  const W = 340, pad = { l: 2, r: 36, t: 16, b: labels.length ? 18 : 8 };
  let lo = Math.min(...values), hi = Math.max(...values);
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const gap = (hi - lo) * 0.18; lo -= gap; hi += gap;

  const x = (i) => pad.l + (n === 1 ? (W - pad.l - pad.r) / 2 : (i * (W - pad.l - pad.r)) / (n - 1));
  const y = (v) => pad.t + ((hi - v) / (hi - lo)) * (h - pad.t - pad.b);
  const line = values.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
  const down = values[n - 1] < values[0];
  const base = (h - pad.b).toFixed(1);
  const area = `${line} L ${x(n - 1).toFixed(1)} ${base} L ${x(0).toFixed(1)} ${base} Z`;
  const len = Math.round((W - pad.l - pad.r) * 1.7);

  const zeroLine = zero
    ? `<line class="zero" x1="${pad.l}" y1="${y(0).toFixed(1)}" x2="${W - pad.r}" y2="${y(0).toFixed(1)}"/>
       <text class="tick" x="${W - pad.r + 5}" y="${y(0).toFixed(1)}" dominant-baseline="middle">0%</text>`
    : `<text class="tick" x="${W - pad.r + 5}" y="${y(values[n - 1]).toFixed(1)}" dominant-baseline="middle">${
        opts.lastLabel ?? ""}</text>`;

  const ticks = labels.length
    ? `<text class="tick" x="${pad.l}" y="${h - 4}">${esc(labels[0])}</text>
       <text class="tick" x="${W - pad.r}" y="${h - 4}" text-anchor="end">${esc(labels[1])}</text>` : "";

  return `
  <div class="chartwrap">
    <svg viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(opts.aria || "値動き")}">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--${down ? "down" : "up"})" stop-opacity=".26"/>
        <stop offset="100%" stop-color="var(--${down ? "down" : "up"})" stop-opacity="0"/>
      </linearGradient></defs>
      ${zeroLine}
      <path class="fade-in" d="${area}" fill="url(#${id})"/>
      ${opts.benchPath || ""}
      <path class="ln mine ${down ? "dn" : ""} draw" style="--len:${len}" d="${line}"/>
      ${ticks}
    </svg>
  </div>`;
}

/* 概要の資産推移。自分とベンチの2本 */
function equityChart(series, benchLabel, key) {
  if (!series || !series.length) {
    return `<p class="empty">まだ日次の記録がありません。最初の日報セッションで記録が始まります。</p>`;
  }
  const W = 340, H = 132, pad = { l: 2, r: 36, t: 16, b: 18 };
  const vals = series.flatMap((d) => [d.ret, d.bench]).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { const m = (hi + lo) / 2; lo = m - .5; hi = m + .5; }
  const gap = (hi - lo) * .18; lo -= gap; hi += gap;
  const n = series.length;
  const x = (i) => pad.l + (n === 1 ? (W - pad.l - pad.r) / 2 : (i * (W - pad.l - pad.r)) / (n - 1));
  const y = (v) => pad.t + ((hi - v) / (hi - lo)) * (H - pad.t - pad.b);
  const p = (k) => series.map((d, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(d[k]).toFixed(1)).join(" ");
  const last = series[n - 1], down = last.ret < 0;
  const base = (H - pad.b).toFixed(1);
  const len = Math.round((W - pad.l - pad.r) * 1.7);

  return `
  <div class="chartwrap">
    <svg viewBox="0 0 ${W} ${H}" role="img"
         aria-label="資産推移。自分 ${pct(last.ret)}、ベンチマーク ${pct(last.bench)}">
      <defs><linearGradient id="g${key}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--${down ? "down" : "up"})" stop-opacity=".26"/>
        <stop offset="100%" stop-color="var(--${down ? "down" : "up"})" stop-opacity="0"/>
      </linearGradient></defs>
      <line class="zero" x1="${pad.l}" y1="${y(0).toFixed(1)}" x2="${W - pad.r}" y2="${y(0).toFixed(1)}"/>
      <text class="tick" x="${W - pad.r + 4}" y="${y(0).toFixed(1)}" dominant-baseline="middle">0%</text>
      <path class="fade-in" d="${p("ret")} L ${x(n - 1).toFixed(1)} ${base} L ${x(0).toFixed(1)} ${base} Z"
            fill="url(#g${key})"/>
      <path class="ln bench draw" style="--len:${len}" d="${p("bench")}"/>
      <path class="ln mine ${down ? "dn" : ""} draw" style="--len:${len}" d="${p("ret")}"/>
      <text class="tick" x="${pad.l}" y="${H - 4}">${esc(series[0].date.slice(5))}</text>
      <text class="tick" x="${W - pad.r}" y="${H - 4}" text-anchor="end">${esc(last.date.slice(5))}</text>
    </svg>
    <div class="legend">
      <span class="k1 ${down ? "dn" : ""}"><i></i>自分</span>
      <span class="k2"><i></i>${esc(benchLabel)}</span>
      <span class="spacer">${series.length}営業日</span>
    </div>
  </div>`;
}

/* ---------------- 概要 ---------------- */

function posRows(bk, clickable) {
  if (!bk.positions.length) return `<p class="empty">保有はありません。全額現金で待機しています。</p>`;
  return bk.positions.map((p) => {
    // バー満タン = 1銘柄25%上限。制約にどれだけ近いかを目で見せる
    const fill = Math.min(100, (p.weight_pct / 25) * 100).toFixed(1);
    const day = p.day_pct != null
      ? `<span class="${dir(p.day_pct)}-t">本日 ${pct(p.day_pct)}</span>` : "";
    return `
    <div class="pos${clickable ? " tapable" : ""}"${clickable ? ` data-tk="${esc(p.ticker)}" data-bk="${bk.key}"` : ""}>
      <div class="pos-r1">
        <span class="pos-tk">${esc(p.ticker)}</span>
        <span class="pos-mv">${money(bk.currency, p.value)}</span>
      </div>
      <div class="bar"><i style="width:${fill}%"></i></div>
      <div class="pos-r2">
        <span>${nf.format(p.shares)}株 · ${bk.currency}${nf1.format(p.price)}${day ? " · " + day : ""}</span>
        <span class="${dir(p.pnl_pct)}-t">${pct(p.pnl_pct)} · ${p.weight_pct.toFixed(1)}%</span>
      </div>
    </div>`;
  }).join("");
}

function bookCard(bk) {
  return `
  <section class="card">
    <div class="card-head">
      <h2>${esc(bk.name)}</h2>
      <span class="tag">${esc(bk.ccy_code)}</span>
    </div>
    <div class="hero">
      <span class="num">${money(bk.currency, bk.equity)}</span>
      <span class="pill ${dir(bk.ret_pct)}">${arrow(bk.ret_pct)} ${pct(bk.ret_pct).replace(/^[+−]/, "")}</span>
    </div>
    ${equityChart(DATA.series[bk.key], BENCH_LABEL[bk.bench] || bk.bench, bk.key)}
    <dl class="grid2">
      <div class="stat"><dt>${esc(benchName(bk.bench))}</dt><dd class="${dir(bk.bench_pct)}-t">${pct(bk.bench_pct)}</dd></div>
      <div class="stat"><dt>これとの差</dt><dd class="${dir(bk.diff_pt)}-t">${ptv(bk.diff_pt)}</dd></div>
    </dl>
    <div class="meterline">
      <span>現金 <b>${money(bk.currency, bk.cash)}</b> · ${bk.cash_pct.toFixed(1)}%</span>
      <span>買い枠 <b>${bk.buys_today}/${bk.max_buys}</b></span>
    </div>
    <p class="sec-label">保有 ${bk.positions.length}銘柄 / ユニバース ${bk.universe.length}</p>
    ${posRows(bk, false)}
  </section>`;
}

/* ---------------- 保有一覧 ---------------- */

function holdingsView() {
  const books = ["us", "jp"].map(book);
  const total = books.reduce((n, b) => n + b.positions.length, 0);
  if (!total) {
    return `<p class="empty">まだ1銘柄も保有していません。全額現金で待機しています。</p>`;
  }
  return books.map((bk) => `
    <section class="card">
      <div class="card-head">
        <h2>${esc(bk.name)}</h2>
        <span class="tag">${bk.positions.length}銘柄 · 現金 ${bk.cash_pct.toFixed(1)}%</span>
      </div>
      <p class="sec-label">バーが満タンで1銘柄25%の上限です</p>
      ${posRows(bk, true)}
    </section>`).join("");
}

/* ---------------- 個別銘柄 ---------------- */

const RANGES = [["1d", "1日"], ["1m", "1ヶ月"], ["1y", "1年"]];

function reasonFor(tk) {
  const t = DATA.trades.find((x) => x.ticker === tk && x.status === "FILLED" && x.side === "BUY");
  return t ? { when: t.ts.slice(0, 16).replace("T", " "), why: t.reason } : null;
}

function detailView(tk, bkey) {
  const bk = book(bkey);
  const p = bk.positions.find((x) => x.ticker === tk);
  const q = PX && PX.quotes && PX.quotes[tk];
  const s = PX && PX.series && PX.series[tk];
  const c = bk.currency;

  if (!p) return `<p class="empty">${esc(tk)} は保有していません。</p>`;

  const ser = s && s[RANGE] && s[RANGE].v.length ? s[RANGE] : null;
  let chart = `<p class="empty">この期間の値動きをまだ取得できていません。市場が開くと入ります。</p>`;
  let rangeChg = null;
  if (ser) {
    rangeChg = (ser.v[ser.v.length - 1] / ser.v[0] - 1) * 100;
    // 1年だと両端とも同じ月日になりやすいので、年月まで出す
    const fmt = (x) => RANGE === "1d"
      ? new Date(x * 1000).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })
      : RANGE === "1y" ? String(x).slice(0, 7) : String(x).slice(5);
    chart = linechart(ser.v, {
      h: 150, id: "d" + tk.replace(/\W/g, ""),
      labels: [fmt(ser.t[0]), fmt(ser.t[ser.t.length - 1])],
      lastLabel: nf1.format(ser.v[ser.v.length - 1]),
      aria: `${tk} の値動き`,
    });
  }

  const r = reasonFor(tk);

  return `
  <div class="dhead">
    <div>
      <h2 class="dtk">${esc(tk)}</h2>
      <p class="dbk">${esc(bk.name)}</p>
    </div>
    <div class="dpx">
      <div class="num2">${c}${nf1.format(p.price)}</div>
      ${q ? `<span class="pill ${dir(q.chg_pct)}">${arrow(q.chg_pct)} ${pct(q.chg_pct).replace(/^[+−]/, "")}</span>` : ""}
    </div>
  </div>

  <div class="rangebar">
    ${RANGES.map(([k, label]) =>
      `<button data-r="${k}" class="${k === RANGE ? "on" : ""}">${label}</button>`).join("")}
    ${rangeChg != null ? `<span class="rchg ${dir(rangeChg)}-t">${pct(rangeChg)}</span>` : ""}
  </div>

  ${chart}

  <dl class="grid2" style="margin-top:1rem">
    <div class="stat"><dt>評価額</dt><dd>${money(c, p.value)}</dd></div>
    <div class="stat"><dt>損益</dt><dd class="${dir(p.pnl_pct)}-t">${pct(p.pnl_pct)}</dd></div>
    <div class="stat"><dt>保有株数</dt><dd>${nf.format(p.shares)}</dd></div>
    <div class="stat"><dt>簿価</dt><dd>${c}${nf1.format(p.avg_cost)}</dd></div>
    <div class="stat"><dt>比率</dt><dd>${p.weight_pct.toFixed(1)}%</dd></div>
    <div class="stat"><dt>上限まで</dt><dd>${Math.max(0, 25 - p.weight_pct).toFixed(1)}pt</dd></div>
  </dl>

  ${r ? `
    <p class="sec-label">買った理由</p>
    <div class="reason">
      <p class="rwhen">${esc(r.when)}</p>
      <p class="rwhy">${esc(r.why)}</p>
    </div>` : ""}`;
}

function openDetail(tk, bkey) {
  CURRENT = { tk, bkey };
  RANGE = "1d";
  showPanel("view-detail");
  paintDetail();
}

function paintDetail() {
  $("#detail").innerHTML = detailView(CURRENT.tk, CURRENT.bkey);
  $("#detail").querySelectorAll(".rangebar button").forEach((b) => {
    b.onclick = () => { RANGE = b.dataset.r; paintDetail(); };
  });
}

/* ---------------- 履歴 ---------------- */

let logFilter = "all";

function renderLog() {
  const list = DATA.trades.filter((t) => logFilter === "all" || t.status === logFilter);
  if (!list.length) { $("#ledger").innerHTML = `<p class="empty">該当する記録がありません。</p>`; return; }
  $("#ledger").innerHTML = list.map((t, i) => {
    const ok = t.status === "FILLED";
    const when = t.ts.slice(5, 16).replace("T", " ");
    const price = t.price ? ` @${nf1.format(t.price)}` : "";
    return `
    <li class="${ok ? "ok" : "ng"}" style="animation-delay:${Math.min(i, 8) * 40}ms">
      <div class="f-r1">
        <span class="f-side ${esc(t.side)}">${esc(t.side)}</span>
        <span class="f-tk">${esc(t.ticker)}</span>
        <span class="f-qty">${nf.format(t.shares)}株${esc(price)}</span>
        <span class="f-when">${esc(when)}</span>
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
  // 個別銘柄でもタブは出したままにする。別のタブへ直接移れるほうが速い
  window.scrollTo({ top: 0, behavior: "instant" });
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const glider = $("#glider");
  tabs.forEach((tab, i) => {
    tab.onclick = () => {
      tabs.forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      glider.style.transform = `translateX(calc(${i * 100}% + ${i * 0.15}rem))`;
      showPanel(tab.getAttribute("aria-controls"));
    };
  });

  $("#back").onclick = () => {
    document.getElementById("tab-holdings").click();
  };

  $("#log-filters").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    [...$("#log-filters").children].forEach((x) => x.classList.toggle("on", x === b));
    logFilter = b.dataset.filter;
    renderLog();
  };

  $("#holdings").onclick = (e) => {
    const row = e.target.closest(".pos.tapable");
    if (row) openDetail(row.dataset.tk, row.dataset.bk);
  };
}

/* ---------------- 組み立て ---------------- */

function render() {
  $("#books").innerHTML = ["us", "jp"].map((b) => bookCard(book(b))).join("");
  $("#holdings").innerHTML = holdingsView();

  const stamp = (PX && PX.updated_at) || DATA.generated_at;
  const live = !!(PX && PX.updated_at);
  $("#updated").textContent =
    `${live ? "価格" : "台帳"} ${stamp.replace("T", " ").slice(0, 16)} · 開始 ${DATA.start_date}`;
  $("#stamp").textContent = `ledger ${DATA.generated_at}${live ? ` / prices ${PX.updated_at}` : ""}`;
  $("#freshness").textContent = live ? "LIVE" : (DATA.prices_ok ? "台帳のみ" : "簿価表示");
  if (!live) $("#pulse").classList.add("stale");

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

// 前面に戻ったら価格を取り直す（市場が動いている間に開き直したとき用）
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

  // 新しい Service Worker が主導権を取ったら1度だけ読み直す。
  // これが無いと、外殻を更新しても端末には古い画面が出たままになる。
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    location.reload();
  });
}
