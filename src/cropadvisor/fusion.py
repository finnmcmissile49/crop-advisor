"""Sensor fusion: a Kalman filter that combines the farm station's soil moisture readings with the
FAO-56 water balance, for a better estimate of the root-zone water than either alone.

State: root-zone depletion Dr (mm below field capacity), as in the water balance.
Each day:
  1. Predict with the same FAO-56 step the calculator uses (crop water use, rain, irrigation,
     drainage). Station rain replaces public rain on days the farm gauge recorded it.
     The prediction's uncertainty grows by Q: Q_ETC_FRAC of the day's crop water use, Q_RAIN_FRAC
     of the rain, Q_IRR_FRAC of any irrigation (the farmer's flood depth is not measured), plus a
     small floor.
  2. Update with the sensors, if any valid reading: the two depths are averaged over the root
     zone (the shallow sensor stands for the top 30 cm, the deep one for the rest), turned into
     depletion with the soil's field capacity, and combined with the prediction in proportion to
     their uncertainties (Kalman gain). Sensor uncertainty R: SENSOR_SD m3/m3 per sensor (a
     typical figure for a field-calibrated capacitance probe, our assumption until the station is
     calibrated against oven-dried samples, groundtruth.py); larger when only one sensor works.
     A reading more than GATE_SD standard deviations from the prediction is rejected as an outlier.
  3. No valid reading (sensor failed, station off): the filter keeps going on the prediction,
     and its uncertainty grows until readings return.

All the uncertainty figures are our starting assumptions. They should be set from the station's
own calibration (sensor against oven-dried samples) and from the first season's data.

The result is a daily table (model-only, fused, uncertainty, readings, what was rejected) and the
correction that brings the calculator's water balance to the fused value at the end of yesterday.
advisor.advise applies it as an adjustment to that day's water input, so every advice rule (all
crops, rain wait, soil range) works from the fused soil water.
"""
from dataclasses import replace

import numpy as np
import pandas as pd

from cropadvisor import irrigation as ir

Q_ETC_FRAC = 0.20
Q_RAIN_FRAC = 0.20
Q_IRR_FRAC = 0.25
Q_FLOOR_MM = 0.5
SENSOR_SD = 0.03          # m3/m3, each sensor (assumption until calibrated)
SINGLE_SENSOR_SD = 0.045  # m3/m3, one sensor standing for the whole root zone
TOP_LAYER_M = 0.30
GATE_SD = 3.0
P0_MM2 = 4.0              # start: field capacity after the pre-sowing irrigation, +-2 mm


def root_zone_theta(sm_top, sm_deep, zr):
    """Volumetric water over the root zone from the two sensors, and its standard deviation."""
    top_ok, deep_ok = not pd.isna(sm_top), not pd.isna(sm_deep)
    if top_ok and deep_ok:
        w_top = min(TOP_LAYER_M, zr) / zr
        theta = w_top * sm_top + (1 - w_top) * sm_deep
        sd = SENSOR_SD * np.sqrt(w_top ** 2 + (1 - w_top) ** 2)
        return theta, sd, "both"
    if top_ok or deep_ok:
        return (sm_top if top_ok else sm_deep), SINGLE_SENSOR_SD, ("top" if top_ok else "deep")
    return None, None, None


