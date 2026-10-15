import numpy as np
import pandas as pd

from cropadvisor.prices import clean
from cropadvisor.weather import disagreement, longest_run, qc_daily, season_table
from cropadvisor.yields import area_scale_flags, combine, standardise, year_scale_flags


def _daily(name="Latur", year=2023, rain=None):
    dates = pd.date_range(f"{year}-01-01", f"{year + 1}-03-31")
    n = len(dates)
    rng = np.random.default_rng(0)
    rain = rng.gamma(0.5, 6, n) if rain is None else rain
    return pd.DataFrame({
        "date": dates, "name": name,
        "tmax_om": 32.0, "tmin_om": 22.0, "rain_om": rain, "solar_om": 20.0, "rh_om": 60.0,
        "wind2_om": 2.0, "et0_om": 4.0,
        "tmax_pw": 33.0, "tmin_pw": 22.5, "rain_pw": rain * 0.8, "solar_pw": 19.0, "rh_pw": 62.0,
        "wind2_pw": 2.1, "et0_pw": 4.2,
        "rain_imd": rain,
    })


def test_longest_run():
    assert longest_run([True, True, False, True, True, True, False]) == 3
    assert longest_run([False, False]) == 0


def test_season_table_counts_rain_and_dry_spells():
    d = _daily()
    d["rain_om"] = 0.0
    kharif = (d.date >= "2023-06-01") & (d.date <= "2023-10-31")
    d.loc[kharif & (d.date.dt.day == 1), "rain_om"] = 10.0  # rain on the 1st of each month
    s = season_table(d)
    k = s[(s.season == "kharif") & (s.year == 2023)].iloc[0]
    assert k.n_days == 153
    assert k.rain_total_om == 50.0
    assert k.rainy_days_om == 5
    assert k.longest_dry_spell_om == 30  # 2 Aug..31 Aug, or 2 Oct..31 Oct
    assert k.et0_total_om == 153 * 4.0
    assert k.water_balance_om == 50.0 - 612.0
    # rabi 2023 runs into 2024 and is fully covered; rabi 2024 is not and must be skipped
    assert ((s.season == "rabi") & (s.year == 2023)).sum() == 1
    assert ((s.season == "rabi") & (s.year == 2024)).sum() == 0


def test_disagreement_flags_large_differences():
    s = season_table(_daily())
    flagged = disagreement(s, threshold=0.10)
    assert flagged["sources_disagree"].all()  # POWER rain is 20% lower by construction
    assert (disagreement(s, threshold=0.30)["sources_disagree"] == False).all()


def test_qc_catches_bad_values_and_gaps():
    d = _daily()
    d.loc[5, "tmin_om"] = 40.0        # tmin above tmax
    d.loc[6, "rh_pw"] = 120.0         # impossible humidity
    d.loc[7, "rain_om"] = np.nan      # missing value
    d = d.drop(index=10)              # missing date
    qc = qc_daily(d)
    checks = set(qc["check"])
    assert "tmax below tmin (om)" in checks
    assert "humidity outside 0-100 (pw)" in checks
    assert "missing values: rain_om" in checks
    assert "missing dates" in checks
    assert qc_daily(_daily()).empty


def _yields():
    rows = []
    for yr in range(2010, 2016):
        for dist in ("Latur", "Beed", "Nanded"):
            area = 1000.0 if yr != 2013 else 10.0  # 2013 mimics the 2007 scale error
            rows.append({"Dist": dist, "Crop": "soybean", "Season": "Kharif", "Yr": yr,
                         "Area": area, "Prod": area * 1.2})
    return standardise(pd.DataFrame(rows), {"Dist": "district", "Crop": "crop",
                                            "Season": "season", "Yr": "year",
                                            "Area": "area_ha", "Prod": "production_t"},
                       source="test")


def test_standardise_and_scale_checks():
    y = _yields()
    assert list(y.columns)[-1] == "source"
    assert (y["yield_t_ha"].round(3) == 1.2).all()
    assert set(area_scale_flags(y)["year"]) == {2013}
    assert list(year_scale_flags(y).index) == [2013]


def test_combine_never_overwrites_and_reports_conflicts():
    old = _yields()
    new = old[old.year >= 2014].copy()
    new["source"] = "new"
    new.loc[new.year == 2015, "yield_t_ha"] = 2.0
    extra = new[new.year == 2015].assign(year=2016)
    combined, conflicts = combine(old, pd.concat([new, extra]))
    assert len(combined) == len(old) + 3                  # only the 2016 rows are added
    assert (combined[combined.year == 2015]["source"] == "test").all()
    assert set(conflicts["year"]) == {2015}


def test_price_cleaning():
    raw = pd.DataFrame([
        {"State": "Maharashtra", "Arrival_Date": "05/10/2026", "Min_Price": "4200",
         "Max_Price": "4600", "Modal_Price": "4450"},
        {"State": "Maharashtra", "Arrival_Date": "06/10/2026", "Min_Price": "5000",
         "Max_Price": "4000", "Modal_Price": "4500"},   # min > max: dropped
    ])
    df = clean(raw)
    assert len(df) == 1
    assert df.loc[0, "arrival_date"] == pd.Timestamp("2026-10-05")
    assert df.loc[0, "modal_price"] == 4450
