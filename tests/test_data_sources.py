"""Offline tests for the data sources added on 1 November 2026: NASA POWER recorded rain, IMD rain
normals, Soil Health Card notes, and the season outlook from district yields and mandi prices.
All weather and tables here are made up, except the checks on the committed reference tables."""
import os
import sys
import threading
import urllib.request
import json

import pandas as pd
import pytest

from cropadvisor import advisor as av
from cropadvisor import outlook as ol
from cropadvisor import rainnormals as rn
from cropadvisor import service
from cropadvisor import soilcard as sc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
HISAR = av.Site("Hisar", "Haryana", "NWPZ", 122.0, 29.152, 75.721)


def om_history(rain=None, et0=4.0):
    """Made-up Open-Meteo archive: dry, or rain on given days."""
    def f(lat, lon, s, e, raw_path=None):
        d = pd.DataFrame({"date": pd.date_range(s, e), "rain_mm": 0.0, "et0_openmeteo_mm": et0,
                          "rh_min": 40.0, "wind_2m_ms": 1.5})
        for day, mm in (rain or {}).items():
            d.loc[d["date"] == pd.Timestamp(day), "rain_mm"] = mm
        return d
    return f


def power(rain=None, lag_days=0):
    """Made-up NASA POWER: rain on given days; the last lag_days are missing (as -999 -> NaN)."""
    def f(lat, lon, s, e, raw_path=None):
        d = pd.DataFrame({"date": pd.date_range(s, e), "rain_mm": 0.0})
        for day, mm in (rain or {}).items():
            d.loc[d["date"] == pd.Timestamp(day), "rain_mm"] = mm
        if lag_days:
            d.loc[d.index[-lag_days:], "rain_mm"] = float("nan")
        return d
    return f


# ------------------------------------------------------------------- NASA POWER rain

def test_power_rain_replaces_recorded_days_only():
    w, mode = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                             fetch_history=om_history({"2025-12-20": 30.0, "2026-01-10": 25.0}),
                             fetch_power=power({"2025-12-20": 5.0, "2026-01-10": 99.0}))
    assert mode == "test"
    day = w.set_index("date")
    assert day.loc["2025-12-20", "rain_mm"] == 5.0 and day.loc["2025-12-20", "rain_om_mm"] == 30
    assert day.loc["2025-12-20", "rain_source"] == "pw"
    # the "forecast" days stay Open-Meteo even though POWER would have them
    assert day.loc["2026-01-10", "rain_mm"] == 25.0 and day.loc["2026-01-10", "rain_source"] == "om"
    assert (w.loc[w["forecast"], "rain_source"] == "om").all()


def test_power_lag_days_fall_back_to_open_meteo():
    w, _ = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                          fetch_history=om_history({"2026-01-04": 12.0}),
                          fetch_power=power(lag_days=3))
    day = w.set_index("date")
    assert day.loc["2026-01-04", "rain_source"] == "om" and day.loc["2026-01-04", "rain_mm"] == 12
    assert day.loc["2026-01-02", "rain_source"] == "pw"
    rec = av.rain_record(w, "2025-11-10", pd.Timestamp("2026-01-05"))
    assert rec["pw_until"] == pd.Timestamp("2026-01-02") and rec["rain_om_mm"] == 12.0


def test_power_failure_is_reported_not_fatal():
    def boom(*a, **k):
        raise RuntimeError("POWER down")
    w, _ = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                          fetch_history=om_history(), fetch_power=boom)
    assert "POWER down" in w.attrs["power_error"] and (w["rain_source"] == "om").all()


def test_open_meteo_date_shown_when_rain_records_disagree():
    # Open-Meteo says 40 mm fell after the first watering, NASA POWER says nothing did, so the
    # soil is dry by POWER and wet by Open-Meteo.
    hist = om_history({"2025-12-20": 40.0})
    w, mode = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                             fetch_history=hist, fetch_power=power())
    a = av.advise(HISAR, "2025-11-10", "2026-01-05", ["2025-12-08"], w, mode=mode)
    assert "rain_source_om_day" in a
    om_day = a["rain_source_om_day"]
    assert om_day is None or om_day > a.get("likely", a["today"])
    en, hi = av.render(a)
    assert "With Open-Meteo's rain record instead" in en and "Open-Meteo के बारिश रिकॉर्ड" in hi
    assert "NASA POWER up to" in en
    (lvl, _), why = av.confidence(a)
    assert any("rain records" in r[0] for r in why)


