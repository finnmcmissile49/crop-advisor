"""Fertiliser advice: when each dose is due and how much per acre (11 November 2026).

Punjab and Haryana: Punjab Agricultural University's Package of Practices, the same books the
irrigation rules come from (Rabi 2025-26, Kharif 2026, Vegetables 2021; page numbers below are the
printed pages). Doses are PAU's for medium-fertility soil. With the farmer's Soil Health Card
ratings they follow PAU's soil-test rule (Rabi 2025-26 pp. 106-107, Kharif 2026 p. 152): PAU's
table where it lists the crop, otherwise 25 percent more on a low soil and 25 percent less on a
high one. Organic carbon is PAU's index for nitrogen, so the card's organic-carbon rating is used
for urea when it is given, else the nitrogen rating.

Wheat in the other eight states: the all-India zone dose for irrigated, timely sown wheat
(150:60:40 kg N:P2O5:K2O per hectare in the north-western and north-eastern plains, 120:60:40 in
the central zone; one third of the nitrogen with all the phosphorus and potash at sowing, the rest
at the first node stage, 40-45 days after sowing), turned into bags of urea, DAP and potash per
acre here.

What this is not: a soil test. The quantities are the universities' general doses; they have not
been checked on any field by this project.
"""
from dataclasses import dataclass

import pandas as pd

from cropadvisor import crops as cr

PAU_RABI = "PAU Package of Practices, Rabi 2025-26"
PAU_KHARIF = "PAU Package of Practices, Kharif 2026"
PAU_VEG = "PAU Package of Practices for Cultivation of Vegetables 2021"
ICAR_WHEAT = ("ICAR wheat package of practices (zone doses for irrigated timely sown wheat; "
              "Vikaspedia / ICAR-IIWBR)")

PAU_STATES = ("Punjab", "Haryana")
DAP_UREA_CREDIT = 0.4     # PAU: "for each kg of DAP applied, reduce the amount of urea by 0.4 kg"
SOIL_RULE = {"low": 1.25, "medium": 1.0, "high": 0.75}   # PAU's general soil-test rule
N_UREA, N_DAP, P_DAP, K_MOP = 0.46, 0.18, 0.46, 0.60      # nutrient content of the fertilisers
HA_PER_ACRE = 1 / 2.47105
DUE_SOON_DAYS = 7         # a dose within this many days is "coming up"
LATE_DAYS = 3             # a dose is still "due now" this many days after its window


@dataclass(frozen=True)
class Dose:
    """One application. `when`: ("sowing",) | ("watering", n) | ("das", first, last) |
    ("stage", key). n_share: its share of the season's urea."""
    when: tuple
    n_share: float = 0.0
    p: bool = False            # the phosphorus fertiliser goes with this dose
    k: bool = False            # the potash goes with this dose
    extra_en: str = ""
    extra_hi: str = ""
    optional: bool = False
    fixed: tuple = ()          # ((product, kg), ...) given as is, never adjusted (sprays, gypsum)
    fallback_das: int = None   # ("watering", n) only: PAU's day if rain delays that watering


@dataclass(frozen=True)
class Plan:
    crop: str
    urea: float                # season total for medium soil, kg per acre, with p_product as below
    p_product: str             # "dap" or "ssp"
    p_kg: float
    doses: tuple
    source: str
    urea_table: tuple = None   # PAU soil-test table (low, medium, high), single-superphosphate basis
    p_table: tuple = None      # PAU soil-test table for p_product (low, medium, high)
    mop_kg: float = 0.0
    mop_rule: str = "if_low"   # "if_low": only when the card says potash is low | "always"
    alt_en: str = ""
    alt_hi: str = ""
    notes_en: tuple = ()
    notes_hi: tuple = ()


# Growth stages PAU names without a date. The day range is our estimate from the crop's FAO-56
# stage lengths (start of the mid-season stage = flowering / tasselling), shown as an estimate.
STAGES = {
    "knee_high": ("when the crop is knee-high", "जब फ़सल घुटने तक ऊँची हो"),
    "pre_tassel": ("just before tasselling", "बल्ली (झंडा) निकलने से ठीक पहले"),
    "thinning": ("at thinning", "छँटाई (विरलन) के समय"),
    "pre_ear": ("before the ears form", "बालियाँ बनने से पहले"),
    "flowering": ("when the first flowers appear", "जब पहले फूल दिखें"),
}