def run(weather, sowing, today, params, watered, depth_mm, readings, field_capacity):
    """Kalman filter from sowing to the end of `today - 1`. Returns (daily DataFrame, correction).

    weather: date, rain_mm, et0_mm (+ rh_min, wind_2m_ms); params: CropParams (likely soil);
    watered: irrigation dates; depth_mm: fixed depth or None (refill to field capacity);
    readings: station.daily output or None; field_capacity: m3/m3.
    correction: {"date", "mm", ...}: water to add on that day (negative: remove) so the
    calculator's own water balance ends the day at the fused depletion.
    """
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    last = today - pd.Timedelta(days=1)
    w = weather[(weather["date"] >= sowing) & (weather["date"] <= last)].copy()
    if w.empty:
        return None, None
    cols = [c for c in ("date", "rain_mm", "et0_mm", "rh_min", "wind_2m_ms") if c in w]
    full = weather[weather["date"] >= sowing][cols]   # same climate window as the calculator
    p, _ = ir.climate_adjusted_kc(params, full)
    if p.kc_ini_wetting:
        p = replace(p, kc_ini=ir.kc_ini_from_wetting(p, full))
    rd = readings.set_index("date") if readings is not None and len(readings) else None
    wat = {pd.Timestamp(d) for d in watered}
    x = x_open = 0.0
    P = P0_MM2
    rows = []
    for das, r in enumerate(w.itertuples(index=False)):
        date = pd.Timestamp(r.date)
        kc, zr = p.kc(das), p.root_depth(das)
        taw = p.awc_mm_per_m * zr
        etc = kc * r.et0_mm
        pp = float(np.clip(p.p_table + 0.04 * (5 - etc), 0.1, 0.8)) if p.adjust_p else p.p_table
        raw = pp * taw
        rain_public = float(r.rain_mm)
        rain = rain_public
        st = rd.loc[date] if rd is not None and date in rd.index else None
        if st is not None and not pd.isna(st["rain_mm"]):
            rain = float(st["rain_mm"])

        def step(dr, rain_mm):
            dr = min(dr, taw)
            irr = 0.0
            if date in wat:
                irr = dr if depth_mm is None else float(depth_mm)
            start = max(dr - irr, 0.0)
            ks = 1.0 if start <= raw else float(np.clip((taw - start) / ((1 - pp) * taw), 0, 1))
            new = dr - rain_mm - irr + ks * etc
            return float(np.clip(new, 0.0, taw)), irr

        x_open, _ = step(x_open, rain_public)          # the calculator's own model, no station
        x_pred, irr = step(x, rain)
        P_pred = P + (Q_ETC_FRAC * etc) ** 2 + (Q_RAIN_FRAC * rain) ** 2 + \
            (Q_IRR_FRAC * irr) ** 2 + Q_FLOOR_MM ** 2
        row = {"date": date, "das": das, "taw_mm": taw, "raw_mm": raw, "dr_model_mm": x_open,
               "dr_pred_mm": x_pred, "rain_used_mm": rain, "station_rain": rain != rain_public,
               "z_mm": np.nan, "sensors": None, "gain": 0.0, "rejected": False}
        theta, sd, which = (root_zone_theta(st["sm_top"], st["sm_deep"], zr)
                            if st is not None else (None, None, None))
        x, P = x_pred, P_pred
        if theta is not None:
            z = float(np.clip((field_capacity - theta) * zr * 1000.0, 0.0, taw))
            R = (sd * zr * 1000.0) ** 2
            S = P_pred + R
            nu = z - x_pred
            row.update(z_mm=z, sensors=which)
            if abs(nu) > GATE_SD * np.sqrt(S):
                row["rejected"] = True
            else:
                K = P_pred / S
                x = float(np.clip(x_pred + K * nu, 0.0, taw))
                P = (1 - K) * P_pred
                row["gain"] = K
        row.update(dr_fused_mm=x, sd_mm=float(np.sqrt(P)))
        rows.append(row)
    out = pd.DataFrame(rows)
    end = out.iloc[-1]
    # Water to add on the last day so the open-loop balance ends at the fused value. The model's
    # own last day used public rain; station rain differences are part of the correction.
    corr = {"date": end["date"], "mm": round(float(end["dr_model_mm"] - end["dr_fused_mm"]), 2),
            "dr_model_mm": round(float(end["dr_model_mm"]), 1),
            "dr_fused_mm": round(float(end["dr_fused_mm"]), 1),
            "sd_mm": round(float(end["sd_mm"]), 1), "taw_mm": round(float(end["taw_mm"]), 1)}
    return out, corr


def summary(out, readings, report=None):
    """What the station contributed, for the advice text and JSON."""
    used = out[out["sensors"].notna() & ~out["rejected"]]
    last_reading = None
    if readings is not None and len(readings):
        r = readings.dropna(subset=["sm_top", "sm_deep"], how="all")
        last_reading = r["date"].max() if len(r) else None
    return {"days_with_readings": int(out["sensors"].notna().sum()),
            "days_used": int(len(used)), "days_rejected": int(out["rejected"].sum()),
            "days_station_rain": int(out["station_rain"].sum()),
            "last_reading": last_reading, "checks_failed": report or {}}
