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
              "Card) and ask your agriculture office for the fertiliser dose for your result.")
    hi.append("ये ज़िले के आँकड़े हैं, आपके खेत के नहीं। अपने खेत की मिट्टी जाँच (सॉइल हेल्थ कार्ड) "
              "करवाएँ और खाद की मात्रा के लिए कृषि विभाग से पूछें।")
    return en, hi
