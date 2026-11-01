"""One call from request to advice, shared by the calculator script and the web server.

    advise_request({"district": "Hisar", "sowing": "2026-11-10", "watered": ["2026-12-01"],
                    "crop": "wheat", "lat": 29.2, "lon": 75.6, "soil_type": "loam"})

Returns {"ok": True, "advice": {...JSON...}, "extras": {...}, "text_en": "...", "text_hi": "..."}
or {"ok": False, "error": "...", "text_en": "I do not know: ...", "text_hi": "..."}.

    outlook_request({"district": "Hisar"})   season-start yields and prices (outlook.py)

Data used: Open-Meteo (ET0, forecast, recorded rain where NASA POWER has none), NASA POWER
(recorded rain), SoilGrids or the farmer's soil type (water-holding), and as district background
IMD rain normals, Soil Health Card results, ICRISAT/DES yields and CEDA/Agmarknet prices.
"""
import pandas as pd

from cropadvisor import advisor
from cropadvisor import crops as cr
from cropadvisor import extras, nasapower, sites
from cropadvisor import outlook as ol


def advise_request(req, now=None, fetch_history=None, fetch_forecast=None, fetch_soil=None,
                   locations=sites.LOCATIONS, soil_files=sites.SOIL_FILES, fetch_power="auto",
                   with_extras=True):
    """fetch_power: "auto" uses NASA POWER for recorded rain, except when made-up Open-Meteo
    fetchers are passed (offline tests) or req["rain_source"] == "openmeteo"; None turns it off;
    or pass a fetcher."""
    if fetch_power == "auto":
        off = fetch_history is not None or fetch_forecast is not None or \
            req.get("rain_source") == "openmeteo"
        fetch_power = None if off else nasapower.fetch_history
    try:
        crop = req.get("crop") or "wheat"
        if crop != "wheat" and crop not in cr.CROPS:
            raise advisor.AdviceError(f"Unknown crop '{crop}'. Crops: wheat, "
                                      f"{', '.join(cr.CROPS)}.")
        if not req.get("district") or not req.get("sowing"):
            raise advisor.AdviceError("district and sowing date are needed.")
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
                                            fetch_power=fetch_power)
        if "power_error" in weather.attrs:
            notes = notes + [("power_failed",
                              "NASA POWER could not be reached, so the recorded rain is from "
                              "Open-Meteo only.",
                              "NASA POWER से संपर्क नहीं हो सका, इसलिए दर्ज बारिश केवल Open-Meteo "
                              "से ली गई है।")]
        depth = req.get("depth_cm")
        a = advisor.advise(site, sowing, today, watered, weather,
                           depth_mm=float(depth) * 10 if depth else None, mode=mode, crop=crop)
        a["notes"] = notes
        en, hi = advisor.render(a)
        res = {"ok": True, "advice": advisor.to_json(a)}
        if with_extras:
            x = extras.build(a)
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


def outlook_request(req, now=None, locations=sites.LOCATIONS):
    """Season-start outlook for a district: {"ok", "outlook": [...], "text_en", "text_hi"}."""
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
        outs = ol.district_outlook(name, state, today, keys)
        en, hi = ol.render(outs, name, state)
        return {"ok": True, "outlook": advisor._jsonable(outs), "text_en": en, "text_hi": hi}
    except advisor.AdviceError as e:
        msg = str(e)
    en, hi = advisor.i_do_not_know(msg)
    return {"ok": False, "error": msg, "text_en": en, "text_hi": hi}
