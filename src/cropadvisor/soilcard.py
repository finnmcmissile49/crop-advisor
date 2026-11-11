"""Soil Health Card results for the district, as background for the farmer (not an input to the
water balance or to any model).

Source: the Soil Health Card dashboard's district nutrient status, cycles 2023-24 to 2026-27
(data/reference/soil_health_card.csv, built by scripts/build_reference_tables.py). It gives, per
district and cycle, how many samples were tested for each nutrient and how many were rated low
(or deficient). It does not give sample values, and results can swing between cycles (Bathinda
potassium rated low: 96, 40 and 8 percent in three cycles, with 9,000 to 18,000 samples each),
which looks more like a change in reporting than in the soil (not confirmed). So:

- a cycle counts only if at least MIN_SAMPLES samples were tested for that nutrient;
- if the counted cycles disagree by more than MAX_SPREAD_PP percentage points, no number is given,
  only that the results vary;
- the note always tells the farmer to get their own field tested.
"""
import functools
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
TABLE = os.path.join(ROOT, "data", "reference", "soil_health_card.csv")
MIN_SAMPLES = 500      # same threshold as the North India table (northindia.SHC_MIN_SAMPLES)
MAX_SPREAD_PP = 30     # our choice: wider than this between cycles is not a usable range

NUTRIENTS = {  # key: (English, Hindi), in the order shown
    "n": ("nitrogen", "नाइट्रोजन"),
    "p": ("phosphorus", "फ़ॉस्फ़ोरस"),
    "k": ("potassium", "पोटाश"),
    "oc": ("organic carbon", "जैविक कार्बन"),
    "zn": ("zinc", "ज़िंक"),
    "s": ("sulphur", "सल्फ़र"),
}


@functools.lru_cache(maxsize=1)
def _table(path=TABLE):
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def summary(name, state=None, path=TABLE):
    """Per nutrient: {"status": "range"|"varies"|"few_tests", "lo", "hi", "cycles", "samples"}.
    None if the district is not in the table."""
    t = _table(path)
    if t is None:
        return None
    g = t[t["name"].str.lower() == str(name).lower()]
    if state is not None:
        g = g[g["state"].str.lower() == str(state).lower()]
    if g.empty:
        return None
    out = {}
    for nut in NUTRIENTS:
        gn = g[(g["nutrient"] == nut) & (g["samples"] >= MIN_SAMPLES)]
        if gn.empty:
            out[nut] = {"status": "few_tests", "cycles": [], "samples": int(
                g.loc[g["nutrient"] == nut, "samples"].sum())}
            continue
        lo, hi = float(gn["pct_low"].min()), float(gn["pct_low"].max())
        out[nut] = {"status": "varies" if hi - lo > MAX_SPREAD_PP else "range",
                    "lo": round(lo), "hi": round(hi), "cycles": sorted(gn["cycle"].unique()),
                    "samples": int(gn["samples"].sum())}
    return out


def _pct(s):
    return f"{s['lo']}" if s["lo"] == s["hi"] else f"{s['lo']}-{s['hi']}"


def text(name, s):
    """English and Hindi lines for a summary (from summary())."""
    if not s:
        return [], []
    ranges = [(k, v) for k, v in s.items() if v["status"] == "range"]
    varies = [k for k, v in s.items() if v["status"] == "varies"]
    few = [k for k, v in s.items() if v["status"] == "few_tests"]
    cycles = sorted({c for v in s.values() for c in v.get("cycles", [])})
    period = f"{cycles[0][:4]}-{cycles[-1][-2:]}" if cycles else ""
    en, hi = [], []
    if ranges:
        parts_en = [f"{NUTRIENTS[k][0]} {_pct(v)}%" for k, v in ranges]
        parts_hi = [f"{NUTRIENTS[k][1]} {_pct(v)}%" for k, v in ranges]
        en.append(f"Soil tests in {name} district (Soil Health Card, {period}): share of tested "
                  f"fields rated low in {', '.join(parts_en)}.")
        hi.append(f"{name} ज़िले में मिट्टी जाँच (सॉइल हेल्थ कार्ड, {period}): जाँचे गए खेतों में कम "
                  f"पाए गए - {', '.join(parts_hi)}।")
    if varies:
        en.append(f"Results for {', '.join(NUTRIENTS[k][0] for k in varies)} changed a lot "
                  "between test rounds, so no figure is given.")
        hi.append(f"{', '.join(NUTRIENTS[k][1] for k in varies)} के नतीजे हर दौर में बहुत बदले, "
                  "इसलिए कोई आँकड़ा नहीं दिया गया।")
    if few:
        if len(few) == len(s):
            en.append(f"Soil Health Card: too few soil tests in {name} district to say anything "
                      "about its soils.")
            hi.append(f"सॉइल हेल्थ कार्ड: {name} ज़िले में इतनी कम जाँचें हुईं कि मिट्टी के बारे में "
                      "कुछ नहीं कहा जा सकता।")
        else:
            en.append(f"Too few tests for {', '.join(NUTRIENTS[k][0] for k in few)}.")
            hi.append(f"{', '.join(NUTRIENTS[k][1] for k in few)} की जाँचें बहुत कम हैं।")
    en.append("These are district figures, not your field. Get your own field tested (Soil Health "
              "Card) and give its ratings with --soil-card so the fertiliser doses follow them.")
    hi.append("ये ज़िले के आँकड़े हैं, आपके खेत के नहीं। अपने खेत की मिट्टी जाँच (सॉइल हेल्थ कार्ड) "
              "करवाएँ और उसकी रेटिंग --soil-card से दें ताकि खाद की मात्रा उसी के हिसाब से आए।")
    return en, hi


