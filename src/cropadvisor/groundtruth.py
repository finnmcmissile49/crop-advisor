"""Independent check: soil samples weighed before and after oven-drying give the true soil moisture,
so the sensors, the water balance and the fused estimate are not judged only by our own models.

The standard gravimetric method: a soil core of known volume (or a sample plus a separate bulk
density), weighed wet, dried at 105 C until its weight stops changing (usually 24 hours), weighed
again. Sample sheet, one row per sample (template: data/templates/soil_samples.csv):

    date, depth_cm, tin_g, wet_with_tin_g, dry_with_tin_g, bulk_density_g_cm3, field_id (optional)

Gravimetric water = (wet - dry) / (dry - tin); volumetric = gravimetric x bulk density (water at
1 g/cm3). Bulk density from a core (dry soil mass / core volume) is best; if it is blank the
district's SoilGrids value is used and the row says so.

Comparisons (each only on days that have both):
    sensor     the station's reading at the sensor nearest the sample depth, that day
    model      the water balance alone (fusion.run dr_model_mm), as root-zone water content
    fused      the Kalman estimate (dr_fused_mm)
Reported as bias (estimate minus sample) and RMSE in m3/m3, with the number of samples. With few
samples (one field, one season), these are case studies, not accuracy figures.
"""
import io

import numpy as np
import pandas as pd

SAMPLE_COLUMNS = ["date", "depth_cm", "tin_g", "wet_with_tin_g", "dry_with_tin_g",
                  "bulk_density_g_cm3", "field_id"]


def load_samples(source, default_bulk_density=None):
    """Samples from a CSV path, CSV text or list of dicts, with gravimetric and volumetric water."""
    if isinstance(source, list):
        df = pd.DataFrame(source)
    elif isinstance(source, str) and "\n" in source:
        df = pd.read_csv(io.StringIO(source))
    else:
        df = pd.read_csv(source)
    for c in SAMPLE_COLUMNS:
        if c not in df:
            df[c] = np.nan
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    for c in SAMPLE_COLUMNS[1:6]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    water = df["wet_with_tin_g"] - df["dry_with_tin_g"]
    soil = df["dry_with_tin_g"] - df["tin_g"]
    bad = df["date"].isna() | (soil <= 0) | (water < 0)
    df["problem"] = np.where(bad, "check the weights and date", "")
    df["theta_g"] = (water / soil).where(~bad)
    bd = df["bulk_density_g_cm3"]
    df["bulk_density_source"] = np.where(bd.notna(), "sample", "district (SoilGrids)")
    df["theta_v"] = df["theta_g"] * bd.fillna(default_bulk_density if default_bulk_density
                                              else np.nan)
    return df


def _stats(est, true):
    e = (np.asarray(est, float) - np.asarray(true, float))
    e = e[~np.isnan(e)]
    if not len(e):
        return {"n": 0, "bias": None, "rmse": None}
    return {"n": int(len(e)), "bias": round(float(e.mean()), 3),
            "rmse": round(float(np.sqrt((e ** 2).mean())), 3)}


def compare(samples, readings=None, fused=None, field_capacity=None, awc_mm_per_m=None,
            top_depth_cm=15, deep_depth_cm=45):
    """Bias and RMSE (m3/m3) of the sensors, the model and the fused estimate against samples.

    readings: station.daily output. fused: fusion.run daily output; with field_capacity (m3/m3)
    and awc_mm_per_m, root-zone depletion Dr (mm) becomes water content:
    theta = FC - Dr / (1000 Zr), with Zr = TAW / AWC. It is compared with the mean of that day's
    samples over all depths, the nearest thing to a root-zone average."""
    s = samples[samples["theta_v"].notna()]
    rows = []
    if readings is not None and len(readings):
        r = readings.set_index("date")
        for x in s.itertuples():
            if x.date not in r.index:
                continue
            near_top = abs(x.depth_cm - top_depth_cm) <= abs(x.depth_cm - deep_depth_cm)
            col = "sm_top" if near_top else "sm_deep"
            rows.append({"what": f"sensor ({col})", "est": r.loc[x.date, col], "true": x.theta_v})
    if fused is not None and len(fused) and field_capacity is not None and awc_mm_per_m:
        f = fused.set_index("date")
        for d, true in s.groupby("date")["theta_v"].mean().items():
            if d not in f.index:
                continue
            zr_m = f.loc[d, "taw_mm"] / awc_mm_per_m
            for what, col in (("model", "dr_model_mm"), ("fused", "dr_fused_mm")):
                rows.append({"what": what, "true": true,
                             "est": field_capacity - f.loc[d, col] / (1000.0 * zr_m)})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["what", "n", "bias", "rmse"])
    return pd.DataFrame([{"what": w, **_stats(g["est"], g["true"])} for w, g in df.groupby("what")])
