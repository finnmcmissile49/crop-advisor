"""Offline tests for waiting for forecast rain (rainrule.py). All weather is made up."""
import pandas as pd

from cropadvisor import advisor as av
from cropadvisor import crops as cr
from cropadvisor import irrigation as ir
from cropadvisor import rainrule as rr

HISAR = av.Site("Hisar", "Haryana", "NWPZ", 140.0, 29.152, 75.721)


def wx(start, end, et0=3.0, rain=None, today=None):
    d = pd.DataFrame({"date": pd.date_range(start, end), "rain_mm": 0.0, "et0_mm": et0})
    for day, mm in (rain or {}).items():
        d.loc[d["date"] == pd.Timestamp(day), "rain_mm"] = mm
    d["forecast"] = d["date"] > pd.Timestamp(today) if today else False
    return d


def test_wait_when_heavy_rain_close_and_soil_safe():
    w = rr.wait_for_rain("2027-01-08", 60, 60, 140, [3, 3, 3], [0, 0, 30])
    assert w == (2, 30.0)


def test_no_wait_for_small_rain_or_in_april_may():
    assert rr.wait_for_rain("2027-01-08", 60, 60, 140, [3, 3, 3], [0, 5, 10]) is None
    assert rr.wait_for_rain("2027-04-20", 60, 60, 140, [3, 3, 3], [0, 0, 40]) is None


def test_no_wait_if_soil_would_get_too_dry():
    # limit = 60 + 0.25 * 80 = 80 mm; 70 + 2 days of 6 mm = 82 > 80
    assert rr.wait_for_rain("2027-01-08", 70, 60, 140, [6, 6, 6], [0, 0, 30]) is None
    assert rr.wait_for_rain("2027-01-08", 70, 60, 140, [4, 4, 4], [0, 0, 30]) == (2, 30.0)


def find_water_now(rain=None):
    """First day the dry Hisar wheat season says water_now (after a 1st watering on 8 Dec)."""
    for k in range(30, 120):
        t = pd.Timestamp("2025-11-10") + pd.Timedelta(days=k)
        w = wx("2025-11-10", t + pd.Timedelta(days=16), today=t)
        a = av.advise(HISAR, "2025-11-10", t, ["2025-12-08"], w, mode="test")
        if a["status"] == "water_now":
            return t
    raise AssertionError("never water_now")


def test_calculator_waits_for_forecast_rain():
    t = find_water_now()
    # the 26 Oct finding: 30 mm forecast two days later used to leave "water today" unchanged
    w = wx("2025-11-10", t + pd.Timedelta(days=16), rain={t + pd.Timedelta(days=2): 30},
           today=t)
    a = av.advise(HISAR, "2025-11-10", t, ["2025-12-08"], w, mode="test")
    assert a["status"] == "wait_for_rain"
    assert a["rain_day"] == t + pd.Timedelta(days=2)
    assert a["water_if_dry"] == t + pd.Timedelta(days=3)
    en, hi = av.render(a)
    assert "WAIT FOR THE RAIN" in en and "बारिश का इंतज़ार" in hi


def test_crop_path_waits_too():
    w = wx("2026-10-05", "2027-01-20", et0=3.0)
    for t in pd.date_range("2026-10-08", "2026-11-30"):
        a = av.advise(HISAR, "2026-10-05", t, [], w.assign(forecast=w["date"] > t),
                      crop="potato")
        if a["status"] == "water_now":
            break
    else:
        raise AssertionError("no water_now")
    w2 = w.copy()
    w2.loc[w2["date"] == t + pd.Timedelta(days=1), "rain_mm"] = 25.0
    a = av.advise(HISAR, "2026-10-05", t, [], w2.assign(forecast=w2["date"] > t), crop="potato")
    assert a["status"] == "wait_for_rain"


def test_no_wait_when_soil_already_too_dry():
    # mustard just after the stem-rot period: the soil has been past the trigger for days
    w = wx("2026-10-25", "2027-03-20", et0=3.0)
    w.loc[w["date"] == pd.Timestamp("2027-01-17"), "rain_mm"] = 25.0
    a = av.advise(HISAR, "2026-10-25", "2027-01-16", ["2026-11-18"],
                  w.assign(forecast=w["date"] > pd.Timestamp("2027-01-16")), crop="mustard")
    assert a["status"] == "water_now"


def test_replay_rule_holds_then_irrigates_if_rain_fails():
    spec = cr.get("barley")
    p = spec.params(140.0)
    sow = pd.Timestamp("2025-11-01")
    inp = wx(sow, sow + pd.Timedelta(days=p.season_days - 1), et0=3.0)[["date", "rain_mm",
                                                                         "et0_mm"]]
    base = ir.simulate(inp, sow, p, cr.CropRule(spec))
    second = base.loc[base["irrigation_mm"] > 0, "date"].iloc[1]   # first trigger watering
    etc = {d: p.kc(i) * 3.0 for i, d in enumerate(inp["date"])}
    # a forecast of 30 mm on the second day, which never falls
    fc = lambda d: [0.0, 0.0, 30.0] if d == second else [0.0, 0.0, 0.0]   # noqa: E731
    rule = rr.RainAwareRule(cr.CropRule(spec), fc, etc)
    run = ir.simulate(inp, sow, p, rule)
    irr = run.loc[run["irrigation_mm"] > 0, "date"].tolist()
    assert second not in irr and second + pd.Timedelta(days=3) in irr   # held, then watered
    assert len(rule.holds) == 1
    assert abs(ir.summarise(run)["closure_error_mm"]) < 1e-9
    assert len(irr) <= spec.max_irrigations                           # state restored
