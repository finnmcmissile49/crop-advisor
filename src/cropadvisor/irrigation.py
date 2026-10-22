"""FAO-56 root-zone soil water balance for wheat, and two irrigation advice rules.

This is the public-data-only irrigation baseline. It is a physics-based reference rule, not a
model trained on data, and there is no ground truth for "correct" irrigation in our districts
(see claude/ml-limitations.md section 4).

Daily balance, FAO-56 eq. 85 and 86 (runoff and capillary rise taken as zero):
    Dr[i] = Dr[i-1] - rain[i] - irrigation[i] + ETa[i] + DP[i],   0 <= Dr[i] <= TAW[i]
    TAW = AWC (mm per m) x Zr                                       (eq. 82)
    RAW = p x TAW,  p = p_table + 0.04 (5 - ETc), 0.1 <= p <= 0.8     (eq. 83 and Table 22 note)
    Ks  = (TAW - Dr) / ((1 - p) TAW) when Dr > RAW, else 1           (eq. 84, checked against
                                                                      FAO-56 Example 37)
    ETa = Ks x Kc x ET0                                              (eq. 81)

Dr is the root-zone depletion in mm: 0 means the root zone is at field capacity.

Assumptions (each is a stress-test input, see irrigation_eval.py):
- The whole profile is at field capacity at sowing (PAU: heavy 10 cm pre-sowing irrigation).
- Soil below the current root depth stays at field capacity, so root growth adds full soil and
  does not change Dr.
- Roots grow linearly from zr_ini at sowing to zr_max at the start of mid-season. FAO-56 gives
  no general growth rule; this is our choice.
- FAO-56 stage lengths for wheat (Central India, November sowing, 120 days) are stretched in
  proportion to the Punjab season length (PAU varieties mature in about 145 to 158 days).
- No runoff, no capillary rise from groundwater. Excess water drains as deep percolation (DP).
- The Kc climate adjustment (FAO-56 eq. 62) is not applied: it needs daily minimum humidity,
  which the pipeline does not keep.
"""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

# FAO-56 Table 11, Barley/Oats/Wheat, Central India, November planting: 15, 25, 50, 30 days
FAO_STAGE_DAYS = (15, 25, 50, 30)


@dataclass(frozen=True)
class WheatParams:
    """Crop and soil numbers for one run. Each value notes where it comes from."""
    awc_mm_per_m: float                 # SoilGrids + Saxton-Rawls (soil.py), a model estimate
    season_days: int = 152              # PAU Rabi 2025-26: timely-sown varieties 145-158 days
    stage_days_fao: tuple = FAO_STAGE_DAYS  # FAO-56 Table 11, stretched to season_days
    kc_ini: float = 0.3                 # FAO-56 Table 12, cereals group value
    kc_mid: float = 1.15                # FAO-56 Table 12, wheat
    kc_end: float = 0.25                # FAO-56 Table 12: 0.25, higher value 0.4 is hand harvest
    zr_ini: float = 0.2                 # assumption: rooting depth at sowing (m)
    zr_max: float = 1.0                 # FAO-56 Table 22 spring wheat 1.0-1.5 m; soil data stop at 1 m
    p_table: float = 0.55               # FAO-56 Table 22, wheat
    adjust_p: bool = True               # FAO-56 Table 22 footnote: p = p + 0.04 (5 - ETc)

    def stage_lengths(self):
        """FAO stage lengths stretched to season_days, as integers that add up exactly."""
        fao = np.array(self.stage_days_fao, float)
        edges = np.round(np.cumsum(fao) / fao.sum() * self.season_days).astype(int)
        return tuple(int(x) for x in np.diff(np.concatenate([[0], edges])))

    def kc(self, das):
        """Single crop coefficient on day-after-sowing das (FAO-56 Figure 25 shape)."""
        l_ini, l_dev, l_mid, l_late = self.stage_lengths()
        if das < l_ini:
            return self.kc_ini
        if das < l_ini + l_dev:
            return self.kc_ini + (das - l_ini) / l_dev * (self.kc_mid - self.kc_ini)
        if das < l_ini + l_dev + l_mid:
            return self.kc_mid
        t = (das - l_ini - l_dev - l_mid) / l_late
        return self.kc_mid + min(t, 1.0) * (self.kc_end - self.kc_mid)

    def root_depth(self, das):
        """Effective rooting depth (m), linear to zr_max at the start of mid-season."""
        l_ini, l_dev, _, _ = self.stage_lengths()
        grow = l_ini + l_dev
        return self.zr_ini + min(das / grow, 1.0) * (self.zr_max - self.zr_ini)

    def stage(self, das):
        l_ini, l_dev, l_mid, _ = self.stage_lengths()
        for name, end in (("initial", l_ini), ("development", l_ini + l_dev),
                          ("mid", l_ini + l_dev + l_mid)):
            if das < end:
                return name
        return "late"


