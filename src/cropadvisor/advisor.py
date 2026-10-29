"""Live irrigation advice for one wheat field (calculator v0).

Given a district, the sowing date and the dates the farmer has irrigated, replay the root-zone
water balance from sowing to today with the weather recorded so far, then look ahead with the
16-day forecast and say when the next irrigation is due.

The rule is the agreed advice rule (24 Oct 2026): always the first irrigation at crown root
initiation (PAU for Punjab, ICAR-IIWBR elsewhere), then irrigate when the soil has used its readily
available water (FAO-56), up to the season cut-off.

The answer is a window, not a date: the earliest and latest day across soil water-holding capacity
20 percent below and above the estimate (an arbitrary range, not a measured uncertainty). It is
advice for a typical field in the district from public data. It has not been checked against
real fields.
"""
import datetime as dt
from dataclasses import dataclass

import pandas as pd

from cropadvisor import crops as cr
from cropadvisor import irrigation as ir
from cropadvisor import openmeteo
from cropadvisor import rainrule as rr

SOIL_SCALES = (0.8, 1.0, 1.2)   # no soil type given: plus or minus 20 percent (arbitrary)

# FAO-56 Table 19, available water (theta FC - theta WP, m3/m3) for typical soils, as mm per metre.
# Farmer words map to the nearest class: sandy -> loamy sand, light loam -> sandy loam,
# loam -> loam, heavy/clay -> clay.
SOIL_TYPES = {
    "sandy": {"fao_class": "loamy sand", "range": (60.0, 120.0), "en": "sandy",
              "hi": "रेतीली"},
    "light_loam": {"fao_class": "sandy loam", "range": (110.0, 150.0), "en": "light loam",
                   "hi": "हल्की दोमट"},
    "loam": {"fao_class": "loam", "range": (130.0, 180.0), "en": "loam", "hi": "दोमट"},
    "clay": {"fao_class": "clay", "range": (120.0, 200.0), "en": "heavy (clay)",
             "hi": "भारी (चिकनी)"},
}


def soil_cases(site):
    """Water-holding (mm per m) for the light, likely and heavy cases.

    Farmer gave a soil type: its FAO-56 Table 19 range, with the model (SoilGrids) value as the
    likely case when it falls inside that range, else the middle of the range. No soil type: the
    model value plus or minus 20 percent."""
    st = getattr(site, "soil_type", None)
    if st:
        lo, hi = SOIL_TYPES[st]["range"]
        awc = site.awc_mm_per_m
        likely = awc if awc is not None and lo <= awc <= hi else (lo + hi) / 2
        return {"light": lo, "likely": likely, "heavy": hi}
    a = site.awc_mm_per_m
    return {"light": a * SOIL_SCALES[0], "likely": a * SOIL_SCALES[1], "heavy": a * SOIL_SCALES[2]}
EARLIEST_SOWING = (10, 15)   # PAU's schedule table starts with October sowing
# Latest sowing: the end of the zone's timely sowing window (irrigation.ZONES) plus this grace,
# with a warning after the window. The crop settings (season length, Kc and root curves) are for
# timely-sown varieties; late-sown varieties are shorter, so later sowings are refused (decided
# 29 October 2026; PAU's late-sown rows run to 15 January).
LATE_GRACE_DAYS = 10
FORECAST_DAYS = 16           # Open-Meteo forecast limit
RECHECK_DAYS = 7


class AdviceError(ValueError):
    """Inputs the calculator cannot give advice for. The message is shown to the user."""


@dataclass
class Site:
    name: str
    state: str
    zone: str
    awc_mm_per_m: float
    lat: float = None
    lon: float = None
    soil_type: str = None          # key of SOIL_TYPES, from the farmer; None: not given
    soil_source: str = "district"  # "district" (SoilGrids at the district point) or "field"


# ----------------------------------------------------------------------------------- inputs

def timely_end(site, sowing):
    """Last day of the zone's timely wheat sowing window for the season containing `sowing`."""
    return ir._rabi_date(pd.Timestamp(sowing), *ir.ZONES[site.zone]["window"][1])


def wheat_warnings(site, sowing):
    end = timely_end(site, sowing)
    if pd.Timestamp(sowing) <= end:
        return []
    return [("late", f"Sown after the timely window ({end.day} {end:%B}): the crop may mature "
                     "earlier than assumed, so treat the dates as rough.",
             f"समय पर बुवाई की अवधि ({end.day} {HI_MONTHS[end.month - 1]}) के बाद बोया गया: फ़सल "
             "जल्दी पक सकती है, इसलिए तारीख़ें अनुमान मानें।")]


def check_inputs(site, sowing, today, watered):
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    if site.zone not in ir.ZONES:
        raise AdviceError(f"No wheat settings for zone {site.zone}.")
    lo = ir._rabi_date(sowing, *EARLIEST_SOWING)
    limit = timely_end(site, sowing) + pd.Timedelta(days=LATE_GRACE_DAYS)
    if not lo <= sowing <= limit:
        raise AdviceError(f"The calculator is set up for wheat sown between 15 October and "
                          f"{limit.day} {limit:%B}, because its crop settings are for timely "
                          f"sowing. {sowing:%d %b %Y} is outside that. Late-sown wheat needs "
                          "shorter-season settings, which are not added yet.")
    if today < sowing:
        raise AdviceError(f"Today ({today:%d %b %Y}) is before the sowing date.")
    params = ir.zone_params(site.zone, site.awc_mm_per_m, state=site.state)
    if (today - sowing).days >= params.season_days:
        raise AdviceError(f"The crop is past its expected {params.season_days}-day season "
                          "(near or at harvest). No irrigation advice.")
    w = sorted(pd.Timestamp(d) for d in watered)
    if len(set(w)) != len(w):
        raise AdviceError("The same watering date is given twice.")
    for d in w:
        if d < sowing or d > today:
            raise AdviceError(f"Watering date {d:%d %b %Y} is before sowing or after today.")
    return sowing, today, w, params


