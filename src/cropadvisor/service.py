"""One call from request to advice, shared by the calculator script and the web server.

    advise_request({"district": "Hisar", "sowing": "2026-11-10", "watered": ["2026-12-01"],
                    "crop": "wheat", "lat": 29.2, "lon": 75.6, "soil_type": "loam"})

Returns {"ok": True, "advice": {...JSON...}, "text_en": "...", "text_hi": "..."} or
{"ok": False, "error": "...", "text_en": "I do not know: ...", "text_hi": "..."}.
"""
import pandas as pd

from cropadvisor import advisor
from cropadvisor import crops as cr
from cropadvisor import sites


def advise_request(req, now=None, fetch_history=None, fetch_forecast=None, fetch_soil=None,
                   locations=sites.LOCATIONS, soil_files=sites.SOIL_FILES):
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
                                            fetch_forecast=fetch_forecast)
        depth = req.get("depth_cm")
        a = advisor.advise(site, sowing, today, watered, weather,
                           depth_mm=float(depth) * 10 if depth else None, mode=mode, crop=crop)
        a["notes"] = notes
        en, hi = advisor.render(a)
        return {"ok": True, "advice": advisor.to_json(a), "text_en": en, "text_hi": hi}
    except advisor.AdviceError as e:
        msg = str(e)
    except (ValueError, TypeError) as e:
        msg = f"could not read the input ({e})."
    except Exception as e:   # network or service errors: say so plainly
        msg = (f"could not get the weather data ({str(e)[:150]}). Check the internet connection "
               "and try again.")
    en, hi = advisor.i_do_not_know(msg)
    return {"ok": False, "error": msg, "text_en": en, "text_hi": hi}