PRODUCT = {"urea": ("urea", "यूरिया"), "dap": ("DAP", "डीएपी"),
           "ssp": ("single superphosphate", "सिंगल सुपरफ़ॉस्फ़ेट"),
           "mop": ("muriate of potash", "म्यूरेट ऑफ़ पोटाश"), "gypsum": ("gypsum", "जिप्सम"),
           "urea_spray": ("urea as a 2% spray (3 kg in 150 litres of water)",
                          "यूरिया का 2% घोल (150 लीटर पानी में 3 किलो)")}

PLANS = {
    # Wheat, PAU Rabi 2025-26 pp. 9-10: 55 kg DAP at sowing and no urea then; 45 kg urea each with
    # the first and second irrigation; if rain delays the second irrigation, at 55 days.
    "wheat": Plan(
        "wheat", urea=110, p_product="dap", p_kg=55, urea_table=(130, 110, 90),
        p_table=(65, 55, 45), mop_kg=20, source=PAU_RABI + ", pp. 9-10, 107",
        doses=(Dose(("sowing",), p=True, k=True),
               Dose(("watering", 1), n_share=0.5),
               Dose(("watering", 2), n_share=0.5, fallback_das=55)),
        alt_en="With 155 kg single superphosphate instead of DAP, also give 20 kg urea at sowing.",
        alt_hi="डीएपी की जगह 155 किलो सिंगल सुपरफ़ॉस्फ़ेट दें तो बुवाई पर 20 किलो यूरिया भी दें।",
        notes_en=("If water stands in the field near the second watering, PAU advises urea sprays "
                  "instead of broadcasting.",),
        notes_hi=("दूसरी सिंचाई के समय खेत में पानी खड़ा हो तो PAU छिड़काव की जगह यूरिया के घोल का "
                  "स्प्रे बताता है।",)),
    # Barley, pp. 24-25: 55 kg urea + 75 kg SSP (or 27 kg DAP + 45 kg urea), all at sowing.
    "barley": Plan(
        "barley", urea=55, p_product="ssp", p_kg=75, urea_table=(65, 55, 40),
        p_table=(100, 75, 55), mop_kg=10, source=PAU_RABI + ", pp. 24-25, 107",
        doses=(Dose(("sowing",), n_share=1.0, p=True, k=True),),
        alt_en="Or 27 kg DAP with 45 kg urea in place of the superphosphate.",
        alt_hi="या सुपरफ़ॉस्फ़ेट की जगह 27 किलो डीएपी और 45 किलो यूरिया।"),
    # Raya (mustard), p. 52: 90 kg urea + 75 kg SSP; half N and all P before sowing, half N with
    # the first irrigation. PAU prefers superphosphate (it carries sulphur).
    "mustard": Plan(
        "mustard", urea=90, p_product="ssp", p_kg=75, urea_table=(110, 90, 70),
        p_table=(100, 75, 60), mop_kg=10, source=PAU_RABI + ", pp. 52, 107",
        doses=(Dose(("sowing",), n_share=0.5, p=True, k=True),
               Dose(("watering", 1), n_share=0.5)),
        notes_en=("PAU prefers single superphosphate for mustard because it also gives sulphur.",),
        notes_hi=("सरसों के लिए PAU सिंगल सुपरफ़ॉस्फ़ेट को बेहतर मानता है क्योंकि इसमें गंधक भी "
                  "होता है।",)),
    # Desi gram, p. 36: 13 kg urea + 50 kg SSP drilled at sowing; for higher yield 2% urea sprays
    # at 90 and 110 days.
    "chickpea": Plan(
        "chickpea", urea=13, p_product="ssp", p_kg=50, source=PAU_RABI + ", p. 36",
        doses=(Dose(("sowing",), n_share=1.0, p=True),
               Dose(("das", 90, 90), optional=True, fixed=(("urea_spray", 3),)),
               Dose(("das", 110, 110), optional=True, fixed=(("urea_spray", 3),))),
        notes_en=("Doses are for desi gram; kabuli gram takes 100 kg superphosphate.",),
        notes_hi=("मात्रा देसी चने की है; काबुली चने में 100 किलो सुपरफ़ॉस्फ़ेट लगता है।",)),
    # Autumn potato, PAU Vegetables 2021 p. 111: 165 kg urea, 155 kg SSP, 40 kg MOP; all P and K
    # and half N at sowing, the rest of the N at earthing-up, 25-30 days after sowing.
    "potato": Plan(
        "potato", urea=165, p_product="ssp", p_kg=155, mop_kg=40, mop_rule="always",
        source=PAU_VEG + ", p. 111",
        doses=(Dose(("sowing",), n_share=0.5, p=True, k=True),
               Dose(("das", 25, 30), n_share=0.5,
                    extra_en="at earthing-up", extra_hi="मिट्टी चढ़ाते समय")),
        notes_en=("PAU also asks for 20 tonnes of farmyard manure or a green manure crop per "
                  "acre.",),
        notes_hi=("PAU प्रति एकड़ 20 टन गोबर की खाद या हरी खाद भी बताता है।",)),
    # Spring maize, p. 28: 110 kg urea + 150 kg SSP (or 55 kg DAP with 90 kg urea); one third of
    # the N at sowing, one third at knee-high, one third before tasselling.
    "spring_maize": Plan(
        "spring_maize", urea=110, p_product="ssp", p_kg=150, urea_table=(130, 110, 90),
        p_table=(190, 155, 125), mop_kg=20, source=PAU_RABI + ", pp. 28, 107",
        doses=(Dose(("sowing",), n_share=1 / 3, p=True, k=True),
               Dose(("stage", "knee_high"), n_share=1 / 3),
               Dose(("stage", "pre_tassel"), n_share=1 / 3)),
        alt_en="Or 55 kg DAP in place of the superphosphate, with 90 kg urea in all.",
        alt_hi="या सुपरफ़ॉस्फ़ेट की जगह 55 किलो डीएपी, और कुल 90 किलो यूरिया।",
        notes_en=("Doses are for the long-duration hybrids (PMH 10, PMH 8, PMH 1, P 1844, "
                  "DKC 9108); PMH 7 takes 75 kg urea and 75 kg superphosphate.",),
        notes_hi=("मात्रा लंबी अवधि की हाइब्रिड किस्मों की है; PMH 7 में 75 किलो यूरिया और 75 किलो "
                  "सुपरफ़ॉस्फ़ेट लगता है।",)),
    # Summer moong, p. 44: 11 kg urea + 100 kg SSP at sowing; none after potato.
    "summer_moong": Plan(
        "summer_moong", urea=11, p_product="ssp", p_kg=100, source=PAU_RABI + ", p. 44",
        doses=(Dose(("sowing",), n_share=1.0, p=True),),
        notes_en=("Summer moong sown after potato needs no fertiliser (PAU).",),
        notes_hi=("आलू के बाद बोई गई गर्मी की मूँग को खाद की ज़रूरत नहीं (PAU)।",)),
    # Cotton, Kharif 2026 p. 49: Bt hybrids 120 kg urea, 75 kg SSP (or 27 kg DAP, urea less by
    # 10 kg); all P at sowing; half N at thinning (done after the first irrigation), half when
    # flowers appear; 20 kg MOP in light soils.
    "cotton": Plan(
        "cotton", urea=120, p_product="ssp", p_kg=75, mop_kg=20, source=PAU_KHARIF + ", p. 49",
        doses=(Dose(("sowing",), p=True, k=True),
               Dose(("watering", 1), n_share=0.5,
                    extra_en="at thinning, after the first watering",
                    extra_hi="छँटाई के समय, पहली सिंचाई के बाद"),
               Dose(("stage", "flowering"), n_share=0.5)),
        alt_en="Or 27 kg DAP in place of the superphosphate, with 10 kg less urea.",
        alt_hi="या सुपरफ़ॉस्फ़ेट की जगह 27 किलो डीएपी, और यूरिया 10 किलो कम।",
        notes_en=("Doses are for Bt hybrids; Bt varieties take 80 kg urea and non-Bt varieties "
                  "65 kg. No phosphorus is needed if the wheat before it got its full dose. On "
                  "light soils PAU adds 20 kg muriate of potash and 10 kg zinc sulphate.",),
        notes_hi=("मात्रा बीटी हाइब्रिड की है; बीटी किस्मों में 80 और ग़ैर-बीटी में 65 किलो यूरिया। "
                  "पिछली गेहूँ को पूरा फ़ॉस्फ़ोरस मिला हो तो कपास में फ़ॉस्फ़ोरस ज़रूरी नहीं। हल्की "
                  "ज़मीन में PAU 20 किलो पोटाश और 10 किलो ज़िंक सल्फ़ेट जोड़ता है।",)),
    # Kharif maize, pp. 32-33: as spring maize; potash only when the soil test shows a shortage.
    "kharif_maize": Plan(
        "kharif_maize", urea=110, p_product="ssp", p_kg=150, urea_table=(130, 110, 90),
        p_table=(190, 155, 125), mop_kg=20, source=PAU_KHARIF + ", pp. 32-33, 152",
        doses=(Dose(("sowing",), n_share=1 / 3, p=True, k=True),
               Dose(("stage", "knee_high"), n_share=1 / 3),
               Dose(("stage", "pre_tassel"), n_share=1 / 3)),
        alt_en="Or 55 kg DAP in place of the superphosphate, with 90 kg urea in all.",
        alt_hi="या सुपरफ़ॉस्फ़ेट की जगह 55 किलो डीएपी, और कुल 90 किलो यूरिया।",
        notes_en=("Doses are for the long-duration hybrids; PMH 2 and JC 4 take 75 kg urea and "
                  "75 kg superphosphate. No phosphorus is needed if the wheat before it got its "
                  "full dose.",),
        notes_hi=("मात्रा लंबी अवधि की हाइब्रिड किस्मों की है; PMH 2 और JC 4 में 75 किलो यूरिया और "
                  "75 किलो सुपरफ़ॉस्फ़ेट। पिछली गेहूँ को पूरा फ़ॉस्फ़ोरस मिला हो तो ज़रूरी नहीं।",)),
    # Bajra, irrigated, pp. 42-43: 90 kg urea + 150 kg SSP (or 55 kg DAP, urea less by 20 kg);
    # half N and all P at the last ploughing, the rest in two splits at thinning and before the
    # ears form.
    "bajra": Plan(
        "bajra", urea=90, p_product="ssp", p_kg=150, source=PAU_KHARIF + ", pp. 42-43",
        doses=(Dose(("sowing",), n_share=0.5, p=True,
                    extra_en="with the last ploughing", extra_hi="आख़िरी जुताई के साथ"),
               Dose(("stage", "thinning"), n_share=0.25),
               Dose(("stage", "pre_ear"), n_share=0.25)),
        alt_en="Or 55 kg DAP in place of the superphosphate, with 20 kg less urea.",
        alt_hi="या सुपरफ़ॉस्फ़ेट की जगह 55 किलो डीएपी, और यूरिया 20 किलो कम।",
        notes_en=("Doses are for an irrigated crop; a rainfed crop takes 55 kg urea and 75 kg "
                  "superphosphate.",),
        notes_hi=("मात्रा सिंचित फ़सल की है; बारानी फ़सल में 55 किलो यूरिया और 75 किलो "
                  "सुपरफ़ॉस्फ़ेट।",)),
    # Kharif moong, p. 65: 11 kg urea + 100 kg SSP at sowing.
    "kharif_moong": Plan(
        "kharif_moong", urea=11, p_product="ssp", p_kg=100, source=PAU_KHARIF + ", p. 65",
        doses=(Dose(("sowing",), n_share=1.0, p=True),)),
    # Kharif groundnut, p. 98: 13 kg urea, 50 kg SSP, 50 kg gypsum, all at sowing (gypsum
    # broadcast); 17 kg MOP only where the soil test shows a shortage.
    "groundnut": Plan(
        "groundnut", urea=13, p_product="ssp", p_kg=50, mop_kg=17,
        source=PAU_KHARIF + ", p. 98",
        doses=(Dose(("sowing",), n_share=1.0, p=True, k=True, fixed=(("gypsum", 50),)),),
        notes_en=("No phosphorus is needed if the wheat before it got its full dose.",),
        notes_hi=("पिछली गेहूँ को पूरा फ़ॉस्फ़ोरस मिला हो तो फ़ॉस्फ़ोरस ज़रूरी नहीं।",)),
}

