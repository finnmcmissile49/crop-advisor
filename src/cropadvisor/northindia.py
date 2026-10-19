"""North India (Haryana, Punjab) district table: yields + rainfall + soil nutrient classes.

Joins four sources that name districts differently:
- ICRISAT district yields, 2009-2019 (multistate table), names like "Bhatinda", "Roopnagar"
- DES government yields, 2015-16 to 2022-23, names like "Firozepur", "Nawanshahr"
- IMD district rainfall, LGD codes (21 Haryana and 20 Punjab districts; newer districts have no series)
- Soil Health Card dashboard, own district names and LGD codes

Rules carried over from the rest of the project:
- Nothing existing is modified. Outputs are new, labelled files.
- ICRISAT is kept wherever ICRISAT and DES both have a district-crop-year; conflicts are reported.
- Every row says which source it came from.
- Delhi is left out: ICRISAT has no Delhi, DES gives one state total only, and the Soil Health Card
  dashboard has no usable Delhi samples.
"""
import numpy as np
import pandas as pd

from .yields import combine, standardise

CROPS = {"Wheat": "Rabi", "Rice": "Kharif", "Cotton": "Kharif"}
COTTON_KG_PER_BALE = 170.0  # same conversion the all-India file uses
SHC_MIN_SAMPLES = 500        # below this a district's class percentages are not trusted

