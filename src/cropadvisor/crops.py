"""Crop settings for the irrigation advisor, beyond wheat.

Wheat keeps its own settings and zone logic in irrigation.py (ICAR zones, PAU/IIWBR first watering,
fixed 7-7.5 cm waterings). Every other crop is described here by one CropSpec built only from:

- FAO-56 (Allen et al. 1998, FAO Irrigation and Drainage Paper 56): Table 11 stage lengths,
  Table 12 crop coefficients (Kc) and crop height, Table 22 rooting depth and depletion fraction p.
- PAU, Package of Practices for Crops of Punjab, Rabi 2025-26 (Vol. 42 No. 2, August 2025) and
  Kharif 2026 (Vol. 43 No. 1, March 2026); PAU Package of Practices for Cultivation of Vegetables
  2021 (potato). Page numbers are the printed book pages.

Rules applied the same way to every crop (our choices, stated once here):
- Region: Punjab and Haryana only. The guidance is PAU's (Punjab). Haryana's own university
  guidance (HAU) could not be read online; Haryana uses PAU's guidance as the nearest available.
- Maximum rooting depth: the lower end of FAO-56 Table 22's range (FAO-56: "the smaller values
  may be used for irrigation scheduling"), capped at 1.0 m because the SoilGrids profile stops at
  1 m (the same rule as wheat). Exceptions, still inside FAO's range: the upper end where past
  seasons at the lower end needed clearly more waterings than PAU states (summer and kharif moong,
  groundnut; checked 27 October 2026, see notes/crops.md), and chickpea, where PAU says the heavy
  pre-sowing irrigation "will ensure deep rooting". The other end of the range is a stress test.
  Matching PAU's number of waterings is a check against guidance, not against measured fields.
- Season length: the middle of the maturity days PAU gives for its recommended varieties.
- Stage split: the FAO-56 Table 11 row closest in region and sowing month, stretched to the season
  length. Where Table 11 has no row for the crop, the row used is named and is an assumption.
- Range values in Table 12 without a footnote saying which applies: the midpoint.
- The soil is at field capacity on the sowing day (pre-sowing irrigation, the planting irrigation,
  or monsoon rain for kharif crops sown into wet soil).
- Every watering refills the root zone (a flood irrigation wets the whole root zone; extra
  drains). Advice gives the amount the soil is short of on that day.
- No irrigation in the last STAGE_MARGIN_DAYS before maturity unless PAU gives its own last date.
- Kc mid and Kc end are adjusted for humidity and wind (FAO-56 eq. 62) when the weather has them.
"""
from dataclasses import dataclass, field

import pandas as pd

from cropadvisor import irrigation as ir

STAGE_MARGIN_DAYS = ir.STAGE_MARGIN_DAYS   # 10 days, the same assumption as wheat
SOWING_GRACE_DAYS = 10                     # accepted after PAU's window, with a warning
STATES = ("Punjab", "Haryana")
PAU_RABI = "PAU Package of Practices, Rabi 2025-26"
PAU_KHARIF = "PAU Package of Practices, Kharif 2026"
PAU_VEG = "PAU Package of Practices for Cultivation of Vegetables 2021"


