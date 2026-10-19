import numpy as np
import pandas as pd
import pytest

from cropadvisor import northindia as ni


def _des(rows):
    return pd.DataFrame(rows, columns=["state", "district", "crop_year", "season", "crop", "area_ha",
                                        "production", "flag"])


def test_district_map_has_no_duplicates_and_covers_both_states():
    m = ni.DISTRICT_MAP
    assert not m.duplicated(["state", "district"]).any()
    assert set(m["state"]) == {"Haryana", "Punjab"}
    assert len(m) == 45
    assert not m.duplicated(["state", "des_name"]).any()
    assert not m.duplicated(["state", "shc_name"]).any()


def test_des_names_are_mapped_and_cotton_bales_become_tonnes():
    d = _des([["Punjab", "Firozepur", 2018, "Rabi", "Wheat", 100.0, 450.0, None],
              ["Punjab", "Muktsar", 2018, "Kharif", "Cotton(lint)", 100.0, 300.0, None],
              ["Delhi", "Delhi_Total", 2018, "Rabi", "Wheat", 10.0, 40.0, None]])
    out = ni.des_north_india(d)
    assert set(out["district"]) == {"Ferozepur", "Sri Muktsar Sahib"}  # Delhi dropped
    wheat = out[out["crop"] == "Wheat"].iloc[0]
    cotton = out[out["crop"] == "Cotton"].iloc[0]
    assert wheat["yield_t_ha"] == pytest.approx(4.5)
    # 300 bales x 170 kg = 51 t over 100 ha
    assert cotton["production_t"] == pytest.approx(51.0)
    assert cotton["yield_t_ha"] == pytest.approx(0.51)


def test_thousandfold_production_slip_is_flagged_and_excluded_not_rescaled():
    rows = [["Haryana", "Sirsa", y, "Kharif", "Cotton(lint)", 200000.0, p, None]
            for y, p in [(2018, 600000.0), (2019, 800000.0), (2020, 499.59), (2021, 450000.0)]]
    out = ni.des_north_india(_des(rows)).set_index("year")
    assert np.isnan(out.loc[2020, "yield_t_ha"]) and np.isnan(out.loc[2020, "production_t"])
    assert "thousand-bales" in out.loc[2020, "flag"]
    assert out.loc[2019, "flag"] == ""
    assert out.loc[2019, "yield_t_ha"] == pytest.approx(800000 * 0.17 / 200000)
    table, _ = ni.stitch_yields(out.reset_index().iloc[0:0], out.reset_index())
    assert "excluded" in table[table["year"] == 2020]["note"].iloc[0]


def test_unmapped_des_district_fails_loudly():
    d = _des([["Haryana", "Atlantis", 2018, "Rabi", "Wheat", 100.0, 450.0, None]])
    with pytest.raises(ValueError, match="Atlantis"):
        ni.des_north_india(d)


def test_icrisat_contradicting_rows_lose_their_yield():
    icr = pd.DataFrame({
        "state": ["Haryana", "Haryana"], "icrisat_name": ["Hissar", "Hissar"], "year": [2010, 2011],
        "crop": ["Wheat", "Wheat"], "area_ha": [100.0, 100.0], "production_t": [450.0, 450.0],
        "flag": [np.nan, "area/yield contradict"]})
    out = ni.icrisat_north_india(icr)
    assert out["district"].tolist() == ["Hisar", "Hisar"]
    assert out["yield_t_ha"].iloc[0] == pytest.approx(4.5)
    assert np.isnan(out["yield_t_ha"].iloc[1])


def test_icrisat_zero_production_on_sown_area_is_a_gap_not_a_zero_yield():
    icr = pd.DataFrame({
        "state": ["Punjab"], "icrisat_name": ["Mansa"], "year": [2012], "crop": ["Cotton"],
        "area_ha": [1000.0], "production_t": [0.0], "flag": [np.nan]})
    assert np.isnan(ni.icrisat_north_india(icr)["yield_t_ha"].iloc[0])


