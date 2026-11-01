"""Validate and test the season-start ensemble (2 November 2026).

    python scripts/check_season_model.py

1. Validation, rolling origin, 2014-2016: each year predicted by a model trained on all target
   years before it. The ensemble is used for a crop only if it beats the last-5-year average here,
   one year ahead (the gate). Decided before the test.
2. Test, once: trained on 2009-2016, scored on 2017-2022, one year ahead and four years ahead (the
   distance the season outlook really predicts, as the data end in 2022), against the long-run
   mean, the trend and the last-5-year average. Errors in quintal per acre (rice as milled rice,
   cotton as lint), per crop, with the number of districts.
3. Which features the Random Forest leaned on.

Writes data/checks/season_model_validation.csv, season_model_test.csv, season_model_gate.csv,
season_model_features.csv.
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import seasonmodel as sm  # noqa: E402

OUT = os.path.join(HERE, "..", "data", "checks")


def main():
    val = sm.rolling_validation(sm.GATE_HORIZON).assign(horizon=sm.GATE_HORIZON)
    gate = sm.gate()
    tests, model = [], None
    for h in (1, 4):
        res, _, m = sm.evaluate(h, sm.TEST)
        tests.append(res.assign(horizon=h))
        model = model or m
    test = pd.concat(tests)
    g = pd.DataFrame([{"crop": c, "uses_ensemble": v} for c, v in gate.items()])
    feats = model.importance().rename("rf_importance").reset_index().rename(
        columns={"index": "feature"})
    val.to_csv(os.path.join(OUT, "season_model_validation.csv"), index=False)
    test.to_csv(os.path.join(OUT, "season_model_test.csv"), index=False)
    g.to_csv(os.path.join(OUT, "season_model_gate.csv"), index=False)
    feats.round(3).to_csv(os.path.join(OUT, "season_model_features.csv"), index=False)
    print("Validation (rolling, 2014-2016, one year ahead):")
    print(val.pivot(index="crop", columns="method", values="mae_q_acre").to_string())
    print("\nGate:", {k: v for k, v in gate.items()})
    for h in (1, 4):
        print(f"\nTest 2017-2022, {h} year(s) ahead:")
        t = test[test["horizon"] == h]
        p = t.pivot(index="crop", columns="method", values="mae_q_acre")
        p["n"] = t.groupby("crop")["n"].first()
        p["districts"] = t.groupby("crop")["districts"].first()
        print(p.to_string())
    print("\nRandom Forest feature importance:")
    print(feats.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
