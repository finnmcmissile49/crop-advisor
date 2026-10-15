"""FAO-56 Penman-Monteith reference evapotranspiration (ET0), daily time step.

Reference: Allen et al. (1998), FAO Irrigation and Drainage Paper 56.
All inputs may be floats or numpy arrays / pandas Series.
"""
import numpy as np
import pandas as pd


def sat_vapour_pressure(t_c):
    """Saturation vapour pressure (kPa) at air temperature t_c (deg C). FAO-56 eq. 11."""
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(lat_deg, doy):
    """Extraterrestrial radiation Ra (MJ m-2 day-1). FAO-56 eq. 21."""
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws)
    )


def wind_10m_to_2m(u10):
    """Convert wind speed measured at 10 m to 2 m. FAO-56 eq. 47."""
    return u10 * 4.87 / np.log(67.8 * 10 - 5.42)


def et0_penman_monteith(tmax, tmin, rh_mean, u2, rs, lat_deg, elev_m, doy, ea=None):
    """Daily ET0 in mm/day.

    tmax, tmin : deg C
    rh_mean    : mean relative humidity, percent
    u2         : wind speed at 2 m height, m/s
    rs         : incoming solar radiation, MJ m-2 day-1
    lat_deg    : latitude in degrees (north positive)
    elev_m     : elevation above sea level, m
    doy        : day of year (1-366)
    ea         : optional actual vapour pressure (kPa); if None it is derived from rh_mean
    """
    tmean = (tmax + tmin) / 2
    pressure = 101.3 * ((293 - 0.0065 * elev_m) / 293) ** 5.26
    gamma = 0.000665 * pressure
    delta = 4098 * sat_vapour_pressure(tmean) / (tmean + 237.3) ** 2

    es = (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2
    if ea is None:
        ea = rh_mean / 100 * es

    ra = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * elev_m) * ra
    rs_rso = np.clip(rs / rso, 0.3, 1.0)
    rns = (1 - 0.23) * rs
    rnl = 4.903e-9 * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) * (
        0.34 - 0.14 * np.sqrt(ea)
    ) * (1.35 * rs_rso - 0.35)
    rn = rns - rnl

    num = 0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return num / den


def add_et0(df, lat_deg, elev_m, col="et0_calc_mm"):
    """Add a computed ET0 column to a harmonised daily weather DataFrame.

    Needs columns: date, tmax, tmin, rh_mean, wind_2m_ms, solar_mj.
    """
    out = df.copy()
    doy = pd.to_datetime(out["date"]).dt.dayofyear.to_numpy()
    out[col] = et0_penman_monteith(
        out["tmax"].to_numpy(float), out["tmin"].to_numpy(float),
        out["rh_mean"].to_numpy(float), out["wind_2m_ms"].to_numpy(float),
        out["solar_mj"].to_numpy(float), lat_deg, elev_m, doy,
    )
    return out
