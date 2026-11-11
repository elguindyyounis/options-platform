(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
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
  let killState = false;
  let lastPoints = [];

  // Build DOM with textContent only: nothing from the API is ever parsed as HTML.
  const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  };
  const money = (n) => (n === null || n === undefined ? "n/a" : Number(n).toLocaleString(undefined, { style: "currency", currency: "USD" }));
  const setMsg = (text, cls) => { const m = $("msg"); m.textContent = text || ""; m.className = cls || "muted"; };

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({}, opts, {
      headers: { "X-API-Token": token, "content-type": "application/json" },
    }));
    let body = {};
    try { body = await r.json(); } catch (e) { /* empty body */ }
    if (!r.ok) {
      const d = body.detail;
      throw new Error(d ? (typeof d === "string" ? d : JSON.stringify(d)) : r.statusText);
    }
    return body;
  }

  function table(container, cols, rows, emptyText) {
    container.replaceChildren();
    if (!rows.length) { container.appendChild(el("div", emptyText, "muted")); return; }
    const t = el("table");
    const head = el("tr");
    cols.forEach((c) => head.appendChild(el("th", c.label)));
    t.appendChild(head);
    rows.forEach((row) => {
      const tr = el("tr");
      cols.forEach((c) => tr.appendChild(el("td", c.get(row))));
      t.appendChild(tr);
    });
    container.appendChild(t);
  }

  function pill(id, text, cls) { const e = $(id); e.textContent = text; e.className = "pill " + (cls || ""); }

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
  const shortMoney = (n) => Number(n).toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const fmtTime = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); };

  // Equity chart: one series, so no legend; the title line above names it. Built with createElementNS and
  // textContent only. The crosshair is keyboard-reachable (arrow keys) and a table view carries the same data.
  function drawEquity(host, points) {
    host.replaceChildren();
    if (points.length < 2) { host.appendChild(el("div", "Not enough history to draw a curve yet: it needs at least two completed cycles with trading allowed.", "muted")); return; }
    // Draw at the real pixel width so text stays 11px on a phone instead of scaling down with a fixed canvas.
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
    tip.appendChild(tv); tip.appendChild(tt); tip.appendChild(tc);
    host.appendChild(root); host.appendChild(tip);
    let idx = last;
    const show = (i) => {
      idx = Math.max(0, Math.min(last, i));
      const cx = X(xs[idx]), cy = Y(ys[idx]);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
      hot.setAttribute("cx", cx); hot.setAttribute("cy", cy); hot.setAttribute("visibility", "visible");
      tv.textContent = money(ys[idx]);
      tt.textContent = fmtTime(points[idx].ts);
      const delta = ys[idx] - start;
      tc.textContent = " | " + (delta >= 0 ? "+" : "") + money(delta) + " vs first point";
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

  function tile(label, value, sub) {
    const t = el("div", null, "tile");
    t.appendChild(el("div", label, "label")); t.appendChild(el("div", value, "value"));
    if (sub) t.appendChild(el("div", sub, "sub"));
    return t;
  }
  const pct = (v) => (v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%");

  function renderTrust(health, status) {
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

  function renderResults(portfolio, report, eq) {
    const a = portfolio.account, sm = eq.summary, t = $("tiles");
    t.replaceChildren();
    t.appendChild(tile("Equity", money(a.equity), "cash " + money(a.cash)));
    t.appendChild(tile("Since first point", sm.change_pct === null ? "n/a" : pct(sm.change_pct), sm.points + " points" + (eq.fictional ? ", fictional data" : "")));
    t.appendChild(tile("Drawdown now / worst", sm.current_drawdown_pct === null ? "n/a" : "-" + sm.current_drawdown_pct + "% / -" + sm.max_drawdown_pct + "%", "from the peak"));
    t.appendChild(tile("Closed trades", report.closed_trades, "realized " + money(report.realized_pnl) + (report.win_rate_pct === null ? "" : ", win rate " + report.win_rate_pct + "%")));
    t.appendChild(tile("Open premium", money(a.open_premium), report.open.length + " position(s)"));
    const need = Math.max(0, MIN_TRADES - report.closed_trades);
    $("sample").textContent = need
      ? "Not evidence yet: " + report.closed_trades + " closed trades, and at least " + MIN_TRADES + " are needed before any win rate or return means anything. " + report.caveat
      : report.closed_trades + " closed trades is above the minimum sample, but it does not show an edge on its own. " + report.caveat;
    lastPoints = eq.points;
    drawEquity($("equity-chart"), eq.points);
    table($("equity-table"), [
      { label: "Time", get: (p) => p.ts.slice(0, 19) }, { label: "Equity", get: (p) => money(p.equity) },
    ], eq.points.slice().reverse().slice(0, 200), "No equity points yet");
  }

  // "SPY261218C00600000" -> { expiry, dte }. Anything unparseable is shown as unknown, never guessed.
  function dteOf(contract, now) {
    const m = /^[A-Z.\-]{1,10}(\d{2})(\d{2})(\d{2})[CP]\d{8}$/.exec(contract || "");
    if (!m) return null;
    const exp = Date.UTC(2000 + Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.round((exp - today) / 86400000);
  }

  function renderPositions(report, cfg) {
    const now = new Date();
    table($("positions"), [
      { label: "Contract", get: (r) => r.contract }, { label: "Qty", get: (r) => r.quantity },
      { label: "Avg cost", get: (r) => r.avg_cost },
      { label: "Bid mark", get: (r) => r.mark === null ? "unobservable" : r.mark },
      { label: "Unrealized", get: (r) => money(r.unrealized_pnl) },
      { label: "Take profit at bid", get: (r) => cfg.auto_exits ? (r.avg_cost * (1 + cfg.take_profit_pct / 100)).toFixed(2) : "auto exits off" },
      { label: "Stop at bid", get: (r) => cfg.auto_exits ? (r.avg_cost * (1 - cfg.stop_loss_pct / 100)).toFixed(2) : "auto exits off" },
      { label: "Days to expiry", get: (r) => { const d = dteOf(r.contract, now); return d === null ? "unknown" : d + (d <= cfg.min_dte_to_hold ? " (forced exit zone)" : ""); } },
    ], report.open, "No open positions");
  }

  function renderResearch(list) {
    table($("research"), [
      { label: "Id", get: (h) => h.id }, { label: "Hypothesis", get: (h) => h.statement },
      { label: "Status", get: (h) => h.status + (h.intact ? "" : " (RECORD TAMPERED)") },
      { label: "Min trades", get: (h) => (h.criteria.min_trades || "") + " total / " + (h.criteria.min_oos_trades || "") + " out-of-sample" },
      { label: "Evaluations", get: (h) => h.evaluations },
    ], list, "No experiments registered. Register one with: python -m optplat.research register (the baseline stays frozen).");
  }

  const pctText = (v) => (v === null || v === undefined ? "n/a" : (v >= 0 ? "+" : "") + v + "%");
  function renderCommittee(c, cfg) {
    const sum = $("committee-summary");
    sum.className = "verdict" + (c.mode === "off" ? "" : " ok");
    const e = c.committee.WOULD_ENTER || { n: 0 }, r = c.committee.WOULD_REJECT || { n: 0 };
    sum.textContent = "Mode " + c.mode + ". It uses " + Math.round(c.trust * 100) + "% of its allowed order size, and that share moves with its hit rate. " +
      "Matured " + c.horizon_hours + "h outcomes: " + e.n + " entries" + (e.n ? " (" + pctText(e.mean_return_pct) + " avg)" : "") + ", " +
      r.n + " rejections" + (r.n ? " (" + pctText(r.mean_return_pct) + " avg if taken)" : "") + ".";
    const rows = Object.keys(c.weights).map((name) => {
      const a = c.agents[name] || { votes: {}, descriptive_only: true };
      const v = (s) => a.votes[s] ? a.votes[s].n + " calls, " + pctText(a.votes[s].mean_return_pct) + ", " + (a.votes[s].hit_rate === null ? "n/a" : Math.round(a.votes[s].hit_rate * 100) + "% up") : "none yet";
      return { name, weight: c.weights[name], support: v("SUPPORT"), oppose: v("OPPOSE"), note: a.descriptive_only ? "too few outcomes to judge" : "" };
    });
    table($("committee-agents"), [
      { label: "Agent", get: (x) => x.name }, { label: "Learned weight", get: (x) => Number(x.weight).toFixed(2) },
      { label: "When it said SUPPORT", get: (x) => x.support }, { label: "When it said OPPOSE", get: (x) => x.oppose },
      { label: "Note", get: (x) => x.note },
    ], rows, "No agents");
    const ul = $("committee-lessons"); ul.replaceChildren();
    (c.lessons.length ? c.lessons : ["No matured mistakes to learn from yet."]).forEach((t) => ul.appendChild(el("li", t)));
    table($("committee-history"), [
      { label: "Time", get: (h) => h.ts.slice(0, 19) }, { label: "Agent", get: (h) => h.agent }, { label: "Change", get: (h) => h.note },
    ], c.history, "No weight has moved yet");
    if (document.activeElement !== $("cfg-committee")) $("cfg-committee").value = cfg.committee_mode;
  }

  async function refresh() {
    if (!token) return;
    try {
      const [health, status, portfolio, orders, report, decisions, eq, hyps, committee] = await Promise.all([
        fetch("/api/health").then((r) => r.json()),
        api("/api/engine/status"),
        api("/api/portfolio"),
        api("/api/paper/orders"),
        api("/api/report"),
        api("/api/journal?limit=15"),
        api("/api/equity"),
        api("/api/research/hypotheses"),
        api("/api/committee"),
      ]);
      pill("mode", health.mode + " (" + (health.broker.broker || "broker") + ")", health.mode === "PAPER" ? "ok" : "bad");
      pill("data", status.data_source.name + (status.data_source.fictional ? " - FICTIONAL" : ""), status.data_source.fictional ? "warn" : "");
      pill("market", "market " + (status.market.open ? "open" : "closed") + ": " + status.market.reason, status.market.open ? "ok" : "");
      killState = !!portfolio.kill_switch;
      pill("kill", killState ? "KILL SWITCH ON" : "kill switch off", killState ? "bad" : "");
      const rn = status.runner;
      pill("runner",
        rn.stalled ? "LOOP STALLED: no good cycle for " + rn.seconds_since_success + "s" : (rn.running ? "loop running" : "loop stopped"),
        rn.stalled ? "bad" : (rn.running ? "ok" : ""));
      $("runner").title = rn.last_error ? "Last error: " + rn.last_error : "";
      $("cfg-entries").checked = status.config.auto_entries;
      $("cfg-exits").checked = status.config.auto_exits;
      $("cfg-hours").checked = status.market.hours_enforced;
      $("cfg-hours").disabled = status.market.hours_enforced && !status.data_source.fictional; // real data: always on
      if (document.activeElement !== $("cfg-watch")) $("cfg-watch").value = status.config.watchlist.join(", ");

      renderTrust(health, status);
      renderResults(portfolio, report, eq);
      renderPositions(report, status.config);
      renderResearch(hyps);
      renderCommittee(committee, status.config);

      const why = (d) => (d.payload.risk_failures && d.payload.risk_failures.length) ? d.payload.risk_failures.join("; ")
        : (d.payload.why || d.payload.reason || (d.payload.reasons && d.payload.reasons.join("; ")) || (d.payload.score !== undefined ? "score " + Number(d.payload.score).toFixed(2) : ""));
      table($("decisions"), [
        { label: "Time", get: (d) => d.ts.slice(0, 19) }, { label: "Type", get: (d) => d.kind },
        { label: "Contract", get: (d) => d.contract }, { label: "Outcome", get: (d) => d.disposition },
        { label: "Why", get: why },
      ], decisions, "No decisions recorded yet");

      table($("orders"), [
        { label: "Time", get: (o) => o.created_at.slice(0, 19) }, { label: "Side", get: (o) => o.intent.side },
        { label: "Contract", get: (o) => o.intent.contract.underlying + " " + o.intent.contract.expiry + " " + o.intent.contract.right + o.intent.contract.strike },
        { label: "Qty", get: (o) => o.filled_qty + "/" + o.intent.quantity }, { label: "Limit", get: (o) => o.intent.limit_price },
        { label: "Fill", get: (o) => o.avg_fill_price === null ? "" : o.avg_fill_price },
        { label: "State", get: (o) => o.state }, { label: "Why", get: (o) => o.risk_failures.join("; ") },
      ], orders.slice(0, 30), "No orders yet");
      setMsg("");
    } catch (e) {
      setMsg("Error: " + e.message, "bad");
    }
  }

  async function act(fn) { try { await fn(); } catch (e) { setMsg("Error: " + e.message, "bad"); } await refresh(); }

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
    api("/api/risk/kill-switch", { method: "POST", body: JSON.stringify({ active: !killState, reason: "dashboard" }) })));
  $("btn-save").addEventListener("click", () => act(() => api("/api/engine/config", {
    method: "PUT",
    body: JSON.stringify({
      auto_entries: $("cfg-entries").checked, auto_exits: $("cfg-exits").checked,
      enforce_market_hours: $("cfg-hours").checked, committee_mode: $("cfg-committee").value,
      watchlist: $("cfg-watch").value.split(/[,\s]+/).filter(Boolean),
    }),
  })));

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (!$("equity-chart").hidden) drawEquity($("equity-chart"), lastPoints); }, 150);
  });
  refresh();
  setInterval(refresh, 10000);
})();
