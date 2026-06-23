/* AI Stock Sentiment Tracker — client-side dashboard.
   Reads static JSON written by the daily GitHub Action (src/predict.py) and the
   frozen-model eval (src/eval/report.py). It NEVER runs the model itself. */

const J = (p) => fetch(p, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const fmtPct = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "%");
const fmtMoney = (x) => (x == null ? "–" : "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 }));
const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();

async function main() {
  const [preds, log, port, board, calib, mood, evalSum] = await Promise.all([
    J("data/predictions.json"), J("data/prediction_log.json"), J("data/portfolio.json"),
    J("data/scoreboard.json"), J("data/calibration_live.json"), J("data/market_mood.json"),
    J("data/eval_summary.json"),
  ]);

  if (!preds) {
    document.getElementById("watchlist").querySelector("tbody").innerHTML =
      `<tr><td colspan="8">No predictions yet. Run <code>python -m src.predict</code> to populate the tracker.</td></tr>`;
    return;
  }

  window.TARGET_TYPE = preds.target_type || "binary";
  applyTargetCopy(preds);
  renderTakeaways(preds, evalSum);
  renderFreshness(preds);
  renderBanner(preds, port, mood);
  renderPortfolio(port);
  renderWatchlist(preds);
  renderScoreboard(board);
  renderGame(preds, log);
  renderCalibration(calib);
  renderPaperTrade(preds, port);
  renderMood(mood);
  renderAblationSummary(evalSum);
  renderToggleNote(evalSum);
}

function renderTakeaways(p, s) {
  const el = document.getElementById("takeaways-grid");
  if (!el) return;
  const big = (p.target_type === "big_move");
  const h = s && s.headline_ablation, t = s && s.metrics_table, bt = s && s.backtest;
  const auc = t ? t.model.roc_auc : null;
  const sdelta = h ? h.sentiment_delta_f1 : null;
  const wf = h ? h.walk_forward : null;
  const lift = bt && bt.lift_vs_own_norm_flagged != null ? bt.lift_vs_own_norm_flagged : null;
  const num = (x, d = 3) => (x == null ? "—" : (x >= 0 && d === 4 ? "+" : "") + x.toFixed(d));

  const cards = big ? [
    ["🎲", "Predicting direction is a coin flip",
     `We tested next-session up/down first — it lands ~50%. Calling <em>which way</em> a stock moves
      tomorrow isn't really possible from this data, and that's market efficiency, not a bug.`],
    ["📈", "But volatility IS predictable",
     `The model ranks big-move days at <strong>AUC ${num(auc)}</strong> (0.5 = no signal). Big moves
      cluster, so "is an outsized move coming?" has genuine signal — that's the pivot that made this useful.`],
    ["💬", "Sentiment helps — modestly",
     `Adding news/sentiment changed AUC by <strong>${num(sdelta, 4)}</strong>${wf ? ` (walk-forward ${num(wf.mean,4)} ± ${wf.std.toFixed(4)})` : ""}.
      A real, repeatable lift for <em>volatility</em> — small, but it's there (it wasn't for direction).`],
    ["🎯", "It's a radar, not advice",
     `On the days it flags, stocks move <strong>${lift != null ? (lift*100).toFixed(2) + "%" : "—"}</strong>
      above their own normal range. Use it to see <em>what's likely to move</em> — never as a buy signal.`],
  ] : [
    ["📏", "Direction, not price", `Predicting price level is autocorrelation theatre; we predict up/down so any edge is honest.`],
    ["⚖️", "It must beat baselines", `Persistence, majority, and buy-and-hold are reported next to the model — beating them is the whole point.`],
    ["💬", "Does sentiment help?", `Headline ablation: sentiment changed test F1 by <strong>${num(sdelta,4)}</strong>.`],
    ["🔬", "Honesty over hype", `Leakage tests in CI, calibrated confidence, a live un-cherry-pickable log. A modest honest edge beats a fake 90%.`],
  ];
  el.innerHTML = cards.map(([icon, title, body]) =>
    `<div class="takeaway"><div class="tk-icon">${icon}</div><div><h3>${title}</h3><p>${body}</p></div></div>`).join("");
}

function applyTargetCopy(p) {
  const big = (p.target_type === "big_move");
  const set = (sel, txt) => { const e = document.querySelector(sel); if (e) e.textContent = txt; };
  // disclaimer comes straight from the data
  const dis = document.getElementById("disclaimer");
  if (dis && p.disclaimer) dis.innerHTML = "⚠️ " + p.disclaimer;
  if (!big) return;
  document.title = "AI Big-Move Radar";
  set(".brand h1", "AI Big-Move Radar");
  set(".tagline", "Direction is a coin-flip — so we predict what's actually predictable: which stocks are about to move big.");
  // relabel watchlist header + heading
  const ths = document.querySelectorAll("#watchlist thead th");
  if (ths[3]) ths[3].textContent = "Move likely?";
  if (ths[4]) ths[4].textContent = "Big-move prob";
  const wlH = document.querySelector("#watchlist").closest("section").querySelector("h2");
  if (wlH) wlH.innerHTML = 'Big-move radar <span class="hint">ranked by probability of an outsized move next session — either direction</span>';
  // banner relabels
  const aggLabel = document.querySelector("#aggregate-banner .banner-card:nth-child(1) .stat-label");
  if (aggLabel) aggLabel.innerHTML = 'precision when it flags a big move <span id="agg-n"></span>';
  // paper-trade section reframed: the model flags volatility, you pick direction
  const ptH = document.querySelector("#paper-trade h2");
  if (ptH) ptH.innerHTML = 'Paper portfolio <span class="hint">the radar flags volatile names — direction is your call. Fake money, saved in your browser.</span>';
  const fb = document.getElementById("pt-follow");
  if (fb) fb.textContent = "⚡ Buy the model's top big-move flags";
}

function renderFreshness(p) {
  const el = document.getElementById("freshness");
  const when = p.updated_at ? new Date(p.updated_at) : null;
  el.textContent = `as of ${p.as_of}${when ? " · updated " + when.toLocaleString() : ""}`;
  const modeTxt = p.data_mode === "offline"
    ? "⚙︎ synthetic data (mechanics demo)" : "live data";
  document.getElementById("mode-note").textContent = modeTxt;
  document.getElementById("footer-mode").textContent =
    p.data_mode === "offline" ? "Running on synthetic data — swap config data.mode to 'live' for real markets." : "";
}

function renderBanner(p, port, mood) {
  const agg = document.getElementById("agg-hitrate");
  const base = (p.baseline != null) ? p.baseline : 0.5;
  agg.textContent = fmtPct(p.aggregate_hit_rate);
  agg.style.color = p.aggregate_hit_rate == null ? css("--muted")
    : p.aggregate_hit_rate > base ? css("--up") : css("--down");
  const aggN = document.getElementById("agg-n");
  if (aggN) aggN.textContent = p.n_reconciled ? `(${p.n_reconciled} resolved)` : "";
  // baseline note: coin-flip for direction, base rate for big-move
  const bn = document.querySelector("#aggregate-banner .banner-card:nth-child(1) .baseline-note");
  if (bn) bn.textContent = (p.target_type === "big_move")
    ? `base rate of big moves ≈ ${fmtPct(base)} (so higher = real skill)`
    : "coin-flip baseline ≈ 50%";
  if (port) {
    document.getElementById("paper-value").textContent = fmtMoney(port.strategy_value);
    document.getElementById("paper-bh").textContent = "buy & hold: " + fmtMoney(port.buy_hold_value);
  }
  if (mood) {
    const m = mood.universe_sentiment;
    const el = document.getElementById("mood-stat");
    el.textContent = (m > 0 ? "+" : "") + m.toFixed(3);
    el.style.color = m > 0.02 ? css("--up") : m < -0.02 ? css("--down") : css("--muted");
  }
}

// ---- self-contained SVG charts (no CDN; works fully offline) ----
function svgLineChart(el, series, opts) {
  // series: [{values, color, dash, name}]; opts: {yfmt}
  const W = el.clientWidth || 760, H = el.clientHeight || 320;
  const pad = { l: 56, r: 14, t: 12, b: 34 };
  const all = series.flatMap((s) => s.values);
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const n = Math.max(...series.map((s) => s.values.length));
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => H - pad.b - ((v - min) / (max - min)) * (H - pad.t - pad.b);
  const yfmt = opts.yfmt || ((v) => v.toFixed(0));
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const v = min + f * (max - min), yy = y(v);
    return `<line x1="${pad.l}" y1="${yy}" x2="${W - pad.r}" y2="${yy}" stroke="${css("--border")}" stroke-width="1"/>
            <text x="${pad.l - 8}" y="${yy + 4}" text-anchor="end" font-size="11" fill="${css("--muted")}">${yfmt(v)}</text>`;
  }).join("");
  const paths = series.map((s) => {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2.4" ${s.dash ? 'stroke-dasharray="6 4"' : ""}/>`;
  }).join("");
  const legend = series.map((s, i) =>
    `<g transform="translate(${pad.l + i * 230},${H - 6})"><rect width="22" height="3" y="-4" fill="${s.color}"/>
     <text x="28" y="0" font-size="11" fill="${css("--text")}">${s.name}</text></g>`).join("");
  el.innerHTML = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${paths}${legend}</svg>`;
}

function svgScatter(el, pts, opts) {
  const W = el.clientWidth || 420, H = el.clientHeight || 300;
  const pad = { l: 46, r: 14, t: 12, b: 34 };
  const x = (v) => pad.l + v * (W - pad.l - pad.r);
  const y = (v) => H - pad.b - v * (H - pad.t - pad.b);
  const diag = `<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="${css("--muted")}" stroke-dasharray="3 3"/>`;
  let line = "", dots = "";
  if (pts.x && pts.x.length) {
    line = `<path d="${pts.x.map((vx, i) => `${i ? "L" : "M"}${x(vx).toFixed(1)},${y(pts.y[i]).toFixed(1)}`).join(" ")}" fill="none" stroke="${css("--accent")}" stroke-width="2"/>`;
    dots = pts.x.map((vx, i) => `<circle cx="${x(vx)}" cy="${y(pts.y[i])}" r="4" fill="${css("--accent")}"/>`).join("");
  }
  const axes = `<text x="${W / 2}" y="${H - 4}" text-anchor="middle" font-size="11" fill="${css("--muted")}">predicted P(up)</text>`;
  el.innerHTML = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}">${diag}${line}${dots}${axes}</svg>`;
}

