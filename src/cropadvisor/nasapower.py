"""NASA POWER daily fetcher, returning the same harmonised columns as the Open-Meteo module
(minus ET0, which POWER does not provide).

Harmonised columns: date, tmax, tmin, rain_mm, solar_mj, rh_mean, wind_2m_ms
No API key needed. POWER data lags real time by a few days.
"""
import pandas as pd

from cropadvisor.common import http_get_json

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN"]


def fetch_history(lat, lon, start, end, raw_path=None):
    """Daily history. start/end as 'YYYY-MM-DD'."""
    params = {"parameters": ",".join(PARAMS), "community": "AG",
              "latitude": lat, "longitude": lon,
              "start": start.replace("-", ""), "end": end.replace("-", ""),
              "format": "JSON"}
    data = http_get_json(POWER_URL, params, raw_path=raw_path)
    p = data["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.replace(-999, float("nan"))  # POWER's missing-data flag
    df = df.rename(columns={"T2M_MAX": "tmax", "T2M_MIN": "tmin", "PRECTOTCORR": "rain_mm",
                            "RH2M": "rh_mean", "WS2M": "wind_2m_ms",
                            "ALLSKY_SFC_SW_DWN": "solar_mj"})
    return df[["date", "tmax", "tmin", "rain_mm", "solar_mj", "rh_mean", "wind_2m_ms"]]
