"""Mandi prices from data.gov.in (step 7).

NEEDS A FREE API KEY. Register at https://data.gov.in, copy your key, and store it as a Colab
secret named DATA_GOV_IN_KEY (key icon in Colab's left sidebar). Never paste it into code.

Untested against the live API: written to the documented response format. The default resource
("Current daily price of various commodities from various markets") only holds recent days, so
this builds history going forward; older history needs Agmarknet report downloads.
"""
import pandas as pd

from cropadvisor.common import http_get_json

API = "https://api.data.gov.in/resource/{rid}"
RESOURCE_CURRENT = "9ef84268-d588-465a-a308-a864a43d0070"

# Commodity names as Agmarknet spells them, for the five project crops
COMMODITIES = {
    "soybean": "Soyabean",
    "cotton": "Cotton",
    "tur": "Arhar (Tur/Red Gram)(Whole)",
    "jowar": "Jowar(Sorghum)",
    "gram": "Bengal Gram(Gram)(Whole)",
}


def fetch_prices(api_key, commodity, state="Maharashtra", resource_id=RESOURCE_CURRENT,
                 page_size=1000, max_pages=20):
    rows = []
    for page in range(max_pages):
        params = {"api-key": api_key, "format": "json", "limit": page_size,
                  "offset": page * page_size, "filters[state]": state,
                  "filters[commodity]": commodity}
        data = http_get_json(API.format(rid=resource_id), params, use_cache=False)
        recs = data.get("records", [])
        rows.extend(recs)
        if len(recs) < page_size:
            break
    return clean(pd.DataFrame(rows))


def clean(df):
    """Lower-case column names, parse dates and Rs/quintal prices, drop exact duplicates."""
    if df.empty:
        return df
    df = df.rename(columns=lambda c: c.strip().lower())
    if "arrival_date" in df:
        df["arrival_date"] = pd.to_datetime(df["arrival_date"], dayfirst=True, errors="coerce")
    for c in ("min_price", "max_price", "modal_price"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates()
    bad = df["modal_price"].le(0) | (df["min_price"] > df["max_price"])
    return df[~bad.fillna(False)].reset_index(drop=True)
