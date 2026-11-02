"""Offline tests for the live inputs (IMD priority, live mandi price, the farmer's Soil Health Card,
Sentinel-2) and the technical features (station checks, Kalman fusion, ground truth, digital twin).
All weather, readings and satellite pixels here are made up: these test the code, not the science.
"""
import numpy as np
import pandas as pd
import pytest

from cropadvisor import advisor as av
from cropadvisor import fusion, groundtruth, prices, sentinel, service, station
from cropadvisor import irrigation as ir
from cropadvisor import soilcard as sc

from test_service import fake_forecast, fake_history

SOWING = pd.Timestamp("2025-11-10")
TODAY = pd.Timestamp("2026-01-10")


def weather(days=90, et0=3.0, rain=0.0):
    return pd.DataFrame({"date": pd.date_range(SOWING, periods=days), "rain_mm": rain,
                         "et0_mm": et0, "rh_min": 40.0, "wind_2m_ms": 1.5})


def params():
    return ir.zone_params("NWPZ", 150.0, state="Haryana")


FC = 0.30


# ----------------------------------------------------------------------------- station checks

def test_station_checks_drop_bad_and_stuck_values():
    ts = pd.date_range("2026-01-01", periods=12, freq="6h")
    rows = [{"timestamp": t, "sm_top": 0.25 + 0.001 * i, "sm_deep": 0.28, "rain_mm": 0}
            for i, t in enumerate(ts)]
    rows[3]["sm_top"] = 0.95          # out of range
    rows[5]["rain_mm"] = 900          # impossible rain
    d, rep = station.prepare(rows)
    assert rep["sm_top_out_of_range"] == 1
    assert rep["rain_out_of_range"] == 1
    assert rep["sm_deep_stuck"] == 12   # 0.28 for 66 hours: a stuck sensor
    assert d["sm_deep"].isna().all() and d["sm_top"].notna().all()


# ----------------------------------------------------------------------------- Kalman fusion

def _consistent_readings(out, days, theta_shift=0.0):
    """Readings that agree with the model's own soil water (plus an optional shift)."""
    p = params()
    rows = []
    for r in out.iloc[:days].itertuples():
        zr = r.taw_mm / p.awc_mm_per_m
        th = FC - r.dr_model_mm / (1000 * zr) + theta_shift
        rows.append({"date": r.date, "sm_top": th, "sm_deep": th, "rain_mm": np.nan})
    return pd.DataFrame(rows)


def test_fusion_without_readings_equals_the_calculator_model():
    out, corr = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, None, FC)
    assert np.allclose(out["dr_fused_mm"], out["dr_model_mm"])
    assert corr["mm"] == 0


def test_fusion_wetter_readings_pull_the_estimate_and_give_water():
    out0, _ = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, None, FC)
    wet = _consistent_readings(out0, len(out0), theta_shift=0.03)
    out, corr = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, wet, FC)
    assert (out["dr_fused_mm"].iloc[-1] < out["dr_model_mm"].iloc[-1])
    assert corr["mm"] > 0


def test_fusion_keeps_working_when_the_sensor_fails():
    out0, _ = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, None, FC)
    half = _consistent_readings(out0, 30)
    out, corr = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, half, FC)
    assert len(out) == len(out0)                       # no gap after the last reading
    after = out.iloc[30:]
    assert after["sensors"].isna().all()
    assert after["sd_mm"].is_monotonic_increasing     # uncertainty grows without readings
    assert corr is not None


def test_fusion_rejects_a_reading_far_outside_the_uncertainty():
    out0, _ = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, None, FC)
    r = _consistent_readings(out0, 40)
    r.loc[39, ["sm_top", "sm_deep"]] = 0.03            # bone dry, against 39 days of agreement
    out, _ = fusion.run(weather(), SOWING, TODAY, params(), [], 75.0, r, FC)
    assert bool(out.loc[39, "rejected"])
    assert out.loc[:38, "rejected"].sum() == 0


def test_apply_correction_adds_water_on_its_day():
    w = weather()
    w2 = av.apply_correction(w, {"date": SOWING + pd.Timedelta(days=5), "mm": 7.5})
    assert w2.loc[5, "rain_mm"] == pytest.approx(7.5)
    assert w2["rain_mm"].drop(index=5).eq(0).all()
    assert av.apply_correction(w, None) is w


def test_service_with_station_reports_date_without_station():
    days = pd.date_range(SOWING, "2026-01-19")
    readings = [{"timestamp": d + pd.Timedelta(hours=h), "sm_top": 0.30, "sm_deep": 0.32,
                 "rain_mm": 0} for d in days for h in (6, 18)]
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2026-01-20", "station": readings, "field_capacity": 0.33}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast(), with_extras=False)
    assert res["ok"], res.get("error")
    assert "station" in res["text_en"].lower()


