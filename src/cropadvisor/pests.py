"""Pest and disease watch: says when the risk is rising, from the weather and the crop's stage
(11 November 2026).

Every rule is a condition a university has published for that pest or disease:
- Punjab Agricultural University, Package of Practices (Rabi 2025-26, Kharif 2026): the weather
  it calls congenial for each disease, and the months or growth stage it gives for each insect.
- Potato late blight: the JHULSACAST model as fitted for the Punjab plains (Arora, Ahmad and
  Singh, Potato Journal 39(2), 2012): blight is expected within 10 days once, over 7 days, the
  air has been above 85 percent humidity for 90 hours or more and between 7.2 and 26.6 deg C for
  115 hours or more.

The weather is Open-Meteo's (the last 7 days and the 7-day forecast, hourly), for the district
point or the field point. A day counts as "favourable" when it meets the published condition. The
risk is called rising when at least MIN_DAYS of the next 7 forecast days are favourable and that
is more than in the last 7 days; high when both weeks have at least MIN_DAYS. MIN_DAYS = 3 is our
choice, and so are the numbers used for the words PAU does not quantify ("high humidity",
"cloudy", "intermittent rains"); they are the constants below.

This is a watch: it tells the farmer when to look at the crop. It names no spray. It has not been
checked against outbreaks in fields.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cropadvisor import crops as cr
from cropadvisor import irrigation as ir
from cropadvisor.common import http_get_json

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "cloud_cover"]
BACK_DAYS = 14      # 7 days to judge, plus 7 more for the 7-day sums of the first of them
AHEAD_DAYS = 7
MIN_DAYS = 3        # our choice: favourable days in a week that count as a risk

# Our numbers for PAU's unquantified words
HIGH_RH = 80.0          # "high relative humidity" / "humid": daily mean humidity, percent
CLOUDY = 70.0           # "cloudy": daily mean cloud cover, percent
RAIN_DAY_MM = 1.0       # a day with rain
INTERMITTENT_DAYS = 2   # "intermittent rains": this many rain days in the 5 days ending that day
AROUND_C = 3.0          # "around 20 deg C": daily mean within this many degrees
COLD_TMAX = 20.0        # "cold" (mustard aphid): daily maximum at or below this

PAU_RABI = "PAU Package of Practices, Rabi 2025-26"
PAU_KHARIF = "PAU Package of Practices, Kharif 2026"
JHULSACAST = "JHULSACAST for the Punjab plains (Arora, Ahmad and Singh 2012, Potato Journal 39(2))"

# JHULSACAST (Punjab): 7-day totals
LB_RH = 85.0
LB_RH_HOURS = 90
LB_T_LO, LB_T_HI = 7.2, 26.6
LB_T_HOURS = 115


def fetch_hourly(lat, lon, today, now=None, raw_path=None):
    """Hourly temperature, humidity, rain and cloud from BACK_DAYS before `today` to AHEAD_DAYS
    after it. Live (today within 2 days of now): Open-Meteo forecast with its recent past. A past
    date: Open-Meteo's record, used as if the following week were the forecast."""
    today = pd.Timestamp(today).normalize()
    now = pd.Timestamp(now).normalize() if now is not None else pd.Timestamp.today().normalize()
    base = {"latitude": lat, "longitude": lon, "hourly": ",".join(HOURLY),
            "timezone": "Asia/Kolkata"}
    if today >= now - pd.Timedelta(days=2):
        data = http_get_json(FORECAST_URL, {**base, "past_days": BACK_DAYS + (now - today).days,
                                            "forecast_days": AHEAD_DAYS + 1}, raw_path=raw_path)
    else:
        f = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731
        data = http_get_json(ARCHIVE_URL, {
            **base, "start_date": f(today - pd.Timedelta(days=BACK_DAYS)),
            "end_date": f(today + pd.Timedelta(days=AHEAD_DAYS))}, raw_path=raw_path)
    h = pd.DataFrame(data["hourly"]).rename(columns={
        "temperature_2m": "temp", "relative_humidity_2m": "rh", "precipitation": "rain",
        "cloud_cover": "cloud"})
    h["time"] = pd.to_datetime(h["time"])
    return h[["time", "temp", "rh", "rain", "cloud"]]


