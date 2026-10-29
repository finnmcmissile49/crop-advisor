"""Offline tests for the crops beyond wheat (crops.py and the advisor's crop path).
All weather here is made up."""
import numpy as np
import pandas as pd
import pytest

from cropadvisor import advisor as av
from cropadvisor import crops as cr
from cropadvisor import irrigation as ir

HISAR = av.Site("Hisar", "Haryana", "NWPZ", 122.0, 29.152, 75.721)
BATHINDA = av.Site("Bathinda", "Punjab", "NWPZ", 123.0, 30.23, 74.952)
PATNA = av.Site("Patna", "Bihar", "NEPZ", 120.0, 25.6, 85.1)


def wx(start, n, et0=5.0, rain=None, today=None, rh=None, u2=None):
    d = pd.DataFrame({"date": pd.date_range(start, periods=n), "rain_mm": 0.0, "et0_mm": et0})
    for day, mm in (rain or {}).items():
        d.loc[d["date"] == pd.Timestamp(day), "rain_mm"] = mm
    if rh is not None:
        d["rh_min"], d["wind_2m_ms"] = rh, u2
    d["forecast"] = d["date"] > pd.Timestamp(today) if today else False
    return d


def sim(spec, sowing, et0=5.0, rain=None, awc=122.0):
    p = spec.params(awc)
    w = wx(sowing, p.season_days, et0, rain)[["date", "rain_mm", "et0_mm"]]
    run = ir.simulate(w, sowing, p, cr.CropRule(spec))
    return run, ir.summarise(run)


def sow(spec, year):
    m, d = spec.default_sowing
    return pd.Timestamp(year, m, d)


# ------------------------------------------------------------------------- settings

@pytest.mark.parametrize("key", list(cr.CROPS))
def test_every_crop_is_complete_and_sourced(key):
    s = cr.CROPS[key]
    p = s.params(120.0)
    assert sum(p.stage_lengths()) == s.season_days
    assert 0.1 <= s.p <= 0.8 and 0 < s.zr_max <= 1.0
    assert s.kc_ini < s.kc_mid and s.kc_end <= s.kc_mid
    assert any("PAU" in x for x in s.sources) and any("FAO-56" in x for x in s.sources)
    assert s.hi and s.en
    lo, hi = s.sowing_range(sow(s, 2026))
    assert lo <= sow(s, 2026) <= hi
    if s.first:
        assert s.first[1] <= s.first[0] <= s.first[2]


@pytest.mark.parametrize("key", list(cr.CROPS))
def test_water_balance_closes_for_every_crop(key):
    s = cr.CROPS[key]
    run, summ = sim(s, sow(s, 2025), et0=6.0, rain={sow(s, 2025) + pd.Timedelta(days=40): 30})
    assert abs(summ["closure_error_mm"]) < 1e-9
    assert (run["dr_mm"] >= 0).all() and (run["dr_mm"] <= run["taw_mm"] + 1e-9).all()


def test_wheat_settings_unchanged():
    p = ir.zone_params("NWPZ", 122.0, state="Punjab")
    assert (p.kc_ini, p.kc_mid, p.kc_end, p.zr_max, p.p_table) == (0.3, 1.15, 0.25, 1.0, 0.55)
    assert p.adjust_kc is False and p.season_days == 152


# ------------------------------------------------------------------------- FAO-56 eq. 62

def test_kc_adjustment_matches_fao_eq62():
    p = cr.get("spring_maize").params(122.0)             # h = 2 m
    w = wx("2026-02-01", p.season_days, rh=25.0, u2=3.0)
    adj, used = ir.climate_adjusted_kc(p, w)
    expected = 1.20 + (0.04 * (3 - 2) - 0.004 * (25 - 45)) * (2 / 3) ** 0.3
    assert adj.kc_mid == pytest.approx(expected)
    assert adj.kc_end == pytest.approx(0.60 + (0.04 - 0.004 * -20) * (2 / 3) ** 0.3)
    # reference climate (RHmin 45 percent, u2 2 m/s): no change
    same, _ = ir.climate_adjusted_kc(p, wx("2026-02-01", p.season_days, rh=45.0, u2=2.0))
    assert same.kc_mid == pytest.approx(1.20)


def test_kc_adjustment_limits_and_low_kc_end():
    p = cr.get("barley").params(122.0)                    # Kc end 0.25 < 0.45: not adjusted
    adj, _ = ir.climate_adjusted_kc(p, wx("2026-11-01", p.season_days, rh=5.0, u2=9.0))
    assert adj.kc_end == 0.25
    # RHmin clipped to 20, u2 to 6
    assert adj.kc_mid == pytest.approx(1.15 + (0.04 * 4 - 0.004 * -25) * (1 / 3) ** 0.3)


