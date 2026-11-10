"""One call from request to advice, shared by the calculator script and the web server.

    advise_request({"district": "Hisar", "sowing": "2026-11-10", "watered": ["2026-12-01"],
                    "crop": "wheat", "lat": 29.2, "lon": 75.6, "soil_type": "loam"})

Returns {"ok": True, "advice": {...JSON...}, "extras": {...}, "text_en": "...", "text_hi": "..."}
or {"ok": False, "error": "...", "text_en": "I do not know: ...", "text_hi": "..."}.

    outlook_request({"district": "Hisar", "season": "rabi"})   season outlook (outlook.py) and the
                                                 season-start model (seasonmodel.py)

Data used: Open-Meteo (ET0, forecast, recorded rain where NASA POWER has none), NASA POWER
(recorded rain), SoilGrids or the farmer's soil type (water-holding), and as district background
IMD rain normals, Soil Health Card results, ICRISAT/DES yields and CEDA/Agmarknet prices.
"""
import os

import pandas as pd

from cropadvisor import advisor
from cropadvisor import crops as cr

from cropadvisor import extras, fusion, imd, nasapower, sites, station
from cropadvisor import irrigation as ir
from cropadvisor import outlook as ol
from cropadvisor import sentinel
from cropadvisor import soilcard as sc


def advise_request(req, now=None, fetch_history=None, fetch_forecast=None, fetch_soil=None,
                   locations=sites.LOCATIONS, soil_files=sites.SOIL_FILES, fetch_power="auto",
                   with_extras=True, fetch_imd="auto", fetch_sentinel="auto"):
    """fetch_power: "auto" uses NASA POWER for recorded rain, except when made-up Open-Meteo
    fetchers are passed (offline tests) or req["rain_source"] == "openmeteo"; None turns it off;
    or pass a fetcher."""
    off = fetch_history is not None or fetch_forecast is not None or \
        req.get("rain_source") == "openmeteo"
    if fetch_power == "auto":
        fetch_power = None if off else nasapower.fetch_history
    if fetch_imd == "auto":
        fetch_imd = None if off else (lambda la, lo, s, e: imd.point_rain(
            la, lo, s, e, cache_dir=os.path.join(sites.ROOT, "data", "raw", "imd")))
    if fetch_sentinel == "auto":   # only for a real field point; a district point means nothing
        fetch_sentinel = None if off else sentinel.field_ndvi
    try:
        crop = req.get("crop") or "wheat"
        if crop != "wheat" and crop not in cr.CROPS:
            raise advisor.AdviceError(f"Unknown crop '{crop}'. Crops: wheat, "
                                      f"{', '.join(cr.CROPS)}.")
        if not req.get("district") or not req.get("sowing"):
            raise advisor.AdviceError("district and sowing date are needed.")
        card = sc.farmer_card(parse_card(req.get("soil_card")))
        site, notes = sites.build_site(req["district"], req.get("lat"), req.get("lon"),
                                       req.get("soil_type") or None, locations, soil_files,
                                       fetch_soil)
        sowing = pd.Timestamp(req["sowing"])
        now_ts = pd.Timestamp(now) if now is not None else pd.Timestamp.today().normalize()
        today = pd.Timestamp(req["today"]) if req.get("today") else now_ts
        watered = list(req.get("watered") or [])
        if crop == "wheat":
            advisor.check_inputs(site, sowing, today, watered)
        else:
            advisor.check_crop_inputs(cr.get(crop), site, sowing, today, watered)
        weather, mode = advisor.get_weather(site.lat, site.lon, sowing, today, now=now_ts,
                                            fetch_history=fetch_history,
                                            fetch_forecast=fetch_forecast,
                                            fetch_power=fetch_power, fetch_imd=fetch_imd)
        if "power_error" in weather.attrs:
            notes = notes + [("power_failed",
                              "NASA POWER could not be reached, so the recorded rain is from "
                              "Open-Meteo only.",
                              "NASA POWER से संपर्क नहीं हो सका, इसलिए दर्ज बारिश केवल Open-Meteo "
                              "से ली गई है।")]
        depth = req.get("depth_cm")
        depth_mm = float(depth) * 10 if depth else None
        corr, st_info = None, None
        if req.get("station"):
            corr, st_info = station_fusion(req, site, sowing, today, watered, weather, crop,
                                           depth_mm)
        a = advisor.advise(site, sowing, today, watered, weather, depth_mm=depth_mm, mode=mode,
                           crop=crop, correction=corr)
        if st_info is not None:
            base = advisor.advise(site, sowing, today, watered, weather, depth_mm=depth_mm,
                                  mode=mode, crop=crop)
            d_with, d_without = key_date(a), key_date(base)
            a["station"] = st_info
            a["date_without_station"] = "same" if d_with == d_without else d_without
        a["notes"] = notes
        en, hi = advisor.render(a)
        res = {"ok": True, "advice": advisor.to_json(a)}
        if with_extras:
            x = extras.build(a, soil_card=card)
            if fetch_sentinel is not None and req.get("lat") is not None and \
                    req.get("lon") is not None:
                try:
                    x["sentinel"] = fetch_sentinel(float(req["lat"]), float(req["lon"]), today)
                except Exception as e:   # satellite is background: never block the advice
                    x["sentinel"] = {"error": str(e)[:150]}
            x_en, x_hi = extras.text(a, x)
            en, hi = en + "\n" + "\n".join(x_en) if x_en else en, \
                hi + "\n" + "\n".join(x_hi) if x_hi else hi
            res["extras"] = advisor._jsonable(x)
        return {**res, "text_en": en, "text_hi": hi}
    except advisor.AdviceError as e:
        msg = str(e)
    except (ValueError, TypeError) as e:
        msg = f"could not read the input ({e})."
    except Exception as e:   # network or service errors: say so plainly
        msg = (f"could not get the weather data ({str(e)[:150]}). Check the internet connection "
               "and try again.")
    en, hi = advisor.i_do_not_know(msg)
    return {"ok": False, "error": msg, "text_en": en, "text_hi": hi}