# ---------------------------------------------------------------------------------- weather

def get_weather(lat, lon, sowing, today, now=None, fetch_history=None, fetch_forecast=None):
    """Daily rain and ET0 (Open-Meteo) from sowing to the end of the forecast.

    Live (today within 2 days of now): recorded weather to today plus the 16-day forecast.
    Test mode (today well in the past): recorded weather to today + 16 days, used as if it were
    the forecast (a perfect forecast, so real advice will be less certain).
    Returns DataFrame date, rain_mm, et0_mm, forecast (bool), and the mode.
    """
    fetch_history = fetch_history or openmeteo.fetch_history
    fetch_forecast = fetch_forecast or openmeteo.fetch_forecast
    now = pd.Timestamp(now or dt.date.today()).normalize()
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    f = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731
    if today >= now - pd.Timedelta(days=2):
        mode = "live"
        past = (now - sowing).days + 1
        if past <= 60:
            df = fetch_forecast(lat, lon, days=FORECAST_DAYS, past_days=past)
        else:   # older part from the archive (a few days' delay), recent part from the forecast
            hist = fetch_history(lat, lon, f(sowing), f(now - pd.Timedelta(days=10)))
            fc = fetch_forecast(lat, lon, days=FORECAST_DAYS, past_days=12)
            df = pd.concat([hist, fc[~fc["date"].isin(hist["date"])]], ignore_index=True)
        forecast_from = now + pd.Timedelta(days=1)
    elif today <= now - pd.Timedelta(days=FORECAST_DAYS + 7):
        mode = "test"
        df = fetch_history(lat, lon, f(sowing), f(today + pd.Timedelta(days=FORECAST_DAYS)))
        forecast_from = today + pd.Timedelta(days=1)
    else:
        raise AdviceError("For a past date, choose one at least 23 days ago (so its following "
                          "16 days are recorded), or leave out --today for live advice.")
    df = df[df["date"] >= sowing].sort_values("date").drop_duplicates("date")
    out = pd.DataFrame({"date": df["date"], "rain_mm": df["rain_mm"].astype(float),
                        "et0_mm": df["et0_openmeteo_mm"].astype(float)})
    for col in ("rh_min", "wind_2m_ms"):   # for the FAO-56 Kc adjustment of the other crops
        if col in df:
            out[col] = df[col].astype(float)
    out["forecast"] = out["date"] >= forecast_from
    full = pd.date_range(sowing, out["date"].max())
    if len(full) != len(out) or out[["rain_mm", "et0_mm"]].isna().any().any():
        raise AdviceError("Weather data has gaps, so the soil water cannot be tracked. Try again "
                          "later.")
    return out.reset_index(drop=True), mode


# ----------------------------------------------------------------------------------- advice

def _trigger_day(weather, sowing, params, watered, depth_mm, today, cutoff):
    """First day from today on whose start-of-day depletion reaches RAW, or None."""
    run = ir.simulate(weather[["date", "rain_mm", "et0_mm"]], sowing, params,
                      ir.GivenIrrigations(watered, depth_mm))
    run["dr_start"] = run["dr_mm"].shift(1).fillna(0.0)
    look = run[(run["date"] >= today) & (run["date"] <= cutoff)]
    hit = look[look["dr_start"] >= look["raw_mm"]]
    return (hit["date"].iloc[0] if len(hit) else None), run


def advise(site, sowing, today, watered, weather, depth_mm=None, mode="live", crop="wheat"):
    """Advice as a dict (see render). weather: date, rain_mm, et0_mm, forecast (and optionally
    rh_min, wind_2m_ms). crop: "wheat" or a key of crops.CROPS."""
    if crop != "wheat":
        return advise_crop(cr.get(crop), site, sowing, today, watered, weather,
                           depth_mm=depth_mm, mode=mode)
    sowing, today, watered, params = check_inputs(site, sowing, today, watered)
    cutoff = ir.last_irrigation_date(sowing, params)
    first_das, first_lo, first_hi, first_depth = ir.first_watering(site.state, sowing)
    depth_mm = float(depth_mm or first_depth)
    end = weather["date"].max()
    das = (today - sowing).days
    fc = weather[(weather["date"] > today) & (weather["date"] <= today + pd.Timedelta(days=7))]
    out = {"site": site, "sowing": sowing, "today": today, "das": das, "watered": watered,
           "season_days": params.season_days, "cutoff": cutoff, "depth_mm": depth_mm,
           "mode": mode, "rain_next7_mm": round(float(fc["rain_mm"].sum()), 1),
           "forecast_end": end, "warnings": wheat_warnings(site, sowing),
           "soil_type": site.soil_type}

    if today > cutoff:
        return {**out, "status": "season_over"}
    if not watered:
        lo = sowing + pd.Timedelta(days=first_lo)
        hi = sowing + pd.Timedelta(days=first_hi)
        status = "first_upcoming" if das < first_lo else (
            "first_now" if das <= first_hi else "first_overdue")
        return {**out, "status": status, "first_lo": lo, "first_hi": hi,
                "first_day": sowing + pd.Timedelta(days=first_das),
                "first_lo_das": first_lo, "first_hi_das": first_hi}

    days = {}
    for scale, awc in soil_cases(site).items():
        p = ir.zone_params(site.zone, awc, state=site.state)
        day, run = _trigger_day(weather, sowing, p, watered, depth_mm, today, min(cutoff, end))
        days[scale] = day
        if scale == "likely":
            run_likely = run
            row = run[run["date"] == today].iloc[0]
            out.update(raw_used_pct=round(100 * row["dr_mm"] / row["raw_mm"]) if row["raw_mm"]
                       else 0, dr_mm=round(float(row["dr_mm"]), 1),
                       taw_mm=round(float(row["taw_mm"]), 1))
    found = [d for d in days.values() if d is not None]
    covers_season = end >= cutoff   # forecast reaches the last irrigation date
    quiet = {"recheck": min(today + pd.Timedelta(days=RECHECK_DAYS), cutoff),
             "horizon_days": (end - today).days, "covers_season": covers_season}
    likely = days["likely"]
    wait = rain_wait(run_likely, weather, likely, today)
    if wait:
        return {**out, **wait, "status": "wait_for_rain"}
    if likely is not None and likely <= today + pd.Timedelta(days=1):
        return {**out, "status": "water_now"}   # due today, or soil crosses the line tonight
    if not found:
        return {**out, "status": "no_more_needed" if covers_season else "not_needed_soon",
                **quiet}
    if likely is None:
        # only the lighter-soil case (less water-holding) needs water within the horizon
        return {**out, "status": "light_soil_only", "light_soil_day": min(found), **quiet}
    return {**out, "status": "water_window", "earliest": min(found), "latest": max(found),
            "likely": likely,
            "heavy_soil_later": days["heavy"] is None,   # heavier soil: later than the horizon
            "heavy_soil_none": days["heavy"] is None and covers_season}


