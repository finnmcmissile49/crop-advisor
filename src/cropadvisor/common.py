"""Shared helpers: HTTP with retries, raw-response saving."""
import json
import os
import time

import requests


def http_get_json(url, params, retries=3, timeout=60, raw_path=None):
    """GET a JSON API with simple retry/backoff. Optionally save the raw response to disk."""
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if raw_path:
                os.makedirs(os.path.dirname(raw_path), exist_ok=True)
                with open(raw_path, "w") as f:
                    json.dump(data, f)
            return data
        except Exception as e:  # network error, 429, bad JSON
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Request failed after {retries} tries: {url} ({last_err})")
