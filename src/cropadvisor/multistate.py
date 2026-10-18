"""Multi-state data: district rainfall + district yields for every ICRISAT state.

Sources
- Daily district rainfall, 2009 to Jul 2024 (`daily-rainfall-data-district-level.csv`, IMD via
  data.gov.in). District ids are LGD codes, not Census codes, so districts are matched by name.
- ICRISAT District Level Database, unapportioned (about 2015 boundaries), 1990-2019.
  Area in 1000 ha, production in 1000 t, yield in kg/ha; -1 means missing. Cotton is lint;
  sugarcane is gur equivalent (about 6,800 kg/ha, a tenth of cane weight).
- All-India crop production (data.gov.in / DES), 1997-2015. Area in ha, production in tonnes,
  except cotton and jute/mesta (bales) and coconut (nuts). Checked against ICRISAT for 2009-2014:
  state totals agree (median ratio 0.94-1.0) where both cover the same districts, and cotton at
  170 kg per bale matches ICRISAT's lint tonnes (5.7 bales per tonne).

Main steps
1. `clean_rainfall`   remove duplicate district-days (only Leh Ladakh has them; the copies disagree,
                      so they are averaged and flagged).
2. `monthly_rain`     district-month totals with a coverage share (days with data / days in month).
3. `seasonal_rain`    crop-year seasons per district: kharif Jun-Sep, rabi Oct-Feb, agri year Jun-May.
4. `match_districts`  ICRISAT districts to rainfall districts within each state:
                      exact name -> alias table -> fuzzy (difflib), one-to-one.
5. `icrisat_long`     wide ICRISAT table to one row per district-year-crop, with checks.
6. `build_table`      yields joined to seasonal rainfall, 2009-2019.
"""
import difflib
import re

import pandas as pd

# ICRISAT gives Telangana census state code 0; the rainfall file (LGD) uses 36.
STATE_CODE_FIX = {"Telangana": 36}

