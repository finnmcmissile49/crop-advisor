import pandas as pd
import pytest

from cropadvisor import multistate as ms


def test_norm_handles_punctuation_and_ampersand():
    assert ms.norm("Y.S.R.") == "y s r"
    assert ms.norm("Lahul & Spiti District") == "lahul and spiti"
    assert ms.norm("  Kaimur (Bhabua) ") == "kaimur bhabua"


def test_clean_rainfall_averages_and_flags_duplicates():
    df = pd.DataFrame({
        "date": ["2010-06-01", "2010-06-01", "2010-06-02"],
        "state_code": [37, 37, 37], "state_name": ["Ladakh"] * 3,
        "district_code": [9, 9, 9], "district_name": ["Leh Ladakh"] * 3,
        "actual": [0.0, 0.06, -1.0], "normal": [0.1, 0.1, 0.1]})
    out = ms.clean_rainfall(df)
    assert len(out) == 2
    first = out[out.date == "2010-06-01"].iloc[0]
    assert first.actual == pytest.approx(0.03) and bool(first.dup_averaged)
    assert pd.isna(out[out.date == "2010-06-02"].actual.iloc[0])   # negative -> missing


def _daily(code, start, end, value):
    days = pd.date_range(start, end)
    return pd.DataFrame({"date": days, "district_code": code, "actual": value, "normal": 1.0})


def test_monthly_and_seasonal_rain():
    d = pd.concat([_daily(1, "2015-06-01", "2016-05-31", 2.0)])
    d = d[~((d.date.dt.month == 7) & (d.date.dt.day > 15))]          # half of July missing
    m = ms.monthly_rain(d)
    july = m[(m.year == 2015) & (m.month == 7)].iloc[0]
    assert july.coverage == pytest.approx(15 / 31)
    s = ms.seasonal_rain(m).set_index("crop_year")
    # July scaled up to a full month, so kharif = 2 mm/day * 122 days
    assert s.loc[2015, "kharif_rain_mm"] == pytest.approx(2 * 122)
    assert not s.loc[2015, "kharif_complete"]                        # July below 80 percent
    assert s.loc[2015, "rabi_complete"]                              # Oct 2015 - Feb 2016
    assert s.loc[2015, "rabi_rain_mm"] == pytest.approx(2 * (31 + 30 + 31 + 31 + 29))


def test_match_districts_exact_alias_fuzzy_and_none():
    icr = pd.DataFrame({"icrisat_dist": [1, 2, 3, 4], "state_code": [29] * 4,
                        "icrisat_name": ["Mandya", "Belgaum", "Chickballapur", "Old Mystery"]})
    rain = pd.DataFrame({"district_code": [544, 527, 630, 999], "state_code": [29] * 4,
                         "district_name": ["Mandya", "Belagavi", "Chikkaballapura", "Bidar"]})
    m = ms.match_districts(icr, rain, cutoff=0.8).set_index("icrisat_dist")
    assert m.loc[1, "method"] == "exact" and m.loc[1, "district_code"] == 544
    assert m.loc[2, "method"] == "alias" and m.loc[2, "district_code"] == 527
    assert m.loc[3, "method"] == "fuzzy" and m.loc[3, "district_code"] == 630
    assert m.loc[4, "method"] == "none"


def test_match_is_one_to_one():
    icr = pd.DataFrame({"icrisat_dist": [1, 2], "state_code": [9, 9],
                        "icrisat_name": ["Kanpur", "Kanpur Dehat"]})
    rain = pd.DataFrame({"district_code": [157], "state_code": [9],
                         "district_name": ["Kanpur Dehat"]})
    m = ms.match_districts(icr, rain, cutoff=0.6)
    assert m["district_code"].dropna().tolist() == [157]


def test_icrisat_long_units_and_missing():
    w = pd.DataFrame({"Dist Code": [1], "Year": [2015],
                      "SOYABEAN AREA [1000 ha]": [100.0],
                      "SOYABEAN PRODUCTION [1000 tons]": [80.0],
                      "SOYABEAN YIELD [Kg per ha]": [800.0],
                      "COTTON AREA [1000 ha]": [-1.0],
                      "COTTON PRODUCTION [1000 tons]": [-1.0],
                      "COTTON YIELD [Kg per ha]": [-1.0]})
    out = ms.icrisat_long(w).set_index("crop")
    assert out.loc["Soyabean", "area_ha"] == 100000
    assert out.loc["Soyabean", "yield_check"] == pytest.approx(1.0)
    assert pd.isna(out.loc["Cotton", "area_ha"])


def test_all_india_converts_bales_and_drops_nuts():
    df = pd.DataFrame({"State_Name": ["Maharashtra"] * 3, "District_Name": ["LATUR"] * 3,
                       "Crop_Year": [2010] * 3, "Season": ["Kharif"] * 3,
                       "Crop": ["Cotton(lint)", "Coconut ", "Soyabean"],
                       "Area": [1000, 10, 2000], "Production": [2000, 50000, 2400]})
    out = ms.all_india_long(df).set_index("crop")
    assert out.loc["Cotton(Lint)", "production_t"] == pytest.approx(340)   # 2000 bales * 170 kg
    assert pd.isna(out.loc["Coconut", "production_t"])
    assert out.loc["Soyabean", "yield_t_ha"] == pytest.approx(1.2)


def test_build_table_joins_on_matched_district_and_crop_year():
    icr_long = pd.DataFrame({"icrisat_dist": [1, 1], "year": [2008, 2015], "crop": ["Soyabean"] * 2,
                             "yield_kg_ha": [700, 900]})
    matches = pd.DataFrame({"icrisat_dist": [1], "district_code": [481], "state": ["Maharashtra"],
                            "icrisat_name": ["Latur"], "method": ["exact"]})
    seasons = pd.DataFrame({"district_code": [481], "crop_year": [2015], "kharif_rain_mm": [450.0]})
    t = ms.build_table(icr_long, matches, seasons)
    assert len(t) == 1 and t.iloc[0].kharif_rain_mm == 450.0


def test_new_district_borrows_parent_rainfall():
    icr = pd.DataFrame({"icrisat_dist": [1, 2], "state_code": [36, 36],
                        "icrisat_name": ["Medak", "Siddipet"]})
    rain = pd.DataFrame({"district_code": [513], "state_code": [36], "district_name": ["Medak"]})
    m = ms.match_districts(icr, rain).set_index("icrisat_dist")
    assert m.loc[1, "method"] == "exact"
    assert m.loc[2, "method"] == "parent" and m.loc[2, "district_code"] == 513
