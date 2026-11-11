(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const phone = window.matchMedia("(max-width:860px)");
  const PAGES = ["desk", "trades", "swing", "shortterm", "market", "agents", "research", "system"];
  let token = "";
  try { token = sessionStorage.getItem("optplat_token") || ""; } catch (e) { /* storage unavailable */ }
  // The launcher opens /#token=... . A URL fragment is never sent to the server. Read it once, keep it for this
  // tab only, then remove it from the address bar so it is not left in the URL or copied by accident.
  const fromUrl = /^#token=([A-Za-z0-9_-]{16,200})$/.exec(location.hash);
  if (fromUrl) {
    token = fromUrl[1];
    try { sessionStorage.setItem("optplat_token", token); } catch (e) { /* storage unavailable */ }
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* ignore */ }
  }
  const S = {
    killState: false, lastPoints: [], core: null, connected: false,
    trades: null, filter: "all", query: "", sort: { key: "entry_time", dir: -1 }, openTrade: null, opener: null,
    scan: null, marketTab: "active", unusualFilter: "reviewable",
  };

  // ---------------------------------------------------------------- DOM helpers (textContent only)
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  };
  const kids = (parent, list) => { list.forEach((c) => { if (c) parent.appendChild(c); }); return parent; };
  const money = (n) => (n === null || n === undefined ? "n/a" : Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" }));
  const shortMoney = (n) => Number(n).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const sgn = (n) => (n === null || n === undefined ? "n/a" : (n > 0 ? "+" : n < 0 ? "-" : "") + money(Math.abs(n)));
  const pct = (v) => (v === null || v === undefined ? "n/a" : (v > 0 ? "+" : "") + Number(v).toFixed(2) + "%");
  const num = (n) => (n === null || n === undefined ? "n/a" : Number(n).toLocaleString());
  const tone = (n) => (n > 0 ? "gain" : n < 0 ? "loss" : "");
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); };
  const fmtDay = (iso) => { const d = new Date(iso + "T12:00:00"); return isNaN(d) ? String(iso) : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); };
  const span = (text, cls) => el("span", text, cls);
  function duration(sec) {
    if (sec === null || sec === undefined) return "n/a";
    const m = Math.floor(sec / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
    return d >= 1 ? d + "d " + (h % 24) + "h" : h >= 1 ? h + "h " + (m % 60) + "m" : Math.max(m, 0) + "m";
  }
  const words = (x) => { const t = String(x === null || x === undefined ? "" : x).toLowerCase().replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
  function setMsg(text, cls) { const m = $("msg"); m.textContent = text || ""; m.className = cls || "muted"; }
  function empty(container, title, hint) {
    container.replaceChildren();
    const d = el("div", null, "empty");
    d.appendChild(el("b", title));
    if (hint) d.appendChild(el("span", hint));
    container.appendChild(d);
  }

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({}, opts, { headers: { "X-API-Token": token, "content-type": "application/json" } }));
    let body = {};
    try { body = await r.json(); } catch (e) { /* empty body */ }
    if (!r.ok) {
      const err = new Error(body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : r.statusText);
      err.status = r.status;
      throw err;
    }
    return body;
  }

  function table(container, cols, rows, emptyTitle, emptyHint) {
    if (!rows.length) { empty(container, emptyTitle, emptyHint); return; }
    container.replaceChildren();
    const t = el("table"), head = el("tr");
    cols.forEach((c) => head.appendChild(el("th", c.label, c.right ? "r" : "")));
    t.appendChild(head);
    rows.forEach((row) => {
      const tr = el("tr");
      cols.forEach((c) => {
        const td = el("td", null, c.right ? "r" : "");
        const v = c.get(row);
        if (v instanceof Node) td.appendChild(v); else td.textContent = v === null || v === undefined ? "" : String(v);
        tr.appendChild(td);
      });
      t.appendChild(tr);
    });
    container.appendChild(t);
  }

  function pill(id, text, cls) { const e = $(id); e.textContent = text; e.className = "pill " + (cls || ""); }
  function chips(host, options, current, onPick, role) {
    host.replaceChildren();
    options.forEach((o) => {
      const b = el("button", o.label, "chip");
      b.type = "button";
      b.setAttribute(role === "tab" ? "aria-selected" : "aria-pressed", String(o.id === current));
      if (role === "tab") b.setAttribute("role", "tab");
      b.addEventListener("click", () => onPick(o.id));
      host.appendChild(b);
    });
  }

  // ---------------------------------------------------------------- routing
  const route = () => { const m = /^#\/([a-z]+)/.exec(location.hash); return m && PAGES.indexOf(m[1]) >= 0 ? m[1] : "desk"; };
  function showPage() {
    const page = route();
    document.querySelectorAll("section[data-page]").forEach((s) => { s.hidden = !S.connected || s.getAttribute("data-page") !== page; });
    $("view-connect").hidden = S.connected;
    document.querySelectorAll("a.nav").forEach((a) => {
      if (a.getAttribute("data-page") === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = (S.connected ? ({ desk: "Desk", trades: "Trades", swing: "Swing", shortterm: "Short-term", market: "Market", agents: "Agents", research: "Research", system: "Controls" })[page] + " - " : "") + "options-platform";
  }

  // ---------------------------------------------------------------- equity chart (unchanged behaviour)
  const SVGNS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs, text) => {
    const e = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach((k) => e.setAttribute(k, String(attrs[k])));
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  };
  const MIN_TRADES = 30; // mirrors evaluation.MIN_TRADES: below this, results are not evidence

  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) { const pad = Math.max(Math.abs(lo) * 0.001, 1); lo -= pad; hi += pad; }
    const raw = (hi - lo) / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw) || 10 * mag;
    const first = Math.floor(lo / step) * step, ticks = [];
    for (let v = first; v <= hi + step * 0.5; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
    return ticks;
  }

  // One series, so no legend; the panel title names it. The crosshair is keyboard-reachable (arrow keys) and a
  // table view carries the same data.
  function drawEquity(host, points) {
    host.replaceChildren();
    if (points.length < 2) { empty(host, "Not enough history to draw a curve yet", "It needs at least two completed cycles with trading allowed."); return; }
    const W = Math.max(300, Math.round(host.clientWidth || 720)), H = W < 520 ? 220 : 260;
    const m = { l: W < 520 ? 58 : 64, r: 70, t: 12, b: 26 };
    const xs = points.map((p) => new Date(p.ts).getTime()), ys = points.map((p) => Number(p.equity));
    const ticks = niceTicks(Math.min.apply(null, ys), Math.max.apply(null, ys), 4);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1], x0 = xs[0], x1 = xs[xs.length - 1] || x0 + 1;
    const X = (t) => m.l + ((t - x0) / Math.max(x1 - x0, 1)) * (W - m.l - m.r);
    const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", tabindex: 0,
      "aria-label": "Paper account equity over time, " + points.length + " points. Use left and right arrow keys to read values." });
    ticks.forEach((v) => {
      root.appendChild(svg("line", { class: "grid", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }));
      root.appendChild(svg("text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, shortMoney(v)));
    });
    root.appendChild(svg("text", { x: m.l, y: H - 6, "text-anchor": "start" }, fmtTime(points[0].ts)));
    root.appendChild(svg("text", { x: W - m.r, y: H - 6, "text-anchor": "end" }, fmtTime(points[points.length - 1].ts)));
    const start = ys[0];
    if (start >= y0 && start <= y1) root.appendChild(svg("line", { class: "ref", x1: m.l, x2: W - m.r, y1: Y(start), y2: Y(start), "stroke-dasharray": "4 4" }));
    const path = points.map((p, i) => (i ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(ys[i]).toFixed(1)).join(" ");
    root.appendChild(svg("path", { class: "area", d: path + " L" + X(x1).toFixed(1) + " " + Y(y0) + " L" + X(x0).toFixed(1) + " " + Y(y0) + " Z" }));
    root.appendChild(svg("path", { class: "line", d: path }));
    const last = points.length - 1;
    root.appendChild(svg("circle", { class: "dot", cx: X(xs[last]), cy: Y(ys[last]), r: 5 }));
    root.appendChild(svg("text", { class: "end", x: Math.min(X(xs[last]) + 10, W - 2), y: Y(ys[last]) + 4, "text-anchor": "start" }, shortMoney(ys[last])));
    const cross = svg("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" });
    const hot = svg("circle", { class: "dot", r: 5, visibility: "hidden" });
    root.appendChild(cross); root.appendChild(hot);
    const tip = el("div", null, "tip"); tip.hidden = true;
    const tv = el("strong"), tt = el("span"), tc = el("span");
    kids(tip, [tv, tt, tc]);
    host.appendChild(root); host.appendChild(tip);
    let idx = last;
    const show = (i) => {
      idx = Math.max(0, Math.min(last, i));
      const cx = X(xs[idx]), cy = Y(ys[idx]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
      hot.setAttribute("cx", cx); hot.setAttribute("cy", cy); hot.setAttribute("visibility", "visible");
      tv.textContent = money(ys[idx]);
      tt.textContent = fmtTime(points[idx].ts);
      tc.textContent = " | " + sgn(ys[idx] - start) + " vs first point";
      tip.hidden = false;
      const r = root.getBoundingClientRect(), hr = host.getBoundingClientRect();
      const px = (cx / W) * r.width + (r.left - hr.left);
      tip.style.left = Math.max(0, Math.min(px + 12, hr.width - tip.offsetWidth)) + "px";
      tip.style.top = Math.max(0, (cy / H) * r.height - 8) + "px";
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); hot.setAttribute("visibility", "hidden"); tip.hidden = true; };
    const nearest = (ev) => {
      const r = root.getBoundingClientRect(), t = x0 + (((ev.clientX - r.left) / r.width) * W - m.l) / (W - m.l - m.r) * (x1 - x0);
      let best = 0;
      for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - t) < Math.abs(xs[best] - t)) best = i;
      return best;
    };
    root.addEventListener("pointermove", (ev) => show(nearest(ev)));
    root.addEventListener("pointerleave", hide);
    root.addEventListener("blur", hide);
    root.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft") { show(idx - 1); ev.preventDefault(); }
      else if (ev.key === "ArrowRight") { show(idx + 1); ev.preventDefault(); }
      else if (ev.key === "Escape") hide();
    });
  }

  // ---------------------------------------------------------------- shared formatting for contracts
  function ticket(t) {
    const w = el("span", null, "ticket");
    w.appendChild(el("span", t.symbol, "sym"));
    w.appendChild(el("span", (t.right === "C" ? "Call " : "Put ") + t.strike, "leg " + (t.right === "C" ? "call" : "put")));
    w.appendChild(el("span", fmtDay(t.expiry), "muted"));
    return w;
  }
  const EXIT_TEXT = {
    take_profit: "Take profit", stop_loss: "Stop loss", expiry_window: "Too close to expiry", max_days_held: "Held too long",
  };
  const exitLabel = (t) => (t.status === "OPEN" ? "Open" : t.status === "PARTIAL" ? "Partly closed" : (EXIT_TEXT[t.exit_reason] || t.exit_reason || "Closed"));
  const EXIT_WHY = {
    take_profit: "The bid reached the take-profit level, so the exit rule sold the position.",
    stop_loss: "The bid fell to the stop-loss level, so the exit rule sold to limit the loss.",
    expiry_window: "The contract came within the minimum days to expiry, so it was closed before expiry risk grows.",
    max_days_held: "It had been held for the maximum number of days, so the time stop closed it.",
  };

  // ---------------------------------------------------------------- Desk
  function renderStrip(health, status, portfolio) {
    pill("mode", health.mode + " (" + (health.broker.broker || "broker") + ")", health.mode === "PAPER" ? "ok" : "bad");
    pill("data", status.data_source.name + (status.data_source.fictional ? " - FICTIONAL" : ""), status.data_source.fictional ? "warn" : "");
    pill("market", "market " + (status.market.open ? "open" : "closed") + ": " + status.market.reason, status.market.open ? "ok" : "");
    S.killState = !!portfolio.kill_switch;
    pill("kill", S.killState ? "KILL SWITCH ON" : "kill switch off", S.killState ? "bad" : "");
    const rn = status.runner;
    pill("runner", rn.stalled ? "LOOP STALLED: no good cycle for " + rn.seconds_since_success + "s" : (rn.running ? "loop running" : "loop stopped"),
      rn.stalled ? "bad" : (rn.running ? "ok" : ""));
    $("runner").title = rn.last_error ? "Last error: " + rn.last_error : "";
    $("updated").textContent = "Updated " + new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function renderTrust(status) {
    const reasons = [], cautions = [];
    const rn = status.runner, c = status.last_cycle, dq = Object.entries(status.data_quality.issues);
    if (rn.stalled) reasons.push("the loop has stalled");
    if (c && c.errors.length) cautions.push("the last cycle reported errors");
    if (status.data_source.fictional) cautions.push("data is fictional, so results prove nothing");
    if (!status.market.open) cautions.push("market is closed");
    if (!status.config.record_snapshots) cautions.push("snapshot recording is off");
    if (dq.some(([, v]) => v.severity === "reject")) reasons.push("snapshots were rejected as bad data");
    const v = $("trust-verdict");
    if (reasons.length) { v.textContent = "Do not rely on it yet: " + reasons.concat(cautions).join("; ") + "."; v.className = "verdict bad"; }
    else if (cautions.length) { v.textContent = "Usable with care: " + cautions.join("; ") + "."; v.className = "verdict warn"; }
    else { v.textContent = "No problems detected in the last " + status.data_quality.window_hours + " hours."; v.className = "verdict ok"; }
    const rec = status.recorder, f = $("trust");
    f.replaceChildren();
    const row = (k, val) => { f.appendChild(el("dt", k)); f.appendChild(el("dd", val)); };
    row("Loop", rn.stalled ? "stalled: " + rn.seconds_since_success + "s since a good cycle" : (rn.running ? "running" : "stopped"));
    if (rn.last_error) row("Last loop error", rn.last_error);
    row("Last cycle", c ? c.started_at.slice(0, 19) + (c.entries_note ? ". " + c.entries_note : "") : "none yet");
    if (c && c.errors.length) row("Cycle errors", c.errors.join("; "));
    row("Data source", status.data_source.name + (status.data_source.fictional ? " (FICTIONAL)" : ""));
    row("Market", (status.market.open ? "open" : "closed") + ": " + status.market.reason);
    row("Recorded snapshots", rec.real + " real, " + rec.fictional + " fictional" + (rec.newest ? ", latest " + rec.newest.slice(0, 19) : ""));
    row("Data quality, " + status.data_quality.window_hours + "h",
      dq.length ? dq.map(([k, x]) => k.toLowerCase().replace(/_/g, " ") + " x" + x.items + " (" + x.severity + ")").join(", ") : "no issues");
  }

  function fig(value, label, sub, cls) {
    const f = el("div", null, "fig");
    f.appendChild(el("div", value, "v num " + (cls || "")));
    f.appendChild(el("div", label, "l"));
    if (sub) f.appendChild(el("div", sub, "s"));
    return f;
  }

  function renderDesk(portfolio, report, eq, status) {
    const a = portfolio.account, sm = eq.summary;
    const fict = eq.fictional ? " on fictional data" : "";
    let head = "The paper account is worth " + money(a.equity) + fict;
    if (sm.change_pct !== null && sm.change_pct !== 0) head += ", " + (sm.change_pct > 0 ? "up " : "down ") + Math.abs(sm.change_pct).toFixed(2) + "% since the first recorded point";
    head += ". It holds " + report.open.length + " open position" + (report.open.length === 1 ? "" : "s") + " and has closed " + report.closed_trades + " trade" + (report.closed_trades === 1 ? "" : "s") + ".";
    $("desk-headline").textContent = head;
    const need = Math.max(0, MIN_TRADES - report.closed_trades);
    $("desk-sub").textContent = "Everything on this page is the long-term book: options bought with at least a week to expiry and held until an exit rule fires. " +
      (need ? "With " + report.closed_trades + " closed trades, none of these numbers is evidence yet; " + MIN_TRADES + " is the minimum." : "The sample is past the minimum, which still does not show an edge on its own.");
    const t = $("tiles");
    t.replaceChildren();
    kids(t, [
      fig(money(a.equity), "Equity", "cash " + money(a.cash)),
      fig(pct(sm.change_pct), "Since first point", sm.points + " points", tone(sm.change_pct)),
      fig(sm.current_drawdown_pct === null ? "n/a" : "-" + sm.current_drawdown_pct + "%", "Drawdown now", "worst -" + (sm.max_drawdown_pct || 0) + "%"),
      fig(sgn(report.realized_pnl), "Realized profit", report.closed_trades + " closed" + (report.win_rate_pct === null ? "" : ", " + report.win_rate_pct + "% winners"), tone(report.realized_pnl)),
      fig(money(a.open_premium), "Open premium", report.open.length + " position(s)"),
    ]);
    $("sample").textContent = report.caveat;
    S.lastPoints = eq.points;
    drawEquity($("equity-chart"), eq.points);
    table($("equity-table"), [
      { label: "Time", get: (p) => p.ts.slice(0, 19) }, { label: "Equity", right: true, get: (p) => money(p.equity) },
    ], eq.points.slice().reverse().slice(0, 200), "No equity points yet");
  }

  // "SPY261218C00600000" -> days to expiry. Anything unparseable is shown as unknown, never guessed.
  function dteOf(contract, now) {
    const m = /^[A-Z.\-]{1,10}(\d{2})(\d{2})(\d{2})[CP]\d{8}$/.exec(contract || "");
    if (!m) return null;
    const exp = Date.UTC(2000 + Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return Math.round((exp - Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())) / 86400000);
  }

  function renderPositions(report, cfg) {
    const now = new Date();
    table($("positions"), [
      { label: "Contract", get: (r) => el("span", r.contract, "mono") }, { label: "Qty", right: true, get: (r) => r.quantity },
      { label: "Avg cost", right: true, get: (r) => r.avg_cost },
      { label: "Bid mark", right: true, get: (r) => r.mark === null ? "unobservable" : r.mark },
      { label: "Unrealized", right: true, get: (r) => r.unrealized_pnl === null ? "n/a" : span(sgn(r.unrealized_pnl), tone(r.unrealized_pnl)) },
      { label: "Take profit at bid", right: true, get: (r) => cfg.auto_exits ? (r.avg_cost * (1 + cfg.take_profit_pct / 100)).toFixed(2) : "auto exits off" },
      { label: "Stop at bid", right: true, get: (r) => cfg.auto_exits ? (r.avg_cost * (1 - cfg.stop_loss_pct / 100)).toFixed(2) : "auto exits off" },
      { label: "Days to expiry", right: true, get: (r) => { const d = dteOf(r.contract, now); return d === null ? "unknown" : d + (d <= cfg.min_dte_to_hold ? " (forced exit zone)" : ""); } },
    ], report.open, "No open positions", "When an entry fills it appears here with the prices that would close it.");
  }

  function whyOf(d) {
    const p = d.payload || {};
    if (p.risk_failures && p.risk_failures.length) return p.risk_failures.join("; ");
    return p.why || p.reason || (p.reasons && p.reasons.join("; ")) || (p.score !== undefined ? "score " + Number(p.score).toFixed(2) : "");
  }
  function renderDecisions(list) {
    table($("decisions"), [
      { label: "Time", get: (d) => fmtTime(d.ts) }, { label: "Type", get: (d) => words(d.kind) },
      { label: "Contract", get: (d) => el("span", d.contract || "", "mono") }, { label: "Outcome", get: (d) => words(d.disposition) },
      { label: "Why", get: whyOf },
    ], list, "No decisions recorded yet", "Run one cycle from Controls to see what it considers.");
  }

  function renderOrders(orders) {
    table($("orders"), [
      { label: "Time", get: (o) => fmtTime(o.created_at) }, { label: "Side", get: (o) => o.intent.side },
      { label: "Contract", get: (o) => o.intent.contract.underlying + " " + o.intent.contract.expiry + " " + o.intent.contract.right + o.intent.contract.strike },
      { label: "Qty", right: true, get: (o) => o.filled_qty + "/" + o.intent.quantity }, { label: "Limit", right: true, get: (o) => o.intent.limit_price },
      { label: "Fill", right: true, get: (o) => o.avg_fill_price === null ? "" : o.avg_fill_price },
      { label: "State", get: (o) => o.state }, { label: "Why", get: (o) => o.risk_failures.join("; ") },
    ], orders.slice(0, 30), "No orders yet");
  }

  function syncControls(status, cfg) {
    $("cfg-entries").checked = status.config.auto_entries;
    $("cfg-exits").checked = status.config.auto_exits;
    $("cfg-shortterm").checked = !!cfg.shortterm_enabled;
    $("cfg-swing").checked = !!cfg.swing_enabled;
    $("cfg-hours").checked = status.market.hours_enforced;
    $("cfg-hours").disabled = status.market.hours_enforced && !status.data_source.fictional; // real data: always on
    if (document.activeElement !== $("cfg-watch")) $("cfg-watch").value = status.config.watchlist.join(", ");
    const sel = $("cfg-scan"), v = String(cfg.scan_interval_s === undefined ? 0 : cfg.scan_interval_s);
    if (document.activeElement !== sel) {
      if (!Array.prototype.some.call(sel.options, (o) => o.value === v)) sel.appendChild(Object.assign(document.createElement("option"), { value: v, textContent: "every " + Math.round(Number(v) / 60) + " minutes" }));
      sel.value = v;
    }
    if (document.activeElement !== $("cfg-committee")) $("cfg-committee").value = cfg.committee_mode;
  }

  // ---------------------------------------------------------------- Trades
  const FILTERS = [
    { id: "all", label: "All", test: () => true }, { id: "open", label: "Open", test: (t) => t.status !== "CLOSED" },
    { id: "closed", label: "Closed", test: (t) => t.status === "CLOSED" },
    { id: "winners", label: "Winners", test: (t) => t.status === "CLOSED" && t.pnl > 0 },
    { id: "losers", label: "Losers", test: (t) => t.status === "CLOSED" && t.pnl <= 0 },
  ];
  const SORTS = {
    entry_time: (t) => t.entry_time, symbol: (t) => t.symbol, pnl: (t) => (t.pnl === null ? -Infinity : t.pnl),
    pnl_pct: (t) => (t.pnl_pct === null ? -Infinity : t.pnl_pct), held: (t) => (t.held_seconds === null ? Infinity : t.held_seconds),
  };

  function pnlCell(t) {
    const w = el("span", null, "num");
    if (t.pnl === null) { w.textContent = "unobservable"; w.className = "muted"; return w; }
    w.appendChild(span(sgn(t.pnl), tone(t.pnl)));
    const bar = el("span", null, "bar"), i = el("i", null, t.pnl >= 0 ? "up" : "down");
    i.style.width = Math.min(50, Math.abs(t.pnl_pct || 0) / 2) + "%";
    bar.appendChild(i);
    w.appendChild(bar);
    return w;
  }
  function statusTag(t) {
    if (t.status !== "CLOSED") return el("span", exitLabel(t), "tag info");
    return el("span", exitLabel(t), "tag " + (t.pnl > 0 ? "gain" : "loss"));
  }

  function renderTrades() {
    const data = S.trades;
    if (!data) return;
    const sm = data.summary, f = $("trade-summary");
    $("trade-lede").textContent = sm.total
      ? sm.total + " trade" + (sm.total === 1 ? "" : "s") + " so far, each one a filled buy matched to the sells that closed it. Select a row to see why it was entered, what the agents said, and how it ended. " + sm.caveat
      : "Nothing has traded yet. Entries need automatic entries switched on in Controls and a candidate that passes the risk gate, the agents and the data-quality check.";
    f.replaceChildren();
    kids(f, [
      fig(String(sm.total), "Trades", sm.open + " open, " + sm.closed + " closed"),
      fig(sm.win_rate_pct === null ? "n/a" : sm.win_rate_pct + "%", "Winners", sm.closed ? sm.wins + " of " + sm.closed + " closed" : "no closed trades"),
      fig(sgn(sm.realized_pnl), "Realized", "from closed and partly closed", tone(sm.realized_pnl)),
      fig(sgn(sm.unrealized_pnl), "Unrealized", sm.unobservable_open ? sm.unobservable_open + " open without a usable bid" : "marked at the bid", tone(sm.unrealized_pnl)),
      fig(sm.best === null ? "n/a" : sgn(sm.best), "Best closed", sm.worst === null ? "" : "worst " + sgn(sm.worst), tone(sm.best)),
    ]);
    chips($("trade-filters"), FILTERS.map((x) => ({ id: x.id, label: x.label + " " + data.trades.filter(x.test).length })), S.filter, (id) => { S.filter = id; renderTrades(); });
    const flt = FILTERS.find((x) => x.id === S.filter) || FILTERS[0], q = S.query.trim().toUpperCase();
    const key = SORTS[S.sort.key], dir = S.sort.dir;
    const rows = data.trades.filter(flt.test).filter((t) => !q || t.symbol.indexOf(q) >= 0 || t.contract.indexOf(q) >= 0)
      .sort((x, y) => (key(x) < key(y) ? -dir : key(x) > key(y) ? dir : 0));
    const host = $("trade-table");
    if (!rows.length) {
      empty(host, data.trades.length ? "No trades match this filter" : "No trades yet",
        data.trades.length ? "Clear the search box or pick All." : "Run a cycle from Controls, or let the loop run during market hours.");
      return;
    }
    host.replaceChildren();
    if (window.matchMedia("(max-width:860px)").matches) {
      // Phones: one card per trade instead of a table that would scroll sideways.
      const sorter = el("select");
      sorter.setAttribute("aria-label", "Sort trades");
      [["entry_time", -1, "Newest first"], ["entry_time", 1, "Oldest first"], ["pnl", -1, "Best profit first"], ["pnl", 1, "Worst result first"]].forEach((o) => {
        const opt = el("option", o[2]); opt.value = o[0] + ":" + o[1]; sorter.appendChild(opt);
      });
      sorter.value = S.sort.key + ":" + S.sort.dir;
      sorter.addEventListener("change", () => { const v = sorter.value.split(":"); S.sort = { key: v[0], dir: Number(v[1]) }; renderTrades(); });
      host.appendChild(sorter);
      rows.forEach((x) => {
        const card = el("div", null, "tcard");
        card.tabIndex = 0; card.setAttribute("role", "button");
        card.setAttribute("aria-label", "Open trade file for " + x.symbol + " " + (x.right === "C" ? "call " : "put ") + x.strike);
        const top = el("div", null, "tc-top");
        top.appendChild(ticket(x)); top.appendChild(statusTag(x));
        const mid = el("div", null, "tc-mid");
        mid.appendChild(el("span", x.pnl === null ? "Unobservable" : sgn(x.pnl), "tc-pnl num " + tone(x.pnl)));
        if (x.pnl_pct !== null) mid.appendChild(el("span", pct(x.pnl_pct), "num " + tone(x.pnl_pct)));
        const low = el("div", x.quantity + " at " + Number(x.entry_price).toFixed(2) + (x.exit_price !== null ? ", sold at " + Number(x.exit_price).toFixed(2) : (x.mark !== null ? ", bid " + Number(x.mark).toFixed(2) : ", no usable bid")) +
          ". Opened " + fmtTime(x.entry_time) + ".", "muted");
        kids(card, [top, mid, low]);
        const open = () => openTrade(x.id, card);
        card.addEventListener("click", open);
        card.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
        host.appendChild(card);
      });
      return;
    }
    const t = el("table"), head = el("tr");
    const col = (label, sortKey, right) => {
      const th = el("th", null, right ? "r" : "");
      if (sortKey) {
        const b = el("button", label + (S.sort.key === sortKey ? (sortKey === "entry_time" ? (S.sort.dir > 0 ? " (oldest first)" : " (newest first)") : (S.sort.dir > 0 ? " (low to high)" : " (high to low)")) : ""));
        b.type = "button";
        th.setAttribute("aria-sort", S.sort.key === sortKey ? (S.sort.dir > 0 ? "ascending" : "descending") : "none");
        b.addEventListener("click", () => { S.sort = { key: sortKey, dir: S.sort.key === sortKey ? -S.sort.dir : -1 }; renderTrades(); });
        th.appendChild(b);
      } else th.textContent = label;
      head.appendChild(th);
    };
    col("Opened", "entry_time"); col("Contract", "symbol"); col("Qty", null, true); col("Entry", null, true); col("Exit or mark", null, true);
    col("Profit or loss", "pnl", true); col("Return", "pnl_pct", true); col("Held", "held", true); col("Status", null);
    t.appendChild(head);
    const now = Date.now();
    rows.forEach((x) => {
      const tr = el("tr", null, "click");
      tr.tabIndex = 0;
      tr.setAttribute("aria-label", "Open trade file for " + x.symbol + " " + (x.right === "C" ? "call " : "put ") + x.strike);
      const cell = (content, right) => { const td = el("td", null, right ? "r num" : ""); if (content instanceof Node) td.appendChild(content); else td.textContent = content; tr.appendChild(td); };
      cell(fmtTime(x.entry_time)); cell(ticket(x)); cell(String(x.quantity), true); cell(Number(x.entry_price).toFixed(2), true);
      cell(x.exit_price !== null ? Number(x.exit_price).toFixed(2) : (x.mark !== null ? Number(x.mark).toFixed(2) + " (mark)" : "unobservable"), true);
      cell(pnlCell(x), true);
      cell(x.pnl_pct === null ? "n/a" : span(pct(x.pnl_pct), tone(x.pnl_pct)), true);
      cell(duration(x.held_seconds !== null ? x.held_seconds : Math.floor((now - new Date(x.entry_time).getTime()) / 1000)), true);
      cell(statusTag(x));
      const open = () => openTrade(x.id, tr);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } });
      t.appendChild(tr);
    });
    host.appendChild(t);
  }

  async function loadTrades() {
    S.trades = await api("/api/trades?limit=500");
    renderTrades();
  }

  // ---------------------------------------------------------------- Trade file drawer
  const RATIONALE = {
    trend: (v) => "Trend: " + v, sma20: (v) => "20-day average " + v, sma50: (v) => "50-day average " + v,
    spread_pct: (v) => "Bid-ask spread " + v + "% of the ask", volume: (v) => "Contract volume " + num(v),
    open_interest: (v) => "Open interest " + num(v), dte: (v) => v + " days to expiry", strategy: (v) => "Strategy " + v,
  };
  function voteChip(v) {
    const s = v.stance === "SUPPORT" ? "s" : v.stance === "OPPOSE" ? "o" : "";
    const word = v.stance === "SUPPORT" ? "supports" : v.stance === "OPPOSE" ? "opposes" : "abstains";
    const c = el("span", v.agent + " " + word + (v.stance === "ABSTAIN" ? "" : " " + Math.round(v.confidence * 100) + "%"), "vote " + s);
    c.title = (v.reasons || []).join("; ");
    return c;
  }
  function section(title, nodes) {
    const s = el("div");
    s.appendChild(el("h3", title));
    kids(s, nodes);
    return s;
  }
  function renderTradeFile(t) {
    $("drawer-title").textContent = t.symbol + " " + (t.right === "C" ? "call " : "put ") + t.strike + ", " + fmtDay(t.expiry);
    $("drawer-sub").textContent = t.contract + " | " + exitLabel(t);
    const body = $("drawer-body");
    body.replaceChildren();
    const res = el("div");
    const big = el("div", t.pnl === null ? "Unobservable" : sgn(t.pnl), "result " + tone(t.pnl));
    res.appendChild(big);
    res.appendChild(el("div", (t.pnl_pct === null ? "No usable bid to mark this trade." : pct(t.pnl_pct) + " on " + money(t.entry_price * t.quantity * t.multiplier) + " paid")
      + (t.status === "CLOSED" ? "" : " (still open, marked at the bid)"), "muted"));
    body.appendChild(res);

    const facts = el("dl", null, "facts");
    const row = (k, v) => { facts.appendChild(el("dt", k)); facts.appendChild(el("dd", v)); };
    row("Bought", t.quantity + " at " + Number(t.entry_price).toFixed(2) + " on " + fmtTime(t.entry_time));
    t.exit_orders.forEach((x) => row("Sold", x.quantity + " at " + Number(x.price).toFixed(2) + " on " + fmtTime(x.time)));
    if (t.remaining > 0) row("Still held", t.remaining + (t.mark !== null ? ", bid " + Number(t.mark).toFixed(2) : ", no usable bid"));
    row("Held", duration(t.held_seconds !== null ? t.held_seconds : Math.floor((Date.now() - new Date(t.entry_time).getTime()) / 1000)));
    body.appendChild(section("The trade", [facts]));

    const why = [];
    if (t.entry_reason && typeof t.entry_reason === "object") {
      const ul = el("ul", null, "plain");
      Object.keys(t.entry_reason).forEach((k) => ul.appendChild(el("li", RATIONALE[k] ? RATIONALE[k](t.entry_reason[k]) : k + ": " + t.entry_reason[k])));
      why.push(ul);
    } else why.push(el("p", "No entry reasoning was recorded for this order.", "muted"));
    body.appendChild(section("Why it entered", why));

    const c = t.committee, cm = [];
    if (c) {
      cm.push(el("p", "Net score " + Number(c.net_score).toFixed(2) + ", order size " + c.quantity + " contract" + (c.quantity === 1 ? "" : "s") + " at " + Math.round((c.scale || 0) * 100) + "% of the allowed size."));
      const votes = el("div", null, "votes");
      (c.verdicts || []).forEach((v) => votes.appendChild(voteChip(v)));
      cm.push(votes);
      const sk = (c.verdicts || []).find((v) => v.agent === "skeptic");
      if (sk && sk.reasons.length) {
        const ul = el("ul", null, "plain");
        sk.reasons.forEach((r) => ul.appendChild(el("li", "Skeptic: " + r)));
        cm.push(ul);
      }
    } else cm.push(el("p", "No committee vote was matched to this entry. The committee may have been off, or this trade is older than the committee.", "muted"));
    body.appendChild(section("What the agents said", cm));

    const end = [];
    if (t.status === "CLOSED") {
      end.push(el("p", EXIT_WHY[t.exit_reason] || ("Closed: " + (t.exit_reason || "reason not recorded") + ".")));
    } else {
      end.push(el("p", "Still open. It will close when the bid hits the take-profit or stop level, or when expiry gets too close.", "muted"));
    }
    body.appendChild(section("How it ended", end));

    const trail = el("div");
    trail.appendChild(el("p", "Loading the order trail", "muted"));
    body.appendChild(section("Order trail", [trail]));
    return trail;
  }

  async function openTrade(id, opener) {
    const t = S.trades && S.trades.trades.find((x) => x.id === id);
    if (!t) return;
    S.openTrade = id; S.opener = opener || document.activeElement;
    const trail = renderTradeFile(t);
    $("scrim").hidden = false; $("drawer").hidden = false;
    document.body.style.overflow = "hidden";
    $("btn-drawer-close").focus();
    try {
      const d = await api("/api/trades/" + encodeURIComponent(id));
      if (S.openTrade !== id) return;
      trail.replaceChildren();
      const ol = el("ol", null, "timeline");
      (d.audit || []).forEach((e) => {
        const li = el("li");
        li.appendChild(el("time", fmtTime(e.ts)));
        const p = e.payload || {};
        const what = e.kind === "order_created" ? (p.intent ? (p.intent.side === "BUY_TO_OPEN" ? "Buy" : "Sell") + " order created, " + p.intent.quantity + " at limit " + p.intent.limit_price : "Order created")
          : e.kind === "order_state" && p.state ? words(p.state) + (p.reason ? ": " + p.reason : "") : words(e.kind);
        li.appendChild(el("span", what));
        ol.appendChild(li);
      });
      if (ol.children.length) trail.appendChild(ol); else trail.appendChild(el("p", "No audit events recorded.", "muted"));
    } catch (e) {
      if (S.openTrade === id) { trail.replaceChildren(); trail.appendChild(el("p", "Could not load the order trail: " + e.message, "loss")); }
    }
  }
  function closeTrade() {
    if ($("drawer").hidden) return;
    $("drawer").hidden = true; $("scrim").hidden = true; S.openTrade = null;
    document.body.style.overflow = "";
    if (S.opener && document.contains(S.opener)) S.opener.focus();
    S.opener = null;
  }
  // Keep Tab inside the open drawer.
  function trapFocus(ev) {
    if ($("drawer").hidden || ev.key !== "Tab") return;
    const items = $("drawer").querySelectorAll("button, [href], input, select, [tabindex]:not([tabindex='-1'])");
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && document.activeElement === first) { last.focus(); ev.preventDefault(); }
    else if (!ev.shiftKey && document.activeElement === last) { first.focus(); ev.preventDefault(); }
  }

  // ---------------------------------------------------------------- Research lanes (short-term and swing)
  // Both lanes are simulated share trades on the underlying in their own ledger. They share one renderer; the ids on
  // each page start with a prefix (st or sw) and each lane supplies its own wording.
  const ST_EXIT = { stop: "Stop", target: "Target", below_vwap: "Below VWAP", flat_by_close: "Closed for the day", carried_over: "Left over" };
  const SW_EXIT = { stop: "Stop", target: "Target", trend_break: "Trend broke", time: "Time stop" };
  const LANES = {
    st: {
      path: "/api/shortterm", exits: ST_EXIT, cadence: "Runs with the loop, on completed 5-minute bars",
      intro: "This is the day-trading experiment, kept apart from the long-term options book. It simulates buying shares of six liquid names when a fast trend line crosses above the day's average price, and selling when that fails. It places no orders. ",
      hint: "A trade needs a fresh crossing between 10:00 and 15:00 New York time on a name in the list.",
      why: (w) => "EMA " + w.ema + " crossed above VWAP " + w.vwap + " (was " + w.prev_ema + " under " + w.prev_vwap + ")",
    },
    sw: {
      path: "/api/swing", exits: SW_EXIT, cadence: "Checks about once an hour, on completed daily bars",
      intro: "This is the swing experiment, kept apart from the long-term options book. It simulates buying shares of liquid names after a pullback inside an uptrend, holds them for up to ten trading days, and sells at a stop, a target, a broken trend or the time limit. It places no orders. ",
      hint: "A trade needs an uptrend, a recent dip in momentum that is turning up, and no earnings in the way.",
      why: (w) => "Dip to RSI " + w.rsi_dip + ", now " + w.rsi + ". Stop " + w.stop + ", target " + w.target,
    },
  };
  function renderLane(p, d) {
    const L = LANES[p], sm = d.summary, id = (x) => $(p + "-" + x);
    id("lede").textContent = (d.enabled ? "" : "The lane is switched off. Turn it on under Controls. ") + L.intro +
      (sm.closed < sm.min_trades_for_evidence ? "With " + sm.closed + " closed trades it is far below the " + sm.min_trades_for_evidence + " needed before the result means anything." : "It has passed the minimum sample, which still does not show an edge on its own.") +
      (d.fictional ? " These trades come from fictional demo data." : "");
    id("status").textContent = d.enabled ? L.cadence : "Off";
    $("btn-" + p + "-step").disabled = !d.enabled;
    const f = id("summary");
    f.replaceChildren();
    kids(f, [
      fig(String(sm.total), "Simulated trades", sm.open + " open, " + sm.closed + " closed"),
      fig(sm.win_rate_pct === null ? "n/a" : sm.win_rate_pct + "%", "Winners", sm.closed ? sm.wins + " of " + sm.closed + " closed" : "no closed trades"),
      fig(sgn(sm.realized_pnl), "Realized", "simulated, after slippage", tone(sm.realized_pnl)),
    ]);
    const ended = (t) => t.status === "OPEN" ? el("span", "Open", "tag info") : el("span", L.exits[t.close_reason] || words(t.close_reason), "tag " + (t.pnl > 0 ? "gain" : "loss"));
    const host = id("table");
    if (phone.matches && d.trades.length) {
      host.replaceChildren();
      d.trades.forEach((t) => {
        const card = el("div", null, "tcard"), top = el("div", null, "tc-top"), mid = el("div", null, "tc-mid");
        top.appendChild(el("b", t.symbol)); top.appendChild(ended(t));
        mid.appendChild(el("span", t.pnl === null ? "Open" : sgn(t.pnl), "tc-pnl num " + tone(t.pnl)));
        if (t.pnl_pct !== null) mid.appendChild(el("span", pct(t.pnl_pct), "num " + tone(t.pnl_pct)));
        kids(card, [top, mid, el("div", t.quantity + " shares at " + Number(t.entry_price).toFixed(2) + (t.exit_price === null ? "" : ", sold at " + Number(t.exit_price).toFixed(2)) +
          ". Opened " + fmtTime(t.opened_at) + ". " + L.why(t.why_entered || {}) + ".", "muted")]);
        host.appendChild(card);
      });
    } else table(host, [
      { label: "Opened", get: (t) => fmtTime(t.opened_at) }, { label: "Name", get: (t) => el("b", t.symbol) },
      { label: "Shares", right: true, get: (t) => t.quantity }, { label: "Entry", right: true, get: (t) => Number(t.entry_price).toFixed(2) },
      { label: "Exit", right: true, get: (t) => t.exit_price === null ? "open" : Number(t.exit_price).toFixed(2) },
      { label: "Profit or loss", right: true, get: (t) => t.pnl === null ? "open" : span(sgn(t.pnl) + " (" + pct(t.pnl_pct) + ")", tone(t.pnl)) },
      { label: "How it ended", get: ended }, { label: "Why it entered", get: (t) => L.why(t.why_entered || {}) },
    ], d.trades, "No simulated trades yet", d.enabled ? L.hint : "Switch the lane on under Controls.");
    const r = id("rules"), l = id("limits");
    r.replaceChildren(); l.replaceChildren();
    d.rules.forEach((x) => r.appendChild(el("li", x)));
    d.limitations.forEach((x) => l.appendChild(el("li", x)));
  }
  async function loadShortterm() { renderLane("st", await api("/api/shortterm")); }
  async function loadSwing() { renderLane("sw", await api("/api/swing")); }

  // ---------------------------------------------------------------- Market scan
  const TABS = [{ id: "active", label: "Most active names" }, { id: "unusual", label: "Unusual options activity" }, { id: "options", label: "Option volume by name" }];
  function renderMarket() {
    const d = S.scan, res = d && d.result;
    const st = d && d.status;
    $("scan-lede").textContent = "A fixed list of about 75 liquid names ranked by dollar volume, and the option contracts trading far above their open interest. This is a screen for where to look, not a signal to trade.";
    $("scan-status").textContent = !st ? "" : st.running ? "Scanning now" : st.last_scan_at ? "Last scan " + fmtTime(st.last_scan_at) + (d.interval_s ? ", repeats every " + Math.round(d.interval_s / 60) + " minutes" : ", automatic scanning is off") : "No scan has run yet";
    $("btn-scan").disabled = !!(st && st.running);
    chips($("market-tabs"), TABS, S.marketTab, (id) => { S.marketTab = id; renderMarket(); }, "tab");
    $("scan-active-panel").hidden = S.marketTab !== "active";
    $("scan-unusual-panel").hidden = S.marketTab !== "unusual";
    $("scan-options-panel").hidden = S.marketTab !== "options";
    const notes = $("scan-notes");
    notes.replaceChildren();
    ((res && res.limitations) || []).forEach((x) => notes.appendChild(el("li", x)));
    if (res && res.fictional) notes.appendChild(el("li", "This scan ran on fictional demo data. The names and volumes are invented.", "warn"));
    if (res && res.errors && res.errors.length) notes.appendChild(el("li", "Problems during the scan: " + res.errors.slice(0, 6).join("; ")));
    if (!res) {
      ["scan-active", "scan-unusual", "scan-options"].forEach((id) => empty($(id), "No scan yet", "Choose Scan now, or set a scan interval in Controls."));
      return;
    }
    table($("scan-active"), [
      { label: "Rank", right: true, get: (r) => r.rank }, { label: "Name", get: (r) => el("b", r.symbol) },
      { label: "Close", right: true, get: (r) => money(r.close) },
      { label: "Day change", right: true, get: (r) => span(pct(r.change_pct), tone(r.change_pct)) },
      { label: "Dollar volume", right: true, get: (r) => "$" + (r.dollar_volume / 1e9 >= 1 ? (r.dollar_volume / 1e9).toFixed(1) + "B" : (r.dollar_volume / 1e6).toFixed(0) + "M") },
      { label: "Volume vs usual", right: true, get: (r) => r.relative_volume === null ? "n/a" : span(r.relative_volume.toFixed(1) + "x", r.surge ? "tag warn" : "") },
    ], res.active_names, "No ranked names", (res.errors || [])[0] || "The scan returned no daily bars.");

    chips($("scan-filters"), [{ id: "reviewable", label: "Tradable by the rules" }, { id: "all", label: "Everything unusual" }], S.unusualFilter, (id) => { S.unusualFilter = id; renderMarket(); });
    const un = res.unusual.filter((r) => S.unusualFilter === "all" || r.decision === "REVIEWABLE");
    table($("scan-unusual"), [
      { label: "Name", get: (r) => el("b", r.symbol) },
      { label: "Contract", get: (r) => el("span", (r.right === "C" ? "Call " : "Put ") + r.strike + ", " + fmtDay(r.expiry) + " (" + r.dte + "d)", "") },
      { label: "Volume", right: true, get: (r) => num(r.volume) },
      { label: "Open interest", right: true, get: (r) => r.open_interest === null ? "missing" : (r.oi_state === "REPORTED_ZERO" ? "zero" : num(r.open_interest)) },
      { label: "Volume / OI", right: true, get: (r) => r.volume_oi_ratio === null ? "no ratio" : r.volume_oi_ratio + "x" },
      { label: "Spread", right: true, get: (r) => r.spread_pct.toFixed(1) + "%" },
      { label: "Quoted turnover", right: true, get: (r) => "$" + num(r.quoted_turnover_usd) },
      { label: "Status", get: (r) => r.decision === "REVIEWABLE" ? el("span", "Reviewable", "tag info") : el("span", "Watch only: " + r.why_observe_only, "tag") },
    ], un, "Nothing unusual by these thresholds", "Thresholds: at least " + res.thresholds.min_volume + " contracts and volume at " + res.thresholds.min_volume_oi_ratio + "x open interest or more.");
    table($("scan-options"), [
      { label: "Name", get: (r) => el("b", r.symbol) }, { label: "Call volume", right: true, get: (r) => num(r.call_volume) },
      { label: "Put volume", right: true, get: (r) => num(r.put_volume) },
      { label: "Calls per put", right: true, get: (r) => r.call_put_ratio === null ? "no puts" : r.call_put_ratio },
      { label: "Unusual contracts", right: true, get: (r) => r.unusual_count }, { label: "Contracts read", right: true, get: (r) => r.contracts },
    ], res.option_names, "No option chains were read", (res.errors || [])[0] || "");
  }
  async function loadMarket() { S.scan = await api("/api/scan"); renderMarket(); }

  // ---------------------------------------------------------------- Agents
  const pctText = (v) => (v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + v + "%");
  function renderCommittee(c, votes) {
    const sum = $("committee-summary");
    const e = c.committee.WOULD_ENTER || { n: 0 }, r = c.committee.WOULD_REJECT || { n: 0 };
    sum.textContent = "The committee is in " + c.mode + " mode" + (c.mode === "shadow" ? " (it records votes but does not change orders)" : c.mode === "off" ? "" : "") + ". It uses " +
      Math.round(c.trust * 100) + "% of its allowed order size, and that share moves with its hit rate. Matured " + c.horizon_hours + "h outcomes: " +
      e.n + " entries" + (e.n ? " (" + pctText(e.mean_return_pct) + " avg)" : "") + ", " + r.n + " rejections" + (r.n ? " (" + pctText(r.mean_return_pct) + " avg if taken)" : "") + ".";
    const rows = Object.keys(c.weights).map((name) => {
      const a = c.agents[name] || { votes: {}, descriptive_only: true };
      const v = (s) => a.votes[s] ? a.votes[s].n + " calls, " + pctText(a.votes[s].mean_return_pct) + " avg, " + (a.votes[s].hit_rate === null ? "n/a" : Math.round(a.votes[s].hit_rate * 100) + "% rose") : "none yet";
      return { name, weight: c.weights[name], support: v("SUPPORT"), oppose: v("OPPOSE"), note: a.descriptive_only ? "too few outcomes to judge" : "" };
    });
    table($("committee-agents"), [
      { label: "Agent", get: (x) => el("b", x.name) }, { label: "Learned weight", right: true, get: (x) => Number(x.weight).toFixed(2) },
      { label: "After it supported", get: (x) => x.support }, { label: "After it opposed", get: (x) => x.oppose }, { label: "Note", get: (x) => x.note },
    ], rows, "No agents");
    const latest = [], seen = {};
    votes.forEach((d) => { if (d.contract && !seen[d.contract] && latest.length < 8) { seen[d.contract] = 1; latest.push(d); } });
    table($("committee-votes"), [
      { label: "Time", get: (d) => fmtTime(d.ts) }, { label: "Contract", get: (d) => el("span", d.contract, "mono") },
      { label: "Result", get: (d) => el("span", d.disposition === "WOULD_ENTER" ? "Would enter" : "Would reject", "tag " + (d.disposition === "WOULD_ENTER" ? "gain" : "")) },
      { label: "How each voted", get: (d) => { const w = el("div", null, "votes"); ((d.payload && d.payload.verdicts) || []).forEach((v) => w.appendChild(voteChip(v))); return w; } },
      { label: "Net", right: true, get: (d) => d.payload && d.payload.net_score !== undefined ? Number(d.payload.net_score).toFixed(2) : "" },
    ], latest, "No votes recorded yet", "Votes appear after the first cycle that finds a candidate.");
    const ul = $("committee-lessons"); ul.replaceChildren();
    (c.lessons.length ? c.lessons : ["No matured mistakes to learn from yet. Outcomes are scored four hours after each vote."]).forEach((t) => ul.appendChild(el("li", t)));
    table($("committee-history"), [
      { label: "Time", get: (h) => fmtTime(h.ts) }, { label: "Agent", get: (h) => h.agent }, { label: "Change", get: (h) => h.note },
    ], c.history, "No weight has moved yet");
  }
  async function loadAgents() {
    const [c, votes] = await Promise.all([api("/api/committee"), api("/api/journal?kind=COMMITTEE&limit=200")]);
    renderCommittee(c, votes);
  }

  // ---------------------------------------------------------------- Research
  function renderResearch(list) {
    table($("research"), [
      { label: "Id", get: (h) => h.id }, { label: "Hypothesis", get: (h) => h.statement },
      { label: "Status", get: (h) => h.status + (h.intact ? "" : " (RECORD TAMPERED)") },
      { label: "Min trades", get: (h) => (h.criteria.min_trades || "") + " total / " + (h.criteria.min_oos_trades || "") + " out-of-sample" },
      { label: "Evaluations", right: true, get: (h) => h.evaluations },
    ], list, "No experiments registered", "Register one with: python -m optplat.research register. The baseline stays frozen.");
  }
  async function loadResearch() { renderResearch(await api("/api/research/hypotheses")); }

  // ---------------------------------------------------------------- refresh loop
  async function loadPage() {
    const page = route();
    if (page === "trades") await loadTrades();
    else if (page === "swing") await loadSwing();
    else if (page === "shortterm") await loadShortterm();
    else if (page === "market") await loadMarket();
    else if (page === "agents") await loadAgents();
    else if (page === "research") await loadResearch();
  }

  async function refresh() {
    if (!token) { S.connected = false; showPage(); return; }
    try {
      const [health, status, portfolio, orders, report, decisions, eq] = await Promise.all([
        fetch("/api/health").then((r) => r.json()),
        api("/api/engine/status"), api("/api/portfolio"), api("/api/paper/orders"), api("/api/report"),
        api("/api/journal?limit=15"), api("/api/equity"),
      ]);
      S.connected = true; S.core = { status, report };
      showPage();
      renderStrip(health, status, portfolio);
      renderTrust(status);
      renderDesk(portfolio, report, eq, status);
      renderPositions(report, status.config);
      renderDecisions(decisions);
      renderOrders(orders);
      syncControls(status, status.config);
      await loadPage();
      setMsg("");
    } catch (e) {
      if (e.status === 401 || e.status === 403) { S.connected = false; showPage(); setMsg("The token was not accepted. Paste the one the server printed.", "loss"); }
      else if (S.connected) { $("updated").textContent = "Could not refresh: " + e.message; }
      else setMsg("Error: " + e.message, "loss");
    }
  }

  async function act(fn) { try { await fn(); } catch (e) { $("updated").textContent = "Error: " + e.message; } await refresh(); }

  $("btn-connect").addEventListener("click", () => {
    token = $("token").value.trim();
    try { sessionStorage.setItem("optplat_token", token); } catch (e) { /* ignore */ }
    $("token").value = "";
    refresh();
  });
  $("btn-table").addEventListener("click", () => {
    const t = $("equity-table"), showing = t.hidden;
    t.hidden = !showing; $("equity-chart").hidden = showing;
    $("btn-table").textContent = showing ? "Show as chart" : "Show as table";
  });
  $("btn-cycle").addEventListener("click", () => act(() => api("/api/engine/cycle", { method: "POST" })));
  $("btn-start").addEventListener("click", () => act(() => api("/api/engine/start", { method: "POST" })));
  $("btn-stop").addEventListener("click", () => act(() => api("/api/engine/stop", { method: "POST" })));
  $("btn-kill").addEventListener("click", () => act(() =>
    api("/api/risk/kill-switch", { method: "POST", body: JSON.stringify({ active: !S.killState, reason: "dashboard" }) })));
  $("btn-save").addEventListener("click", () => act(() => api("/api/engine/config", {
    method: "PUT",
    body: JSON.stringify({
      auto_entries: $("cfg-entries").checked, auto_exits: $("cfg-exits").checked,
      enforce_market_hours: $("cfg-hours").checked, committee_mode: $("cfg-committee").value,
      scan_interval_s: Number($("cfg-scan").value), shortterm_enabled: $("cfg-shortterm").checked, swing_enabled: $("cfg-swing").checked,
      watchlist: $("cfg-watch").value.split(/[,\s]+/).filter(Boolean),
    }),
  })));
  $("btn-sw-step").addEventListener("click", () => act(async () => { await api("/api/swing/step", { method: "POST" }); }));
  $("btn-st-step").addEventListener("click", () => act(async () => { await api("/api/shortterm/step", { method: "POST" }); }));
  $("btn-scan").addEventListener("click", () => act(async () => {
    await api("/api/scan/run", { method: "POST" });
    // The scan runs in the background; check back every few seconds until it finishes.
    let tries = 0;
    const poll = async () => {
      tries += 1;
      try { await loadMarket(); } catch (e) { return; }
      if (S.scan && S.scan.status.running && tries < 30) setTimeout(poll, 3000);
    };
    setTimeout(poll, 2000);
  }));
  $("trade-search").addEventListener("input", (ev) => { S.query = ev.target.value; renderTrades(); });
  $("btn-drawer-close").addEventListener("click", closeTrade);
  $("scrim").addEventListener("click", closeTrade);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeTrade(); trapFocus(ev); });
  const onBreak = () => { if (S.trades && route() === "trades") renderTrades(); if (route() === "shortterm") loadShortterm().catch(() => {}); if (route() === "swing") loadSwing().catch(() => {}); };
  if (phone.addEventListener) phone.addEventListener("change", onBreak); else if (phone.addListener) phone.addListener(onBreak);
  window.addEventListener("hashchange", () => { showPage(); if (S.connected && route() === "desk" && !$("equity-chart").hidden) drawEquity($("equity-chart"), S.lastPoints); if (S.connected) loadPage().catch((e) => { $("updated").textContent = "Error: " + e.message; }); });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (route() === "desk" && !$("equity-chart").hidden) drawEquity($("equity-chart"), S.lastPoints); }, 150);
  });
  showPage();
  refresh();
  setInterval(refresh, 10000);
})();
