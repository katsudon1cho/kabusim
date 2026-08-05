/* 仮想運用記録 — 表示側。build_site.py が書いた data/summary.json だけを読む。 */

const $ = (sel) => document.querySelector(sel);

const nf = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const money = (cur, v) => cur + nf.format(v);
const pct = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";
const pt = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "pt";
const cls = (v) => (v > 0.0001 ? "pos" : v < -0.0001 ? "neg" : "flat");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let DATA = null;

/* ---------------- 図: 資産推移 ---------------- */

function chart(series, benchName) {
  if (!series || series.length === 0) {
    return `<p class="empty">まだ日次記録がない。最初の日報セッションで記録が始まる。</p>`;
  }

  const W = 320, H = 110;
  const pad = { l: 2, r: 30, t: 10, b: 16 };
  const vals = series.flatMap((d) => [d.ret, d.bench]).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { const m = (hi + lo) / 2; lo = m - 0.5; hi = m + 0.5; }
  const padY = (hi - lo) * 0.15;
  lo -= padY; hi += padY;

  const n = series.length;
  const x = (i) => pad.l + (n === 1 ? 0 : (i * (W - pad.l - pad.r)) / (n - 1));
  const y = (v) => pad.t + ((hi - v) / (hi - lo)) * (H - pad.t - pad.b);

  const path = (key) =>
    series.map((d, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(d[key]).toFixed(1)).join(" ");

  const last = series[n - 1];
  const zeroY = y(0).toFixed(1);

  // 線を引く長さの目安。厳密でなくてよい（アニメーションの尺に使うだけ）
  const len = Math.round((W - pad.l - pad.r) * 1.6);

  const dot = n === 1
    ? `<circle cx="${x(0)}" cy="${y(last.ret)}" r="2.4" fill="var(--shu)"/>
       <circle cx="${x(0)}" cy="${y(last.bench)}" r="2" fill="var(--ink-mute)"/>`
    : "";

  return `
  <figure>
    <svg viewBox="0 0 ${W} ${H}" role="img"
         aria-label="資産推移。自分 ${pct(last.ret)}、ベンチマーク ${pct(last.bench)}">
      <line class="spark-zero" x1="${pad.l}" y1="${zeroY}" x2="${W - pad.r}" y2="${zeroY}"/>
      <text class="spark-label" x="${W - pad.r + 4}" y="${zeroY}" dominant-baseline="middle">0</text>
      <path class="spark-line bench draw" style="--len:${len}" d="${path("bench")}"/>
      <path class="spark-line mine draw"  style="--len:${len}" d="${path("ret")}"/>
      ${dot}
      <text class="spark-label" x="${pad.l}" y="${H - 4}">${esc(series[0].date.slice(5))}</text>
      <text class="spark-label" x="${W - pad.r}" y="${H - 4}" text-anchor="end">${esc(last.date.slice(5))}</text>
    </svg>
    <figcaption>
      <span class="legend">
        <span class="k-mine">自分</span>
        <span class="k-bench">${esc(benchName)}</span>
      </span>
      <span>${series.length}営業日</span>
    </figcaption>
  </figure>`;
}

/* ---------------- 台帳カード ---------------- */

function holdings(bk) {
  if (!bk.positions.length) {
    return `<p class="empty">保有なし。全額現金。</p>`;
  }
  const rows = bk.positions.map((p) => `
    <tr>
      <td class="tk">${esc(p.ticker)}</td>
      <td>${nf.format(p.shares)}</td>
      <td>${bk.currency}${nf2.format(p.avg_cost)}</td>
      <td>${bk.currency}${nf2.format(p.price)}</td>
      <td class="${cls(p.pnl_pct)}">${pct(p.pnl_pct)}</td>
      <td class="w">${p.weight_pct.toFixed(1)}%</td>
    </tr>`).join("");

  return `
  <table class="holdings">
    <thead><tr>
      <th>銘柄</th><th>株数</th><th>簿価</th><th>現在</th><th>損益</th><th>比率</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function bookCard(bk) {
  return `
  <section class="book">
    <div class="book-head">
      <h2>${esc(bk.name)}</h2>
      <span class="ccy">${esc(bk.ccy_code)}</span>
    </div>

    <div class="equity">
      <span class="amount">${money(bk.currency, bk.equity)}</span>
      <span class="delta ${cls(bk.ret_pct)}">${pct(bk.ret_pct)}</span>
    </div>

    <dl class="versus">
      <div>
        <dt>ベンチ ${esc(bk.bench)}</dt>
        <dd class="${cls(bk.bench_pct)}">${pct(bk.bench_pct)}</dd>
      </div>
      <div>
        <dt>差</dt>
        <dd class="${cls(bk.diff_pt)}">${pt(bk.diff_pt)}</dd>
      </div>
    </dl>

    ${chart(DATA.series[bk.key], bk.bench)}

    <p class="meters">
      <span>現金 <b>${money(bk.currency, bk.cash)}</b>（${bk.cash_pct.toFixed(1)}%）</span>
      <span>本日の買い <b>${bk.buys_today}/${bk.max_buys}</b>件</span>
      <span>ユニバース <b>${bk.universe.length}</b>銘柄</span>
    </p>

    <h3 class="sub">保有</h3>
    ${holdings(bk)}
  </section>`;
}

/* ---------------- 履歴 ---------------- */

let logFilter = "all";

function renderLog() {
  const list = DATA.trades.filter((t) => logFilter === "all" || t.status === logFilter);
  if (!list.length) {
    $("#ledger").innerHTML = `<p class="empty">該当する記録がない。</p>`;
    return;
  }
  $("#ledger").innerHTML = list.map((t) => {
    const ok = t.status === "FILLED";
    const when = t.ts.slice(5, 16).replace("T", " ");
    const price = t.price ? ` @${nf2.format(t.price)}` : "";
    const why = ok ? t.reason : t.error;
    return `
    <li>
      <span class="mark ${ok ? "ok" : "ng"}">${ok ? "✓" : "✗"}</span>
      <span class="entry-head">
        <span class="side">${esc(t.side)}</span>
        <span class="tk">${esc(t.ticker)}</span>
        <span>${nf.format(t.shares)}株${esc(price)}</span>
        <span class="when">${esc(when)}</span>
      </span>
      <p class="entry-why ${ok ? "" : "rejected"}">${esc(why || "—")}</p>
    </li>`;
  }).join("");
}

/* ---------------- 日報 ---------------- */

const reportCache = new Map();

async function showReport(date) {
  const body = $("#report-body");
  if (!date) {
    body.innerHTML = `<p class="empty">まだ日報がない。最初の report セッションで書かれる。</p>`;
    return;
  }
  if (reportCache.has(date)) {
    body.innerHTML = reportCache.get(date);
    return;
  }
  body.innerHTML = `<p class="loading">読み込み中…</p>`;
  try {
    const r = await fetch(`data/reports/${date}.json`);
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    reportCache.set(date, j.html);
    body.innerHTML = j.html;
  } catch {
    body.innerHTML = `<p class="empty">${esc(date)} の日報を読めなかった。オフラインで未取得かもしれない。</p>`;
  }
}

/* ---------------- 組み立て ---------------- */

function render() {
  const books = ["us", "jp"].map((k) => ({ ...DATA.books[k], key: k }));
  $("#books").innerHTML = books.map(bookCard).join("");

  const stale = DATA.prices_ok ? "" : "  ／ 価格取得に失敗したため簿価で表示";
  $("#colophon").textContent =
    `更新 ${DATA.generated_at.replace("T", " ").slice(0, 16)} JST　開始 ${DATA.start_date}${stale}`;
  $("#stamp").textContent = `generated ${DATA.generated_at}`;

  const sel = $("#report-date");
  sel.innerHTML = DATA.reports.map((d) => `<option value="${d}">${d}</option>`).join("");
  sel.onchange = () => showReport(sel.value);
  showReport(DATA.reports[0]);

  renderLog();
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab) => {
    tab.onclick = () => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
  });

  $("#log-filters").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    [...$("#log-filters").children].forEach((x) => x.classList.toggle("on", x === b));
    logFilter = b.dataset.filter;
    renderLog();
  };
}

async function boot() {
  setupTabs();
  try {
    const r = await fetch("data/summary.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    DATA = await r.json();
    render();
  } catch (e) {
    $("#books").innerHTML =
      `<p class="empty">データを読めなかった。まだ一度もセッションが走っていないか、オフラインで未取得。</p>`;
    $("#colophon").textContent = "データなし";
  }
}

boot();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