def rain_wait(run, weather, likely, today, sowing=None, spec=None):
    """If the watering due on `likely` (within the next WAIT_DAYS days) should wait for forecast
    rain, return the rain day and forecast total (see rainrule.py), else None."""
    if likely is None or likely > today + pd.Timedelta(days=rr.WAIT_DAYS):
        return None
    days = pd.date_range(likely, periods=rr.WAIT_DAYS)
    w = weather.set_index("date")
    r = run.set_index("date")
    if days[-1] not in w.index or days[-1] not in r.index:
        return None
    dr_start = float(r["dr_mm"].shift(1).fillna(0.0).loc[likely])
    raw, taw = float(r.loc[likely, "raw_mm"]), float(r.loc[likely, "taw_mm"])
    res = rr.wait_for_rain(likely, dr_start, raw, taw, r.loc[days, "etc_mm"].tolist(),
                           w.loc[days, "rain_mm"].tolist())
    if res is None:
        return None
    rain_day = likely + pd.Timedelta(days=res[0])
    if spec is not None:   # never move a watering past the crop's last watering date
        params = spec.params(1.0)
        if rain_day + pd.Timedelta(days=1) > spec.cutoff_date(sowing, params):
            return None
    return {"rain_day": rain_day, "rain_total_mm": res[1],
            "water_if_dry": rain_day + pd.Timedelta(days=1)}


# ------------------------------------------------------------------------------ confidence
# How sure the advice is about its own date, from the forecast backtest (29 October 2026, six
# Punjab and Haryana districts, forecasts as issued, 2024-2026): when the watering was really due
# 1-3 days ahead the forecast-based date was within a day in 96-100 percent of cases, 4-5 days
# ahead 91-93 percent, 6 days ahead 79 percent; beyond 6 days it could not be tested. This says
# nothing about whether the water balance matches a real field (not yet checked anywhere).

CONF_LEVELS = {3: ("high", "ऊँचा"), 2: ("medium", "मध्यम"), 1: ("low", "कम")}


def confidence(a):
    """(level, [(reason_en, reason_hi), ...]) for an advice dict."""
    score, why = 3, []
    st = a["status"]
    if st in ("water_window", "light_soil_only"):
        day = a.get("likely") or a.get("light_soil_day")
        lead = (day - a["today"]).days
        if lead > 6:
            score -= 2
            why.append((f"the date is {lead} days away, further than the forecast could be "
                        "tested", f"तारीख़ {lead} दिन दूर है, जितना मौसम-अनुमान जाँचा जा सका उससे आगे"))
        elif lead >= 4:
            score -= 1
            why.append((f"the date is {lead} days away", f"तारीख़ {lead} दिन दूर है"))
    elif st == "wait_for_rain":
        score -= 1
        why.append(("forecast rain of this size came about 3 times in 4 in past seasons",
                    "इतनी बारिश का अनुमान पिछले मौसमों में लगभग 4 में से 3 बार सही निकला"))
    elif st in ("not_needed_soon", "no_more_needed", "window_upcoming"):
        score -= 1
        why.append(("it depends on the long-range forecast", "यह लंबे मौसम-अनुमान पर निर्भर है"))
    site = a["site"]
    if not a.get("soil_type") and getattr(site, "soil_source", "district") != "field":
        score -= 1
        why.append(("the soil is the district's estimate, not your field's",
                    "मिट्टी ज़िले का अनुमान है, आपके खेत की नहीं"))
    spec = a.get("spec")
    if spec is not None and spec.confidence != "normal":
        score -= 1
        why.append((f"{spec.en.lower()} advice is less certain (see notes)",
                    f"{spec.hi} की सलाह कम पक्की है"))
    if any(w[0] == "late" for w in a.get("warnings", [])):
        score -= 1
        why.append(("sown late", "देर से बुवाई"))
    if st in ("season_over", "max_reached"):
        score, why = 3, []
    return CONF_LEVELS[max(1, min(3, score))], why


def confidence_text(a):
    (lvl_en, lvl_hi), why = confidence(a)
    en = f"Confidence: {lvl_en}" + (f" ({'; '.join(w[0] for w in why)})." if why else ".")
    hi = f"भरोसा: {lvl_hi}" + (f" ({'; '.join(w[1] for w in why)})।" if why else "।")
    return en, hi


def to_json(a):
    """The advice as plain JSON-ready data (dates as YYYY-MM-DD), for the web service and app."""
    out = {}
    for k, v in a.items():
        if k in ("site", "spec"):
            continue
        if isinstance(v, pd.Timestamp):
            v = v.strftime("%Y-%m-%d")
        elif isinstance(v, list):
            v = [x.strftime("%Y-%m-%d") if isinstance(x, pd.Timestamp) else
                 (list(x) if isinstance(x, tuple) else x) for x in v]
        elif hasattr(v, "item"):
            v = v.item()
        out[k] = v
    s = a["site"]
    out["site"] = {"district": s.name, "state": s.state, "zone": s.zone, "lat": s.lat,
                   "lon": s.lon, "awc_mm_per_m": s.awc_mm_per_m, "soil_type": s.soil_type,
                   "soil_source": s.soil_source}
    out["crop"] = a.get("crop", "wheat")
    (lvl, _), why = confidence(a)
    out["confidence"] = {"level": lvl, "reasons": [w[0] for w in why]}
    return out


