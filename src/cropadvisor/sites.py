"""Build the Site (district, soil, location) for one field. Shared by the calculator script and
the web service.

Soil water-holding, in order of preference:
1. The field's own point (--lat/--lon): SoilGrids at that point, fetched live and cached.
2. The district's value from data/soil_awc.csv (committed) or the data pull's soil.csv.
A soil type the farmer gives (sandy / light loam / loam / clay) then sets the range of the advice
(advisor.SOIL_TYPES, FAO-56 Table 19).
"""
import math
import os

import pandas as pd

from cropadvisor import advisor
from cropadvisor import soil as sg

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
LOCATIONS = os.path.join(ROOT, "data", "locations_wheat_10states.csv")
SOIL_FILES = (os.path.join(ROOT, "data_10states", "processed", "soil.csv"),
              os.path.join(ROOT, "data", "soil_awc.csv"))
FIELD_SOIL_CACHE = os.path.join(ROOT, "data", "raw", "soilgrids_fields")
FAR_KM = 60   # a field further than this from the district point is probably in another district


def distance_km(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def district_row(name, locations=LOCATIONS):
    loc = pd.read_csv(locations)
    match = loc[loc["name"].str.lower() == str(name).strip().lower()]
    if match.empty:
        raise advisor.AdviceError(f"'{name}' is not one of the {len(loc)} districts set up. "
                                  "Run with --list to see them.")
    return match.iloc[0]


def district_awc(name, soil_files=SOIL_FILES):
    for path in soil_files:
        if os.path.exists(path):
            s = pd.read_csv(path).set_index("name")
            if name in s.index and not pd.isna(s.loc[name, "awc_mm_per_m"]):
                return float(s.loc[name, "awc_mm_per_m"])
    raise advisor.AdviceError(f"No soil data for {name}. Run the 10-state data pull first (see "
                              "README).")


def field_awc(lat, lon, fetch=None):
    """SoilGrids water-holding at the field (nearest point with soil data within 10 km)."""
    fetch = fetch or (lambda la, lo: sg.fetch_nearest_soil(la, lo, FIELD_SOIL_CACHE,
                                                           f"field_{la:.4f}_{lo:.4f}"))
    long_df, plat, plon, dist = fetch(lat, lon)
    return sg.soil_summary(long_df)["awc_mm_per_m"], dist


def build_site(district, lat=None, lon=None, soil_type=None, locations=LOCATIONS,
               soil_files=SOIL_FILES, fetch_soil=None):
    """Returns (Site, notes). notes: list of (code, English, Hindi) shown with the advice."""
    row = district_row(district, locations)
    notes = []
    if soil_type is not None and soil_type not in advisor.SOIL_TYPES:
        raise advisor.AdviceError(f"Soil type must be one of: {', '.join(advisor.SOIL_TYPES)}.")
    site = advisor.Site(name=row["name"], state=row["state"], zone=row["zone"],
                        awc_mm_per_m=None, lat=float(row["lat"]), lon=float(row["lon"]),
                        soil_type=soil_type)
    if (lat is None) != (lon is None):
        raise advisor.AdviceError("Give both latitude and longitude for the field, or neither.")
    if lat is not None:
        lat, lon = float(lat), float(lon)
        if not (6 <= lat <= 37 and 68 <= lon <= 98):
            raise advisor.AdviceError(f"The field location ({lat}, {lon}) is not in India.")
        d = distance_km(site.lat, site.lon, lat, lon)
        if d > FAR_KM:
            raise advisor.AdviceError(f"The field is {d:.0f} km from {site.name}'s centre. "
                                      "Check the district or the location.")
        site.lat, site.lon = lat, lon
        try:
            awc, dist = field_awc(lat, lon, fetch_soil)
            site.awc_mm_per_m, site.soil_source = float(awc), "field"
            notes.append(("field", "Weather and soil are for your field's location.",
                          "मौसम और मिट्टी आपके खेत की जगह के हैं।"))
        except Exception:   # SoilGrids down or no soil nearby: use the district value
            notes.append(("field_soil_failed",
                          "Weather is for your field's location; the soil map could not be "
                          "reached, so the district's soil is used.",
                          "मौसम आपके खेत की जगह का है; मिट्टी का नक्शा नहीं मिला, इसलिए ज़िले की "
                          "मिट्टी ली गई है।"))
    if site.awc_mm_per_m is None:
        site.awc_mm_per_m = district_awc(site.name, soil_files)
    if soil_type:
        t = advisor.SOIL_TYPES[soil_type]
        notes.append(("soil_type", f"Soil: {t['en']} (as you said).",
                      f"मिट्टी: {t['hi']} (आपके बताए अनुसार)।"))
    return site, notes