ICAR_NPK_HA = {"NWPZ": (150, 60, 40), "NEPZ": (150, 60, 40), "CZ": (120, 60, 40)}
ICAR_FIRST_NODE_DAS = (40, 45)


def icar_wheat_plan(zone):
    """The all-India zone dose for irrigated timely sown wheat as kg of DAP, urea and MOP per
    acre: all P as DAP, the DAP's own nitrogen counted, one third of the N at sowing."""
    n_ha, p_ha, k_ha = ICAR_NPK_HA.get(zone, ICAR_NPK_HA["NWPZ"])
    n, p, k = n_ha * HA_PER_ACRE, p_ha * HA_PER_ACRE, k_ha * HA_PER_ACRE
    dap = p / P_DAP
    urea_total = (n - dap * N_DAP) / N_UREA
    basal = max(n / 3 - dap * N_DAP, 0) / N_UREA
    return Plan(
        "wheat", urea=urea_total, p_product="dap", p_kg=dap, mop_kg=k / K_MOP, mop_rule="always",
        source=ICAR_WHEAT,
        doses=(Dose(("sowing",), n_share=basal / urea_total, p=True, k=True),
               Dose(("das",) + ICAR_FIRST_NODE_DAS, n_share=1 - basal / urea_total,
                    extra_en="at the first node stage", extra_hi="पहली गाँठ बनने पर")),
        notes_en=(f"All-India dose for the {zone} wheat zone ({n_ha}:{p_ha}:{k_ha} kg "
                  "N:P2O5:K2O per hectare), turned into fertiliser per acre. Your state "
                  "university or KVK may advise a different dose.",),
        notes_hi=(f"यह {zone} गेहूँ क्षेत्र की अखिल भारतीय मात्रा है ({n_ha}:{p_ha}:{k_ha} किलो "
                  "N:P2O5:K2O प्रति हेक्टेयर), प्रति एकड़ खाद में बदली हुई। आपका राज्य कृषि "
                  "विश्वविद्यालय या KVK अलग मात्रा बता सकता है।",))