# Known renames, as (state code, normalised ICRISAT name) -> normalised rainfall name.
ALIASES = {
    (6, "gurgaon"): "gurugram",
    (6, "mewat"): "nuh",
    (9, "allahabad"): "prayagraj",
    (9, "faizabad"): "ayodhya",
    (9, "jyotiba phule nagar"): "amroha",
    (9, "sant ravidas nagar"): "bhadohi",
    (9, "sant ravidas nagar bhadohi"): "bhadohi",
    (9, "kushinagar"): "kushi nagar",
    (9, "lakhimpur kheri"): "kheri",
    (9, "sant kabir nagar"): "sant kabeer nagar",
    (23, "hoshangabad"): "narmadapuram",
    (23, "khandwa"): "east nimar",
    (23, "east nimar khandwa"): "east nimar",
    (23, "west nimar"): "khargone",
    (29, "belgaum"): "belagavi",
    (29, "bellary"): "ballari",
    (29, "bijapur"): "vijayapura",
    (29, "gulbarga"): "kalaburagi",
    (29, "mysore"): "mysuru",
    (29, "shimoga"): "shivamogga",
    (29, "tumkur"): "tumakuru",
    (29, "chikmagalur"): "chikkamagaluru",
    (29, "bangalore"): "bengaluru urban",
    (29, "bangalore urban"): "bengaluru urban",
    (29, "bangalore rural"): "bengaluru rural",
    (29, "bagalkot"): "bagalkote",
    (29, "chamarajanagar"): "chamarajanagara",
    (29, "uttar kannad"): "uttara kannada",
    (29, "dakshin kannad"): "dakshina kannada",
    (28, "cuddapah"): "y s r",
    (28, "kadapa"): "y s r",
    (28, "nellore"): "spsr nellore",
    (28, "visakhapatnam"): "visakhapatanam",
    (36, "rangareddy"): "ranga reddy",
    (24, "ahmedabad"): "ahmadabad",
    (24, "dahod"): "dohad",
    (24, "kutch"): "kachchh",
    (24, "panchmahal"): "panch mahals",
    (24, "panch mahal"): "panch mahals",
    (24, "banaskantha"): "banas kantha",
    (24, "sabarkantha"): "sabar kantha",
    (24, "mehsana"): "mahesana",
    (24, "dangs"): "dang",
    (27, "buldana"): "buldhana",
    (27, "gondiya"): "gondia",
    (27, "raigarh"): "raigad",
    (27, "bid"): "beed",
    (21, "keonjhar"): "kendujhar",
    (21, "balasore"): "baleshwar",
    (21, "bolangir"): "balangir",
    (21, "angul"): "anugul",
    (21, "jajpur"): "jajapur",
    (21, "khurda"): "khordha",
    (21, "nawarangpur"): "nabarangpur",
    (21, "phulbani kandhamal"): "kandhamal",
    (21, "sonepur subarnapur"): "sonepur",
    (21, "subarnapur"): "sonepur",
    (21, "boudh"): "boudh",
    (3, "ropar"): "rupnagar",
    (3, "nawanshahr"): "shahid bhagat singh nagar",
    (3, "muktsar"): "sri muktsar sahib",
    (3, "firozpur"): "ferozepur",
    (3, "bhatinda"): "bathinda",
    (8, "chittaurgarh"): "chittorgarh",
    (8, "dhaulpur"): "dholpur",
    (8, "jhunjhunun"): "jhunjhunu",
    (8, "sri ganganagar"): "ganganagar",
    (33, "kanyakumari"): "kanniyakumari",
    (33, "thoothukudi"): "tuticorin",
    (33, "tiruvallur"): "thiruvallur",
    (33, "tiruvarur"): "thiruvarur",
    (33, "nilgiris"): "the nilgiris",
    (33, "trichy"): "tiruchirappalli",
    (33, "tiruchirapalli"): "tiruchirappalli",
    (33, "kancheepuram"): "kanchipuram",
    (33, "viluppuram"): "villupuram",
    (33, "toothukudi"): "tuticorin",
    (5, "udham singh nagar"): "udam singh nagar",
    (5, "uttarkashi"): "uttar kashi",
    (5, "garhwal"): "pauri garhwal",
    (5, "dehra dun"): "dehradun",
    (5, "rudraprayag"): "rudra prayag",
    (19, "24 parganas north"): "24 paraganas north",
    (19, "24 parganas south"): "24 paraganas south",
    (19, "north 24 parganas"): "24 paraganas north",
    (19, "south 24 parganas"): "24 paraganas south",
    (19, "cooch behar"): "coochbehar",
    (19, "malda"): "maldah",
    (19, "hugli"): "hooghly",
    (19, "haora"): "howrah",
    (19, "uttar dinajpur"): "dinajpur uttar",
    (19, "dakshin dinajpur"): "dinajpur dakshin",
    (19, "medinipur"): "medinipur west",
    (19, "midnapur"): "medinipur west",
    (19, "burdwan"): "paschim bardhaman",
    (19, "bardhaman"): "paschim bardhaman",
    (20, "east singhbhum"): "east singhbum",
    (20, "saraikela"): "saraikela kharsawan",
    (20, "palamau"): "palamu",
    (20, "sahibganj"): "sahebganj",
    (10, "kaimur"): "kaimur bhabua",
    (10, "purnea"): "purnia",
    (10, "east champaran"): "purbi champaran",
    (10, "west champaran"): "pashchim champaran",
    (2, "lahul and spiti"): "lahul and spiti",
    (2, "lahul spiti"): "lahul and spiti",
    (22, "kawardha"): "kabirdham",
    (22, "janjgir"): "janjgir champa",
    (22, "dantewara"): "dantewada",
    (22, "kanker"): "kanker",
    (18, "north cachar hills"): "dima hasao",
    (18, "kamrup rural"): "kamrup",
    (18, "morigaon"): "marigaon",
    (18, "sibsagar"): "sivasagar",
    (32, "trivandrum"): "thiruvananthapuram",
    (32, "quilon"): "kollam",
    (32, "trichur"): "thrissur",
    (32, "alleppey"): "alappuzha",
    (32, "calicut"): "kozhikode",
    (32, "cannanore"): "kannur",
    (32, "palghat"): "palakkad",
    # spellings found when matching the real files (Oct 2026)
    (28, "kadapa ysr"): "y s r",
    (18, "north cachar hil"): "dima hasao",
    (10, "mungair"): "munger",
    (10, "champaran east"): "purbi champaran",
    (10, "champaran west"): "pashchim champaran",
    (10, "bhabhua kaimur"): "kaimur bhabua",
    (22, "koriya"): "korea",
    (20, "santhal paragana dumka"): "dumka",
    (20, "devghar deogarh"): "deoghar",
    (20, "singhbhum east"): "east singhbum",
    (20, "singhbhum west"): "west singhbhum",
    (20, "gadva garhwa"): "garhwa",
    (20, "khodrama koderma"): "koderma",
    (20, "pakund pakur"): "pakur",
    (29, "shimoge"): "shivamogga",
    (29, "chickmagalur"): "chikkamagaluru",
    (23, "sheopur kalan"): "sheopur",
    (27, "amarawati"): "amravati",
    (27, "yeotmal"): "yavatmal",
    (27, "mumbai sub"): "mumbai suburban",
    (27, "mumbai city"): "mumbai",
    (3, "roopnagar"): "rupnagar",
    (3, "s b s nagar"): "shahid bhagat singh nagar",
    (8, "karoli"): "karauli",
    (33, "south arcot cuddalore"): "cuddalore",
    (33, "north arcot vellore"): "vellore",
    (33, "tiruchirapalli trichy"): "tiruchirappalli",
    (33, "periyar erode"): "erode",
    (33, "dindigul anna"): "dindigul",
    (33, "virudhunagar kamarajar"): "virudhunagar",
    (33, "sivagangai pasumpon"): "sivaganga",
    (33, "chidambanar toothukudi"): "tuticorin",
    (33, "perambular"): "perambalur",
    (9, "kushi nagar padrauna"): "kushi nagar",
    (9, "g b nagar"): "gautam buddha nagar",
    (9, "amroha j b fulenagar"): "amroha",
    (9, "santh ravi das nagar bhadoi"): "bhadohi",
    (9, "kasganj khansi ram nagar"): "kasganj",
    (19, "east midnapore purba midnapore"): "medinipur east",
    (19, "west midnapore"): "medinipur west",
}

