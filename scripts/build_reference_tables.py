"""Build the small reference tables the calculator reads (data/reference/), from the processed files
in the agri-project folder. Run once after the source files change:

    python scripts/build_reference_tables.py --agri-dir "C:/Users/Aviral/OneDrive/Desktop/agri-project"

Inputs (all already in the agri-project folder; nothing there is modified):
    03_processed_data/rainfall_district_monthly_2009_2024.csv   IMD district rainfall + IMD normals
    03_processed_data/shc_district_nutrient_status_2023_2027.csv Soil Health Card, all India
    03_processed_data/north_india_yields_2009_2022.csv           ICRISAT + DES district yields
    03_processed_data/north_india_district_map.csv               district spellings per source
    04_market_prices_ceda/ceda_prices_monthly_2001_2025.csv.gz   CEDA / Agmarknet monthly prices

Outputs (committed, so the calculator runs from a fresh copy of the code):
    data/reference/imd_rain_monthly.csv      27 calculator districts: IMD normal and 2009-2024 mean
    data/reference/soil_health_card.csv      calculator + Haryana/Punjab districts, per cycle and nutrient
    data/reference/district_yields.csv       Haryana and Punjab wheat, rice, cotton, 2009-2022
    data/reference/mandi_prices.csv          Haryana and Punjab monthly modal prices from 2015, unflagged rows
    data/reference/district_yields_all.csv   Haryana and Punjab yields, 9 crops, 2000-2022 (season model)
    data/reference/district_rain_monthly.csv Haryana and Punjab IMD monthly rain and normals, 2009-2024

Extra inputs for the last two:
    01_raw_data/icrisat_district_database/icrisat_dld_crops_unapportioned_1990_2019.csv
    03_processed_data/des_apy_district_2015_2022.csv
"""
import argparse
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REF = os.path.join(ROOT, "data", "reference")
LOCATIONS = os.path.join(ROOT, "data", "locations_wheat_10states.csv")

# Calculator district -> name in the IMD district list (data/reference/rain_districts_lgd.csv)
IMD_NAMES = {"Udham Singh Nagar": "Udam Singh Nagar", "Dakshin Dinajpur": "Dinajpur Dakshin"}
# Calculator district -> (state, district) as the Soil Health Card dashboard spells them
SHC_NAMES = {"Ahmadabad": ("GUJARAT", "AHMADABAD"), "Udham Singh Nagar": (None, "UDAM SINGH NAGAR"),
             "Dakshin Dinajpur": (None, "DINAJPUR DAKSHIN")}
NUTRIENTS = {"n": ("n_low", "n_samples"), "p": ("p_low", "p_samples"), "k": ("k_low", "k_samples"),
             "oc": ("oc_low", "oc_samples"), "zn": ("zn_deficient", "zn_samples"),
             "s": ("s_deficient", "s_samples")}
# CEDA (Agmarknet) commodity names for the calculator's crops
COMMODITIES = ["Wheat", "Paddy(Dhan)(Common)", "Cotton", "Mustard", "Bengal Gram (Gram)(Whole)",
               "Barley (Jau)", "Potato", "Maize", "Green Gram (Moong)(Whole)",
               "Bajra (Pearl Millet/Cumbu)", "Groundnut"]
PRICES_FROM = "2015-01"   # ten-plus years is enough for recent prices and their spread
# CEDA district spelling -> the project's canonical name (north_india_district_map.csv)
CEDA_DISTRICTS = {"Firozpur": "Ferozepur", "Muktsar": "Sri Muktsar Sahib",
                  "Sahibzada Ajit Singh Nagar": "S.A.S Nagar", "Gurgaon": "Gurugram", "Mewat": "Nuh"}


def _norm(s):
    return str(s).strip().lower().replace("&", "and")


def imd_monthly(agri, locations):
    lgd = pd.read_csv(os.path.join(ROOT, "data", "reference", "rain_districts_lgd.csv"))
    lgd["key"] = lgd["state_name"].map(_norm) + "|" + lgd["district_name"].map(_norm)
    m = pd.read_csv(os.path.join(agri, "03_processed_data", "rainfall_district_monthly_2009_2024.csv"))
    rows = []
    for _, r in locations.iterrows():
        key = _norm(r["state"]) + "|" + _norm(IMD_NAMES.get(r["name"], r["name"]))
        hit = lgd[lgd["key"] == key]
        if hit.empty:
            raise SystemExit(f"No IMD rainfall district for {r['name']}, {r['state']}")
        code = int(hit["district_code"].iloc[0])
        g = m[(m["district_code"] == code) & (m["coverage"] >= 0.9)]
        for month, gm in g.groupby("month"):
            rows.append({"name": r["name"], "state": r["state"], "imd_district_code": code,
                         "month": int(month), "normal_mm": round(float(gm["normal_mm"].iloc[0]), 1),
                         "mean_2009_2024_mm": round(float(gm["rain_mm"].mean()), 1),
                         "years": int(gm["year"].nunique())})
    return pd.DataFrame(rows)