# ----------------------------------------------------------------------------- ground truth

def test_oven_dry_sample_maths():
    s = groundtruth.load_samples([
        {"date": "2026-01-05", "depth_cm": 15, "tin_g": 20, "wet_with_tin_g": 145,
         "dry_with_tin_g": 120, "bulk_density_g_cm3": 1.5},
        {"date": "2026-01-05", "depth_cm": 45, "tin_g": 20, "wet_with_tin_g": 100,
         "dry_with_tin_g": 110},     # dry heavier than wet: a weighing mistake
    ], default_bulk_density=1.4)
    assert s.loc[0, "theta_g"] == pytest.approx(0.25)          # 25 g water / 100 g soil
    assert s.loc[0, "theta_v"] == pytest.approx(0.375)
    assert s.loc[1, "problem"] and np.isnan(s.loc[1, "theta_v"])
    readings = pd.DataFrame({"date": [pd.Timestamp("2026-01-05")], "sm_top": [0.355],
                             "sm_deep": [0.30]})
    c = groundtruth.compare(s, readings=readings).set_index("what")
    assert c.loc["sensor (sm_top)", "bias"] == pytest.approx(-0.02)


# ----------------------------------------------------------------------------- IMD priority

def test_imd_rain_used_ahead_of_nasa_power_on_recorded_days():
    def power(lat, lon, s, e):
        return pd.DataFrame({"date": pd.date_range(s, e), "rain_mm": 1.0})

    def imd(lat, lon, s, e):
        return pd.DataFrame({"date": pd.date_range(s, periods=10), "rain_mm": 5.0})

    w, mode = av.get_weather(29.2, 75.7, SOWING, TODAY, now="2027-01-20",
                             fetch_history=fake_history(), fetch_forecast=fake_forecast(),
                             fetch_power=power, fetch_imd=imd)
    assert mode == "test"
    assert (w.loc[:9, "rain_mm"] == 5.0).all()
    assert (w.loc[10:20, "rain_mm"] == 1.0).all()


def test_imd_failure_does_not_stop_the_advice():
    def imd(lat, lon, s, e):
        raise OSError("IMD server did not answer")

    w, _ = av.get_weather(29.2, 75.7, SOWING, TODAY, now="2027-01-20",
                          fetch_history=fake_history(), fetch_forecast=fake_forecast(),
                          fetch_imd=imd)
    assert "imd_error" in w.attrs and (w["rain_mm"] == 0).all()


# ----------------------------------------------------------------------------- live mandi price

def test_live_price_district_then_state():
    feed = pd.DataFrame({
        "commodity": ["Wheat", "Wheat", "Wheat", "Mustard"],
        "state": ["Haryana"] * 4, "district": ["Hisar", "Hisar", "Sirsa", "Hisar"],
        "market": ["Hisar", "Adampur", "Sirsa", "Hisar"],
        "arrival_date": pd.to_datetime(["2026-10-30", "2026-10-29", "2026-10-30", "2026-10-30"]),
        "modal_price": [2400.0, 2440.0, 2300.0, 5600.0]})
    p = prices.live_price("Wheat", "Haryana", "Hisar", fetch=lambda c: feed)
    assert p["price"] == 2420 and p["level"] == "district" and p["markets"] == 2
    p = prices.live_price("Wheat", "Haryana", "Rohtak", fetch=lambda c: feed)
    assert p["level"] == "state" and p["price"] == round((2400 + 2440 + 2300) / 3)


def test_live_price_without_key_or_feed_is_none(monkeypatch):
    monkeypatch.delenv("DATA_GOV_IN_KEY", raising=False)
    assert prices.live_price("Wheat", "Haryana") is None

    def broken(c):
        raise OSError("timeout")
    assert prices.live_price("Wheat", "Haryana", fetch=broken) is None


# ----------------------------------------------------------------------------- Soil Health Card

def test_dashboard_parser_counts_and_percent():
    rec = [{"cycle": "2025-26", "state": "HARYANA", "state_code": "6", "district": "HISAR",
            "district_code": "73", "results": {"n": {"Low": 60, "Medium": 30, "High": 10},
                                               "Zn": {"Deficient": 25, "Sufficient": 75}}}]
    df = sc.parse_dashboard(rec)
    r = df.iloc[0]
    assert r["n_low"] == 60 and r["n_samples"] == 100 and r["pct_n_low"] == 60.0
    assert r["zn_deficient"] == 25 and r["samples"] == 100


def test_farmer_card_checks_and_text():
    card = sc.farmer_card({"N": "Low", "zn": "deficient", "ph": "alkaline"})
    assert card == {"n": "low", "zn": "deficient", "ph": "alkaline"}
    with pytest.raises(ValueError):
        sc.farmer_card({"n": "very low"})
    with pytest.raises(ValueError):
        sc.farmer_card({"calcium": "low"})
    en, hi = sc.farmer_card_text(card)
    assert "nitrogen low" in en[0] and "नाइट्रोजन कम" in hi[0]
    assert service.parse_card("n=low zn=deficient") == {"n": "low", "zn": "deficient"}
    with pytest.raises(ValueError):
        service.parse_card("n:low")