# Districts created after the rainfall file's boundaries (about 2012-2019). They have no rainfall
# series of their own, so they borrow the district they were carved out of ("parent" match).
# (state code, normalised ICRISAT name) -> normalised rainfall name of the parent district.
PARENTS = {
    (18, "biswanath"): "sonitpur", (18, "charaideo"): "sivasagar", (18, "hojai"): "nagaon",
    (18, "majuli"): "jorhat", (18, "south salmara mankachar"): "dhubri",
    (18, "west karbi anglong"): "karbi anglong",
    (22, "balod"): "durg", (22, "bemetra"): "durg", (22, "baloda bazar"): "raipur",
    (22, "gariaband"): "raipur", (22, "balrampur"): "surguja", (22, "surajpur"): "surguja",
    (22, "kondagaon"): "bastar", (22, "sukma"): "dantewada", (22, "mungli"): "bilaspur",
    (22, "gaurela pendra marwahi"): "bilaspur",
    (24, "aravalli"): "sabar kantha", (24, "botad"): "bhavnagar",
    (24, "chhota udaipur"): "vadodara", (24, "devbhoomi dwarka"): "jamnagar",
    (24, "gir somnath"): "junagadh", (24, "mahi sagar"): "panch mahals", (24, "morbi"): "rajkot",
    (6, "charkhi dadri"): "bhiwani",
    (23, "agar malwa"): "shajapur", (23, "niwari"): "tikamgarh",
    (27, "palghar"): "thane",
    (3, "pathankot"): "gurdaspur", (3, "fazilka"): "ferozepur",
    (33, "tenkasi"): "tirunelveli", (33, "kallakurichi"): "villupuram",
    (33, "tirupattur"): "vellore", (33, "ranipet"): "vellore",
    (33, "chengalpattu"): "kanchipuram", (33, "mayiladuthurai"): "nagapattinam",
    (36, "kumurambheem asifabad"): "adilabad", (36, "macherial"): "adilabad",
    (36, "nirmal"): "adilabad", (36, "jagityal"): "karimnagar", (36, "peddapally"): "karimnagar",
    (36, "rajanna siricilla"): "karimnagar", (36, "bhadradri"): "khammam",
    (36, "jogulamba"): "mahabubnagar", (36, "nagarkurnool"): "mahabubnagar",
    (36, "wanaparthy"): "mahabubnagar", (36, "narayanpet"): "mahabubnagar",
    (36, "sangareddy"): "medak", (36, "siddipet"): "medak", (36, "suryapet"): "nalgonda",
    (36, "yadadri bhuvanagiri"): "nalgonda", (36, "kamareddy"): "nizamabad",
    (36, "malkaigiri"): "ranga reddy", (36, "vikarabad"): "ranga reddy",
    (36, "jayashankar bhuppaly"): "warangal", (36, "janagaon"): "warangal",
    (36, "warangal urban"): "warangal", (36, "mahabubabad"): "warangal",
    (36, "mulugu"): "warangal",
    (9, "amethi c s m nagar"): "sultanpur", (9, "sambhal"): "moradabad",
    (9, "shamli"): "muzaffarnagar", (9, "hapur"): "ghaziabad",
    (19, "kalimpong"): "darjeeling", (19, "alipurduar"): "jalpaiguri",
    (19, "jhargram"): "medinipur west", (19, "paschim bardhaman"): "paschim bardhaman",
}