def soil_health_card(agri, locations):
    shc = pd.read_csv(os.path.join(agri, "03_processed_data",
                                   "shc_district_nutrient_status_2023_2027.csv"))
    shc["s_key"], shc["d_key"] = shc["state"].map(_norm), shc["district"].map(_norm)
    dmap = pd.read_csv(os.path.join(agri, "03_processed_data", "north_india_district_map.csv"))
    wanted = [(r["name"], r["state"], *SHC_NAMES.get(r["name"], (r["state"], r["name"])))
              for _, r in locations.iterrows()]
    wanted += [(r["district"], r["state"], r["state"], r["shc_name"]) for _, r in dmap.iterrows()
               if isinstance(r["shc_name"], str)]
    rows, seen = [], set()
    for name, state, shc_state, shc_dist in wanted:
        if (name, state) in seen:
            continue
        seen.add((name, state))
        g = shc[shc["d_key"] == _norm(shc_dist)]
        if shc_state:
            sk = _norm(shc_state)
            g = g[g["s_key"].str.replace(" and ", " ").str.contains(sk.replace(" and ", " ")[:6])]
        for _, r in g.iterrows():
            for nut, (low, n) in NUTRIENTS.items():
                samples = r.get(n)
                if pd.isna(samples) or samples <= 0:
                    continue
                rows.append({"name": name, "state": state, "cycle": r["cycle"], "nutrient": nut,
                             "samples": int(samples),
                             "pct_low": round(100 * float(r[low]) / float(samples), 1)})
    return pd.DataFrame(rows)


def district_yields(agri):
    y = pd.read_csv(os.path.join(agri, "03_processed_data", "north_india_yields_2009_2022.csv"))
    keep = ["state", "district", "crop", "season", "year", "area_ha", "production_t", "yield_t_ha",
            "source", "note"]
    return y[keep]


def mandi_prices(agri):
    p = pd.read_csv(os.path.join(agri, "04_market_prices_ceda", "ceda_prices_monthly_2001_2025.csv.gz"),
                    low_memory=False)
    p = p[p["state"].isin(["Punjab", "Haryana"]) & p["commodity"].isin(COMMODITIES)
          & p["flag"].isna() & p["p_modal"].gt(0) & (p["month"] >= PRICES_FROM)]
    p = p.assign(district=p["district"].where(p["level"] == "district").map(
        lambda d: CEDA_DISTRICTS.get(d, d) if isinstance(d, str) else None))
    out = p[["level", "state", "district", "commodity", "month", "p_min", "p_max", "p_modal"]]
    return out.sort_values(["state", "level", "district", "commodity", "month"],
                           na_position="first")


# Season model crops: name -> (ICRISAT column stem, DES crop name, DES season, DES unit factor)
MODEL_CROPS = {
    "Mustard": ("RAPESEED AND MUSTARD", "Rapeseed &Mustard", "Rabi", 1.0),
    "Barley": ("BARLEY", "Barley", "Rabi", 1.0),
    "Chickpea": ("CHICKPEA", "Gram", "Rabi", 1.0),
    "Maize": ("MAIZE", "Maize", "Kharif", 1.0),
    "Bajra": ("PEARL MILLET", "Bajra", "Kharif", 1.0),
    "Groundnut": ("GROUNDNUT", "Groundnut", "Kharif", 1.0),
}
HISTORY_FROM = 2000   # years before the rain record, used only for the lagged-yield features
SEASON = {"Wheat": "Rabi", "Mustard": "Rabi", "Barley": "Rabi", "Chickpea": "Rabi",
          "Rice": "Kharif", "Cotton": "Kharif", "Maize": "Kharif", "Bajra": "Kharif",
          "Groundnut": "Kharif"}


def _icrisat(agri, dmap):
    ic = pd.read_csv(os.path.join(agri, "01_raw_data", "icrisat_district_database",
                                  "icrisat_dld_crops_unapportioned_1990_2019.csv"))
    ic = ic[ic["State Name"].isin(["Punjab", "Haryana"])]
    ic = ic.merge(dmap[["state", "district", "icrisat_name"]], left_on="Dist Name",
                  right_on="icrisat_name")
    return ic


