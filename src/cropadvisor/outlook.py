"""Season-start crop outlook for a Haryana or Punjab district: what the crop usually yields in the
district, what it sold for at the last harvest, and the gross value per acre that implies.

This is information, not a crop recommendation. Farmers' crop choice here depends on things not in
these tables (assured procurement, water, the previous crop, machinery, labour), and the figures
are district averages, not a farm's yield (notes/ml-limitations section 6).

Yield: the average of the district's last YIELD_YEARS years with data (ICRISAT 2009-2019, DES
2020-2022; data/reference/district_yields.csv). Chosen on 2015-2018 against the long-run district
mean and a linear trend (it was best or within 0.02 quintal per acre of best for all three crops),
then tested on 2019-2022 (scripts/check_outlook.py, data/checks/yield_outlook_*.csv). The range is
the 10th to 90th percentile of past errors at the same distance ahead of the data (the data end in
2022, so a 2026 season is 4 years ahead).

Price: the average monthly modal mandi price in the harvest months (CEDA / Agmarknet,
data/reference/mandi_prices.csv), district level if the district has prices in the last three
seasons, else the state. Mandi prices are market prices, not what every farmer receives; most wheat
and paddy here is bought by the government at the minimum support price.

Units: quintal per acre and Rs per quintal. Rice yields in the data are milled rice; they are turned
into paddy at the official 67 percent out-turn (100 kg paddy gives 67 kg raw rice; Tariff Commission
2005 norm, CAG report 31 of 2015). Cotton yields are lint, its price is for seed cotton (kapas), and
the lint share of kapas varies a lot (22 to 44 percent, ITMF SpinCom report, India 2002), so no gross
value is given for cotton.
"""
import functools
import os

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
YIELDS = os.path.join(ROOT, "data", "reference", "district_yields.csv")
PRICES = os.path.join(ROOT, "data", "reference", "mandi_prices.csv")

T_HA_TO_Q_ACRE = 10 / 2.47105          # 1 t/ha = 10 quintal per 2.471 acres
PADDY_PER_RICE = 1 / 0.67              # official raw-rice out-turn of paddy
YIELD_YEARS = 5
BAND = (0.10, 0.90)
DISTRICT_TOLERANCE = 0.25   # our choice
MAX_PRICE_AGE_YEARS = 2     # a latest harvest older than this is not shown
STATES = ("Haryana", "Punjab")

# crop key -> (English, Hindi, yield crop in the table or None, CEDA commodity, harvest months)
# Harvest months: from each crop's PAU season in crops.py (default sowing + season length) and the
# month after; wheat from the North Western Plains zone (10 November sowing, 152 days); paddy has
# no irrigation settings yet, so October-November (PAU: transplanting in June, harvest in October).
CROPS = {
    "wheat": ("Wheat", "गेहूँ", "Wheat", "Wheat", (4, 5)),
    "paddy": ("Paddy (rice)", "धान", "Rice", "Paddy(Dhan)(Common)", (10, 11)),
    "cotton": ("Cotton (narma)", "कपास (नरमा)", "Cotton", "Cotton", (10, 11)),
    "mustard": ("Mustard (raya)", "सरसों (राया)", None, "Mustard", None),
    "chickpea": ("Chickpea (gram)", "चना", None, "Bengal Gram (Gram)(Whole)", None),
    "barley": ("Barley", "जौ", None, "Barley (Jau)", None),
    "potato": ("Potato (autumn)", "आलू", None, "Potato", None),
    "spring_maize": ("Spring maize", "बसंत मक्का", None, "Maize", None),
    "summer_moong": ("Summer moong", "गर्मी की मूंग", None, "Green Gram (Moong)(Whole)", None),
    "kharif_maize": ("Kharif maize", "खरीफ़ मक्का", None, "Maize", None),
    "bajra": ("Bajra (pearl millet)", "बाजरा", None, "Bajra (Pearl Millet/Cumbu)", None),
    "kharif_moong": ("Kharif moong", "खरीफ़ मूंग", None, "Green Gram (Moong)(Whole)", None),
    "groundnut": ("Groundnut (kharif)", "मूंगफली", None, "Groundnut", None),
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]


def harvest_months(key):
    m = CROPS[key][4]
    if m:
        return m
    from cropadvisor import crops as cr
    spec = cr.get(key)
    mo, da = spec.default_sowing
    end = pd.Timestamp(2001, mo, da) + pd.Timedelta(days=spec.season_days)
    return (end.month, end.month % 12 + 1)