def plan_for(crop, state, zone=None):
    if crop == "wheat" and state not in PAU_STATES:
        return icar_wheat_plan(zone)
    return PLANS.get(crop)


def _round(kg):
    """Whole kilograms; amounts of 20 kg or more that we worked out go to the nearest 5."""
    return int(round(kg))


def _round5(kg):
    return int(round(kg)) if kg < 20 else int(5 * round(kg / 5))


def soil_levels(card):
    """(nitrogen level, phosphorus level, potash level) from the farmer's card ratings, each
    "low" / "medium" / "high" or None. Organic carbon stands for nitrogen when given (PAU)."""
    card = card or {}
    n = card.get("oc") or card.get("n")
    lv = lambda v: v if v in SOIL_RULE else None   # noqa: E731
    return lv(n), lv(card.get("p")), lv(card.get("k"))


def amounts(plan, card=None, adjust=True):
    """Season quantities per acre: {"urea", "p_kg", "mop", "n_level", "p_level", "k_level",
    "adjusted"}. adjust=False (outside Punjab and Haryana): the card is not applied."""
    n_lv, p_lv, k_lv = soil_levels(card) if adjust else (None, None, None)
    idx = {"low": 0, "medium": 1, "high": 2}
    p_kg = plan.p_kg
    if p_lv and p_lv != "medium":
        p_kg = plan.p_table[idx[p_lv]] if plan.p_table else _round5(plan.p_kg * SOIL_RULE[p_lv])
    urea = plan.urea
    if n_lv and n_lv != "medium":
        urea = plan.urea_table[idx[n_lv]] if plan.urea_table else plan.urea * SOIL_RULE[n_lv]
    if plan.p_product == "dap" and plan.urea_table:
        # PAU's table is on a superphosphate basis: take off the nitrogen the DAP brings
        urea = urea - DAP_UREA_CREDIT * p_kg
    mop = plan.mop_kg if (plan.mop_rule == "always" or k_lv == "low") else 0.0
    changed = bool((n_lv and n_lv != "medium") or (p_lv and p_lv != "medium"))
    urea = _round5(urea) if (changed or plan.p_product == "dap") and plan.urea_table else urea
    return {"urea": urea, "p_kg": p_kg, "mop": mop, "n_level": n_lv, "p_level": p_lv,
            "k_level": k_lv, "adjusted": changed}