def test_service_shows_the_farmers_card():
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2026-01-20", "soil_card": "n=low p=medium"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast())
    assert res["ok"] and "Your Soil Health Card: nitrogen low" in res["text_en"]
    bad = service.advise_request({**req, "soil_card": "n=lots"}, now="2027-01-20",
                                 fetch_history=fake_history(), fetch_forecast=fake_forecast())
    assert not bad["ok"]


# ----------------------------------------------------------------------------- Sentinel-2

def _stac(scenes):
    feats = [{"id": f"S2_{d}", "properties": {"datetime": f"{d}T05:30:00Z", "eo:cloud_cover": 10,
                                              "s2:processing_baseline": "05.10"},
              "assets": {"B04": {"href": f"red_{d}"}, "B08": {"href": f"nir_{d}"},
                         "SCL": {"href": f"scl_{d}"}}} for d in scenes]
    return lambda url, body: {"features": feats}


def _reader(pixels):
    """pixels: {date: (red_dn, nir_dn, scl)} -> fake 3 x 3 window reader."""
    def read(href, lat, lon):
        kind, d = href.split("_", 1)
        red, nir, scl = pixels[d]
        val = {"red": red, "nir": nir, "scl": scl}[kind]
        return np.full((3, 3), val)
    return read


def test_sentinel_ndvi_skips_cloud_and_applies_the_offset():
    px = {"2026-10-30": (1500, 4000, 9),      # cloud: skipped
          "2026-10-25": (1500, 4000, 4),      # (0.05, 0.30) -> 0.714
          "2026-10-20": (1600, 3000, 4)}      # (0.06, 0.20) -> 0.538
    res = sentinel.field_ndvi(29.2, 75.7, pd.Timestamp("2026-11-01"), post=_stac(list(px)),
                              reader=_reader(px), signer=lambda h: h)
    assert res["latest"]["date"] == "2026-10-25" and res["latest"]["ndvi"] == 0.71
    assert res["previous"]["ndvi"] == 0.54 and res["change"] == 0.17
    assert res["skipped"] == 1
    en, hi = sentinel.text(res)
    assert "up from 0.54" in en[0] and "बढ़ी" in hi[0]


def test_sentinel_all_cloudy_and_old_baseline():
    px = {"2021-12-01": (1500, 4000, 8)}
    res = sentinel.field_ndvi(29.2, 75.7, pd.Timestamp("2021-12-05"), post=_stac(list(px)),
                              reader=_reader(px), signer=lambda h: h)
    assert res["latest"] is None and "no clear view" in sentinel.text(res)[0][0]
    scene = {"date": "2021-12-01", "baseline": 3.01, "red": "red_x", "nir": "nir_x",
             "scl": "scl_x"}
    r = sentinel.scene_ndvi(scene, 0, 0, reader=_reader({"x": (500, 3000, 4)}),
                            signer=lambda h: h)
    assert r["ndvi"] == round((0.3 - 0.05) / 0.35, 2)   # no offset before baseline 04.00


def test_sentinel_error_never_blocks_advice():
    def boom(lat, lon, today):
        raise OSError("planetary computer unreachable")
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2026-01-20", "lat": 29.15, "lon": 75.72}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast(), fetch_sentinel=boom)
    assert res["ok"] and "could not be reached" in res["text_en"]


# ----------------------------------------------------------------------------- digital twin

def test_twin_settings_scale_the_season():
    twin = pytest.importorskip("cropadvisor.twin")
    pytest.importorskip("aquacrop")
    name, kw = twin.crop_settings("wheat", 140)
    assert name == "Wheat" and kw["MaturityCD"] <= 140 + 5
    assert twin.season_days("wheat") > 100


def test_twin_one_real_season_orders_strategies_sensibly():
    twin = pytest.importorskip("cropadvisor.twin")
    pytest.importorskip("aquacrop")
    w = twin.load_weather()
    w = w[w["name"] == "Hisar"].rename(columns={"rain_imd_mm": "rain_mm"})
    df = twin.compare_strategies("wheat", "Hisar", "2022-11-10", w, 150.0, "loam", "NWPZ",
                                 "Haryana").set_index("strategy")
    assert set(df.index) == {"advice", "calendar", "rainfed", "frequent"}
    assert df.loc["rainfed", "irrigation_mm"] == 0
    assert df.loc["rainfed", "yield_t_ha"] < df.loc["advice", "yield_t_ha"]
    assert df["share_of_best_yield"].max() == 1.0
