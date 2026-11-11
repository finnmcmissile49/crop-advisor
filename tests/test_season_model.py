"""Tests for the season-start model (seasonmodel.py). Made-up yields and rain for the mechanics;
one test on the committed tables checks the real model end to end."""
import numpy as np
import pandas as pd
import pytest

from cropadvisor import seasonmodel as sm
from cropadvisor import service


@pytest.fixture(scope="module")
def fake_tables(tmp_path_factory):
    """Six Punjab districts, wheat and mustard, 2000-2022. Mustard yield rises with Feb-Mar rain,
    wheat is steady, so the model has something real to find."""
    d = tmp_path_factory.mktemp("sm")
    rng = np.random.default_rng(0)
    rain_rows, yield_rows = [], []
    for i in range(6):
        dist = f"D{i}"
        rain_by_year = {}
        for yr in range(2009, 2025):
            for m in range(1, 13):
                normal = 20.0 + 5 * (m in (1, 2, 3))
                r = float(normal * rng.uniform(0.2, 2.0))
                rain_rows.append({"state": "Punjab", "district": dist, "rain_basis": "own",
                                  "year": yr, "month": m, "rain_mm": r, "normal_mm": normal,
                                  "coverage": 1.0})
                rain_by_year[(yr, m)] = r / normal
        for yr in range(2000, 2023):
            wet = np.mean([rain_by_year.get((yr + 1, m), 1.0) for m in (2, 3)])
            for crop, base in (("Wheat", 4.5 + 0.03 * (yr - 2000)), ("Mustard", 1.6)):
                y = base * (1 + (0.25 * (wet - 1) if crop == "Mustard" else 0)) \
                    * rng.normal(1, 0.03)
                yield_rows.append({"state": "Punjab", "district": dist, "crop": crop,
                                   "year": yr, "area_ha": 5000, "production_t": y * 5000,
                                   "source": "test", "yield_t_ha": y, "season": "Rabi"})
    yp, rp = d / "y.csv", d / "r.csv"
    pd.DataFrame(yield_rows).to_csv(yp, index=False)
    pd.DataFrame(rain_rows).to_csv(rp, index=False)
    return str(yp), str(rp)


def test_rain_features_and_history():
    s = pd.Series([1.0, 2, 3, 4, 5, 6], index=range(2010, 2016))
    h = sm.history_features(s, 2015)
    assert h["lag_mean5"] == 4.0 and h["last_ratio"] == pytest.approx(6 / 3.0)   # vs 2010-2014
    assert sm.history_features(s, 2011) is None
    assert sm._months(2020, (0, 10), (1, 3))[0] == (2020, 10)
    assert sm._months(2020, (0, 10), (1, 3))[-1] == (2021, 3)


def test_rows_use_only_past_yields(fake_tables):
    yp, rp = fake_tables
    rows = sm.build_rows(4, yp, rp)
    assert rows["year"].min() >= 2009 and set(rows["crop"]) == {"Wheat", "Mustard"}
    assert {"lag_mean5", "rain_dep", "rain_p3"} <= set(rows.columns)
    assert "year" not in sm.FEATURES
    r = rows[(rows["district"] == "D0") & (rows["crop"] == "Wheat") & (rows["year"] == 2015)]
    y = sm.load_yields(yp)
    past = y[(y["district"] == "D0") & (y["crop"] == "Wheat") & (y["year"] <= 2011)]
    assert r["lag_mean5"].iloc[0] == pytest.approx(past.sort_values("year")["yield_t_ha"]
                                                    .tail(5).mean())


def test_ensemble_learns_rain_effect_and_beats_baseline(fake_tables):
    yp, rp = fake_tables
    res, te, model = sm.evaluate(1, sm.TEST, yp, rp)
    p = res.pivot(index="crop", columns="method", values="mae_q_acre")
    assert p.loc["Mustard", "ensemble"] < p.loc["Mustard", "last5"]
    assert len(model.models) == 3 and model.importance().index[0] in sm.FEATURES
    gate = sm.gate(yp, rp)
    assert gate["Mustard"] is True