# ----------------------------------------------------------------------------------- render

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]


def _light_en(a):
    if a.get("soil_type"):
        return f"If your {SOIL_TYPES[a['soil_type']]['en']} soil holds less water than usual"
    return "If your soil is light or sandy"


def _light_hi(a):
    if a.get("soil_type"):
        return f"आपकी {SOIL_TYPES[a['soil_type']]['hi']} मिट्टी कम पानी रोकती हो"
    return "हल्की या रेतीली मिट्टी हो"


def _heavy_en(a):
    if a.get("soil_type"):
        return f"If your {SOIL_TYPES[a['soil_type']]['en']} soil holds more water than usual"
    return "If your soil is heavy (holds more water)"


def _heavy_hi(a):
    if a.get("soil_type"):
        return f"आपकी {SOIL_TYPES[a['soil_type']]['hi']} मिट्टी ज़्यादा पानी रोकती हो"
    return "भारी मिट्टी हो (ज़्यादा पानी रोके)"


def _soil_note(a):
    """The 'how sure' sentence about the soil range."""
    if a.get("soil_type"):
        t = SOIL_TYPES[a["soil_type"]]
        lo, hi = t["range"]
        return (f"The earlier and later dates cover the range of water a {t['en']} soil can hold "
                f"({lo:g} to {hi:g} mm per metre, FAO-56).")
    return ("'Light' and 'heavy' soil show how the answer changes if the soil holds 20 percent "
            "less or more water than estimated.")


def _en(d):
    return f"{d.day} {d:%b %Y}"


def _hi(d):
    return f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}"


def _in(d, today):
    return (d - today).days