# --------------------------------------------------------------- refresh and the farmer's card

DASHBOARD_KEYS = {"n": "n", "p": "p", "k": "k", "S": "s", "OC": "oc", "pH": "ph", "EC": "ec",
                  "Fe": "fe", "Zn": "zn", "Cu": "cu", "B": "b", "Mn": "mn"}


def parse_dashboard(records):
    """The Soil Health Card nutrient dashboard's district records (as saved in
    01_raw_data/soil_health_card/shc_district_nutrient_status_raw.json) to one row per district and
    cycle: counts and percent of samples in each rating class per nutrient."""
    rows = []
    for r in records:
        row = {"cycle": r.get("cycle"), "state": r.get("state"), "state_code": r.get("state_code"),
               "district": r.get("district"), "district_code_lgd": r.get("district_code")}
        res = r.get("results") or {}
        for key, short in DASHBOARD_KEYS.items():
            classes = res.get(key) or {}
            n = sum(int(v or 0) for v in classes.values())
            for cls, v in classes.items():
                row[f"{short}_{cls.lower()}"] = int(v or 0)
            row[f"{short}_samples"] = n
            for cls, v in classes.items():
                row[f"pct_{short}_{cls.lower()}"] = round(100 * int(v or 0) / n, 1) if n else None
        row["samples"] = row.get("n_samples", 0)   # as in the processed table: nitrogen samples
        rows.append(row)
    return pd.DataFrame(rows)


# Ratings a farmer reads off their own card. The card states the rating for each nutrient, so no
# thresholds are applied here (they differ between states and labs).
CARD_RATINGS = {"n": ("low", "medium", "high"), "p": ("low", "medium", "high"),
                "k": ("low", "medium", "high"), "oc": ("low", "medium", "high"),
                "s": ("deficient", "sufficient"), "zn": ("deficient", "sufficient"),
                "ph": ("acidic", "neutral", "alkaline"), "ec": ("saline", "non-saline")}
RATING_HI = {"low": "कम", "medium": "मध्यम", "high": "ज़्यादा", "deficient": "कमी",
             "sufficient": "पर्याप्त", "acidic": "अम्लीय", "neutral": "सामान्य",
             "alkaline": "क्षारीय", "saline": "लवणीय", "non-saline": "सामान्य"}
EXTRA_NAMES = {"ph": ("pH", "pH"), "ec": ("salinity (EC)", "लवणता (EC)")}


def farmer_card(card):
    """Check the ratings a farmer typed from their own Soil Health Card. card: {nutrient: rating}.
    Returns the cleaned dict; raises ValueError for an unknown nutrient or rating."""
    out = {}
    for k, v in (card or {}).items():
        k2, v2 = str(k).strip().lower(), str(v).strip().lower().replace("_", "-")
        if k2 not in CARD_RATINGS:
            raise ValueError(f"unknown Soil Health Card item '{k}' (use: {', '.join(CARD_RATINGS)})")
        if v2 not in CARD_RATINGS[k2]:
            raise ValueError(f"{k}: rating must be one of {', '.join(CARD_RATINGS[k2])}")
        out[k2] = v2
    return out


def farmer_card_text(card, district_summary=None):
    """English and Hindi lines for the farmer's own card, with the district's share alongside."""
    if not card:
        return [], []
    names = {**{k: v for k, v in NUTRIENTS.items()}, **EXTRA_NAMES}
    parts_en, parts_hi = [], []
    for k, v in card.items():
        en_name, hi_name = names[k]
        extra = ""
        s = (district_summary or {}).get(k)
        if s and s["status"] == "range" and v in ("low", "deficient"):
            extra = f" (district: {_pct(s)}% of fields low)"
        parts_en.append(f"{en_name} {v}{extra}")
        parts_hi.append(f"{hi_name} {RATING_HI[v]}")
    return ([f"Your Soil Health Card: {', '.join(parts_en)}. In Punjab and Haryana the fertiliser "
             "doses above follow the organic carbon (or nitrogen), phosphorus and potash ratings "
             "by PAU's soil-test rule."],
            [f"आपका सॉइल हेल्थ कार्ड: {', '.join(parts_hi)}। पंजाब और हरियाणा में ऊपर दी गई खाद की "
             "मात्रा जैविक कार्बन (या नाइट्रोजन), फ़ॉस्फ़ोरस और पोटाश की रेटिंग के हिसाब से PAU के "
             "मिट्टी-जाँच नियम से तय हुई है।"])
