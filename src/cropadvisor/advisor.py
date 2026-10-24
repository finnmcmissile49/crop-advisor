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

from cropadvisor import irrigation as ir
from cropadvisor import openmeteo

SOIL_SCALES = (0.8, 1.0, 1.2)
EARLIEST_SOWING = (10, 15)   # PAU's schedule table starts with October sowing
LATEST_SOWING = (1, 15)      # PAU's last row: sown 21 December to 15 January
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


# ----------------------------------------------------------------------------------- inputs

def check_inputs(site, sowing, today, watered):
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    lo = ir._rabi_date(sowing, *EARLIEST_SOWING)
    hi = ir._rabi_date(sowing, *LATEST_SOWING)
    if not lo <= sowing <= hi:
        raise AdviceError("The calculator is set up for wheat sown between 15 October and "
                          f"15 January. {sowing:%d %b %Y} is outside that.")
    if site.zone not in ir.ZONES:
        raise AdviceError(f"No wheat settings for zone {site.zone}.")
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


def advise(site, sowing, today, watered, weather, depth_mm=None, mode="live"):
    """Advice as a dict (see render). weather: date, rain_mm, et0_mm, forecast."""
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
           "forecast_end": end}

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
    for scale in SOIL_SCALES:
        p = ir.zone_params(site.zone, site.awc_mm_per_m * scale, state=site.state)
        day, run = _trigger_day(weather, sowing, p, watered, depth_mm, today, min(cutoff, end))
        days[scale] = day
        if scale == 1.0:
            row = run[run["date"] == today].iloc[0]
            out.update(raw_used_pct=round(100 * row["dr_mm"] / row["raw_mm"]) if row["raw_mm"]
                       else 0, dr_mm=round(float(row["dr_mm"]), 1),
                       taw_mm=round(float(row["taw_mm"]), 1))
    found = [d for d in days.values() if d is not None]
    covers_season = end >= cutoff   # forecast reaches the last irrigation date
    quiet = {"recheck": min(today + pd.Timedelta(days=RECHECK_DAYS), cutoff),
             "horizon_days": (end - today).days, "covers_season": covers_season}
    likely = days[1.0]
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
            "heavy_soil_later": days[1.2] is None,   # heavier soil: later than the horizon
            "heavy_soil_none": days[1.2] is None and covers_season}


# ----------------------------------------------------------------------------------- render

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]


def _en(d):
    return f"{d.day} {d:%b %Y}"


def _hi(d):
    return f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}"


def _in(d, today):
    return (d - today).days


def render(a):
    """English and Hindi text for the advice dict. Units farmers use: days, dates, cm, inches."""
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
    elif st == "water_now":
        en.append("WATER TODAY OR TOMORROW: the soil has used up its easily available water.")
        hi.append("आज या कल सिंचाई करें: मिट्टी में आसानी से मिलने वाला पानी ख़त्म हो गया है।")
    elif st == "water_window":
        e, l, k = a["earliest"], a["latest"], a["likely"]
        en.append(f"NEXT WATERING: most likely around {_en(k)} (in {_in(k, today)} days).")
        hi.append(f"अगली सिंचाई: सबसे संभावित {_hi(k)} के आसपास ({_in(k, today)} दिन में)।")
        if e < k:
            en.append(f"If your soil is light or sandy, as early as {_en(e)}.")
            hi.append(f"हल्की या रेतीली मिट्टी हो तो पहले, {_hi(e)} के आसपास।")
        if a["heavy_soil_none"]:
            en.append("If your soil is heavy (holds more water), maybe no more watering this "
                      "season.")
            hi.append("भारी मिट्टी हो (ज़्यादा पानी रोके) तो शायद इस मौसम में और सिंचाई न लगे।")
        elif a["heavy_soil_later"]:
            en.append(f"If your soil is heavy, later than {_en(a['forecast_end'])}.")
            hi.append(f"भारी मिट्टी हो तो {_hi(a['forecast_end'])} के बाद।")
        elif l > k:
            en.append(f"If your soil is heavy, as late as {_en(l)}.")
            hi.append(f"भारी मिट्टी हो तो {_hi(l)} तक।")
    elif st == "light_soil_only":
        if a["covers_season"]:
            en.append("PROBABLY NO MORE WATERING NEEDED this season.")
            hi.append("शायद इस मौसम में और सिंचाई की ज़रूरत नहीं।")
        else:
            en.append(f"PROBABLY NO WATERING NEEDED in the next {a['horizon_days']} days. "
                      f"Check again on {_en(a['recheck'])}.")
            hi.append(f"अगले {a['horizon_days']} दिन शायद सिंचाई की ज़रूरत नहीं। "
                      f"{_hi(a['recheck'])} को फिर देखें।")
        en.append(f"But if your soil is light or sandy, water around {_en(a['light_soil_day'])}.")
        hi.append(f"लेकिन हल्की या रेतीली मिट्टी हो तो {_hi(a['light_soil_day'])} के आसपास "
                  "सिंचाई करें।")
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
    note = ("How sure is this? It uses free weather data for the whole district and an "
            "estimated soil, not your own field, and it has not yet been checked against real "
            "fields. 'Light' and 'heavy' soil show how the answer changes if the soil holds 20 "
            "percent less or more water than estimated. If it rains well before the date, "
            "check again.")
    hi_note = ("यह सलाह ज़िले के मुफ़्त मौसम आँकड़ों और अनुमानित मिट्टी पर आधारित है, आपके खेत पर "
               "नहीं, और अभी असली खेतों में जाँची नहीं गई है। अगर बीच में अच्छी बारिश हो, तो फिर से "
               "देखें।")
    return "\n".join(head + [""] + en + ["", note]), "\n".join(hi + ["", hi_note])


def i_do_not_know(reason):
    return (f"I do not know: {reason}", f"मैं नहीं बता सकता: {reason}")