def daily(hourly):
    """One row per day with what the rules need."""
    h = hourly.copy()
    h["date"] = h["time"].dt.normalize()
    hour = h["time"].dt.hour
    h["night_rh"] = h["rh"].where((hour >= 20) | (hour <= 6))
    h["lb_wet"] = (h["rh"] > LB_RH).astype(float).where(h["rh"].notna())
    h["lb_temp"] = h["temp"].between(LB_T_LO, LB_T_HI).astype(float).where(h["temp"].notna())
    d = h.groupby("date").agg(
        tmax=("temp", "max"), tmin=("temp", "min"), tmean=("temp", "mean"),
        rh_mean=("rh", "mean"), night_rh=("night_rh", "mean"), rain_mm=("rain", "sum"),
        cloud=("cloud", "mean"), wet_hours=("lb_wet", "sum"), temp_hours=("lb_temp", "sum"),
        hours=("temp", "count")).reset_index()
    d = d[d["hours"] >= 20].reset_index(drop=True)      # whole days only
    rainy = (d["rain_mm"] >= RAIN_DAY_MM).astype(int)
    d["rain_days_5"] = rainy.rolling(5, min_periods=1).sum()
    d["wet_hours_7"] = d["wet_hours"].rolling(7, min_periods=7).sum()
    d["temp_hours_7"] = d["temp_hours"].rolling(7, min_periods=7).sum()
    return d


@dataclass(frozen=True)
class Rule:
    key: str
    crops: tuple
    en: str                    # name
    hi: str
    kind: str                  # "weather" (favourable days) | "stage" (the crop is at that stage)
    test: object = None        # daily row -> bool
    window: tuple = ("das", 20, None)   # ("das", first, last or None) | ("months", (m, ...)) |
    #                                     ("stage", "mid" | "late") | ("das+months", first, months)
    why_en: str = ""           # the published condition, in words
    why_hi: str = ""
    look_en: str = ""          # what to look for in the field
    look_hi: str = ""
    source: str = PAU_RABI
    min_days: int = MIN_DAYS
    ours: bool = False         # True: part of the condition uses our number for a PAU word
    always_watch: bool = False   # a weather rule that is also a standing watch inside its window


def _between(v, lo, hi):
    return v is not None and not np.isnan(v) and lo <= v <= hi


