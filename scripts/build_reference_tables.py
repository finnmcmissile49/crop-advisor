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
    for fn, df in tables.items():
        df.to_csv(os.path.join(a.out, fn), index=False)
        print(f"{fn}: {len(df)} rows")


if __name__ == "__main__":
    main()