# (state, canonical name, DES name, ICRISAT name, Soil Health Card name, rainfall district, rain_basis)
# rain_basis "own" = district has its own IMD series; "parent" = district created after about 2012,
# rainfall is taken from the district it was carved from.
DISTRICTS = [
    ("Haryana", "Ambala", "Ambala", "Ambala", "AMBALA", "Ambala", "own"),
    ("Haryana", "Bhiwani", "Bhiwani", "Bhiwani", "BHIWANI", "Bhiwani", "own"),
    ("Haryana", "Charkhi Dadri", "Charki dadri", "Charkhi Dadri", "CHARKI DADRI", "Bhiwani", "parent"),
    ("Haryana", "Faridabad", "Faridabad", "Faridabad", "FARIDABAD", "Faridabad", "own"),
    ("Haryana", "Fatehabad", "Fatehabad", "Fatehabad", "FATEHABAD", "Fatehabad", "own"),
    ("Haryana", "Gurugram", "Gurgaon", "Gurgaon", "GURUGRAM", "Gurugram", "own"),
    ("Haryana", "Hisar", "Hisar", "Hissar", "HISAR", "Hisar", "own"),
    ("Haryana", "Jhajjar", "Jhajjar", "Jhajjar", "JHAJJAR", "Jhajjar", "own"),
    ("Haryana", "Jind", "Jind", "Jind", "JIND", "Jind", "own"),
    ("Haryana", "Kaithal", "Kaithal", "Kaithal", "KAITHAL", "Kaithal", "own"),
    ("Haryana", "Karnal", "Karnal", "Karnal", "KARNAL", "Karnal", "own"),
    ("Haryana", "Kurukshetra", "Kurukshetra", "Kurukshetra", "KURUKSHETRA", "Kurukshetra", "own"),
    ("Haryana", "Mahendragarh", "Mahendragarh", "Mahendragarh", "MAHENDRAGARH", "Mahendragarh", "own"),
    ("Haryana", "Nuh", "Mewat", "Mewat", "NUH", "Nuh", "own"),
    ("Haryana", "Palwal", "Palwal", "Palwal", "PALWAL", "Palwal", "own"),
    ("Haryana", "Panchkula", "Panchkula", "Panchkula", "PANCHKULA", "Panchkula", "own"),
    ("Haryana", "Panipat", "Panipat", "Panipat", "PANIPAT", "Panipat", "own"),
    ("Haryana", "Rewari", "Rewari", "Rewari", "REWARI", "Rewari", "own"),
    ("Haryana", "Rohtak", "Rohtak", "Rohtak", "ROHTAK", "Rohtak", "own"),
    ("Haryana", "Sirsa", "Sirsa", "Sirsa", "SIRSA", "Sirsa", "own"),
    ("Haryana", "Sonipat", "Sonipat", "Sonepat", "SONIPAT", "Sonipat", "own"),
    ("Haryana", "Yamunanagar", "Yamunanagar", "Yamunanagar", "YAMUNANAGAR", "Yamunanagar", "own"),
    ("Punjab", "Amritsar", "Amritsar", "Amritsar", "AMRITSAR", "Amritsar", "own"),
    ("Punjab", "Barnala", "Barnala", "Barnala", "BARNALA", "Barnala", "own"),
    ("Punjab", "Bathinda", "Bathinda", "Bhatinda", "BATHINDA", "Bathinda", "own"),
    ("Punjab", "Faridkot", "Faridkot", "Faridkot", "FARIDKOT", "Faridkot", "own"),
    ("Punjab", "Fatehgarh Sahib", "Fatehgarh sahib", "Fatehgarh Sahib", "FATEHGARH SAHIB",
     "Fatehgarh Sahib", "own"),
    ("Punjab", "Fazilka", "Fazilka", "Fazilka", "FAZILKA", "Ferozepur", "parent"),
    ("Punjab", "Ferozepur", "Firozepur", "Ferozpur", "FEROZEPUR", "Ferozepur", "own"),
    ("Punjab", "Gurdaspur", "Gurdaspur", "Gurdaspur", "GURDASPUR", "Gurdaspur", "own"),
    ("Punjab", "Hoshiarpur", "Hoshiarpur", "Hoshiarpur", "HOSHIARPUR", "Hoshiarpur", "own"),
    ("Punjab", "Jalandhar", "Jalandhar", "Jalandhar", "JALANDHAR", "Jalandhar", "own"),
    ("Punjab", "Kapurthala", "Kapurthala", "Kapurthala", "KAPURTHALA", "Kapurthala", "own"),
    ("Punjab", "Ludhiana", "Ludhiana", "Ludhiana", "LUDHIANA", "Ludhiana", "own"),
    ("Punjab", "Malerkotla", "Malerkotla", None, "MALERKOTLA", "Sangrur", "parent"),
    ("Punjab", "Mansa", "Mansa", "Mansa", "MANSA", "Mansa", "own"),
    ("Punjab", "Moga", "Moga", "Moga", "MOGA", "Moga", "own"),
    ("Punjab", "Pathankot", "Pathankot", "Pathankot", "PATHANKOT", "Gurdaspur", "parent"),
    ("Punjab", "Patiala", "Patiala", "Patiala", "PATIALA", "Patiala", "own"),
    ("Punjab", "Rupnagar", "Rupnagar", "Roopnagar", "RUPNAGAR", "Rupnagar", "own"),
    ("Punjab", "S.A.S Nagar", "S.a.s nagar", "S.A.S Nagar", "S.A.S Nagar", "S.A.S Nagar", "own"),
    ("Punjab", "Sangrur", "Sangrur", "Sangrur", "SANGRUR", "Sangrur", "own"),
    ("Punjab", "Shahid Bhagat Singh Nagar", "Nawanshahr", "S.B.S Nagar", "Shahid Bhagat Singh Nagar",
     "Shahid Bhagat Singh Nagar", "own"),
    ("Punjab", "Sri Muktsar Sahib", "Muktsar", "Shri Mukatsar Sahib", "SRI MUKTSAR SAHIB",
     "Sri Muktsar Sahib", "own"),
    ("Punjab", "Tarn Taran", "Tarn taran", "Taran Taran", "Tarn Taran", "Tarn Taran", "own"),
]
# Pilot districts, chosen on data coverage (19 Oct 2026): every one has a complete 14-year wheat
# and rice series and its own IMD rainfall series, and together they span both states and both
# farming systems: south-west cotton-wheat belt (Sirsa, Hisar, Bathinda, with 13 to 14 years of cotton)
# and rice-wheat districts (Kurukshetra, Sangrur, Tarn Taran). To be revisited once Digital Green
# names the districts it can deploy in.
PILOT = ["Sirsa", "Hisar", "Kurukshetra", "Bathinda", "Sangrur", "Tarn Taran"]