RULES = (
    # ---------------------------------------------------------------- wheat and barley
    Rule("yellow_rust", ("wheat", "barley"), "Yellow rust", "पीला रतुआ", "weather",
         test=lambda r: _between(r.tmin, 7, 13) and _between(r.tmax, 15, 24)
         and r.night_rh >= 85,
         window=("das", 25, None),
         why_en="nights of 7-13 deg C with 85-100% humidity and days of 15-24 deg C",
         why_hi="रात का तापमान 7-13 डिग्री और नमी 85-100%, दिन का तापमान 15-24 डिग्री",
         look_en="yellow powdery stripes on the leaves; it starts in patches",
         look_hi="पत्तों पर पीले पाउडर जैसी धारियाँ; यह टुकड़ों में शुरू होता है",
         source=PAU_RABI + ", p. 19 (wheat; the same rust attacks barley, p. 25)"),
    # Ears: PAU gives the stage, not a day. Timely sown wheat in Punjab heads about 100 days after
    # sowing (our estimate), so the watch runs from two thirds of the season to near harvest.
    Rule("wheat_aphid", ("wheat",), "Aphid", "चेपा (माहू)", "stage", window=("frac", 0.66, 0.92),
         why_en="aphids build up once the ears are out",
         why_hi="बालियाँ निकलने पर चेपा बढ़ता है",
         look_en="aphids on the ears, first on the borders of the field; PAU's threshold is 5 "
                 "aphids per ear",
         look_hi="बालियों पर चेपा, पहले खेत के किनारों पर; PAU की सीमा 5 चेपा प्रति बाली है",
         source=PAU_RABI + ", p. 18"),
    # ---------------------------------------------------------------- mustard
    Rule("alternaria", ("mustard",), "Alternaria blight", "अल्टरनेरिया झुलसा", "weather",
         test=lambda r: _between(r.tmean, 15, 25) and r.rh_mean > 75, window=("das", 30, None),
         why_en="15-25 deg C with humidity above 75%",
         why_hi="15-25 डिग्री तापमान और 75% से ज़्यादा नमी",
         look_en="brown to black spots with rings on leaves, stems and pods",
         look_hi="पत्तों, तनों और फलियों पर छल्लेदार भूरे-काले धब्बे",
         source=PAU_RABI + ", p. 55"),
    Rule("white_rust", ("mustard",), "White rust", "सफ़ेद रतुआ", "weather",
         test=lambda r: _between(r.tmean, 13, 25) and r.rh_mean > 75, window=("das", 30, None),
         why_en="13-25 deg C with humidity above 75%",
         why_hi="13-25 डिग्री तापमान और 75% से ज़्यादा नमी",
         look_en="white raised pustules under the leaves; swollen, twisted flower shoots",
         look_hi="पत्तों के नीचे सफ़ेद उभरे फफोले; फूल वाली टहनियाँ फूली और टेढ़ी",
         source=PAU_RABI + ", p. 55"),
    Rule("downy_mildew", ("mustard",), "Downy mildew", "मृदुरोमिल आसिता", "weather",
         test=lambda r: _between(r.tmean, 10, 20) and r.rh_mean > 90, window=("das", 20, None),
         why_en="10-20 deg C with humidity above 90%",
         why_hi="10-20 डिग्री तापमान और 90% से ज़्यादा नमी",
         look_en="whitish growth under the leaves and deformed stems",
         look_hi="पत्तों के नीचे सफ़ेद फफूँद और टेढ़े तने",
         source=PAU_RABI + ", p. 55"),
    Rule("mustard_aphid", ("mustard",), "Mustard aphid", "सरसों का चेपा (माहू)", "weather",
         test=lambda r: r.cloud >= CLOUDY and r.tmax <= COLD_TMAX,
         window=("months", (1, 2, 3)),
         why_en="cold and cloudy weather (PAU: watch twice a week from the first week of January)",
         why_hi="ठंडा और बादलों वाला मौसम (PAU: जनवरी के पहले हफ़्ते से हफ़्ते में दो बार देखें)",
         look_en="green aphids crowding the flower shoots and pods",
         look_hi="फूल वाली टहनियों और फलियों पर हरे चेपे के झुंड",
         source=PAU_RABI + ", p. 54", ours=True, always_watch=True),
    # ---------------------------------------------------------------- chickpea
    Rule("ascochyta", ("chickpea",), "Ascochyta blight", "एस्कोकाइटा झुलसा", "weather",
         test=lambda r: abs(r.tmean - 20) <= AROUND_C and r.rh_mean > 85
         and (r.cloud >= CLOUDY or r.rain_days_5 >= INTERMITTENT_DAYS),
         window=("das", 30, None),
         why_en="about 20 deg C, humidity above 85% and cloudy weather with rain on and off",
         why_hi="लगभग 20 डिग्री तापमान, 85% से ज़्यादा नमी और रुक-रुक कर बारिश वाला बादली मौसम",
         look_en="dark spots on leaves, stems and pods; shoot tips dying back in patches",
         look_hi="पत्तों, तनों और फलियों पर गहरे धब्बे; टुकड़ों में टहनियों के सिरे सूखना",
         source=PAU_RABI + ", p. 38", ours=True),
    Rule("grey_mould", ("chickpea",), "Grey mould", "धूसर फफूँद", "weather",
         test=lambda r: abs(r.tmean - 25) <= AROUND_C and r.rh_mean >= HIGH_RH
         and r.rain_mm >= RAIN_DAY_MM,
         window=("stage", "mid"), min_days=2,
         why_en="about 25 deg C, high humidity and rain during flowering",
         why_hi="फूल आते समय लगभग 25 डिग्री तापमान, ज़्यादा नमी और बारिश",
         look_en="grey-brown rot on flowers and growing tips; flowers dropping",
         look_hi="फूलों और सिरों पर धूसर-भूरी सड़न; फूल झड़ना",
         source=PAU_RABI + ", p. 38", ours=True),
    # ---------------------------------------------------------------- potato
    Rule("late_blight", ("potato",), "Late blight", "पछेती झुलसा", "weather",
         test=lambda r: r.wet_hours_7 >= LB_RH_HOURS and r.temp_hours_7 >= LB_T_HOURS,
         window=("das", 15, None), min_days=1,
         why_en="in 7 days, 90 or more hours above 85% humidity and 115 or more hours between "
                "7.2 and 26.6 deg C; blight is then expected within 10 days",
         why_hi="7 दिनों में 85% से ज़्यादा नमी के 90 या ज़्यादा घंटे और 7.2-26.6 डिग्री के 115 या "
                "ज़्यादा घंटे; इसके बाद 10 दिन के अंदर झुलसा आने की आशंका",
         look_en="water-soaked patches on leaf edges turning black, white growth underneath in "
                 "the morning",
         look_hi="पत्तों के किनारों पर पानी भरे धब्बे जो काले पड़ते हैं, सुबह नीचे सफ़ेद फफूँद",
         source=JHULSACAST),
    # ---------------------------------------------------------------- maize
    Rule("maydis", ("kharif_maize",), "Maydis leaf blight", "मेडिस पत्ता झुलसा", "weather",
         test=lambda r: abs(r.tmean - 25) <= 2 and r.rh_mean > 80, window=("das", 20, None),
         why_en="humidity above 80% with temperature of 25 deg C (plus or minus 2)",
         why_hi="80% से ज़्यादा नमी और 25 डिग्री (2 डिग्री ऊपर-नीचे) तापमान",
         look_en="long brown spindle-shaped spots on the leaves that join into patches",
         look_hi="पत्तों पर लंबे भूरे तकले जैसे धब्बे जो मिलकर बड़े हो जाते हैं",
         source=PAU_KHARIF + ", p. 39"),
    Rule("stalk_rot", ("kharif_maize",), "Stalk rot", "तना गलन", "weather",
         test=lambda r: r.rain_mm >= 20, window=("das", 30, None), min_days=2,
         why_en="excessive rain and poor drainage (here: 2 or more days of 20 mm or more in a "
                "week)",
         why_hi="बहुत ज़्यादा बारिश और पानी की निकासी न होना (यहाँ: हफ़्ते में 2 या ज़्यादा दिन 20 "
                "मिमी या ज़्यादा बारिश)",
         look_en="stalks rotting and breaking near the base; drain standing water",
         look_hi="तने नीचे से गलकर टूटना; खड़ा पानी निकालें",
         source=PAU_KHARIF + ", p. 39", ours=True),
    Rule("shoot_fly", ("spring_maize",), "Maize shoot fly", "मक्का की तना मक्खी", "stage",
         window=("das", 3, 21),
         why_en="it attacks very young seedlings (3-7 days old), the most serious pest of spring "
                "maize",
         why_hi="यह बहुत छोटे (3-7 दिन के) पौधों पर हमला करती है, बसंत मक्का का सबसे गंभीर कीट",
         look_en="twisted seedlings with a dead central shoot",
         look_hi="मुड़े हुए पौधे जिनकी बीच की पत्ती सूखी हो",
         source=PAU_RABI + ", p. 30"),
    # ---------------------------------------------------------------- cotton
    Rule("sucking_pests", ("cotton",), "Whitefly, jassid and other sucking pests",
         "सफ़ेद मक्खी, तेला और दूसरे रस चूसने वाले कीट", "stage", window=("months", (7, 8, 9)),
         why_en="they do the most damage from July to September",
         why_hi="ये जुलाई से सितंबर तक सबसे ज़्यादा नुक़सान करते हैं",
         look_en="whitefly under the upper leaves before 10 in the morning (PAU's threshold: 6 "
                 "adults per leaf), sticky honeydew",
         look_hi="सुबह 10 बजे से पहले ऊपरी पत्तों के नीचे सफ़ेद मक्खी (PAU की सीमा: 6 प्रति "
                 "पत्ता), चिपचिपा शहद जैसा पदार्थ",
         source=PAU_KHARIF + ", p. 53"),
    Rule("cotton_leaf_spot", ("cotton",), "Fungal leaf spots", "फफूँद वाले पत्ता धब्बे", "weather",
         test=lambda r: r.rh_mean >= HIGH_RH and r.rain_days_5 >= INTERMITTENT_DAYS,
         window=("das", 40, None),
         why_en="high humidity with rain on and off",
         why_hi="ज़्यादा नमी और रुक-रुक कर बारिश",
         look_en="round brown spots with violet edges on leaves and bolls",
         look_hi="पत्तों और टिंडों पर बैंगनी किनारे वाले गोल भूरे धब्बे",
         source=PAU_KHARIF + ", p. 60", ours=True),
    # ---------------------------------------------------------------- groundnut, moong, bajra
    Rule("tikka", ("groundnut",), "Tikka (leaf spot)", "टिक्का (पत्ता धब्बा)", "weather",
         test=lambda r: _between(r.tmean, 25, 30) and r.rh_mean >= HIGH_RH,
         window=("das", 30, None),
         why_en="25-30 deg C with high humidity",
         why_hi="25-30 डिग्री तापमान और ज़्यादा नमी",
         look_en="dark round spots on the leaves, leaves dropping",
         look_hi="पत्तों पर गहरे गोल धब्बे, पत्ते झड़ना",
         source=PAU_KHARIF + ", p. 100", ours=True),
    Rule("moong_leaf_spot", ("kharif_moong",), "Cercospora leaf spot and web blight",
         "सर्कोस्पोरा पत्ता धब्बा और जाला झुलसा", "weather",
         test=lambda r: r.rain_days_5 >= INTERMITTENT_DAYS and r.rh_mean >= HIGH_RH,
         window=("das", 20, None),
         why_en="rain on and off with humid weather",
         why_hi="रुक-रुक कर बारिश और नमी वाला मौसम",
         look_en="round brown spots on leaves; whitish web-like growth on leaves in patches",
         look_hi="पत्तों पर गोल भूरे धब्बे; टुकड़ों में पत्तों पर सफ़ेद जाले जैसी फफूँद",
         source=PAU_KHARIF + ", p. 67", ours=True),
    Rule("moong_thrips", ("summer_moong",), "Thrips", "थ्रिप्स", "stage", window=("stage", "mid"),
         why_en="thrips attack summer moong severely at flowering",
         why_hi="फूल आते समय गर्मी की मूँग पर थ्रिप्स का तेज़ हमला होता है",
         look_en="tiny dark insects inside the flowers; flowers dropping",
         look_hi="फूलों के अंदर छोटे गहरे कीट; फूल झड़ना",
         source=PAU_RABI + ", p. 44"),
    Rule("ergot", ("bajra",), "Ergot", "अरगट (चेपा रोग)", "stage", window=("stage", "mid"),
         why_en="ergot infects the ears at blossoming",
         why_hi="अरगट फूल आते समय बालियों में लगता है",
         look_en="pinkish sticky drops (honeydew) on the ears",
         look_hi="बालियों पर गुलाबी चिपचिपी बूँदें",
         source=PAU_KHARIF + ", p. 44"),
)