def test_scenarios_pair_crops_and_count_wins(fake_tables):
    yp, rp = fake_tables
    so = sm.season_outlook("D0", "Punjab", "rabi", "2026-11-02", yp, rp)
    c = so["crops"]
    assert set(c) == {"wheat", "mustard"} and so["season_year"] == 2026
    assert so["years_ahead_of_data"] == 4
    n = c["wheat"]["n_scenarios"]
    assert n == c["mustard"]["n_scenarios"] and n >= 100
    for v in c.values():
        assert v["income_low"] <= v["income_rs_acre"] <= v["income_high"]
    assert 0 <= so["wins"]["mustard|wheat"] <= 1
    en, hi = sm.text(so)
    assert en[0].startswith("Crop recommendation") and "ranked by expected gross income" in en[0]
    assert so["ranking"][0] == so["recommended"] and set(so["ranking"]) == {"wheat", "mustard"}
    best, other = so["ranking"]
    assert c[best]["score_rs_acre"] >= c[other]["score_rs_acre"]
    assert en[1].startswith("1. ") and en[2].startswith("2. ")
    assert any(line.startswith("Recommended: ") and "of 10" in line for line in en)
    assert all(v["risk"] in ("low", "medium", "high") for v in c.values())
    assert "not advice" not in "\n".join(en).lower() and len(en) == len(hi)
    assert any("संभावित मौसमों" in line for line in hi)
    assert "before costs" in en[-1]


def test_cotton_and_paddy_market_units():
    assert sm._to_market("Rice", 1.0, 0) == pytest.approx(10 / 2.47105 / 0.67)
    assert sm._to_market("Cotton", 1.0, 1) == pytest.approx(10 / 2.47105 / 0.34)
    assert sm._to_market("Wheat", 1.0, 0) == pytest.approx(10 / 2.47105)


def test_real_tables_end_to_end():
    """The committed tables: gate decided, Bathinda rabi compares wheat and mustard."""
    res = service.outlook_request({"district": "Bathinda", "season": "rabi"}, now="2026-11-02")
    assert res["ok"]
    so = res["season_model"]
    assert {"wheat", "mustard"} <= set(so["crops"]) and "mustard|wheat" in so["wins"]
    assert so["crops"]["wheat"]["method"] in ("ensemble", "last5")
    assert "Crop recommendation" in res["text_en"] and "Last harvest prices" in res["text_en"]
    assert so["recommended"] in so["crops"] and "Recommended: " in res["text_en"]
    bad = service.outlook_request({"district": "Bathinda", "season": "summer"},
                                  now="2026-11-02")
    assert not bad["ok"]


def test_risk_score_can_rank_a_steadier_crop_first():
    steady = {"method": "last5", "income": __import__("numpy").array([50000.0] * 10),
              "yield_market": __import__("numpy").array([20.0] * 10),
              "price": {"price": 2500, "latest_season": "2025"}, "rain_years": [2009, 2023],
              "own_years": 14}
    wild = {**steady, "income": __import__("numpy").array([10000.0] * 5 + [94000.0] * 5)}
    per_crop, _ = sm.summarise({"wheat": steady, "mustard": wild})
    assert per_crop["mustard"]["income_rs_acre"] > per_crop["wheat"]["income_rs_acre"]
    assert sm.ranking(per_crop) == ["wheat", "mustard"]
    assert per_crop["wheat"]["risk"] == "low" and per_crop["mustard"]["risk"] == "high"


def test_the_model_sees_which_crop_a_row_is():
    """Until 11 November 2026 the crop columns never reached the model (cut off by a comment)."""
    assert set(sm.CROP_FEATURES) <= set(sm.FEATURES)
    assert not set(sm.TEMP_FEATURES) & set(sm.FEATURES)       # tested on validation, not adopted
    assert set(sm.TEMP_FEATURES) <= set(sm.WITH_TEMP_FEATURES)


def test_temperature_departures_use_the_1991_2008_base():
    t = sm.temp_features("Hisar", "rabi", 2021)               # Feb-Mar 2022, the heat year
    assert t["tmax_p3"] == pytest.approx(30.5 - 29.6, abs=0.01)
    assert sm.temp_features("Hisar", "rabi", 2030) is None
    assert sm.temp_or_normal("Nowhere", "rabi", 2021) == sm.NORMAL_TEMP
    assert sm.gate()["Maize"] is True
