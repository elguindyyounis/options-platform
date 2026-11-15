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
      ["Early half vs later half", split.status === "CHECKED"
        ? money(split.first_half_pnl_usd) + " vs " + money(split.second_half_pnl_usd) + (split.consistent ? " (same sign)" : " (NOT consistent)")
        : "withheld until enough trades"],
      ["Unrealized P&L (marked to bid)", open.unrealized_pnl_usd === null || open.unrealized_pnl_usd === undefined
        ? "n/a: " + (open.error || ((open.unmarked || []).length + " position(s) cannot be marked")) : money(open.unrealized_pnl_usd)],
      ["Filled exits with no cost basis", r.unpriced_exits],
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
  function renderDecisions(c) {
    const rows = (c ? c.entries : []).map((x) => ({
      what: x.contract || x.symbol,
      outcome: RESULT_TEXT[x.result] || String(x.result),
      why: x.reason || (x.risk_failures || []).join("; ") || (x.rationale && x.rationale.trend ? "Trend " + x.rationale.trend + ", spread " + x.rationale.spread_pct + "%" : ""),
    }));
    $("decisions-note").textContent = c ? (c.entries_note || (rows.length ? "" : "No symbols were evaluated.")) : "No cycle has run yet.";
    table($("decisions-table"), [
      { label: "Symbol / contract", get: (r) => r.what }, { label: "Outcome", get: (r) => r.outcome }, { label: "Why", get: (r) => r.why },
    ], rows, "No entry decisions in the last cycle");
  }

  async function refresh() {
    if (!token) return;
    try {
      const [health, status, portfolio, orders, report, results] = await Promise.all([
        fetch("/api/health").then((r) => r.json()),
        api("/api/engine/status"),
        api("/api/portfolio"),
        api("/api/paper/orders"),
        api("/api/report"),
        api("/api/results"),
      ]);
      renderResults(results);
      renderDecisions(status.last_cycle);
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

      const a = portfolio.account;
      $("account").textContent = "Equity " + money(a.equity) + "  |  Cash " + money(a.cash) + "  |  Open premium " + money(a.open_premium);
      $("report").textContent = report.closed_trades + " closed trades, realized " + money(report.realized_pnl) +
        (report.win_rate_pct === null ? "" : ", win rate " + report.win_rate_pct + "%") + ". " + report.caveat;

      table($("positions"), [
        { label: "Contract", get: (r) => r.contract }, { label: "Qty", get: (r) => r.quantity },
        { label: "Avg cost", get: (r) => r.avg_cost }, { label: "Bid mark", get: (r) => r.mark === null ? "unobservable" : r.mark },
        { label: "Unrealized", get: (r) => money(r.unrealized_pnl) },
      ], report.open, "No open positions");

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

  refresh();
  setInterval(refresh, 10000);
})();