def stage_window(spec, sowing, key):
    """Estimated (first, last) dates of a named growth stage, from the crop's FAO-56 stage
    lengths stretched to its season. An estimate: PAU names these stages, not dates."""
    params = spec.params(100.0)
    ini, dev, _, _ = params.stage_lengths()
    if key in ("knee_high",):
        lo, hi = ini, ini + dev / 2
    elif key == "thinning":
        lo, hi = ini * 0.7, ini
    else:   # just before the mid-season stage starts (flowering, tasselling, ear formation)
        lo, hi = ini + dev - 10, ini + dev
    s = pd.Timestamp(sowing)
    return s + pd.Timedelta(days=int(round(lo))), s + pd.Timedelta(days=int(round(hi)))


def schedule(crop, state, sowing, today, watered=(), next_watering=None, card=None, zone=None):
    """The season's doses with dates and status, or None when the crop has no plan.

    watered: dates of waterings already given after sowing. next_watering: the date the irrigation
    advice points to for the next watering (so a dose "with the first watering" gets a date).
    Returns {"plan", "amounts", "doses": [{..., "status"}], "next": dose or None}."""
    plan = plan_for(crop, state, zone)
    if plan is None:
        return None
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    watered = sorted(pd.Timestamp(w) for w in watered)
    amt = amounts(plan, card, adjust=state in PAU_STATES)
    spec = cr.CROPS.get(crop)
    out = []
    for d in plan.doses:
        kind = d.when[0]
        estimate, given = False, False
        if kind == "sowing":
            lo = hi = sowing
        elif kind == "watering":
            n = d.when[1]
            if len(watered) >= n:
                lo = hi = watered[n - 1]
                given = True
            elif len(watered) == n - 1 and next_watering is not None:
                lo = hi = pd.Timestamp(next_watering)
                estimate = True
            else:
                lo = hi = None
            if d.fallback_das and lo is not None and not given:
                cap = sowing + pd.Timedelta(days=d.fallback_das)
                if lo > cap:
                    lo = hi = cap
        elif kind == "das":
            lo = sowing + pd.Timedelta(days=d.when[1])
            hi = sowing + pd.Timedelta(days=d.when[2])
        else:
            lo, hi = stage_window(spec, sowing, d.when[1]) if spec is not None else (None, None)
            estimate = True
        items = []
        if d.n_share:
            items.append(("urea", _round(amt["urea"] * d.n_share)))
        if d.p and amt["p_kg"]:
            items.append((plan.p_product, _round(amt["p_kg"])))
        if d.k and amt["mop"]:
            items.append(("mop", _round(amt["mop"])))
        items += list(d.fixed)
        items = [(p, kg) for p, kg in items if kg > 0]
        if not items:
            continue
        if lo is None:
            status = "later"
        elif today > hi + pd.Timedelta(days=LATE_DAYS):
            status = "past"
        elif today >= lo:
            status = "due_now"
        elif today >= lo - pd.Timedelta(days=DUE_SOON_DAYS):
            status = "due_soon"
        else:
            status = "later"
        out.append({"when": d.when, "first": lo, "last": hi, "items": items, "status": status,
                    "estimate": estimate, "with_watering_given": given, "optional": d.optional,
                    "extra_en": d.extra_en, "extra_hi": d.extra_hi,
                    "fallback_das": d.fallback_das})
    nxt = next((x for x in out if not x["optional"] and x["status"] != "past"), None)
    return {"crop": crop, "plan": plan, "amounts": amt, "doses": out, "next": nxt,
            "pau": state in PAU_STATES, "sowing": sowing, "today": today}