def test_no_rain_source_line_when_records_agree():
    w, mode = av.get_weather(0, 0, "2025-11-10", "2026-01-05", now="2027-01-20",
                             fetch_history=om_history(), fetch_power=power())
    a = av.advise(HISAR, "2025-11-10", "2026-01-05", ["2025-12-08"], w, mode=mode)
    assert "rain_source_om_day" not in a
    assert "instead" not in av.render(a)[0]


def test_service_uses_power_only_with_real_fetchers(monkeypatch):
    calls = []
    monkeypatch.setattr(service.nasapower, "fetch_history",
                        lambda *a, **k: calls.append(a) or power()(*a))
    req = {"district": "Hisar", "sowing": "2025-11-10", "today": "2026-01-05",
           "watered": ["2025-12-08"]}
    # made-up Open-Meteo fetchers (an offline test): POWER stays off
    res = service.advise_request(req, now="2027-01-20", fetch_history=om_history())
    assert res["ok"] and calls == []
    # an explicit POWER fetcher is used
    res = service.advise_request(req, now="2027-01-20", fetch_history=om_history(),
                                 fetch_power=power())
    assert res["advice"]["rain_record"]["pw_days"] > 0


def test_service_reports_power_failure():
    def boom(*a, **k):
        raise RuntimeError("timeout")
    res = service.advise_request({"district": "Hisar", "sowing": "2025-11-10",
                                  "today": "2026-01-05"}, now="2027-01-20",
                                 fetch_history=om_history(), fetch_power=boom)
    assert res["ok"] and "NASA POWER could not be reached" in res["text_en"]


# ------------------------------------------------------------------------- IMD normals

def test_committed_imd_table_covers_every_district():
    t = pd.read_csv(rn.TABLE)
    loc = pd.read_csv(os.path.join(ROOT, "data", "locations_wheat_10states.csv"))
    assert set(t["name"]) == set(loc["name"]) and (t.groupby("name").size() == 12).all()


def test_normal_between_is_pro_rata(tmp_path):
    p = tmp_path / "imd.csv"
    rows = [{"name": "X", "state": "S", "imd_district_code": 1, "month": m,
             "normal_mm": 31.0 if m in (1, 3) else 28.0, "mean_2009_2024_mm": 10.0, "years": 16}
            for m in range(1, 13)]
    pd.DataFrame(rows).to_csv(p, index=False)
    rn._table.cache_clear()
    try:
        assert rn.normal_between("X", "2026-01-01", "2026-01-31", str(p)) == 31.0
        assert rn.normal_between("X", "2026-01-17", "2026-02-14", str(p)) == 29.0   # 15 + 14
        c = rn.context("X", "2026-01-01", "2026-01-10", 7.0, "2026-01-26", str(p))
        assert c["normal_so_far_mm"] == 10.0 and c["after_forecast_month"] == 1
        en, hi = rn.text(c)
        assert "IMD's normal for this period: about 10 mm" in en[0] and "सामान्य" in hi[0]
        assert rn.monthly("Nowhere", str(p)) is None
    finally:
        rn._table.cache_clear()


# ------------------------------------------------------------------------- Soil Health Card

def test_soil_card_statuses(tmp_path):
    p = tmp_path / "shc.csv"
    rows = []
    for cyc, n_pct, k_pct in (("2023-24", 80, 90), ("2024-25", 90, 20)):
        rows += [{"name": "X", "state": "S", "cycle": cyc, "nutrient": "n", "samples": 900,
                  "pct_low": n_pct},
                 {"name": "X", "state": "S", "cycle": cyc, "nutrient": "k", "samples": 900,
                  "pct_low": k_pct},
                 {"name": "X", "state": "S", "cycle": cyc, "nutrient": "p", "samples": 40,
                  "pct_low": 50}]
    pd.DataFrame(rows).to_csv(p, index=False)
    sc._table.cache_clear()
    try:
        s = sc.summary("X", "S", str(p))
        assert s["n"] == {"status": "range", "lo": 80, "hi": 90, "cycles": ["2023-24", "2024-25"],
                          "samples": 1800}
        assert s["k"]["status"] == "varies" and s["p"]["status"] == "few_tests"
        en, hi = sc.text("X", s)
        assert "nitrogen 80-90%" in en[0] and "potassium changed a lot" in en[1]
        assert "Get your own field tested" in en[-1] and "मिट्टी जाँच" in hi[-1]
        assert sc.summary("Nowhere", None, str(p)) is None
    finally:
        sc._table.cache_clear()


