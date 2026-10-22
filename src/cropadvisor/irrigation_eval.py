"""Compare irrigation advice between two runs, and stress-test the baseline's guessed inputs.

compare_events is the measurement the research question needs later: run the same rule on two
input sets for the same field and dates (public data vs station data) and count how often the
irrigation decision differs. Until real station data exists it is only used to compare public
sources with each other and to measure sensitivity. Nothing here is evidence of a sensor benefit.
"""
import pandas as pd

from cropadvisor import irrigation as ir

DEFAULT_SOWING = (11, 10)    # 10 November: inside PAU's optimum first fortnight of November


def compare_events(dates_a, dates_b, tol_days=3):
    """Match irrigation dates in run A with run B (nearest first, each used once).

    Returns counts, the shift in days for each matched pair (B minus A), and how many events have
    no partner within tol_days. An event "differs" if it is unmatched or shifted by more than
    tol_days.
    """
    a = sorted(pd.Timestamp(x) for x in dates_a)
    b = sorted(pd.Timestamp(x) for x in dates_b)
    pairs = sorted(((abs((y - x).days), i, j) for i, x in enumerate(a) for j, y in enumerate(b)))
    used_a, used_b, shifts = set(), set(), []
    for dist, i, j in pairs:
        if i in used_a or j in used_b or dist > tol_days:
            continue
        used_a.add(i)
        used_b.add(j)
        shifts.append((b[j] - a[i]).days)
    n_events = max(len(a), len(b))
    differ = n_events - len(shifts)
    return {
        "n_a": len(a), "n_b": len(b), "matched": len(shifts),
        "unmatched_a": len(a) - len(shifts), "unmatched_b": len(b) - len(shifts),
        "count_diff": len(b) - len(a),
        "mean_abs_shift_days": round(sum(abs(s) for s in shifts) / len(shifts), 2) if shifts else None,
        "share_events_differ": round(differ / n_events, 3) if n_events else 0.0,
    }


def make_rule(name):
    if name == "fao_trigger":
        return ir.FaoTriggerRule(mode="refill")
    if name == "fao_trigger_fixed75":
        return ir.FaoTriggerRule(mode="fixed", depth_mm=75.0)
    if name == "pau_calendar":
        return ir.PauCalendarRule(depth_mm=75.0)
    raise ValueError(name)


def run_one(daily, name, awc, sowing, rule_name="fao_trigger", rain_src="imd", et0_src="om",
            awc_scale=1.0, **param_overrides):
    params = ir.default_params(awc * awc_scale, **param_overrides)
    inputs = ir.season_inputs(daily, name, sowing, params.season_days, rain_src, et0_src)
    run = ir.simulate(inputs, sowing, params, make_rule(rule_name))
    return run, ir.summarise(run)


# One-at-a-time stress tests around the default. The ranges are arbitrary stress tests, not
# uncertainty estimates, except where a source is named.
SCENARIOS = {
    "default": {},
    "awc_minus_20pc": {"awc_scale": 0.8},                       # arbitrary
    "awc_plus_20pc": {"awc_scale": 1.2},                        # arbitrary
    "roots_1.5m": {"zr_max": 1.5},          # FAO-56 Table 22 upper value; assumes 0-1 m AWC below 1 m
    "kc_ini_0.7": {"kc_ini": 0.7},          # FAO-56 Table 12 winter wheat, non-frozen soils
    "kc_mid_1.05": {"kc_mid": 1.05},                            # arbitrary, minus 0.1
    "kc_mid_1.25": {"kc_mid": 1.25},                            # arbitrary, plus 0.1
    "kc_end_0.4": {"kc_end": 0.4},          # FAO-56 Table 12 upper value (hand harvest)
    "season_120d": {"season_days": 120},    # FAO-56 Table 11 Central India row, unstretched
    "sow_1_nov": {"sow": (11, 1)},          # agreed window 1 to 25 November
    "sow_25_nov": {"sow": (11, 25)},
    "rain_openmeteo": {"rain_src": "om"},
    "rain_nasapower": {"rain_src": "pw"},
    "et0_nasapower": {"et0_src": "pw"},
}


def stress_test(daily, soil, years, rule_name="fao_trigger", scenarios=SCENARIOS, tol_days=3):
    """Every scenario for every district and season, compared with that district-season's default.

    soil: DataFrame indexed by district name with awc_mm_per_m.
    """
    rows = []
    for name in soil.index:
        awc = float(soil.loc[name, "awc_mm_per_m"])
        for yr in years:
            base_dates = None
            for scen, kw in scenarios.items():
                kw = dict(kw)
                m, d = kw.pop("sow", DEFAULT_SOWING)
                sowing = pd.Timestamp(yr, m, d)
                try:
                    _, s = run_one(daily, name, awc, sowing, rule_name, **kw)
                except ValueError as e:  # data gap: report it, do not guess
                    rows.append({"name": name, "season": f"{yr}-{yr + 1 - 2000}",
                                 "scenario": scen, "error": str(e)})
                    continue
                dates = s["irrigation_dates"].split(";") if s["irrigation_dates"] else []
                if scen == "default":
                    base_dates = dates
                cmp = compare_events(base_dates or [], dates, tol_days) \
                    if base_dates is not None else {}
                rows.append({"name": name, "season": f"{yr}-{yr + 1 - 2000}", "rule": rule_name,
                             "scenario": scen, "sowing": sowing.date().isoformat(), **s,
                             **{f"vs_default_{k}": v for k, v in cmp.items()}})
    return pd.DataFrame(rows)


def scenario_table(stress):
    """Across all district-seasons: how much each scenario moves the advice."""
    ok = stress[stress.get("error").isna()] if "error" in stress else stress
    g = ok.groupby("scenario", sort=False)
    return pd.DataFrame({
        "district_seasons": g.size(),
        "mean_irrigations": g["n_irrigations"].mean().round(2),
        "min_irrigations": g["n_irrigations"].min(),
        "max_irrigations": g["n_irrigations"].max(),
        "share_seasons_count_changed": g["vs_default_count_diff"].apply(lambda s: (s != 0).mean()).round(2),
        "mean_share_events_differ": g["vs_default_share_events_differ"].mean().round(2),
        "mean_abs_shift_days": g["vs_default_mean_abs_shift_days"].mean().round(1),
        "mean_stress_days": g["stress_days"].mean().round(1),
        "mean_irrigation_mm": g["irrigation_mm"].mean().round(0),
    })