# ------------------------------------------------------------------------------------ text

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]
ORDINAL = {1: ("first", "पहली"), 2: ("second", "दूसरी"), 3: ("third", "तीसरी")}
LEVEL_HI = {"low": "कम", "medium": "मध्यम", "high": "ज़्यादा"}


def _d_en(d):
    return f"{d.day} {d:%b}"


def _d_hi(d):
    return f"{d.day} {HI_MONTHS[d.month - 1]}"


def _range(lo, hi, fn):
    return fn(lo) if lo == hi else f"{fn(lo)} - {fn(hi)}"


def _items(items, lang):
    i = 0 if lang == "en" else 1
    unit = "kg" if lang == "en" else "किलो"
    parts = [f"{kg} {unit} {PRODUCT[p][i]}" for p, kg in items]
    return (" + " if lang == "en" else " + ").join(parts)


def _when(dose, lang):
    kind = dose["when"][0]
    en = lang == "en"
    fn = _d_en if en else _d_hi
    date = _range(dose["first"], dose["last"], fn) if dose["first"] is not None else None
    if kind == "sowing":
        base = dose["extra_en"] if en and dose["extra_en"] else (
            dose["extra_hi"] if not en and dose["extra_hi"] else ("at sowing" if en else "बुवाई पर"))
        return f"{base} ({date})" if en else f"{base} ({date})"
    if kind == "watering":
        o = ORDINAL[dose["when"][1]][0 if en else 1]
        base = (dose["extra_en"] if en else dose["extra_hi"]) or (
            f"with the {o} watering" if en else f"{o} सिंचाई के साथ")
        if date is None:
            return base
        if dose["with_watering_given"]:
            return f"{base} (given {date})" if en else f"{base} ({date} को दी गई)"
        return f"{base} (about {date})" if en else f"{base} (लगभग {date})"
    if kind == "das":
        base = dose["extra_en"] if en else dose["extra_hi"]
        days = (f"{dose['when'][1]}" if dose["when"][1] == dose["when"][2]
                else f"{dose['when'][1]}-{dose['when'][2]}")
        tail = f"{days} days after sowing" if en else f"बुवाई के {days} दिन बाद"
        return f"{base + ', ' if base else ''}{tail} ({date})"
    name = STAGES[dose["when"][1]][0 if en else 1]
    if date is None:
        return name
    return f"{name} (our estimate: {date})" if en else f"{name} (हमारा अनुमान: {date})"


