"""Offline tests for the per-zone settings, the ICAR-IIWBR calendar and the 10-state locations.

Weather here is made up for testing; none of it is a measurement.
"""
import os

import numpy as np
import pandas as pd
import pytest

from cropadvisor import irrigation as ir
from cropadvisor.irrigation_eval import run_one
from cropadvisor.weather import resolve_elevation

HERE = os.path.dirname(os.path.abspath(__file__))
LOCATIONS = os.path.join(HERE, "..", "data", "locations_wheat_10states.csv")
TEN_STATES = {"Punjab", "Haryana", "Uttar Pradesh", "Madhya Pradesh", "Rajasthan", "Bihar",
              "Gujarat", "Uttarakhand", "Jammu and Kashmir", "West Bengal"}


def weather(n, et0=3.0, start="2021-11-15"):
    return pd.DataFrame({"date": pd.date_range(start, periods=n), "rain_mm": np.zeros(n),
                         "et0_mm": np.full(n, et0)})


def test_zone_settings_and_cutoffs():
    assert ir.zone_params("NWPZ", 120, state="Punjab").last_irrigation_das is None   # PAU dates
    hry = ir.zone_params("NWPZ", 120, state="Haryana")
    assert hry.season_days == 152 and hry.last_irrigation_das is None                # PAU dates (zone)
    assert ir.last_irrigation_date("2021-11-10", hry) == pd.Timestamp("2022-03-31")
    nep = ir.zone_params("NEPZ", 120, state="Bihar")
    assert nep.season_days == 120 and nep.last_irrigation_das == 105                 # milk stage
    cz = ir.zone_params("CZ", 120, state="Madhya Pradesh")
    assert cz.season_days == 118 and cz.last_irrigation_das == 105
    # a stress-test season length moves the cut-off with it
    assert ir.zone_params("CZ", 120, state="Gujarat", season_days=100).last_irrigation_das == 85


def test_first_watering_always_given():
    # no water stress at all (ET0 tiny): the water balance alone would never irrigate early,
    # the advice rule still gives the crown-root irrigation
    for state, zone, day, depth in (("Punjab", "NWPZ", 28, 75), ("Bihar", "NEPZ", 21, 70)):
        params = ir.zone_params(zone, 140, state=state)
        run = ir.simulate(weather(40, et0=0.5), "2021-11-15", params,
                          ir.FirstWateringThenTrigger(state=state))
        irr = run[run["irrigation_mm"] > 0]
        assert irr["das"].tolist() == [day] and irr["irrigation_mm"].iloc[0] == depth
    assert ir.first_watering("Punjab", "2021-10-28")[0] == 21   # PAU: 3 weeks for October
    assert ir.first_watering("Gujarat", "2021-11-15")[1:3] == (20, 25)


def test_calendar_rule_per_state():
    assert ir.calendar_rule_name("Punjab") == "pau_calendar"
    assert ir.calendar_rule_name("Bihar") == "iiwbr_calendar"


def test_iiwbr_calendar_dates_and_depth():
    params = ir.zone_params("CZ", 125, state="Madhya Pradesh")
    run = ir.simulate(weather(params.season_days), "2021-11-15", params, ir.IiwbrCalendarRule())
    irr = run[run["irrigation_mm"] > 0]
    assert irr["das"].tolist() == [21, 45, 65, 85, 105]
    assert (irr["irrigation_mm"] == 70).all()
    assert abs(ir.summarise(run)["closure_error_mm"]) < 1e-9


def test_fao_trigger_cutoff_outside_punjab():
    params = ir.zone_params("NEPZ", 120, state="Bihar")
    run = ir.simulate(weather(params.season_days, et0=6.0), "2021-11-15", params,
                      ir.FaoTriggerRule())
    last = run.loc[run["irrigation_mm"] > 0, "das"].max()
    assert last <= 105


def test_punjab_defaults_unchanged():
    # run_one's defaults (NWPZ, Punjab) must reproduce the original pilot settings
    daily = weather(152, start="2021-11-10").assign(name="X")
    daily = daily.rename(columns={"rain_mm": "rain_imd", "et0_mm": "et0_om"})
    _, new = run_one(daily, "X", 125, pd.Timestamp("2021-11-10"), "fao_trigger")
    old = ir.summarise(ir.simulate(weather(152, start="2021-11-10"), "2021-11-10",
                                   ir.default_params(125), ir.FaoTriggerRule()))
    assert new == old


def test_elevation_fallback():
    part = pd.DataFrame({"x": [1]})
    part.attrs["elevation_m"] = 154.0
    assert resolve_elevation(201, [part]) == 201
    assert resolve_elevation(np.nan, [part]) == 154.0
    with pytest.raises(ValueError):
        resolve_elevation(None, [pd.DataFrame()])


def test_locations_file():
    loc = pd.read_csv(LOCATIONS)
    assert set(loc["state"]) == TEN_STATES
    assert loc["name"].is_unique
    assert set(loc["zone"]) <= set(ir.ZONES)
    assert loc["lat"].between(8, 37).all() and loc["lon"].between(68, 98).all()
    # every state has at least two districts
    assert (loc.groupby("state").size() >= 2).all()
