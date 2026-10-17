"""Download today's mandi prices for ALL states from data.gov.in. Run this on your own computer.

Why locally: data.gov.in refuses connections from Google Colab (foreign cloud addresses), but works
from an ordinary Indian home or school connection.

What it does:
  1. Reads your API key from the environment variable DATA_GOV_IN_KEY, or asks for it with the
     typing hidden (so it never appears on screen or in a file).
  2. Downloads every record in the "current daily price" feed, 1000 rows at a time.
  3. Saves prices_out/prices_YYYY-MM-DD.csv (this run) and merges it into prices_out/prices_all.csv
     (all runs so far, duplicates removed).

The feed only holds the most recent days, so history builds up one run at a time. Run it daily
(or at least weekly) and keep prices_all.csv. Older history needs Agmarknet report downloads.

Needs: Python 3.9+ and  pip install requests pandas
"""
import datetime as dt
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
PAGE = 200                # small pages: the server is slow with big ones
TIMEOUT = (15, 180)       # connect, read (seconds)
OUT = Path("prices_out")


def get_page(key, offset, retries=5, limit=None):
    params = {"api-key": key, "format": "json", "limit": limit or PAGE, "offset": offset}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code} at offset {offset} (attempt {attempt})")
            if r.status_code in (401, 403):
                sys.exit("The API rejected the key. Check DATA_GOV_IN_KEY is copied in full.")
        except requests.RequestException as e:
            print(f"  {type(e).__name__} at offset {offset} (attempt {attempt})")
        time.sleep(5 * attempt)
    return None


def clean(df):
    """Lower-case columns, parse dates and prices, drop duplicates and impossible rows."""
    df = df.rename(columns=lambda c: c.strip().lower())
    if "arrival_date" in df:
        df["arrival_date"] = pd.to_datetime(df["arrival_date"], dayfirst=True, errors="coerce")
    for c in ("min_price", "max_price", "modal_price"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates()
    if {"modal_price", "min_price", "max_price"} <= set(df.columns):
        bad = df["modal_price"].le(0) | (df["min_price"] > df["max_price"])
        df = df[~bad.fillna(False)]
    return df.reset_index(drop=True)


def download(key):
    rows, offset, total = [], 0, None
    print("Checking the connection with a 1-row request...")
    probe = get_page(key, 0, limit=1)
    if probe is None:
        sys.exit("The server did not answer. Try again in 10-15 minutes, or on another network "
                 "(for example your phone's hotspot).")
    print("Connected.")
    while True:
        data = get_page(key, offset)
        if data is None:
            print(f"Stopped at offset {offset}; keeping the {len(rows)} rows already downloaded.")
            break
        if total is None:
            total = int(data.get("total", 0))
            print(f"Feed reports {total} records.")
        recs = data.get("records", [])
        rows.extend(recs)
        print(f"  got {len(rows)} / {total}")
        if len(recs) < PAGE or (total and len(rows) >= total):
            break
        offset += PAGE
        time.sleep(0.5)
    return pd.DataFrame(rows)


def merge_into_all(today_df, path):
    if path.exists():
        old = pd.read_csv(path, parse_dates=["arrival_date"])
        today_df = pd.concat([old, today_df], ignore_index=True)
    key_cols = [c for c in ("state", "district", "market", "commodity", "variety", "grade",
                            "arrival_date") if c in today_df.columns]
    return today_df.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)


def main():
    key = os.environ.get("DATA_GOV_IN_KEY", "").strip()
    if not key:
        import getpass
        key = getpass.getpass("Paste your data.gov.in API key (it stays hidden), then Enter: ").strip()
    if not key:
        sys.exit("No key entered.")
    OUT.mkdir(exist_ok=True)
    raw = download(key)
    if raw.empty:
        sys.exit("The feed returned no records.")
    df = clean(raw)
    today_file = OUT / f"prices_{dt.date.today().isoformat()}.csv"
    df.to_csv(today_file, index=False)
    allf = OUT / "prices_all.csv"
    merged = merge_into_all(df, allf)
    merged.to_csv(allf, index=False)
    print(f"\nSaved {len(df)} rows to {today_file}")
    print(f"prices_all.csv now has {len(merged)} rows, {merged['state'].nunique()} states, "
          f"{merged['commodity'].nunique()} commodities, dates "
          f"{merged['arrival_date'].min().date()} to {merged['arrival_date'].max().date()}")


if __name__ == "__main__":
    main()