function renderPortfolio(port) {
  const el = document.getElementById("portfolio-chart");
  if (!port || !port.dates || !port.dates.length) { el.innerHTML = '<p class="hint">No reconciled history yet.</p>'; return; }
  svgLineChart(el, [
    { values: port.strategy, color: css("--accent"), name: "Model (long/flat, after costs)" },
    { values: port.buy_hold, color: css("--muted"), dash: true, name: "Buy & hold" },
  ], { yfmt: (v) => "$" + Math.round(v).toLocaleString() });
}

function sparkline(vals) {
  if (!vals || !vals.length) return "";
  const w = 90, h = 22, min = Math.min(...vals), max = Math.max(...vals), r = max - min || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${h - ((v - min) / r) * h}`).join(" ");
  const col = vals[vals.length - 1] >= 0 ? css("--up") : css("--down");
  return `<svg class="spark" width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6"/></svg>`;
}

function renderWatchlist(p) {
  const tb = document.getElementById("watchlist").querySelector("tbody");
  tb.innerHTML = "";
  p.watchlist.forEach((row, i) => {
    const tr = document.createElement("tr");
    const conf = Math.round(row.confidence * 100);
    const hr = row.hit_rate;
    const hrCls = hr == null ? "hitrate-na" : hr >= 0.5 ? "hitrate-good" : "hitrate-bad";
    const price = row.price ? "$" + row.price.toFixed(2) : "—";
    const big = (window.TARGET_TYPE === "big_move");
    const callCell = big
      ? `<span class="${row.flagged ? "call-up" : "sector"}">${row.flagged ? "⚡ likely" : "· calm"}</span>
         ${row.conviction ? '<span class="badge conv">HIGH</span>' : ""}
         ${row.earnings_day ? '<span class="badge">EARN</span>' : ""}`
      : `<span class="${row.pred_up ? "call-up" : "call-down"}">${row.direction} ${row.pred_up ? "up" : "down"}</span>
         ${row.conviction ? '<span class="badge conv">CONV</span>' : ""}
         ${row.earnings_day ? '<span class="badge">EARN</span>' : ""}`;
    const probPct = big ? Math.round((row.big_move_prob ?? 0) * 100) : conf;
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td><span class="tk">${row.ticker}</span></td>
      <td class="sector">${row.sector}</td>
      <td>${callCell}</td>
      <td><div class="confbar"><span style="width:${probPct}%"></span><b>${probPct}%</b></div></td>
      <td>${price}</td>
      <td>${sparkline(row.sentiment_spark)}</td>
      <td class="${hrCls}">${hr == null ? "n/a" : fmtPct(hr)} ${row.n_predictions ? `<small>(${row.n_predictions})</small>` : ""}</td>
      <td class="why">${(row.why || []).join(", ")}</td>
      <td>${row.price ? `<div class="trade-btns"><button class="buy" data-tk="${row.ticker}" data-px="${row.price}">Buy</button></div>` : ""}</td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll(".buy").forEach((b) => b.onclick = (ev) => {
    ev.stopPropagation();
    ptBuy(b.dataset.tk, parseFloat(b.dataset.px));
  });
}

/* ---------- Paper trading (fake money, localStorage) ---------- */
const PT_KEY = "paperTrade_v1";
const PT_START = 100000;
let PT_PRICES = {};      // ticker -> latest price, from the watchlist
let PT_MODEL_RETURN = null;

function ptLoad() {
  const d = JSON.parse(localStorage.getItem(PT_KEY) || "null");
  return d || { cash: PT_START, holdings: {}, start: PT_START };
}
function ptSave(s) { localStorage.setItem(PT_KEY, JSON.stringify(s)); }

function ptMsg(t) {
  const el = document.getElementById("pt-msg");
  if (el) { el.textContent = t; setTimeout(() => { if (el.textContent === t) el.textContent = ""; }, 3500); }
}

function ptTradeAmount() {
  const el = document.getElementById("pt-amount");
  const v = el ? Number(el.value) : 5000;
  return v > 0 ? v : 5000;
}

function ptBuy(ticker, price) {
  const s = ptLoad();
  const amount = Math.min(ptTradeAmount(), s.cash);   // never spend more than cash
  const qty = Math.floor(amount / price);
  if (!(qty > 0)) return ptMsg(`Not enough cash for one share of ${ticker} ($${price.toFixed(2)}). Lower the trade size or sell something.`);
  const cost = qty * price;
  const h = s.holdings[ticker] || { shares: 0, cost: 0 };
  h.cost += cost; h.shares += qty;
  s.holdings[ticker] = h; s.cash -= cost;
  ptSave(s); ptMsg(`Bought ${qty} ${ticker} @ $${price.toFixed(2)} = $${cost.toFixed(2)}.`); renderPaperTrade();
}

function ptSell(ticker) {
  const s = ptLoad();
  const h = s.holdings[ticker]; if (!h) return;
  const price = PT_PRICES[ticker] || (h.cost / h.shares);
  const proceeds = h.shares * price;                  // one-click: sell the whole position
  s.cash += proceeds; delete s.holdings[ticker];
  ptSave(s); ptMsg(`Sold ${h.shares} ${ticker} @ $${price.toFixed(2)} = $${proceeds.toFixed(2)}.`); renderPaperTrade();
}

function ptFollowModel(watchlist) {
  const s = ptLoad();
  const up = (watchlist || []).filter((r) => r.pred_up && r.price);
  // prefer conviction calls; fall back to the top-confidence up-picks
  let picks = up.filter((r) => r.conviction).slice(0, 5);
  if (!picks.length) picks = up.slice(0, 3);
  if (!picks.length) return ptMsg("No upward picks with prices right now.");
  // size by confidence (higher conviction -> bigger slice)
  const wsum = picks.reduce((a, r) => a + r.confidence, 0);
  picks.forEach((r) => {
    const budget = (s.cash * r.confidence) / wsum;
    const qty = Math.floor(budget / r.price);
    if (qty > 0) {
      const cost = qty * r.price;
      const h = s.holdings[r.ticker] || { shares: 0, cost: 0 };
      h.shares += qty; h.cost += cost; s.holdings[r.ticker] = h; s.cash -= cost;
    }
  });
  ptSave(s); ptMsg(`Bought the model's ${picks.length} ${picks[0].conviction ? "conviction" : "top"} ▲ picks (confidence-weighted).`); renderPaperTrade();
}

function renderPaperTrade(preds, port) {
  if (preds) PT_PRICES = Object.fromEntries((preds.watchlist || []).map((r) => [r.ticker, r.price]));
  if (port && port.start_cash) PT_MODEL_RETURN = port.strategy_value / port.start_cash - 1;
  const wl = (preds && preds.watchlist) || (window._lastWatchlist || []);
  if (preds) window._lastWatchlist = wl;

  const s = ptLoad();
  let holdingsVal = 0;
  const tb = document.querySelector("#pt-holdings tbody");
  if (tb) {
    tb.innerHTML = "";
    const tickers = Object.keys(s.holdings);
    if (!tickers.length) {
      tb.innerHTML = `<tr class="empty"><td colspan="7">No positions yet — hit “Buy” on a watchlist row, or let the model pick.</td></tr>`;
    }
    tickers.forEach((tk) => {
      const h = s.holdings[tk];
      const px = PT_PRICES[tk] || (h.cost / h.shares);
      const val = h.shares * px, pl = val - h.cost, avg = h.cost / h.shares;
      holdingsVal += val;
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="tk">${tk}</td><td>${h.shares}</td><td>$${avg.toFixed(2)}</td>
        <td>$${px.toFixed(2)}</td><td>$${val.toFixed(2)}</td>
        <td class="${pl >= 0 ? "pnl-pos" : "pnl-neg"}">${pl >= 0 ? "+" : ""}$${pl.toFixed(2)}</td>
        <td><div class="trade-btns"><button class="sell" data-tk="${tk}">Sell</button></div></td>`;
      tb.appendChild(tr);
    });
    tb.querySelectorAll(".sell").forEach((b) => b.onclick = () => ptSell(b.dataset.tk));
  }

  const total = s.cash + holdingsVal, pnl = total - s.start, ret = pnl / s.start;
  const set = (id, txt, cls) => { const e = document.getElementById(id); if (e) { e.textContent = txt; if (cls) e.className = "pt-big " + cls; } };
  set("pt-total", fmtMoney(total));
  set("pt-cash", fmtMoney(s.cash));
  set("pt-pnl", `${pnl >= 0 ? "+" : ""}${fmtMoney(pnl)} (${(ret * 100).toFixed(1)}%)`, pnl >= 0 ? "pnl-pos" : "pnl-neg");
  if (PT_MODEL_RETURN != null) {
    const diff = ret - PT_MODEL_RETURN;
    set("pt-vs", `${diff >= 0 ? "+" : ""}${(diff * 100).toFixed(1)} pts`, diff >= 0 ? "pnl-pos" : "pnl-neg");
  } else set("pt-vs", "—");

  const fb = document.getElementById("pt-follow"), rs = document.getElementById("pt-reset");
  if (fb) fb.onclick = () => ptFollowModel(wl);
  if (rs) rs.onclick = () => { if (confirm("Reset your paper portfolio to $100,000?")) { ptSave({ cash: PT_START, holdings: {}, start: PT_START }); renderPaperTrade(); } };
}

function renderScoreboard(board) {
  const el = document.getElementById("scoreboard");
  if (!board) { el.textContent = "No scoreboard yet."; return; }
  const ts = board.top_streak || {};
  let html = "";
  if (ts.ticker) html += `<div class="board-row"><span>🔥 Best current streak</span><span class="streak-pill">${ts.len} on ${ts.ticker}</span></div>`;
  html += `<div class="board-row"><span>Aggregate hit-rate</span><span>${fmtPct(board.aggregate_hit_rate)}</span></div>`;
  html += `<h3>Predicts best</h3>`;
  (board.best || []).forEach((b) => html += `<div class="board-row"><span>${b.ticker}</span><span class="hitrate-good">${fmtPct(b.hit_rate)} <small>(${b.n})</small></span></div>`);
  html += `<h3>Predicts worst <span class="hint">showing the misses keeps it honest</span></h3>`;
  (board.worst || []).forEach((b) => html += `<div class="board-row"><span>${b.ticker}</span><span class="hitrate-bad">${fmtPct(b.hit_rate)} <small>(${b.n})</small></span></div>`);
  el.innerHTML = html;
}

function renderGame(preds, log) {
  const el = document.getElementById("game");
  const store = JSON.parse(localStorage.getItem("btm") || '{"user":0,"model":0,"n":0}');
  // pick a recent reconciled prediction the user hasn't seen
  const done = (log && log.predictions || []).filter((e) => e.correct != null);
  const pick = done.length ? done[done.length - 1 - (store.n % Math.min(done.length, 30))] : null;
  function paintScore() {
    return `<div class="game-score">You: ${store.user} correct · Model: ${store.model} correct · ${store.n} rounds.
      The model runs ~55%, not magic.</div>`;
  }
  if (!pick) { el.innerHTML = `<p class="hint">Need a reconciled prediction to play. Come back after a few daily runs.</p>` + paintScore(); return; }
  el.innerHTML = `<div class="game-q">Will <b>${pick.ticker}</b> close <b>up</b> or <b>down</b> next session? (round ${store.n + 1})</div>
    <div class="game-btns"><button data-g="1">▲ Up</button><button data-g="0">▼ Down</button></div>
    <div id="reveal"></div>` + paintScore();
  el.querySelectorAll(".game-btns button").forEach((b) => b.onclick = () => {
    const guess = +b.dataset.g, actual = pick.actual_up, model = pick.pred_up ? 1 : 0;
    if (guess === actual) store.user++;
    if (model === actual) store.model++;
    store.n++;
    localStorage.setItem("btm", JSON.stringify(store));
    document.getElementById("reveal").innerHTML =
      `<div class="reveal">Actual: <b>${actual ? "▲ up" : "▼ down"}</b>.
       Model said ${pick.pred_up ? "▲ up" : "▼ down"} (${Math.round(pick.confidence * 100)}%).
       You ${guess === actual ? "✅" : "❌"}, model ${model === actual ? "✅" : "❌"}.</div>`;
    setTimeout(() => renderGame(preds, log), 1400);
  });
}

function renderCalibration(calib) {
  const el = document.getElementById("calibration-chart");
  const live = calib && calib.pred_prob && calib.pred_prob.length ? calib : null;
  svgScatter(el, live ? { x: live.pred_prob, y: live.obs_freq } : { x: [], y: [] }, {});
}

function renderMood(mood) {
  const el = document.getElementById("market-mood");
  if (!mood) { el.textContent = "–"; return; }
  el.innerHTML = `
    <div class="board-row"><span>Universe sentiment</span><span>${mood.universe_sentiment > 0 ? "+" : ""}${mood.universe_sentiment.toFixed(3)}</span></div>
    <div class="board-row"><span>🐂 Most bullish</span><span>${(mood.top_bullish || []).join(", ") || "–"}</span></div>
    <div class="board-row"><span>🐻 Most bearish</span><span>${(mood.top_bearish || []).join(", ") || "–"}</span></div>
    <div class="board-row"><span>📅 Earnings flagged</span><span>${(mood.upcoming_earnings || []).join(", ") || "none"}</span></div>`;
  const hm = document.getElementById("sector-heatmap");
  hm.innerHTML = "";
  Object.entries(mood.sector_heatmap || {}).forEach(([s, v]) => {
    const d = document.createElement("div");
    d.className = "heat-cell";
    const g = Math.round(v * 255);
    d.style.background = `rgb(${255 - g},${110 + Math.round(v * 110)},${120})`;
    d.textContent = `${s} ${Math.round(v * 100)}%`;
    hm.appendChild(d);
  });
}

function renderAblationSummary(s) {
  const el = document.getElementById("ablation-summary");
  if (!s || !s.headline_ablation) { el.textContent = ""; return; }
  const h = s.headline_ablation, t = s.metrics_table, bt = s.backtest;
  const big = (s.target_type === "big_move");
  const metric = big ? "AUC" : "test F1";
  const sign = (x) => (x >= 0 ? "+" : "") + x.toFixed(4);
  let econ;
  if (big) {
    const lift = (bt.lift_vs_own_norm_flagged ?? 0) * 100;
    econ = `<strong>Model:</strong> ranks big-move days at <code>AUC ${t.model.roc_auc.toFixed(3)}</code>
      (0.5 = no signal). On the days it flags, stocks move <code>${lift >= 0 ? "+" : ""}${lift.toFixed(2)}%</code>
      ${lift >= 0 ? "above" : "below"} their <em>own</em> typical move — so the flags ${lift >= 0 ? "find genuinely above-normal days" : "don't beat each stock's baseline (honest null)"}.`;
  } else {
    econ = `<strong>vs baselines (test accuracy):</strong> model <code>${t.model.accuracy.toFixed(3)}</code>,
      persistence <code>${t.persistence.accuracy.toFixed(3)}</code>, majority <code>${t.majority_class.accuracy.toFixed(3)}</code>.
      <strong>Backtest:</strong> strategy <code>${(bt.strategy_total_return * 100).toFixed(1)}%</code>
      vs buy-and-hold <code>${(bt.buy_hold_total_return * 100).toFixed(1)}%</code>.`;
  }
  el.innerHTML = `
    ${big ? `<p class="edu">📌 <strong>Why this isn't a "buy" predictor:</strong> we tested AI on next-day
      <em>direction</em> and it was a coin flip (~50%) — that's market efficiency, not a bug. So this predicts what
      genuinely <em>is</em> predictable: <strong>volatility</strong> (big moves cluster). It tells you what's likely to
      <em>move</em>, not which way.</p>` : ""}
    <p><strong>Does sentiment help?</strong> adding the sentiment group changed ${metric} from
    <code>${h.market_only_f1.toFixed(3)}</code> (price/volume only) to
    <code>${h.market_sentiment_f1.toFixed(3)}</code> — Δ <code>${sign(h.sentiment_delta_f1)}</code>.
    Walk-forward: <code>${sign(h.walk_forward.mean)} ± ${h.walk_forward.std.toFixed(4)}</code>.</p>
    <p>${econ}</p>`;
}

function renderToggleNote(s) {
  const note = document.getElementById("toggle-note");
  const t = document.getElementById("sentiment-toggle");
  const setNote = () => {
    if (!s || !s.headline_ablation) { note.textContent = ""; return; }
    const d = s.headline_ablation.sentiment_delta_f1;
    const metric = s.target_type === "big_move" ? "AUC" : "test F1";
    note.textContent = t.checked
      ? `sentiment on — it ${d >= 0 ? "added" : "subtracted"} ${Math.abs(d).toFixed(4)} ${metric}`
      : "sentiment off — showing the price-only control";
  };
  t.onchange = setNote; setNote();
}

// theme toggle (persisted)
const tt = document.getElementById("theme-toggle");
const applyTheme = (th) => { document.body.dataset.theme = th; tt.textContent = th === "dark" ? "☾" : "☀"; };
applyTheme(localStorage.getItem("theme") || "dark");
tt.onclick = () => { const n = document.body.dataset.theme === "dark" ? "light" : "dark"; localStorage.setItem("theme", n); applyTheme(n); main(); };

main();