@functools.lru_cache(maxsize=2)
def _yields(path=YIELDS):
    if not os.path.exists(path):
        return None
    return pd.read_csv(path).dropna(subset=["yield_t_ha"])


@functools.lru_cache(maxsize=2)
def _prices(path=PRICES):
    if not os.path.exists(path):
        return None
    p = pd.read_csv(path)
    p["date"] = pd.to_datetime(p["month"] + "-01")
    return p


# ------------------------------------------------------------------------------- yields

def predict(series, upto_year, n=YIELD_YEARS):
    """Average of the last n yields with data up to upto_year. series: year -> yield."""
    s = series[series.index <= upto_year].sort_index().tail(n)
    return float(s.mean()) if len(s) >= 3 else None


@functools.lru_cache(maxsize=16)
def error_band(crop, horizon, path=YIELDS):
    """10th and 90th percentile of (actual - prediction), t/ha, pooled over districts, for a
    prediction made `horizon` years after the last year of data used. Returns (lo, hi, n)."""
    y = _yields(path)
    errs = []
    for _, g in y[y["crop"] == crop].groupby("district"):
        s = g.set_index("year")["yield_t_ha"]
        for yr, actual in s.items():
            p = predict(s, yr - horizon)
            if p is not None and len(s[s.index <= yr - horizon]) >= YIELD_YEARS:
                errs.append(actual - p)
    if len(errs) < 20:
        return None
    return float(np.quantile(errs, BAND[0])), float(np.quantile(errs, BAND[1])), len(errs)


def yield_outlook(district, crop, season_year, path=YIELDS):
    """Expected district yield for the season (q/acre) with a range, or None."""
    y = _yields(path)
    if y is None:
        return None
    g = y[(y["district"].str.lower() == district.lower()) & (y["crop"] == crop)]
    if len(g) < 3:
        return None
    s = g.set_index("year")["yield_t_ha"].sort_index()
    s = s[s.index < season_year]   # only years before the season (matters for past-season tests)
    if len(s) < 3:
        return None
    last = int(s.index.max())
    p = predict(s, last)
    if p is None:
        return None
    horizon = int(min(max(season_year - last, 1), 5))
    band = error_band(crop, horizon, path)
    used = s.tail(YIELD_YEARS)
    conv = T_HA_TO_Q_ACRE * (PADDY_PER_RICE if crop == "Rice" else 1.0)
    out = {"crop": crop, "expected_q_acre": round(p * conv, 1),
           "years": (int(used.index.min()), int(used.index.max())), "n_years": len(used),
           "horizon_years": horizon,
           "sources": sorted(g[g["year"].isin(used.index)]["source"].unique()),
           "unit": "quintal lint per acre" if crop == "Cotton" else (
               "quintal paddy per acre" if crop == "Rice" else "quintal per acre")}
    if band:
        out["low_q_acre"] = round(max(p + band[0], 0) * conv, 1)
        out["high_q_acre"] = round((p + band[1]) * conv, 1)
        out["band_n"] = band[2]
    return out


# ------------------------------------------------------------------------------- prices

def _seasons(rows, months, today, n_seasons):
    """Mean modal price per season (labelled by the year of its first harvest month)."""
    if rows.empty:
        return pd.Series(dtype=float)
    yr = rows["date"].dt.year - np.where(rows["date"].dt.month < months[0], 1, 0)
    s = rows.assign(season=yr).groupby("season")["p_modal"].mean().sort_index()
    return s[s.index >= today.year - n_seasons - 1].tail(n_seasons)