def _rabi_date(sowing, month, day):
    """The date month/day inside the rabi season that contains `sowing` (July to June)."""
    start_year = sowing.year if sowing.month >= 7 else sowing.year - 1
    return pd.Timestamp(start_year if month >= 7 else start_year + 1, month, day)


def last_irrigation_date(sowing):
    """PAU Rabi 2025-26: irrigate the timely-sown crop until the end of March if needed; for crops
    sown after 5 December, until 10 April."""
    sowing = pd.Timestamp(sowing)
    if sowing <= _rabi_date(sowing, 12, 5):
        return _rabi_date(sowing, 3, 31)
    return _rabi_date(sowing, 4, 10)


# ---------------------------------------------------------------------------------- rules

class FaoTriggerRule:
    """Irrigate when the root-zone depletion reaches the readily available water (Dr >= RAW).

    mode "refill" applies exactly the depletion (back to field capacity, the FAO-56 textbook rule);
    mode "fixed" applies depth_mm every time, like a farmer flooding a field.
    """
    name = "fao_trigger"

    def __init__(self, mode="refill", depth_mm=75.0):
        self.mode, self.depth_mm = mode, depth_mm

    def start(self, sowing, params):
        self.cutoff = last_irrigation_date(sowing)

    def decide(self, date, das, dr_prev, raw, taw):
        if date > self.cutoff or dr_prev < raw:
            return 0.0
        return dr_prev if self.mode == "refill" else self.depth_mm

    def observe_rain(self, date, rain_mm):
        pass


# PAU Rabi 2025-26, wheat irrigation table: weeks after the previous irrigation for the 2nd, 3rd
# and 4th irrigation, by sowing date. Ranges such as "5-6" use the midpoint.
PAU_INTERVAL_WEEKS = (
    ((11, 21), (5.5, 5.5, 4.0)),   # sown up to 21 November
    ((12, 20), (5.5, 3.5, 2.0)),   # 22 November to 20 December
    ((1, 15), (4.0, 3.0, 2.0)),    # 21 December to 15 January
)


class PauCalendarRule:
    """Punjab Agricultural University calendar schedule, with its rain adjustment.

    First irrigation 3 weeks after sowing for October sowing, 4 weeks for later sowing; then the
    intervals in PAU_INTERVAL_WEEKS. For each cm of rain, the next irrigation moves 5 days later
    up to the end of January and 2 days later after that. 7.5 cm per irrigation. The soil-type
    adjustment (one week earlier on light soils, later on heavy paddy soils) is not applied: all
    six pilot soils are loam or clay loam, the "sandy loam or heavier" case the table is for.
    """
    name = "pau_calendar"

    def __init__(self, depth_mm=75.0):
        self.depth_mm = depth_mm

    def start(self, sowing, params):
        sowing = pd.Timestamp(sowing)
        self.sowing, self.cutoff = sowing, last_irrigation_date(sowing)
        self.intervals = self._intervals(sowing)
        first_weeks = 3 if sowing.month == 10 else 4
        self.n_done, self.push_days = 0, 0.0
        self.base_due = sowing + pd.Timedelta(days=round(first_weeks * 7))

    @staticmethod
    def _intervals(sowing):
        for (m, d), weeks in PAU_INTERVAL_WEEKS:
            if sowing <= _rabi_date(sowing, m, d):
                return [int(w * 7 + 0.5) for w in weeks]
        raise ValueError(f"PAU schedule has no row for sowing on {sowing.date()}")

    def due_date(self):
        if self.n_done > len(self.intervals):
            return None
        return self.base_due + pd.Timedelta(days=int(round(self.push_days)))

    def decide(self, date, das, dr_prev, raw, taw):
        due = self.due_date()
        if due is None or date > self.cutoff or date < due:
            return 0.0
        self.n_done += 1
        if self.n_done <= len(self.intervals):
            self.base_due = date + pd.Timedelta(days=self.intervals[self.n_done - 1])
            self.push_days = 0.0
        return self.depth_mm

    def observe_rain(self, date, rain_mm):
        if self.due_date() is None or not rain_mm > 0:
            return
        per_cm = 5 if (date.month == 1 or date.month >= 7) else 2   # up to end of January
        self.push_days += rain_mm / 10 * per_cm