def parse_card(card):
    """The farmer's card as a dict, or from text like "n=low p=medium zn=deficient"."""
    if not card:
        return {}
    if isinstance(card, dict):
        return card
    items = card.split() if isinstance(card, str) else list(card)
    out = {}
    for it in items:
        if "=" not in it:
            raise ValueError(f"Soil Health Card item '{it}' should look like n=low")
        k, v = it.split("=", 1)
        out[k] = v
    return out


def key_date(a):
    """The date an advice points to (for comparing advice with and without the station)."""
    st = a["status"]
    if st == "water_now":
        return a["today"]
    if st == "water_window":
        return a["likely"]
    if st == "wait_for_rain":
        return a["water_if_dry"]
    if st.startswith("first_"):
        return a["first_day"]
    return None


def station_fusion(req, site, sowing, today, watered, weather, crop, depth_mm):
    """Run the Kalman filter on the farm station's readings. Returns (correction, info)."""
    readings, report = station.prepare(req["station"])
    soil = sites.district_soil(site.name) or {}
    fc = float(req.get("field_capacity") or soil.get("field_capacity") or 0)
    if not fc:
        raise advisor.AdviceError("The station needs the soil's field capacity (no soil data for "
                                  "this district): give field_capacity.")
    likely = advisor.soil_cases(site)["likely"]
    if crop == "wheat":
        params = ir.zone_params(site.zone, likely, state=site.state)
        depth = float(depth_mm or ir.first_watering(site.state, sowing)[3])
    else:
        params = cr.get(crop).params(likely)
        depth = depth_mm
    out, corr = fusion.run(weather, sowing, today, params, watered, depth, readings, fc)
    if out is None:
        return None, None
    info = fusion.summary(out, readings, report)
    info["correction"] = corr
    info["field_capacity"] = fc
    has_reading = info["last_reading"] is not None
    return (corr if has_reading else None), info


def next_season(today):
    """The next season to be sown: rabi from July to December, kharif from January to June."""
    return "rabi" if pd.Timestamp(today).month >= 7 else "kharif"


def outlook_request(req, now=None, locations=sites.LOCATIONS, with_model=True):
    """Season-start outlook for a district: {"ok", "outlook": [...], "season_model": {...},
    "text_en", "text_hi"}. req["season"]: "rabi" or "kharif" (default: the next to be sown)."""
    try:
        if not req.get("district"):
            raise advisor.AdviceError("district is needed.")
        loc = pd.read_csv(ol.YIELDS)
        match = loc[loc["district"].str.lower() == str(req["district"]).strip().lower()]
        if match.empty:
            row = sites.district_row(req["district"], locations)   # raises if unknown
            name, state = row["name"], row["state"]
        else:
            name, state = match["district"].iloc[0], match["state"].iloc[0]
        if state not in ol.STATES:
            raise advisor.AdviceError(f"The season outlook covers Haryana and Punjab only (district "
                                      f"yields and prices are set up there). {name} is in "
                                      f"{state}.")
        today = pd.Timestamp(req["today"]) if req.get("today") else (
            pd.Timestamp(now) if now is not None else pd.Timestamp.today().normalize())
        keys = [req["crop"]] if req.get("crop") else None
        if keys and keys[0] not in ol.CROPS:
            raise advisor.AdviceError(f"Unknown crop '{keys[0]}'. Crops: {', '.join(ol.CROPS)}.")
        from cropadvisor import prices as pr
        live = (lambda c, s, d: pr.live_price(c, s, d)) if os.environ.get("DATA_GOV_IN_KEY") \
            else None
        outs = ol.district_outlook(name, state, today, keys, live_price_fn=live)
        en, hi = ol.render(outs, name, state, prices_only=with_model)
        res = {"ok": True, "outlook": advisor._jsonable(outs)}
        if with_model:
            from cropadvisor import seasonmodel as sm
            season = req.get("season") or next_season(today)
            if season not in ("rabi", "kharif"):
                raise advisor.AdviceError("season must be rabi or kharif.")
            so = sm.season_outlook(name, state, season, today)
            res["season_model"] = advisor._jsonable(so)
            m_en, m_hi = sm.text(so)
            if m_en:
                en, hi = "\n".join(m_en) + "\n\n" + en, "\n".join(m_hi) + "\n\n" + hi
        return {**res, "text_en": en, "text_hi": hi}
    except advisor.AdviceError as e:
        msg = str(e)
    en, hi = advisor.i_do_not_know(msg)
    return {"ok": False, "error": msg, "text_en": en, "text_hi": hi}
