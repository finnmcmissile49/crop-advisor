"""Offline tests for the FAO-56 wheat water balance and the two irrigation rules.

All weather here is made up for testing. None of it is a measurement.
"""
import numpy as np
import pandas as pd
import pytest

from cropadvisor import irrigation as ir
from cropadvisor.irrigation_eval import compare_events


class NoIrrigation:
    name = "none"

    def start(self, sowing, params):
        pass

    def decide(self, *a):
        return 0.0

    def observe_rain(self, *a):
        pass


def flat_params(awc, zr, kc, p, season_days=152):
    """Constant root depth and Kc, no p adjustment: makes hand calculation possible."""
    return ir.default_params(awc, zr_ini=zr, zr_max=zr, kc_ini=kc, kc_mid=kc, kc_end=kc,
                             p_table=p, adjust_p=False, season_days=season_days)


def weather(n, et0=5.0, rain=None, start="2021-11-10"):
    return pd.DataFrame({"date": pd.date_range(start, periods=n),
                         "rain_mm": np.zeros(n) if rain is None else rain,
                         "et0_mm": np.full(n, et0)})


# ------------------------------------------------------------------------ crop parameters

def test_stage_lengths_fao_row_and_stretch():
    assert ir.default_params(120, season_days=120).stage_lengths() == (15, 25, 50, 30)
    stretched = ir.default_params(120).stage_lengths()
    assert sum(stretched) == 152 and stretched == (19, 32, 63, 38)


def test_kc_curve_shape():
    p = ir.default_params(120, season_days=120)
    assert p.kc(0) == 0.3 and p.kc(14) == 0.3
    assert p.kc(15 + 12.5) == pytest.approx((0.3 + 1.15) / 2)
    assert p.kc(40) == 1.15 and p.kc(89) == 1.15
    assert p.kc(119) == pytest.approx(1.15 + 29 / 30 * (0.25 - 1.15))


def test_root_depth_grows_to_max_at_mid_season():
    p = ir.default_params(120, season_days=120)
    assert p.root_depth(0) == 0.2 and p.root_depth(40) == 1.0 and p.root_depth(100) == 1.0
    assert p.root_depth(20) == pytest.approx(0.6)


def test_irrigation_cutoff_dates_follow_pau():
    assert ir.last_irrigation_date("2021-11-10") == pd.Timestamp("2022-03-31")
    assert ir.last_irrigation_date("2021-12-10") == pd.Timestamp("2022-04-10")
    assert ir.last_irrigation_date("2022-01-05") == pd.Timestamp("2022-04-10")


# ------------------------------------------------------------------------ water balance

def test_hand_worked_drying_sequence():
    # TAW = 100 mm/m x 0.5 m = 50 mm, p = 0.5 so RAW = 25 mm, ETc = 5 mm/day, no rain.
    # Days 1-6: no stress, Dr = 5, 10, ..., 30. Day 7: Ks = (50-30)/(0.5x50) = 0.8, ETa = 4,
    # Dr = 34. Day 8: Ks = 16/25 = 0.64, ETa = 3.2, Dr = 37.2.
    run = ir.simulate(weather(8), "2021-11-10", flat_params(100, 0.5, 1.0, 0.5), NoIrrigation())
    assert run["dr_mm"].round(6).tolist() == [5, 10, 15, 20, 25, 30, 34, 37.2]
    assert run["ks"].round(6).tolist()[-2:] == [0.8, 0.64]


def test_matches_fao56_example_37():
    # FAO-56 Example 37: TAW 160 mm, p 0.40, Dr 55 mm at the start of day 1, ETo 5, Kc 1.2.
    # Published Ks: 1.00 on day 2, 0.97 on day 3, 0.62 on day 10 (start-of-day Dr 100.8 mm).
    run = ir.simulate(weather(10), "2021-11-10", flat_params(200, 0.8, 1.2, 0.4), NoIrrigation(),
                      dr0=55)
    start_dr = [55] + run["dr_mm"].tolist()[:-1]
    assert start_dr[1] == pytest.approx(61) and start_dr[2] == pytest.approx(67)
    assert round(run["ks"].iloc[1], 2) == 1.00
    assert round(run["ks"].iloc[2], 2) == 0.97
    assert start_dr[9] == pytest.approx(100.8, abs=0.1)
    assert round(run["ks"].iloc[9], 2) == 0.62


def test_p_adjusted_for_evaporative_demand():
    params = ir.default_params(100, kc_ini=1.0)   # ETc = 3 mm on day 1
    run = ir.simulate(weather(1, et0=3.0), "2021-11-10", params, NoIrrigation())
    assert run["p"].iloc[0] == pytest.approx(0.55 + 0.04 * (5 - 3))
    hot = ir.simulate(weather(1, et0=20.0), "2021-11-10", params, NoIrrigation())
    assert hot["p"].iloc[0] == 0.1   # clipped at the FAO-56 lower bound