def price_outlook(district, state, commodity, months, today, path=PRICES, n_seasons=3):
    """Mean modal price (Rs/quintal) in the harvest months of the last n_seasons seasons that have
    prices before `today`. District seasons more than DISTRICT_TOLERANCE away from the state price
    that season are dropped (a district with few sales can show odd prices, e.g. Sangrur cotton
    Rs 2,500 in 2022); the district is used if it still has the latest season, else the state."""
    p = _prices(path)
    if p is None:
        return None
    today = pd.Timestamp(today)
    c = p[(p["commodity"] == commodity) & (p["state"] == state) & (p["date"] < today)
          & p["date"].dt.month.isin(months)]
    st = _seasons(c[c["level"] == "state"], months, today, n_seasons)
    st_all = _seasons(c[c["level"] == "state"], months, today, n_seasons + 2)
    dist = _seasons(c[(c["level"] == "district")
                      & (c["district"].str.lower() == str(district).lower())], months, today,
                    n_seasons)
    note = None
    level, seasons = "state", st
    if not dist.empty:
        ok = [s for s in dist.index
              if s not in st_all.index or abs(dist[s] / st_all[s] - 1) <= DISTRICT_TOLERANCE]
        if len(ok) < len(dist):
            note = "district_unusual_dropped"
        dist = dist[ok]
        if not dist.empty and (st.empty or dist.index[-1] >= st.index[-1]):
            level, seasons = "district", dist
    if seasons.empty or seasons.index[-1] < today.year - MAX_PRICE_AGE_YEARS:
        return None   # no price in the last few seasons: say nothing rather than an old price
    return {"level": level, "commodity": commodity, "months": tuple(months),
            "latest_season": int(seasons.index[-1]), "price": round(float(seasons.iloc[-1])),
            "seasons": {int(k): round(float(v)) for k, v in seasons.items()},
            "low": round(float(seasons.min())), "high": round(float(seasons.max())),
            "note": note}


# ------------------------------------------------------------------------------- together

def season_year(key, today):
    """The year of the season a farmer is planning at `today`: the next sowing of this crop."""
    today = pd.Timestamp(today)
    if key == "wheat":
        return today.year if today.month <= 11 else today.year + 1
    if key == "paddy":
        return today.year if today.month <= 6 else today.year + 1
    from cropadvisor import crops as cr
    mo, _ = cr.get(key).sowing_window[1]
    return today.year if today.month <= mo else today.year + 1


def crop_outlook(district, state, key, today, yields_path=YIELDS, prices_path=PRICES,
                 season=None):
    """Everything for one crop in one district, or None outside Haryana and Punjab.
    season: the data year of the season (the sowing year); default the next sowing after today."""
    if state not in STATES or key not in CROPS:
        return None
    en, hi, ycrop, commodity, _ = CROPS[key]
    months = harvest_months(key)
    out = {"key": key, "en": en, "hi": hi, "district": district, "state": state,
           "season_year": int(season) if season is not None else season_year(key, today)}
    out["yield"] = yield_outlook(district, ycrop, out["season_year"], yields_path) if ycrop else None
    out["price"] = price_outlook(district, state, commodity, months, today, prices_path)
    y, pr = out["yield"], out["price"]
    if y and pr and ycrop != "Cotton":
        out["gross_rs_acre"] = int(round(y["expected_q_acre"] * pr["price"], -2))
        if "low_q_acre" in y:
            out["gross_low_rs_acre"] = int(round(y["low_q_acre"] * pr["low"], -2))
            out["gross_high_rs_acre"] = int(round(y["high_q_acre"] * pr["high"], -2))
    return out


def district_outlook(district, state, today, keys=None):
    keys = keys or list(CROPS)
    return [o for o in (crop_outlook(district, state, k, today) for k in keys)
            if o and (o["yield"] or o["price"])]


def _rs(x):
    return f"Rs {x:,}"


def _months_en(pr):
    a, b = pr["months"]
    yr = pr["latest_season"]
    return f"{MONTHS[a - 1]}-{MONTHS[b - 1]} {yr}" if b > a else f"{MONTHS[a - 1]} {yr}-" \
        f"{MONTHS[b - 1]} {yr + 1}"


def _months_hi(pr):
    a, b = pr["months"]
    return f"{HI_MONTHS[a - 1]}-{HI_MONTHS[b - 1]} {pr['latest_season']}"


