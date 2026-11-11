"""Fertiliser schedule: PAU's quantities and timing, the soil-test rule, the ICAR wheat dose.

The numbers checked here are the ones printed in PAU's Package of Practices (Rabi 2025-26, Kharif
2026, Vegetables 2021). The tests check that the code gives them back, not that they suit a field.
"""
import pandas as pd
import pytest

from cropadvisor import fertiliser as f
from cropadvisor import service

from test_service import fake_forecast, fake_history


def kg(dose):
    return dict(dose["items"])


def test_wheat_pau_medium_soil_is_55_dap_then_45_urea_twice():
    s = f.schedule("wheat", "Punjab", "2026-11-10", "2026-12-05", next_watering="2026-12-08")
    d = s["doses"]
    assert kg(d[0]) == {"dap": 55} and d[0]["first"] == pd.Timestamp("2026-11-10")
    assert kg(d[1]) == {"urea": 45} and d[1]["first"] == pd.Timestamp("2026-12-08")
    assert kg(d[2]) == {"urea": 45} and d[2]["first"] is None
    assert d[1]["status"] == "due_soon" and s["next"] is d[1]
    en, hi = f.text(s)
    assert "45 kg urea" in en[2] and "55 days after sowing" in "\n".join(en)
    assert "यूरिया" in "\n".join(hi) and len(en) == len(hi)


def test_wheat_second_dose_falls_back_to_day_55_when_the_watering_is_late():
    s = f.schedule("wheat", "Haryana", "2026-11-10", "2026-12-20", watered=["2026-12-08"],
                   next_watering="2027-01-20")
    assert s["doses"][1]["with_watering_given"] and s["doses"][1]["status"] == "past"
    assert s["doses"][2]["first"] == pd.Timestamp("2027-01-04")     # sowing + 55 days


def test_wheat_follows_pau_soil_test_table():
    low = f.schedule("wheat", "Punjab", "2026-11-10", "2026-11-10",
                     card={"oc": "low", "p": "low", "k": "low"})
    assert kg(low["doses"][0]) == {"dap": 65, "mop": 20}             # PAU Table 1: DAP 65 on low P
    assert kg(low["doses"][1])["urea"] == 52                         # (130 - 0.4 x 65) = 104, half each
    high = f.schedule("wheat", "Punjab", "2026-11-10", "2026-11-10", card={"n": "high", "p": "high"})
    assert kg(high["doses"][0]) == {"dap": 45}
    assert kg(high["doses"][1])["urea"] == 35                        # (90 - 0.4 x 45) / 2 = 36
    assert high["amounts"]["adjusted"] and "adjusted for your Soil Health Card" in f.text(high)[0][0]


def test_organic_carbon_stands_for_nitrogen():
    assert f.soil_levels({"oc": "low", "n": "high"})[0] == "low"
    assert f.soil_levels({"n": "high"})[0] == "high"
    assert f.soil_levels({}) == (None, None, None)


@pytest.mark.parametrize("crop,total_urea,p_product,p_kg", [
    ("barley", 55, "ssp", 75), ("mustard", 90, "ssp", 75), ("chickpea", 13, "ssp", 50),
    ("potato", 165, "ssp", 155), ("spring_maize", 110, "ssp", 150), ("summer_moong", 11, "ssp", 100),
    ("cotton", 120, "ssp", 75), ("kharif_maize", 110, "ssp", 150), ("bajra", 90, "ssp", 150),
    ("kharif_moong", 11, "ssp", 100), ("groundnut", 13, "ssp", 50)])
def test_pau_totals_for_every_crop(crop, total_urea, p_product, p_kg):
    from cropadvisor import crops as cr
    spec = cr.get(crop)
    (m, d), _ = spec.sowing_window
    sow = pd.Timestamp(2026, m, d)
    s = f.schedule(crop, "Punjab", sow, sow, next_watering=sow + pd.Timedelta(days=30))
    urea = sum(kg(x).get("urea", 0) for x in s["doses"])
    assert abs(urea - total_urea) <= 2                               # thirds are rounded
    assert kg(s["doses"][0]).get(p_product) == p_kg
    assert all(x["first"] is None or x["first"] >= sow for x in s["doses"])
    en, hi = f.text(s)
    assert en[-1].startswith("Source: PAU") and len(en) == len(hi)


def test_stage_doses_are_marked_as_our_estimate():
    s = f.schedule("kharif_maize", "Punjab", "2026-06-10", "2026-06-12")
    knee, tassel = s["doses"][1], s["doses"][2]
    assert knee["estimate"] and tassel["estimate"] and knee["first"] < tassel["first"]
    assert "our estimate" in "\n".join(f.text(s)[0])


def test_potato_second_half_at_earthing_up_25_to_30_days():
    s = f.schedule("potato", "Punjab", "2026-10-01", "2026-10-27")
    d = s["doses"][1]
    assert d["first"] == pd.Timestamp("2026-10-26") and d["last"] == pd.Timestamp("2026-10-31")
    assert d["status"] == "due_now" and kg(s["doses"][0])["mop"] == 40


def test_low_soil_without_a_pau_table_gets_25_percent_more():
    s = f.schedule("cotton", "Punjab", "2026-05-01", "2026-05-01", card={"oc": "low"})
    assert sum(kg(x).get("urea", 0) for x in s["doses"]) == 150      # 120 x 1.25


def test_wheat_outside_punjab_and_haryana_uses_the_icar_zone_dose():
    s = f.schedule("wheat", "Bihar", "2026-11-20", "2026-11-20", zone="NEPZ",
                   card={"oc": "low"})                               # card not applied there
    urea = sum(kg(x).get("urea", 0) for x in s["doses"])
    dap = kg(s["doses"][0])["dap"]
    n_ha = (urea * 0.46 + dap * 0.18) * 2.47105
    p_ha = dap * 0.46 * 2.47105
    assert n_ha == pytest.approx(150, abs=2) and p_ha == pytest.approx(60, abs=1.5)
    assert not s["amounts"]["adjusted"] and not s["pau"]
    cz = f.schedule("wheat", "Madhya Pradesh", "2026-11-15", "2026-11-15", zone="CZ")
    n_cz = (sum(kg(x).get("urea", 0) for x in cz["doses"]) * 0.46 + kg(cz["doses"][0])["dap"] * 0.18)
    assert n_cz * 2.47105 == pytest.approx(120, abs=2)
    assert s["doses"][1]["first"] == pd.Timestamp("2026-12-30")     # first node, 40 days


def test_daily_advice_carries_the_fertiliser_block():
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2025-12-01"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast())
    assert res["ok"] and "Fertiliser for wheat" in res["text_en"]
    assert res["fertiliser"]["doses"][0]["kg_per_acre"] == {"dap": 55}
    assert "खाद" in res["text_hi"]
    only = service.advise_request({**req, "parts": ("water",)}, now="2027-01-20",
                                  fetch_history=fake_history(), fetch_forecast=fake_forecast())
    assert "Fertiliser" not in only["text_en"]
