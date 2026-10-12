#!/usr/bin/env python3
"""Stage 1 M1: blind hold-out predictions with the frozen profile (profile_m1.txt).  Reads from each hold-out row
only its runtime-traffic records (colours 21/22) and its first-injection time (the replay anchor, Addendum C);
never its primary metric.  Writes results/fabric_pred_holdout.json."""
import json, os
import compare2
HERE = os.path.dirname(os.path.abspath(__file__))
prof = open(os.path.join(HERE, "profile_m1.txt")).read().split()
preds = {}
for r in compare2.rows():
    if r["role"] != "holdout":
        continue
    obs = compare2.model(r, prof)
    if r["family"] in compare2.CTL_FAMILIES:
        pm = compare2.primary_ctl(r, obs)
    else:
        pm = compare2.primary_legacy(compare2.legacy_obs(r, obs))
    preds[r["tag"]] = pm
json.dump({"profile": " ".join(prof), "predictions": preds}, open(os.path.join(HERE, "results/fabric_pred_holdout.json"), "w"), indent=1)
print(len(preds), "hold-out cases predicted")
