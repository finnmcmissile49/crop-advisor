"""Soil properties from ISRIC SoilGrids 2.0 (step 6), plus the derived water-holding numbers the
FAO-56 water balance needs.

SoilGrids is a 250 m global model, not a field measurement. Treat it as a first guess that the
field station and Soil Health Card data will later correct.
"""
import pandas as pd

from cropadvisor.common import http_get_json

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["clay", "sand", "silt", "phh2o", "soc", "bdod", "cfvo", "nitrogen"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm"]
THICKNESS_CM = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30, "60-100cm": 40}
FRIENDLY = {"clay": "clay_pct", "sand": "sand_pct", "silt": "silt_pct", "phh2o": "ph",
            "soc": "soc_g_kg", "bdod": "bulk_density_g_cm3", "cfvo": "coarse_frag_pct",
            "nitrogen": "nitrogen_g_kg"}


def parse_soilgrids(data):
    """SoilGrids JSON -> long DataFrame (property, depth, value) in conventional units."""
    rows = []
    for layer in data["properties"]["layers"]:
        d_factor = layer.get("unit_measure", {}).get("d_factor", 1) or 1
        for d in layer["depths"]:
            v = d["values"].get("mean")
            rows.append({"property": FRIENDLY.get(layer["name"], layer["name"]),
                         "depth": d["label"],
                         "value": None if v is None else v / d_factor})
    return pd.DataFrame(rows)


def fetch_point(lat, lon, raw_path=None):
    params = {"lat": lat, "lon": lon, "property": PROPERTIES, "depth": DEPTHS, "value": "mean"}
    return parse_soilgrids(http_get_json(SOILGRIDS_URL, params, timeout=90, raw_path=raw_path))


def depth_weighted(long_df, max_depth_cm=100):
    """Thickness-weighted mean of each property over 0..max_depth_cm."""
    df = long_df.dropna(subset=["value"]).copy()
    df["w"] = df["depth"].map(THICKNESS_CM)
    df = df[df["depth"].map(lambda s: int(s.split("-")[1].rstrip("cm")) <= max_depth_cm)]
    g = df.groupby("property").apply(lambda x: (x["value"] * x["w"]).sum() / x["w"].sum(),
                                     include_groups=False)
    return g.to_dict()


def saxton_rawls(sand_pct, clay_pct, om_pct):
    """Field capacity and wilting point (volumetric fractions), Saxton & Rawls (2006) eqs 1-2.

    Reasonable for clay up to about 60 percent; black cotton soils near that limit are flagged.
    """
    S, C, OM = sand_pct / 100, clay_pct / 100, om_pct
    t1500 = (-0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM
             + 0.068 * S * C + 0.031)
    wp = t1500 + (0.14 * t1500 - 0.02)
    t33 = (-0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM
           + 0.452 * S * C + 0.299)
    fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    return fc, wp


def usda_texture(sand, silt, clay):
    """USDA texture class from percentages (normalised to sum to 100)."""
    total = sand + silt + clay
    sand, silt, clay = (100 * x / total for x in (sand, silt, clay))
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    return "clay"


def soil_summary(long_df):
    """One row of the numbers the rest of the project uses, for a 0-100 cm profile."""
    p = depth_weighted(long_df)
    om_pct = p.get("soc_g_kg", 0) / 10 * 1.724  # g/kg -> percent, x van Bemmelen factor
    fc, wp = saxton_rawls(p["sand_pct"], p["clay_pct"], om_pct)
    return {
        **{k: round(v, 2) for k, v in p.items()},
        "organic_matter_pct": round(om_pct, 2),
        "texture": usda_texture(p["sand_pct"], p["silt_pct"], p["clay_pct"]),
        "field_capacity": round(fc, 3),
        "wilting_point": round(wp, 3),
        "awc_mm_per_m": round(1000 * (fc - wp), 1),
        "clay_above_model_range": p["clay_pct"] > 60,
    }


def fetch_locations(locations, raw_dir="data/raw/soilgrids"):
    """Soil summary for every location (DataFrame indexed by name with lat, lon)."""
    out = []
    for name, row in locations.iterrows():
        try:
            long_df = fetch_point(row["lat"], row["lon"], raw_path=f"{raw_dir}/{name}.json")
            out.append({"name": name, **soil_summary(long_df), "error": None})
        except Exception as e:  # SoilGrids is sometimes down; keep the other locations
            out.append({"name": name, "error": str(e)[:200]})
    return pd.DataFrame(out).set_index("name")
