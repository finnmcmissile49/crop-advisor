"""Digital twin: FAO's AquaCrop crop model (AquaCrop-OSPy, Foster et al. 2017) simulates whole
seasons, so the irrigation advice can be tested over many past years instead of waiting for one
harvest.

For a district, crop and season it runs the same weather four ways and compares the simulated
yield and water used:
    advice     the calculator's own rule (first watering at the guidance's stage, then the FAO-56
               trigger), its irrigation dates computed from the same weather by the calculator's
               water balance, each watering the usual fixed depth;
    calendar   PAU's schedule (Punjab) or ICAR-IIWBR's stage calendar (elsewhere) for wheat;
    rainfed    no irrigation after sowing;
    frequent   AquaCrop irrigates whenever soil water falls below 70 percent of available water
               (little water stress).
The useful numbers are relative: each strategy's yield as a share of the best of the four that
season, and the water it uses. ("frequent" is usually the best, but not always: in Ujjain 2021 the
advice schedule out-yielded it in AquaCrop, and rainfed cotton slightly out-yielded irrigated
cotton in Bathinda, both quirks of the uncalibrated crop files.)

Limits (say these with every result):
    - AquaCrop's built-in crop files are not calibrated for Indian varieties. Its stage lengths are
      scaled here to the calculator's season length (wheat 152 days in the North Western Plains),
      but canopy, water productivity and harvest index stay at the built-in values. Absolute yields
      are not predictions; they come out well above district averages (about 8.8 t/ha fully
      irrigated wheat in Hisar against a district average near 4.8). Calibrating against district
      yields is the next step.
    - The soil is AquaCrop's standard soil for the district's SoilGrids texture class, not the
      SoilGrids water-holding the calculator uses, so the two models do not see exactly the same
      soil.
    - Crops with a built-in AquaCrop file only: wheat, barley, cotton, maize (spring and kharif),
      potato. Mustard, chickpea, moong, bajra and groundnut have none, and no settings are made up.
    - The soil starts at field capacity (the pre-sowing irrigation PAU advises).
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

from cropadvisor import crops as cr
from cropadvisor import irrigation as ir
from cropadvisor import outlook as ol

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
WEATHER = os.path.join(ROOT, "data", "reference", "daily_weather_2021_2023.csv")

# calculator crop key -> AquaCrop built-in crop name
AQUACROP_CROPS = {"wheat": "Wheat", "barley": "Barley", "cotton": "Cotton",
                  "spring_maize": "Maize", "kharif_maize": "Maize", "potato": "Potato"}
STAGE_KEYS = ["EmergenceCD", "MaxRootingCD", "SenescenceCD", "MaturityCD", "HIstartCD",
              "FloweringCD", "YldFormCD"]
RATE_KEYS = ["CGC_CD", "CDC_CD"]
# USDA texture (soil.usda_texture) -> AquaCrop standard soil
SOILS = {"sand": "Sand", "loamy sand": "LoamySand", "sandy loam": "SandyLoam", "loam": "Loam",
         "silt loam": "SiltLoam", "silt": "Silt", "sandy clay loam": "SandyClayLoam",
         "clay loam": "ClayLoam", "silty clay loam": "SiltClayLoam", "sandy clay": "SandyClay",
         "silty clay": "SiltClay", "clay": "Clay"}
FULL_SMT = 70
MAX_IRR_MM = 120   # AquaCrop's default cap is 25 mm a day, below a flood irrigation (70-100 mm)
STRATEGIES = ("advice", "calendar", "rainfed", "frequent")


def _aquacrop():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import aquacrop
        return aquacrop
    except ImportError as e:   # pragma: no cover
        raise ImportError("AquaCrop is not installed: pip install aquacrop") from e


def _builtin(name):
    import aquacrop
    sys.path.insert(0, os.path.join(os.path.dirname(aquacrop.__file__), "entities", "crops"))
    from crop_params import crop_params
    return crop_params[name]


def crop_settings(key, season_days):
    """AquaCrop built-in crop with its calendar stages scaled to the calculator's season length
    (and its canopy growth and decline rates scaled the other way)."""
    name = AQUACROP_CROPS[key]
    p = _builtin(name)
    f = season_days / p["MaturityCD"]
    kw = {k: int(round(p[k] * f)) for k in STAGE_KEYS if k in p}
    kw.update({k: p[k] / f for k in RATE_KEYS if k in p})
    return name, kw


def season_days(key, zone="NWPZ"):
    if key == "wheat":
        return ir.ZONES[zone]["season_days"]
    return cr.get(key).season_days


def load_weather(path=WEATHER):
    """The committed 2021-2023 daily weather for the 27 districts (Open-Meteo temperatures, ET0 and
    rain; NASA POWER and IMD rain)."""
    return pd.read_csv(path, parse_dates=["date"])


def schedule(key, weather, sowing, awc, zone, state, depth_mm=None):
    """Irrigation dates the calculator's rule gives for this weather (advice) and the guidance
    calendar (calendar, wheat only). Returns {strategy: [(date, depth_mm), ...]}."""
    out = {}
    if key == "wheat":
        params = ir.zone_params(zone, awc, state=state)
        days = params.season_days
        inp = weather[["date", "rain_mm", "et0_mm"]].iloc[:days]
        first_depth = ir.first_watering(state, sowing)[3]
        rules = {"advice": ir.FirstWateringThenTrigger(state=state)}
        rules["calendar"] = (ir.PauCalendarRule(depth_mm=75.0) if state == "Punjab"
                             else ir.IiwbrCalendarRule())
        for name, rule in rules.items():
            run = ir.simulate(inp, sowing, params, rule)
            irr = run[run["irrigation_mm"] > 0]
            if name == "advice":   # the farmer gives the usual fixed depth each time
                out[name] = [(d, float(depth_mm or first_depth)) for d in irr["date"]]
            else:
                out[name] = list(zip(irr["date"], irr["irrigation_mm"].astype(float)))
    else:
        spec = cr.get(key)
        params = spec.params(awc)
        cols = [c for c in ("date", "rain_mm", "et0_mm", "rh_min", "wind_2m_ms") if c in weather]
        inp = weather[cols].iloc[:params.season_days]
        run = ir.simulate(inp, sowing, params, cr.CropRule(spec))
        irr = run[run["irrigation_mm"] > 0]
        out["advice"] = list(zip(irr["date"], irr["irrigation_mm"].astype(float)))
    return out


def run_aquacrop(key, weather, sowing, texture, irrigation=None, smt=None, zone="NWPZ"):
    """One AquaCrop season. irrigation: [(date, mm)] schedule; smt: soil-moisture threshold rule;
    neither: rainfed. Returns dict with dry yield (t/ha) and seasonal irrigation (mm)."""
    aq = _aquacrop()
    name, kw = crop_settings(key, season_days(key, zone))
    sowing = pd.Timestamp(sowing)
    end = sowing + pd.Timedelta(days=season_days(key, zone) + 40)
    w = weather[(weather["date"] >= sowing) & (weather["date"] <= end)]
    wdf = pd.DataFrame({"MinTemp": w["tmin"].to_numpy(), "MaxTemp": w["tmax"].to_numpy(),
                        "Precipitation": w["rain_mm"].to_numpy(),
                        "ReferenceET": w["et0_mm"].to_numpy(), "Date": w["date"].to_numpy()})
    crop = aq.Crop(name, planting_date=sowing.strftime("%m/%d"), **kw)
    soil = aq.Soil(SOILS.get(str(texture).lower(), "Loam"))
    if irrigation:
        sched = pd.DataFrame({"Date": pd.to_datetime([d for d, _ in irrigation]),
                              "Depth": [float(m) for _, m in irrigation]})
        im = aq.IrrigationManagement(irrigation_method=3, Schedule=sched, MaxIrr=MAX_IRR_MM)
    elif smt is not None:
        im = aq.IrrigationManagement(irrigation_method=1, SMT=[smt] * 4, MaxIrr=MAX_IRR_MM)
    else:
        im = aq.IrrigationManagement(irrigation_method=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = aq.AquaCropModel(sowing.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d"), wdf, soil,
                                 crop, aq.InitialWaterContent(value=["FC"]),
                                 irrigation_management=im)
        model.run_model(till_termination=True)
        r = model.get_simulation_results().iloc[0]
    return {"yield_t_ha": float(r["Dry yield (tonne/ha)"]),
            "irrigation_mm": float(r["Seasonal irrigation (mm)"]),
            "harvest": pd.Timestamp(r["Harvest Date (YYYY/MM/DD)"])}


def compare_strategies(key, district, sowing, weather, awc, texture, zone, state):
    """All strategies for one season. weather: date, tmin, tmax, rain_mm, et0_mm (from sowing)."""
    sowing = pd.Timestamp(sowing)
    w = weather[weather["date"] >= sowing].reset_index(drop=True)
    sch = schedule(key, w, sowing, awc, zone, state)
    rows = []
    for strat in STRATEGIES:
        if strat in ("advice", "calendar") and strat not in sch:
            continue
        res = run_aquacrop(key, w, sowing, texture,
                           irrigation=sch.get(strat) if strat in ("advice", "calendar") else None,
                           smt=FULL_SMT if strat == "frequent" else None, zone=zone)
        rows.append({"district": district, "crop": key, "sowing": sowing.date().isoformat(),
                     "strategy": strat,
                     "n_irrigations": len(sch.get(strat, [])) if strat in sch else None,
                     **res})
    df = pd.DataFrame(rows)
    best = df["yield_t_ha"].max()
    df["share_of_best_yield"] = (df["yield_t_ha"] / best).round(3) if best > 0 else np.nan
    df["yield_q_acre"] = (df["yield_t_ha"] * ol.T_HA_TO_Q_ACRE).round(1)
    return df


def text(df):
    """English and Hindi summary lines for one season's comparison."""
    en, hi = [], []
    names = {"advice": ("Calculator advice", "कैलकुलेटर की सलाह"),
             "calendar": ("Guidance calendar", "सिफ़ारिश वाला कैलेंडर"),
             "rainfed": ("No irrigation", "बिना सिंचाई"),
             "frequent": ("Frequent irrigation (below 70% available water)",
                          "बार-बार सिंचाई (70% उपलब्ध पानी से नीचे)")}
    for r in df.itertuples():
        n = "" if r.n_irrigations is None or pd.isna(r.n_irrigations) else \
            f", {int(r.n_irrigations)} waterings"
        pct = 100 * r.share_of_best_yield
        en.append(f"{names[r.strategy][0]}: {pct:.0f}% of the best yield, "
                  f"{r.irrigation_mm:.0f} mm of irrigation{n}.")
        hi.append(f"{names[r.strategy][1]}: सबसे अच्छी पैदावार का {pct:.0f}%, "
                  f"{r.irrigation_mm:.0f} मिमी सिंचाई।")
    en.append("AquaCrop with built-in crop settings (not calibrated for Indian varieties): compare "
              "the strategies with each other; the yields themselves are not predictions.")
    hi.append("AquaCrop की मूल फ़सल सेटिंग (भारतीय किस्मों के लिए जाँची नहीं गई): तरीक़ों की आपस में "
              "तुलना करें; पैदावार अनुमान नहीं है।")
    return en, hi
