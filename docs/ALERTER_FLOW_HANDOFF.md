# Handoff for the options-alerter (owner asked: "implement this for the rest of the accounts")

The challenger has read-only access to options-alerter, and the alerter's accounts (swing-aggressive, challenge-1k and the other
lanes) live on the owner's Mac, so this was NOT implemented there. Findings for a session that works in that repo:

* The alerter already has the radar: `unusual_activity.py` (`MIN_VOLUME_OI_RATIO = 3`, EXTREME tier) and it would flag all three
  screenshot examples. It labels every hit `OBSERVE_ONLY` when the contract is short-dated and 20%+ OTM, or fails
  `entry_quality`, and says aggressor side and opening trades are unverified.
* So the open question is not detection but policy: should a flow hit ever feed a lane's candidates, and at what size? The
  owner's 2026-11-15 aggressive-sizing note ranks ideas by the sizing agent's evidence index. A flow flag is not independent
  evidence of direction (it can be a hedge), and correlated names (SMH, MU, SOXX) should count once, not three times.
* Suggested research-first step: record each flagged contract and its later outcome in a shadow table (as the alerter does for
  shadow exits), judged against a do-nothing baseline with its 30-trigger minimum, before any lane trades on it.
* Do not give a flow flag its own sizing slice until that shadow table has a sample the alerter's own gates call sufficient.