def _stage_bounds(crop, state, zone, sowing):
    """(start of mid-season stage, start of late stage, harvest) as dates."""
    if crop == "wheat":
        params = ir.zone_params(zone, 100.0, state=state) if zone else ir.CropParams(100.0)
    else:
        params = cr.get(crop).params(100.0)
    ini, dev, mid, late = params.stage_lengths()
    s = pd.Timestamp(sowing)
    d = lambda n: s + pd.Timedelta(days=int(n))  # noqa: E731
    return d(ini + dev), d(ini + dev + mid), d(ini + dev + mid + late)


def in_window(rule, crop, state, zone, sowing, date):
    sowing, date = pd.Timestamp(sowing), pd.Timestamp(date)
    mid, late, harvest = _stage_bounds(crop, state, zone, sowing)
    if date < sowing or date > harvest:
        return False
    das = (date - sowing).days
    w = rule.window
    if w[0] == "das":
        return das >= w[1] and (w[2] is None or das <= w[2])
    if w[0] == "months":
        return date.month in w[1]
    if w[0] == "stage":
        return mid <= date < late if w[1] == "mid" else date >= late
    if w[0] == "frac":
        season = (harvest - sowing).days
        return w[1] * season <= das <= w[2] * season
    return True


def assess(crop, state, sowing, today, days, zone=None):
    """Every rule of the crop judged on the last 7 days and the next 7.

    days: daily() frame. Returns a list of {"rule", "level", "past", "next", "first_date"} with
    level "rising", "high", "easing", "stage" or "none"."""
    today = pd.Timestamp(today).normalize()
    past = days[(days["date"] > today - pd.Timedelta(days=7)) & (days["date"] <= today)]
    nxt = days[(days["date"] > today) & (days["date"] <= today + pd.Timedelta(days=7))]
    out = []
    for rule in RULES:
        if crop not in rule.crops:
            continue
        if rule.kind == "stage":
            now_in = in_window(rule, crop, state, zone, sowing, today)
            soon = [d for d in nxt["date"] if in_window(rule, crop, state, zone, sowing, d)]
            level = "stage" if now_in else ("stage_soon" if soon else "none")
            out.append({"rule": rule, "level": level, "past": None, "next": None,
                        "first_date": None if now_in or not soon else soon[0]})
            continue

        def fav(frame):
            hits = []
            for r in frame.itertuples():
                try:
                    ok = bool(rule.test(r)) and in_window(rule, crop, state, zone, sowing, r.date)
                except TypeError:
                    ok = False
                if ok:
                    hits.append(r.date)
            return hits
        hp, hn = fav(past), fav(nxt)
        n_p, n_n, m = len(hp), len(hn), rule.min_days
        if n_n >= m and n_p >= m:
            level = "high"
        elif n_n >= m and n_n > n_p:
            level = "rising"
        elif n_p >= m:
            level = "easing"
        elif rule.always_watch and in_window(rule, crop, state, zone, sowing, today):
            level = "watch"
        else:
            level = "none"
        out.append({"rule": rule, "level": level, "past": n_p, "next": n_n,
                    "first_date": (hn or hp or [None])[0]})
    return out