# ---------------------------------------------------------------------------------- engine

def season_inputs(daily, name, sowing, season_days, rain_src="imd", et0_src="om"):
    """Daily rain and ET0 for one district from sowing for season_days, from the pipeline table.

    Refuses to run on a gap or a missing value instead of guessing.
    """
    sowing = pd.Timestamp(sowing)
    dates = pd.date_range(sowing, periods=season_days)
    d = daily[daily["name"] == name].set_index("date").reindex(dates)
    out = pd.DataFrame({"date": dates, "rain_mm": d[f"rain_{rain_src}"].to_numpy(float),
                        "et0_mm": d[f"et0_{et0_src}"].to_numpy(float)})
    bad = out[["rain_mm", "et0_mm"]].isna().any(axis=1)
    if bad.any():
        raise ValueError(f"{name}: {int(bad.sum())} days without rain_{rain_src} or et0_{et0_src} "
                         f"(first {out.loc[bad, 'date'].iloc[0].date()})")
    return out


def simulate(inputs, sowing, params, rule, dr0=0.0):
    """Run the daily balance. inputs: DataFrame with date, rain_mm, et0_mm from the sowing day.

    Returns one row per day. Irrigation is applied at the start of the day it is decided.
    """
    rule.start(sowing, params)
    rows, dr_prev = [], float(dr0)
    for das, r in enumerate(inputs.itertuples(index=False)):
        date = pd.Timestamp(r.date)
        kc, zr = params.kc(das), params.root_depth(das)
        taw = params.awc_mm_per_m * zr
        etc = kc * r.et0_mm
        p = float(np.clip(params.p_table + 0.04 * (5 - etc), 0.1, 0.8)) if params.adjust_p \
            else params.p_table
        raw = p * taw
        dr_prev = min(dr_prev, taw)  # only matters if a caller starts with dr0 > TAW
        irr = float(rule.decide(date, das, dr_prev, raw, taw))
        rule.observe_rain(date, r.rain_mm)

        dr_start = max(dr_prev - irr, 0.0)
        ks = 1.0 if dr_start <= raw else (taw - dr_start) / ((1 - p) * taw)
        ks = float(np.clip(ks, 0.0, 1.0))
        eta = ks * etc
        dr = dr_prev - r.rain_mm - irr + eta
        dp = 0.0
        if dr < 0:
            dp, dr = -dr, 0.0
        if dr > taw:  # cannot dry beyond the wilting point: cut ETa, keep the books balanced
            eta -= dr - taw
            dr = taw
        rows.append({"date": date, "das": das, "stage": params.stage(das), "kc": kc, "zr_m": zr,
                     "taw_mm": taw, "p": p, "raw_mm": raw, "et0_mm": r.et0_mm, "etc_mm": etc,
                     "ks": ks, "eta_mm": eta, "rain_mm": r.rain_mm, "irrigation_mm": irr,
                     "dp_mm": dp, "dr_mm": dr})
        dr_prev = dr
    return pd.DataFrame(rows)


def summarise(run, dr0=0.0):
    """Season totals for one run, including the water-balance closure error (should be ~0)."""
    irr = run[run["irrigation_mm"] > 0]
    closure = (run["dr_mm"].iloc[-1] - dr0) - (run["eta_mm"].sum() + run["dp_mm"].sum()
                                               - run["rain_mm"].sum() - run["irrigation_mm"].sum())
    return {
        "n_irrigations": len(irr),
        "irrigation_dates": ";".join(d.strftime("%Y-%m-%d") for d in irr["date"]),
        "irrigation_das": ";".join(str(x) for x in irr["das"]),
        "irrigation_mm": round(run["irrigation_mm"].sum(), 1),
        "rain_mm": round(run["rain_mm"].sum(), 1),
        "etc_mm": round(run["etc_mm"].sum(), 1),
        "eta_mm": round(run["eta_mm"].sum(), 1),
        "eta_over_etc": round(run["eta_mm"].sum() / run["etc_mm"].sum(), 3),
        "deep_percolation_mm": round(run["dp_mm"].sum(), 1),
        "stress_days": int((run["ks"] < 1).sum()),
        "min_ks": round(run["ks"].min(), 3),
        "closure_error_mm": float(closure),
    }


def default_params(awc_mm_per_m, **overrides):
    return replace(WheatParams(awc_mm_per_m=awc_mm_per_m), **overrides)
