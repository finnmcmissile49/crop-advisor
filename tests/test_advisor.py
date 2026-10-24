"""Offline tests for the irrigation calculator. All weather here is made up."""
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from cropadvisor import advisor as av

HERE = os.path.dirname(os.path.abspath(__file__))
HISAR = av.Site("Hisar", "Haryana", "NWPZ", 122.0, 29.152, 75.721)
BATHINDA = av.Site("Bathinda", "Punjab", "NWPZ", 123.0, 30.23, 74.952)


def wx(start, n, et0=4.0, rain=None, today=None):
    d = pd.DataFrame({"date": pd.date_range(start, periods=n), "rain_mm": 0.0, "et0_mm": et0})
    if rain:
        for day, mm in rain.items():
            d.loc[d["date"] == pd.Timestamp(day), "rain_mm"] = mm
    d["forecast"] = d["date"] > pd.Timestamp(today) if today else False
    return d


# ------------------------------------------------------------------------- input checks

@pytest.mark.parametrize("sowing,today,watered,msg", [
    ("2026-09-20", "2026-10-01", [], "between 15 October and 15 January"),
    ("2026-11-10", "2026-11-01", [], "before the sowing date"),
    ("2026-11-10", "2027-05-01", [], "past its expected"),
    ("2026-11-10", "2026-12-20", ["2026-12-25"], "after today"),
    ("2026-11-10", "2026-12-20", ["2026-12-08", "2026-12-08"], "twice"),
])
def test_refuses_bad_inputs(sowing, today, watered, msg):
    with pytest.raises(av.AdviceError, match=msg):
        av.check_inputs(HISAR, sowing, today, watered)


# ------------------------------------------------------------------------- first watering

def test_first_watering_windows():
    w = wx("2026-11-15", 60)
    a = av.advise(HISAR, "2026-11-15", "2026-11-25", [], w)            # day 10
    assert a["status"] == "first_upcoming"
    assert a["first_lo"] == pd.Timestamp("2026-12-05") and a["first_hi"] == pd.Timestamp("2026-12-10")
    assert av.advise(HISAR, "2026-11-15", "2026-12-07", [], w)["status"] == "first_now"
    assert av.advise(HISAR, "2026-11-15", "2026-12-14", [], w)["status"] == "first_overdue"
    # Punjab follows PAU: 4 weeks after a November sowing, plus or minus 3 days
    b = av.advise(BATHINDA, "2026-11-15", "2026-11-25", [], w)
    assert b["first_lo"] == pd.Timestamp("2026-12-10") and b["first_hi"] == pd.Timestamp("2026-12-16")


# ------------------------------------------------------------------------- next watering

def test_window_after_first_watering():
    # dry, steady demand: after the first watering the soil dries towards the trigger
    w = wx("2026-11-10", 75, et0=4.0)
    a = av.advise(HISAR, "2026-11-10", "2026-12-15", ["2026-12-01"], w)
    assert a["status"] in ("water_window", "water_now")
    if a["status"] == "water_window":
        assert a["earliest"] <= a["latest"]
        assert a["earliest"] >= pd.Timestamp("2026-12-15")
        if a["likely"] is not None:
            assert a["earliest"] <= a["likely"] <= a["latest"]
    en, hi = av.render(a)
    assert "WATER" in en and "सिंचाई" in hi


def test_wetter_soil_waters_later():
    w = wx("2026-11-10", 120, et0=4.0)
    a = av.advise(HISAR, "2026-11-10", "2026-12-20", ["2026-12-01", "2026-12-20"], w)
    assert a["status"] == "water_window"
    # 20 percent less water-holding capacity must be the earliest date, more must be the latest
    small = av.Site("x", "Haryana", "NWPZ", 122.0 * 0.8)
    big = av.Site("x", "Haryana", "NWPZ", 122.0 * 1.2)
    d_small = av.advise(small, "2026-11-10", "2026-12-20", ["2026-12-01", "2026-12-20"], w)["likely"]
    d_big = av.advise(big, "2026-11-10", "2026-12-20", ["2026-12-01", "2026-12-20"], w)["likely"]
    assert d_small <= a["likely"] <= d_big


def test_water_now_when_soil_is_dry():
    # first watering long ago and a hot dry spell since
    w = wx("2026-11-10", 120, et0=6.0)
    a = av.advise(HISAR, "2026-11-10", "2027-02-20", ["2026-12-01"], w)
    assert a["status"] == "water_now"


def test_rain_means_no_watering_soon():
    rain = {d.strftime("%Y-%m-%d"): 30.0 for d in pd.date_range("2026-12-10", "2027-01-10", freq="3D")}
    w = wx("2026-11-10", 75, et0=1.5, rain=rain)
    a = av.advise(HISAR, "2026-11-10", "2026-12-20", ["2026-12-01"], w)
    assert a["status"] == "not_needed_soon"
    assert a["recheck"] == pd.Timestamp("2026-12-27")


