"""Past-season checks for every crop in crops.py (not wheat, which has its own notes).

    python scripts/check_crops.py
    python scripts/check_crops.py --weather data/checks/openmeteo_daily_punjab_haryana_2021_2025.csv

For each crop, each pilot district in Punjab and Haryana and each season the weather file covers,
the advice rule runs from PAU's default sowing date with the recorded weather. It reports the
number of waterings, the water given, crop water use, days of water stress and the water-balance
closure, and compares the number of waterings with the range PAU states. Then it repeats the runs
with one guessed input changed at a time (soil, roots, season length, Kc adjustment) to show how
much each guess moves the advice.

What this is: a check that the arithmetic closes and that the advice is plausible against PAU.
What it is not: an accuracy test. There are no recorded field irrigations to compare with.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import crops as cr          # noqa: E402
from cropadvisor import irrigation as ir     # noqa: E402
from cropadvisor import irrigation_eval as ev  # noqa: E402

DEF_WEATHER = os.path.join(HERE, "..", "data", "checks",
                           "openmeteo_daily_punjab_haryana_2021_2025.csv")
DEF_SOIL = os.path.join(HERE, "..", "data", "soil_awc_pilot.csv")
DEF_OUT = os.path.join(HERE, "..", "data", "checks")

SCENARIOS = {
    "default": {},
    "soil_minus_20pc": {"awc_scale": 0.8},        # arbitrary
    "soil_plus_20pc": {"awc_scale": 1.2},         # arbitrary
    "roots_other_end": {"roots": "other"},        # the other end of FAO-56 Table 22's range
    "season_minus_10pc": {"season_scale": 0.9},   # arbitrary
    "season_plus_10pc": {"season_scale": 1.1},    # arbitrary
    "no_kc_adjustment": {"adjust_kc": False},     # FAO-56 Table 12 values as printed
}
# The other end of FAO-56 Table 22's rooting range, for the stress test (depths below 1 m are
# assumed to hold water like the top metre)
ZR_OTHER = {"mustard": 1.5, "chickpea": 0.6, "barley": 1.5, "potato": 0.6, "spring_maize": 1.7,
            "summer_moong": 0.6, "cotton": 1.7, "kharif_maize": 1.7, "bajra": 2.0,
            "kharif_moong": 0.6, "groundnut": 0.5}


def seasons_in(spec, daily, sowing_md=None):
    """Sowing dates (default sowing) whose whole season lies inside the weather file."""
    first, last = daily["date"].min(), daily["date"].max()
    m, d = sowing_md or spec.default_sowing
    out = []
    for y in range(first.year - 1, last.year + 1):
        sow = pd.Timestamp(y, m, d)
        if sow >= first and sow + pd.Timedelta(days=round(spec.season_days * 1.1)) <= last:
            out.append(sow)
    return out


def run_one(spec, daily, name, awc, sowing, awc_scale=1.0, roots=None, season_scale=1.0,
            adjust_kc=True):
    over = {"adjust_kc": adjust_kc}
    if roots == "other":
        over["zr_max"] = ZR_OTHER[spec.key]
        over["zr_ini"] = min(0.2, ZR_OTHER[spec.key])
    if season_scale != 1.0:
        over["season_days"] = round(spec.season_days * season_scale)
    params = spec.params(awc * awc_scale, **over)
    d = daily[daily["name"] == name].set_index("date")
    dates = pd.date_range(sowing, periods=params.season_days)
    d = d.reindex(dates)
    inputs = pd.DataFrame({"date": dates, "rain_mm": d["rain_mm"].to_numpy(float),
                           "et0_mm": d["et0_mm"].to_numpy(float),
                           "rh_min": d["rh_min"].to_numpy(float),
                           "wind_2m_ms": d["wind_2m_ms"].to_numpy(float)})
    if inputs[["rain_mm", "et0_mm"]].isna().any().any():
        raise ValueError(f"{name}: weather gap in the season from {sowing.date()}")
    run = ir.simulate(inputs, sowing, params, cr.CropRule(spec))
    _, kc_used = ir.climate_adjusted_kc(params, inputs)
    s = ir.summarise(run)
    s["kc_mid_used"] = (kc_used or {}).get("mid", {}).get("kc_mid", params.kc_mid)
    return run, s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weather", default=DEF_WEATHER)
    ap.add_argument("--soil", default=DEF_SOIL)
    ap.add_argument("--out", default=DEF_OUT)
    a = ap.parse_args()
    daily = pd.read_csv(a.weather, parse_dates=["date"])
    soil = pd.read_csv(a.soil).set_index("name")

    rows = []
    for key, spec in cr.CROPS.items():
        for name in soil.index:
            awc = float(soil.loc[name, "awc_mm_per_m"])
            for sowing in seasons_in(spec, daily):
                base = None
                for scen, kw in SCENARIOS.items():
                    try:
                        _, s = run_one(spec, daily, name, awc, sowing, **kw)
                    except ValueError as e:
                        rows.append({"crop": key, "name": name, "sowing": sowing.date(),
                                     "scenario": scen, "error": str(e)})
                        continue
                    dates = s["irrigation_dates"].split(";") if s["irrigation_dates"] else []
                    if scen == "default":
                        base = dates
                    cmp = ev.compare_events(base or [], dates, 3) if base is not None else {}
                    rows.append({"crop": key, "name": name, "state": soil.loc[name, "state"],
                                 "sowing": sowing.date(), "scenario": scen, **s,
                                 "vs_default_count_diff": cmp.get("count_diff"),
                                 "vs_default_share_events_differ": cmp.get("share_events_differ")})
    res = pd.DataFrame(rows)
    os.makedirs(a.out, exist_ok=True)
    res.to_csv(os.path.join(a.out, "crop_checks_all_runs.csv"), index=False)

    d = res[res["scenario"] == "default"]
    summary = []
    for key, spec in cr.CROPS.items():
        g = d[d["crop"] == key]
        lo, hi = spec.expected_irrigations or (None, None)
        n = g["n_irrigations"]
        inside = ((n >= lo) & (n <= hi)).mean() if lo is not None else None
        summary.append({
            "crop": key, "district_seasons": len(g),
            "seasons": f"{g['sowing'].min()} to {g['sowing'].max()}",
            "rain_mm": round(g["rain_mm"].mean()), "crop_water_use_mm": round(g["eta_mm"].mean()),
            "irrigations_mean": round(n.mean(), 1), "irrigations_range": f"{n.min()}-{n.max()}",
            "pau_range": f"{lo}-{hi}" if lo is not None else "not stated",
            "share_inside_pau_range": None if inside is None else round(inside, 2),
            "irrigation_mm": round(g["irrigation_mm"].mean()),
            "stress_days": round(g["stress_days"].mean(), 1),
            "kc_mid_adjusted": round(g["kc_mid_used"].mean(), 3), "kc_mid_table": spec.kc_mid,
            "max_closure_error_mm": float(g["closure_error_mm"].abs().max()),
        })
    summary = pd.DataFrame(summary)
    summary.to_csv(os.path.join(a.out, "crop_checks_summary.csv"), index=False)

    ok = res[res.get("error").isna()] if "error" in res else res
    sens = ok.groupby(["crop", "scenario"], sort=False).agg(
        irrigations_mean=("n_irrigations", "mean"),
        share_count_changed=("vs_default_count_diff", lambda s: (s.fillna(0) != 0).mean()),
        share_dates_differ=("vs_default_share_events_differ", "mean"),
        stress_days=("stress_days", "mean")).round(2).reset_index()
    sens.to_csv(os.path.join(a.out, "crop_checks_sensitivity.csv"), index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(summary.to_string(index=False))
    print()
    print(sens.pivot(index="crop", columns="scenario", values="irrigations_mean")
          .reindex(columns=list(SCENARIOS)).to_string())


if __name__ == "__main__":
    main()
