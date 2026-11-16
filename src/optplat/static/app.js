(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let token = "";
  try { token = sessionStorage.getItem("optplat_token") || ""; } catch (e) { /* storage unavailable */ }
  let killState = false;

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

  const pct = (n) => (n === null || n === undefined ? "n/a" : n + "%");
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

  // Results come from /api/results; every value is shown as text, and gaps are shown as "n/a", never as zero.
  function renderResults(r) {
    const split = r.split_half || {};
    const open = r.open_positions || {};
    const bad = r.status !== "SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE";
    $("results-status").replaceChildren(
      el("div", (STATUS_TEXT[r.status] || String(r.status)) + " (" + r.closed_trades + " of " + r.min_trades_required + " trades)", bad ? "warn" : ""));
    const rows = [
      ["Realized P&L (closed trades)", money(r.realized_pnl_usd)],
      ["Win rate", pct(r.win_rate_pct)],
      ["P&L without the best trade", money(r.pnl_without_best_trade_usd)],
      ["Worst closed-trade drawdown (not account drawdown)", pct(r.closed_trade_max_drawdown_pct)],
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

  function renderDecisions(c, recent) {
    const rows = (c ? c.entries : []).map((x) => ({
      what: x.contract || x.symbol,
      outcome: RESULT_TEXT[x.result] || String(x.result),
      why: x.reason || (x.risk_failures || []).join("; ") || (x.rationale && x.rationale.trend ? "Trend " + x.rationale.trend + ", spread " + x.rationale.spread_pct + "%" : ""),
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
      ? "Contracts that passed the strategy filters, best score first. The score ranks liquidity and closeness to the price; it is not a chance of profit. Symbols after a buy in the same cycle are not scanned."
      : "No cycle has run yet.";
    table($("candidates-table"), [
      { label: "Contract", get: (r) => r.contract }, { label: "Trend", get: (r) => r.trend },
      { label: "Score", get: (r) => r.score }, { label: "Limit", get: (r) => r.limit_price },
      { label: "Spread %", get: (r) => r.spread_pct }, { label: "Days to expiry", get: (r) => r.dte },
      { label: "Volume", get: (r) => (r.volume == null ? "not reported" : r.volume) },
      { label: "Open interest", get: (r) => (r.open_interest == null ? "not reported" : r.open_interest) },
    ], rows, "No contract passed the filters in the last cycle");
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
    if (st.config && st.config.auto_entries) add("warn", "Automatic entries are ON: the engine may buy paper contracts by itself.");
    else if (st.config) add("ok", "Automatic entries are off: nothing is bought unless you press Run one cycle.");
    if (st.market) {
      if (st.market.open) add("ok", "Market is open (" + st.market.reason + ").");
      else add("ok", "Market is closed (" + st.market.reason + "): " + (st.config && st.config.enforce_market_hours === false ? "but the market-hours check is off, see below." : "no new paper trades until it opens."));
    } else add("warn", "Market session unknown.");
    if (st.config && st.config.enforce_market_hours === false) add("warn", "Market-hours check is OFF: the engine may act outside the session, on quotes that may be stale.");
    if (pol && pol.require_verified_quote_time === false) add("warn", "Quote-time verification is OFF.");
    if (pol && typeof pol.max_position_pct === "number")
      add("ok", "Risk limits: up to " + pol.max_position_pct + "% of equity per order, " + pol.max_total_premium_pct + "% open in total, " + pol.max_open_positions + " positions.");
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

  function renderGlance(items) {
    const box = $("glance");
    box.replaceChildren();
    const worst = items.some((i) => i.level === "bad") ? "bad" : items.some((i) => i.level === "warn") ? "warn" : "ok";
    box.appendChild(el("div", worst === "bad" ? "Needs your attention" : worst === "warn" ? "Check these" : "Nothing needs you right now", "pill " + worst));
    const ul = el("ul");
    items.forEach((i) => ul.appendChild(el("li", (i.level === "ok" ? "OK: " : i.level === "warn" ? "Note: " : "ACTION: ") + i.text, i.level)));
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

  async function refresh() {
    if (!token) return;
    try {
      const [health, status, portfolio, orders, report, results, policy] = await Promise.all([
        fetch("/api/health").then((r) => r.json()),
        api("/api/engine/status"),
        api("/api/portfolio"),
        api("/api/paper/orders"),
        api("/api/report"),
        api("/api/results"),
        api("/api/risk/policy"),
      ]);
      renderGlance(buildGlance(health, status, portfolio, results, policy));
      renderResults(results);
      renderDecisions(status.last_cycle, status.recent_outcomes);
      renderCandidates(status.last_cycle);
      renderGex(status.last_cycle);
      pill("mode", health.mode + " (" + (health.broker.broker || "broker") + ")", health.mode === "PAPER" ? "ok" : "bad");
      pill("data", status.data_source.name + (status.data_source.fictional ? " - FICTIONAL" : ""), status.data_source.fictional ? "warn" : "");
      pill("market", "market " + (status.market.open ? "open" : "closed") + ": " + status.market.reason, status.market.open ? "ok" : "");
      killState = !!portfolio.kill_switch;
      pill("kill", killState ? "KILL SWITCH ON" : "kill switch off", killState ? "bad" : "");
      pill("runner", status.runner.running ? "loop running" : "loop stopped", status.runner.running ? "ok" : "");
      $("cfg-entries").checked = status.config.auto_entries;
      $("cfg-exits").checked = status.config.auto_exits;
      $("cfg-hours").checked = status.config.enforce_market_hours;
      if (document.activeElement !== $("cfg-watch")) $("cfg-watch").value = status.config.watchlist.join(", ");

      const plans = status.exit_plans || [];
      const a = portfolio.account;
      $("account").textContent = "Equity " + money(a.equity) + "  |  Cash " + money(a.cash) + "  |  Open premium " + money(a.open_premium);
      $("report").textContent = report.closed_trades + " closed trades, realized " + money(report.realized_pnl) +
        (report.win_rate_pct === null ? "" : ", win rate " + report.win_rate_pct + "%") + ". " + report.caveat;

      table($("positions"), [
        { label: "Contract", get: (r) => r.contract }, { label: "Qty", get: (r) => r.quantity },
        { label: "Avg cost", get: (r) => r.avg_cost }, { label: "Bid mark", get: (r) => r.mark === null ? "unobservable" : r.mark },
        { label: "Unrealized", get: (r) => money(r.unrealized_pnl) },
        { label: "Take-profit when bid reaches", get: (r) => planFor(plans, r.contract, "take_profit_bid") },
        { label: "Stop when bid falls to", get: (r) => planFor(plans, r.contract, "stop_loss_bid") },
        { label: "Leaves for expiry by", get: (r) => expiryExit(plans, r.contract) },
      ], report.open, "No open positions");
      $("positions-note").textContent = status.config.auto_exits
        ? "Automatic exits are ON: the loop sells at these levels using the bid, if a fresh quote exists. No fresh quote means no exit and a warning, never a guess. Levels are rules, not predictions; fills are simulated."
        : "Automatic exits are OFF: nothing sells by itself. The levels shown are what the rules would use if you turned exits on.";

      const c = status.last_cycle;
      $("cycle").textContent = c ? ("Started " + c.started_at + ". " + (c.entries_note || "") + (c.errors.length ? " Errors: " + c.errors.join("; ") : "")) : "No cycle has run yet";
      const rows = c ? c.exits.map((x) => ({ kind: "exit", name: x.contract, action: x.action, detail: (x.trigger || x.reason) + (x.result ? " -> " + x.result : "") }))
        .concat(c.entries.map((x) => ({ kind: "entry", name: x.contract || x.symbol, action: x.result, detail: (x.risk_failures || []).join("; ") }))) : [];
      table($("cycle-table"), [
        { label: "Type", get: (r) => r.kind }, { label: "Contract", get: (r) => r.name },
        { label: "Result", get: (r) => r.action }, { label: "Detail", get: (r) => r.detail },
      ], rows, "Nothing to show");

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
  $("btn-cycle").addEventListener("click", () => act(() => api("/api/engine/cycle", { method: "POST" })));
  $("btn-start").addEventListener("click", () => act(() => api("/api/engine/start", { method: "POST" })));
  $("btn-stop").addEventListener("click", () => act(() => api("/api/engine/stop", { method: "POST" })));
  $("btn-kill").addEventListener("click", () => act(() =>
    api("/api/risk/kill-switch", { method: "POST", body: JSON.stringify({ active: !killState, reason: "dashboard" }) })));
  $("btn-save").addEventListener("click", () => act(() => api("/api/engine/config", {
    method: "PUT",
    body: JSON.stringify({
      auto_entries: $("cfg-entries").checked, auto_exits: $("cfg-exits").checked,
      enforce_market_hours: $("cfg-hours").checked,
      watchlist: $("cfg-watch").value.split(/[,\s]+/).filter(Boolean),
    }),
  })));

  window.optplatGlance = buildGlance; // exposed so tests can run it under node
  refresh();
  setInterval(refresh, 10000);
})();