def test_after_cutoff_no_more_watering():
    w = wx("2026-11-10", 152, et0=6.0)
    a = av.advise(HISAR, "2026-11-10", "2027-04-02", ["2026-12-01"], w)
    assert a["status"] == "season_over"
    assert "NO MORE WATERING" in av.render(a)[0]


# ------------------------------------------------------------------------- weather fetch

def _fake(start, end):
    d = pd.DataFrame({"date": pd.date_range(start, end)})
    d["rain_mm"], d["et0_openmeteo_mm"] = 0.0, 3.0
    return d


def test_get_weather_modes():
    calls = []

    def hist(lat, lon, s, e):
        calls.append(("hist", s, e))
        return _fake(s, e)

    def fc(lat, lon, days, past_days):
        calls.append(("fc", days, past_days))
        now = pd.Timestamp("2027-01-20")
        return _fake(now - pd.Timedelta(days=past_days - 1), now + pd.Timedelta(days=days - 1))

    # live, sown 30 days ago: one forecast call with past days
    w, mode = av.get_weather(0, 0, "2026-12-22", "2027-01-20", now="2027-01-20",
                             fetch_history=hist, fetch_forecast=fc)
    assert mode == "live" and calls[-1] == ("fc", 16, 30)
    assert w["forecast"].sum() == 15 and w["date"].min() == pd.Timestamp("2026-12-22")
    # live, sown 71 days ago: archive plus recent forecast, no gaps
    w, mode = av.get_weather(0, 0, "2026-11-10", "2027-01-20", now="2027-01-20",
                             fetch_history=hist, fetch_forecast=fc)
    assert mode == "live" and len(w) == len(pd.date_range("2026-11-10", w["date"].max()))
    # test mode: recorded weather to today + 16 days
    w, mode = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                             fetch_history=hist, fetch_forecast=fc)
    assert mode == "test" and w["date"].max() == pd.Timestamp("2026-01-21")
    assert w["forecast"].sum() == 16
    # a date only a few days ago cannot be tested yet
    with pytest.raises(av.AdviceError, match="23 days ago"):
        av.get_weather(0, 0, "2026-11-10", "2027-01-10", now="2027-01-20",
                       fetch_history=hist, fetch_forecast=fc)


def test_get_weather_refuses_gaps():
    def hist(lat, lon, s, e):
        d = _fake(s, e)
        return d.drop(index=5)
    with pytest.raises(av.AdviceError, match="gaps"):
        av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20", fetch_history=hist)


# ------------------------------------------------------------------------- command line

def test_cli_list_and_unknown_district(tmp_path):
    script = os.path.join(HERE, "..", "scripts", "advise.py")
    out = subprocess.run([sys.executable, script, "--list"], capture_output=True, text=True,
                         encoding="utf-8")
    assert "Bihar: Rohtas, Muzaffarpur" in out.stdout
    soil = tmp_path / "soil.csv"
    soil.write_text("name,awc_mm_per_m\nHisar,122\n")
    out = subprocess.run([sys.executable, script, "--district", "Atlantis", "--sowing",
                          "2026-11-10", "--soil", str(soil)], capture_output=True, text=True,
                         encoding="utf-8")
    assert "I do not know" in out.stdout and "--list" in out.stdout


def test_render_all_statuses():
    base = {"site": HISAR, "sowing": pd.Timestamp("2026-11-10"), "today": pd.Timestamp("2027-02-01"),
            "das": 83, "watered": [pd.Timestamp("2026-12-01")], "season_days": 152,
            "cutoff": pd.Timestamp("2027-03-31"), "depth_mm": 70.0, "mode": "test",
            "rain_next7_mm": 3.0, "forecast_end": pd.Timestamp("2027-02-17"), "raw_used_pct": 64}
    d = pd.Timestamp
    cases = [
        {"status": "water_now"},
        {"status": "water_window", "earliest": d("2027-02-05"), "likely": d("2027-02-08"),
         "latest": d("2027-02-08"), "heavy_soil_later": True, "heavy_soil_none": False},
        {"status": "water_window", "earliest": d("2027-02-05"), "likely": d("2027-02-08"),
         "latest": d("2027-02-12"), "heavy_soil_later": False, "heavy_soil_none": False},
        {"status": "light_soil_only", "light_soil_day": d("2027-02-10"), "covers_season": False,
         "recheck": d("2027-02-08"), "horizon_days": 16},
        {"status": "light_soil_only", "light_soil_day": d("2027-03-20"), "covers_season": True,
         "recheck": d("2027-02-08"), "horizon_days": 16},
        {"status": "not_needed_soon", "recheck": d("2027-02-08"), "horizon_days": 16},
        {"status": "no_more_needed"}, {"status": "season_over"},
    ]
    for c in cases:
        en, hi = av.render({**base, **c})
        assert "TEST MODE" in en and len(hi) > 50
    en, _ = av.render({**base, **cases[1]})
    assert "most likely around 8 Feb 2027" in en and "light or sandy, as early as 5 Feb" in en
    en, _ = av.render({**base, **cases[4]})
    assert "PROBABLY NO MORE WATERING" in en and "20 Mar" in en