DISTRICT_MAP = pd.DataFrame(DISTRICTS, columns=[
    "state", "district", "des_name", "icrisat_name", "shc_name", "rain_name", "rain_basis"])


def _key(s):
    return str(s).strip().lower()


def _lookup(series, state, column):
    """Map a column of source names to canonical district names within one state."""
    m = DISTRICT_MAP[DISTRICT_MAP[column].notna()]
    table = {(r.state, _key(r[column])): r.district for _, r in m.iterrows()}
    return pd.Series([table.get((st, _key(n))) for st, n in zip(state, series)], index=series.index)


def _require_all_mapped(df, name_col, source):
    bad = df[df["district"].isna()][[name_col]].drop_duplicates()
    if len(bad):
        raise ValueError(f"{source}: districts with no mapping: {sorted(bad[name_col])}")


# ---------- yields ----------

def des_north_india(des):
    """Standardised DES yields for Haryana and Punjab wheat, rice, cotton.

    Cotton is reported in bales (170 kg of lint each); it is converted to tonnes so it lines up
    with ICRISAT's cotton lint. Yield is recomputed as production / area.
    """
    d = des[des["state"].isin(["Haryana", "Punjab"])].copy()
    d["crop"] = d["crop"].replace({"Cotton(lint)": "Cotton"})
    d = d[d["crop"].isin(CROPS)]
    d["district"] = _lookup(d["district"], d["state"], "des_name")
    _require_all_mapped(d.assign(des_name=des.loc[d.index, "district"]), "des_name", "DES")
    out = []
    for crop, g in d.groupby("crop"):
        factor = COTTON_KG_PER_BALE / 1000.0 if crop == "Cotton" else 1.0
        s = standardise(g, {"crop_year": "year", "production": "production_t"}, "DES (data.desagri.gov.in)",
                        production_factor=factor)
        out.append(s)
    res = pd.concat(out, ignore_index=True)
    res["season"] = res["crop"].map(CROPS)  # DES labels each of these crops with one season anyway
    res["flag"] = ""
    bad = yield_scale_flags(res)
    res.loc[bad.index, ["production_t", "yield_t_ha"]] = np.nan
    res.loc[bad.index, "flag"] = SCALE_FLAG
    return res


SCALE_FLAG = ("production about 1000x below this district's other years (likely a thousand-bales unit slip "
              "in the source); excluded, not rescaled")


def yield_scale_flags(df, ratio=0.05):
    """Rows whose yield is below `ratio` times that district-crop's median yield across years.

    Same idea as yields.area_scale_flags, but on yield: it catches a unit slip in production
    (a thousand-fold error) that the area check cannot see.
    """
    med = df.groupby(["state", "district", "crop", "season"], dropna=False)["yield_t_ha"].transform("median")
    return df[df["yield_t_ha"] < ratio * med]


def icrisat_north_india(icr):
    """Standardised ICRISAT yields (multistate table) for the same states and crops."""
    d = icr[icr["state"].isin(["Haryana", "Punjab"]) & icr["crop"].isin(CROPS)].copy()
    d["district"] = _lookup(d["icrisat_name"], d["state"], "icrisat_name")
    _require_all_mapped(d, "icrisat_name", "ICRISAT")
    s = standardise(d, {"production_t": "production_t"}, "ICRISAT DLD")
    s["season"] = s["crop"].map(CROPS)
    # ICRISAT rows whose yield was blanked as contradicting their area keep no yield here either,
    # and a zero yield on a sown area is a gap, not a harvest (same rule as multistate.py)
    contradict = d["flag"].fillna("").to_numpy() != ""
    s.loc[contradict, "yield_t_ha"] = np.nan
    s.loc[s["yield_t_ha"] <= 0, "yield_t_ha"] = np.nan
    return s.reset_index(drop=True)