def norm(name):
    """Lower-case, '&' -> 'and', drop punctuation and the word 'district', squash spaces."""
    s = str(name).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(district|dist)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- rainfall ----------

def clean_rainfall(df):
    """Parse dates, drop negative values, average duplicate district-days and flag them."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    for c in ("actual", "normal"):
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            out.loc[out[c] < 0, c] = float("nan")
    key = ["district_code", "date"]
    dup = out.duplicated(key, keep=False)
    if dup.any():
        ids = [c for c in ("state_code", "state_name", "district_name") if c in out]
        agg = {c: "first" for c in ids}
        agg.update({c: "mean" for c in ("actual", "normal") if c in out})
        merged = out[dup].groupby(key, as_index=False).agg(agg)
        merged["dup_averaged"] = True
        out = pd.concat([out[~dup].assign(dup_averaged=False), merged], ignore_index=True)
    else:
        out["dup_averaged"] = False
    return out.sort_values(key).reset_index(drop=True)


def monthly_rain(df):
    """District-month rain total (mm), normal (mm), days with data and coverage share."""
    d = df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
    g = d.groupby(["district_code", "year", "month"])
    out = g.agg(rain_mm=("actual", "sum"), normal_mm=("normal", "sum"),
                days_obs=("actual", "count")).reset_index()
    days = pd.to_datetime(dict(year=out.year, month=out.month, day=1)).dt.days_in_month
    out["coverage"] = out["days_obs"] / days
    return out


SEASONS = {  # month -> (season, offset added to calendar year to get the crop year)
    "kharif": {6: 0, 7: 0, 8: 0, 9: 0},
    "rabi": {10: 0, 11: 0, 12: 0, 1: -1, 2: -1},
    "agri_year": {6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 1: -1, 2: -1, 3: -1, 4: -1, 5: -1},
}


def seasonal_rain(monthly, min_coverage=0.8):
    """Per district and crop year (the year the kharif season starts): season totals.

    A season is marked `complete` when every month in it is present with coverage >= min_coverage.
    Rain in a month with partial data is scaled up by 1/coverage before summing.
    """
    rows = []
    for season, months in SEASONS.items():
        m = monthly[monthly["month"].isin(months.keys())].copy()
        m["crop_year"] = m["year"] + m["month"].map(months)
        m["rain_scaled"] = m["rain_mm"] / m["coverage"].where(m["coverage"] > 0)
        g = m.groupby(["district_code", "crop_year"])
        s = g.agg(rain_mm=("rain_scaled", "sum"), normal_mm=("normal_mm", "sum"),
                  n_months=("month", "nunique"), min_cov=("coverage", "min")).reset_index()
        s["complete"] = (s["n_months"] == len(months)) & (s["min_cov"] >= min_coverage)
        s["season"] = season
        rows.append(s)
    out = pd.concat(rows, ignore_index=True)
    out["departure_pct"] = 100 * (out["rain_mm"] - out["normal_mm"]) / out["normal_mm"].where(
        out["normal_mm"] > 0)
    wide = out.pivot_table(index=["district_code", "crop_year"], columns="season",
                           values=["rain_mm", "departure_pct", "complete"], aggfunc="first")
    wide.columns = [f"{s}_{v}" for v, s in wide.columns]
    return wide.reset_index()


# ---------- district matching ----------

def icrisat_districts(icrisat):
    """Unique ICRISAT districts with a state code that matches the rainfall file."""
    cols = ["Dist Code", "Dist Name", "State Name", "Indian census State Code 2011"]
    d = icrisat[cols].drop_duplicates("Dist Code").rename(columns={
        "Dist Code": "icrisat_dist", "Dist Name": "icrisat_name", "State Name": "state",
        "Indian census State Code 2011": "state_code"})
    d["state_code"] = d.apply(lambda r: STATE_CODE_FIX.get(r["state"], r["state_code"]), axis=1)
    return d.reset_index(drop=True)


def match_districts(icr, rain, aliases=ALIASES, cutoff=0.85, parents=PARENTS):
    """Match ICRISAT districts to rainfall districts within each state, one to one.

    icr:  icrisat_dist, icrisat_name, state_code
    rain: district_code, district_name, state_code
    Returns one row per ICRISAT district: district_code (or NA), rain_name, method, score.
    Districts still unmatched that appear in `parents` get their parent's rainfall district
    (method "parent"); several ICRISAT districts may share one parent.
    """
    rain = rain.assign(n=rain["district_name"].map(norm))
    out = []
    for sc, grp in icr.groupby("state_code"):
        pool = rain[rain["state_code"] == sc]
        free = dict(zip(pool["n"], pool["district_code"]))
        names = dict(zip(pool["district_code"], pool["district_name"]))
        pending = []
        for _, r in grp.iterrows():
            n = norm(r["icrisat_name"])
            target, method = None, None
            if n in free:
                target, method = n, "exact"
            elif aliases.get((sc, n)) in free:
                target, method = aliases[(sc, n)], "alias"
            if target:
                code = free.pop(target)
                out.append({**r, "district_code": code, "rain_name": names[code],
                            "method": method, "score": 1.0})
            else:
                pending.append((r, n))
        # fuzzy, best scores first, one to one
        cands = []
        for r, n in pending:
            for fn in free:
                sc_ = difflib.SequenceMatcher(None, n, fn).ratio()
                if sc_ >= cutoff:
                    cands.append((sc_, r["icrisat_dist"], fn))
        taken = set()
        for sc_, idist, fn in sorted(cands, key=lambda t: t[0], reverse=True):
            if idist in taken or fn not in free:
                continue
            taken.add(idist)
            r = next(r for r, _ in pending if r["icrisat_dist"] == idist)
            code = free.pop(fn)
            out.append({**r, "district_code": code, "rain_name": names[code],
                        "method": "fuzzy", "score": round(sc_, 3)})
        for r, _ in pending:
            if r["icrisat_dist"] not in taken:
                out.append({**r, "district_code": pd.NA, "rain_name": pd.NA,
                            "method": "none", "score": 0.0})
    res = pd.DataFrame(out)
    lookup = {(r.state_code, norm(r.district_name)): (r.district_code, r.district_name)
              for r in rain.itertuples()}
    for i, r in res[res["method"] == "none"].iterrows():
        par = parents.get((r["state_code"], norm(r["icrisat_name"])))
        hit = lookup.get((r["state_code"], par)) if par else None
        if hit:
            res.loc[i, ["district_code", "rain_name", "method", "score"]] = [*hit, "parent", 1.0]
    return res


# ---------- yields ----------

def icrisat_long(icrisat):
    """One row per district-year-crop: area_ha, production_t, yield_kg_ha (ICRISAT's), checks.

    -1 and other negatives become missing. `yield_check` is ICRISAT's yield divided by
    production / area; values far from 1 point at unit or entry errors.
    """
    pat = re.compile(r"^(.*) (AREA|PRODUCTION|YIELD) \[(.*)\]$")
    parts = {}
    for c in icrisat.columns:
        m = pat.match(c)
        if m:
            parts.setdefault(m.group(1), {})[m.group(2)] = c
    base = icrisat[["Dist Code", "Year"]].rename(columns={"Dist Code": "icrisat_dist",
                                                         "Year": "year"})
    rows = []
    for crop, cols in parts.items():
        if "AREA" not in cols:
            continue
        t = base.copy()
        t["crop"] = crop.title()
        t["area_ha"] = icrisat[cols["AREA"]] * 1000
        t["production_t"] = icrisat[cols["PRODUCTION"]] * 1000 if "PRODUCTION" in cols else pd.NA
        t["yield_kg_ha"] = icrisat[cols["YIELD"]] if "YIELD" in cols else pd.NA
        rows.append(t)
    out = pd.concat(rows, ignore_index=True)
    for c in ("area_ha", "production_t", "yield_kg_ha"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
        out.loc[out[c] < 0, c] = float("nan")
    # contradictions: a yield with no area, or zero yield on a sown area -> missing, flagged
    bad = ((out["area_ha"].fillna(0) == 0) & (out["yield_kg_ha"] > 0)) | \
          ((out["area_ha"] > 0) & (out["yield_kg_ha"] == 0))
    out["flag"] = bad.map({True: "area/yield contradict", False: ""})
    out.loc[bad, "yield_kg_ha"] = float("nan")
    out.loc[out["area_ha"].fillna(0) == 0, "yield_kg_ha"] = float("nan")
    calc = 1000 * out["production_t"] / out["area_ha"].where(out["area_ha"] > 0)
    out["yield_check"] = out["yield_kg_ha"] / calc.where(calc > 0)
    # ICRISAT reports sugarcane as gur (jaggery), about a tenth of cane weight
    out["unit_note"] = out["crop"].map({"Sugarcane": "gur equivalent, not cane"}).fillna("")
    return out


# All-India file: units that are not tonnes, and the factor to tonnes
BALE_CROPS = {"cotton(lint)": 0.170, "jute": 0.180, "mesta": 0.180, "jute & mesta": 0.180}
NON_WEIGHT_CROPS = {"coconut"}           # reported in nuts; no weight conversion


def all_india_long(df):
    """All-India crop file to the standard columns, with bale crops converted to tonnes.

    Crops reported in nuts are kept but their production and yield are set to missing.
    """
    from .yields import standardise
    d = df.copy()
    crop_key = d["Crop"].astype(str).str.strip().str.lower()
    factor = crop_key.map(BALE_CROPS).fillna(1.0)
    d["Production"] = pd.to_numeric(d["Production"], errors="coerce") * factor
    d.loc[crop_key.isin(NON_WEIGHT_CROPS), "Production"] = float("nan")
    d["unit_note"] = crop_key.map(lambda k: "bales->t" if k in BALE_CROPS else
                                  ("nuts, dropped" if k in NON_WEIGHT_CROPS else ""))
    out = standardise(d, {"State_Name": "state", "District_Name": "district", "Crop": "crop",
                          "Season": "season", "Crop_Year": "year", "Area": "area_ha",
                          "Production": "production_t"}, source="data.gov.in all-India")
    out["unit_note"] = d["unit_note"].values
    return out


# ---------- the joined table ----------

def build_table(icr_long, matches, seasons, years=(2009, 2019)):
    """ICRISAT yields joined to seasonal rainfall through the district match, for `years`."""
    m = matches.dropna(subset=["district_code"])[["icrisat_dist", "district_code", "state",
                                                  "icrisat_name", "method"]]
    y = icr_long[(icr_long["year"] >= years[0]) & (icr_long["year"] <= years[1])]
    y = y.merge(m, on="icrisat_dist", how="inner")
    return y.merge(seasons, left_on=["district_code", "year"],
                   right_on=["district_code", "crop_year"], how="left")