def district_yields_all(agri):
    """Yields for the season model: wheat, rice and cotton from the North India table (2009-2022)
    with ICRISAT years before 2009 added for history; six more crops from ICRISAT (to 2019) and
    DES (2020-2022). Yield = production / area (t/ha; cotton is lint). ICRISAT is kept wherever
    both exist; how well the two agree for each crop is printed and saved."""
    dmap = pd.read_csv(os.path.join(agri, "03_processed_data", "north_india_district_map.csv"))
    ic = _icrisat(agri, dmap)
    north = district_yields(agri)
    rows = []
    for crop, stem in (("Wheat", "WHEAT"), ("Rice", "RICE"), ("Cotton", "COTTON")):
        h = ic[(ic["Year"] >= HISTORY_FROM) & (ic["Year"] < 2009)]
        rows.append(pd.DataFrame({"state": h["state"], "district": h["district"], "crop": crop,
                                  "year": h["Year"], "area_ha": h[f"{stem} AREA [1000 ha]"] * 1000,
                                  "production_t": h[f"{stem} PRODUCTION [1000 tons]"] * 1000,
                                  "source": "ICRISAT DLD"}))
        n = north[north["crop"] == crop]
        rows.append(n[["state", "district", "crop", "year", "area_ha", "production_t", "source"]])
    des = pd.read_csv(os.path.join(agri, "03_processed_data", "des_apy_district_2015_2022.csv"))
    des = des[des["state"].isin(["Punjab", "Haryana"])].merge(
        dmap[["state", "district", "des_name"]].rename(columns={"district": "canon"}),
        left_on=["state", "district"], right_on=["state", "des_name"])
    agree = []
    for crop, (stem, dname, dseason, factor) in MODEL_CROPS.items():
        i = ic[ic["Year"] >= HISTORY_FROM]
        a = pd.DataFrame({"state": i["state"], "district": i["district"], "crop": crop,
                          "year": i["Year"], "area_ha": i[f"{stem} AREA [1000 ha]"] * 1000,
                          "production_t": i[f"{stem} PRODUCTION [1000 tons]"] * 1000,
                          "source": "ICRISAT DLD"})
        d = des[(des["crop"] == dname) & (des["season"] == dseason)]
        b = pd.DataFrame({"state": d["state"], "district": d["canon"], "crop": crop,
                          "year": d["crop_year"], "area_ha": d["area_ha"],
                          "production_t": d["production"] * factor,
                          "source": "DES (data.desagri.gov.in)"})
        a = a[(a["area_ha"] > 0) & (a["production_t"] >= 0)]
        b = b[(b["area_ha"] > 0) & (b["production_t"] >= 0)]
        both = a.merge(b, on=["district", "year"], suffixes=("_i", "_d"))
        if len(both):
            r = (both["production_t_i"] / both["area_ha_i"]) / (both["production_t_d"] / both["area_ha_d"])
            agree.append({"crop": crop, "district_years_both": len(both),
                          "share_within_10pct": round(float(((r - 1).abs() <= 0.10).mean()), 2),
                          "median_ratio_icrisat_over_des": round(float(r.median()), 3)})
        rows += [a, b[b["year"] > a["year"].max()]]
    out = pd.concat(rows, ignore_index=True)
    out = out[(out["area_ha"] > 0) & out["production_t"].notna() & (out["production_t"] >= 0)]
    out["yield_t_ha"] = (out["production_t"] / out["area_ha"]).round(4)
    out["season"] = out["crop"].map(SEASON)
    out = out.drop_duplicates(["district", "crop", "year"], keep="first")
    return out.sort_values(["crop", "state", "district", "year"]), pd.DataFrame(agree)


def district_rain_monthly(agri):
    """IMD monthly rain and IMD's normal for the 45 Haryana and Punjab districts (districts with
    no series of their own take their parent's, as in the North India table)."""
    dmap = pd.read_csv(os.path.join(agri, "03_processed_data", "north_india_district_map.csv"))
    lgd = pd.read_csv(os.path.join(ROOT, "data", "reference", "rain_districts_lgd.csv"))
    lgd["key"] = lgd["state_name"].map(_norm) + "|" + lgd["district_name"].map(_norm)
    m = pd.read_csv(os.path.join(agri, "03_processed_data", "rainfall_district_monthly_2009_2024.csv"))
    rows = []
    for _, r in dmap.iterrows():
        hit = lgd[lgd["key"] == _norm(r["state"]) + "|" + _norm(r["rain_name"])]
        if hit.empty:
            raise SystemExit(f"No IMD district for {r['district']} ({r['rain_name']})")
        g = m[m["district_code"] == int(hit["district_code"].iloc[0])]
        rows.append(g.assign(state=r["state"], district=r["district"], rain_basis=r["rain_basis"]))
    out = pd.concat(rows)[["state", "district", "rain_basis", "year", "month", "rain_mm",
                           "normal_mm", "coverage"]]
    return out.round(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agri-dir", required=True, help="the agri-project folder")
    ap.add_argument("--out", default=REF)
    a = ap.parse_args()
    loc = pd.read_csv(LOCATIONS)
    os.makedirs(a.out, exist_ok=True)
    tables = {"imd_rain_monthly.csv": imd_monthly(a.agri_dir, loc),
              "soil_health_card.csv": soil_health_card(a.agri_dir, loc),
              "district_yields.csv": district_yields(a.agri_dir),
              "mandi_prices.csv": mandi_prices(a.agri_dir)}
    yall, agree = district_yields_all(a.agri_dir)
    tables["district_yields_all.csv"] = yall
    tables["district_rain_monthly.csv"] = district_rain_monthly(a.agri_dir)
    agree.to_csv(os.path.join(ROOT, "data", "checks", "yield_sources_agreement.csv"), index=False)
    print(agree.to_string(index=False))
    for fn, df in tables.items():
        df.to_csv(os.path.join(a.out, fn), index=False)
        print(f"{fn}: {len(df)} rows")


if __name__ == "__main__":
    main()