def render(a):
    """English and Hindi text for the advice dict. Units farmers use: days, dates, cm, inches."""
    if a.get("crop", "wheat") != "wheat":
        return render_crop(a)
    s, today = a["site"], a["today"]
    cm = a["depth_mm"] / 10
    inch = round(cm / 2.54)
    zone = ir.ZONES[s.zone]["label"]
    head = [f"Crop Advisor: wheat irrigation (test version, public data only)",
            f"District: {s.name}, {s.state} ({zone})",
            f"Sown {_en(a['sowing'])}. Today {_en(today)} is day {a['das']} of about "
            f"{a['season_days']}."]
    if a["watered"]:
        head.append("Watered on: " + ", ".join(_en(d) for d in a["watered"]))
    if a["mode"] == "test":
        head.append("TEST MODE: the 'forecast' is weather that was actually recorded.")
    en, hi = [], []
    for _, w_en, w_hi in a.get("warnings", []) + a.get("notes", []):
        en.append(w_en)
        hi.append(w_hi)
    st = a["status"]
    if st == "season_over":
        en.append(f"NO MORE WATERING this season (no irrigation after {_en(a['cutoff'])}).")
        hi.append(f"इस मौसम में अब सिंचाई नहीं ({_hi(a['cutoff'])} के बाद सिंचाई नहीं)।")
    elif st == "no_more_needed":
        en.append(f"NO MORE WATERING NEEDED before the last irrigation date "
                  f"({_en(a['cutoff'])}), unless the weather turns much hotter or drier.")
        hi.append(f"आख़िरी सिंचाई की तारीख़ ({_hi(a['cutoff'])}) से पहले और सिंचाई की ज़रूरत नहीं, "
                  "जब तक मौसम बहुत गर्म या सूखा न हो जाए।")
    elif st in ("first_upcoming", "first_now", "first_overdue"):
        lo, hi_d = a["first_lo"], a["first_hi"]
        if st == "first_upcoming":
            en.append(f"FIRST WATERING: between {_en(lo)} and {_en(hi_d)} "
                      f"(day {a['first_lo_das']} to {a['first_hi_das']} after sowing; in "
                      f"{_in(lo, today)} to {_in(hi_d, today)} days).")
            hi.append(f"पहली सिंचाई: {_hi(lo)} से {_hi(hi_d)} के बीच (बुवाई के "
                      f"{a['first_lo_das']} से {a['first_hi_das']} दिन बाद)।")
        elif st == "first_now":
            en.append(f"FIRST WATERING: NOW (due by {_en(hi_d)}).")
            hi.append(f"पहली सिंचाई: अभी करें ({_hi(hi_d)} तक)।")
        else:
            en.append(f"FIRST WATERING IS LATE (was due by {_en(hi_d)}). Water as soon as "
                      "possible. If you already watered, add the date with --watered.")
            hi.append(f"पहली सिंचाई देर से हो रही है ({_hi(hi_d)} तक होनी थी)। जल्द से जल्द "
                      "सिंचाई करें।")
        en.append("Do not skip it: this is when the crown roots form, the most sensitive stage.")
        hi.append("इसे न छोड़ें: इस समय जड़ें (क्राउन रूट) बनती हैं, यह सबसे ज़रूरी समय है।")
    elif st == "wait_for_rain":
        rd, wd = a["rain_day"], a["water_if_dry"]
        en.append(f"WAIT FOR THE RAIN: the soil is nearly due for water, but about "
                  f"{a['rain_total_mm']:g} mm of rain is forecast by {_en(rd)}. Do not water "
                  f"before then. If less than 1 cm (10 mm) falls by {_en(rd)}, water on "
                  f"{_en(wd)}.")
        hi.append(f"बारिश का इंतज़ार करें: मिट्टी को जल्द पानी चाहिए, पर {_hi(rd)} तक लगभग "
                  f"{a['rain_total_mm']:g} मिमी बारिश का अनुमान है। उससे पहले सिंचाई न करें। अगर "
                  f"{_hi(rd)} तक 1 सेमी (10 मिमी) से कम बारिश हो, तो {_hi(wd)} को सिंचाई करें।")
    elif st == "water_now":
        en.append("WATER TODAY OR TOMORROW: the soil has used up its easily available water.")
        hi.append("आज या कल सिंचाई करें: मिट्टी में आसानी से मिलने वाला पानी ख़त्म हो गया है।")
    elif st == "water_window":
        e, l, k = a["earliest"], a["latest"], a["likely"]
        en.append(f"NEXT WATERING: most likely around {_en(k)} (in {_in(k, today)} days).")
        hi.append(f"अगली सिंचाई: सबसे संभावित {_hi(k)} के आसपास ({_in(k, today)} दिन में)।")
        if e < k:
            en.append(f"{_light_en(a)}, as early as {_en(e)}.")
            hi.append(f"{_light_hi(a)} तो पहले, {_hi(e)} के आसपास।")
        if a["heavy_soil_none"]:
            en.append(f"{_heavy_en(a)}, maybe no more watering this season.")
            hi.append(f"{_heavy_hi(a)} तो शायद इस मौसम में और सिंचाई न लगे।")
        elif a["heavy_soil_later"]:
            en.append(f"{_heavy_en(a)}, later than {_en(a['forecast_end'])}.")
            hi.append(f"{_heavy_hi(a)} तो {_hi(a['forecast_end'])} के बाद।")
        elif l > k:
            en.append(f"{_heavy_en(a)}, as late as {_en(l)}.")
            hi.append(f"{_heavy_hi(a)} तो {_hi(l)} तक।")
    elif st == "light_soil_only":
        if a["covers_season"]:
            en.append("PROBABLY NO MORE WATERING NEEDED this season.")
            hi.append("शायद इस मौसम में और सिंचाई की ज़रूरत नहीं।")
        else:
            en.append(f"PROBABLY NO WATERING NEEDED in the next {a['horizon_days']} days. "
                      f"Check again on {_en(a['recheck'])}.")
            hi.append(f"अगले {a['horizon_days']} दिन शायद सिंचाई की ज़रूरत नहीं। "
                      f"{_hi(a['recheck'])} को फिर देखें।")
        en.append(f"But {_light_en(a)[0].lower()}{_light_en(a)[1:]}, water around {_en(a['light_soil_day'])}.")
        hi.append(f"लेकिन {_light_hi(a)} तो {_hi(a['light_soil_day'])} के आसपास सिंचाई करें।")
    elif st == "not_needed_soon":
        en.append(f"NO WATERING NEEDED in the next {a['horizon_days']} days. Check again on "
                  f"{_en(a['recheck'])}.")
        hi.append(f"अगले {a['horizon_days']} दिन सिंचाई की ज़रूरत नहीं। {_hi(a['recheck'])} को "
                  "फिर देखें।")
    if st in ("first_upcoming", "first_now", "first_overdue", "water_now", "water_window",
              "light_soil_only"):
        en.append(f"Give a normal irrigation, about {cm:g} cm (about {inch} inches) of water.")
        hi.append(f"सामान्य सिंचाई करें, लगभग {cm:g} सेमी (लगभग {inch} इंच) पानी।")
    if "raw_used_pct" in a and st != "season_over":
        en.append(f"Soil today: about {min(a['raw_used_pct'], 100)} percent of the easily "
                  "available water is used.")
        hi.append(f"आज मिट्टी: आसानी से मिलने वाले पानी का लगभग {min(a['raw_used_pct'], 100)} "
                  "प्रतिशत इस्तेमाल हो चुका है।")
    if st != "season_over":
        en.append(f"Rain forecast, next 7 days: {a['rain_next7_mm']:g} mm.")
        hi.append(f"अगले 7 दिन में बारिश का अनुमान: {a['rain_next7_mm']:g} मिमी।")
    c_en, c_hi = confidence_text(a)
    en.append(c_en)
    hi.append(c_hi)
    note = ("How sure is this? It uses free weather data for the whole district and an "
            "estimated soil, not your own field, and it has not yet been checked against real "
            f"fields. {_soil_note(a)} If it rains well before the date, check again.")
    hi_note = ("यह सलाह ज़िले के मुफ़्त मौसम आँकड़ों और अनुमानित मिट्टी पर आधारित है, आपके खेत पर "
               "नहीं, और अभी असली खेतों में जाँची नहीं गई है। अगर बीच में अच्छी बारिश हो, तो फिर से "
               "देखें।")
    return "\n".join(head + [""] + en + ["", note]), "\n".join(hi + ["", hi_note])


def i_do_not_know(reason):
    return (f"I do not know: {reason}", f"मैं नहीं बता सकता: {reason}")


# ================================================================== other crops (crops.py)
# Wheat keeps the functions above unchanged. Every other crop goes through advise_crop and
# render_crop: the same water balance and statuses, with each crop's PAU rules (first watering,
# cut-off, no-irrigation periods, the chickpea date window, the largest number of waterings).

WEATHER_COLS = ["date", "rain_mm", "et0_mm", "rh_min", "wind_2m_ms"]


