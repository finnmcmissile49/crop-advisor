"""District crop yields (step 8).

Rules, carried over from the IRIS project:
- The IRIS dataset (1997-2014) is never modified. New years go in separate, labelled files.
- Every row carries a `source` column, and combining never silently overwrites a value.
- Area values are checked for scale errors like the 2007 problem (area about 1/100 of normal).

DES/UPAg district data has no public API: download it from the UPAg / DES crop statistics portal
as CSV, then map its columns with `standardise()`.
"""
import pandas as pd

STANDARD = ["state", "district", "crop", "season", "year", "area_ha", "production_t",
            "yield_t_ha", "source"]


def standardise(df, column_map, source, area_factor=1.0, production_factor=1.0):
    """Rename to the standard columns and convert units.

    column_map: {their_column: standard_column}
    area_factor / production_factor: multiply to reach hectares / tonnes
    (e.g. 1000 if the file reports thousand hectares).
    """
    out = df.rename(columns=column_map)
    missing = [c for c in ("district", "crop", "year", "area_ha", "production_t") if c not in out]
    if missing:
        raise KeyError(f"column_map does not provide: {missing}")
    for c in ("district", "crop", "season", "state"):
        if c in out:
            out[c] = out[c].astype(str).str.strip().str.title()
    out["area_ha"] = pd.to_numeric(out["area_ha"], errors="coerce") * area_factor
    out["production_t"] = pd.to_numeric(out["production_t"], errors="coerce") * production_factor
    out["yield_t_ha"] = (out["production_t"] / out["area_ha"]).where(out["area_ha"] > 0)
    out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
    out["source"] = source
    for c in STANDARD:
        if c not in out:
            out[c] = pd.NA
    return out[STANDARD]


def area_scale_flags(df, ratio=0.1):
    """Rows whose area is below `ratio` times that district-crop's median area across years.

    This is the check that would have caught the 2007 corruption in the IRIS source data.
    """
    med = df.groupby(["district", "crop", "season"], dropna=False)["area_ha"].transform("median")
    return df[df["area_ha"] < ratio * med]


def year_scale_flags(df, share=0.5, ratio=0.1):
    """Years where more than `share` of district-crop series look scaled wrong at once."""
    flagged = area_scale_flags(df, ratio)
    per_year = flagged.groupby("year").size() / df.groupby("year").size()
    return per_year[per_year > share].sort_index()


def combine(old, new, tolerance=0.05):
    """Stack two standardised tables without overwriting.

    Returns (combined, conflicts). Rows for the same district-crop-season-year in both are kept
    from `old`; a conflict row is reported when their yields differ by more than `tolerance`.
    """
    key = ["district", "crop", "season", "year"]
    both = old.merge(new, on=key, suffixes=("_old", "_new"))
    rel = (both["yield_t_ha_old"] - both["yield_t_ha_new"]).abs() / both["yield_t_ha_old"]
    conflicts = both[rel > tolerance]
    new_only = new.merge(old[key], on=key, how="left", indicator=True)
    new_only = new_only[new_only["_merge"] == "left_only"].drop(columns="_merge")
    return pd.concat([old, new_only], ignore_index=True), conflicts