def overlap_check(icrisat, des, tolerances=(0.05, 0.10)):
    """How closely ICRISAT and DES agree where both report the same district-crop-year."""
    key = ["district", "crop", "year"]
    both = icrisat.merge(des, on=key, suffixes=("_icr", "_des"))
    both = both[both["yield_t_ha_icr"].notna() & both["yield_t_ha_des"].notna()]
    both = both.assign(rel_diff=(both["yield_t_ha_des"] - both["yield_t_ha_icr"]).abs() / both["yield_t_ha_icr"])
    rows = []
    for crop, g in both.groupby("crop"):
        row = {"crop": crop, "n_pairs": len(g), "median_rel_diff": g["rel_diff"].median()}
        for t in tolerances:
            row[f"share_within_{int(t * 100)}pct"] = (g["rel_diff"] <= t).mean()
        rows.append(row)
    return pd.DataFrame(rows), both


COTTON_NOTE = ("ICRISAT cotton runs about 5 percent above DES (implied 180 vs 170 kg per bale) and its "
               "area and production are rounded to the nearest 1,000, so small districts are rough; "
               "do not read the 2014 to 2015 step as a real change")


def stitch_yields(icrisat, des):
    """ICRISAT first, DES added for years ICRISAT lacks. Returns (table, conflicts).

    Nothing is rescaled. Every row gets a `note`: cotton rows say the two sources use different
    bale weights (the join would otherwise show a false step of about 5 percent), and rows that
    failed the scale check say why their yield is blank.
    """
    table, conflicts = combine(icrisat, des, tolerance=0.05)
    if "flag" not in table:
        table["flag"] = np.nan
    table = table.assign(note="")
    table.loc[table["crop"].eq("Cotton"), "note"] = COTTON_NOTE
    flagged = table["flag"].fillna("").astype(str) != ""
    table.loc[flagged, "note"] = (table.loc[flagged, "note"] + "; " + table.loc[flagged, "flag"]).str.strip("; ")
    return table.drop(columns="flag"), conflicts


# ---------- rainfall ----------

def rain_for_yields(yields, seasons, rain_lgd):
    """Add the crop's own season rain (rabi for wheat, kharif for rice and cotton)."""
    lgd = rain_lgd.rename(columns={"district_name": "rain_name", "state_name": "state",
                                   "district_code": "district_code"})
    code = DISTRICT_MAP.merge(lgd[["state", "rain_name", "district_code"]], on=["state", "rain_name"], how="left")
    if code["district_code"].isna().any():
        raise ValueError("rainfall districts not found: " + str(code[code["district_code"].isna()]["rain_name"].tolist()))
    y = yields.merge(code[["state", "district", "district_code", "rain_basis"]], on=["state", "district"], how="left")
    s = seasons.rename(columns={"crop_year": "year"})
    cols = ["district_code", "year"]
    kh = s[cols + ["kharif_rain_mm", "kharif_departure_pct", "kharif_complete"]].rename(columns={
        "kharif_rain_mm": "season_rain_mm", "kharif_departure_pct": "season_rain_departure_pct",
        "kharif_complete": "season_rain_complete"})
    rb = s[cols + ["rabi_rain_mm", "rabi_departure_pct", "rabi_complete"]].rename(columns={
        "rabi_rain_mm": "season_rain_mm", "rabi_departure_pct": "season_rain_departure_pct",
        "rabi_complete": "season_rain_complete"})
    kharif = y[y["season"] == "Kharif"].merge(kh, on=cols, how="left")
    rabi = y[y["season"] == "Rabi"].merge(rb, on=cols, how="left")
    out = pd.concat([kharif, rabi], ignore_index=True)
    out["season_rain_complete"] = out["season_rain_complete"].map(
        {True: True, False: False, "True": True, "False": False})
    return out