def test_no_adjustment_without_humidity_data():
    p = cr.get("cotton").params(122.0)
    adj, used = ir.climate_adjusted_kc(p, wx("2026-04-25", p.season_days))
    assert used is None and adj.kc_mid == p.kc_mid


# ------------------------------------------------------------------------- rules

def test_first_watering_is_always_given():
    s = cr.get("cotton")
    run, summ = sim(s, pd.Timestamp(2025, 4, 25), et0=1.0)   # almost no demand
    assert int(summ["irrigation_das"].split(";")[0]) == s.first[0]


def test_max_irrigations_respected():
    for key in ("mustard", "barley", "bajra", "groundnut", "chickpea"):
        s = cr.get(key)
        _, summ = sim(s, sow(s, 2025), et0=8.0)               # very dry: rule wants more
        assert summ["n_irrigations"] <= s.max_irrigations


def test_mustard_no_watering_in_stem_rot_period():
    s = cr.get("mustard")
    run, _ = sim(s, pd.Timestamp(2025, 10, 25), et0=4.0)
    black = run[(run["date"] >= "2025-12-25") & (run["date"] <= "2026-01-15")]
    assert (black["irrigation_mm"] == 0).all()
    assert (run.loc[run["date"] > "2026-02-28", "irrigation_mm"] == 0).all()


def test_chickpea_watering_only_inside_pau_window():
    s = cr.get("chickpea")
    run, summ = sim(s, pd.Timestamp(2025, 11, 1), et0=4.0)
    irr = run[run["irrigation_mm"] > 0]
    assert len(irr) <= 1
    if len(irr):
        d = irr["date"].iloc[0]
        assert pd.Timestamp("2025-12-15") <= d <= pd.Timestamp("2026-01-31")
        assert (d - pd.Timestamp("2025-11-01")).days >= 28


def test_chickpea_window_end_rule():
    # little demand: the soil never reaches the trigger, but is past half of RAW at the end
    s = cr.get("chickpea")
    p = s.params(122.0)
    rule = cr.CropRule(s)
    rule.start(pd.Timestamp(2025, 11, 1), p)
    assert rule.decide(pd.Timestamp("2026-01-20"), 80, 40.0, 60.0, 120.0) == 0.0
    assert rule.decide(pd.Timestamp("2026-01-31"), 91, 40.0, 60.0, 120.0) == 40.0
    rule.start(pd.Timestamp(2025, 11, 1), p)
    assert rule.decide(pd.Timestamp("2026-01-31"), 91, 20.0, 60.0, 120.0) == 0.0


def test_summer_moong_stops_at_day_55_and_cotton_end_september():
    s = cr.get("summer_moong")
    run, _ = sim(s, pd.Timestamp(2025, 4, 1), et0=8.0)
    assert (run.loc[run["das"] > 55, "irrigation_mm"] == 0).all()
    c = cr.get("cotton")
    run, _ = sim(c, pd.Timestamp(2025, 4, 25), et0=7.0)
    assert (run.loc[run["date"] > "2025-09-30", "irrigation_mm"] == 0).all()


def test_rain_delays_waterings():
    s = cr.get("summer_moong")
    _, dry = sim(s, pd.Timestamp(2025, 4, 1), et0=7.0)
    rain = {pd.Timestamp(2025, 4, 1) + pd.Timedelta(days=d): 25 for d in range(26, 56, 6)}
    _, wet = sim(s, pd.Timestamp(2025, 4, 1), et0=7.0, rain=rain)
    assert wet["n_irrigations"] < dry["n_irrigations"]


def test_refill_waterings_replay():
    s = cr.get("potato")
    p = s.params(122.0)
    w = wx("2025-10-05", 40, et0=4.0)[["date", "rain_mm", "et0_mm"]]
    run = ir.simulate(w, "2025-10-05", p, ir.GivenIrrigations(["2025-10-20"]))
    day = run[run["date"] == "2025-10-20"].iloc[0]
    prev = run[run["date"] == "2025-10-19"].iloc[0]
    assert day["irrigation_mm"] == pytest.approx(prev["dr_mm"])


# ------------------------------------------------------------------------- advisor

