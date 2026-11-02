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
                  "offset": page * page_size, "filters[state]": state}
        if commodity:
            params["filters[commodity]"] = commodity
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


def _norm_commodity(name):
    return "".join(str(name).lower().split())


def live_price(commodity, state, district=None, api_key=None, days=7, fetch=None, today=None):
    """Latest modal mandi price (Rs/quintal) from data.gov.in's daily Agmarknet feed: the mean
    over the district's (else the state's) markets of the most recent `days` days in the feed.
    Needs a free API key (environment variable DATA_GOV_IN_KEY). Returns None without a key,
    when the feed has nothing for the crop, or when it cannot be reached (its server is slow and
    refuses some networks; see scripts/fetch_prices_local.py)."""
    import os
    api_key = api_key or os.environ.get("DATA_GOV_IN_KEY")
    if not api_key and fetch is None:
        return None
    # the whole state's feed, matched on names without spaces (CEDA and data.gov.in space
    # Agmarknet's commodity names differently, e.g. "Bengal Gram (Gram)(Whole)")
    fetch = fetch or (lambda c: _state_feed(api_key, state))
    try:
        df = fetch(commodity)
    except Exception:
        return None
    if df is None or df.empty or "modal_price" not in df:
        return None
    df = clean(df) if "arrival_date" in df and df["arrival_date"].dtype == object else df
    if "commodity" in df:
        df = df[df["commodity"].map(_norm_commodity) == _norm_commodity(commodity)]
    if "state" in df:
        df = df[df["state"].str.lower() == str(state).lower()]
    if df.empty:
        return None
    level = "state"
    if district and "district" in df:
        d = df[df["district"].str.lower() == str(district).lower()]
        if len(d):
            df, level = d, "district"
    latest = df["arrival_date"].max()
    recent = df[df["arrival_date"] > latest - pd.Timedelta(days=days)]
    return {"price": round(float(recent["modal_price"].mean())), "date": latest,
            "markets": int(recent["market"].nunique()) if "market" in recent else None,
            "level": level, "source": "data.gov.in (Agmarknet daily)"}


_FEED_CACHE = {}


def _state_feed(api_key, state):
    """One download of a state's current daily feed per run (all crops)."""
    import datetime as dt
    key = (state, dt.date.today())
    if key not in _FEED_CACHE:
        _FEED_CACHE[key] = fetch_prices(api_key, None, state=state, max_pages=20)
    return _FEED_CACHE[key]