def test_committed_soil_card_covers_calculator_districts():
    t = pd.read_csv(sc.TABLE)
    loc = pd.read_csv(os.path.join(ROOT, "data", "locations_wheat_10states.csv"))
    assert set(loc["name"]) <= set(t["name"])
    assert t["pct_low"].between(0, 100).all() and (t["samples"] > 0).all()


# ------------------------------------------------------------------------- outlook

@pytest.fixture
def tables(tmp_path):
    years = range(2009, 2023)
    y = pd.DataFrame([{"state": "Punjab", "district": "D", "crop": c, "season": "x", "year": yr,
                       "area_ha": 1, "production_t": 1, "yield_t_ha": v + 0.01 * (yr % 3),
                       "source": "ICRISAT DLD" if yr < 2020 else "DES", "note": None}
                      for c, v in (("Wheat", 5.0), ("Rice", 4.0), ("Cotton", 0.6))
                      for yr in years])
    # more districts so the error band has enough cases
    extra = [y.assign(district=f"E{i}", yield_t_ha=y["yield_t_ha"] * (1 + 0.02 * i))
             for i in range(5)]
    yp = tmp_path / "y.csv"
    pd.concat([y] + extra).to_csv(yp, index=False)
    pr = []
    for season, price in ((2023, 2100), (2024, 2200), (2025, 2400)):
        for m in (4, 5):
            pr.append({"level": "state", "state": "Punjab", "district": None,
                       "commodity": "Wheat", "month": f"{season}-{m:02d}", "p_min": 0,
                       "p_max": 0, "p_modal": price})
            pr.append({"level": "district", "state": "Punjab", "district": "D",
                       "commodity": "Wheat", "month": f"{season}-{m:02d}", "p_min": 0, "p_max": 0,
                       "p_modal": price + 10 if season != 2024 else 9000})   # 2024 is an outlier
        pr.append({"level": "state", "state": "Punjab", "district": None, "commodity": "Cotton",
                   "month": f"{season}-10", "p_min": 0, "p_max": 0, "p_modal": 7000})
        pr.append({"level": "state", "state": "Punjab", "district": None,
                   "commodity": "Paddy(Dhan)(Common)", "month": f"{season}-10", "p_min": 0,
                   "p_max": 0, "p_modal": 2300})
    pr.append({"level": "state", "state": "Punjab", "district": None, "commodity": "Barley (Jau)",
               "month": "2019-04", "p_min": 0, "p_max": 0, "p_modal": 1500})
    pp = tmp_path / "p.csv"
    pd.DataFrame(pr).to_csv(pp, index=False)
    ol._yields.cache_clear()
    ol._prices.cache_clear()
    ol.error_band.cache_clear()
    yield str(yp), str(pp)
    ol._yields.cache_clear()
    ol._prices.cache_clear()
    ol.error_band.cache_clear()


def test_predict_last_five_years():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7], index=range(2010, 2017), dtype=float)
    assert ol.predict(s, 2016) == 5.0 and ol.predict(s, 2012) == 2.0
    assert ol.predict(s, 2011) is None   # fewer than 3 years


def test_outlook_wheat_yield_price_and_value(tables):
    yp, pp = tables
    o = ol.crop_outlook("D", "Punjab", "wheat", "2026-11-02", yp, pp)
    y, pr = o["yield"], o["price"]
    assert y["years"] == (2018, 2022) and y["horizon_years"] == 4
    assert y["expected_q_acre"] == pytest.approx(5.01 * ol.T_HA_TO_Q_ACRE, abs=0.1)
    assert y["low_q_acre"] <= y["expected_q_acre"] <= y["high_q_acre"]
    # district prices used, the 2024 outlier dropped
    assert pr["level"] == "district" and pr["seasons"] == {2023: 2110, 2025: 2410}
    assert pr["note"] == "district_unusual_dropped" and pr["price"] == 2410
    assert o["gross_rs_acre"] == round(y["expected_q_acre"] * 2410, -2)
    en, hi = ol.text(o)
    assert "quintal per acre" in en[0] and "Rs 2,410 per quintal" in en[1]
    assert "before costs" in en[2] and "क्विंटल प्रति एकड़" in hi[0]