def test_cotton_rows_carry_the_bale_weight_note_and_other_crops_do_not():
    base = {"state": "Punjab", "district": "Moga", "season": "Kharif", "year": 2016, "area_ha": 100.0,
            "production_t": 50.0, "yield_t_ha": 0.5, "source": "ICRISAT DLD"}
    icr = pd.DataFrame([{**base, "crop": "Cotton"}, {**base, "crop": "Rice"}])
    des = icr.iloc[0:0]
    table, _ = ni.stitch_yields(icr, des)
    notes = dict(zip(table["crop"], table["note"]))
    assert "bale" in notes["Cotton"]
    assert notes["Rice"] == ""


def test_overlap_check_and_icrisat_wins_when_both_report():
    base = {"state": "Punjab", "district": "Moga", "crop": "Wheat", "season": "Rabi", "year": 2016,
            "area_ha": 100.0, "production_t": 500.0}
    icr = pd.DataFrame([{**base, "yield_t_ha": 5.0, "source": "ICRISAT DLD"}])
    des = pd.DataFrame([{**base, "yield_t_ha": 5.1, "source": "DES"},
                        {**base, "year": 2020, "yield_t_ha": 4.0, "source": "DES"}])
    summary, pairs = ni.overlap_check(icr, des)
    assert summary.loc[0, "n_pairs"] == 1
    assert summary.loc[0, "share_within_5pct"] == 1.0
    table, conflicts = ni.stitch_yields(icr, des)
    assert len(table) == 2 and len(conflicts) == 0
    assert table[table["year"] == 2016]["source"].iloc[0] == "ICRISAT DLD"
    assert table[table["year"] == 2020]["source"].iloc[0] == "DES"


def test_shc_best_cycle_keeps_only_well_sampled_districts():
    shc = pd.DataFrame({
        "cycle": ["2023-24", "2024-25", "2023-24"], "state": ["Punjab"] * 3,
        "district": ["Bathinda", "Bathinda", "Mansa"], "n_samples": [9000, 18000, 4],
        **{c: [50.0, 60.0, 99.0] for c in ni.SHC_PCT}})
    best = ni.shc_best_cycle(shc).set_index("district")
    assert best.loc["Bathinda", "shc_cycle"] == "2024-25"
    assert bool(best.loc["Bathinda", "shc_reliable"]) is True
    assert bool(best.loc["Mansa", "shc_reliable"]) is False
    assert np.isnan(best.loc["Mansa", "pct_n_low"])
    # Bathinda has two well-sampled cycles: P went 50 -> 60 (and K the same), spread 10 points
    assert best.loc["Bathinda", "shc_cycles_used"] == 2
    assert best.loc["Bathinda", "shc_p_low_spread_pp"] == pytest.approx(10.0)
    assert best.loc["Mansa", "shc_cycles_used"] == 0


def test_rain_uses_the_crops_own_season_and_parent_districts():
    yields = pd.DataFrame({
        "state": ["Punjab", "Punjab"], "district": ["Pathankot", "Pathankot"], "crop": ["Wheat", "Rice"],
        "season": ["Rabi", "Kharif"], "year": [2016, 2016]})
    # the mapping needs every district's rain name; give the full list so the check passes
    full = ni.DISTRICT_MAP[["state", "rain_name"]].drop_duplicates().rename(
        columns={"state": "state_name", "rain_name": "district_name"})
    full["district_code"] = range(1, len(full) + 1)
    full.loc[(full["state_name"] == "Punjab") & (full["district_name"] == "Gurdaspur"), "district_code"] = 32
    seasons = pd.DataFrame({"district_code": [32], "crop_year": [2016], "kharif_rain_mm": [700.0],
                            "kharif_departure_pct": [5.0], "kharif_complete": [True],
                            "rabi_rain_mm": [90.0], "rabi_departure_pct": [-10.0], "rabi_complete": [True]})
    out = ni.rain_for_yields(yields, seasons, full).set_index("crop")
    assert out.loc["Wheat", "season_rain_mm"] == 90.0   # rabi rain for wheat
    assert out.loc["Rice", "season_rain_mm"] == 700.0   # kharif rain for rice
    assert out.loc["Wheat", "rain_basis"] == "parent"