def test_heavy_rain_drains_and_never_goes_above_field_capacity():
    rain = np.zeros(5)
    rain[2] = 80
    run = ir.simulate(weather(5, rain=rain), "2021-11-10", flat_params(100, 0.5, 1.0, 0.5),
                      NoIrrigation())
    assert run["dr_mm"].iloc[2] == 0 and run["dp_mm"].iloc[2] == pytest.approx(80 - 15)
    assert (run["dr_mm"] >= 0).all()


def test_water_is_conserved_over_a_full_season():
    rng = np.random.default_rng(1)
    rain = np.where(rng.random(152) < 0.08, rng.gamma(2, 12, 152), 0.0)
    et0 = 1.5 + 3.5 * np.linspace(0, 1, 152) ** 2
    w = pd.DataFrame({"date": pd.date_range("2021-11-10", periods=152), "rain_mm": rain,
                      "et0_mm": et0})
    for rule in (ir.FaoTriggerRule(), ir.FaoTriggerRule("fixed", 75), ir.PauCalendarRule()):
        run = ir.simulate(w, "2021-11-10", ir.default_params(125), rule)
        s = ir.summarise(run)
        assert abs(s["closure_error_mm"]) < 1e-9
        assert (run["dr_mm"] <= run["taw_mm"] + 1e-9).all() and (run["dr_mm"] >= 0).all()


def test_missing_weather_refuses_to_run():
    daily = pd.DataFrame({"date": pd.date_range("2021-11-10", periods=10), "name": "X",
                          "rain_imd": 0.0, "et0_om": 3.0})
    daily.loc[4, "rain_imd"] = np.nan
    with pytest.raises(ValueError, match="1 days without"):
        ir.season_inputs(daily, "X", "2021-11-10", 10)
    with pytest.raises(ValueError):
        ir.season_inputs(daily, "X", "2021-11-10", 20)  # season runs past the data


# ------------------------------------------------------------------------ rules

def test_fao_trigger_irrigates_at_raw_and_refills():
    run = ir.simulate(weather(30), "2021-11-10", flat_params(100, 0.5, 1.0, 0.5),
                      ir.FaoTriggerRule())
    first = run[run["irrigation_mm"] > 0].iloc[0]
    assert first["das"] == 5 and first["irrigation_mm"] == pytest.approx(25)


def test_fao_trigger_stops_after_pau_cutoff():
    run = ir.simulate(weather(152, et0=6.0), "2021-11-10", ir.default_params(120),
                      ir.FaoTriggerRule())
    assert run.loc[run["irrigation_mm"] > 0, "date"].max() <= pd.Timestamp("2022-03-31")


def _pau_dates(sowing, rain=None, n=152):
    run = ir.simulate(weather(n, et0=3.0, rain=rain, start=sowing), sowing,
                      ir.default_params(120), ir.PauCalendarRule())
    return [d.strftime("%Y-%m-%d") for d in run.loc[run["irrigation_mm"] > 0, "date"]]


def test_pau_schedule_without_rain():
    # 10 Nov sowing: 4 weeks, then 5.5, 5.5 and 4 weeks (39, 39, 28 days)
    assert _pau_dates("2021-11-10") == ["2021-12-08", "2022-01-16", "2022-02-24", "2022-03-24"]


def test_pau_rain_pushes_next_irrigation():
    rain = np.zeros(152)
    rain[21] = 20   # 2 cm on 1 Dec: +10 days
    assert _pau_dates("2021-11-10", rain)[0] == "2021-12-18"
    rain = np.zeros(152)
    rain[90] = 10   # 1 cm on 8 Feb (after January): +2 days for the third irrigation
    assert _pau_dates("2021-11-10", rain)[2] == "2022-02-26"


def test_pau_rows_for_later_sowing():
    # 25 Nov: second row, 5.5, 3.5 and 2 weeks (39, 25, 14 days); depth 7.5 cm each
    assert _pau_dates("2021-11-25") == ["2021-12-23", "2022-01-31", "2022-02-25", "2022-03-11"]
    # October sowing: first irrigation after 3 weeks
    assert _pau_dates("2021-10-28")[0] == "2021-11-18"
    # January sowing: third row, and irrigation allowed to 10 April
    assert _pau_dates("2022-01-05", n=110)[1] == "2022-03-02"


# ------------------------------------------------------------------------ comparison

def test_compare_events():
    a = ["2022-01-01", "2022-02-01", "2022-03-01"]
    assert compare_events(a, a)["share_events_differ"] == 0
    c = compare_events(a, ["2022-01-03", "2022-02-08"], tol_days=3)
    assert c["matched"] == 1 and c["count_diff"] == -1 and c["share_events_differ"] == pytest.approx(2 / 3, abs=1e-3)
    assert c["mean_abs_shift_days"] == 2
    assert compare_events([], [])["share_events_differ"] == 0