STATUS = {"due_now": ("DUE NOW", "अभी देना है"), "due_soon": ("coming up", "जल्द आने वाली"),
          "later": ("later", "आगे"), "past": ("time has passed", "समय निकल चुका")}


def text(s):
    """English and Hindi lines for a schedule() result."""
    if not s:
        return [], []
    plan, amt = s["plan"], s["amounts"]
    spec = cr.CROPS.get(s["crop"])
    name_en = spec.en if spec else "Wheat"
    name_hi = spec.hi if spec else "गेहूँ"
    if amt["adjusted"]:
        bits_en, bits_hi = [], []
        if amt["n_level"] and amt["n_level"] != "medium":
            bits_en.append(f"nitrogen {amt['n_level']}")
            bits_hi.append(f"नाइट्रोजन {LEVEL_HI[amt['n_level']]}")
        if amt["p_level"] and amt["p_level"] != "medium":
            bits_en.append(f"phosphorus {amt['p_level']}")
            bits_hi.append(f"फ़ॉस्फ़ोरस {LEVEL_HI[amt['p_level']]}")
        basis_en = f"adjusted for your Soil Health Card ({', '.join(bits_en)})"
        basis_hi = f"आपके मृदा स्वास्थ्य कार्ड के हिसाब से ({', '.join(bits_hi)})"
    elif s["pau"]:
        basis_en, basis_hi = "for a medium-fertility soil", "मध्यम उपजाऊ ज़मीन के लिए"
    else:
        basis_en, basis_hi = "general dose", "सामान्य मात्रा"
    en = [f"Fertiliser for {name_en.lower()}, per acre ({basis_en}):"]
    hi = [f"{name_hi} के लिए खाद, प्रति एकड़ ({basis_hi}):"]
    for d in s["doses"]:
        opt_en = " (optional, for higher yield)" if d["optional"] else ""
        opt_hi = " (वैकल्पिक, ज़्यादा पैदावार के लिए)" if d["optional"] else ""
        st = STATUS[d["status"]]
        w_en = _when(d, "en")
        en.append(f"  - {w_en[0].upper() + w_en[1:]}: {_items(d['items'], 'en')}{opt_en}. "
                  f"[{st[0]}]")
        hi.append(f"  - {_when(d, 'hi')}: {_items(d['items'], 'hi')}{opt_hi}। [{st[1]}]")
        if d["fallback_das"] and not d["with_watering_given"]:
            cap = s["sowing"] + pd.Timedelta(days=d["fallback_das"])
            en.append(f"    If rain delays that watering, broadcast it by {_d_en(cap)} "
                      f"({d['fallback_das']} days after sowing).")
            hi.append(f"    बारिश से वह सिंचाई टल जाए तो {_d_hi(cap)} तक (बुवाई के "
                      f"{d['fallback_das']} दिन बाद) छिड़क दें।")
    nxt = s["next"]
    if nxt is None:
        en.append("All fertiliser doses for this crop are behind you.")
        hi.append("इस फ़सल की सभी खाद की ख़ुराकें निकल चुकी हैं।")
    elif nxt["status"] == "due_now":
        en.append(f"Fertiliser now: {_items(nxt['items'], 'en')} per acre, "
                  f"{_when(nxt, 'en')}.")
        hi.append(f"अभी खाद: {_items(nxt['items'], 'hi')} प्रति एकड़, {_when(nxt, 'hi')}।")
    else:
        en.append(f"Next fertiliser: {_items(nxt['items'], 'en')} per acre, "
                  f"{_when(nxt, 'en')}.")
        hi.append(f"अगली खाद: {_items(nxt['items'], 'hi')} प्रति एकड़, {_when(nxt, 'hi')}।")
    if plan.mop_kg and plan.mop_rule == "if_low" and not amt["mop"]:
        en.append(f"Potash: {_round(plan.mop_kg)} kg muriate of potash per acre at sowing only if "
                  "your soil test shows potash is low.")
        hi.append(f"पोटाश: बुवाई पर {_round(plan.mop_kg)} किलो म्यूरेट ऑफ़ पोटाश प्रति एकड़, केवल "
                  "तब जब मिट्टी की जाँच में पोटाश कम हो।")
    if plan.alt_en and not amt["adjusted"]:
        en.append(plan.alt_en)
        hi.append(plan.alt_hi)
    en += list(plan.notes_en)
    hi += list(plan.notes_hi)
    if s["pau"] and not amt["adjusted"] and not any(amt[k] for k in ("n_level", "p_level")):
        en.append("Give your Soil Health Card ratings (--soil-card oc=low p=high k=low) and the "
                  "doses follow PAU's soil-test rule.")
        hi.append("अपने मृदा स्वास्थ्य कार्ड की रेटिंग दें (--soil-card oc=low p=high k=low) तो "
                  "मात्रा PAU के मिट्टी-जाँच नियम से बदलेगी।")
    en.append(f"Source: {plan.source}.")
    hi.append(f"स्रोत: {plan.source}।")
    return en, hi


def to_json(s):
    if not s:
        return None
    f = lambda d: None if d is None else pd.Timestamp(d).strftime("%Y-%m-%d")  # noqa: E731
    return {"source": s["plan"].source,
            "soil_levels": {k: s["amounts"][k] for k in ("n_level", "p_level", "k_level")},
            "adjusted_for_soil_card": s["amounts"]["adjusted"],
            "doses": [{"when": list(d["when"]), "first": f(d["first"]), "last": f(d["last"]),
                       "kg_per_acre": {p: kg for p, kg in d["items"]}, "status": d["status"],
                       "date_is_estimate": d["estimate"], "optional": d["optional"]}
                      for d in s["doses"]],
            "next": None if s["next"] is None else
            {"first": f(s["next"]["first"]), "kg_per_acre": dict(s["next"]["items"]),
             "status": s["next"]["status"]}}