def test_refuses_other_states_and_out_of_window_sowing():
    with pytest.raises(av.AdviceError, match="Punjab and Haryana"):
        av.check_crop_inputs(cr.get("mustard"), PATNA, "2026-10-25", "2026-11-01", [])
    with pytest.raises(av.AdviceError, match="sowing time"):
        av.check_crop_inputs(cr.get("cotton"), HISAR, "2026-10-20", "2026-11-01", [])
    *_, warns = av.check_crop_inputs(cr.get("mustard"), HISAR, "2026-11-20", "2026-11-25", [])
    assert warns and warns[0][0] == "late"
    with pytest.raises(av.AdviceError, match="sowing time"):
        av.check_crop_inputs(cr.get("mustard"), HISAR, "2026-12-10", "2026-12-12", [])


def test_mustard_first_watering_window():
    w = wx("2026-10-25", 60, et0=3.0)
    a = av.advise(HISAR, "2026-10-25", "2026-11-05", [], w, crop="mustard")
    assert a["status"] == "first_upcoming"
    assert a["first_lo"] == pd.Timestamp("2026-11-15") and a["first_hi"] == pd.Timestamp("2026-11-22")
    assert av.advise(HISAR, "2026-10-25", "2026-11-18", [], w, crop="mustard")["status"] == \
        "first_now"


def test_max_reached_and_season_over():
    w = wx("2026-10-25", 150, et0=3.0)
    a = av.advise(HISAR, "2026-10-25", "2027-01-20", ["2026-11-18", "2027-01-16"], w,
                  crop="mustard")
    assert a["status"] == "max_reached"
    a = av.advise(HISAR, "2026-10-25", "2027-03-05", ["2026-11-18"], w, crop="mustard")
    assert a["status"] == "season_over"


def test_mustard_date_moved_out_of_stem_rot_period():
    # dry and steady: after the first watering the soil would reach the trigger in early January
    w = wx("2026-10-25", 120, et0=3.0)
    hows = set()
    for today in pd.date_range("2026-12-10", "2027-01-15"):
        a = av.advise(HISAR, "2026-10-25", today, ["2026-11-18"], w, crop="mustard")
        hows.add(a.get("how"))
        for k in ("likely", "earliest", "latest", "light_soil_day"):
            d = a.get(k)
            if d is not None:
                assert not (pd.Timestamp("2026-12-25") <= d <= pd.Timestamp("2027-01-15"))
        if pd.Timestamp("2026-12-25") <= today <= pd.Timestamp("2027-01-15"):
            assert a["status"] != "water_now"        # never "water today" inside the period
    assert "after_blackout" in hows


def test_chickpea_window_upcoming():
    w = wx("2026-11-01", 30, et0=2.0, today="2026-11-14")   # forecast ends before the window
    a = av.advise(HISAR, "2026-11-01", "2026-11-14", [], w, crop="chickpea")
    assert a["status"] == "window_upcoming"
    assert a["window_start"] == pd.Timestamp("2026-12-15")


def test_cotton_water_now_in_heat_and_amount_in_cm():
    w = wx("2026-04-25", 110, et0=8.0)
    a = av.advise(HISAR, "2026-04-25", "2026-06-25", ["2026-05-30"], w, crop="cotton")
    assert a["status"] in ("water_now", "water_window")
    en, hi = av.render(a)
    assert "cm of water" in en and "सेमी" in hi


@pytest.mark.parametrize("key", list(cr.CROPS))
def test_every_crop_renders_through_its_season(key):
    s = cr.get(key)
    sowing = sow(s, 2026)
    w = wx(sowing, s.season_days + 20, et0=5.0, rain={sowing + pd.Timedelta(days=30): 20},
           rh=40.0, u2=2.0)
    seen = set()
    for das in range(0, s.season_days - 1, 4):
        today = sowing + pd.Timedelta(days=das)
        watered = [sowing + pd.Timedelta(days=s.first[0])] if s.first and \
            das > s.first[2] else []
        a = av.advise(HISAR, sowing, today, watered, w, crop=key, mode="test")
        en, hi = av.render(a)
        assert en.startswith("Crop Advisor:") and s.en.lower() in en
        assert any("ऀ" <= ch <= "ॿ" for ch in hi)     # Devanagari present
        seen.add(a["status"])
    assert seen


def test_wheat_path_unchanged():
    w = wx("2026-11-15", 60, et0=4.0)
    a = av.advise(HISAR, "2026-11-15", "2026-11-25", [], w)
    assert "crop" not in a and a["status"] == "first_upcoming"
    en, _ = av.render(a)
    assert en.startswith("Crop Advisor: wheat irrigation")
