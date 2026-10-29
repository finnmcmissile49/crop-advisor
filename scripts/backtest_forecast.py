"""Forecast backtest: how far can forecast-based irrigation advice be trusted?

    python scripts/backtest_forecast.py

Uses forecasts as they were really issued (Open-Meteo Previous Runs API: the rain forecast made
1 to 7 days before each day), January 2024 to October 2026, for the six Punjab and Haryana
districts, and compares them with what was later recorded (Open-Meteo history). Three parts:

1. Rain forecast skill by lead day and season.
2. Next-watering date: on each day of each season, the day the soil would reach the watering
   point predicted with the forecast available that morning, against the day it really reached it
   (hindsight). This is how much the advice moves because the forecast is imperfect.
3. The rain-wait rule (rainrule.py) replayed through real seasons: waterings saved, extra water
   stress, and how often the rain did not come.

Hindsight here is Open-Meteo's recorded weather, not a field measurement. ET0 is taken as known
(only rain forecasts are archived); ET0 forecasts are usually much better than rain forecasts, so
this slightly flatters the forecast. Leads 1-6 are used; lead 7 is incomplete in the archive
(about half the rain of the other leads).
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import crops as cr          # noqa: E402
from cropadvisor import irrigation as ir     # noqa: E402
from cropadvisor import rainrule as rr       # noqa: E402

D = os.path.join(HERE, "..", "data")
WEATHER = os.path.join(D, "checks", "openmeteo_daily_punjab_haryana.csv")
FORECASTS = os.path.join(D, "checks", "openmeteo_previous_runs_rain_2024_2026.csv")
SOIL = os.path.join(D, "soil_awc.csv")
OUT = os.path.join(D, "checks")
LEADS = range(1, 7)
HORIZON = 6


# ------------------------------------------------------------------------------- loading

def load():
    wx = pd.read_csv(WEATHER, parse_dates=["date"])
    fc = pd.read_csv(FORECASTS, parse_dates=["date"])
    soil = pd.read_csv(SOIL).set_index("name")
    soil = soil[soil.index.isin(fc["name"].unique())]   # districts with archived forecasts
    return wx, fc, soil


def forecast_table(fc, name):
    """issued[t][k] = rain forecast for day t+k made on day t (lead k)."""
    g = fc[fc["name"] == name].set_index("date").sort_index()
    out = {}
    for k in LEADS:
        s = g[f"fc_day{k}"].copy()
        s.index = s.index - pd.Timedelta(days=k)      # index by issue day
        out[k] = s
    return pd.DataFrame(out)


# ------------------------------------------------------------------------ part 1: skill

def rain_skill(wx, fc):
    m = fc.merge(wx[["name", "date", "rain_mm"]], on=["name", "date"])
    rows = []
    for k in range(1, 8):
        f, o = m[f"fc_day{k}"], m["rain_mm"]
        ok = f.notna()
        f, o = f[ok], o[ok]
        hit = ((f >= 2.5) & (o >= 2.5)).sum()
        fa = ((f >= 2.5) & (o < 2.5)).sum()
        miss = ((f < 2.5) & (o >= 2.5)).sum()
        rows.append({"lead_days": k, "days": len(f), "rain_days_detected": round(hit / (hit + miss), 2),
                     "false_alarms": round(fa / (hit + fa), 2), "forecast_over_recorded":
                     round(f.sum() / o.sum(), 2), "correlation": round(np.corrcoef(f, o)[0, 1], 2)})
    by_lead = pd.DataFrame(rows)

    parts = []
    for name, g in m.groupby("name"):
        g = g.set_index("date").sort_index()
        f3 = g["fc_day1"].shift(-1) + g["fc_day2"].shift(-2) + g["fc_day3"].shift(-3)
        o3 = g["rain_mm"].shift(-1) + g["rain_mm"].shift(-2) + g["rain_mm"].shift(-3)
        parts.append(pd.DataFrame({"f3": f3, "o3": o3, "month": g.index.month}))
    d = pd.concat(parts).dropna()
    seasons = {"all": range(1, 13), "rabi Nov-Mar": (11, 12, 1, 2, 3), "Apr-May": (4, 5),
               "kharif Jun-Oct": (6, 7, 8, 9, 10)}
    rows = []
    for lab, months in seasons.items():
        s = d[d["month"].isin(months)]
        for n in (10, 20, 30):
            t = s[s["f3"] >= n]
            rows.append({"season": lab, "forecast_3day_at_least_mm": n, "cases": len(t),
                         "share_10mm_fell": round(float((t["o3"] >= 10).mean()), 2) if len(t) else None,
                         "median_fell_mm": round(float(t["o3"].median()), 1) if len(t) else None})
    return by_lead, pd.DataFrame(rows)


# ------------------------------------------------------------------ seasons and replays

def crop_setups():
    """(key, params_fn(awc), base_rule_fn(), default (month, day), depth note)."""
    out = []
    for key, spec in cr.CROPS.items():
        out.append((key, lambda awc, s=spec: s.params(awc), lambda s=spec: cr.CropRule(s),
                    spec.default_sowing))
    for state in ("Punjab", "Haryana"):
        out.append((f"wheat_{state.lower()}",
                    lambda awc, st=state: ir.zone_params("NWPZ", awc, state=st),
                    lambda st=state: ir.FirstWateringThenTrigger(state=st), (11, 10)))
    return out


def seasons(wx_g, fcast, season_days, md):
    first = max(wx_g.index.min(), fcast.index.min())
    last = min(wx_g.index.max(), fcast.index.max())
    out = []
    for y in range(first.year - 1, last.year + 1):
        sow = pd.Timestamp(y, *md)
        if sow >= first and sow + pd.Timedelta(days=season_days + HORIZON) <= last:
            out.append(sow)
    return out


def inputs_for(wx_g, sowing, n):
    dates = pd.date_range(sowing, periods=n)
    g = wx_g.reindex(dates)
    return pd.DataFrame({"date": dates, "rain_mm": g["rain_mm"].to_numpy(float),
                         "et0_mm": g["et0_mm"].to_numpy(float),
                         "rh_min": g["rh_min"].to_numpy(float),
                         "wind_2m_ms": g["wind_2m_ms"].to_numpy(float)})


def project(params, das0, dr0, rain, et0):
    """Start-of-day depletion and RAW for days das0, das0+1, ... with no irrigation."""
    dr, out = dr0, []
    for i, (r, e) in enumerate(zip(rain, et0)):
        das = das0 + i
        taw = params.awc_mm_per_m * params.root_depth(das)
        etc = params.kc(das) * e
        p = float(np.clip(params.p_table + 0.04 * (5 - etc), 0.1, 0.8))
        raw = p * taw
        dr = min(dr, taw)
        out.append((dr, raw))
        ks = 1.0 if dr <= raw else max((taw - dr) / ((1 - p) * taw), 0.0)
        dr = min(max(dr - r + ks * etc, 0.0), taw)
    return out


def first_trigger(proj):
    for i, (dr, raw) in enumerate(proj):
        if dr >= raw:
            return i
    return None


def replay_all(wx, fc, soil):
    date_rows, rule_rows = [], []
    for key, pfn, rfn, md in crop_setups():
        for name in soil.index:
            state = soil.loc[name, "state"]
            if key.startswith("wheat_") and not key.endswith(state.lower()):
                continue
            awc = float(soil.loc[name, "awc_mm_per_m"])
            wx_g = wx[wx["name"] == name].set_index("date").sort_index()
            fcast = forecast_table(fc, name)
            params0 = pfn(awc)
            for sow in seasons(wx_g, fcast, params0.season_days, md):
                inp = inputs_for(wx_g, sow, params0.season_days)
                params, _ = ir.climate_adjusted_kc(params0, inp)
                base = ir.simulate(inp, sow, params, rfn())
                # ---- part 2: next-watering date, forecast vs hindsight
                dr_start = base["dr_mm"].shift(1).fillna(0.0).to_numpy()
                irr_days = set(base.loc[base["irrigation_mm"] > 0, "date"])
                for i, t in enumerate(base["date"]):
                    if t in irr_days or i + HORIZON >= len(base):
                        continue
                    sl = slice(i, i + HORIZON + 1)
                    et0 = inp["et0_mm"].to_numpy()[sl]
                    actual = inp["rain_mm"].to_numpy()[sl]
                    if t not in fcast.index or fcast.loc[t].isna().any():
                        continue
                    pred_rain = np.concatenate([[actual[0]], fcast.loc[t, list(LEADS)].to_numpy(float)])
                    h = first_trigger(project(params, i, dr_start[i], actual, et0))
                    if h is None:
                        continue
                    pz = first_trigger(project(params, i, dr_start[i], pred_rain, et0))
                    date_rows.append({"crop": key, "name": name, "lead_days": h,
                                      "predicted": pz, "error_days": None if pz is None else pz - h,
                                      "month": t.month})
                # ---- part 3: rain-wait rule
                etc = {d: params.kc(j) * e for j, (d, e) in enumerate(zip(inp["date"], inp["et0_mm"]))}

                def forecast(d, fcast=fcast, inp=inp):
                    if d not in fcast.index:
                        return None
                    row = fcast.loc[d]
                    today = float(inp.loc[inp["date"] == d, "rain_mm"].iloc[0])
                    return [today, row[1], row[2]]   # today (known by evening), lead 1, lead 2
                rule = rr.RainAwareRule(rfn(), forecast, etc)
                wait = ir.simulate(inp, sow, params, rule)
                failed = 0
                for (d, w, tot) in rule.holds:
                    fell = inp.loc[(inp["date"] >= d) & (inp["date"] <= d + pd.Timedelta(days=w)),
                                   "rain_mm"].sum()
                    failed += fell < rr.RAIN_ARRIVES_MM
                sb, sw = ir.summarise(base), ir.summarise(wait)
                rule_rows.append({
                    "crop": key, "name": name, "sowing": sow.date(),
                    "irrigations_base": sb["n_irrigations"], "irrigations_wait": sw["n_irrigations"],
                    "water_mm_base": sb["irrigation_mm"], "water_mm_wait": sw["irrigation_mm"],
                    "stress_days_base": sb["stress_days"], "stress_days_wait": sw["stress_days"],
                    "severe_days_base": int((base["ks"] < rr.KS_FLOOR).sum()),
                    "severe_days_wait": int((wait["ks"] < rr.KS_FLOOR).sum()),
                    "waits": len(rule.holds), "waits_rain_failed": int(failed),
                    "closure_wait": sw["closure_error_mm"]})
    return pd.DataFrame(date_rows), pd.DataFrame(rule_rows)


def date_skill(dates):
    rows = []
    for lead in range(0, HORIZON + 1):
        g = dates[dates["lead_days"] == lead]
        e = g["error_days"]
        rows.append({"days_ahead_watering_really_due": lead, "cases": len(g),
                     "within_1_day": round(float((e.abs() <= 1).mean()), 2),
                     "within_2_days": round(float((e.abs() <= 2).mean()), 2),
                     "predicted_later_than_6_days": round(float(e.isna().mean()), 2),
                     "mean_error_days": round(float(e.mean()), 2)})
    return pd.DataFrame(rows)


def main():
    wx, fc, soil = load()
    by_lead, three_day = rain_skill(wx, fc)
    dates, rule = replay_all(wx, fc, soil)
    skill = date_skill(dates)
    by_lead.to_csv(os.path.join(OUT, "forecast_rain_skill_by_lead.csv"), index=False)
    three_day.to_csv(os.path.join(OUT, "forecast_rain_3day.csv"), index=False)
    skill.to_csv(os.path.join(OUT, "forecast_watering_date_skill.csv"), index=False)
    rule.to_csv(os.path.join(OUT, "rain_wait_rule_replay.csv"), index=False)
    agg = rule.groupby("crop").agg(
        seasons=("sowing", "size"), irrigations_base=("irrigations_base", "mean"),
        irrigations_wait=("irrigations_wait", "mean"), water_mm_saved=(
            "water_mm_base", "mean"), stress_days_base=("stress_days_base", "mean"),
        stress_days_wait=("stress_days_wait", "mean"), severe_base=("severe_days_base", "mean"),
        severe_wait=("severe_days_wait", "mean"), waits=("waits", "sum"),
        waits_rain_failed=("waits_rain_failed", "sum"))
    agg["water_mm_saved"] = (rule.groupby("crop")["water_mm_base"].mean()
                             - rule.groupby("crop")["water_mm_wait"].mean())
    agg = agg.round(2)
    agg.to_csv(os.path.join(OUT, "rain_wait_rule_summary.csv"))
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(by_lead.to_string(index=False), "\n")
    print(three_day.to_string(index=False), "\n")
    print(skill.to_string(index=False), "\n")
    print(agg.to_string())
    print("\nAll seasons: waits", int(rule["waits"].sum()), "rain failed",
          int(rule["waits_rain_failed"].sum()), "| waterings", rule["irrigations_base"].sum(),
          "->", rule["irrigations_wait"].sum(), "| max closure error",
          float(rule["closure_wait"].abs().max()))


if __name__ == "__main__":
    main()
