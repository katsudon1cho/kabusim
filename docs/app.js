/* 仮想運用記録 — 表示側。build_site.py が書いた data/summary.json だけを読む。 */

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

let DATA = null;

/* ---------------- チャート ---------------- */

function chart(series, benchName, key) {
  if (!series || !series.length) {
    return `<p class="empty">まだ日次記録がない。最初の日報セッションで記録が始まる。</p>`;
  }

  const W = 340, H = 132, pad = { l: 2, r: 36, t: 16, b: 18 };
  const vals = series.flatMap((d) => [d.ret, d.bench]).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { const m = (hi + lo) / 2; lo = m - 0.5; hi = m + 0.5; }
  const gap = (hi - lo) * 0.18; lo -= gap; hi += gap;

  const n = series.length;
  const x = (i) => pad.l + (n === 1 ? (W - pad.l - pad.r) / 2 : (i * (W - pad.l - pad.r)) / (n - 1));
  const y = (v) => pad.t + ((hi - v) / (hi - lo)) * (H - pad.t - pad.b);
  const line = (k) => series.map((d, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(d[k]).toFixed(1)).join(" ");

  const last = series[n - 1];
  const down = last.ret < 0;
  const base = (H - pad.b).toFixed(1);
  const area = `${line("ret")} L ${x(n - 1).toFixed(1)} ${base} L ${x(0).toFixed(1)} ${base} Z`;
  const len = Math.round((W - pad.l - pad.r) * 1.7);
  const gid = "g" + key;

  const dot = n === 1
    ? `<circle cx="${x(0)}" cy="${y(last.ret)}" r="3" fill="var(--${down ? "down" : "up"})"/>` : "";

  return `
  <div class="chartwrap">
    <svg viewBox="0 0 ${W} ${H}" role="img"
         aria-label="資産推移。自分 ${pct(last.ret)}、ベンチマーク ${pct(last.bench)}">
      <defs>
        <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stop-color="var(--${down ? "down" : "up"})" stop-opacity=".26"/>
          <stop offset="100%" stop-color="var(--${down ? "down" : "up"})" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <line class="zero" x1="${pad.l}" y1="${y(0).toFixed(1)}" x2="${W - pad.r}" y2="${y(0).toFixed(1)}"/>
      <text class="tick" x="${W - pad.r + 5}" y="${y(0).toFixed(1)}" dominant-baseline="middle">0%</text>
      <path class="fade-in" d="${area}" fill="url(#${gid})"/>
      <path class="ln bench draw" style="--len:${len}" d="${line("bench")}"/>
      <path class="ln mine ${down ? "dn" : ""} draw" style="--len:${len}" d="${line("ret")}"/>
      ${dot}
      <text class="tick" x="${pad.l}" y="${H - 4}">${esc(series[0].date.slice(5))}</text>
      <text class="tick" x="${W - pad.r}" y="${H - 4}" text-anchor="end">${esc(last.date.slice(5))}</text>
    </svg>
    <div class="legend">
      <span class="k1 ${down ? "dn" : ""}"><i></i>自分</span>
      <span class="k2"><i></i>${esc(benchName)}</span>
      <span class="spacer">${series.length}営業日</span>
    </div>
  </div>`;
}

/* ---------------- 保有 ---------------- */

function holdings(bk) {
  if (!bk.positions.length) {
    return `<p class="empty">保有なし。全額現金で待機している。</p>`;
  }
  return bk.positions.map((p) => {
    // バー満タン = 1銘柄25%上限。制約にどれだけ近いかを目で見せる
    const fill = Math.min(100, (p.weight_pct / 25) * 100).toFixed(1);
    return `
    <div class="pos">
      <div class="pos-r1">
        <span class="pos-tk">${esc(p.ticker)}</span>
        <span class="pos-mv">${money(bk.currency, p.value)}</span>
      </div>
      <div class="bar"><i style="width:${fill}%"></i></div>
      <div class="pos-r2">
        <span>${nf.format(p.shares)}株 · 簿価 ${bk.currency}${nf1.format(p.avg_cost)} → ${bk.currency}${nf1.format(p.price)}</span>
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

    ${chart(DATA.series[bk.key], bk.bench, bk.key)}

    <dl class="grid2">
      <div class="stat">
        <dt>${esc(bk.bench)}</dt>
        <dd class="${dir(bk.bench_pct)}-t">${pct(bk.bench_pct)}</dd>
      </div>
      <div class="stat">
        <dt>ベンチとの差</dt>
        <dd class="${dir(bk.diff_pt)}-t">${ptv(bk.diff_pt)}</dd>
      </div>
    </dl>

    <div class="meterline">
      <span>現金 <b>${money(bk.currency, bk.cash)}</b> · ${bk.cash_pct.toFixed(1)}%</span>
      <span>買い枠 <b>${bk.buys_today}/${bk.max_buys}</b></span>
    </div>

    <p class="sec-label">保有 ${bk.positions.length}銘柄 / ユニバース ${bk.universe.length}</p>
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

  if (!date) {
    body.innerHTML = `<p class="empty">まだ日報がない。最初の report セッションで書かれる。</p>`;
    return;
  }
  if (reportCache.has(date)) { body.innerHTML = reportCache.get(date); return; }

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

  $("#updated").textContent = `更新 ${DATA.generated_at.replace("T", " ").slice(0, 16)} · 開始 ${DATA.start_date}`;
  $("#stamp").textContent = `generated ${DATA.generated_at}`;

  const fresh = DATA.prices_ok;
  $("#freshness").textContent = fresh ? "LIVE" : "簿価表示";
  if (!fresh) $("#pulse").classList.add("stale");

  const rail = $("#daterail");
  rail.innerHTML = DATA.reports.map((d) =>
    `<button data-date="${d}">${d.slice(5)}</button>`).join("");
  rail.onclick = (e) => {
    const b = e.target.closest("button");
    if (b) showReport(b.dataset.date);
  };
  showReport(DATA.reports[0]);

  renderLog();
}

function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const glider = $("#glider");
  tabs.forEach((tab, i) => {
    tab.onclick = () => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      glider.style.transform = `translateX(calc(${i * 100}% + ${i * 0.15}rem))`;
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
  } catch {
    $("#books").innerHTML =
      `<p class="empty">データを読めなかった。まだ一度もセッションが走っていないか、オフラインで未取得。</p>`;
    $("#updated").textContent = "データなし";
    $("#pulse").classList.add("stale");
  }
}

boot();

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
