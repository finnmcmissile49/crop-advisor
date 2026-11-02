"""How good is the outlook's district yield? (1 November 2026)

Three simple predictions of a district's yield, compared on years they did not see:
    mean    the district's long-run average
    trend   a straight-line trend through the district's years
    last5   the average of the district's last 5 years
Chosen on a validation period (trained on years up to 2014, scored on 2015-2018), then tested
once on 2019-2022 (trained up to 2018). Errors are in quintal per acre (wheat and rice as in the
data: rice is milled rice here; cotton is lint), per crop, with the number of districts.
Also scores last5 at 1 to 5 years ahead, which is how far the outlook reaches past the data.

    python scripts/check_outlook.py

Reads data/reference/district_yields.csv. Writes data/checks/yield_outlook_check.csv and
data/checks/yield_outlook_by_horizon.csv.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import outlook as ol  # noqa: E402

ROOT = os.path.join(HERE, "..")
Q = ol.T_HA_TO_Q_ACRE


def _preds(train, years):
    b = np.polyfit(train["year"], train["yield_t_ha"], 1)
    return {"mean": np.full(len(years), train["yield_t_ha"].mean()),
            "trend": np.polyval(b, years),
            "last5": np.full(len(years), train.sort_values("year")["yield_t_ha"].tail(5).mean())}


def score(y, train_end, test_years, period):
    rows = []
    for (crop, dist), g in y.groupby(["crop", "district"]):
        tr, te = g[g["year"] <= train_end], g[g["year"].isin(test_years)]
        if len(tr) < 5 or te.empty:
            continue
        for m, p in _preds(tr, te["year"].to_numpy()).items():
            for e in (p - te["yield_t_ha"].to_numpy()) * Q:
                rows.append({"period": period, "crop": crop, "district": dist, "method": m,
                             "err_q_acre": e})
    d = pd.DataFrame(rows)
    return d.groupby(["period", "crop", "method"]).agg(
        mae_q_acre=("err_q_acre", lambda s: s.abs().mean()),
        bias_q_acre=("err_q_acre", "mean"), n=("err_q_acre", "size"),
        districts=("district", "nunique")).round(2).reset_index()


def by_horizon(y):
    rows = []
    for crop in sorted(y["crop"].unique()):
        for h in range(1, 6):
            band = ol.error_band(crop, h)
            errs = []
            for _, g in y[y["crop"] == crop].groupby("district"):
                s = g.set_index("year")["yield_t_ha"]
                for yr, actual in s.items():
                    p = ol.predict(s, yr - h)
                    if p is not None and len(s[s.index <= yr - h]) >= ol.YIELD_YEARS:
                        errs.append((p - actual) * Q)
            rows.append({"crop": crop, "years_ahead": h, "n": len(errs),
                         "mae_q_acre": round(float(np.mean(np.abs(errs))), 2),
                         "band_p10_q_acre": round(band[0] * Q, 2) if band else None,
                         "band_p90_q_acre": round(band[1] * Q, 2) if band else None})
    return pd.DataFrame(rows)


def main():
    y = pd.read_csv(ol.YIELDS).dropna(subset=["yield_t_ha"])
    check = pd.concat([score(y, 2014, range(2015, 2019), "validation 2015-2018"),
                       score(y, 2018, range(2019, 2023), "test 2019-2022")])
    hz = by_horizon(y)
    out = os.path.join(ROOT, "data", "checks")
    check.to_csv(os.path.join(out, "yield_outlook_check.csv"), index=False)
    hz.to_csv(os.path.join(out, "yield_outlook_by_horizon.csv"), index=False)
    print(check.to_string(index=False))
    print()
    print(hz.to_string(index=False))


if __name__ == "__main__":
    main()
