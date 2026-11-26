"""The Now page (design proposal 2026-11-25): the verdict state, the evidence level, the exposure reading and the digest.

These are pure functions in app.js, run here under node. They only read API data; nothing here places or changes a trade.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
HARNESS = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);
const W=window, ok={level:'ok',text:'fine'}, warn=(t)=>({level:'warn',text:t}), bad=(t)=>({level:'bad',text:t});
const opt=(s,r,st)=>({instrument:'options',symbol:s,right:r,status:st||'OPEN'});
const heavy=[opt('A','P'),opt('B','P'),opt('C','P'),opt('D','P'),opt('E','C')];
const since=Date.parse('2026-11-24T00:00:00Z');
const dec=(kind,disp,ts)=>({kind,disposition:disp,ts});
console.log(JSON.stringify({
  clear:W.optplatNowState([ok],null),
  standing:W.optplatNowState([warn('Automatic entries are ON: the engine may buy'),warn('There is no daily loss halt: a bad day'),ok],null),
  thin:W.optplatNowState([warn('Results: only 2 closed trade(s); too few to judge anything.'),ok],null),
  fict:W.optplatNowState([warn('Market data is FICTIONAL demo data'),ok],null),
  act:W.optplatNowState([warn('x'),bad('Kill switch is ON: no new orders are accepted.')],null),
  lean:W.optplatNowState([ok],W.optplatExposure(heavy)),
  few:W.optplatNowState([ok],W.optplatExposure(heavy.slice(0,3))),
  closed:W.optplatExposure(heavy.map((t)=>({...t,status:'CLOSED'}))),
  expo:W.optplatExposure(heavy),
  ev:[null,0,9,10,29,30,100].map(W.optplatEvidence),
  first:W.optplatDigest([],0),
  dig:W.optplatDigest([dec('ENTRY','FILLED','2026-11-24T10:00:00Z'),dec('ENTRY','FILLED','2026-11-24T11:00:00Z'),dec('ENTRY','SKIPPED_HELD','2026-11-24T12:00:00Z'),dec('ENTRY','FILLED','2026-11-23T10:00:00Z')],since),
  lane:[
    W.optplatLaneVerdict({source:'frozen-baseline-options',closed:40,open:0,realized_pnl:100,instrument:'options'},null,[]),
    W.optplatLaneVerdict({source:'x',closed:0,open:2,realized_pnl:0,instrument:'options'},null,[]),
    W.optplatLaneVerdict({source:'x',closed:4,open:0,realized_pnl:900,instrument:'options'},{closed:40,realized_pnl:100},[]),
    W.optplatLaneVerdict({source:'x',closed:12,open:0,realized_pnl:900,instrument:'options'},{closed:40,realized_pnl:100},[]),
    W.optplatLaneVerdict({source:'x',closed:12,open:0,realized_pnl:-5,instrument:'options'},{closed:40,realized_pnl:100},[]),
    W.optplatLaneVerdict({source:'x',closed:12,open:0,realized_pnl:900,instrument:'options'},null,[]),
    W.optplatLaneVerdict({source:'s',closed:0,open:3,realized_pnl:0,instrument:'options'},null,[opt('A','P'),opt('B','P'),opt('C','P')].map((t)=>({...t,source:'s'}))),
  ],
  gate:[
    W.optplatLabGate(null,[]),
    W.optplatLabGate({fictional:true,followed:240,underlyings:43,trading_days:1,complete_pct:0,independent_observations:43,gate:{trading_days:20,followed:2000,underlyings:50,complete_pct:80,export_days_in_a_row:5}},[]),
    W.optplatLabGate({fictional:false,followed:0,underlyings:0,trading_days:0,complete_pct:null,gate:{trading_days:20,followed:2000,underlyings:50,complete_pct:80,export_days_in_a_row:5}},[]),
    W.optplatLabGate({fictional:false,followed:900,underlyings:30,trading_days:9,complete_pct:85,gate:{trading_days:20,followed:2000,underlyings:50,complete_pct:80,export_days_in_a_row:5}},[{status:'PASSED',intact:true},{status:'NOT_EVALUATED',intact:false}]),
    W.optplatLabGate({fictional:false,followed:2400,underlyings:55,trading_days:21,complete_pct:90,gate:{trading_days:20,followed:2000,underlyings:50,complete_pct:80,export_days_in_a_row:5}},[]),
  ],
  sys:[
    W.optplatSystem({config:{auto_entries:true,auto_exits:true,max_new_per_cycle:1,take_profit_pct:40,stop_loss_pct:30},data_source:{fictional:false},kill_switch:false,runner:{stalled:false}},40,{gate_met_except_export:true}),
    W.optplatSystem({config:{auto_entries:true,auto_exits:false},data_source:{fictional:true},kill_switch:false,runner:{stalled:false}},2,null),
    W.optplatSystem({config:{auto_entries:true,auto_exits:true},data_source:{fictional:false},kill_switch:true,runner:{stalled:true}},12,null),
  ],
  broker:[
    W.optplatSystem({config:{},data_source:{fictional:false},kill_switch:false,runner:{}},0,null,{broker:{connected:true,ibkr_mirror:{state:'idle'}}}),
    W.optplatSystem({config:{},data_source:{fictional:false},kill_switch:false,runner:{}},0,null,{broker:{connected:true}}),
    W.optplatSystem({config:{},data_source:{fictional:false},kill_switch:false,runner:{}},0,null),
  ].map((r)=>r.guard.find((g)=>g[0]==='Broker connection')[1]),
  none:W.optplatDigest([dec('ENTRY','FILLED','2026-11-23T10:00:00Z')],since),
  gap:[0,2,9,10,29,30,null].map(W.optplatEvidenceGap),
  fix:['Automatic actions are enabled but the loop is stopped, so nothing runs on its own.','Market-hours check is OFF: the engine may act','Kill switch is ON: no new orders are accepted.','Market data is FICTIONAL demo data'].map(W.optplatNeedAction),
  dis:[
    W.optplatDisagreement({kind:'ENTRY',disposition:'FILLED',payload:{committee:{decision:'WOULD_REJECT',mode:'shadow',reasons:['net conviction -0.16 is below 0.25']}}}),
    W.optplatDisagreement({kind:'ENTRY',disposition:'FILLED',payload:{committee:{decision:'WOULD_ENTER',mode:'shadow',reasons:[]}}}),
    W.optplatDisagreement({kind:'ENTRY',disposition:'RISK_REJECTED',payload:{committee:{decision:'WOULD_REJECT',mode:'shadow'}}}),
    W.optplatDisagreement({kind:'ENTRY',disposition:'FILLED',payload:{}}),
  ],
  ready:(()=>{
    const mk=(src,n,pnl,day0)=>Array.from({length:n},(_,i)=>({source:src,status:'CLOSED',pnl:pnl,opened_at:new Date(Date.UTC(2026,0,1+(day0||0)+i)).toISOString(),closed_at:new Date(Date.UTC(2026,0,2+(day0||0)+i)).toISOString()}));
    const base={source:'frozen-baseline-options',label:'Baseline',instrument:'options',closed:40,realized_pnl:400};
    const lane={source:'lane-a',label:'Lane A',instrument:'options',closed:40,realized_pnl:2000,hypothesis:{id:'L1',first_day:'2026-01-01'}};
    const trades=mk('lane-a',40,50).concat(mk('frozen-baseline-options',40,10));
    const ctx={base,trades,fictional:false,dataName:'ibkr-shared-research-only'};
    return {
      good:W.optplatReadiness(lane,ctx),
      fict:W.optplatReadiness(lane,{...ctx,fictional:true}),
      yahoo:W.optplatReadiness(lane,{...ctx,dataName:'yahoo-unofficial'}),
      oneday:W.optplatReadiness(lane,{...ctx,trades:mk('lane-a',40,50).map((t)=>({...t,opened_at:'2026-01-01T15:00:00Z'}))}),
      unreg:W.optplatReadiness({...lane,hypothesis:null},ctx),
      split:W.optplatReadiness(lane,{...ctx,trades:mk('lane-a',20,-30).concat(mk('lane-a',20,130,20))}),
      shares:W.optplatReadiness({source:'swing-pullback',label:'Swing',instrument:'shares',closed:3,realized_pnl:5,hypothesis:{id:'SW1',first_day:'2026-11-27'}},ctx),
      main:W.optplatReadiness({source:'main',label:'Options account',instrument:'options',closed:2,realized_pnl:-617},ctx),
    };
  })(),
  mirror:(()=>{
    const o={intent:{idempotency_key:'k1'}}, byKey={k1:{ibkr_avg_fill_price:1.95,ibkr_better_by_per_share:0.05,ibkr_status:'FILLED'},k2:{ibkr_avg_fill_price:null,ibkr_better_by_per_share:null,ibkr_status:'SUBMITTED'}};
    const lane={source:'lane-a',label:'Lane A',instrument:'options',closed:2,realized_pnl:0};
    const ctx=(sm)=>({base:null,trades:[],fictional:false,dataName:'ibkr',mirror:sm?{summary:sm}:null});
    return {
      cells:[W.optplatMirrorCells(o,byKey),W.optplatMirrorCells({intent:{idempotency_key:'k2'}},byKey),W.optplatMirrorCells({intent:{idempotency_key:'zz'}},byKey)],
      none:W.optplatMirrorLine({summary:{mirrored_orders:0},notes:[]}),
      some:W.optplatMirrorLine({summary:{mirrored_orders:5,both_filled:4,ibkr_better_by_per_share_median:-0.03,sim_filled_ibkr_not:1},notes:['Only 4 orders filled in both books; too few.']}),
      f6:[null,{mirrored_orders:3,both_filled:3},{mirrored_orders:40,both_filled:31,ibkr_better_by_per_share_median:0.01},{mirrored_orders:40,both_filled:31,ibkr_better_by_per_share_median:-0.02}]
        .map((sm)=>W.optplatReadiness(lane,ctx(sm)).checks.find((c)=>c.id==='fills')),
    };
  })(),
  why:[W.optplatWhy({payload:{rank:1,of:6,score:96.15}}),W.optplatWhy({payload:{score:88.6}}),W.optplatWhy({payload:{rank:1,of:1,risk_failures:['too wide']}}),W.optplatWhy({payload:{rank:3,of:9,score:50}})],
}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", HARNESS, str(ROOT / "app.js")], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_state_is_clear_watch_or_act_and_standing_cautions_never_raise_it(out):
    assert out["clear"]["state"] == "clear" and out["clear"]["needs"] == []
    assert out["standing"]["state"] == "clear"  # automatic entries are on by the owner's decision: shown in the notes, not a Watch
    assert out["thin"]["state"] == "clear"  # a small sample is shown by the evidence meter, it does not need the owner
    assert out["fict"]["state"] == "watch" and len(out["fict"]["needs"]) == 1  # fictional data is never "all clear"
    assert out["act"]["state"] == "act" and out["act"]["headline"].startswith("Act now: Kill switch is ON")
    assert out["act"]["needs"][0]["level"] == "bad"  # most urgent first


def test_one_sided_open_exposure_raises_watch_but_only_with_enough_trades_and_names(out):
    assert out["expo"] == {"open": 5, "puts": 4, "calls": 1, "names": 5, "putPct": 80}
    assert out["lean"]["state"] == "watch" and "80% puts across 5 names" in out["lean"]["needs"][0]["text"]
    assert out["few"]["state"] == "clear"  # three trades are too few to call a pile-up
    assert out["closed"]["open"] == 0 and out["closed"]["putPct"] is None  # closed trades are not exposure


def test_evidence_level_is_too_early_below_ten_building_below_thirty_and_enough_after(out):
    assert out["ev"] == [1, 1, 1, 2, 2, 3, 3]


def test_digest_counts_only_decisions_after_the_last_look_and_says_so_when_there_was_none(out):
    assert "First visit" in out["first"]
    assert "2 entries" in out["dig"] and "1 skipped" in out["dig"] and "3 entries" not in out["dig"]
    assert "nothing was decided" in out["none"]


def test_front_page_dom_has_the_band_the_needs_list_and_keeps_the_old_status_ids():
    html = (ROOT / "index.html").read_text()
    js = (ROOT / "app.js").read_text()
    for ident in ("now-band", "now-headline", "needs-list", "vt-meter", "nav-needs", "attn", "glance", "trust-verdict"):
        assert f'id="{ident}"' in html, ident
    assert "innerHTML" not in js and "optplat.lastSeen" in js


def test_lane_verdict_never_calls_a_thin_lane_ahead_and_flags_a_one_sided_book(out):
    v = [x["text"] for x in out["lane"]]
    assert v == ["Reference", "Open only, none closed", "Too early", "Ahead of the baseline", "Behind the baseline",
                 "No baseline to compare", "Watch: 3 open, all puts"]
    assert out["lane"][2]["tone"] == "warn"  # 4 closed trades and +$900 is still only "too early"
    assert 'id="view-lanes"' in (ROOT / "index.html").read_text() and 'data-question="Which approach is working' in (ROOT / "index.html").read_text()


def test_lane_options_trades_open_the_drawer_trade_file():
    js = (ROOT / "app.js").read_text()
    assert 'else if (t.instrument === "options" && t.detail) openLaneTrade(t, node)' in js
    assert "function renderLaneFile" in js and "function laneLadder" in js
    for ident in ("drawer-title", "drawer-sub", "drawer-body", "scrim", "drawer", "btn-drawer-close"):
        assert f'id="{ident}"' in (ROOT / "index.html").read_text()


def test_lab_gate_reads_the_shadow_book_and_never_claims_readiness_it_cannot_see(out):
    unknown, fict, empty, building, ready = out["gate"]
    assert unknown["state"] == "unknown" and unknown["rows"] == []
    assert fict["state"] == "early" and "fictional" in fict["text"].lower()
    assert empty["state"] == "early" and "Nothing is being followed" in empty["text"]
    assert building["state"] == "building" and [r["met"] for r in building["rows"]] == [False, False, False, True]
    assert building["hyps"]["total"] == 2 and building["hyps"]["tampered"] == 1
    assert ready["state"] == "ready" and "you confirm" in ready["text"]
    assert all(0 <= r["pct"] <= 100 for r in ready["rows"])


def test_no_two_functions_share_a_name_in_app_js():
    """A duplicate declaration silently replaced the registered-experiments renderer once."""
    import re
    names = re.findall(r"^  (?:async )?function ([A-Za-z0-9_]+)\(", (ROOT / "app.js").read_text(), re.M)
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, dupes


def test_system_ladder_follows_the_settings_and_real_money_is_never_a_step_you_can_be_on(out):
    live, observe, killed = out["sys"]
    assert (live["step"], observe["step"], killed["step"]) == (3, 2, 1)
    tags = {c["key"]: c for c in live["checks"]}
    assert tags["entry"]["tag"] == "Enough to look at" and tags["real"]["tag"] == "Real data" and tags["gate"]["tag"] == "Data numbers met"
    # Operations is always the owner's call: the page cannot see a kill-switch test.
    assert tags["ops"]["tag"] == "You confirm"
    o = {c["key"]: c for c in observe["checks"]}
    assert o["entry"]["tag"] == "Too early" and o["real"]["level"] == "warn" and o["exit"]["tag"] == "Exits off"
    assert {c["key"]: c for c in killed["checks"]}["ops"]["tag"] == "Runner stalled"
    assert ["Live order path", "None exists"] in live["guard"]


def test_evidence_gap_says_how_far_to_the_next_level(out):
    words = [g["decide"] for g in out["gap"]]
    assert words == ["No", "No", "No", "Not yet", "Not yet", "Look", "No"]  # unknown counts as no evidence
    assert out["gap"][1]["more"] == 8 and "8 more closed trades to directional" in out["gap"][1]["text"]
    assert out["gap"][2]["text"].startswith("1 more closed trade to")  # singular
    assert out["gap"][3]["more"] == 20 and "until it counts" in out["gap"][3]["text"]
    assert "not proof of an edge" in out["gap"][5]["text"]


def test_needs_you_buttons_only_switch_safe_things_back_on(out):
    start, hours, kill, fict = out["fix"]
    assert start == {"id": "start", "label": "Start loop"}
    assert hours["id"] == "hours"
    assert kill is None and fict is None  # turning the kill switch off or accepting demo data stays a System-page choice


def test_disagreement_flags_only_a_taken_trade_the_committee_would_refuse(out):
    flagged, agreed, blocked, none = out["dis"]
    assert flagged and "would have rejected" in flagged and "net conviction" in flagged
    assert agreed is None and blocked is None and none is None


def test_activity_shows_rank_not_a_bare_score(out):
    ranked, legacy, failed, lower = out["why"]
    assert "did not fit the size cap" not in ranked and "did not fit the size cap" in lower
    assert ranked.startswith("ranked #1 of 6 eligible candidates") and "ranking only" in ranked
    assert "no pass mark" in legacy  # older journal lines without a rank
    assert failed == "too wide"  # a risk refusal is still the reason shown


def _ck(r):
    return {c["id"]: c["state"] for c in r["checks"]}


def test_readiness_never_says_ready_while_a_check_is_waiting_or_failing(out):
    r = out["ready"]
    good = _ck(r["good"])
    assert [c["id"] for c in r["good"]["checks"]] == ["data", "sample", "beats", "registered", "halves", "fills"]
    assert good == {"data": "pass", "sample": "pass", "beats": "pass", "registered": "pass", "halves": "pass", "fills": "wait"}
    assert r["good"]["ready"] is False  # no IBKR mirror data, so the fill check waits and nothing is ready
    assert _ck(r["fict"])["data"] == "fail" and _ck(r["yahoo"])["data"] == "fail"
    assert _ck(r["oneday"])["sample"] == "fail"  # 40 trades on one day are one observation, not 40
    assert _ck(r["unreg"])["registered"] == "fail"
    assert _ck(r["split"])["halves"] == "fail"  # older half lost, newer half won: not consistent


def test_readiness_marks_what_does_not_apply(out):
    r = out["ready"]
    sh, main = _ck(r["shares"]), _ck(r["main"])
    assert sh["fills"] == "na" and sh["beats"] == "wait" and sh["registered"] == "pass"
    assert main["beats"] == "na" and main["registered"] == "na" and main["sample"] == "fail"
    assert r["main"]["gap"]["more"] == 8 and r["main"]["ready"] is False


def test_orders_show_the_ibkr_fill_and_the_gap_from_the_traders_side(out):
    m = out["mirror"]
    filled, working, unknown = m["cells"]
    assert filled == {"fill": "1.95", "gap": "+0.05 IBKR better"}
    assert working == {"fill": "Submitted", "gap": ""} and unknown == {"fill": "", "gap": ""}
    assert "switches it on" in m["none"]
    assert "median IBKR worse by 0.03" in m["some"] and "not at IBKR" in m["some"] and "too few" in m["some"]


def test_fill_check_waits_for_30_paired_fills_then_needs_ibkr_no_worse(out):
    states = [c["state"] for c in out["mirror"]["f6"]]
    assert states == ["wait", "wait", "pass", "fail"]
    assert out["mirror"]["f6"][1]["text"] == "3 of 30 paired fills"


def test_system_guardrail_says_whether_orders_are_mirrored_to_ibkr_paper(out):
    mirrored, sim, unknown = out["broker"]
    assert "IBKR paper mirror" in mirrored and "DU" in mirrored
    assert sim == "Simulator only" and unknown == "Unknown"