def test_outlook_only_uses_years_before_the_season(tables):
    yp, pp = tables
    o = ol.crop_outlook("D", "Punjab", "wheat", "2026-11-02", yp, pp, season=2019)
    assert o["yield"]["years"] == (2014, 2018)


def test_outlook_paddy_converted_and_cotton_has_no_value(tables):
    yp, pp = tables
    paddy = ol.crop_outlook("D", "Punjab", "paddy", "2026-11-02", yp, pp)
    assert paddy["yield"]["unit"] == "quintal paddy per acre"
    assert paddy["yield"]["expected_q_acre"] == pytest.approx(
        4.01 * ol.T_HA_TO_Q_ACRE / 0.67, abs=0.1)
    assert paddy["price"]["level"] == "state" and "gross_rs_acre" in paddy
    cotton = ol.crop_outlook("D", "Punjab", "cotton", "2026-11-02", yp, pp)
    assert cotton["yield"] and cotton["price"] and "gross_rs_acre" not in cotton
    assert "No value per acre for cotton" in " ".join(ol.text(cotton)[0])


def test_outlook_stale_price_and_other_states(tables):
    yp, pp = tables
    assert ol.crop_outlook("D", "Punjab", "barley", "2026-11-02", yp, pp)["price"] is None
    assert ol.crop_outlook("Ujjain", "Madhya Pradesh", "wheat", "2026-11-02", yp, pp) is None


def test_outlook_request_real_tables():
    res = service.outlook_request({"district": "Bathinda"}, now="2026-11-02")
    assert res["ok"] and res["outlook"][0]["key"] == "wheat"
    assert "Not a recommendation" in res["text_en"]
    bad = service.outlook_request({"district": "Ujjain"}, now="2026-11-02")
    assert not bad["ok"] and "Haryana and Punjab only" in bad["error"]
    assert not service.outlook_request({"district": "Nowhere"})["ok"]
    assert not service.outlook_request({"district": "Hisar", "crop": "rice"})["ok"]


def test_advice_carries_district_extras():
    res = service.advise_request({"district": "Bathinda", "sowing": "2025-11-10",
                                  "today": "2026-01-05", "watered": ["2025-12-08"]},
                                 now="2027-01-20", fetch_history=om_history(),
                                 fetch_power=power())
    x = res["extras"]
    assert x["rain"]["normal_so_far_mm"] > 0 and x["soil_card"]["n"]["status"] == "range"
    assert x["outlook"]["yield"]["years"][1] <= 2024 and x["outlook"]["price"]["latest_season"] <= 2025
    assert "About your district" in res["text_en"] and "आपके ज़िले के बारे में" in res["text_hi"]
    json.dumps(res, ensure_ascii=False)   # everything serialisable
    lean = service.advise_request({"district": "Bathinda", "sowing": "2025-11-10",
                                   "today": "2026-01-05"}, now="2027-01-20",
                                  fetch_history=om_history(), with_extras=False)
    assert "extras" not in lean and "About your district" not in lean["text_en"]


def test_extras_outside_haryana_punjab_have_no_outlook():
    res = service.advise_request({"district": "Ujjain", "sowing": "2025-11-10",
                                  "today": "2025-11-20"}, now="2027-01-20",
                                 fetch_history=om_history())
    assert res["ok"] and res["extras"]["outlook"] is None and res["extras"]["rain"]


# ------------------------------------------------------------------------- web server

def test_server_outlook_endpoint():
    import serve
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/outlook?district=Sirsa&crop=wheat"
        with urllib.request.urlopen(url) as r:
            res = json.loads(r.read())
        assert res["ok"] and len(res["outlook"]) == 1 and res["outlook"][0]["yield"]
    finally:
        srv.shutdown()