def watch(crop, state, sowing, today, lat, lon, zone=None, now=None, fetch=None):
    """Fetch the weather and assess. Returns {"crop", "today", "results", "days_ahead"} or
    {"error": ...} when the weather could not be read (the rest of the advice still stands)."""
    try:
        hourly = (fetch or fetch_hourly)(lat, lon, today, now)
        days = daily(hourly)
    except Exception as e:
        return {"crop": crop, "today": pd.Timestamp(today), "results": [], "error": str(e)[:150]}
    ahead = int((days["date"] > pd.Timestamp(today).normalize()).sum())
    return {"crop": crop, "today": pd.Timestamp(today),
            "results": assess(crop, state, sowing, today, days, zone), "days_ahead": ahead}


# ------------------------------------------------------------------------------------ text

LEVEL = {"rising": ("RISK RISING", "ख़तरा बढ़ रहा है"), "high": ("RISK HIGH", "ख़तरा ज़्यादा है"),
         "easing": ("risk easing", "ख़तरा घट रहा है"),
         "stage": ("WATCH NOW", "अभी निगरानी करें"), "watch": ("WATCH NOW", "अभी निगरानी करें"),
         "stage_soon": ("watch from next week", "अगले हफ़्ते से निगरानी करें")}
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]


def text(w):
    """English and Hindi lines for a watch() result."""
    if w is None:
        return [], []
    if w.get("error"):
        return (["Pest watch: the hourly weather could not be read just now, so the pest watch "
                 "is left out today. Run the advice again later."],
                ["कीट-रोग निगरानी: अभी घंटेवार मौसम नहीं मिल सका, इसलिए आज यह हिस्सा नहीं है। "
                 "थोड़ी देर बाद सलाह दोबारा चलाएँ।"])
    res = w["results"]
    if not res:
        return [], []
    flagged = [r for r in res if r["level"] != "none"]
    quiet = [r for r in res if r["level"] == "none"]
    en = ["Pest and disease watch (weather of the last 7 days and the 7-day forecast):"]
    hi = ["कीट और रोग निगरानी (पिछले 7 दिन का मौसम और 7 दिन का पूर्वानुमान):"]
    order = {"high": 0, "rising": 1, "stage": 2, "watch": 2, "stage_soon": 3, "easing": 4}
    for r in sorted(flagged, key=lambda x: order[x["level"]]):
        rule, lv = r["rule"], LEVEL[r["level"]]
        if rule.kind == "stage" or r["level"] == "watch":
            en.append(f"  - {rule.en}: {lv[0]}. {rule.why_en[0].upper() + rule.why_en[1:]}. "
                      f"Look for: {rule.look_en}.")
            hi.append(f"  - {rule.hi}: {lv[1]}। {rule.why_hi}। खेत में देखें: {rule.look_hi}।")
            continue
        en.append(f"  - {rule.en}: {lv[0]}. {r['next']} of the next 7 days and {r['past']} of "
                  f"the last 7 have the weather it likes ({rule.why_en}). "
                  f"Look for: {rule.look_en}.")
        hi.append(f"  - {rule.hi}: {lv[1]}। अगले 7 में से {r['next']} दिन और पिछले 7 में से "
                  f"{r['past']} दिन का मौसम इसके अनुकूल है ({rule.why_hi})। खेत में देखें: "
                  f"{rule.look_hi}।")
    if not flagged:
        en.append("  No pest or disease risk is rising from the weather or the crop stage right "
                  "now.")
        hi.append("  अभी मौसम या फ़सल की अवस्था से किसी कीट या रोग का ख़तरा नहीं बढ़ रहा है।")
    if quiet:
        en.append("  Also watched, quiet now: " + ", ".join(r["rule"].en.lower() for r in quiet)
                  + ".")
        hi.append("  इन पर भी नज़र है, अभी शांत: " + ", ".join(r["rule"].hi for r in quiet) + "।")
    if flagged:
        en.append("  If you find it, show it to your Krishi Vigyan Kendra or agriculture officer "
                  "before spraying.")
        hi.append("  मिले तो छिड़काव से पहले अपने कृषि विज्ञान केंद्र या कृषि अधिकारी को दिखाएँ।")
    srcs = sorted({r["rule"].source for r in res})
    en.append("  Conditions from: " + "; ".join(srcs) + ".")
    hi.append("  शर्तों का स्रोत: " + "; ".join(srcs) + "।")
    return en, hi


def to_json(w):
    if w is None:
        return None
    if w.get("error"):
        return {"error": w["error"]}
    f = lambda d: None if d is None else pd.Timestamp(d).strftime("%Y-%m-%d")  # noqa: E731
    return {"results": [{"key": r["rule"].key, "name": r["rule"].en, "level": r["level"],
                         "favourable_days_last_7": r["past"],
                         "favourable_days_next_7": r["next"], "first_date": f(r["first_date"]),
                         "condition": r["rule"].why_en, "source": r["rule"].source,
                         "uses_our_threshold": r["rule"].ours} for r in w["results"]]}
