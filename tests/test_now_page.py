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
  none:W.optplatDigest([dec('ENTRY','FILLED','2026-11-23T10:00:00Z')],since),
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