# ---------- soil health card ----------

SHC_PCT = ["pct_n_low", "pct_p_low", "pct_k_low", "pct_oc_low", "pct_zn_deficient", "pct_s_deficient",
           "pct_ph_alkaline", "pct_ph_acidic", "pct_ec_saline"]


def shc_north_india(shc):
    """One row per cycle and district for Haryana and Punjab, with canonical names."""
    s = shc[shc["state"].str.upper().isin(["HARYANA", "PUNJAB"])].copy()
    s["state"] = s["state"].str.title()
    s["district_canon"] = _lookup(s["district"], s["state"], "shc_name")
    bad = s[s["district_canon"].isna()]["district"].unique()
    if len(bad):
        raise ValueError(f"Soil Health Card: districts with no mapping: {sorted(bad)}")
    return s.drop(columns="district").rename(columns={"district_canon": "district"})


def shc_best_cycle(shc_ni, min_samples=SHC_MIN_SAMPLES):
    """For each district, the cycle with the most samples, kept only if it has at least min_samples.

    Cycles are not pooled: class percentages for the same district swing a lot between cycles
    (Bathinda potassium: 96 percent low in 2023-24, 8 percent in 2025-26), which looks like a change
    in reporting rather than in soil.
    """
    idx = shc_ni.groupby(["state", "district"])["n_samples"].idxmax()
    best = shc_ni.loc[idx, ["state", "district", "cycle", "n_samples"] + SHC_PCT].copy()
    best = best.rename(columns={"cycle": "shc_cycle", "n_samples": "shc_samples"})
    keep = best["shc_samples"] >= min_samples
    best.loc[~keep, ["shc_cycle"] + SHC_PCT] = np.nan
    best["shc_reliable"] = keep
    # how much the same district's answer moves between well-sampled cycles, in percentage points
    big = shc_ni[shc_ni["n_samples"] >= min_samples]
    g = big.groupby(["state", "district"])
    def _spread(x):  # needs two valid readings, otherwise there is nothing to compare
        x = x.dropna()
        return x.max() - x.min() if len(x) >= 2 else np.nan

    spread = pd.DataFrame({
        "shc_cycles_used": g["cycle"].nunique(),  # cycles with at least min_samples samples
        "shc_p_low_spread_pp": g["pct_p_low"].agg(_spread),
        "shc_k_low_spread_pp": g["pct_k_low"].agg(_spread),
    }).reset_index()
    best = best.merge(spread, on=["state", "district"], how="left")
    best["shc_cycles_used"] = best["shc_cycles_used"].fillna(0).astype(int)
    return best.reset_index(drop=True)


# ---------- one row per district ----------

def district_summary(yields, shc_best, last_years=8):
    """Coverage and basic yield facts per district, for choosing pilot districts."""
    y = yields[yields["yield_t_ha"].notna()]
    last = y["year"].max() - last_years + 1
    rows = []
    for (state, district), g in DISTRICT_MAP.groupby(["state", "district"]):
        r = {"state": state, "district": district, "pilot": district in PILOT,
             "rain_basis": g["rain_basis"].iloc[0]}
        sub = y[(y["state"] == state) & (y["district"] == district)]
        for crop in CROPS:
            c = sub[sub["crop"] == crop]
            r[f"{crop.lower()}_years"] = c["year"].nunique()
            recent = c[c["year"] >= last]
            r[f"{crop.lower()}_mean_yield_t_ha"] = recent["yield_t_ha"].mean()
            r[f"{crop.lower()}_yield_cv"] = (recent["yield_t_ha"].std() / recent["yield_t_ha"].mean()
                                              if len(recent) > 2 else np.nan)
            r[f"{crop.lower()}_mean_area_ha"] = recent["area_ha"].mean()
        rows.append(r)
    out = pd.DataFrame(rows).merge(shc_best, on=["state", "district"], how="left")
    return out.round(3)
