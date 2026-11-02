"""District background added to every irrigation advice: IMD rain normals, Soil Health Card
results, and the district's usual yield and last harvest price for the crop.

None of these changes the watering date. The date comes from the water balance (Open-Meteo ET0 and
forecast, NASA POWER or Open-Meteo recorded rain, SoilGrids or the farmer's soil type). These are
shown beside it so the farmer and the field team see what the public data say about the district.
"""
from cropadvisor import outlook as ol
from cropadvisor import rainnormals as rn
from cropadvisor import sentinel
from cropadvisor import soilcard as sc

# calculator crop key -> outlook crop key (the outlook has paddy, the calculator does not)
OUTLOOK_KEY = {k: k for k in ol.CROPS}


def build(a, soil_card=None):
    """Dict of extras for an advice dict (see advisor.advise). soil_card: the farmer's own Soil
    Health Card ratings, already checked by soilcard.farmer_card."""
    s = a["site"]
    rec = a.get("rain_record") or {}
    x = {"rain": rn.context(s.name, a["sowing"], a["today"], rec.get("rain_used_mm"),
                            a["forecast_end"]),
         "soil_card": sc.summary(s.name, s.state),
         "outlook": ol.crop_outlook(s.name, s.state, OUTLOOK_KEY.get(a.get("crop", "wheat"),
                                                                     "wheat"), a["today"],
                                    season=a["sowing"].year)}
    if soil_card:
        x["farmer_card"] = soil_card
    return x


def text(a, x):
    """English and Hindi lines, under a heading."""
    en, hi = [], []
    e, h = rn.text(x.get("rain"))
    en += e
    hi += h
    e, h = sc.farmer_card_text(x.get("farmer_card"), x.get("soil_card"))
    en += e
    hi += h
    e, h = sc.text(a["site"].name, x.get("soil_card"))
    en += e
    hi += h
    e, h = sentinel.text(x.get("sentinel"))
    en += e
    hi += h
    o = x.get("outlook")
    if o and (o.get("yield") or o.get("price")):
        e, h = ol.text(o)
        en += e
        hi += h
    if not en:
        return [], []
    return (["", "About your district (background; it does not change the date):"] + en,
            ["", "आपके ज़िले के बारे में (जानकारी; इससे तारीख़ नहीं बदलती):"] + hi)
