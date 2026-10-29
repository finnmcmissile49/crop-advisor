"""Wait for forecast rain instead of irrigating just before it.

The water-balance trigger only asks whether the soil has used its readily available water (RAW)
today. If heavy rain is forecast for the next days, a farmer who irrigates now wastes a watering
and risks waterlogging. This module decides when waiting is safe.

Thresholds come from the forecast backtest (scripts/backtest_forecast.py, 29 October 2026):
Open-Meteo forecasts archived by its Previous Runs API, six Punjab and Haryana districts,
January 2024 to October 2026, compared with Open-Meteo's recorded rain.
- When the forecast for the next 3 days totals at least 20 mm, at least 10 mm fell in 79 percent
  of rabi cases (November-March, 39 cases) and 72 percent of kharif cases (June-October, 607).
- In April and May the same forecast came true only 20 percent of the time (25 cases), so the
  rule never waits in those months.
Waiting is also refused if the soil would get too dry before the rain arrives: the root zone may
not go further than a quarter of the way from RAW to wilting point (water stress coefficient Ks
stays at or above 0.75). That limit is our choice, not from FAO-56 or PAU.
"""
import pandas as pd

RAIN_TOTAL_MM = 20.0     # forecast total over the next WAIT_DAYS days needed to consider waiting
RAIN_ARRIVES_MM = 10.0   # cumulative forecast rain that counts as "the rain has come"
WAIT_DAYS = 3
KS_FLOOR = 0.75
NO_WAIT_MONTHS = (4, 5)  # forecast rain too unreliable (backtest)


def wait_for_rain(date, dr_start, raw, taw, etc_next, rain_next):
    """Should a watering due on `date` wait for forecast rain?

    dr_start: root-zone depletion at the start of `date` (mm).
    etc_next, rain_next: crop water use and forecast rain for date, date+1, ... (mm per day).
    Returns (days_to_wait, forecast_total_mm) or None. days_to_wait is the number of days from
    `date` until the cumulative forecast reaches RAIN_ARRIVES_MM (0 = rain due on that day).
    """
    if pd.Timestamp(date).month in NO_WAIT_MONTHS:
        return None
    rain = [float(x) for x in rain_next[:WAIT_DAYS]]
    if len(rain) < WAIT_DAYS or sum(rain) < RAIN_TOTAL_MM:
        return None
    cum, wait = 0.0, None
    for i, r in enumerate(rain):
        cum += r
        if cum >= RAIN_ARRIVES_MM:
            wait = i
            break
    if wait is None:
        return None
    limit = raw + (1 - KS_FLOOR) * (taw - raw)       # depletion at which Ks = KS_FLOOR
    dr_when_rain = dr_start + sum(float(x) for x in etc_next[:wait])   # no rain until then
    if dr_when_rain > limit:
        return None
    return wait, round(sum(rain), 1)


class RainAwareRule:
    """Wraps an advice rule (CropRule or FirstWateringThenTrigger) for season replays.

    When the base rule would irrigate by the water-balance trigger (not a fixed-stage watering),
    it checks the forecast that was available that day; if waiting is safe, it holds the
    watering until the day the rain was due. After that day it irrigates if the soil still needs
    it. One hold per dry spell.

    forecast(date) -> list of forecast rain for date, date+1, date+2 as issued on that morning.
    etc_by_date: crop water use by date (Kc x ET0; it does not depend on irrigation).
    """

    def __init__(self, base, forecast, etc_by_date):
        self.base, self.forecast, self.etc = base, forecast, etc_by_date
        self.name = base.name + "+rain"

    def start(self, sowing, params):
        self.base.start(sowing, params)
        self.hold_until = None
        self.held_this_spell = False
        self.holds = []          # (date, wait_days, forecast_total, rain_that_fell) for reports
        self.taw = None

    def decide(self, date, das, dr_prev, raw, taw):
        if dr_prev < raw:
            self.held_this_spell = False
        if self.hold_until is not None and date <= self.hold_until:
            if dr_prev <= raw + (1 - KS_FLOOR) * (taw - raw):
                return 0.0
        self.hold_until = None
        snapshot = _snapshot(self.base)
        irr = self.base.decide(date, das, dr_prev, raw, taw)
        if irr <= 0 or getattr(self.base, "last_kind", "trigger") == "first" \
                or self.held_this_spell:
            return irr
        fc = self.forecast(date)
        etc = [self.etc.get(date + pd.Timedelta(days=i), 0.0) for i in range(WAIT_DAYS)]
        w = wait_for_rain(date, dr_prev, raw, taw, etc, fc) if fc is not None else None
        if w is None:
            return irr
        _restore(self.base, snapshot)   # the base rule did not really irrigate
        self.hold_until = date + pd.Timedelta(days=w[0])
        self.held_this_spell = True
        self.holds.append((date, w[0], w[1]))
        return 0.0

    def observe_rain(self, date, rain_mm):
        self.base.observe_rain(date, rain_mm)


def _snapshot(rule):
    return {k: v for k, v in vars(rule).items() if isinstance(v, (int, float, bool, type(None)))}


def _restore(rule, snap):
    for k, v in snap.items():
        setattr(rule, k, v)