@dataclass(frozen=True)
class CropSpec:
    key: str
    en: str
    hi: str
    season_en: str                 # e.g. "rabi (winter)"
    sowing_window: tuple           # ((month, day), (month, day)), PAU's sowing time
    default_sowing: tuple          # (month, day) used for the past-season checks
    season_days: int
    stage_days_fao: tuple          # FAO-56 Table 11 row (initial, development, mid, late)
    stage_row: str                 # which Table 11 row, and whether it is a stand-in
    kc_ini: float
    kc_mid: float
    kc_end: float
    height_m: float                # FAO-56 Table 12
    zr_max: float
    p: float                       # FAO-56 Table 22
    first: tuple = None            # (usual day, earliest, latest) of the first watering after sowing
    first_reason_en: str = ""
    first_reason_hi: str = ""
    max_irrigations: int = None    # PAU's largest stated number of waterings after sowing
    cutoff: tuple = ("margin", STAGE_MARGIN_DAYS)   # ("das", n) | ("date", (m, d)) | ("margin", n)
    window: dict = None            # chickpea: the one watering must fall inside a date window
    blackout: tuple = None         # ((m, d), (m, d)): PAU says do not irrigate in this period
    expected_irrigations: tuple = None   # PAU's stated range, for the plausibility check
    notes_en: tuple = ()           # always shown with the advice
    notes_hi: tuple = ()
    sources: tuple = ()
    confidence: str = "normal"

    def params(self, awc_mm_per_m, **overrides):
        """CropParams for the engine. The cut-off 'das' and 'margin' rules become
        last_irrigation_das; a 'date' cut-off is applied by the rule."""
        season = overrides.pop("season_days", self.season_days)
        kind, val = self.cutoff
        last = val if kind == "das" else (season - val if kind == "margin" else None)
        base = dict(awc_mm_per_m=awc_mm_per_m, season_days=season,
                    stage_days_fao=self.stage_days_fao, kc_ini=self.kc_ini, kc_mid=self.kc_mid,
                    kc_end=self.kc_end, zr_ini=min(0.2, self.zr_max), zr_max=self.zr_max,
                    p_table=self.p, adjust_p=True, last_irrigation_das=last,
                    crop_height_m=self.height_m, adjust_kc=True)
        base.update(overrides)
        return ir.CropParams(**base)

    # ------------------------------------------------------------------ dates for one season
    def cutoff_date(self, sowing, params):
        sowing = pd.Timestamp(sowing)
        if self.cutoff[0] == "date":
            return ir.season_date(sowing, *self.cutoff[1])
        return sowing + pd.Timedelta(days=int(params.last_irrigation_das))

    def window_dates(self, sowing):
        if not self.window:
            return None
        sowing = pd.Timestamp(sowing)
        start = max(ir.season_date(sowing, *self.window["start"]),
                    sowing + pd.Timedelta(days=self.window["min_das"]))
        return start, ir.season_date(sowing, *self.window["end"])

    def blackout_dates(self, sowing):
        if not self.blackout:
            return None
        a = ir.season_date(sowing, *self.blackout[0])
        b = ir.season_date(a, *self.blackout[1])
        return a, b

    def sowing_range(self, sowing):
        """PAU's window for the season that contains (or is nearest to) this sowing date."""
        sowing = pd.Timestamp(sowing)
        (m1, d1), (m2, d2) = self.sowing_window
        for y in (sowing.year, sowing.year - 1):
            lo = pd.Timestamp(y, m1, d1)
            hi = pd.Timestamp(y + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)
            if lo - pd.Timedelta(days=60) <= sowing <= hi + pd.Timedelta(days=60):
                return lo, hi
        lo = pd.Timestamp(sowing.year, m1, d1)
        return lo, pd.Timestamp(sowing.year + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)


class CropRule:
    """The advice rule for one crop, for the season simulation and the past-season checks.

    1. The first watering at the stage PAU names, when it names one.
    2. Then irrigate when the root zone has used its readily available water (FAO-56 trigger).
    3. Never after the cut-off, never in a PAU no-irrigation period, never more than PAU's largest
       stated number of waterings, and (chickpea) only inside PAU's date window: if the soil has
       not reached the trigger by the end of the window but has used at least half of its readily
       available water, the watering is given on the last day of the window (our reading of
       "give one more irrigation between mid-December and end-January").
    """
    name = "crop_rule"

    def __init__(self, spec):
        self.spec = spec

    def start(self, sowing, params):
        self.sowing = pd.Timestamp(sowing)
        self.cutoff = self.spec.cutoff_date(sowing, params)
        self.win = self.spec.window_dates(sowing)
        self.black = self.spec.blackout_dates(sowing)
        self.n_done = 0
        self.first_done = self.spec.first is None

    def decide(self, date, das, dr_prev, raw, taw):
        s = self.spec
        self.last_kind = None
        if date > self.cutoff:
            return 0.0
        if s.max_irrigations is not None and self.n_done >= s.max_irrigations:
            return 0.0
        if self.black and self.black[0] <= date <= self.black[1]:
            return 0.0
        if not self.first_done:
            if das >= s.first[0]:
                self.first_done = True
                self.n_done += 1
                self.last_kind = "first"
                return dr_prev
            return 0.0
        if self.win:
            start, end = self.win
            if date < start or date > end:
                return 0.0
            due = dr_prev >= raw or (date == end and dr_prev >= s.window["end_fraction"] * raw)
        else:
            due = dr_prev >= raw
        if due and dr_prev > 0:
            self.n_done += 1
            self.last_kind = "trigger"
            return dr_prev
        return 0.0

    def observe_rain(self, date, rain_mm):
        pass


