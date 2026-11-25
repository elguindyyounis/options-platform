(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const phone = window.matchMedia("(max-width:860px)");
  const PAGES = ["desk", "trades", "lanes", "options", "swing", "shortterm", "market", "context", "tracker", "agents", "research", "system"];
  // The token is kept in this browser's local storage for this address (127.0.0.1 only), so a new tab, a refresh or a restart of
  // the browser stays connected. It is never sent anywhere except as the API header. An older session-only copy is moved over.
  const TOKEN_KEY = "optplat_token";
  function loadToken() {
    try { const t = localStorage.getItem(TOKEN_KEY); if (t) return t; } catch (e) { /* storage unavailable */ }
    try { const t = sessionStorage.getItem(TOKEN_KEY); if (t) { saveToken(t); return t; } } catch (e) { /* storage unavailable */ }
    return "";
  }
  function saveToken(t) {
    try { localStorage.setItem(TOKEN_KEY, t); } catch (e) { /* storage unavailable: this tab still works until it closes */ }
    try { sessionStorage.setItem(TOKEN_KEY, t); } catch (e) { /* ignore */ }
  }
  function forgetToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
  }
  let token = loadToken();
  // The launcher opens /#token=... . A URL fragment is never sent to the server. Read it once, keep it, then remove it
  // from the address bar so it is not left in the URL or copied by accident.
  function takeTokenFromUrl() {
    const m = /^#token=([A-Za-z0-9_-]{16,200})$/.exec(location.hash);
    if (!m) return false;
    token = m[1];
    saveToken(token);
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* ignore */ }
    return true;
  }
  takeTokenFromUrl();
  const S = {
    killState: false, lastPoints: [], core: null, connected: false,
    trades: null, filter: "all", kind: "all", source: "all", query: "", sort: { key: "opened_at", dir: -1 }, shown: 100, tkH: "3", openTrade: null, opener: null,
    decFilter: "key", decShown: 8, decisions: [], scan: null, marketTab: "heat", unusualFilter: "all", opt: null, optLane: "shortterm-options-base",
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
    document.title = (S.connected ? ({ desk: "Desk", trades: "Trades", lanes: "Lanes", options: "Options lanes", swing: "Swing", shortterm: "Short-term", market: "Market", context: "Context", tracker: "Tracker", agents: "Agents", research: "Lab", system: "System" })[page] + " - " : "") + "options-platform";
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
    const W = Math.max(300, Math.round(host.clientWidth || 720)), H = W < 520 ? 170 : 190;
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
  // Contract names read like a person would say them: "SPY call 751 · Dec 11". An OCC symbol such as
  // "SPY   261211P00751000" is split into those parts; if it cannot be read, the raw text is shown, never a guess.
  function occParts(occ) {
    const m = /^\s*([A-Z.\-]{1,6}?)\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})\s*$/.exec(occ || "");
    if (!m) return null;
    return { symbol: m[1], expiry: "20" + m[2] + "-" + m[3] + "-" + m[4], right: m[5], strike: Number(m[6]) / 1000 };
  }
  const expiryText = (iso) => {
    const d = new Date(iso + "T12:00:00");
    if (isNaN(d)) return String(iso);
    return d.toLocaleDateString(undefined, d.getFullYear() === new Date().getFullYear() ? { month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" });
  };
  const contractText = (t) => t.symbol + " " + (t.right === "C" ? "call " : "put ") + Number(t.strike) + " · " + expiryText(t.expiry);
  function ticket(t) {
    const w = el("span", null, "ticket");
    w.setAttribute("title", contractText(t));
    w.appendChild(el("span", t.symbol, "sym"));
    w.appendChild(el("span", (t.right === "C" ? "call " : "put ") + Number(t.strike), "leg " + (t.right === "C" ? "call" : "put")));
    w.appendChild(el("span", expiryText(t.expiry), "muted"));
    return w;
  }
  function ticketOcc(occ) {
    const p = occParts(occ);
    return p ? ticket(p) : el("span", occ || "", "mono");
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
    $("updated").textContent = "Updated " + new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) +
      (health.build_id && health.build_id !== "unknown" ? " - build " + health.build_id : "");
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
    if (status.clock && status.clock.warning) reasons.push(status.clock.warning);
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
    row("Computer clock", status.clock && status.clock.behind_s != null ? (status.clock.behind_s >= 1 ? status.clock.behind_s + "s behind the market data" : "in step with the market data") : "not measured yet");
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
    // Headline is realized profit and loss, not the account balance: a balance of $100,000 with nothing traded says nothing.
    const dv = $("desk-value");
    dv.textContent = report.closed_trades ? sgn(report.realized_pnl) : "No closed trades yet";
    dv.className = "hero-value num " + (report.closed_trades ? tone(report.realized_pnl) : "muted");
    const ch = $("desk-change");
    ch.replaceChildren();
    ch.appendChild(span(report.closed_trades ? "After fees, " + report.closed_trades + " closed" + (report.win_rate_pct === null ? "" : ", " + report.win_rate_pct + "% winners") : "Nothing has been bought and sold yet", "muted"));
    const fict = eq.fictional ? " Fictional demo data." : "";
    $("desk-headline").textContent = "Holds " + report.open.length + " open position" + (report.open.length === 1 ? "" : "s") + " and has closed " + report.closed_trades + " trade" + (report.closed_trades === 1 ? "" : "s") + "." + fict;
    const need = Math.max(0, MIN_TRADES - report.closed_trades);
    $("desk-sub").textContent = "This is the long-term book: options bought with at least a week to expiry and held until an exit rule fires. " +
      (need ? "With " + report.closed_trades + " closed trades, none of these numbers is evidence yet; " + MIN_TRADES + " is the minimum." : "The sample is past the minimum, which still does not show an edge on its own.");
    const t = $("tiles");
    t.replaceChildren();
    t.className = "kpis";
    const kpi = (v, l, sub, cls) => { const k = el("div", null, "kpi " + (cls || "")); k.appendChild(el("div", v, "v num")); k.appendChild(el("div", l, "l")); if (sub) k.appendChild(el("div", sub, "s")); return k; };
    kids(t, [
      kpi(String(report.open.length), "Open positions", money(a.open_premium) + " at cost"),
      kpi(String(report.closed_trades), "Closed trades", "minimum " + MIN_TRADES + " before judging"),
      kpi(report.win_rate_pct === null ? "n/a" : report.win_rate_pct + "%", "Winners", report.closed_trades ? "of closed trades" : "no closed trades"),
      kpi(sm.current_drawdown_pct === null ? "n/a" : "-" + sm.current_drawdown_pct + "%", "Below its peak", "worst -" + (sm.max_drawdown_pct || 0) + "%"),
      kpi(money(a.equity) + (a.carried_at_cost > 0 ? " (estimate)" : ""), "Paper balance", "cash " + money(a.cash) + (a.carried_at_cost > 0 ? "; " + a.carried_at_cost + " open position(s) have no bid and are counted at cost, so a loss on them is not in this number" : report.closed_trades ? "" : "; untouched"), "dim"),
    ]);
    $("sample").textContent = report.caveat;
    S.lastPoints = eq.points;
    drawEquity($("equity-chart"), eq.points);
    table($("equity-table"), [
      { label: "Time", get: (p) => p.ts.slice(0, 19) }, { label: "Equity", right: true, get: (p) => money(p.equity) },
    ], eq.points.slice().reverse().slice(0, 200), "No equity points yet");
  }

  // Every account and lane on the front page, so results do not hide behind the other pages. Each row is one ledger;
  // lanes are research with their own sizing and simulated fills, so the total is simulated dollars, not an account balance.
  // Open P&L for one account row. A trade with no usable bid adds nothing to the sum, so say it is partial.
  function openNow(r, prefix) {
    if (r.open_complete === false) return span(prefix + sgn(r.open_pnl) + " (partial, " + r.open_unmarked + " unmarked)", "muted");
    return span(prefix + arrow(r.open_pnl) + sgn(r.open_pnl), tone(r.open_pnl));
  }
  function renderAccounts(data) {
    const host = $("all-accounts"), note = $("all-accounts-note");
    if (!data) { empty(host, "Could not load the lanes", "Trades from every lane appear here once the page can reach /api/alltrades."); note.textContent = ""; return; }
    const kind = (x) => (x.source === "main" ? "Options account" : x.source === "challenge-10x" ? "10x challenge" : x.instrument === "options" ? "Options lane" : "Shares lane");
    const sources = data.sources.slice();
    // The paper account always has a row, even before it has taken a trade.
    if (!sources.some((x) => x.source === "main")) sources.push({ source: "main", label: "Options account", instrument: "options", total: 0, open: 0, closed: 0, wins: 0, win_rate_pct: null, realized_pnl: 0, open_pnl: 0 });
    const rows = sources.sort((a, b) => (a.source === "main" ? -1 : b.source === "main" ? 1 : b.realized_pnl - a.realized_pnl));
    const all = data.summary.all;
    const goTo = (src) => { S.source = src; S.kind = "all"; S.filter = "all"; S.shown = 100; location.hash = "#/trades"; };
    rows.unshift({ source: "", label: "All together", total: all.total, open: all.open, closed: all.closed, wins: all.wins, win_rate_pct: all.win_rate_pct, realized_pnl: all.realized_pnl, open_pnl: all.open_pnl, instrument: "", total_row: true });
    host.replaceChildren();
    const maxAbs = Math.max(1, ...rows.filter((r) => !r.total_row).map((r) => Math.abs(r.realized_pnl) + Math.abs(r.open_pnl || 0)));
    rows.forEach((r) => {
      const card = el("button", null, "lane-card" + (r.total_row ? " total" : "") + (r.source === "main" ? " main" : ""));
      card.type = "button";
      if (r.total_row) card.disabled = true; else card.addEventListener("click", () => goTo(r.source));
      const head = el("div", null, "lc-head");
      head.appendChild(el("span", r.label, "lc-name"));
      if (!r.total_row && kind(r) !== r.label) head.appendChild(el("span", kind(r), "tag"));
      const big = el("div", null, "lc-big num");
      big.appendChild(span(arrow(r.realized_pnl) + sgn(r.realized_pnl), tone(r.realized_pnl)));
      big.appendChild(el("small", " realized", "muted"));
      const open = el("div", null, "lc-open num");
      open.appendChild(el("span", "Open ", "muted")); open.appendChild(openNow(r, ""));
      const foot = el("div", r.open + " open, " + r.closed + " closed" + (r.win_rate_pct === null ? "" : ", " + r.win_rate_pct + "% winners"), "lc-foot muted");
      const kidsList = [head, big, open];
      if (!r.total_row) {
        // A small bar: the share of the largest lane's size, split into closed (solid) and open (faded) results.
        const bar = el("div", null, "lc-bar");
        const seg = (v, cls) => { const i = el("i", null, cls + (v < 0 ? " neg" : " pos")); i.style.width = Math.round(Math.abs(v) / maxAbs * 100) + "%"; return i; };
        bar.appendChild(seg(r.realized_pnl, "done")); if (r.open_pnl) bar.appendChild(seg(r.open_pnl, "live"));
        kidsList.push(bar);
      }
      kidsList.push(foot);
      kids(card, kidsList);
      host.appendChild(card);
    });
    note.textContent = "Realized is after fees on closed trades; open is marked at the bid. The options account is the only one that trades the paper broker. Lanes and the challenge are experiments with their own sizes and simulated fills, so the total adds simulated dollars and is not an account balance." + (data.fictional ? " Fictional demo data." : "") + " Small samples prove nothing.";
  }

  // An OCC symbol (padded or not) -> days to expiry. Anything unparseable is shown as unknown, never guessed.
  function dteOf(contract, now) {
    const p = occParts(contract);
    if (!p) return null;
    const exp = Date.parse(p.expiry + "T00:00:00Z");
    return Math.round((exp - Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())) / 86400000);
  }

  // One card per open position: the contract in words, how it is doing, and a ladder from the stop to the target
  // with a tick at what was paid and a marker at the current bid, so "how close is this to exiting" reads at a glance.
  function renderPositions(report, cfg, plans) {
    const host = $("positions"), now = new Date();
    if (!report.open.length) { host.replaceChildren(); const box = el("div", null, "panel"); host.appendChild(box); empty(box, "No open positions", "When an entry fills it appears here with the prices that would close it."); return; }
    host.replaceChildren();
    const grid = el("div", null, "pos-grid");
    report.open.forEach((r) => {
      const card = el("div", null, "pos"), top = el("div", null, "pos-top");
      const d = dteOf(r.contract, now);
      kids(top, [ticketOcc(r.contract), el("span", d === null ? "expiry unknown" : d + " days left" + (d <= cfg.min_dte_to_hold ? ", in the forced-exit zone" : ""), "tag " + (d !== null && d <= cfg.min_dte_to_hold ? "warn" : ""))]);
      const pnl = el("div", null, "pos-pnl");
      if (r.unrealized_pnl === null) pnl.appendChild(el("span", "No quote to mark it", "muted"));
      else {
        const p = r.avg_cost > 0 && r.mark !== null ? (r.mark / r.avg_cost - 1) * 100 : null;
        kids(pnl, [span(arrow(r.unrealized_pnl) + sgn(r.unrealized_pnl), "big " + tone(r.unrealized_pnl)), p === null ? span("") : span(pct(p), "num " + tone(p))]);
      }
      const facts = el("div", r.quantity + " contract" + (r.quantity === 1 ? "" : "s") + " at " + r.avg_cost + (r.mark === null ? "" : ", bid now " + r.mark), "muted");
      kids(card, [top, pnl, facts]);
      if (cfg.auto_exits) {
        const stop = r.avg_cost * (1 - cfg.stop_loss_pct / 100), goal = r.avg_cost * (1 + cfg.take_profit_pct / 100), span_ = goal - stop;
        const at = (v) => Math.max(0, Math.min(100, ((v - stop) / span_) * 100));
        const lad = el("div", null, "ladder"), track = el("div", null, "track"), cost = el("div", null, "cost");
        cost.style.left = at(r.avg_cost) + "%";
        lad.appendChild(track); lad.appendChild(cost);
        if (r.mark !== null) { const m = el("div", null, "now"); m.style.left = at(r.mark) + "%"; lad.appendChild(m); }
        lad.setAttribute("role", "img");
        lad.setAttribute("aria-label", "Stop " + stop.toFixed(2) + ", paid " + r.avg_cost + ", take profit " + goal.toFixed(2) + (r.mark === null ? ", no current quote" : ", bid now " + r.mark));
        const keys = el("div", null, "ladder-keys");
        [["stop", stop.toFixed(2)], ["paid", String(r.avg_cost)], ["target", goal.toFixed(2)]].forEach((k) => { const s2 = el("span"); s2.appendChild(document.createTextNode(k[0] + " ")); s2.appendChild(el("b", k[1])); keys.appendChild(s2); });
        kids(card, [lad, keys]);
      } else card.appendChild(el("div", "Automatic exits are off, so nothing will close this on its own.", "muted"));
      card.appendChild(el("div", "Take-profit when bid reaches " + planFor(plans, r.contract, "take_profit_bid") + "; stop when bid falls to " +
        planFor(plans, r.contract, "stop_loss_bid") + "; leaves for expiry by " + expiryExit(plans, r.contract) + ".", "muted"));
      grid.appendChild(card);
    });
    host.appendChild(grid);
    host.appendChild(el("p", cfg.auto_exits
      ? "Automatic exits are ON: the loop sells at these levels using the bid, if a fresh quote exists. No fresh quote means no exit and a warning, never a guess. Levels are rules, not predictions."
      : "Automatic exits are OFF: nothing sells by itself. The levels shown are what the rules would use if you turned exits on.", "muted"));
  }

  function whyOf(d) {
    const p = d.payload || {};
    if (p.risk_failures && p.risk_failures.length) return p.risk_failures.join("; ");
    return p.why || p.reason || (p.reasons && p.reasons.join("; ")) || (p.score !== undefined ? "score " + Number(p.score).toFixed(2) : "");
  }
  // One plain verdict per journal line so "taken or skipped, and why" reads in one feed. Pure function of the record.
  // Anything not recognised is shown as "Other" with its raw name, never as taken or fine.
  function decisionVerdict(d) {
    const disp = String((d && d.disposition) || ""), kind = String((d && d.kind) || "");
    if (kind === "EXIT") return /FILLED|SUBMITTED/.test(disp) ? { id: "exit", text: "Exit placed (paper)" } : { id: "skipped", text: "Exit not placed" };
    if (disp === "FILLED") return { id: "taken", text: "Taken (paper fill)" };
    if (disp === "WOULD_ENTER") return { id: "opinion", text: "Committee would enter (opinion, no order)" };
    if (disp === "WOULD_REJECT") return { id: "blocked", text: "Committee would reject" };
    if (/REJECTED|ERROR/.test(disp)) return { id: "blocked", text: "Blocked" };
    if (/^SKIPPED|^NOT_CHOSEN|^KEY_CONFLICT/.test(disp)) return { id: "skipped", text: "Skipped" };
    if (/SUBMITTED|PARTIALLY_FILLED|RISK_APPROVED/.test(disp)) return { id: "pending", text: "Order in progress" };
    return { id: "other", text: "Other: " + (disp || "unknown") };
  }
  function decisionTally(list) {
    const c = {};
    (list || []).forEach((d) => { const v = decisionVerdict(d).id; c[v] = (c[v] || 0) + 1; });
    const names = { taken: "taken", exit: "exits placed", blocked: "blocked", skipped: "skipped", opinion: "opinion only", pending: "in progress", other: "other" };
    const parts = Object.keys(names).filter((k) => c[k]).map((k) => c[k] + " " + names[k]);
    return parts.length ? "Latest " + list.length + ": " + parts.join(", ") + "." : "";
  }
  // Filter groups for the feed. "Orders placed" is the only group that is a paper order; opinions never count as one.
  const DEC_FILTERS = [
    { id: "key", label: "Orders and blocks", ids: ["taken", "exit", "pending", "blocked"] }, { id: "all", label: "All", ids: null }, { id: "placed", label: "Orders placed (paper)", ids: ["taken", "exit", "pending"] },
    { id: "notaken", label: "Blocked or skipped", ids: ["blocked", "skipped"] }, { id: "opinion", label: "Opinions only", ids: ["opinion"] },
    { id: "other", label: "Other", ids: ["other"] },
  ];
  function filterDecisions(list, filterId) {
    const f = DEC_FILTERS.find((x) => x.id === filterId) || DEC_FILTERS.find((x) => x.id === "all");
    return (list || []).filter((d) => !f.ids || f.ids.indexOf(decisionVerdict(d).id) >= 0);
  }
  // Activity feed: what mattered (orders, exits, blocks, opinions) is listed; runs of routine skips fold into one line
  // that can be opened. Skips are the bulk of every cycle and carry the least news, so they must not push the page down.
  const DEC_SHOWN = 8;
  function renderDecisions(all) {
    const host = $("decisions");
    if (!all.length) { empty(host, "No decisions recorded yet", "Run one cycle from Controls to see what it considers."); return; }
    S.decisions = all;
    host.replaceChildren();
    const bar = el("div", null, "chips");
    chips(bar, DEC_FILTERS.map((f) => ({ id: f.id, label: f.label + " " + filterDecisions(all, f.id).length })), S.decFilter, (id) => { S.decFilter = id; S.decShown = DEC_SHOWN; renderDecisions(S.decisions); });
    host.appendChild(bar);
    const tally = decisionTally(all);
    if (tally) host.appendChild(el("p", tally, "muted"));
    const list = filterDecisions(all, S.decFilter);
    if (!list.length) host.appendChild(el("p", S.decFilter === "key" ? "No orders or blocks among the latest " + all.length + " lines. Choose All to see the skips." : "Nothing in this group among the latest " + all.length + " lines.", "muted"));
    // fold consecutive skipped lines
    const items = [];
    list.forEach((d) => {
      const isSkip = decisionVerdict(d).id === "skipped", last = items[items.length - 1];
      if (isSkip && last && last.skips) last.skips.push(d); else if (isSkip) items.push({ skips: [d] }); else items.push({ d });
    });
    const feed = el("div", null, "feed");
    const limit = S.decShown || DEC_SHOWN;
    items.slice(0, limit).forEach((it) => {
      if (it.skips) {
        const det = el("details", null, "skipfold");
        const sum = el("summary", null, "feed-item");
        const why = it.skips.map(whyOf).filter(Boolean);
        kids(sum, [el("span", fmtTime(it.skips[0].ts), "feed-time"), el("span", it.skips.length + " routine skip" + (it.skips.length === 1 ? "" : "s"), "muted"), el("span", "show", "tag")]);
        det.appendChild(sum);
        const inner = el("div", null, "skip-list");
        it.skips.forEach((d, i) => {
          const row = el("div", null, "ticket");
          if (d.contract) row.appendChild(ticketOcc(d.contract)); else if (d.symbol) row.appendChild(el("b", d.symbol));
          if (why[i]) row.appendChild(el("span", why[i], "muted"));
          inner.appendChild(row);
        });
        det.appendChild(inner);
        feed.appendChild(det);
        return;
      }
      const d = it.d, item = el("div", null, "feed-item");
      const who = el("div", null, "ticket");
      who.appendChild(el("span", words(d.kind), "muted"));
      if (d.contract) who.appendChild(ticketOcc(d.contract)); else if (d.symbol) who.appendChild(el("b", d.symbol));
      const v = decisionVerdict(d);
      const tag = el("span", v.text + (d.fictional ? " (fictional)" : ""), "tag " + (v.id === "taken" || v.id === "exit" ? "info" : v.id === "blocked" ? "warn" : ""));
      kids(item, [el("span", fmtTime(d.ts), "feed-time"), who, tag]);
      const why = whyOf(d);
      item.appendChild(el("div", why ? "Rule: " + why : "No reason was recorded for this line (" + words(d.disposition) + ").", "feed-why"));
      feed.appendChild(item);
    });
    host.appendChild(feed);
    if (items.length > limit) {
      const more = el("button", "Show " + (items.length - limit) + " more", "linkbtn");
      more.type = "button";
      more.addEventListener("click", () => { S.decShown = limit + DEC_SHOWN; renderDecisions(S.decisions); });
      host.appendChild(more);
    }
  }

  function renderOrders(orders) {
    table($("orders"), [
      { label: "Time", get: (o) => fmtTime(o.created_at) }, { label: "Side", get: (o) => o.intent.side },
      { label: "Contract", get: (o) => ticket({ symbol: o.intent.contract.underlying, right: o.intent.contract.right, strike: o.intent.contract.strike, expiry: o.intent.contract.expiry }) },
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
    $("cfg-optlanes").checked = !!cfg.option_lanes_enabled;
    $("cfg-hours").checked = status.market.hours_enforced;
    $("cfg-hours").disabled = status.market.hours_enforced && !status.data_source.fictional; // real data: always on
    if (document.activeElement !== $("cfg-watch") && !S.watchDirty) $("cfg-watch").value = status.config.watchlist.join(", ");
    const secSel = $("cfg-sector");
    if (secSel.options.length !== (status.sectors || []).length + 1) {
      secSel.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "Add names from a sector" }));
      (status.sectors || []).forEach((n) => secSel.appendChild(Object.assign(document.createElement("option"), { value: n, textContent: n })));
    }
    const sel = $("cfg-scan"), v = String(cfg.scan_interval_s === undefined ? 0 : cfg.scan_interval_s);
    if (document.activeElement !== sel) {
      if (!Array.prototype.some.call(sel.options, (o) => o.value === v)) sel.appendChild(Object.assign(document.createElement("option"), { value: v, textContent: "every " + Math.round(Number(v) / 60) + " minutes" }));
      sel.value = v;
    }
    if (document.activeElement !== $("cfg-committee")) $("cfg-committee").value = cfg.committee_mode;
  }

  // ---------------------------------------------------------------- Trades
  // One list for every simulated trade: the long-term options account, the options lanes, the 10x challenge and the
  // two share lanes. Each row says which of those took it and whether it was options or shares.
  const FILTERS = [
    { id: "all", label: "All", test: () => true }, { id: "open", label: "Open", test: (t) => t.status !== "CLOSED" },
    { id: "closed", label: "Closed", test: (t) => t.status === "CLOSED" },
    { id: "winners", label: "Winners", test: (t) => t.status === "CLOSED" && t.pnl > 0 },
    { id: "losers", label: "Losers", test: (t) => t.status === "CLOSED" && t.pnl <= 0 },
  ];
  const KINDS = [{ id: "all", label: "Options and shares" }, { id: "options", label: "Options" }, { id: "shares", label: "Shares" }];
  const SORTS = {
    opened_at: (t) => t.opened_at || "", symbol: (t) => t.symbol, pnl: (t) => (t.pnl === null ? -Infinity : t.pnl),
    pnl_pct: (t) => (t.pnl_pct === null ? -Infinity : t.pnl_pct), held: (t) => (t.held_seconds === null ? Infinity : t.held_seconds),
    kind: (t) => t.instrument + " " + (t.opened_at || ""), source: (t) => t.source_label,
  };
  const instrumentTag = (t) => el("span", t.instrument === "options" ? "Options" : "Shares", "tag " + (t.instrument === "options" ? "info" : ""));
  const tradeName = (t) => (t.instrument === "options" && t.right ? ticket(t) : el("b", t.symbol, "sym"));

  function pnlCell(t) {
    const w = el("span", null, "num");
    if (t.pnl === null) { w.textContent = t.status === "CLOSED" ? "n/a" : "no quote yet"; w.className = "muted"; return w; }
    w.appendChild(span(sgn(t.pnl) + (t.pnl_pct === null ? "" : " (" + pct(t.pnl_pct) + ")"), tone(t.pnl)));
    const bar = el("span", null, "bar"), i = el("i", null, t.pnl >= 0 ? "up" : "down");
    i.style.width = Math.min(50, Math.abs(t.pnl_pct || 0) / 2) + "%";
    bar.appendChild(i);
    w.appendChild(bar);
    return w;
  }
  function laneExitLabel(t) {
    const code = t.exit_reason;
    return t.status === "OPEN" ? "Open" : t.status === "PARTIAL" ? "Partly closed" : (EXIT_TEXT[code] || OP_EXIT[code] || ST_EXIT[code] || SW_EXIT[code] || (code ? words(code) : "Closed"));
  }
  function statusTag(t) {
    const label = laneExitLabel(t);
    if (t.status !== "CLOSED") return el("span", label, "tag info");
    return el("span", label, "tag " + (t.pnl > 0 ? "gain" : "loss"));
  }
  const openedText = (t) => fmtTime(t.opened_at);
  const exitText = (t) => (t.exit_price !== null ? Number(t.exit_price).toFixed(2) : (t.mark !== null && t.mark !== undefined ? Number(t.mark).toFixed(2) + " (mark)" : "no quote"));
  const heldText = (t) => duration(t.held_seconds !== null ? t.held_seconds : Math.floor((Date.now() - new Date(t.opened_at).getTime()) / 1000));

  // What opens when a row is chosen: the order-trail drawer for the options account, an inline file for lane trades.
  function laneDetail(t) {
    const d = t.detail;
    if (t.instrument === "options") return tradeItem(Object.assign({}, d, { symbol: t.symbol }), Object.assign({}, OP_EXIT));
    const box = el("div", null, "pm-body"), facts = el("dl", null, "facts");
    const row = (k, v) => { facts.appendChild(el("dt", k)); facts.appendChild(el("dd", v)); };
    const lane = t.source === "swing-pullback" ? LANES.sw : LANES.st;
    row("Opened", fmtTime(t.opened_at));
    row("Bought", t.quantity + " shares at " + Number(t.entry_price).toFixed(2));
    if (t.exit_price !== null) row("Sold", Number(t.exit_price).toFixed(2) + " on " + fmtTime(t.closed_at));
    row("Why it entered", lane.why(d.why_entered || {}));
    if (t.status === "CLOSED") row("How it ended", d.close_text || laneExitLabel(t));
    box.appendChild(facts);
    return box;
  }
  function attachRow(node, t, onOpen) {
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", "Open " + (t.instrument === "options" ? contractText(t) : t.symbol + " shares") + " from " + t.source_label);
    node.addEventListener("click", onOpen);
    node.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onOpen(); } });
  }
  function toggleInline(after, t, colspan) {
    const nxt = after.nextSibling;
    if (nxt && nxt.classList && nxt.classList.contains("inline-file")) { nxt.remove(); return; }
    const holder = colspan ? el("tr", null, "inline-file") : el("div", null, "inline-file");
    let cell = holder;
    if (colspan) { cell = el("td"); cell.colSpan = colspan; holder.appendChild(cell); }
    cell.appendChild(laneDetail(t));
    const det = cell.querySelector("details");
    if (det) det.open = true;
    after.after(holder);
  }
  function openRow(t, node, colspan) {
    if (t.has_file) openTrade(t.id, node);
    else if (t.instrument === "options" && t.detail) openLaneTrade(t, node);
    else toggleInline(node, t, colspan);
  }
  // The trade file for an options lane trade: same drawer as the options account, built from the lane's own record.
  function laneLadder(d, o, mark) {
    const entry = Number(d.entry_price), stop = entry * (1 - o.stop_pct / 100), goal = entry * (1 + o.target_pct / 100), span_ = goal - stop;
    const at = (v) => Math.max(0, Math.min(100, ((v - stop) / span_) * 100));
    const box = el("div"), lad = el("div", null, "ladder"), cost = el("div", null, "cost");
    cost.style.left = at(entry) + "%";
    lad.appendChild(el("div", null, "track")); lad.appendChild(cost);
    if (mark !== null && mark !== undefined) { const m = el("div", null, "now"); m.style.left = at(mark) + "%"; lad.appendChild(m); }
    lad.setAttribute("role", "img");
    lad.setAttribute("aria-label", "Stop " + stop.toFixed(2) + ", paid " + entry.toFixed(2) + ", target " + goal.toFixed(2) + (mark === null || mark === undefined ? ", no quote" : ", bid " + Number(mark).toFixed(2)));
    const keys = el("div", null, "ladder-keys");
    [["stop", stop.toFixed(2)], ["paid", entry.toFixed(2)], ["target", goal.toFixed(2)]].forEach((k) => { const s2 = el("span"); s2.appendChild(document.createTextNode(k[0] + " ")); s2.appendChild(el("b", k[1])); keys.appendChild(s2); });
    kids(box, [lad, keys]);
    return box;
  }
  function renderLaneFile(t) {
    const d = t.detail, o = d.why_entered || {}, open = t.status !== "CLOSED";
    $("drawer-title").textContent = t.label || t.symbol;
    $("drawer-sub").textContent = t.source_label + " · " + (open ? "Open" : laneExitLabel(t));
    const body = $("drawer-body");
    body.replaceChildren();
    const res = el("div"), pnl = t.pnl;
    res.appendChild(el("div", pnl === null || pnl === undefined ? "No mark yet" : arrow(pnl) + sgn(pnl), "result " + tone(pnl)));
    res.appendChild(el("div", (t.pnl_pct === null || t.pnl_pct === undefined ? "No usable bid to mark this trade." : pct(t.pnl_pct) + " on " + money(t.entry_price * t.quantity * 100) + " paid") + (open ? " (still open, marked at the bid)" : ""), "muted"));
    body.appendChild(res);

    const facts = el("dl", null, "facts");
    const row = (k, v) => { facts.appendChild(el("dt", k)); facts.appendChild(el("dd", v)); };
    row("Bought", t.quantity + " at " + Number(t.entry_price).toFixed(2) + " on " + fmtTime(t.opened_at));
    if (t.exit_price !== null && t.exit_price !== undefined) row("Sold", "at " + Number(t.exit_price).toFixed(2) + " on " + fmtTime(t.closed_at));
    else if (t.mark !== null && t.mark !== undefined) row("Still held", "bid " + Number(t.mark).toFixed(2));
    row("Held", heldText(t));
    if (o.fees_open !== undefined) row("Fees in", money(o.fees_open) + ", spread " + o.spread_pct + "%, open interest " + num(o.open_interest));
    body.appendChild(section("The trade", [facts]));

    const why = [el("p", describeSignal(o) || "No entry signal was recorded.")];
    if (o.earnings_state) why.push(el("p", "Earnings: " + (STATE[o.earnings_state] || o.earnings_state) + ".", "muted"));
    if (o.critic) {
      why.push(el("p", o.critic.verdict === "ACCEPTED" ? "Critic: no objections." : "Critic accepted despite: " + o.critic.objections.join("; ") + "."));
      why.push(el("p", o.critic.thesis + " Wrong if " + o.critic.wrong_if + ".", "muted"));
    }
    if (o.stack_index > 0) why.push(el("p", "Position " + (o.stack_index + 1) + " in this name, stacked on " + o.stacked_on.length + " earlier trade" + (o.stacked_on.length > 1 ? "s" : "") + ".", "muted"));
    body.appendChild(section("Why it entered", why));

    if (o.stop_pct !== undefined && o.target_pct !== undefined) {
      body.appendChild(section("Exit plan", [laneLadder(d, o, open ? d.mark_bid : d.exit_price),
        el("p", "Sells at the bid when it reaches either level. Levels are rules, not predictions.", "muted")]));
    }

    const end = [];
    if (open) end.push(el("p", "Still open." + (d.mark_bid !== null && d.mark_bid !== undefined ? " Last bid " + Number(d.mark_bid).toFixed(2) + " at " + fmtTime(d.mark_at) + "." : ""), "muted"));
    else end.push(el("p", d.close_text || laneExitLabel(t)));
    const pm = d.postmortem;
    if (!open && pm) {
      end.push(el("p", pm.headline));
      if (pm.stress_net !== undefined) end.push(el("p", "If the exit had been stressed: " + sgn(pm.stress_net) + " (" + pct(pm.stress_net_pct) + ").", "muted"));
      (pm.lessons || []).forEach((x) => end.push(el("p", x)));
      if ((pm.try_next || []).length) { const u = el("ul", null, "plain"); pm.try_next.forEach((x) => u.appendChild(el("li", "Test next: " + x))); end.push(u); }
    }
    body.appendChild(section("How it ended", end));
    body.appendChild(el("p", "One trade proves nothing about the rule. Paper result on simulated fills.", "muted"));
  }
  function openLaneTrade(t, opener) {
    S.openTrade = t.key || t.id; S.opener = opener || document.activeElement;
    renderLaneFile(t);
    $("scrim").hidden = false; $("drawer").hidden = false;
    document.body.style.overflow = "hidden";
    $("btn-drawer-close").focus();
  }

  function renderTrades() {
    const data = S.trades;
    if (!data) return;
    const all = data.trades;
    const kindOk = (t) => S.kind === "all" || t.instrument === S.kind;
    const srcOk = (t) => S.source === "all" || t.source === S.source;
    const scoped = all.filter(kindOk).filter(srcOk);
    const sm = { total: scoped.length, open: scoped.filter((t) => t.status !== "CLOSED").length };
    const done = scoped.filter((t) => t.status === "CLOSED" && t.pnl !== null), wins = done.filter((t) => t.pnl > 0);
    const realized = done.reduce((a, t) => a + t.pnl, 0), openPnl = scoped.filter((t) => t.status !== "CLOSED").reduce((a, t) => a + (t.pnl || 0), 0);
    const best = done.length ? Math.max.apply(null, done.map((t) => t.pnl)) : null, worst = done.length ? Math.min.apply(null, done.map((t) => t.pnl)) : null;
    const noQuote = scoped.filter((t) => t.status !== "CLOSED" && t.pnl === null).length;
    $("trade-lede").textContent = all.length
      ? all.length + " simulated trade" + (all.length === 1 ? "" : "s") + ". Pick a lane above, filter, or sort any column. " + data.caveat
      : "Nothing has traded yet. The options account needs automatic entries switched on in Controls; the lanes and the challenge need the options lanes switched on.";
    const f = $("trade-summary");
    f.replaceChildren();
    kids(f, [
      fig(String(sm.total), "Trades", sm.open + " open, " + done.length + " closed"),
      fig(done.length ? Math.round(wins.length / done.length * 1000) / 10 + "%" : "n/a", "Winners", done.length ? wins.length + " of " + done.length + " closed" : "no closed trades"),
      fig(sgn(realized), "Realized", "closed trades, after fees", tone(realized)),
      fig(sgn(openPnl), "Open now", noQuote ? noQuote + " open without a usable quote" : "marked at the bid", tone(openPnl)),
      fig(best === null ? "n/a" : sgn(best), "Best closed", worst === null ? "" : "worst " + sgn(worst), tone(best)),
    ]);
    const count = (test) => all.filter(srcOk).filter(test).length;
    chips($("trade-kind"), KINDS.map((k) => ({ id: k.id, label: k.label + " " + all.filter(srcOk).filter((t) => k.id === "all" || t.instrument === k.id).length })), S.kind, (id) => { S.kind = id; S.shown = 100; renderTrades(); });
    // Lane tabs replace the old dropdown: every account and lane is visible at once with its trade count and result.
    const kindScoped = all.filter(kindOk);
    const tabs = [{ id: "all", label: "All lanes", t: kindScoped }];
    const srcs = data.sources.slice();
    if (!srcs.some((x) => x.source === "main")) srcs.unshift({ source: "main", label: "Options account" });
    srcs.sort((x, y) => (x.source === "main" ? -1 : y.source === "main" ? 1 : 0)).forEach((x) => tabs.push({ id: x.source, label: x.label, t: kindScoped.filter((t) => t.source === x.source) }));
    const lb = $("trade-source");
    lb.replaceChildren();
    tabs.forEach((tb) => {
      const closed = tb.t.filter((t) => t.status === "CLOSED" && t.pnl !== null), real = closed.reduce((acc, t) => acc + t.pnl, 0);
      const b = el("button", null, "lanetab");
      b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(tb.id === S.source));
      b.appendChild(el("span", tb.label, "lt-name"));
      const meta = el("span", null, "lt-meta num");
      meta.appendChild(el("span", tb.t.length + " trade" + (tb.t.length === 1 ? "" : "s"), "muted"));
      if (closed.length) meta.appendChild(span(sgn(real), tone(real)));
      b.appendChild(meta);
      b.addEventListener("click", () => { S.source = tb.id; S.shown = 100; renderTrades(); });
      lb.appendChild(b);
    });
    const base = all.filter(kindOk).filter(srcOk);
    chips($("trade-filters"), FILTERS.map((x) => ({ id: x.id, label: x.label + " " + base.filter(x.test).length })), S.filter, (id) => { S.filter = id; S.shown = 100; renderTrades(); });
    const flt = FILTERS.find((x) => x.id === S.filter) || FILTERS[0], q = S.query.trim().toUpperCase();
    const key = SORTS[S.sort.key] || SORTS.opened_at, dir = S.sort.dir;
    const rows = base.filter(flt.test).filter((t) => !q || t.symbol.indexOf(q) >= 0 || t.label.toUpperCase().indexOf(q) >= 0)
      .sort((x, y) => (key(x) < key(y) ? -dir : key(x) > key(y) ? dir : 0));
    renderSources(data, kindOk);
    const matching = rows.length;
    rows.length = Math.min(rows.length, S.shown);
    const host = $("trade-table");
    if (!rows.length) {
      empty(host, all.length ? "No trades match these filters" : "No trades yet",
        all.length ? "Clear the search box, or pick All and Options and shares." : "Run a cycle from Controls, or let the loop run during market hours.");
      return;
    }
    host.replaceChildren();
    if (phone.matches) {
      // Phones: one card per trade instead of a table that would scroll sideways.
      const sorter = el("select");
      sorter.setAttribute("aria-label", "Sort trades");
      [["opened_at", -1, "Newest first"], ["opened_at", 1, "Oldest first"], ["pnl", -1, "Best profit first"], ["pnl", 1, "Worst result first"], ["kind", 1, "Options first"], ["kind", -1, "Shares first"]].forEach((o) => {
        const opt = el("option", o[2]); opt.value = o[0] + ":" + o[1]; sorter.appendChild(opt);
      });
      sorter.value = S.sort.key + ":" + S.sort.dir;
      sorter.addEventListener("change", () => { const v = sorter.value.split(":"); S.sort = { key: v[0], dir: Number(v[1]) }; renderTrades(); });
      host.appendChild(sorter);
      rows.forEach((x) => {
        const card = el("div", null, "tcard");
        const top = el("div", null, "tc-top");
        kids(top, [tradeName(x), statusTag(x)]);
        const mid = el("div", null, "tc-mid");
        mid.appendChild(el("span", x.pnl === null ? "No quote" : sgn(x.pnl), "tc-pnl num " + tone(x.pnl)));
        if (x.pnl_pct !== null) mid.appendChild(el("span", pct(x.pnl_pct), "num " + tone(x.pnl_pct)));
        const low = el("div", x.source_label + ". " + x.quantity + (x.instrument === "options" ? " contract" + (x.quantity === 1 ? "" : "s") : " share" + (x.quantity === 1 ? "" : "s")) + " at " + Number(x.entry_price).toFixed(2) +
          (x.exit_price !== null ? ", sold at " + Number(x.exit_price).toFixed(2) : (x.mark !== null && x.mark !== undefined ? ", bid " + Number(x.mark).toFixed(2) : ", no usable quote")) + ". Opened " + openedText(x) + ".", "muted");
        kids(card, [top, mid, low]);
        attachRow(card, x, () => openRow(x, card, 0));
        host.appendChild(card);
      });
      moreButton(host, rows.length, matching);
      return;
    }
    const t = el("table"), head = el("tr");
    const col = (label, sortKey, right) => {
      const th = el("th", null, right ? "r" : "");
      if (sortKey) {
        const on = S.sort.key === sortKey;
        const b = el("button", label + (on ? (sortKey === "opened_at" ? (S.sort.dir > 0 ? " (oldest first)" : " (newest first)") : (S.sort.dir > 0 ? " (low to high)" : " (high to low)")) : ""));
        b.type = "button";
        th.setAttribute("aria-sort", on ? (S.sort.dir > 0 ? "ascending" : "descending") : "none");
        b.addEventListener("click", () => { S.sort = { key: sortKey, dir: on ? -S.sort.dir : (sortKey === "kind" || sortKey === "source" || sortKey === "symbol" ? 1 : -1) }; renderTrades(); });
        th.appendChild(b);
      } else th.textContent = label;
      head.appendChild(th);
    };
    col("Opened", "opened_at"); col("Trade", "symbol"); col("Type", "kind"); col("Account or lane", "source"); col("Qty", null, true); col("Entry", null, true);
    col("Exit or mark", null, true); col("Profit or loss", "pnl", true); col("Held", "held", true); col("Status", null);
    t.appendChild(head);
    const ncols = head.children.length;
    rows.forEach((x) => {
      const tr = el("tr", null, "click");
      const cell = (content, right) => { const td = el("td", null, right ? "r num" : ""); if (content instanceof Node) td.appendChild(content); else td.textContent = content; tr.appendChild(td); };
      cell(openedText(x)); cell(tradeName(x)); cell(instrumentTag(x)); cell(x.source_label); cell(String(x.quantity), true); cell(Number(x.entry_price).toFixed(2), true);
      cell(exitText(x), true); cell(pnlCell(x), true);
      cell(heldText(x), true); cell(statusTag(x));
      attachRow(tr, x, () => openRow(x, tr, ncols));
      t.appendChild(tr);
    });
    host.appendChild(t);
    moreButton(host, rows.length, matching);
  }
  function moreButton(host, shown, total) {
    if (total <= shown) return;
    const b = el("button", "Show 100 more (" + shown + " of " + total + " shown)", "btn");
    b.type = "button";
    b.addEventListener("click", () => { S.shown += 100; renderTrades(); });
    host.appendChild(b);
  }

  function renderSources(data, kindOk) {
    const rows = data.sources.filter((x) => S.kind === "all" || x.instrument === S.kind);
    table($("trade-sources"), [
      { label: "Account or lane", get: (r) => { const b = el("button", r.label, "linkbtn"); b.type = "button"; b.addEventListener("click", () => { S.source = r.source; renderTrades(); }); return b; } },
      { label: "Type", get: (r) => (r.instrument === "options" ? "Options" : "Shares") },
      { label: "Trades", right: true, get: (r) => r.open + " open, " + r.closed + " closed" },
      { label: "Winners", right: true, get: (r) => (r.win_rate_pct === null ? "n/a" : r.win_rate_pct + "%") },
      { label: "Realized", right: true, get: (r) => span(arrow(r.realized_pnl) + sgn(r.realized_pnl), tone(r.realized_pnl)) },
      { label: "Open now", right: true, get: (r) => openNow(r, "") },
    ], rows, "No lanes have traded yet");
  }

  async function loadTrades() {
    S.trades = await api("/api/alltrades");
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
    $("drawer-title").textContent = contractText(t);
    $("drawer-sub").textContent = exitLabel(t);
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
    S.openTrade = id; S.opener = opener || document.activeElement;
    $("scrim").hidden = false; $("drawer").hidden = false;
    document.body.style.overflow = "hidden";
    $("drawer-title").textContent = "Loading the trade file";
    $("drawer-sub").textContent = "";
    $("drawer-body").replaceChildren();
    $("btn-drawer-close").focus();
    try {
      const d = await api("/api/trades/" + encodeURIComponent(id));
      if (S.openTrade !== id) return;
      const trail = renderTradeFile(d);
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
      if (S.openTrade === id) { $("drawer-title").textContent = "Could not load the trade file"; $("drawer-body").appendChild(el("p", e.message, "loss")); }
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
      intro: "This is the share version of the day-trading experiment, kept as the benchmark for the short-term options lanes. It simulates buying shares of six liquid names when a fast trend line crosses above the day's average price, and selling when that fails. It places no orders. ",
      hint: "A trade needs a fresh crossing between 10:00 and 15:00 New York time on a name in the list.",
      why: (w) => "EMA " + w.ema + " crossed above VWAP " + w.vwap + " (was " + w.prev_ema + " under " + w.prev_vwap + ")",
    },
    sw: {
      path: "/api/swing", exits: SW_EXIT, cadence: "Checks about once an hour, on completed daily bars",
      intro: "This is the share version of the swing experiment, kept as the benchmark for the swing options lanes. It simulates buying shares of liquid names after a pullback inside an uptrend, holds them for up to ten trading days, and sells at a stop, a target, a broken trend or the time limit. It places no orders. ",
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

  // ---------------------------------------------------------------- Options tracker
  const TK_H = { 1: "1 trading day", 3: "3 trading days", 7: "7 trading days", 30: "30 trading days" };
  const retText = (v) => (v === null || v === undefined ? "n/a" : (v > 0 ? "+" : "") + v.toFixed(1) + "%");
  function tkMarks(m) {
    const w = el("span", null, "marks");
    ["1", "3", "7", "30"].forEach((h) => {
      const mk = m[h];
      w.appendChild(el("span", h + "d " + (mk ? retText(mk.ret_pct) : "waiting"), "mark " + (mk ? tone(mk.ret_pct) : "muted")));
    });
    return w;
  }
  function renderTracker() {
    const r = S.tracker;
    if (!r) return;
    const h3 = r.horizons["3"];
    $("tk-lede").textContent = "The scanner flags option contracts that traded far above their open interest. The tracker keeps every flag, reads the contract again 1, 3, 7 and 30 trading days later, and records what happened, so the rules for 'unusual' can be tested instead of trusted. " +
      (r.fictional ? "This is fictional demo data." : "");
    const f = $("tk-figures");
    f.replaceChildren();
    const waiting = r.watching.filter((w) => !w.marks["1"]).length;
    kids(f, [
      fig(String(r.watching.length), "Flags being watched", waiting + " not yet marked once"),
      fig(String(r.total_marks), "Marks taken", "needs " + r.min_n + " in a group before it counts"),
      fig(h3.n ? retText(h3.avg_ret_pct) : "n/a", "Average after 3 days", h3.n ? "median " + retText(h3.median_ret_pct) + ", " + h3.n + " marks" : "no 3 day marks yet", tone(h3.avg_ret_pct)),
      fig(h3.n ? h3.win_rate_pct + "%" : "n/a", "Positive after 3 days", "after paying the spread"),
    ]);
    const fl = $("tk-findings");
    fl.replaceChildren();
    if (r.findings.length) r.findings.forEach((x) => fl.appendChild(el("li", x)));
    else fl.appendChild(el("li", r.total_marks ? "No group of at least " + r.min_n + " marks differs from the average by a meaningful margin yet." : "Nothing yet. Marks start 1 trading day after the first flags, and findings need " + r.min_n + " marks in a group.", "muted"));
    table($("tk-horizons"), [
      { label: "After", get: (x) => TK_H[x.h] }, { label: "Marks", right: true, get: (x) => x.s.n },
      { label: "Positive", right: true, get: (x) => (x.s.n ? x.s.win_rate_pct + "%" : "n/a") },
      { label: "Average return", right: true, get: (x) => span(retText(x.s.avg_ret_pct), tone(x.s.avg_ret_pct)) },
      { label: "Median return", right: true, get: (x) => retText(x.s.median_ret_pct) },
      { label: "Underlying moved the right way by", right: true, get: (x) => retText(x.s.avg_helpful_move_pct) },
      { label: "Enough to read", get: (x) => el("span", x.s.enough ? "Yes" : "Too few", "tag " + (x.s.enough ? "info" : "")) },
    ], ["1", "3", "7", "30"].map((h) => ({ h, s: r.horizons[h] })), "No marks yet");
    chips($("tk-horizon-tabs"), ["1", "3", "7", "30"].map((h) => ({ id: h, label: TK_H[h] + " after" })), S.tkH, (id) => { S.tkH = id; renderTracker(); });
    const groups = r.groups.filter((g) => String(g.horizon) === S.tkH).sort((a, b) => (a.feature === b.feature ? (b.vs_all_pct || 0) - (a.vs_all_pct || 0) : a.feature < b.feature ? -1 : 1));
    table($("tk-groups"), [
      { label: "Feature", get: (g) => g.feature_label }, { label: "Group", get: (g) => el("b", g.bucket) },
      { label: "Marks", right: true, get: (g) => g.n },
      { label: "Positive", right: true, get: (g) => g.win_rate_pct + "%" },
      { label: "Average return", right: true, get: (g) => span(retText(g.avg_ret_pct), tone(g.avg_ret_pct)) },
      { label: "Against all flagged", right: true, get: (g) => (g.vs_all_pct === null ? "n/a" : span(arrow(g.vs_all_pct) + (g.vs_all_pct > 0 ? "+" : "") + g.vs_all_pct.toFixed(1) + " pts", tone(g.vs_all_pct))) },
      { label: "Enough to read", get: (g) => el("span", g.enough ? "Yes" : "Too few", "tag " + (g.enough ? "info" : "")) },
    ], groups, "No marks at this horizon yet", "Groups appear once a flagged contract has been read again that many trading days later.");
    table($("tk-watching"), [
      { label: "Flagged", get: (w) => shortDay(w.day) }, { label: "Contract", get: (w) => ticket(w) },
      { label: "Volume / OI", right: true, get: (w) => (w.ratio === null ? "no ratio" : w.ratio + "x") },
      { label: "Side", get: (w) => ({ BUY: "Looks like buying", SELL: "Looks like selling" }[w.side] || "Unclear") },
      { label: "Score", right: true, get: (w) => w.score },
      { label: "Entry (ask)", right: true, get: (w) => (w.entry_ask === null || w.entry_ask === undefined ? "n/a" : Number(w.entry_ask).toFixed(2)) },
      { label: "Marks", get: (w) => tkMarks(w.marks) },
    ], r.watching, "Nothing flagged yet", "Run a market scan. Flags from the scanner appear here and are marked on later days.");
    table($("tk-criteria"), [
      { label: "Rule", get: (c) => el("b", c.name) }, { label: "What it requires", get: (c) => c.rule }, { label: "Why", get: (c) => el("span", c.why, "muted") },
    ], r.criteria, "No criteria");
    $("tk-agent").textContent = "Two agents read unusual activity. The sentiment agent looks at call and put volume across the whole chain. The flow agent looks at the contracts flagged here on the candidate's own name and can only argue against a trade whose direction the flagged money opposes. If flow agrees it just writes that down. Their votes are scored against what happened next on the Agents page, and the flow agent starts with a quarter of the normal weight. Letting flow add conviction waits until the findings above show flagged flow is worth following.";
    const n = $("tk-notes");
    n.replaceChildren();
    r.limitations.forEach((x) => n.appendChild(el("li", x)));
  }
  async function loadTracker() { S.tracker = await api("/api/tracker"); renderTracker(); }

  // ---------------------------------------------------------------- Market scan
  const TABS = [{ id: "heat", label: "Heat map" }, { id: "unusual", label: "Unusual options" }, { id: "follow", label: "Did it stick?" },
    { id: "rotation", label: "Sector rotation" }, { id: "active", label: "Most active names" }, { id: "options", label: "Option volume by name" }];
  const TONE = { BROAD_STRENGTH: "▲ Broad strength", BROAD_WEAKNESS: "▼ Broad weakness", MIXED: "◆ Mixed", UNKNOWN: "? Unknown" };
  const FLOW = { BULLISH_LEAN: "▲ Bullish lean", BEARISH_LEAN: "▼ Bearish lean", BALANCED: "◆ Balanced", UNCLEAR: "? Unclear" };
  const POSITION = { BUY_TO_OPEN: "likely bought to open", SELL_TO_OPEN: "likely sold to open", BUY_TO_CLOSE: "likely bought to close", SELL_TO_CLOSE: "likely sold to close", UNCLEAR: "open or close unclear" };
  const LEAN = { BULLISH: "▲ Bullish read", BEARISH: "▼ Bearish read", UNCLEAR: "" };
  const arrow = (v) => (v > 0 ? "▲ " : v < 0 ? "▼ " : "◆ ");
  const signed = (v) => arrow(v) + (v > 0 ? "+" : "") + Number(v).toFixed(2) + "%";
  const PRINT = { AT_ASK: "At the ask: buy leaning", ABOVE_ASK: "Above the ask: buy leaning", AT_BID: "At the bid: sell leaning", BELOW_BID: "Below the bid: sell leaning", MID: "Mid price: unclear", UNKNOWN: "No usable last price" };
  const shortDay = (iso) => { const d = new Date(iso + "T12:00:00"); return isNaN(d) ? String(iso) : d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); };
  function histText(h) {
    if (!h) return "First time seen";
    const bits = [];
    if (h.oi_change !== null && h.oi_change !== undefined) bits.push("open interest " + (h.oi_change >= 0 ? "+" : "") + num(h.oi_change) + " since " + shortDay(h.prior_day));
    else bits.push(h.oi_verdict === "TOO_FAR_APART" ? "seen " + shortDay(h.prior_day) + ", too long ago to compare" : "seen " + shortDay(h.prior_day));
    if (h.position_read && h.position_read !== "UNCLEAR") bits.push(POSITION[h.position_read]);
    if (h.lean && LEAN[h.lean]) bits.push(LEAN[h.lean]);
    return bits.join(", ");
  }
  function renderHeat(res) {
    const host = $("scan-heat"), hm = res.heat_map;
    if (!hm || !hm.sectors.length) { empty(host, "No heat map", "The scan returned no ranked names."); return; }
    host.replaceChildren();
    hm.sectors.forEach((sec) => {
      const wrap = el("div", null, "sector"), head = el("header");
      kids(head, [el("b", sec.sector), span(signed(sec.avg_change_pct) + " on average", "num " + tone(sec.avg_change_pct)),
        span(sec.advancers + " up, " + sec.decliners + " down" + (sec.surging ? ", " + sec.surging + " on heavy volume" : ""), "muted")]);
      const tiles = el("div", null, "tiles");
      hm.names.filter((n) => n.sector === sec.sector).sort((x, y) => y.change_pct - x.change_pct).forEach((n) => {
        const t = el("div", null, "tile " + (n.change_pct > 0 ? "up" : n.change_pct < 0 ? "down" : ""));
        t.style.setProperty("--k", Math.min(60, Math.abs(n.change_pct) * 12 + 6) + "%");
        t.title = n.symbol + (n.relative_volume === null ? "" : ", volume " + n.relative_volume.toFixed(1) + "x its usual");
        kids(t, [el("b", n.symbol), el("small", signed(n.change_pct) + (n.relative_volume !== null && n.relative_volume >= 2 ? " · " + n.relative_volume.toFixed(1) + "x vol" : ""))]);
        tiles.appendChild(t);
      });
      kids(wrap, [head, tiles]);
      host.appendChild(wrap);
    });
  }
  function renderSentiment(res) {
    const host = $("scan-sentiment");
    host.replaceChildren();
    const s = res && res.sentiment;
    if (!s) return;
    kids(host, [
      fig(TONE[s.tone] || s.tone, "Stock tape", s.breadth_pct === null ? "" : s.advancers + " of " + s.names + " names up (" + s.breadth_pct + "%)"),
      fig(s.spy_change_pct === null ? "n/a" : signed(s.spy_change_pct), "SPY, last full day", "", tone(s.spy_change_pct)),
      fig(s.call_put_ratio === null ? "n/a" : String(s.call_put_ratio), "Calls per put", num(s.call_volume) + " calls, " + num(s.put_volume) + " puts in the chains read"),
      fig(FLOW[s.flow_lean] || s.flow_lean, "Unusual option flow", "bought $" + num(s.bullish_flow_usd) + " bullish, $" + num(s.bearish_flow_usd) + " bearish, $" + num(s.unclear_flow_usd) + " unclear"),
    ]);
  }
  function renderMarket() {
    const d = S.scan, res = d && d.result;
    const st = d && d.status;
    $("scan-lede").textContent = "About " + ((res && res.coverage && res.coverage.universe) || 200) + " liquid names from mega-caps down to mid-caps, ranked by dollar volume, with the option contracts trading far above their open interest, and what the sectors and the flow are doing. A screen for where to look, not a signal to trade.";
    $("scan-status").textContent = !st ? "" : st.running ? "Scanning now" : st.last_scan_at ? "Last scan " + fmtTime(st.last_scan_at) + (d.interval_s ? ", repeats every " + Math.round(d.interval_s / 60) + " minutes" : ", automatic scanning is off") : "No scan has run yet";
    $("btn-scan").disabled = !!(st && st.running);
    chips($("market-tabs"), TABS, S.marketTab, (id) => { S.marketTab = id; renderMarket(); }, "tab");
    ["heat", "rotation", "unusual", "follow", "active", "options"].forEach((id) => { $("scan-" + id + "-panel").hidden = S.marketTab !== id; });
    renderSentiment(res);
    const notes = $("scan-notes");
    notes.replaceChildren();
    ((res && res.limitations) || []).forEach((x) => notes.appendChild(el("li", x)));
    if (res && res.sentiment) notes.appendChild(el("li", res.sentiment.basis));
    if (res && res.fictional) notes.appendChild(el("li", "This scan ran on fictional demo data. The names and volumes are invented.", "warn"));
    if (res && res.errors && res.errors.length) notes.appendChild(el("li", "Problems during the scan: " + res.errors.slice(0, 6).join("; ")));
    if (!res) {
      ["scan-heat", "scan-active", "scan-unusual", "scan-follow", "scan-options"].forEach((id) => empty($(id), "No scan yet", "Choose Scan now, or set a scan interval in Controls."));
      return;
    }
    renderHeat(res);
    table($("scan-active"), [
      { label: "Rank", right: true, get: (r) => r.rank }, { label: "Name", get: (r) => el("b", r.symbol) },
      { label: "Close", right: true, get: (r) => money(r.close) },
      { label: "Day change", right: true, get: (r) => span(signed(r.change_pct), tone(r.change_pct)) },
      { label: "Dollar volume", right: true, get: (r) => "$" + (r.dollar_volume / 1e9 >= 1 ? (r.dollar_volume / 1e9).toFixed(1) + "B" : (r.dollar_volume / 1e6).toFixed(0) + "M") },
      { label: "Volume vs usual", right: true, get: (r) => r.relative_volume === null ? "n/a" : span(r.relative_volume.toFixed(1) + "x", r.surge ? "tag warn" : "") },
    ], res.active_names, "No ranked names", (res.errors || [])[0] || "The scan returned no daily bars.");

    chips($("scan-filters"), [{ id: "all", label: "Everything unusual" }, { id: "low", label: "Very low open interest" }, { id: "reviewable", label: "Tradable by the rules" }], S.unusualFilter, (id) => { S.unusualFilter = id; renderMarket(); });
    const un = res.unusual.filter((r) => S.unusualFilter === "all" || (S.unusualFilter === "low" ? r.low_oi : r.decision === "REVIEWABLE"));
    const th = res.thresholds;
    table($("scan-unusual"), [
      { label: "Contract", get: (r) => ticket(r) }, { label: "Days left", right: true, get: (r) => r.dte },
      { label: "Volume", right: true, get: (r) => num(r.volume) },
      { label: "Open interest", right: true, get: (r) => { const t = r.open_interest === null ? "missing" : (r.oi_state === "REPORTED_ZERO" ? "zero" : num(r.open_interest)); return r.low_oi ? kids(el("span"), [span(t + " "), span("Low", "tag warn")]) : t; } },
      { label: "Volume / OI", right: true, get: (r) => r.volume_oi_ratio === null ? "no ratio" : r.volume_oi_ratio + "x" },
      { label: "Last trade", get: (r) => PRINT[r.print] || r.print },
      { label: "Seen before?", get: (r) => (r.sightings > 1 ? "Day " + r.sightings + ": " : "") + histText(r.history) },
      { label: "Spread", right: true, get: (r) => r.spread_pct.toFixed(1) + "%" },
      { label: "Quoted turnover", right: true, get: (r) => "$" + num(r.quoted_turnover_usd) },
      { label: "Why consider it", get: (r) => (r.opportunity?.reasons || ["Movement/cost evidence unavailable"]).join(" ") },
      { label: "Status", get: (r) => r.decision === "REVIEWABLE" ? el("span", "Reviewable", "tag info") : el("span", "Watch only: " + r.why_observe_only, "tag") },
    ], un, "Nothing unusual by these thresholds", "Thresholds: at least " + th.min_volume + " contracts at " + th.min_volume_oi_ratio + "x open interest or more" + (th.low_oi_below ? ", or at least " + th.min_volume_when_oi_low + " contracts when open interest is under " + th.low_oi_below : "") + ".");

    table($("scan-follow"), [
      { label: "Contract", get: (f) => ticket(f) },
      { label: "Unusual on", get: (f) => shortDay(f.prior_day) },
      { label: "Volume then", right: true, get: (f) => num(f.prior_volume) },
      { label: "Open interest", right: true, get: (f) => f.oi_change === null ? "n/a" : num(f.prior_oi) + " to " + num(f.oi_now) + " (" + (f.oi_change >= 0 ? "+" : "") + num(f.oi_change) + ")" },
      { label: "Did it stick?", get: (f) => f.oi_verdict === "OI_ROSE" ? el("span", "Yes, positions opened", "tag gain") : f.oi_verdict === "OI_FELL" ? el("span", "No, positions closed", "tag loss") : el("span", words(f.oi_verdict), "tag") },
      { label: "Read", get: (f) => [POSITION[f.position_read], LEAN[f.lean]].filter(Boolean).join(", ") || "Unclear" },
      { label: "Volume today", right: true, get: (f) => num(f.volume_today) },
    ], res.follow_ups || [], "No earlier unusual contracts to follow up", "The scanner remembers each day's unusual contracts and checks their open interest the next trading day, so this fills from the second day of scanning.");

    table($("scan-options"), [
      { label: "Name", get: (r) => el("b", r.symbol) }, { label: "Sector", get: (r) => r.sector || "" }, { label: "Call volume", right: true, get: (r) => num(r.call_volume) },
      { label: "Put volume", right: true, get: (r) => num(r.put_volume) },
      { label: "Calls per put", right: true, get: (r) => r.call_put_ratio === null ? "no puts" : r.call_put_ratio },
      { label: "Unusual contracts", right: true, get: (r) => r.unusual_count }, { label: "Contracts read", right: true, get: (r) => r.contracts },
    ], res.option_names, "No option chains were read", (res.errors || [])[0] || "");
  }

  // ---------------------------------------------------------------- market context: sentiment, gamma levels, expected moves
  const READ = { CALL_HEAVY: "▲ Call-heavy", PUT_HEAVY: "▼ Put-heavy", BALANCED: "◆ Balanced", UNKNOWN: "Unknown" };
  const ratioText = (v) => (v === null || v === undefined ? "n/a" : Number(v).toFixed(2));
  async function loadContext() { S.ctx = await api("/api/context"); renderContext(); }
  function levelLines(lv, spot) {
    return [{ v: spot, label: "spot", cls: "spot" }, { v: lv.call_wall, label: "call wall", cls: "call" }, { v: lv.put_wall, label: "put wall", cls: "put" }, { v: lv.gamma_flip, label: "flip", cls: "flip" }].filter((l) => l.v !== null && l.v !== undefined);
  }
  function drawGex(host, row) {
    host.replaceChildren();
    const lv = row.levels, prof = lv.profile;
    if (!prof.length) { empty(host, "No gamma profile", "No strikes near the price had open interest and implied volatility."); return; }
    const W = 720, H = 270, m = { l: 48, r: 12, t: 46, b: 34 };
    const lo = prof[0].strike, hi = prof[prof.length - 1].strike, span_ = Math.max(hi - lo, 1e-9);
    const X = (k) => m.l + ((k - lo) / span_) * (W - m.l - m.r);
    const mx = Math.max.apply(null, prof.map((p) => Math.max(p.call_musd, -p.put_musd, 1e-9)));
    const mid = m.t + (H - m.t - m.b) / 2, half = (H - m.t - m.b) / 2;
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": row.symbol + " modeled gamma by strike" });
    root.appendChild(svg("line", { class: "grid", x1: m.l, x2: W - m.r, y1: mid, y2: mid }));
    const bw = Math.max(2, Math.min(18, (W - m.l - m.r) / prof.length * 0.7));
    prof.forEach((p) => {
      const up = (p.call_musd / mx) * half, dn = (-p.put_musd / mx) * half;
      const t = svg("rect", { x: X(p.strike) - bw / 2, y: mid - up, width: bw, height: Math.max(up, 0), fill: "var(--gain)", opacity: 0.8 });
      t.appendChild(svg("title", {}, "strike " + p.strike + ": calls " + p.call_musd + " M, puts " + p.put_musd + " M"));
      root.appendChild(t);
      root.appendChild(svg("rect", { x: X(p.strike) - bw / 2, y: mid, width: bw, height: Math.max(dn, 0), fill: "var(--loss)", opacity: 0.8 }));
    });
    levelLines(lv, row.spot).forEach((l, i) => {
      if (l.v < lo || l.v > hi) return;
      const x = X(l.v);
      root.appendChild(svg("line", { x1: x, x2: x, y1: 14 + (i % 4) * 11, y2: H - m.b, stroke: "var(--fg)", "stroke-width": 1, "stroke-dasharray": l.cls === "spot" ? "" : "4 3" }));
      root.appendChild(svg("text", { x: x, y: 11 + (i % 4) * 11, "text-anchor": "start", dx: 4, fill: "var(--mut)", "font-size": 11 }, l.label + " " + l.v));
    });
    root.appendChild(svg("text", { x: m.l, y: H - 10, fill: "var(--mut)", "font-size": 11 }, "strike " + lo));
    root.appendChild(svg("text", { x: W - m.r, y: H - 10, "text-anchor": "end", fill: "var(--mut)", "font-size": 11 }, "strike " + hi));
    root.appendChild(svg("text", { x: 4, y: mid - half + 10, fill: "var(--mut)", "font-size": 11 }, "calls"));
    root.appendChild(svg("text", { x: 4, y: mid + half - 2, fill: "var(--mut)", "font-size": 11 }, "puts"));
    host.appendChild(root);
  }
  function drawLevelsOnPrice(host, row) {
    host.replaceChildren();
    const c = row.closes || [];
    if (c.length < 2) { empty(host, "No price history", "The chain snapshot carried no daily closes."); return; }
    const lines = levelLines(row.levels, row.spot);
    const vals = c.concat(lines.map((l) => l.v));
    const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi - lo || 1) * 0.06;
    const W = 720, H = 220, m = { l: 12, r: 90, t: 10, b: 10 };
    const X = (i) => m.l + (i / (c.length - 1)) * (W - m.l - m.r), Y = (v) => H - m.b - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - m.t - m.b);
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": row.symbol + " recent closes with gamma levels" });
    root.appendChild(svg("polyline", { points: c.map((v, i) => X(i) + "," + Y(v)).join(" "), fill: "none", stroke: "var(--series-1)", "stroke-width": 2 }));
    lines.forEach((l) => {
      root.appendChild(svg("line", { x1: m.l, x2: W - m.r, y1: Y(l.v), y2: Y(l.v), stroke: l.cls === "call" ? "var(--gain)" : l.cls === "put" ? "var(--loss)" : "var(--warn)", "stroke-dasharray": l.cls === "spot" ? "" : "5 4" }));
      root.appendChild(svg("text", { x: W - m.r + 4, y: Y(l.v) + 4, fill: "var(--mut)", "font-size": 11 }, l.label + " " + l.v));
    });
    host.appendChild(root);
  }
  function renderContext() {
    const d = S.ctx || { rows: [], groups: {}, missing: [], notes: [] };
    $("ctx-lede").textContent = d.rows.length
      ? "From the scan of " + (d.as_of ? fmtTime(d.as_of) : "n/a") + (d.fictional ? " (FICTIONAL demo data, the numbers are invented)" : "") + ". " + d.rows.length + " of " + (d.rows.length + d.missing.length) + " core tickers were read."
      : "No scan has read these tickers yet. Run a scan on the Market page; nothing is shown until real chains are read.";
    const g = d.groups || {};
    const gf = (key, name) => {
      const x = g[key];
      return x && x.names ? fig(READ[x.reading] || x.reading, name + ": calls per put " + ratioText(x.call_put_volume_ratio), num(x.call_volume) + " calls, " + num(x.put_volume) + " puts; by premium " + ratioText(x.call_put_premium_ratio) + "; " + x.call_heavy_names + " call-heavy, " + x.put_heavy_names + " put-heavy of " + x.names) : null;
    };
    $("ctx-groups").replaceChildren();
    kids($("ctx-groups"), [gf("index", "Index funds"), gf("mega", "Mega-caps")]);
    table($("ctx-table"), [
      { label: "Ticker", get: (r) => el("b", r.symbol) }, { label: "Price", right: true, get: (r) => money(r.spot) },
      { label: "Call volume", right: true, get: (r) => num(r.sentiment.call_volume) }, { label: "Put volume", right: true, get: (r) => num(r.sentiment.put_volume) },
      { label: "Calls per put (volume)", right: true, get: (r) => ratioText(r.sentiment.call_put_volume_ratio) },
      { label: "Calls per put (premium)", right: true, get: (r) => ratioText(r.sentiment.call_put_premium_ratio) },
      { label: "Calls per put (open interest)", right: true, get: (r) => ratioText(r.sentiment.call_put_oi_ratio) },
      { label: "Reading", get: (r) => READ[r.sentiment.reading] || r.sentiment.reading },
    ], d.rows, "No tickers read yet", "Run a scan on the Market page.");
    const heat = $("ctx-heat");
    heat.replaceChildren();
    d.rows.forEach((r) => {
      const v = r.net_share_of_gross, t = el("div", null, "tile " + (v === null ? "" : v >= 0 ? "up" : "down"));
      if (v !== null) t.style.setProperty("--k", Math.min(60, Math.abs(v) * 60 + 6) + "%");
      t.title = r.symbol + (r.flip_distance_pct === null ? "" : ", flip " + signed(r.flip_distance_pct) + " from the price");
      kids(t, [el("b", r.symbol), el("small", v === null ? "n/a" : (v >= 0 ? "▲ +" : "▼ ") + (v * 100).toFixed(0) + "% net")]);
      heat.appendChild(t);
    });
    if (!d.rows.length) empty(heat, "No tickers read yet", "");
    if (!d.rows.some((r) => r.symbol === S.ctxPick)) S.ctxPick = d.rows.length ? d.rows[0].symbol : null;
    chips($("ctx-pick"), d.rows.map((r) => ({ id: r.symbol, label: r.symbol })), S.ctxPick, (id) => { S.ctxPick = id; renderContext(); }, "tab");
    const sel = d.rows.find((r) => r.symbol === S.ctxPick);
    if (sel) { drawGex($("ctx-gex"), sel); drawLevelsOnPrice($("ctx-price"), sel); } else { empty($("ctx-gex"), "No gamma chart", ""); $("ctx-price").replaceChildren(); }
    const ev = d.earnings || {};
    const evRows = d.rows.filter((r) => r.symbol in ev || r.expected_move);
    table($("ctx-events"), [
      { label: "Ticker", get: (r) => el("b", r.symbol) },
      { label: "Next earnings", get: (r) => { const e = ev[r.symbol]; return e === undefined ? "n/a (fund)" : e === null ? "unknown" : e.length ? e[0] : "none in 45 days"; } },
      { label: "Expected move", right: true, get: (r) => (r.expected_move && r.expected_move.pct !== null ? "±" + r.expected_move.pct + "%" : "n/a") },
      { label: "Move horizon", get: (r) => { const m = r.expected_move; if (!m || m.pct === null) return ""; const e = ev[r.symbol]; return "to " + m.expiry + (e && e.length && e[0] <= m.expiry ? " (includes earnings)" : ""); } },
    ], evRows, "Nothing to show yet", "Needs a scan that read the core tickers.");
    const mac = $("ctx-macro");
    mac.replaceChildren();
    if (d.macro === null || d.macro === undefined) mac.appendChild(el("li", "FOMC dates: unknown for this period (the table does not cover it)."));
    else if (!d.macro.length) mac.appendChild(el("li", "No FOMC decision in the next 45 days."));
    else d.macro.forEach((e) => mac.appendChild(el("li", "FOMC decision " + e.day + (e.tentative ? " (tentative)" : ""))));
    const notes = $("ctx-notes");
    notes.replaceChildren();
    (d.notes || []).forEach((x) => notes.appendChild(el("li", x)));
    if (d.fictional) notes.appendChild(el("li", "This data is fictional demo data.", "warn"));
    if (d.errors && d.errors.length) notes.appendChild(el("li", "Problems: " + d.errors.join("; ")));
  }
  async function loadMarket() { const [scan, rot] = await Promise.all([api("/api/scan"), api("/api/rotation")]); S.scan = scan; S.rotation = rot; renderMarket(); renderRotation(rot); }

  // Where trading is concentrating between sectors, from the daily scans the platform has stored.
  const TREND = { GAINING: "▲ Gaining share", LOSING: "▼ Losing share", STEADY: "◆ Steady" };
  function renderRotation(r) {
    const host = $("scan-rotation");
    const notes = $("scan-rotation-notes");
    notes.replaceChildren();
    (r.summary || []).forEach((x) => notes.appendChild(el("li", x)));
    notes.appendChild(el("li", r.caveat, "muted"));
    if (!r.sectors.length) { empty(host, "No sector history yet", "Run a scan. Rotation needs scans from at least two different trading days."); return; }
    const top = Math.max.apply(null, r.sectors.map((x) => Math.abs(x.share_change_pts)).concat([1]));
    table(host, [
      { label: "Sector", get: (x) => el("b", x.sector) },
      { label: "Share of trading now", right: true, get: (x) => x.share_pct.toFixed(1) + "%" },
      { label: "Change in share since " + shortDay(r.days[0]), right: true, get: (x) => {
        const w = el("span", null, "num"), bar = el("span", null, "bar"), i = el("i", null, x.share_change_pts >= 0 ? "up" : "down");
        i.style.width = Math.min(50, Math.abs(x.share_change_pts) / top * 50) + "%";
        bar.appendChild(i);
        kids(w, [span(arrow(x.share_change_pts) + (x.share_change_pts > 0 ? "+" : "") + x.share_change_pts.toFixed(1) + " pts", tone(x.share_change_pts)), bar]);
        return w; } },
      { label: "Trend", get: (x) => el("span", TREND[x.trend], "tag " + (x.trend === "GAINING" ? "info" : "")) },
      { label: "Price move over the days shown", right: true, get: (x) => span(signed(x.cumulative_change_pct), tone(x.cumulative_change_pct)) },
      { label: "Today", right: true, get: (x) => span(signed(x.avg_change_pct), tone(x.avg_change_pct)) },
      { label: "Calls per put", right: true, get: (x) => (x.call_put_ratio === null ? "n/a" : x.call_put_ratio) },
      { label: "Days seen", right: true, get: (x) => x.days_seen },
    ], r.sectors, "No sector history yet");
  }

  // ---------------------------------------------------------------- Options lanes
  const OP_EXIT = { stop: "Stop", target: "Target", vwap_lost: "Lost VWAP", flat_by_close: "Closed for the day", carried_over: "Left over", trend_break: "Trend broke", time: "Time stop", expiry_near: "Near expiry", expired_unmarked: "Expired", challenge_end: "Attempt ended" };
  const STATE = { FUND: "a fund, no earnings", CLEAR: "no earnings in the way", SOON: "earnings close by", UNKNOWN: "earnings date unknown", "n/a": "not checked" };
  function describeSignal(o) {
    const g = o.signal || {};
    if (o.kind === "short") return "The 9-bar EMA " + g.ema + " crossed " + (g.direction === "up" ? "above" : "below") + " the session VWAP " + g.vwap + ".";
    if (o.kind === "swing") return "Daily close " + g.close + " " + (g.direction === "up" ? "after a dip, RSI turning up (" + g.rsi + ")" : "after a bounce in a downtrend, RSI turning down (" + g.rsi + ")") + ".";
    if (o.kind === "flow") return "On " + shortDay(g.prior_day) + " " + num(g.prior_volume) + " contracts of " + g.from_contract + " traded against " + num(g.prior_oi) + " open interest; open interest then rose by " + num(g.oi_change) + ", read as " + (POSITION[g.position_read] || "unclear") + ".";
    return "";
  }
  function tradeItem(t, exits) {
    const o = t.why_entered || {}, open = t.status === "OPEN";
    const d = el("details", null, "pm");
    const sum = el("summary");
    const label = open ? "Open" : (exits[t.close_reason] || words(t.close_reason));
    kids(sum, [o.right ? ticket({ symbol: t.symbol, right: o.right, strike: o.strike, expiry: o.expiry }) : el("b", t.symbol),
      span(o.dte !== undefined ? o.dte + " days to expiry at entry" : "", "muted"),
      span(t.quantity + " at " + Number(t.entry_price).toFixed(2) + (t.exit_price === null ? "" : " to " + Number(t.exit_price).toFixed(2)), "num"),
      span(label, "tag " + (open ? "info" : t.pnl > 0 ? "gain" : "loss"))]);
    const money_ = open ? (t.unrealized_pnl === null ? "no mark yet" : arrow(t.unrealized_pnl) + sgn(t.unrealized_pnl)) : arrow(t.pnl) + sgn(t.pnl) + " (" + pct(t.pnl_pct) + ")";
    sum.appendChild(span(money_, "pm-money " + tone(open ? t.unrealized_pnl : t.pnl)));
    const body = el("div", null, "pm-body"), facts = el("dl", null, "facts");
    const row = (k, v) => { facts.appendChild(el("dt", k)); facts.appendChild(el("dd", v)); };
    row("Opened", fmtTime(t.opened_at));
    row("Why it entered", describeSignal(o));
    row("Paid", t.quantity + " contract" + (t.quantity > 1 ? "s" : "") + " at the ask of " + Number(t.entry_price).toFixed(2) + " ($" + num(Math.round(t.entry_price * t.quantity * 100)) + "), spread " + o.spread_pct + "%, open interest " + num(o.open_interest) + ", fees " + money(o.fees_open));
    row("Stop and target", "Stop if the bid reaches " + (t.entry_price * (1 - o.stop_pct / 100)).toFixed(2) + ", target at " + (t.entry_price * (1 + o.target_pct / 100)).toFixed(2));
    row("Earnings", STATE[o.earnings_state] || o.earnings_state);
    if (o.critic) {
      row("Critic", o.critic.verdict === "ACCEPTED" ? "No objections." : "Accepted despite: " + o.critic.objections.join("; ") + ".");
      row("Thesis", o.critic.thesis + " Wrong if " + o.critic.wrong_if + ".");
      if (o.critic.needs_pct_per_day_for_goal !== null && o.critic.needs_pct_per_day_for_goal !== undefined) row("Pace", "At this point the account needs about " + o.critic.needs_pct_per_day_for_goal + "% a day, every day, to reach the goal.");
    }
    if (o.stack_index > 0) row("Stacked", "Position " + (o.stack_index + 1) + " in this name, added on top of " + o.stacked_on.length + " earlier trade" + (o.stacked_on.length > 1 ? "s" : "") + ".");
    if (o.size_vs_volume_pct !== null && o.size_vs_volume_pct !== undefined) row("Size against the market", o.size_vs_volume_pct + "% of the contract's volume" + (o.size_vs_oi_pct === null || o.size_vs_oi_pct === undefined ? "" : ", " + o.size_vs_oi_pct + "% of its open interest") + ". A real order this size could move the price.");
    if (open && t.mark_bid !== null) row("Last mark", "Bid " + Number(t.mark_bid).toFixed(2) + " at " + fmtTime(t.mark_at));
    body.appendChild(facts);
    const pm = t.postmortem;
    if (!open && pm) {
      const box = el("div");
      box.appendChild(el("b", "Post-mortem"));
      box.appendChild(el("p", pm.headline));
      if (pm.lessons.length) { const u = el("ul", null, "plain"); pm.lessons.forEach((x) => u.appendChild(el("li", x))); box.appendChild(u); }
      if (pm.try_next.length) { box.appendChild(el("b", "Test next")); const u = el("ul", null, "plain"); pm.try_next.forEach((x) => u.appendChild(el("li", x))); box.appendChild(u); }
      if (t.close_text) box.appendChild(el("p", t.close_text, "muted"));
      body.appendChild(box);
    }
    d.appendChild(sum); d.appendChild(body);
    return d;
  }
  function renderOptions() {
    const o = S.opt;
    if (!o) return;
    renderChallenge(o.ch);
    const d = o.ops, lanes = d.lanes;
    const total = lanes.reduce((a, l) => a + l.summary.closed, 0);
    $("op-lede").textContent = (d.enabled ? "" : "The lanes are switched off. Turn them on under Controls. ") +
      "Five simulated experiments buy calls and puts using real chain quotes: filled at the ask, closed at the bid, with a fee each way. Risk on each is the premium paid. The aggressive versions are loose on purpose, so there are more and different losses to learn from. Nothing here places an order. " +
      "With " + total + " closed trades in total, none of this shows an edge yet." + (d.fictional ? " These trades come from fictional demo data." : "");
    $("op-status").textContent = d.enabled ? "Short-term lanes check every 2 minutes, swing every hour, flow every 30 minutes, while the market is open" : "Off";
    $("btn-op-step").disabled = !d.enabled;
    const bench = [
      { name: "Swing, shares (benchmark)", what: "Shares", s: Object.assign({}, o.swing.summary, { unrealized_pnl: undefined }) },
      { name: "Short-term, shares (benchmark)", what: "Shares", s: Object.assign({}, o.st.summary, { unrealized_pnl: undefined }) },
    ];
    const rows = lanes.map((l) => ({ name: l.label, what: l.params.both_ways ? "Calls and puts" : "Calls", s: l.summary, lane: l.lane })).concat(bench);
    table($("op-compare"), [
      { label: "Lane", get: (r) => r.lane ? el("b", r.name) : span(r.name, "muted") }, { label: "Instrument", get: (r) => r.what },
      { label: "Trades", right: true, get: (r) => r.s.open + " open, " + r.s.closed + " closed" },
      { label: "Winners", right: true, get: (r) => r.s.win_rate_pct === null ? "n/a" : r.s.win_rate_pct + "%" },
      { label: "Average per trade", right: true, get: (r) => r.s.avg_return_pct === null ? "n/a" : span(arrow(r.s.avg_return_pct) + pct(r.s.avg_return_pct), tone(r.s.avg_return_pct)) },
      { label: "Realized", right: true, get: (r) => span(arrow(r.s.realized_pnl) + sgn(r.s.realized_pnl), tone(r.s.realized_pnl)) },
      { label: "Open now", right: true, get: (r) => r.s.unrealized_pnl === undefined ? "n/a" : r.s.unrealized_complete === false ? span(sgn(r.s.unrealized_pnl) + " (partial, " + r.s.unmarked_open + " unmarked)", "muted") : span(arrow(r.s.unrealized_pnl) + sgn(r.s.unrealized_pnl), tone(r.s.unrealized_pnl)) },
    ], rows, "No lanes");
    chips($("op-tabs"), lanes.map((l) => ({ id: l.lane, label: l.label })), S.optLane, (id) => { S.optLane = id; renderOptions(); }, "tab");
    const lane = lanes.find((l) => l.lane === S.optLane) || lanes[0], sm = lane.summary;
    $("op-why").textContent = lane.why + " Up to $" + num(lane.params.budget_usd) + " of premium per trade, " + lane.params.dte[0] + " to " + lane.params.dte[1] + " days to expiry, at most " + lane.params.max_open + " open.";
    const f = $("op-summary");
    f.replaceChildren();
    kids(f, [
      fig(String(sm.total), "Simulated trades", sm.open + " open, " + sm.closed + " closed"),
      fig(sm.win_rate_pct === null ? "n/a" : sm.win_rate_pct + "%", "Winners", sm.closed ? sm.wins + " of " + sm.closed + " closed" : "no closed trades"),
      fig(sm.avg_return_pct === null ? "n/a" : arrow(sm.avg_return_pct) + pct(sm.avg_return_pct), "Average per trade", "of the premium paid, after fees", tone(sm.avg_return_pct)),
      fig(arrow(sm.realized_pnl) + sgn(sm.realized_pnl), "Realized", "simulated", tone(sm.realized_pnl)),
      sm.unrealized_complete === false
        ? fig(sgn(sm.unrealized_pnl) + " (partial)", "Open now", sm.unmarked_open + " open trade(s) have no usable bid and are left out, so the real figure is unknown")
        : fig(arrow(sm.unrealized_pnl) + sgn(sm.unrealized_pnl), "Open now", "at the last bid", tone(sm.unrealized_pnl)),
      fig(sm.stress_pnl === null ? "n/a" : arrow(sm.stress_pnl) + sgn(sm.stress_pnl), "Realized, harder exit", sm.stress_pnl === null ? "needs closed trades with a post-mortem" : "same " + sm.stress_trades + " trades, at the bid they made " + sgn(sm.stress_bid_pnl) + "; a what-if, not a price", tone(sm.stress_pnl)),
    ]);
    const host = $("op-trades");
    if (!lane.trades.length) empty(host, "No simulated trades yet", d.enabled ? "A trade needs this lane's signal while the market is open." : "Switch the options lanes on under Controls.");
    else { host.replaceChildren(); lane.trades.slice(0, 60).forEach((t) => host.appendChild(tradeItem(t, OP_EXIT))); }
    const dg = d.digest;
    table($("op-digest"), [
      { label: "Cause", get: (r) => el("b", words(r.tag)) }, { label: "Trades", right: true, get: (r) => r.count },
      { label: "Winners", right: true, get: (r) => r.win_rate_pct + "%" },
      { label: "Average", right: true, get: (r) => { const x = span(arrow(r.avg_net_pct) + pct(r.avg_net_pct), tone(r.avg_net_pct)); x.style.whiteSpace = "nowrap"; return x; } },
      { label: "Why consider it", get: (r) => (r.opportunity?.reasons || ["Movement/cost evidence unavailable"]).join(" ") },
      { label: "Status", get: (r) => el("span", r.pattern ? "Pattern" : "Too few to say", "tag " + (r.pattern ? "warn" : "")) },
      { label: "What it means", get: (r) => r.means }, { label: "Test next", get: (r) => r.try_next },
    ], dg.tags, "No post-mortems yet", "Each closed trade is reviewed automatically when it closes.");
    $("op-digest-note").textContent = dg.note + " " + dg.trades_reviewed + " closed trades reviewed.";
    const lc = $("op-last"), ck = lane.last_check;
    lc.replaceChildren();
    if (!ck) lc.appendChild(el("li", "Not checked yet since the platform started."));
    else {
      lc.appendChild(el("li", "Looked at " + ck.at.slice(0, 19).replace("T", " ") + " UTC: opened " + ck.opened + ", closed " + ck.closed + "."));
      ck.errors.forEach((x) => lc.appendChild(el("li", "Problem: " + x, "warn")));
      if (ck.error_count > ck.errors.length) lc.appendChild(el("li", "and " + (ck.error_count - ck.errors.length) + " more problems.", "warn"));
      ck.skips.forEach((x) => lc.appendChild(el("li", "Skipped: " + x)));
      if (ck.skip_count > ck.skips.length) lc.appendChild(el("li", "and " + (ck.skip_count - ck.skips.length) + " more skipped."));
      if (!ck.errors.length && !ck.skips.length && !ck.opened && !ck.closed) lc.appendChild(el("li", "No signal met this lane's rules, so nothing was tried."));
    }
    const r = $("op-rules"), l = $("op-limits");
    r.replaceChildren(); l.replaceChildren();
    lane.rules.forEach((x) => r.appendChild(el("li", x)));
    lane.limitations.forEach((x) => l.appendChild(el("li", x)));
  }
  function renderChallenge(ch) {
    if (!ch) return;
    const a = ch.account;
    $("ch-lede").textContent = "A separate simulated account of " + money(a.start_equity) + " that aims for 10x in " + a.days + " days. That is deliberately unreasonable: it needs roughly 11% a day, every day. When an attempt ends, the result is kept and a new one starts, so losing it all is cheap and teaches something. A critic reviews every trade first." + (ch.fictional ? " These trades come from fictional demo data." : "");
    const f = $("ch-figures");
    f.replaceChildren();
    f.appendChild(fig(money(a.equity), "Equity, attempt " + a.attempt, arrow(a.multiple - 1) + a.multiple + "x of the start", a.on_pace ? "gain" : "loss"));
    f.appendChild(fig("Day " + Math.floor(a.day) + " of " + a.days, "Time used", "Goal " + money(a.goal_equity) + ", ruin at " + money(a.ruin_equity)));
    f.appendChild(fig(money(a.cash), "Cash", money(a.open_premium) + " in open trades"));
    f.appendChild(fig(money(a.realized_pnl), "Realized this attempt", a.unmarked_open ? a.unmarked_open + " open trade(s) have no quote yet" : "", tone(a.realized_pnl)));
    $("ch-pace").textContent = (a.needed_pct_per_day === null ? "No time left to reach the goal. " : "To reach " + money(a.goal_equity) + " from here it needs about " + a.needed_pct_per_day + "% a day, every day. ") +
      "A straight-line pace would be " + money(a.straight_line_equity) + " by now, so this attempt is " + (a.on_pace ? "ahead of" : "behind") + " it.";
    $("ch-honesty").textContent = ch.honesty;
    table($("ch-history"), [
      { label: "Attempt", right: true, get: (r) => r.attempt }, { label: "How it ended", get: (r) => words(r.outcome) },
      { label: "Ended with", right: true, get: (r) => money(r.end_equity) + " (" + r.multiple + "x)" },
      { label: "Trades", right: true, get: (r) => r.wins + " won of " + r.trades },
      { label: "Best and worst", right: true, get: (r) => r.best_trade_usd === null ? "n/a" : money(r.best_trade_usd) + " / " + money(r.worst_trade_usd) },
      { label: "Causes that kept showing up", get: (r) => r.top_causes.map((c) => words(c[0]) + " x" + c[1]).join(", ") || "none" },
    ], ch.history, "No attempt has finished yet", "An attempt ends when it reaches 10x, is down 90%, or runs out of its 30 days.");
    const host = $("ch-trades");
    const mine = ch.trades.filter((t) => (t.why_entered || {}).attempt === a.attempt);
    if (!mine.length) empty(host, "No trades in this attempt yet", ch.enabled ? "A trade needs the lane's signal while the market is open, and the critic's approval." : "Switch the options lanes on under Controls.");
    else { host.replaceChildren(); mine.slice(0, 60).forEach((t) => host.appendChild(tradeItem(t, OP_EXIT))); }
    const r = $("ch-rules"), l = $("ch-limits");
    r.replaceChildren(); l.replaceChildren();
    ch.rules.forEach((x) => r.appendChild(el("li", x)));
    ch.limitations.forEach((x) => l.appendChild(el("li", x)));
  }
  async function loadOptions() {
    const [ops, swing, st, ch] = await Promise.all([api("/api/optlanes"), api("/api/swing"), api("/api/shortterm"), api("/api/challenge")]);
    S.opt = { ops, swing, st, ch };
    renderOptions();
  }

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
    const now = $("committee-now");
    now.replaceChildren();
    const per = {};
    votes.forEach((d) => ((d.payload && d.payload.verdicts) || []).forEach((v) => {
      const p = per[v.agent] || (per[v.agent] = { latest: v, support: 0, oppose: 0, abstain: 0 });
      if (v.stance === "SUPPORT") p.support += 1; else if (v.stance === "OPPOSE") p.oppose += 1; else p.abstain += 1;
    }));
    const names = Object.keys(per);
    if (!names.length) now.appendChild(el("p", "No votes yet. The committee votes on the top candidates each cycle; with entries off or the market closed there is nothing to vote on. It is in " + c.mode + " mode, so it records opinions only.", "muted"));
    names.forEach((n) => {
      const p = per[n], card = el("div", null, "agentcard");
      kids(card, [el("b", n), voteChip(p.latest), el("div", p.support + " support, " + p.oppose + " oppose, " + p.abstain + " abstain", "num"),
        el("div", (p.latest.reasons || [])[0] || "No reason recorded", "why")]);
      now.appendChild(card);
    });
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
  function renderHypotheses(list) {
    table($("research"), [
      { label: "Id", get: (h) => h.id }, { label: "Hypothesis", get: (h) => h.statement },
      { label: "Why consider it", get: (r) => (r.opportunity?.reasons || ["Movement/cost evidence unavailable"]).join(" ") },
      { label: "Status", get: (h) => h.status + (h.intact ? "" : " (RECORD TAMPERED)") },
      { label: "Min trades", get: (h) => (h.criteria.min_trades || "") + " total / " + (h.criteria.min_oos_trades || "") + " out-of-sample" },
      { label: "Evaluations", right: true, get: (h) => h.evaluations },
    ], list, "No experiments registered", "Register one with: python -m optplat.research register. The baseline stays frozen.");
  }
  function renderLab(rep) {
    const LV = { NOT_PROVEN: "◇ Not proven", NOT_REFUTED_YET: "◆ Not refuted yet" };
    $("lab-note").textContent = rep ? rep.note + " Window " + rep.from + " to " + rep.to + ", " + rep.symbols.length + " symbols, " + rep.strategies_tried + " strategies tried (the bar per strategy is p at most " + rep.alpha_per_strategy + ")." : "";
    const rows = rep ? rep.results : [];
    const pc = (v) => (v === null || v === undefined ? "n/a" : v + "%");
    table($("lab-table"), [
      { label: "Strategy", get: (r) => kids(el("div"), [el("b", r.name), el("div", r.description, "muted")]) },
      { label: "Trades (days)", right: true, get: (r) => r.all.trades + " (" + r.all.independent_days + ")" },
      { label: "Win rate", right: true, get: (r) => pc(r.all.win_rate_pct) + (r.all.win_rate_ci95 ? " [" + r.all.win_rate_ci95[0] + "-" + r.all.win_rate_ci95[1] + "]" : "") },
      { label: "Mean trade", right: true, get: (r) => pc(r.all.mean_pct) },
      { label: "Later dates mean", right: true, get: (r) => pc(r.later.mean_pct) + " (" + r.later.trades + ")" },
      { label: "Random entries mean", right: true, get: (r) => pc(r.random.mean_pct) + ", p " + (r.random.p_value === null ? "n/a" : r.random.p_value) },
      { label: "Windows up", right: true, get: (r) => r.windows_positive + " of " + r.windows_with_trades },
      { label: "Verdict", get: (r) => kids(el("div"), [el("b", LV[r.verdict] || r.verdict)].concat(r.reasons.map((w) => el("div", w, "muted")))) },
    ], rows, "The lab has not run yet", "Choose Run the lab now, or run python -m optplat.lab --data yahoo --save-db <your database> on the computer that runs the platform.");
    const rg = [];
    rows.forEach((r) => Object.keys(r.by_regime).forEach((g) => rg.push({ name: r.name, g: g, x: r.by_regime[g] })));
    table($("lab-regime"), [
      { label: "Strategy", get: (r) => r.name }, { label: "Market", get: (r) => r.g === "UP" ? "▲ SPY above its 50 day average" : r.g === "DOWN" ? "▼ SPY below it" : "Unknown" },
      { label: "Trades", right: true, get: (r) => r.x.trades }, { label: "Win rate", right: true, get: (r) => pc(r.x.win_rate_pct) },
      { label: "Mean trade", right: true, get: (r) => pc(r.x.mean_pct) }, { label: "Sample", get: (r) => (r.x.enough ? "" : "too few to judge") },
    ], rg, "No regime split yet", "");
  }
  // The Lab band: how close the shadow book is to the research gate, and where each registered hypothesis stands.
  // Pure and read-only. It never registers or judges a hypothesis; the owner confirms the gate.
  function labGate(sh, hyps) {
    const list = Array.isArray(hyps) ? hyps : [];
    const hy = { total: list.length, tampered: list.filter((h) => h.intact === false).length, by: {} };
    list.forEach((h) => { hy.by[h.status] = (hy.by[h.status] || 0) + 1; });
    if (!sh || !sh.gate) return { state: "unknown", rows: [], text: "The shadow book could not be read, so the gate cannot be shown.", hyps: hy };
    const g = sh.gate;
    const mk = (key, label, have, need, unit) => ({ key: key, label: label, have: have || 0, need: need, unit: unit || "", pct: Math.max(0, Math.min(100, Math.round(((have || 0) / need) * 100))), met: (have || 0) >= need });
    const rows = [mk("trading_days", "Trading days", sh.trading_days, g.trading_days), mk("underlyings", "Underlyings", sh.underlyings, g.underlyings),
      mk("followed", "Contracts followed", sh.followed, g.followed), mk("complete_pct", "Paths complete", sh.complete_pct, g.complete_pct, "%")];
    const met = rows.filter((r) => r.met).length;
    let state = met === rows.length ? "ready" : sh.followed > 0 ? "building" : "early", text;
    if (sh.fictional) { state = "early"; text = "Following fictional demo data. None of this counts towards the gate."; }
    else if (sh.followed === 0) text = "Nothing is being followed yet. Candidates are recorded when a scan runs.";
    else if (state === "ready") text = "The data numbers are met. The export must also have run " + g.export_days_in_a_row + " days in a row; this page cannot see that, so you confirm it.";
    else text = met + " of " + rows.length + " gate lines hold. Hypotheses wait until all do.";
    if (typeof sh.independent_observations === "number" && sh.followed > 0) text += " Real sample: " + sh.independent_observations + " independent observations (one per name per day).";
    return { state: state, rows: rows, text: text, hyps: hy };
  }
  function renderLabGate(sh, hyps) {
    const g = labGate(sh, hyps);
    $("lab-gate-text").textContent = g.text;
    const tag = $("lab-gate-tag");
    tag.textContent = g.state === "ready" ? "\u25CF Ready for your check" : g.state === "building" ? "\u25B2 Building" : g.state === "early" ? "\u25C7 Too early" : "\u25C7 Unknown";
    tag.className = "tag " + (g.state === "ready" ? "gain" : g.state === "building" ? "warn" : "info");
    const host = $("lab-gate-rows");
    host.replaceChildren();
    g.rows.forEach((r) => {
      const row = el("div", null, "gate-row"), bar = el("div", null, "gate-bar"), fill = el("i");
      fill.style.width = r.pct + "%";
      if (r.met) fill.className = "met";
      bar.appendChild(fill);
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", r.label + ": " + r.have + r.unit + " of " + r.need + r.unit + (r.met ? ", met" : ""));
      kids(row, [el("span", r.label), bar, el("span", (r.met ? "\u2713 " : "") + r.have + r.unit + " of " + r.need + r.unit, "num muted")]);
      host.appendChild(row);
    });
    const h = g.hyps, by = Object.keys(h.by).map((k) => h.by[k] + " " + words(k).toLowerCase());
    $("lab-hyps").textContent = h.total ? h.total + " registered: " + by.join(", ") + (h.tampered ? ". " + h.tampered + " record(s) fail the tamper check." : ".") : "No hypothesis is registered. That is expected until the gate holds and you confirm it.";
  }
  async function loadResearch() {
    const [hyp, learn, lab, shadow] = await Promise.all([api("/api/research/hypotheses"), api("/api/learning"), api("/api/lab"), api("/api/shadow").catch(() => null)]);
    renderHypotheses(hyp); renderLearning(learn); renderLab(lab); renderLabGate(shadow, hyp);
  }
  const VERDICT = { IMPROVING: ["▲ Improving", "gain"], WORSENING: ["▼ Getting worse", "loss"], NO_CLEAR_CHANGE: ["◆ No clear change", ""], TOO_EARLY: ["◇ Too early to say", ""] };
  function renderLearning(l) {
    const imp = l.improvement, c = l.counts;
    $("rs-lede").textContent = (l.fictional ? "Fictional demo data: none of this is evidence. " : "") + "Everything the platform has recorded about its own mistakes and results, and whether the later trades are better than the earlier ones. Each claim carries its sample size.";
    const f = $("rs-figures");
    f.replaceChildren();
    kids(f, [fig(String(c.closed), "Closed trades", c.trades + " in all, across every lane"), fig(String(c.lessons), "Lessons on record", "patterns and anecdotes"),
      fig(String(c.weight_changes), "Agent weight changes", "from how votes turned out"), fig(String(c.tracker_marks), "Option flow marks", "from the tracker")]);
    const v = VERDICT[imp.verdict] || [imp.verdict, ""], vp = $("rs-verdict");
    vp.replaceChildren();
    kids(vp, [el("span", v[0], "tag " + v[1]), span("  " + imp.text)]);
    l.summary.slice(1).forEach((x) => vp.appendChild(el("div", x, "muted")));
    table($("rs-halves"), [
      { label: "Period", get: (h) => h.label }, { label: "Closed trades", right: true, get: (h) => h.s.n },
      { label: "Winners", right: true, get: (h) => h.s.win_rate_pct + "%" },
      { label: "Average return", right: true, get: (h) => span(retText(h.s.avg_return_pct), tone(h.s.avg_return_pct)) },
      { label: "From", get: (h) => fmtTime(h.s.from) }, { label: "To", get: (h) => fmtTime(h.s.to) },
    ], imp.older ? [{ label: "Older half", s: imp.older }, { label: "Newer half", s: imp.newer }] : [], "No comparison yet", "At least " + (2 * imp.min_half) + " closed trades are needed, " + imp.min_half + " in each half.");
    table($("rs-lessons"), [
      { label: "From", get: (x) => x.source }, { label: "What it found", get: (x) => x.text },
      { label: "How much evidence", get: (x) => el("span", x.strength, "tag " + (x.strength === "Pattern" ? "info" : "")) },
    ], l.lessons, "Nothing learned yet", "Lessons appear once trades close, agents vote and the tracker marks flagged contracts.");
    table($("rs-agents"), [
      { label: "Agent", get: (a) => el("b", a.agent) }, { label: "Weight", right: true, get: (a) => (a.weight === null || a.weight === undefined ? "n/a" : Number(a.weight).toFixed(2)) },
      { label: "Outcomes seen", right: true, get: (a) => a.outcomes + (a.descriptive_only ? " (too few to judge)" : "") },
    ], l.agents, "No agent has voted on an outcome yet");
    const tl = $("rs-timeline");
    tl.replaceChildren();
    if (!l.timeline.length) tl.appendChild(el("li", "Nothing yet. The first closed trade will appear here.", "muted"));
    l.timeline.forEach((e) => { const li = el("li"); li.appendChild(el("time", fmtTime(e.ts))); li.appendChild(el("span", e.text)); tl.appendChild(li); });
    $("rs-caveat").textContent = l.caveat;
  }

  // ---------------------------------------------------------------- refresh loop
  async function loadPage() {
    const page = route();
    if (page === "trades") await loadTrades();
    else if (page === "options") await loadOptions();
    else if (page === "swing") await loadSwing();
    else if (page === "shortterm") await loadShortterm();
    else if (page === "market") await loadMarket();
    else if (page === "context") await loadContext();
    else if (page === "tracker") await loadTracker();
    else if (page === "agents") await loadAgents();
    else if (page === "research") await loadResearch();
  }

  // On the first connected load, ask the server to look for a newer tested release, then reload when the build changes.
  let buildChecked = false;
  async function checkForNewBuild(previous) {
    if (buildChecked) return;
    buildChecked = true;
    let result;
    try { result = await api("/api/deployment/check-on-refresh", { method: "POST", body: "{}" }); } catch (e) { return; }
    if (!result.queued && result.status !== "RECENT_CHECK_OR_IN_PROGRESS") return;
    let left = 60;
    const timer = window.setInterval(async () => {
      left -= 1;
      if (left <= 0) { window.clearInterval(timer); return; }
      try {
        const h = await fetch("/api/health", { cache: "no-store" }).then((r) => r.json());
        if (h.build_id && previous && h.build_id !== previous) { window.clearInterval(timer); window.location.reload(); }
      } catch (e) { /* the server restarts during an update; keep polling */ }
    }, 10000);
  }

  const pctPlain = (n) => (n === null || n === undefined ? "n/a" : n + "%");
  const STATUS_TEXT = {
    NO_CLOSED_TRADES: "No closed trades yet: nothing to judge.",
    INSUFFICIENT_SAMPLE: "Too few closed trades to say anything. Treat every number below as noise.",
    SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE: "Sample size met, but this is still not proof of an edge.",
  };

  function fillModelText(f) {
    if (!f) return "not reported";
    if (f.buys === "unknown") return "unknown (" + (f.note || "") + ")";
    return "buys at " + f.buys + ", sells at " + f.sells + " (" + f.slippage_pct + "%); commissions " +
      (f.commissions_modeled ? "modeled" : "NOT modeled") + ". " + (f.note || "");
  }

  function feeHeadroomText(r) {
    const f = r.breakeven_fee_per_contract_usd;
    if (f === null || f === undefined) return "n/a (no closed profit to erase)";
    return "a round-trip fee of about $" + Number(f).toFixed(2) + " per contract (" + (r.contracts_closed || 0) +
      " closed) would erase the simulated profit; real option fees are charged on top of these fills.";
  }

  function promotionText(p) {
    if (!p) return "unknown (not reported); treat as NOT ready";
    return (p.promotion_recommended ? "unexpected: marked recommended; verify" : "NO") +
      ". Still missing: " + (p.evidence_missing || []).join("; ") + ".";
  }

  function multipleTestingText(m) {
    if (!m) return "unknown (not reported); treat any best-looking result as overstated";
    return (m.strategy_variants_selectable || []).length + " strategies selectable (" + (m.strategy_variants_selectable || []).join(", ") +
      "); results split by strategy: " + (m.results_split_by_strategy ? "yes" : "NO") + ". " + (m.note || "");
  }

  // Results come from /api/results; every value is shown as text, and gaps are shown as "n/a", never as zero.
  function renderResults(r) {
    const split = r.split_half || {};
    const open = r.open_positions || {};
    const bad = r.status !== "SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE";
    $("results-status").replaceChildren(
      el("div", (STATUS_TEXT[r.status] || String(r.status)) + " (" + r.closed_trades + " of " + r.min_trades_required + " trades)", bad ? "warn" : ""));
    const rows = [
      ["Realized P&L (closed trades)", money(r.realized_pnl_usd)],
      ["Win rate", pctPlain(r.win_rate_pct)],
      ["P&L without the best trade", money(r.pnl_without_best_trade_usd)],
      ["Worst closed-trade drawdown (not account drawdown)", pctPlain(r.closed_trade_max_drawdown_pct)],
      ["Longest losing streak (closed trades)", r.longest_losing_streak === null || r.longest_losing_streak === undefined ? "n/a" : String(r.longest_losing_streak)],
      ["Cumulative closed P&L, last " + (r.cumulative_pnl_recent_usd || []).length + " of " + (r.cumulative_pnl_points_total || 0) + " trades",
        (r.cumulative_pnl_recent_usd || []).length ? r.cumulative_pnl_recent_usd.map(money).join(" > ") : "n/a"],
      ["Early half vs later half", split.status === "CHECKED"
        ? money(split.first_half_pnl_usd) + " vs " + money(split.second_half_pnl_usd) + (split.consistent ? " (same sign)" : " (NOT consistent)")
        : "withheld until enough trades"],
      ["Unrealized P&L (marked to bid)", open.unrealized_pnl_usd === null || open.unrealized_pnl_usd === undefined
        ? "n/a: " + (open.error || ((open.unmarked || []).length + " position(s) cannot be marked")) : money(open.unrealized_pnl_usd)],
      ["Fee headroom (no fees are modeled)", feeHeadroomText(r)],
      ["Filled exits with no cost basis", r.unpriced_exits],
      ["Ready to promote beyond paper?", promotionText(r.promotion)],
      ["Several strategies, one total?", multipleTestingText(r.multiple_testing)],
      ["How fills are simulated", fillModelText(r.fill_model)],
    ];
    table($("results-table"), [{ label: "Measure", get: (x) => x[0] }, { label: "Value", get: (x) => x[1] }], rows, "No results");
    $("results-limits").textContent = (r.limitations || []).join(" ");
  }

  // Plain-language reading of the last cycle: what was taken, what was skipped, and why.
  const RESULT_TEXT = {
    FILLED: "Bought (paper)", NO_DATA: "Skipped: no market data for this symbol",
    NO_PROPOSAL: "Skipped: nothing met the strategy rules",
    NOTHING_AFFORDABLE_WITHIN_SIZE_CAP: "Skipped: nothing fits the position size cap",
    REJECTED: "Blocked by a risk check", KEY_CONFLICT: "Skipped: duplicate order key",
  };
  function outcomesLine(r) {
    if (!r || !r.cycles) return "";
    const parts = Object.keys(r.counts).sort().map((k) => (RESULT_TEXT[k] || k).replace(/^Skipped: /, "skipped: ") + " x" + r.counts[k]);
    return "Last " + r.cycles + " cycle(s) (kept up to " + r.window + "): " + (parts.length ? parts.join("; ") : "no entry decisions") + ".";
  }

  function renderCycleDecisions(c, recent) {
    const rows = (c ? c.entries : []).map((x) => ({
      what: x.contract || x.symbol,
      outcome: RESULT_TEXT[x.result] || String(x.result),
      why: [...(x.rationale?.opportunity?.reasons || []), x.reason || (x.risk_failures || []).join("; ") || (x.rationale && x.rationale.trend ? "Trend " + x.rationale.trend + ", spread " + x.rationale.spread_pct + "%" : ""),
      x.size_vs_liquidity && x.size_vs_liquidity.warnings.length ? "Size check: " + x.size_vs_liquidity.warnings.join("; ") : ""].filter(Boolean).join(" | "),
    }));
    const base = c ? (c.entries_note || (rows.length ? "" : "No symbols were evaluated.")) : "No cycle has run yet.";
    $("decisions-note").textContent = [base, outcomesLine(recent)].filter(Boolean).join(" ");
    table($("decisions-table"), [
      { label: "Symbol / contract", get: (r) => r.what }, { label: "Outcome", get: (r) => r.outcome }, { label: "Why", get: (r) => r.why },
    ], rows, "No entry decisions in the last cycle");
  }

  function renderCandidates(c) {
    const rows = c && c.candidates ? c.candidates : [];
    $("candidates-note").textContent = c
      ? "Contracts that passed the strategy filters, best score first. Candidates must pass a historical-movement versus cost screen, including time decay, spread, fees and a 20% IV decline. Ranking is a research heuristic, not a chance of profit. Symbols after a buy in the same cycle are not scanned."
      : "No cycle has run yet.";
    table($("candidates-table"), [
      { label: "Contract", get: (r) => r.contract }, { label: "Trend", get: (r) => r.trend },
      { label: "Score", get: (r) => r.score }, { label: "Limit", get: (r) => r.limit_price },
      { label: "Spread %", get: (r) => r.spread_pct }, { label: "Days to expiry", get: (r) => r.dte },
      { label: "Volume", get: (r) => (r.volume == null ? "not reported" : r.volume) },
      { label: "Open interest", get: (r) => (r.open_interest == null ? "not reported" : r.open_interest) },
      { label: "Why consider it", get: (r) => (r.opportunity?.reasons || ["Movement/cost evidence unavailable"]).join(" ") },
      { label: "Last traded", get: (r) => (r.last_trade_age_hours == null ? "unknown" : r.last_trade_age_hours > 24 ? "STALE? " + r.last_trade_age_hours + "h ago" : r.last_trade_age_hours + "h ago") },
    ], rows, "No contract passed the filters in the last cycle");
  }

  function renderFlow(c) {
    const rows = c && c.flow ? c.flow : [];
    const themes = c && c.flow_themes ? c.flow_themes.map((t) => t.group + ": " + t.symbols.join(", ")).join("; ") : "";
    $("flow-note").textContent = c
      ? (c.flow_caveats || []).join(" ") + (themes ? " Same theme in several names: " + themes + "." : "") + (rows.some((r) => r.fictional) ? " Some rows are from FICTIONAL demo data." : "")
      : "No cycle has run yet.";
    table($("flow-table"), [
      { label: "Contract", get: (r) => r.contract + (r.fictional ? " (fictional)" : "") },
      { label: "Tier", get: (r) => r.tier },
      { label: "Volume / OI", get: (r) => r.volume + " / " + (r.open_interest == null ? "not reported" : r.open_interest) + (r.volume_oi_ratio ? " (" + r.volume_oi_ratio + "x)" : "") },
      { label: "OTM / DTE", get: (r) => (r.otm_pct == null ? "?" : r.otm_pct + "%") + " / " + r.dte + "d" },
      { label: "Premium at quoted mid (scale only)", get: (r) => (r.premium_at_quoted_mid_usd == null ? "n/a" : money(r.premium_at_quoted_mid_usd)) },
      { label: "Ask-side share", get: () => "not available" },
      { label: "Flags", get: (r) => r.flags.join("; ") },
    ], rows, "No unusual turnover in the last cycle");
  }

  function renderGex(c) {
    const rows = c && c.gex ? c.gex : [];
    $("gex-note").textContent = c
      ? "Calls are counted positive and puts negative. That is an assumption, not real dealer positions, and it uses only the chain sample the provider returned. Context, not a prediction. " + (rows.some((r) => r.fictional) ? "Some rows are from FICTIONAL demo data." : "")
      : "No cycle has run yet.";
    table($("gex-table"), [
      { label: "Symbol", get: (r) => r.symbol + (r.fictional ? " (fictional)" : "") },
      { label: "Net GEX, USD M per 1% move", get: (r) => (r.net_gex_musd === null ? "n/a" : r.net_gex_musd) },
      { label: "Largest positive strike", get: (r) => (r.largest_positive_strike === null ? "-" : r.largest_positive_strike) },
      { label: "Largest negative strike", get: (r) => (r.largest_negative_strike === null ? "-" : r.largest_negative_strike) },
      { label: "Rows used / skipped", get: (r) => r.rows_used + " / " + r.rows_skipped },
      { label: "As of", get: (r) => r.as_of },
    ], rows, "No GEX computed in the last cycle");
  }

  // "At a glance": plain-words reading of safety, money and what needs the owner. Pure function of API data.
  // Each item is {level: "ok"|"warn"|"bad", text}. Unknown or missing data is reported as unknown, never as fine.
  function buildGlance(h, st, pf, res, pol, nowMs) {
    const out = [];
    const add = (level, text) => out.push({ level, text });
    if (h.mode !== "PAPER") add("bad", "Broker mode is " + h.mode + ", not PAPER. Stop and check.");
    else add("ok", "Paper only: no real money can be used by this app.");
    if (pf && pf.kill_switch) add("bad", "Kill switch is ON: no new orders are accepted.");
    else if (pf) add("ok", "Kill switch is off (you can still press it any time).");
    else add("warn", "Kill switch state unknown.");
    if (st.data_source && st.data_source.fictional) add("warn", "Market data is FICTIONAL demo data: every number here is made up.");
    else if (st.data_source) add("ok", "Market data source: " + st.data_source.name + " (not demo data).");
    else add("warn", "Market data source unknown.");
    if (st.strategy && st.strategy.name) add("ok", "Strategy in use: " + st.strategy.name + " " + (st.strategy.version || "") +
      " (paper research, no demonstrated edge). Switching strategies mixes their trades in Results; the totals are not split by strategy.");
    else add("warn", "Which strategy is running is unknown.");
    if (st.config && st.config.auto_entries) add("warn", "Automatic entries are ON: the engine may buy paper contracts by itself.");
    else if (st.config) add("ok", "Automatic entries are off: nothing is bought unless you press Run one cycle.");
    if (st.config && st.config.auto_entries) add("warn", "There is no daily loss halt: a bad day will not stop new entries by itself. Only the per-order and total-premium limits and the kill switch apply.");
    if (st.market) {
      if (st.market.open) add("ok", "Market is open (" + st.market.reason + ").");
      else add("ok", "Market is closed (" + st.market.reason + "): " + (st.config && st.config.enforce_market_hours === false ? "but the market-hours check is off, see below." : "no new paper trades until it opens."));
    } else add("warn", "Market session unknown.");
    if (st.market && Array.isArray(st.market.upcoming)) {
      if (st.market.upcoming.length) add("ok", "Coming up (exchange calendar only, not earnings or news): " +
        st.market.upcoming.map(function (e) { return e.date + (e.kind === "closed" ? " market closed" : " early close"); }).join("; ") + ".");
      else add("ok", "No market holidays or early closes in the next 3 weeks (exchange calendar only; earnings and news are not tracked).");
    }
    if (st.config && st.config.enforce_market_hours === false) add("warn", "Market-hours check is OFF: the engine may act outside the session, on quotes that may be stale.");
    if (pol && pol.require_verified_quote_time === false) add("warn", "Quote-time verification is OFF.");
    if (pol && typeof pol.max_position_pct === "number")
      add("ok", "Risk limits: up to " + pol.max_position_pct + "% of equity per order, " + pol.max_total_premium_pct + "% open in total, " + pol.max_open_positions + " positions.");
    const acct = pf && pf.account;
    if (acct && typeof acct.equity === "number" && acct.equity > 0 && typeof acct.open_premium === "number") {
      const share = (acct.open_premium / acct.equity) * 100;
      add(share > 50 ? "warn" : "ok", "Worst case today: the open contracts are worth " + money(acct.open_premium) + " at cost (" + share.toFixed(1) +
        "% of equity). A long option can lose all of its premium, so losing all of it is the worst case for these positions; fees are not modeled.");
    } else if (pf) add("warn", "Money at risk unknown: account equity or open premium is missing.");
    const c = st.last_cycle;
    if (!c) add("warn", "No cycle has run yet, so there is no recent activity to show.");
    else if (c.errors && c.errors.length) add("bad", "The last cycle had " + c.errors.length + " error(s): " + c.errors.join("; "));
    else add("ok", "Last cycle ran without errors (" + c.entries.length + " entry decision(s), " + c.exits.length + " exit decision(s)).");
    if (st.runner && st.runner.running && st.runner.consecutive_failures > 0)
      add("bad", "The loop has failed " + st.runner.consecutive_failures + " cycle(s) in a row. Last error: " + (st.runner.last_error || "unknown") + ".");
    if (st.runner && st.runner.stalled === true) add("warn", "The server reports the loop as stalled: no successful cycle for " + Math.round((st.runner.seconds_since_success || 0) / 60) + " min.");
    else if (c && c.started_at && st.runner && st.runner.running && st.runner.stalled === undefined && st.config && st.config.interval_s) {
      const ageS = ((typeof nowMs === "number" ? nowMs : Date.now()) - Date.parse(c.started_at)) / 1000;
      if (isNaN(ageS)) add("warn", "Last cycle time is unreadable, so staleness cannot be checked.");
      else if (ageS > 3 * st.config.interval_s) add("warn", "The loop says it is running but the last cycle started " + Math.round(ageS / 60) + " min ago (interval " + Math.round(st.config.interval_s / 60) + " min): it may be stalled.");
    }
    if (st.runner && !st.runner.running && st.config && (st.config.auto_entries || st.config.auto_exits))
      add("warn", "Automatic actions are enabled but the loop is stopped, so nothing runs on its own.");
    if (res) {
      if (res.status !== "SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE") add("warn", "Results: only " + res.closed_trades + " closed trade(s); too few to judge anything.");
      const u = res.open_positions ? res.open_positions.unrealized_pnl_usd : null;
      if (u === null || u === undefined) add("warn", "Open-position profit or loss cannot be fully measured right now.");
    }
    return out;
  }

  // Severity order for the glance list: things that need you come first, routine OK lines last.
  // Stable: lines of equal severity keep their original order. Pure function, exposed for tests.
  function orderGlance(items) {
    const rank = { bad: 0, warn: 1, ok: 2 };
    return items
      .map((i, n) => ({ i, n }))
      .sort((a, b) => (rank[a.i.level] - rank[b.i.level]) || (a.n - b.n))
      .map((x) => x.i);
  }

  function glanceCounts(items) {
    const c = { bad: 0, warn: 0, ok: 0 };
    items.forEach((i) => { if (c[i.level] !== undefined) c[i.level] += 1; });
    return c;
  }

  function renderGlance(items) {
    const box = $("glance");
    box.replaceChildren();
    const c = glanceCounts(items);
    const worst = c.bad ? "bad" : c.warn ? "warn" : "ok";
    const sum = $("attn-summary");
    if (sum) {
      const top = orderGlance(items)[0];
      sum.replaceChildren();
      sum.appendChild(el("span", worst === "bad" ? "Needs you" : worst === "warn" ? "Check" : "All clear", "pill " + worst));
      sum.appendChild(el("span", c.bad ? c.bad + " action, " + c.warn + " notes" : c.warn + " notes, nothing urgent", "muted"));
      if (top && top.level !== "ok") sum.appendChild(el("span", top.text.length > 110 ? top.text.slice(0, 107) + "..." : top.text, top.level));
      $("attn").open = worst === "bad";
    }
    box.appendChild(el("div", worst === "bad" ? "Needs your attention" : worst === "warn" ? "Check these" : "Nothing needs you right now", "pill " + worst));
    box.appendChild(el("span", " " + c.bad + " action, " + c.warn + " note, " + c.ok + " ok (most urgent first)", "muted"));
    const ul = el("ul");
    orderGlance(items).forEach((i) => ul.appendChild(el("li", (i.level === "ok" ? "OK: " : i.level === "warn" ? "Note: " : "ACTION: ") + i.text, i.level)));
    box.appendChild(ul);
  }

  // ---- Now page (design proposal 2026-11-25): one verdict, the vitals, a "Needs you" list, evidence next to every result ----
  // Standing cautions are true all the time by design (the owner turned automatic entries on), so they are shown in the full
  // notes but never raise the state to Watch. Everything else that is not OK does.
  const STANDING = [/Automatic entries are ON/, /no daily loss halt/, /^Results: only \d+ closed/]; // the last one is what the evidence meter already shows
  const isStanding = (i) => STANDING.some((re) => re.test(i.text));
  // Evidence level of a sample of closed trades: 1 too early, 2 building, 3 enough to look at (never proof of an edge).
  function evidenceLevel(n) { return !(n >= 10) ? 1 : n >= MIN_TRADES ? 3 : 2; }
  const EVIDENCE_WORDS = ["", "Too early", "Building", "Enough to look at"];
  function exposure(trades) {
    // Share of OPEN option trades that are puts, and across how many names. Only measures what is open; never predicts.
    const open = (trades || []).filter((t) => t.instrument === "options" && t.status !== "CLOSED" && t.right);
    const puts = open.filter((t) => String(t.right).toUpperCase().charAt(0) === "P"), names = new Set(open.map((t) => t.symbol));
    const pct = open.length ? Math.round(puts.length / open.length * 100) : null;
    return { open: open.length, puts: puts.length, calls: open.length - puts.length, names: names.size, putPct: pct };
  }
  // The state of the whole platform from the glance lines plus the exposure reading. Pure function, exposed for tests.
  function nowState(items, expo) {
    const list = items.slice();
    // Engineering threshold, chosen before any result: more than two thirds one way, 4+ open trades, 3+ names.
    if (expo && expo.open >= 4 && expo.names >= 3 && (expo.putPct >= 67 || expo.putPct <= 33))
      list.push({ level: "warn", text: "Open exposure leans one way: " + (expo.putPct >= 67 ? expo.putPct + "% puts" : (100 - expo.putPct) + "% calls") + " across " + expo.names + " names, so one market move hits them all together." });
    const needs = orderGlance(list).filter((i) => i.level !== "ok" && !isStanding(i));
    const bad = needs.filter((i) => i.level === "bad");
    if (bad.length) return { state: "act", needs, headline: "Act now: " + bad[0].text };
    if (needs.length) return { state: "watch", needs, headline: needs.length === 1 ? "Watch: one thing to look at." : "Watch: " + needs.length + " things to look at." };
    return { state: "clear", needs, headline: "Nothing needs you. Autopilot is running within limits." };
  }
  // What happened since the owner last looked (decision lines newer than sinceMs). Counts only, from the journal.
  function digestText(decisions, sinceMs) {
    if (!sinceMs) return "First visit in this browser, so there is no earlier look to compare with.";
    const c = {};
    (decisions || []).filter((d) => Date.parse(d.ts) > sinceMs).forEach((d) => { const v = decisionVerdict(d).id; c[v] = (c[v] || 0) + 1; });
    const hrs = Math.max(1, Math.round((Date.now() - sinceMs) / 3600000));
    const parts = [["taken", "entr", "y", "ies"], ["exit", "exit", "", "s"], ["blocked", "blocked", "", ""], ["skipped", "skipped", "", ""]]
      .filter((p) => c[p[0]]).map((p) => c[p[0]] + " " + (p[0] === "taken" ? (c[p[0]] === 1 ? "entry" : "entries") : p[0] === "exit" ? (c[p[0]] === 1 ? "exit" : "exits") : p[1]));
    return "Since you last looked, " + hrs + " hour" + (hrs === 1 ? "" : "s") + " ago: " + (parts.length ? parts.join(", ") : "nothing was decided") + ". (Counts the latest journal lines only.)";
  }
  function lastSeen() { try { return Number(localStorage.getItem("optplat.lastSeen")) || 0; } catch (e) { return 0; } }
  function markSeen() { try { localStorage.setItem("optplat.lastSeen", String(Date.now())); } catch (e) { /* storage may be blocked */ } }
  function renderMeter(host, level) {
    host.replaceChildren();
    host.setAttribute("role", "img");
    host.setAttribute("aria-label", "Evidence: " + EVIDENCE_WORDS[level].toLowerCase());
    for (let n = 1; n <= 3; n++) host.appendChild(el("i", null, n <= level ? "on" : ""));
  }
  // The System band: which autonomy step the settings put it on, and the readiness evidence. Read-only; the owner judges.
  function systemReadiness(status, closed, shadow) {
    const c = status.config || {}, fict = !!(status.data_source && status.data_source.fictional);
    const step = status.kill_switch ? 1 : (c.auto_entries && c.auto_exits) ? 3 : 2;
    const ev = evidenceLevel(closed);
    const checks = [
      { key: "entry", title: "Entry quality", sub: "Results by lane against the baseline, above " + MIN_TRADES + " closed trades.", tag: ev === 3 ? "Enough to look at" : ev === 2 ? "Building" : "Too early", level: ev === 3 ? "info" : "warn" },
      { key: "exit", title: "Exit quality", sub: "Automatic exits on, with a stop and a target on every position.", tag: c.auto_exits ? "On" : "Exits off", level: c.auto_exits ? "info" : "warn" },
      { key: "real", title: "Real data only", sub: "Nothing on fictional data counts.", tag: fict ? "Fictional data" : "Real data", level: fict ? "warn" : "ok" },
      { key: "gate", title: "Shadow-book gate", sub: "Enough followed contracts and days to test a hypothesis.", tag: shadow && shadow.gate_met_except_export ? "Data numbers met" : "Building", level: shadow && shadow.gate_met_except_export ? "info" : "warn" },
      { key: "costs", title: "Costs included", sub: "Filled at the ask, closed at the bid, a fee each way, in every figure.", tag: "Met", level: "ok" },
      { key: "ops", title: "Operations", sub: "Restart recovery, runner health and a tested kill switch. This page cannot see whether the kill switch was ever tested.", tag: status.runner && status.runner.stalled ? "Runner stalled" : "You confirm", level: status.runner && status.runner.stalled ? "bad" : "warn" },
    ];
    return { step: step, checks: checks, guard: [["Per cycle", (c.max_new_per_cycle || "?") + " new entr" + (c.max_new_per_cycle === 1 ? "y" : "ies")], ["Take profit / stop", "+" + c.take_profit_pct + "% / -" + c.stop_loss_pct + "% of the premium"],
      ["Kill switch", status.kill_switch ? "ON: no new orders" : "Off"], ["Live order path", "None exists"], ["Broker connection", "Read-only"]] };
  }
  const STEPS = [["Off", "Kill switch on. No new orders."], ["Observe", "Automatic entries or exits are off, so nothing is placed on its own."], ["Paper, auto", "Places simulated orders and exits within limits, without asking."], ["Real money", "Not built. No live order path exists. An owner decision, never an automatic one."]];
  function renderSystemBand(status, closed, shadow) {
    const r = systemReadiness(status, closed, shadow), host = $("sys-ladder");
    host.replaceChildren();
    STEPS.forEach((st, i) => {
      const n = i + 1, now = n === r.step, lock = n === 4;
      const card = el("div", null, "rung" + (now ? " now" : "") + (lock ? " lock" : ""));
      kids(card, [el("div", "Step " + n + (now ? " \u00B7 current" : "") + (lock ? " \u00B7 locked" : ""), "eyebrow"), el("b", st[0]), el("p", st[1], "muted")]);
      host.appendChild(card);
    });
    $("sys-state").textContent = r.step === 3 ? "Cleared for paper. Not cleared for real money." : r.step === 1 ? "Stopped: the kill switch is on." : "Observing: nothing is placed on its own.";
    const ck = $("sys-checks"); ck.replaceChildren();
    r.checks.forEach((c) => { const row = el("div", null, "sys-check"); kids(row, [kids(el("div"), [el("b", c.title), el("div", c.sub, "muted")]), el("span", c.tag, "tag " + (c.level === "ok" ? "gain" : c.level === "bad" ? "loss" : c.level === "warn" ? "warn" : "info"))]); ck.appendChild(row); });
    const gd = $("sys-guard"); gd.replaceChildren();
    r.guard.forEach((g) => { const row = el("div", null, "sys-check"); kids(row, [el("span", g[0]), el("b", g[1])]); gd.appendChild(row); });
  }
  function renderNow(items, ctx) {
    const st = nowState(items, exposure(ctx.trades && ctx.trades.trades));
    const band = $("now-band");
    band.className = "band " + st.state;
    $("now-glyph").textContent = st.state === "clear" ? "\u25CF" : st.state === "watch" ? "\u25B2" : "\u25A0";
    $("now-label").textContent = st.state === "clear" ? "All clear" : st.state === "watch" ? "Watch" : "Act now";
    $("now-headline").textContent = st.headline;
    $("now-digest").textContent = digestText(ctx.decisions, ctx.since);
    const pf = ctx.portfolio, rn = ctx.status.runner || {};
    const guards = [];
    guards.push(ctx.health.mode === "PAPER" ? "paper only" : "NOT PAPER");
    guards.push(pf && pf.kill_switch ? "kill switch ON" : "kill switch off");
    guards.push(rn.stalled ? "loop stalled" : rn.running ? "loop running" : "loop stopped");
    $("vt-safety").textContent = (ctx.health.mode === "PAPER" && !(pf && pf.kill_switch) && !rn.stalled) ? "Within limits" : "Look here";
    $("vt-safety").className = "vv " + ((ctx.health.mode === "PAPER" && !(pf && pf.kill_switch) && !rn.stalled) ? "gain" : "loss");
    $("vt-safety-s").textContent = guards.join(" · ");
    const rep = ctx.report, base = (ctx.trades && ctx.trades.sources || []).find((x) => /frozen-baseline/.test(x.source));
    $("vt-result").textContent = rep.closed_trades ? sgn(rep.realized_pnl) : "No closed trades";
    $("vt-result").className = "vv num " + (rep.closed_trades ? tone(rep.realized_pnl) : "muted");
    $("vt-result-s").textContent = base ? "Frozen baseline lane: " + (base.closed ? sgn(base.realized_pnl) + " on " + base.closed + " closed" : "no closed trades yet") : "Long-term account. Baseline lane not found.";
    const lvl = evidenceLevel(rep.closed_trades);
    $("vt-ev").textContent = rep.closed_trades + " of " + MIN_TRADES;
    renderMeter($("vt-meter"), lvl);
    $("vt-ev-s").textContent = EVIDENCE_WORDS[lvl] + (ctx.shadow && typeof ctx.shadow.trading_days === "number" && ctx.shadow.gate ? " · shadow book " + ctx.shadow.trading_days + " of " + ctx.shadow.gate.trading_days + " days" : "");
    // Needs you
    const box = $("needs"), list = $("needs-list"), badge = $("nav-needs");
    list.replaceChildren();
    box.hidden = !st.needs.length;
    $("needs-count").textContent = String(st.needs.length);
    badge.hidden = !st.needs.length; badge.textContent = String(st.needs.length);
    st.needs.slice(0, 5).forEach((i) => {
      const row = el("div", null, "need");
      row.appendChild(el("span", i.level === "bad" ? "Act" : "Look", "tag " + (i.level === "bad" ? "loss" : "warn")));
      row.appendChild(el("div", i.text));
      list.appendChild(row);
    });
    if (st.needs.length > 5) list.appendChild(el("p", "+ " + (st.needs.length - 5) + " more in the full status notes below.", "muted"));
  }

  // ---- Lanes page (design proposal 2026-11-25): every lane on the same terms, sorted by evidence, with exposure ----
  function laneRole(x) { return x.source === "main" ? "Account" : /frozen-baseline/.test(x.source) ? "Benchmark" : x.instrument === "shares" ? "Shares" : "Experiment"; }
  // One row's verdict in plain words. Evidence first: a lane with under 10 closed trades is never called ahead or behind.
  function laneVerdict(x, baseline, trades) {
    const role = laneRole(x), lvl = evidenceLevel(x.closed);
    const mine = (trades || []).filter((t) => t.source === x.source), e = exposure(mine);
    if (e.open >= 3 && (e.putPct === 100 || e.putPct === 0)) return { tone: "warn", text: "Watch: " + e.open + " open, all " + (e.putPct === 100 ? "puts" : "calls") };
    if (role === "Benchmark") return { tone: "", text: "Reference" };
    if (!x.closed) return { tone: "", text: x.open ? "Open only, none closed" : "No trades yet" };
    if (lvl === 1) return { tone: "warn", text: "Too early" };
    if (!baseline || !baseline.closed) return { tone: "", text: "No baseline to compare" };
    return x.realized_pnl > baseline.realized_pnl ? { tone: "gain", text: "Ahead of the baseline" } : { tone: "loss", text: "Behind the baseline" };
  }
  function laneRows(data) {
    const base = data.sources.find((x) => /frozen-baseline/.test(x.source));
    const rows = data.sources.slice();
    if (!rows.some((x) => x.source === "main")) rows.push({ source: "main", label: "Options account", instrument: "options", total: 0, open: 0, closed: 0, wins: 0, win_rate_pct: null, realized_pnl: 0, open_pnl: 0 });
    rows.sort((a, b) => (evidenceLevel(b.closed) - evidenceLevel(a.closed)) || (b.realized_pnl - a.realized_pnl));
    return { rows, base };
  }
  function renderLanes(data) {
    if (!data) { empty($("ln-board"), "Could not load the lanes", "They appear once the page can reach /api/alltrades."); return; }
    const { rows, base } = laneRows(data), all = data.trades || [], ex = exposure(all);
    if (!rows.some((x) => x.source === S.laneSel)) S.laneSel = rows[0] ? rows[0].source : "";
    const verdicts = rows.map((x) => laneVerdict(x, base, all));
    const watch = verdicts.filter((v) => v.tone === "warn" && /^Watch/.test(v.text)).length;
    const enough = rows.filter((x) => evidenceLevel(x.closed) >= 2).length;
    $("ln-headline").textContent = watch ? "Watch: " + watch + " lane" + (watch === 1 ? " holds" : "s hold") + " a one-sided book." : enough ? enough + " of " + rows.length + " lanes have enough trades to compare." : "No lane has enough closed trades to rank on result yet.";
    $("ln-lede").textContent = "Sorted by evidence first, then result. A lane is only called ahead or behind the frozen baseline once it has at least 10 closed trades; 30 is the minimum before any figure counts." + (data.fictional ? " Fictional demo data." : "");
    const host = $("ln-board");
    host.replaceChildren();
    const head = el("div", null, "lb-row lb-head");
    ["Lane", "Realized", "Open now", "Evidence", "Verdict"].forEach((t, n) => head.appendChild(el("span", t, n === 1 || n === 2 ? "r" : "")));
    host.appendChild(head);
    rows.forEach((x, n) => {
      const b = el("button", null, "lb-row" + (x.source === S.laneSel ? " sel" : ""));
      b.type = "button";
      const name = el("span");
      name.appendChild(el("b", x.label)); name.appendChild(el("span", "  " + laneRole(x), "muted"));
      const real = span(arrow(x.realized_pnl) + sgn(x.realized_pnl), tone(x.realized_pnl) + " num r"), open = openNow(x, ""); open.className = (open.className || "") + " r";
      const lvl = evidenceLevel(x.closed), ev = el("span", null, "evrow"), m = el("div", null, "meter");
      renderMeter(m, lvl); ev.appendChild(m); ev.appendChild(el("span", x.closed + " closed", "muted"));
      const v = verdicts[n];
      kids(b, [name, real, open, ev, el("span", v.text, "tag " + v.tone)]);
      b.addEventListener("click", () => { S.laneSel = x.source; renderLanes(S.trades); });
      host.appendChild(b);
    });
    // exposure
    const xb = $("ln-exposure");
    xb.replaceChildren();
    if (!ex.open) xb.appendChild(el("p", "Nothing is open, so there is no exposure.", "muted"));
    else {
      const bar = el("div", null, "xbar"), p = el("i", null, "p"), c = el("i", null, "c");
      p.style.width = ex.putPct + "%"; c.style.width = (100 - ex.putPct) + "%";
      kids(bar, [p, c]);
      const labels = el("div", null, "toolbar"); kids(labels, [span(arrow(-1) + ex.putPct + "% puts", "loss"), span((100 - ex.putPct) + "% calls " + arrow(1), "gain")]);
      kids(xb, [labels, bar, el("p", ex.puts + " puts and " + ex.calls + " calls open across " + ex.names + " name" + (ex.names === 1 ? "" : "s") + ". The Watch line is more than two thirds one way across 3 or more names.", "muted")]);
    }
    // selected lane
    const sel = rows.find((x) => x.source === S.laneSel), d = $("ln-detail");
    d.replaceChildren();
    if (!sel) { empty(d, "No lane selected", ""); $("ln-detail-title").textContent = "Lane detail"; return; }
    $("ln-detail-title").textContent = sel.label;
    const fg = el("div", null, "figures");
    kids(fg, [fig(String(sel.open), "Open", sel.closed + " closed"), fig(sgn(sel.realized_pnl), "Realized", "after fees", tone(sel.realized_pnl)),
      fig(sel.open_complete === false ? "partial" : sgn(sel.open_pnl), "Open now", sel.open_complete === false ? sel.open_unmarked + " unmarked" : "marked at the bid", sel.open_complete === false ? "" : tone(sel.open_pnl))]);
    d.appendChild(fg);
    const mine = all.filter((t) => t.source === sel.source && t.status !== "CLOSED");
    const list = el("div", null, "feed");
    mine.slice(0, 8).forEach((t) => { const row = el("div", null, "feed-item"); kids(row, [el("span", t.label, "mono"), el("span", t.pnl === null ? "no quote" : sgn(t.pnl) + (t.pnl_pct === null ? "" : " (" + t.pnl_pct + "%)"), t.pnl === null ? "muted" : tone(t.pnl)), el("span", "")]); list.appendChild(row); });
    d.appendChild(list);
    const go = el("button", "Open this lane's trades", "linkbtn"); go.type = "button";
    go.addEventListener("click", () => { S.source = sel.source; S.kind = "all"; S.filter = "all"; S.shown = 100; location.hash = "#/trades"; });
    d.appendChild(go);
    if (!sel.closed) d.appendChild(el("p", "Exit reasons and what the closed trades teach appear once this lane has closed trades. Nothing is guessed before then.", "muted"));
  }

  // "Research progress": how far the shadow book is from its gate, and what sample a test could really claim.
  // Pure function of /api/shadow. Items are {level, text}; missing data is reported as unknown, never as fine.
  function buildResearchProgress(sh) {
    const out = [];
    const add = (level, text) => out.push({ level, text });
    if (!sh || typeof sh.followed !== "number" || !sh.gate) {
      add("warn", "Research progress unknown: the shadow-book report could not be read.");
      return out;
    }
    if (sh.fictional) add("warn", "The shadow book is following FICTIONAL demo data: none of this counts towards the research gate.");
    const g = sh.gate;
    const pct = (sh.complete_pct === null || sh.complete_pct === undefined) ? "n/a" : sh.complete_pct + "%";
    if (sh.followed === 0) add("warn", "Nothing is being followed yet, so no hypothesis can be tested. Candidates are recorded when a scan runs.");
    else add("ok", "Research gate (every line must hold): " + sh.trading_days + " of " + g.trading_days + " trading days, " +
      sh.underlyings + " of " + g.underlyings + " underlyings, " + sh.followed + " of " + g.followed + " followed contracts, " +
      pct + " of paths complete (need " + g.complete_pct + "%).");
    if (typeof sh.independent_observations === "number" && sh.followed > 0) add("warn", "Real sample size: " + sh.independent_observations +
      " independent observation(s) (one per name per day), not " + sh.followed + ". Several strikes of one name move together, so the larger count overstates the evidence.");
    add("ok", "The gate also needs the nightly export to run " + g.export_days_in_a_row + " days in a row. This page cannot see that; no hypothesis is registered until the owner confirms the gate.");
    return out;
  }

  function renderResearchProgress(items) {
    const box = $("research-progress");
    box.replaceChildren();
    const ul = el("ul");
    items.forEach((i) => ul.appendChild(el("li", (i.level === "ok" ? "OK: " : "Note: ") + i.text, i.level)));
    box.appendChild(ul);
  }

  function planFor(plans, contract, key) {
    const p = (plans || []).find((x) => x.contract === contract);
    return !p || p[key] === null || p[key] === undefined ? "unknown" : p[key];
  }

  function expiryExit(plans, contract) {
    const p = (plans || []).find((x) => x.contract === contract);
    if (!p) return "unknown";
    return p.expiry_exit_within_days + " days before " + p.expiry + " (" + p.days_to_expiry + " days left)";
  }

  // This is a local, paper-only dashboard: the server hands its token to this page when the page is on the same machine
  // (see /api/session). Falls back to the Connect screen when the server says no (for example OPTPLAT_REQUIRE_PASTED_TOKEN=1).
  async function autoConnect() {
    try {
      const r = await fetch("/api/session", { headers: { "X-Optplat-Page": "1" }, cache: "no-store" });
      if (!r.ok) return false;
      const j = await r.json();
      if (typeof j.token !== "string" || j.token.length < 16) return false;
      token = j.token; saveToken(token); return true;
    } catch (e) { return false; }
  }

  let retriedAutoConnect = false;
  async function refresh() {
    if (!token) await autoConnect();
    if (!token) { S.connected = false; showPage(); return; }
    try {
      const [health, status, portfolio, orders, report, decisions, eq, allTrades, results, policy, shadowRep] = await Promise.all([
        fetch("/api/health").then((r) => r.json()),
        api("/api/engine/status"), api("/api/portfolio"), api("/api/paper/orders"), api("/api/report"),
        api("/api/journal?limit=100"), api("/api/equity"), api("/api/alltrades").catch(() => null),
        api("/api/results").catch(() => null), api("/api/risk/policy").catch(() => null),
        api("/api/shadow").catch(() => null),
      ]);
      S.connected = true; S.core = { status, report };
      checkForNewBuild(health.build_id);
      if (allTrades) S.trades = allTrades;
      showPage();
      renderStrip(health, status, portfolio);
      renderTrust(status);
      renderDesk(portfolio, report, eq, status);
      renderAccounts(allTrades);
      renderLanes(allTrades);
      renderPositions(report, status.config, status.exit_plans);
      renderDecisions(decisions);
      renderOrders(orders);
      syncControls(status, status.config);
      const glanceItems = buildGlance(health, status, portfolio, results, policy);
      renderGlance(glanceItems);
      renderNow(glanceItems, { health, status, portfolio, report, trades: allTrades, decisions, shadow: shadowRep, since: S.since });
      renderResearchProgress(buildResearchProgress(shadowRep));
      renderSystemBand(status, (report.closed_trades !== undefined ? report.closed_trades : (allTrades && allTrades.trades ? allTrades.trades.filter((t) => t.status === "CLOSED").length : 0)), shadowRep);
      if (results) renderResults(results);
      renderCycleDecisions(status.last_cycle, status.recent_outcomes);
      renderCandidates(status.last_cycle);
      renderGex(status.last_cycle);
      renderFlow(status.last_cycle);
      await loadPage();
      setMsg("");
    } catch (e) {
      if (e.status === 401 || e.status === 403) { forgetToken(); token = ""; if (!retriedAutoConnect) { retriedAutoConnect = true; if (await autoConnect()) return refresh(); } S.connected = false; showPage(); setMsg("The saved token was not accepted (the server may have been set up again). Open the dashboard from the \"Open Options Dashboard\" link, or paste the token.", "loss"); }
      else if (S.connected) { $("updated").textContent = "Could not refresh: " + e.message; }
      else setMsg("Error: " + e.message, "loss");
    }
  }

  async function act(fn) { try { await fn(); } catch (e) { $("updated").textContent = "Error: " + e.message; } await refresh(); }

  $("btn-connect").addEventListener("click", () => {
    token = $("token").value.trim();
    saveToken(token);
    $("token").value = "";
    refresh();
  });
  $("btn-table").addEventListener("click", () => {
    const t = $("equity-table"), showing = t.hidden;
    t.hidden = !showing; $("equity-chart").hidden = showing;
    $("btn-table").textContent = showing ? "Show as chart" : "Show as table";
  });
  $("btn-lab").addEventListener("click", async () => { $("lab-status").textContent = "Running"; try { renderLab(await api("/api/lab/run", { method: "POST" })); $("lab-status").textContent = "Done"; } catch (e) { $("lab-status").textContent = "Could not run: " + e.message; } });
  $("btn-cycle").addEventListener("click", () => act(() => api("/api/engine/cycle", { method: "POST" })));
  $("btn-start").addEventListener("click", () => act(() => api("/api/engine/start", { method: "POST" })));
  $("btn-stop").addEventListener("click", () => act(() => api("/api/engine/stop", { method: "POST" })));
  $("btn-kill").addEventListener("click", () => act(() =>
    api("/api/risk/kill-switch", { method: "POST", body: JSON.stringify({ active: !S.killState, reason: "dashboard" }) })));
  $("btn-save").addEventListener("click", () => act(async () => { S.watchDirty = false; return api("/api/engine/config", {
    method: "PUT",
    body: JSON.stringify({
      auto_entries: $("cfg-entries").checked, auto_exits: $("cfg-exits").checked,
      enforce_market_hours: $("cfg-hours").checked, committee_mode: $("cfg-committee").value,
      scan_interval_s: Number($("cfg-scan").value), shortterm_enabled: $("cfg-shortterm").checked, swing_enabled: $("cfg-swing").checked, option_lanes_enabled: $("cfg-optlanes").checked,
      watchlist: $("cfg-watch").value.split(/[,\s]+/).filter(Boolean),
    }),
  }); }));
  $("cfg-watch").addEventListener("input", () => { S.watchDirty = true; });
  $("btn-sector").addEventListener("click", async () => { try {
    const sector = $("cfg-sector").value;
    if (!sector) return;
    const scan = await api("/api/scan"), hm = scan.result && scan.result.heat_map;
    const names = hm ? hm.names.filter((n) => n.sector === sector).sort((a, b) => b.dollar_volume - a.dollar_volume).map((n) => n.symbol) : [];
    const have = $("cfg-watch").value.split(/[,\s]+/).filter(Boolean);
    const add = names.filter((n) => have.indexOf(n) < 0).slice(0, 4);
    if (!add.length) { $("updated").textContent = hm ? "Nothing new to add from " + sector : "Run a market scan first so the names can be ranked"; return; }
    $("cfg-watch").value = have.concat(add).slice(0, 20).join(", ");
    S.watchDirty = true;
    $("updated").textContent = "Added " + add.join(", ") + ". Choose Save settings to use them.";
  } catch (e) { $("updated").textContent = "Error: " + e.message; } });
  $("btn-ch-restart").addEventListener("click", () => act(async () => { await api("/api/challenge/restart", { method: "POST" }); }));
  $("btn-op-step").addEventListener("click", () => act(async () => { await api("/api/optlanes/step", { method: "POST" }); }));
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
  const onBreak = () => { if (S.trades && route() === "trades") renderTrades(); if (route() === "shortterm") loadShortterm().catch(() => {}); if (route() === "swing") loadSwing().catch(() => {}); if (route() === "options" && S.opt) renderOptions(); };
  if (phone.addEventListener) phone.addEventListener("change", onBreak); else if (phone.addListener) phone.addListener(onBreak);
  window.addEventListener("hashchange", () => { if (takeTokenFromUrl()) { refresh(); return; } showPage(); if (S.connected && route() === "desk" && !$("equity-chart").hidden) drawEquity($("equity-chart"), S.lastPoints); if (S.connected) loadPage().catch((e) => { $("updated").textContent = "Error: " + e.message; }); });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (route() === "desk" && !$("equity-chart").hidden) drawEquity($("equity-chart"), S.lastPoints); }, 150);
  });
  window.optplatGlanceOrder = orderGlance;
  window.optplatResearch = buildResearchProgress;
  window.optplatVerdict = decisionVerdict;
  window.optplatDecisionFilter = filterDecisions;
  window.optplatTally = decisionTally;
  window.optplatSystem = systemReadiness; window.optplatLabGate = labGate; window.optplatLaneVerdict = laneVerdict; window.optplatNowState = nowState; window.optplatEvidence = evidenceLevel; window.optplatExposure = exposure; window.optplatDigest = digestText;
  window.optplatGlance = buildGlance; // exposed so tests can run it under node
  S.since = lastSeen(); // the previous look, kept for this whole visit so the digest does not reset itself every refresh
  window.addEventListener("pagehide", markSeen);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") markSeen(); });
  showPage();
  refresh();
  setInterval(refresh, 10000);
})();