def check_crop_inputs(spec, site, sowing, today, watered):
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    if site.state not in cr.STATES:
        raise AdviceError(f"{spec.en} advice is set up for Punjab and Haryana only (it follows "
                          f"PAU's guidance). {site.name} is in {site.state}.")
    lo, hi = spec.sowing_range(sowing)
    late_limit = hi + pd.Timedelta(days=cr.SOWING_GRACE_DAYS)
    if not lo <= sowing <= late_limit:
        raise AdviceError(f"{spec.en}: PAU's sowing time is {lo:%d %B} to {hi:%d %B}. "
                          f"{sowing:%d %b %Y} is outside it, and the crop settings are for sowing "
                          "on time.")
    warnings = []
    if sowing > hi:
        warnings.append(("late",
                         f"Sown after PAU's window ({hi:%d %B}): the crop may mature earlier than "
                         "assumed, so treat the dates as rough.",
                         f"PAU की बुवाई अवधि ({hi.day} {HI_MONTHS[hi.month - 1]}) के बाद बोया गया: "
                         "फ़सल जल्दी पक सकती है, इसलिए तारीख़ें अनुमान मानें।"))
    if today < sowing:
        raise AdviceError(f"Today ({today:%d %b %Y}) is before the sowing date.")
    params = spec.params(site.awc_mm_per_m)
    if (today - sowing).days >= params.season_days:
        raise AdviceError(f"The crop is past its expected {params.season_days}-day season "
                          "(near or at harvest). No irrigation advice.")
    w = sorted(pd.Timestamp(d) for d in watered)
    if len(set(w)) != len(w):
        raise AdviceError("The same watering date is given twice.")
    for d in w:
        if d < sowing or d > today:
            raise AdviceError(f"Watering date {d:%d %b %Y} is before sowing or after today.")
    return sowing, today, w, params, warnings


def _crop_trigger(spec, weather, sowing, params, watered, depth_mm, today, last_day):
    """First day from today (up to last_day) on which the crop's rule would water, given the
    waterings so far and no new ones. Returns (day or None, how, run)."""
    cols = [c for c in WEATHER_COLS if c in weather]
    run = ir.simulate(weather[cols], sowing, params, ir.GivenIrrigations(watered, depth_mm))
    run["dr_start"] = run["dr_mm"].shift(1).fillna(0.0)
    look = run[(run["date"] >= today) & (run["date"] <= last_day)]
    win = spec.window_dates(sowing)
    if win:
        look = look[(look["date"] >= win[0]) & (look["date"] <= win[1])]
    hit = look[look["dr_start"] >= look["raw_mm"]]
    day, how = (hit["date"].iloc[0], "trigger") if len(hit) else (None, None)
    if day is None and win and win[1] <= last_day and len(look):
        end_row = look[look["date"] == win[1]]
        if len(end_row) and end_row["dr_start"].iloc[0] >= \
                spec.window["end_fraction"] * end_row["raw_mm"].iloc[0]:
            day, how = win[1], "window_end"
    black = spec.blackout_dates(sowing)
    if day is not None and black and black[0] <= day <= black[1]:
        before = black[0] - pd.Timedelta(days=1)
        after = black[1] + pd.Timedelta(days=1)
        if before >= today and (day - black[0]).days <= 5:
            day, how = before, "before_blackout"
        elif after <= last_day:
            day, how = after, "after_blackout"
        else:
            day, how = None, "blackout"
    return day, how, run


def advise_crop(spec, site, sowing, today, watered, weather, depth_mm=None, mode="live"):
    sowing, today, watered, params, warnings = check_crop_inputs(spec, site, sowing, today,
                                                                 watered)
    cutoff = spec.cutoff_date(sowing, params)
    end = weather["date"].max()
    das = (today - sowing).days
    fc = weather[(weather["date"] > today) & (weather["date"] <= today + pd.Timedelta(days=7))]
    out = {"crop": spec.key, "spec": spec, "site": site, "sowing": sowing, "today": today,
           "das": das, "watered": watered, "season_days": params.season_days, "cutoff": cutoff,
           "depth_mm": depth_mm, "mode": mode, "warnings": warnings,
           "rain_next7_mm": round(float(fc["rain_mm"].sum()), 1), "forecast_end": end,
           "soil_type": site.soil_type}
    if today > cutoff:
        return {**out, "status": "season_over"}
    if spec.max_irrigations is not None and len(watered) >= spec.max_irrigations:
        return {**out, "status": "max_reached"}
    if spec.first and not watered:
        f_das, f_lo, f_hi = spec.first
        lo, hi = sowing + pd.Timedelta(days=f_lo), sowing + pd.Timedelta(days=f_hi)
        status = "first_upcoming" if das < f_lo else ("first_now" if das <= f_hi
                                                       else "first_overdue")
        return {**out, "status": status, "first_lo": lo, "first_hi": hi,
                "first_day": sowing + pd.Timedelta(days=f_das),
                "first_lo_das": f_lo, "first_hi_das": f_hi}

    last_day = min(cutoff, end)
    days, hows = {}, {}
    for scale, awc in soil_cases(site).items():
        p = spec.params(awc)
        day, how, run = _crop_trigger(spec, weather, sowing, p, watered, depth_mm, today,
                                      last_day)
        days[scale], hows[scale] = day, how
        if scale == "likely":
            run_likely = run
            row = run[run["date"] == today].iloc[0]
            out.update(raw_used_pct=round(100 * row["dr_mm"] / row["raw_mm"]) if row["raw_mm"]
                       else 0, dr_mm=round(float(row["dr_mm"]), 1),
                       taw_mm=round(float(row["taw_mm"]), 1))
            if day is not None:
                short = float(run.loc[run["date"] == day, "dr_start"].iloc[0])
                out["refill_mm"] = round(short, 1)
    out["how"] = hows["likely"]
    win = spec.window_dates(sowing)
    if win:
        out.update(window_start=win[0], window_end=win[1])
    found = [d for d in days.values() if d is not None]
    covers_season = end >= cutoff
    quiet = {"recheck": min(today + pd.Timedelta(days=RECHECK_DAYS), cutoff),
             "horizon_days": (end - today).days, "covers_season": covers_season}
    likely = days["likely"]
    wait = rain_wait(run_likely, weather, likely, today, sowing=sowing, spec=spec)
    if wait:
        return {**out, **wait, "status": "wait_for_rain"}
    black = spec.blackout_dates(sowing)
    today_blocked = bool(black) and black[0] <= today <= black[1]
    if likely is not None and (likely <= today or
                               (likely <= today + pd.Timedelta(days=1) and not today_blocked)):
        return {**out, "status": "water_now"}
    if not found:
        if win and today < win[0] and end < win[1]:
            return {**out, "status": "window_upcoming", **quiet}
        return {**out, "status": "no_more_needed" if covers_season else "not_needed_soon",
                **quiet}
    if likely is None:
        return {**out, "status": "light_soil_only", "light_soil_day": min(found), **quiet}
    return {**out, "status": "water_window", "earliest": min(found), "latest": max(found),
            "likely": likely, "heavy_soil_later": days["heavy"] is None,
            "heavy_soil_none": days["heavy"] is None and covers_season}