# ------------------------------------------------------------------------------------ crops
# FAO-56 Table 12 group Kc ini: legumes 0.4, roots and tubers 0.5, fibre and oil crops 0.35,
# cereals 0.3.

CROPS = {}


def _add(spec):
    CROPS[spec.key] = spec
    return spec


_add(CropSpec(
    key="mustard", en="Mustard (raya)", hi="सरसों (राया)", season_en="rabi (winter)",
    # PAU Rabi p. 50: raya and African sarson, mid October to mid November
    sowing_window=((10, 15), (11, 15)), default_sowing=(10, 25),
    # PAU Rabi pp. 48-50: raya varieties mature in 140-145 days (PHR 127 140, Giriraj 144,
    # RLC 3 145, PBR 357 145)
    season_days=143,
    # FAO-56 Table 11 has no mustard or rapeseed row. Stand-in: "Grains (small), Pakistan, arid
    # region, Oct/Nov" (25, 35, 65, 40), a cool-season crop sown at the same time in the same belt.
    stage_days_fao=(25, 35, 65, 40),
    stage_row="FAO-56 Table 11 has no mustard row; stand-in: small grains, Pakistan, Oct/Nov",
    # FAO-56 Table 12 rapeseed/canola: Kc mid 1.0-1.15 (lower values for rainfed, thinner crops;
    # irrigated raya takes the upper value), Kc end 0.35, height 0.6 m
    kc_ini=0.35, kc_mid=1.15, kc_end=0.35, height_m=0.6,
    zr_max=1.0, p=0.60,                     # FAO-56 Table 22 rapeseed: 1.0-1.5 m, p 0.60
    # PAU Rabi p. 53: "should be irrigated 3 to 4 weeks after sowing to promote deeper rooting"
    first=(24, 21, 28),
    first_reason_en="PAU advises it 3 to 4 weeks after sowing, for deeper roots and better use of "
                    "fertiliser.",
    first_reason_hi="PAU बुवाई के 3-4 हफ़्ते बाद यह सिंचाई बताता है, ताकि जड़ें गहरी जाएँ और खाद का "
                    "पूरा फ़ायदा मिले।",
    # PAU Rabi p. 53: second irrigation at flowering "if necessary"
    max_irrigations=2,
    # PAU Rabi p. 53: raya drip schedule runs November to February; gobhi sarson's last irrigation
    # in the second fortnight of February, none after it (lodging). Our reading for raya: end of
    # February.
    cutoff=("date", (2, 28)),
    # PAU Rabi p. 56: "avoid irrigation to the rapeseed-mustard crop during 25th December to 15th
    # January" (Sclerotinia stem rot)
    blackout=((12, 25), (1, 15)),
    expected_irrigations=(1, 2),
    notes_en=("PAU: no watering from 25 December to 15 January (it spreads stem rot).",
              "If frost is forecast, the second watering may be needed earlier (PAU)."),
    notes_hi=("PAU: 25 दिसंबर से 15 जनवरी तक सिंचाई न करें (तना गलन रोग फैलता है)।",
              "पाला पड़ने का अनुमान हो तो दूसरी सिंचाई पहले करनी पड़ सकती है (PAU)।"),
    sources=(f"{PAU_RABI}, Rapeseed and Mustard, pp. 47-57", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="chickpea", en="Chickpea (gram)", hi="चना", season_en="rabi (winter)",
    # PAU Rabi p. 35: irrigated desi and kabuli gram, 25 October to 10 November
    sowing_window=((10, 25), (11, 10)), default_sowing=(11, 1),
    # PAU Rabi p. 34-35: irrigated varieties PBG 10 153 days, PBG 8 158, PBG 7 159, L 552 157
    season_days=156,
    # FAO-56 Table 11 has no chickpea row. Stand-in: lentil, arid region, Oct/Nov (25, 35, 70, 40).
    stage_days_fao=(25, 35, 70, 40),
    stage_row="FAO-56 Table 11 has no chickpea row; stand-in: lentil, arid region, Oct/Nov",
    kc_ini=0.4, kc_mid=1.00, kc_end=0.35, height_m=0.4,   # FAO-56 Table 12 chick pea
    # FAO-56 Table 22: 0.6-1.0 m, p 0.50. Upper end: PAU Rabi p. 37, the pre-sowing irrigation
    # "will ensure deep rooting for proper utilization of soil moisture"
    zr_max=1.0, p=0.50,
    # PAU Rabi p. 37: heavy pre-sowing irrigation, then "one more irrigation between mid-December
    # and end-January depending upon the date of sowing and the rainfall ... In no case, should
    # this irrigation be given earlier than 4 weeks after sowing. If early rains are received,
    # delay the irrigation."
    max_irrigations=1,
    window={"start": (12, 15), "min_das": 28, "end": (1, 31), "end_fraction": 0.5},
    cutoff=("date", (1, 31)),
    expected_irrigations=(0, 1),
    notes_en=("PAU: do not water chickpea sown after rice on heavy soil (it damages the crop), "
              "unless it is on raised beds.",
              "Too much water makes leafy growth and lowers grain yield (PAU)."),
    notes_hi=("PAU: धान के बाद भारी मिट्टी में बोए चने में सिंचाई न करें (फ़सल को नुकसान होता है), "
              "जब तक बेड पर बुवाई न हो।",
              "ज़्यादा पानी से पौधा बढ़ता है पर दाना कम बनता है (PAU)।"),
    sources=(f"{PAU_RABI}, Gram, pp. 34-38", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="barley", en="Barley", hi="जौ", season_en="rabi (winter)",
    # PAU Rabi p. 24: "best results when sown between October 15 to November 15"
    sowing_window=((10, 15), (11, 15)), default_sowing=(11, 1),
    # PAU Rabi pp. 23-24: PL 942 146 days, PL 891 144, DWRB 123 141, DWRUB 52 140, PL 807 137
    season_days=141,
    stage_days_fao=(15, 25, 50, 30),     # FAO-56 Table 11 barley/oats/wheat, Central India, Nov
    stage_row="FAO-56 Table 11 barley/oats/wheat, Central India, November",
    kc_ini=0.3, kc_mid=1.15, kc_end=0.25, height_m=1.0,   # FAO-56 Table 12 barley
    zr_max=1.0, p=0.55,                                   # FAO-56 Table 22: 1.0-1.5 m, p 0.55
    # PAU Rabi p. 25: "two post-sowing irrigations are generally required [south-western dry
    # districts], whereas in other districts, one irrigation from five to six weeks after sowing
    # may be enough"
    first=(38, 35, 42),
    first_reason_en="PAU advises the first watering 5 to 6 weeks after sowing.",
    first_reason_hi="PAU बुवाई के 5-6 हफ़्ते बाद पहली सिंचाई बताता है।",
    max_irrigations=2,
    expected_irrigations=(1, 2),
    notes_en=("Barley is drought hardy: PAU expects one watering in most districts, two in the "
              "dry south-west.",),
    notes_hi=("जौ सूखा सह लेता है: PAU के अनुसार ज़्यादातर ज़िलों में एक सिंचाई काफ़ी है, सूखे "
              "दक्षिण-पश्चिम में दो।",),
    sources=(f"{PAU_RABI}, Barley, pp. 23-25", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="potato", en="Potato (autumn)", hi="आलू (अगेती/पतझड़)", season_en="rabi (autumn crop)",
    # PAU Vegetables 2021 p. 110: "last week of September to mid-October for the autumn crop"
    sowing_window=((9, 24), (10, 15)), default_sowing=(10, 5),
    # PAU Vegetables pp. 108-109: medium varieties (Kufri Pushkar, Surya, Chipsona) 90-100 days,
    # Kufri Pukhraj 70-90; the middle of 90-100 days is used
    season_days=95,
    stage_days_fao=(25, 30, 30, 30),     # FAO-56 Table 11 potato, (semi) arid climate, Jan/Nov
    stage_row="FAO-56 Table 11 potato, (semi) arid climate, Jan/Nov (115-day version)",
    # FAO-56 Table 12 potato: Kc ini 0.5 (roots and tubers), mid 1.15, end 0.75 (0.40 only for
    # long-season potatoes with vine kill), height 0.6 m
    kc_ini=0.5, kc_mid=1.15, kc_end=0.75, height_m=0.6,
    zr_max=0.4, p=0.35,                  # FAO-56 Table 22: 0.4-0.6 m, p 0.35
    # PAU Vegetables p. 111: first irrigation "immediately after planting"; the model starts at
    # field capacity on the planting day, which is that irrigation. 7-8 irrigations in total,
    # "light and repeated irrigations".
    expected_irrigations=(7, 8),
    notes_en=("Water right after planting (PAU); this advice assumes you did.",
              "Give light waterings and do not let water flow over the ridges (PAU)."),
    notes_hi=("बुवाई के तुरंत बाद सिंचाई करें (PAU); यह सलाह मानती है कि आपने की है।",
              "हल्की सिंचाई करें, पानी मेड़ों के ऊपर से न बहे (PAU)।"),
    sources=(f"{PAU_VEG}, Potato, pp. 107-117", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="spring_maize", en="Spring maize", hi="बसंत मक्का", season_en="spring",
    # PAU Rabi p. 27: "Sow the crop during 20 January to 15 February"
    sowing_window=((1, 20), (2, 15)), default_sowing=(2, 1),
    # PAU Rabi p. 26: hybrids mature in 115-122 days
    season_days=118,
    stage_days_fao=(20, 35, 40, 30),     # FAO-56 Table 11 maize (grain), India (dry, cool), Oct
    stage_row="FAO-56 Table 11 maize (grain), India (dry, cool), October",
    # FAO-56 Table 12 maize (grain): Kc mid 1.20, Kc end 0.60 (harvest at high grain moisture;
    # PAU: ready when the husk has dried though stalks are still green), height 2 m
    kc_ini=0.3, kc_mid=1.20, kc_end=0.60, height_m=2.0,
    zr_max=1.0, p=0.55,                  # FAO-56 Table 22: 1.0-1.7 m, p 0.55
    # PAU Rabi p. 29: "Depending upon rains, apply first irrigation at 25-30 days after sowing.
    # The subsequent irrigations should be applied at 2 weeks interval upto 10th April and
    # thereafter at one week interval upto maturity."
    first=(27, 25, 30),
    first_reason_en="PAU advises the first watering 25 to 30 days after sowing.",
    first_reason_hi="PAU बुवाई के 25-30 दिन बाद पहली सिंचाई बताता है।",
    cutoff=("margin", 0),                # PAU: irrigate "upto maturity"
    notes_en=("Do not let the crop go short of water at grain filling in the heat (PAU).",),
    notes_hi=("दाना भरते समय गर्मी में फ़सल को पानी की कमी न होने दें (PAU)।",),
    sources=(f"{PAU_RABI}, Spring Maize, pp. 26-30", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="summer_moong", en="Summer moong", hi="गर्मी की मूंग", season_en="summer (zaid)",
    # PAU Rabi p. 43: "Sow the crop from 20 March to 10 April. Its sowing can be done up to 3rd
    # week of April."
    sowing_window=((3, 20), (4, 10)), default_sowing=(4, 1),
    # PAU Rabi pp. 42-43: varieties mature in about 60-62 days
    season_days=61,
    stage_days_fao=(20, 30, 30, 20),     # FAO-56 Table 11 green gram, cowpeas, Mediterranean, March
    stage_row="FAO-56 Table 11 green gram and cowpeas, Mediterranean, March",
    # FAO-56 Table 12 green gram and cowpeas: Kc mid 1.05, Kc end 0.35 (dry harvest), h 0.4 m
    kc_ini=0.4, kc_mid=1.05, kc_end=0.35, height_m=0.4,
    # FAO-56 Table 22: 0.6-1.0 m, p 0.45. Upper end: at 0.6 m past seasons needed 5-10 waterings
    # (mean 7.0) against PAU's 3-5; at 1.0 m, mean 4.5.
    zr_max=1.0, p=0.45,
    # PAU Rabi p. 44: "Apply 3 to 5 irrigations ... Apply first irrigation 25 days after sowing.
    # The last irrigation should be stopped about 55 days after sowing." The +-3 day window is
    # ours (PAU's own tolerance for wheat intervals).
    first=(25, 22, 28),
    first_reason_en="PAU advises the first watering 25 days after sowing.",
    first_reason_hi="PAU बुवाई के 25 दिन बाद पहली सिंचाई बताता है।",
    cutoff=("das", 55),
    expected_irrigations=(3, 5),
    notes_en=("Stop watering about 55 days after sowing so the pods ripen together (PAU).",),
    notes_hi=("बुवाई के लगभग 55 दिन बाद सिंचाई बंद करें ताकि फलियाँ एक साथ पकें (PAU)।",),
    sources=(f"{PAU_RABI}, Summer Moong, pp. 42-45", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="cotton", en="Cotton (narma)", hi="कपास (नरमा)", season_en="kharif (summer-monsoon)",
    # PAU Kharif p. 46: "Sow the crop during 1 April to 15 May"
    sowing_window=((4, 1), (5, 15)), default_sowing=(4, 25),
    # PAU Kharif p. 46: Bt varieties 160-165 days, LH 2108 165-170, F 2228 180
    season_days=165,
    stage_days_fao=(30, 50, 60, 55),     # FAO-56 Table 11 cotton, Egypt; Pakistan; Calif., Mar-May
    stage_row="FAO-56 Table 11 cotton, Egypt/Pakistan/California, March-May",
    # FAO-56 Table 12 cotton: Kc mid 1.15-1.20, Kc end 0.70-0.50 (midpoints used), h 1.2-1.5 m
    kc_ini=0.35, kc_mid=1.175, kc_end=0.60, height_m=1.35,
    zr_max=1.0, p=0.65,                  # FAO-56 Table 22: 1.0-1.7 m, p 0.65
    # PAU Kharif p. 50: "4-6 irrigations ... The first irrigation should be given 4 to 6 weeks
    # after sowing and the subsequent ones at interval of two or three weeks ... on light soils
    # ... the first irrigation may be advanced ... give the last irrigation by the end of
    # September."
    first=(35, 28, 42),
    first_reason_en="PAU advises the first watering 4 to 6 weeks after sowing (earlier on light "
                    "soil).",
    first_reason_hi="PAU बुवाई के 4-6 हफ़्ते बाद पहली सिंचाई बताता है (हल्की मिट्टी में पहले)।",
    cutoff=("date", (9, 30)),
    expected_irrigations=(4, 6),
    notes_en=("No water stress at flowering and boll formation, or flowers and bolls drop (PAU).",
              "Drain standing water when the crop is young (PAU)."),
    notes_hi=("फूल और टिंडे बनते समय पानी की कमी न हो, वरना फूल-टिंडे झड़ते हैं (PAU)।",
              "छोटी फ़सल में खड़ा पानी निकाल दें (PAU)।"),
    sources=(f"{PAU_KHARIF}, Cotton, pp. 45-62", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="kharif_maize", en="Kharif maize", hi="खरीफ़ मक्का", season_en="kharif (monsoon)",
    # PAU Kharif p. 30: "Last week of May to end of June"
    sowing_window=((5, 25), (6, 30)), default_sowing=(6, 10),
    # PAU Kharif pp. 28-30: hybrids 95-99 days
    season_days=97,
    stage_days_fao=(20, 35, 40, 30),     # FAO-56 Table 11 maize (grain), Nigeria (humid), June
    stage_row="FAO-56 Table 11 maize (grain), Nigeria (humid), June",
    kc_ini=0.3, kc_mid=1.20, kc_end=0.60, height_m=2.0,   # as spring maize
    zr_max=1.0, p=0.55,
    # PAU Kharif p. 34: "Generally, 4-6 irrigations are required depending on the rainfall ...
    # particularly during the pre-tasselling, silking and grain filling stages."
    expected_irrigations=(4, 6),
    # Past seasons (27 Oct 2026): 0-4 waterings, mean 1.3, below PAU's 4-6 in rainy seasons (3-4
    # in the dry 2021 and 2023 seasons in Sirsa, Hisar, Bathinda). Not resolved: Open-Meteo's
    # monsoon rain in Punjab has not been checked against IMD, and FAO-56's Kc ini of 0.3 is low
    # for a soil wetted by frequent rain. Lower confidence until checked.
    confidence="low",
    notes_en=("Drain standing water: flooding hurts young maize badly (PAU).",),
    notes_hi=("खेत में खड़ा पानी निकालें: छोटी मक्का को इससे बहुत नुकसान होता है (PAU)।",),
    sources=(f"{PAU_KHARIF}, Maize, pp. 28-36", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="bajra", en="Bajra (pearl millet)", hi="बाजरा", season_en="kharif (monsoon)",
    # PAU Kharif p. 42: "In areas of low rainfall, sow bajra in early July. For other areas, sow
    # it in the last week of July"
    sowing_window=((7, 1), (7, 31)), default_sowing=(7, 10),
    # PAU Kharif pp. 41-42: hybrids about 80-90 days (88, 90, 80); the late varieties (111, 124
    # days) are fodder types
    season_days=88,
    stage_days_fao=(15, 25, 40, 25),     # FAO-56 Table 11 millet, Pakistan, June
    stage_row="FAO-56 Table 11 millet, Pakistan, June",
    kc_ini=0.3, kc_mid=1.00, kc_end=0.30, height_m=1.5,   # FAO-56 Table 12 millet
    zr_max=1.0, p=0.55,                                   # FAO-56 Table 22: 1.0-2.0 m, p 0.55
    # PAU Kharif p. 43: "Generally, two irrigations during the growing period of the crop are
    # enough. Bajra does not tolerate water-logging"
    max_irrigations=2,
    expected_irrigations=(0, 2),
    notes_en=("Bajra cannot stand waterlogging: drain rain water within a few hours (PAU).",),
    notes_hi=("बाजरा जलभराव नहीं सहता: बारिश का पानी कुछ घंटों में निकाल दें (PAU)।",),
    sources=(f"{PAU_KHARIF}, Bajra, pp. 41-43", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="kharif_moong", en="Kharif moong", hi="खरीफ़ मूंग", season_en="kharif (monsoon)",
    # PAU Kharif p. 65: "Sowing should be done in the second fortnight of July."
    sowing_window=((7, 16), (7, 31)), default_sowing=(7, 20),
    season_days=71,                      # PAU Kharif p. 64-65: about 71-72 days
    stage_days_fao=(20, 30, 30, 20),
    stage_row="FAO-56 Table 11 green gram and cowpeas, Mediterranean, March",
    kc_ini=0.4, kc_mid=1.05, kc_end=0.35, height_m=0.4,
    # Upper end of FAO-56's 0.6-1.0 m: at 0.6 m some seasons needed up to 7 waterings, against
    # PAU's "if the rain fails"
    zr_max=1.0, p=0.45,
    # PAU Kharif p. 65: "Irrigation is required for the kharif season crop if the rain fails."
    expected_irrigations=(0, 2),
    sources=(f"{PAU_KHARIF}, Moong, pp. 64-67", "FAO-56 Tables 11, 12, 22"),
))

_add(CropSpec(
    key="groundnut", en="Groundnut (kharif)", hi="मूंगफली (खरीफ़)", season_en="kharif",
    # PAU Kharif p. 97: "Optimum sowing time of kharif groundnut is from end April to end May with
    # a pre-sowing irrigation"
    sowing_window=((4, 25), (5, 31)), default_sowing=(5, 10),
    # PAU Kharif pp. 96-97: varieties 101-123 days; kharif-sown crop ready end August to early
    # September (about 115 days)
    season_days=115,
    stage_days_fao=(35, 45, 35, 25),     # FAO-56 Table 11 groundnut, Mediterranean, May/June
    stage_row="FAO-56 Table 11 groundnut, Mediterranean, May/June",
    kc_ini=0.4, kc_mid=1.15, kc_end=0.60, height_m=0.4,   # FAO-56 Table 12 groundnut
    # FAO-56 Table 22: 0.5-1.0 m, p 0.50. Upper end: at 0.5 m past seasons hit PAU's maximum of 3
    # waterings with about 33 days of water stress, i.e. needed more than PAU states.
    zr_max=1.0, p=0.50,
    # PAU Kharif p. 98: "Two or three irrigations may be necessary depending upon the seasonal
    # rainfall. Give first irrigation at flowering ... one or two more ... during the pod formation
    # period ... Another irrigation a few days before the harvesting may be applied for full
    # recovery of pods". PAU gives no day for flowering, so it is not a fixed watering here.
    max_irrigations=3,
    expected_irrigations=(2, 3),
    notes_en=("A watering a few days before digging helps lift all the pods (PAU).",),
    notes_hi=("खुदाई से कुछ दिन पहले सिंचाई करने से सारी फलियाँ निकल आती हैं (PAU)।",),
    sources=(f"{PAU_KHARIF}, Groundnut, pp. 96-99", "FAO-56 Tables 11, 12, 22"),
))


def get(key):
    if key not in CROPS:
        raise KeyError(key)
    return CROPS[key]