def text(o, short=False):
    """English and Hindi lines for one crop outlook."""
    en, hi = [], []
    y, pr = o.get("yield"), o.get("price")
    name_en, name_hi, d = o["en"], o["hi"], o["district"]
    if y:
        unit_en = {"quintal lint per acre": "quintal of lint per acre",
                   "quintal paddy per acre": "quintal of paddy per acre"}.get(y["unit"],
                                                                         "quintal per acre")
        rng = (f" (in 8 of 10 past cases between {y['low_q_acre']:g} and {y['high_q_acre']:g})"
               if "low_q_acre" in y else "")
        en.append(f"{name_en} yield in {d} district: about {y['expected_q_acre']:g} {unit_en}, the "
                  f"average of {y['years'][0]}-{y['years'][1]}{rng}.")
        hi.append(f"{d} ज़िले में {name_hi} की औसत पैदावार: लगभग {y['expected_q_acre']:g} क्विंटल "
                  f"प्रति एकड़ ({y['years'][0]}-{y['years'][1]} का औसत)।")
    if pr:
        where_en = f"{d} mandis" if pr["level"] == "district" else f"{o['state']} mandis"
        where_hi = f"{d} की मंडियों" if pr["level"] == "district" else f"{o['state']} की मंडियों"
        n = len(pr["seasons"])
        spread = (f"; last {n} harvests {_rs(pr['low'])} to {_rs(pr['high'])}" if n > 1 else "")
        en.append(f"{name_en} price at the last harvest: about {_rs(pr['price'])} per quintal "
                  f"({where_en}, {_months_en(pr)}{spread}).")
        hi.append(f"पिछली फ़सल पर {name_hi} का भाव: लगभग {pr['price']:,} रुपये प्रति क्विंटल "
                  f"({where_hi} में, {_months_hi(pr)})।")
    if "gross_rs_acre" in o:
        rng = (f", range {_rs(o['gross_low_rs_acre'])} to {_rs(o['gross_high_rs_acre'])}"
               if "gross_low_rs_acre" in o else "")
        en.append(f"Gross value at that yield and price: about {_rs(o['gross_rs_acre'])} per acre"
                  f"{rng}, before costs.")
        hi.append(f"इस पैदावार और भाव पर कुल कीमत: लगभग {o['gross_rs_acre']:,} रुपये प्रति एकड़, "
                  "लागत घटाने से पहले।")
    elif y and pr and o["key"] == "cotton":
        en.append("No value per acre for cotton: the yield is lint, the price is for kapas, and "
                  "the lint share of kapas varies too much to convert.")
        hi.append("कपास की प्रति एकड़ कीमत नहीं दी गई: पैदावार रूई (लिंट) की है और भाव कपास "
                  "(बिनौले सहित) का।")
    if not short and (y or pr):
        en.append("District averages and market prices, not your field or your sale price; next "
                  "season's price is not predicted.")
        hi.append("ये ज़िले के औसत और मंडी भाव हैं, आपके खेत या आपके बिक्री भाव नहीं; अगले मौसम का "
                  "भाव नहीं बताया गया है।")
    return en, hi


def render(outlooks, district, state, prices_only=False):
    """Full English and Hindi text for --outlook. prices_only: leave out the yield and value
    lines (the season-start model gives those above it)."""
    if prices_only:
        head_en = [f"Last harvest prices in {district}, {state} (mandi averages):"]
        head_hi = [f"{district}, {state} में पिछली फ़सल के भाव (मंडी औसत):"]
    else:
        head_en = [f"Crop Advisor: season outlook for {district}, {state} (district data, not "
                   "advice)"]
        head_hi = [f"क्रॉप एडवाइज़र: {district}, {state} के लिए मौसम की जानकारी (ज़िले के आँकड़े, "
                   "सलाह नहीं)"]
    en, hi = list(head_en), list(head_hi)
    for o in outlooks:
        if prices_only:
            o = {**o, "yield": None}
            o.pop("gross_rs_acre", None)
        e, h = text(o, short=True)
        if prices_only:
            en += e
            hi += h
            continue
        en += [""] + e
        hi += [""] + h
    en += ["", "Yields: ICRISAT and DES district averages (production divided by area). Prices: "
           "CEDA / Agmarknet monthly mandi prices. These are district averages and market prices, "
           "not your field or your sale price, and next season's price is not predicted. Not a "
           "recommendation of what to grow: procurement, water, the previous crop and costs "
           "matter and are not included."]
    hi += ["", "पैदावार: ICRISAT और DES के ज़िला औसत। भाव: CEDA / एगमार्कनेट के मंडी भाव। ये ज़िले के "
           "औसत हैं, आपके खेत के नहीं, और अगले मौसम का भाव नहीं बताया गया है। क्या उगाएँ, इसकी सलाह "
           "नहीं: सरकारी ख़रीद, पानी, पिछली फ़सल और लागत इसमें शामिल नहीं हैं।"]
    return "\n".join(en), "\n".join(hi)