def _amount(a):
    """Watering amount in farmer units: cm and inches, from the soil's shortfall on that day."""
    if a.get("depth_mm"):
        cm = a["depth_mm"] / 10
    elif a.get("refill_mm"):
        cm = max(round(a["refill_mm"] / 5) / 2, 1.0)   # to the nearest half cm, at least 1 cm
    else:
        return ("Give a normal irrigation that wets the whole root zone.",
                "सामान्य सिंचाई करें जिससे जड़ों तक की मिट्टी गीली हो जाए।")
    inch = round(cm / 2.54 * 2) / 2
    inch_txt = f"{inch:g} inch" + ("" if inch <= 1 else "es")
    return (f"The soil will be short of about {cm:g} cm of water (about {inch_txt}): a "
            "normal irrigation that wets the root zone.",
            f"मिट्टी में लगभग {cm:g} सेमी (लगभग {inch:g} इंच) पानी की कमी होगी: सामान्य सिंचाई "
            "करें जिससे जड़ों तक की मिट्टी गीली हो जाए।")


def render_crop(a):
    """English and Hindi text for a non-wheat crop."""
    s, today, spec = a["site"], a["today"], a["spec"]
    head = [f"Crop Advisor: {spec.en.lower()} irrigation (test version, public data only)",
            f"District: {s.name}, {s.state}",
            f"Sown {_en(a['sowing'])}. Today {_en(today)} is day {a['das']} of about "
            f"{a['season_days']}."]
    if a["watered"]:
        head.append("Watered on: " + ", ".join(_en(d) for d in a["watered"]))
    if a["mode"] == "test":
        head.append("TEST MODE: the 'forecast' is weather that was actually recorded.")
    en, hi = [], []
    for _, w_en, w_hi in a.get("warnings", []) + a.get("notes", []):
        en.append(w_en)
        hi.append(w_hi)
    st = a["status"]
    if st == "season_over":
        en.append(f"NO MORE WATERING this season (PAU: none after {_en(a['cutoff'])}).")
        hi.append(f"इस मौसम में अब सिंचाई नहीं (PAU: {_hi(a['cutoff'])} के बाद नहीं)।")
    elif st == "max_reached":
        n = spec.max_irrigations
        en.append(f"NO MORE WATERING NEEDED: PAU gives at most {n} watering"
                  f"{'s' if n > 1 else ''} after sowing for {spec.en.lower()}, and you have "
                  "given them.")
        hi.append(f"और सिंचाई की ज़रूरत नहीं: PAU के अनुसार {spec.hi} में बुवाई के बाद ज़्यादा से "
                  f"ज़्यादा {n} सिंचाई, जो आप कर चुके हैं।")
    elif st == "no_more_needed":
        en.append(f"NO MORE WATERING NEEDED before the last watering date ({_en(a['cutoff'])}), "
                  "unless the weather turns much hotter or drier.")
        hi.append(f"आख़िरी सिंचाई की तारीख़ ({_hi(a['cutoff'])}) से पहले और सिंचाई की ज़रूरत "
                  "नहीं, जब तक मौसम बहुत गर्म या सूखा न हो जाए।")
    elif st in ("first_upcoming", "first_now", "first_overdue"):
        lo, hi_d = a["first_lo"], a["first_hi"]
        if st == "first_upcoming":
            en.append(f"FIRST WATERING: between {_en(lo)} and {_en(hi_d)} (day "
                      f"{a['first_lo_das']} to {a['first_hi_das']} after sowing; in "
                      f"{_in(lo, today)} to {_in(hi_d, today)} days).")
            hi.append(f"पहली सिंचाई: {_hi(lo)} से {_hi(hi_d)} के बीच (बुवाई के "
                      f"{a['first_lo_das']} से {a['first_hi_das']} दिन बाद)।")
        elif st == "first_now":
            en.append(f"FIRST WATERING: NOW (due by {_en(hi_d)}).")
            hi.append(f"पहली सिंचाई: अभी करें ({_hi(hi_d)} तक)।")
        else:
            en.append(f"FIRST WATERING IS LATE (was due by {_en(hi_d)}). Water as soon as "
                      "possible. If you already watered, add the date.")
            hi.append(f"पहली सिंचाई देर से हो रही है ({_hi(hi_d)} तक होनी थी)। जल्द से जल्द "
                      "सिंचाई करें।")
        if spec.first_reason_en:
            en.append(spec.first_reason_en)
            hi.append(spec.first_reason_hi)
    elif st == "wait_for_rain":
        rd, wd = a["rain_day"], a["water_if_dry"]
        en.append(f"WAIT FOR THE RAIN: the soil is nearly due for water, but about "
                  f"{a['rain_total_mm']:g} mm of rain is forecast by {_en(rd)}. Do not water "
                  f"before then. If less than 1 cm (10 mm) falls by {_en(rd)}, water on "
                  f"{_en(wd)}.")
        hi.append(f"बारिश का इंतज़ार करें: मिट्टी को जल्द पानी चाहिए, पर {_hi(rd)} तक लगभग "
                  f"{a['rain_total_mm']:g} मिमी बारिश का अनुमान है। उससे पहले सिंचाई न करें। अगर "
                  f"{_hi(rd)} तक 1 सेमी (10 मिमी) से कम बारिश हो, तो {_hi(wd)} को सिंचाई करें।")
    elif st == "water_now":
        en.append("WATER TODAY OR TOMORROW: the soil has used up its easily available water.")
        hi.append("आज या कल सिंचाई करें: मिट्टी में आसानी से मिलने वाला पानी ख़त्म हो गया है।")
    elif st == "water_window":
        e, l, k = a["earliest"], a["latest"], a["likely"]
        en.append(f"NEXT WATERING: most likely around {_en(k)} (in {_in(k, today)} days).")
        hi.append(f"अगली सिंचाई: सबसे संभावित {_hi(k)} के आसपास ({_in(k, today)} दिन में)।")
        if e < k:
            en.append(f"{_light_en(a)}, as early as {_en(e)}.")
            hi.append(f"{_light_hi(a)} तो पहले, {_hi(e)} के आसपास।")
        if a["heavy_soil_none"]:
            en.append(f"{_heavy_en(a)}, maybe no more watering this season.")
            hi.append(f"{_heavy_hi(a)} तो शायद इस मौसम में और सिंचाई न लगे।")
        elif a["heavy_soil_later"]:
            en.append(f"{_heavy_en(a)}, later than {_en(a['forecast_end'])}.")
            hi.append(f"{_heavy_hi(a)} तो {_hi(a['forecast_end'])} के बाद।")
        elif l > k:
            en.append(f"{_heavy_en(a)}, as late as {_en(l)}.")
            hi.append(f"{_heavy_hi(a)} तो {_hi(l)} तक।")
    elif st == "light_soil_only":
        if a["covers_season"]:
            en.append("PROBABLY NO MORE WATERING NEEDED this season.")
            hi.append("शायद इस मौसम में और सिंचाई की ज़रूरत नहीं।")
        else:
            en.append(f"PROBABLY NO WATERING NEEDED in the next {a['horizon_days']} days. "
                      f"Check again on {_en(a['recheck'])}.")
            hi.append(f"अगले {a['horizon_days']} दिन शायद सिंचाई की ज़रूरत नहीं। "
                      f"{_hi(a['recheck'])} को फिर देखें।")
        en.append(f"But {_light_en(a)[0].lower()}{_light_en(a)[1:]}, water around {_en(a['light_soil_day'])}.")
        hi.append(f"लेकिन {_light_hi(a)} तो {_hi(a['light_soil_day'])} के आसपास सिंचाई करें।")
    elif st == "window_upcoming":
        en.append(f"NO WATERING YET. PAU's watering window for {spec.en.lower()} is "
                  f"{_en(a['window_start'])} to {_en(a['window_end'])}. Check again on "
                  f"{_en(a['recheck'])}.")
        hi.append(f"अभी सिंचाई नहीं। PAU के अनुसार {spec.hi} की सिंचाई {_hi(a['window_start'])} "
                  f"से {_hi(a['window_end'])} के बीच। {_hi(a['recheck'])} को फिर देखें।")
    elif st == "not_needed_soon":
        en.append(f"NO WATERING NEEDED in the next {a['horizon_days']} days. Check again on "
                  f"{_en(a['recheck'])}.")
        hi.append(f"अगले {a['horizon_days']} दिन सिंचाई की ज़रूरत नहीं। {_hi(a['recheck'])} को "
                  "फिर देखें।")
    how = a.get("how")
    if st in ("water_window", "water_now") and how == "before_blackout":
        en.append("The date is set just before PAU's no-watering period.")
        hi.append("तारीख़ PAU की सिंचाई-मनाही अवधि से ठीक पहले रखी गई है।")
    elif st in ("water_window", "water_now") and how == "after_blackout":
        en.append("The soil reaches the watering point inside PAU's no-watering period, so the "
                  "date is set just after it.")
        hi.append("मिट्टी सिंचाई-मनाही अवधि में ही सूखती है, इसलिए तारीख़ उसके ठीक बाद रखी गई है।")
    elif st in ("water_window", "water_now") and how == "window_end":
        en.append("This is the last day of PAU's watering window; the soil is drier than half "
                  "of its easily available water.")
        hi.append("यह PAU की सिंचाई अवधि का आख़िरी दिन है; मिट्टी काफ़ी सूख चुकी है।")
    if st in ("water_now", "water_window", "light_soil_only", "first_upcoming", "first_now",
              "first_overdue"):
        e_amt, h_amt = _amount(a)
        en.append(e_amt)
        hi.append(h_amt)
    if "raw_used_pct" in a and st not in ("season_over", "max_reached"):
        en.append(f"Soil today: about {min(a['raw_used_pct'], 100)} percent of the easily "
                  "available water is used.")
        hi.append(f"आज मिट्टी: आसानी से मिलने वाले पानी का लगभग {min(a['raw_used_pct'], 100)} "
                  "प्रतिशत इस्तेमाल हो चुका है।")
    if st != "season_over":
        en.append(f"Rain forecast, next 7 days: {a['rain_next7_mm']:g} mm.")
        hi.append(f"अगले 7 दिन में बारिश का अनुमान: {a['rain_next7_mm']:g} मिमी।")
    en.extend(spec.notes_en)
    hi.extend(spec.notes_hi)
    c_en, c_hi = confidence_text(a)
    en.append(c_en)
    hi.append(c_hi)
    note = ("How sure is this? It uses free weather data for the whole district, an estimated "
            "soil and PAU's guidance, not your own field, and it has not yet been checked "
            f"against real fields. {_soil_note(a)} If it rains well before the date, check "
            "again.")
    hi_note = ("यह सलाह ज़िले के मुफ़्त मौसम आँकड़ों, अनुमानित मिट्टी और PAU की सिफ़ारिशों पर "
               "आधारित है, आपके खेत पर नहीं, और अभी असली खेतों में जाँची नहीं गई है। अगर बीच में "
               "अच्छी बारिश हो, तो फिर से देखें।")
    return "\n".join(head + [""] + en + ["", note]), "\n".join(hi + ["", hi_note])
