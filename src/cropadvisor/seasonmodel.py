"""Season-start model: expected yield and income per acre for each crop in a Haryana or Punjab
district, how much they vary, and how often one crop beats another ("crop A beats crop B in 7 of
10 likely seasons").

Model. The regression ensemble from the JISEM paper (Jain and Soni 2025): the average of a Random
Forest, XGBoost and LightGBM, retrained on real district data instead of the paper's Kaggle and
Mendeley sets. Target: the season's yield as a ratio to the district's average of its last five
years with data (so districts of different levels can be pooled). Features: that 5-year average,
last year's ratio, the 10-year trend, IMD season rainfall for the crop's own months (total against
the IMD normal, and three sub-periods), the year, the crop and the state. Rows: Haryana and Punjab
district-crop-years from 2009 (when the IMD district record starts) to 2022 where the crop had at
least MIN_AREA_HA, from ICRISAT (to 2019) and DES (2020-2022), with yields back to 2000 for the
lagged features.

Validation (ml-limitations section 3): split by time only. Hyperparameters fixed in advance (small,
regularised); the paper's random 5-fold cross-validation is not used because it leaks a year's
weather between folds. Validation: trained on 2009-2013, scored on 2014-2016; the ensemble is used
for a crop only if it beats the last-5-year average there (the "gate"). Test, once: trained on
2009-2016, scored on 2017-2022, against the long-run mean, the trend and the last-5-year average,
in quintal per acre (scripts/check_season_model.py, data/checks/season_model_*.csv). Predictions are
made the same number of years ahead of the data as they will be used (the data end in 2022).

Likely seasons. A season to come is unknown, so it is replayed as each past season: the IMD rain of
every year 2009-2024 is put through the model, and the model's own out-of-sample error for that
district and year is added back, so a scenario carries that year's weather and everything else that
happened that year. Prices: the latest harvest price (as in outlook.py) times one of the past
year-on-year price changes (state mandi prices, 2016-2025), the same change for every crop in a
scenario. Every rain year is paired with every price year. Yields and prices are district averages
and market prices, so incomes are the gross value of a district-average acre before costs, not a
farmer's profit, and the share of seasons in which one crop beats another reflects past weather,
past price moves and the model's past errors, not a forecast of this season.

Units: rice is converted to paddy at the official 67 percent out-turn; cotton lint to kapas at a
ginning outturn of 31, 34 or 37 percent (north zone 33-35 percent, CAI 2021; north zone Bt hybrid
trials 30.8-36.9 percent, AICRP 2008-09), cycled across scenarios.
"""
import functools
import os

import numpy as np
import pandas as pd

from cropadvisor import outlook as ol

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
YIELDS = os.path.join(ROOT, "data", "reference", "district_yields_all.csv")
RAIN = os.path.join(ROOT, "data", "reference", "district_rain_monthly.csv")

MIN_AREA_HA = 1000          # smaller district crops have rounded, noisy yields
HISTORY_YEARS = 5
FIRST_RAIN_YEAR = 2009
VAL = (range(2009, 2014), range(2014, 2017))
TEST = (range(2009, 2017), range(2017, 2023))
RATIO_CLIP = (0.3, 2.0)
GOT_CYCLE = (0.31, 0.34, 0.37)
FEW_SEASONS = 8          # fewer past seasons than this: flagged in the text
PADDY_PER_RICE = 1 / 0.67

# calculator / outlook key -> (yield crop, season)
CROPS = {
    "wheat": ("Wheat", "rabi"), "mustard": ("Mustard", "rabi"), "barley": ("Barley", "rabi"),
    "chickpea": ("Chickpea", "rabi"),
    "paddy": ("Rice", "kharif"), "cotton": ("Cotton", "kharif"),
    "kharif_maize": ("Maize", "kharif"), "bajra": ("Bajra", "kharif"),
    "groundnut": ("Groundnut", "kharif"),
}
# IMD rain periods per season: (start (year offset, month), end (year offset, month))
PERIODS = {
    "rabi": [((0, 10), (0, 11)), ((0, 12), (1, 1)), ((1, 2), (1, 3))],
    "kharif": [((0, 6), (0, 7)), ((0, 8), (0, 9)), ((0, 10), (0, 10))],
}
SEASON_SPAN = {"rabi": ((0, 10), (1, 3)), "kharif": ((0, 6), (0, 9))}
FEATURES = ["lag_mean5", "last_ratio", "trend10", "rain_dep", "rain_p1", "rain_p2", "rain_p3",
            "punjab"]   # no "year": tree models cannot carry a year beyond the years they saw + [f"crop_{c}" for c in sorted({v[0] for v in CROPS.values()})]


# ------------------------------------------------------------------------------- data

@functools.lru_cache(maxsize=4)
def load_yields(path=None):
    y = pd.read_csv(path or YIELDS)
    return y[y["yield_t_ha"].notna() & (y["yield_t_ha"] > 0)]


@functools.lru_cache(maxsize=4)
def load_rain(path=None):
    r = pd.read_csv(path or RAIN)
    ok = r["coverage"] >= 0.5          # July 2020 has 16 of 31 days: scaled up, as elsewhere
    r["rain_full"] = np.where(ok, r["rain_mm"] / r["coverage"].clip(lower=0.5), np.nan)
    return r.set_index(["district", "year", "month"])


def _months(year, start, end):
    (o1, m1), (o2, m2) = start, end
    d = pd.date_range(pd.Timestamp(year + o1, m1, 1), pd.Timestamp(year + o2, m2, 1), freq="MS")
    return [(x.year, x.month) for x in d]


def rain_features(district, season, rain_year, rain=None):
    """IMD rain features for a district's crop season in data year rain_year, or None."""
    rain = load_rain(RAIN) if rain is None else rain
    def tot(months, col):
        vals = [rain[col].get((district, yy, mm), np.nan) for yy, mm in months]
        return np.nan if any(pd.isna(v) for v in vals) else float(sum(vals))
    span = _months(rain_year, *SEASON_SPAN[season])
    actual, normal = tot(span, "rain_full"), tot(span, "normal_mm")
    if pd.isna(actual) or not normal:
        return None
    out = {"rain_dep": 100 * (actual - normal) / normal}
    for i, (a, b) in enumerate(PERIODS[season], 1):
        mm = _months(rain_year, a, b)
        r, n = tot(mm, "rain_full"), tot(mm, "normal_mm")
        if pd.isna(r):
            return None
        out[f"rain_p{i}"] = min(r / n, 5.0) if n else 1.0
    return out


def history_features(series, upto_year):
    """Lagged-yield features from a year -> yield series, using years <= upto_year."""
    s = series[series.index <= upto_year].sort_index()
    last5 = s.tail(HISTORY_YEARS)
    if len(last5) < 3:
        return None
    m5 = float(last5.mean())
    t10 = s.tail(10)
    slope = float(np.polyfit(t10.index, t10.values, 1)[0]) if len(t10) >= 5 else 0.0
    prev = s.tail(HISTORY_YEARS + 1)
    last_ratio = float(s.iloc[-1] / prev.iloc[:-1].mean()) if len(prev) >= 4 else 1.0
    return {"lag_mean5": m5, "last_ratio": last_ratio, "trend10": slope / m5}


def _crop_cols(crop):
    return {f"crop_{c}": float(c == crop) for c in sorted({v[0] for v in CROPS.values()})}


@functools.lru_cache(maxsize=8)
def build_rows(horizon=1, yields_path=None, rain_path=None):
    """One row per district-crop-year (target year >= 2009) with features made `horizon` years
    after the last yield they use."""
    y, rain = load_yields(yields_path), load_rain(rain_path)
    season_of = {v[0]: v[1] for v in CROPS.values()}
    rows = []
    for (crop, district), g in y.groupby(["crop", "district"]):
        if crop not in season_of:
            continue
        g = g[g["area_ha"] >= MIN_AREA_HA]
        s = g.set_index("year")["yield_t_ha"]
        state = g["state"].iloc[0] if len(g) else ""
        for yr, actual in s[s.index >= FIRST_RAIN_YEAR].items():
            h = history_features(s, yr - horizon)
            r = rain_features(district, season_of[crop], yr, rain)
            if h is None or r is None:
                continue
            rows.append({"district": district, "crop": crop, "year": int(yr), "actual": actual,
                         "ratio": actual / h["lag_mean5"], "punjab": float(state == "Punjab"),
                         **h, **r, **_crop_cols(crop)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------- model

class Ensemble:
    """Average of Random Forest, XGBoost and LightGBM regressors (the JISEM paper's ensemble),
    small and regularised for about 3,000 rows. Fixed settings, not tuned on the test years."""

    def __init__(self, seed=0):
        from lightgbm import LGBMRegressor
        from sklearn.ensemble import RandomForestRegressor
        from xgboost import XGBRegressor
        self.models = [
            RandomForestRegressor(n_estimators=300, min_samples_leaf=5, max_features=0.5,
                                  random_state=seed, n_jobs=-1),
            XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8,
                         colsample_bytree=0.8, reg_lambda=5.0, random_state=seed, n_jobs=4,
                         verbosity=0),
            LGBMRegressor(n_estimators=300, num_leaves=8, learning_rate=0.03,
                          min_child_samples=20, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.8, reg_lambda=5.0, random_state=seed, verbose=-1),
        ]

    def fit(self, X, y):
        for m in self.models:
            m.fit(X[FEATURES], y)
        return self

    def predict(self, X):
        p = np.mean([m.predict(X[FEATURES]) for m in self.models], axis=0)
        return np.clip(p, *RATIO_CLIP)

    def importance(self):
        rf = self.models[0].feature_importances_
        return pd.Series(rf, index=FEATURES).sort_values(ascending=False)


def baselines(rows, yields_path=None, horizon=1):
    """Long-run mean and linear trend from all yields up to year - horizon (from 2000)."""
    y = load_yields(yields_path)
    y = y[y["area_ha"] >= MIN_AREA_HA]
    series = {k: g.set_index("year")["yield_t_ha"] for k, g in y.groupby(["crop", "district"])}
    mean, trend = [], []
    for r in rows.itertuples():
        s = series[(r.crop, r.district)]
        s = s[s.index <= r.year - horizon]
        mean.append(float(s.mean()))
        trend.append(float(np.polyval(np.polyfit(s.index, s.values, 1), r.year))
                     if len(s) >= 5 else float(s.mean()))
    return np.array(mean), np.array(trend)


def evaluate(horizon=1, split=TEST, yields_path=None, rain_path=None):
    """Errors in quintal per acre on the split's scored years, per crop and method."""
    rows = build_rows(horizon, yields_path, rain_path)
    tr = rows[rows["year"].isin(split[0])]
    te = rows[rows["year"].isin(split[1])].copy()
    model = Ensemble().fit(tr, tr["ratio"])
    te["pred_ensemble"] = te["lag_mean5"] * model.predict(te)
    te["pred_last5"] = te["lag_mean5"]
    te["pred_mean"], te["pred_trend"] = baselines(te, yields_path, horizon)
    q = ol.T_HA_TO_Q_ACRE
    out = []
    for crop, g in te.groupby("crop"):
        for m in ("ensemble", "last5", "mean", "trend"):
            e = (g[f"pred_{m}"] - g["actual"]) * q
            out.append({"crop": crop, "method": m, "mae_q_acre": round(float(e.abs().mean()), 3),
                        "bias_q_acre": round(float(e.mean()), 3), "n": len(g),
                        "districts": g["district"].nunique()})
    return pd.DataFrame(out), te, model


def rolling_validation(horizon=1, years=VAL[1], yields_path=None, rain_path=None):
    """Each validation year predicted by a model trained on all target years before it (rolling
    origin), so the validation sees the training sizes the model really has. Errors in quintal per
    acre per crop and method."""
    rows = build_rows(horizon, yields_path, rain_path)
    parts = []
    for yr in years:
        tr = rows[(rows["year"] >= VAL[0][0]) & (rows["year"] <= yr - horizon)]
        te = rows[rows["year"] == yr].copy()
        if tr.empty or te.empty:
            continue
        te["pred_ensemble"] = te["lag_mean5"] * Ensemble().fit(tr, tr["ratio"]).predict(te)
        te["pred_last5"] = te["lag_mean5"]
        parts.append(te)
    te = pd.concat(parts)
    q = ol.T_HA_TO_Q_ACRE
    out = []
    for crop, g in te.groupby("crop"):
        for m in ("ensemble", "last5"):
            e = (g[f"pred_{m}"] - g["actual"]) * q
            out.append({"crop": crop, "method": m, "mae_q_acre": round(float(e.abs().mean()), 3),
                        "n": len(g)})
    return pd.DataFrame(out)


GATE_HORIZON = 1   # validation 4+ years ahead has only 3-4 training years, too few to judge


@functools.lru_cache(maxsize=2)
def gate(yields_path=None, rain_path=None):
    """Crops for which the ensemble beat the last-5-year average on the validation years
    (rolling origin, 2014-2016, one year ahead). Decided before the test years are looked at,
    and used at every distance ahead."""
    v = rolling_validation(GATE_HORIZON, yields_path=yields_path, rain_path=rain_path)
    p = v.pivot(index="crop", columns="method", values="mae_q_acre")
    return {c: bool(p.loc[c, "ensemble"] < p.loc[c, "last5"]) for c in p.index}


@functools.lru_cache(maxsize=8)
def fitted(horizon, yields_path=None, rain_path=None):
    """Ensemble on all rows, plus out-of-sample residuals (each year predicted by a model trained
    without that year's group of years), keyed by (crop, district, year), and the actual ratios
    (yield over the 5-year average `horizon` years earlier) for the same keys."""
    rows = build_rows(horizon, yields_path, rain_path)
    model = Ensemble().fit(rows, rows["ratio"])
    years = sorted(rows["year"].unique())
    folds = [years[i::5] for i in range(5)]
    resid = {}
    for f in folds:
        tr, te = rows[~rows["year"].isin(f)], rows[rows["year"].isin(f)]
        p = Ensemble().fit(tr, tr["ratio"]).predict(te)
        for r, pr in zip(te.itertuples(), p):
            resid[(r.crop, r.district, r.year)] = r.ratio - pr
    ratios = {(r.crop, r.district, r.year): r.ratio for r in rows.itertuples()}
    return model, resid, ratios


# ------------------------------------------------------------------------------- scenarios

def _to_market(crop, t_ha, k):
    """t/ha to the unit the mandi price is in, per acre (quintal paddy, kapas, etc.)."""
    q = t_ha * ol.T_HA_TO_Q_ACRE
    if crop == "Rice":
        return q * PADDY_PER_RICE
    if crop == "Cotton":
        return q / GOT_CYCLE[k % len(GOT_CYCLE)]
    return q


def price_changes(key, today):
    """Year-on-year changes in the state harvest-season price for one crop, {season: ratio}."""
    p = ol._prices()
    _, _, _, commodity, _ = ol.CROPS[key]
    months = ol.harvest_months(key)
    today = pd.Timestamp(today)
    out = {}
    for state in ol.STATES:
        c = p[(p["commodity"] == commodity) & (p["state"] == state) & (p["level"] == "state")
              & (p["date"] < today) & p["date"].dt.month.isin(months)]
        if c.empty:
            continue
        yr = c["date"].dt.year - np.where(c["date"].dt.month < months[0], 1, 0)
        s = c.assign(season=yr).groupby("season")["p_modal"].mean().sort_index()
        out[state] = {int(b): float(s[b] / s[a]) for a, b in zip(s.index[:-1], s.index[1:])
                      if b == a + 1}
    return out


def season_scenarios(district, state, season, today, keys=None, yields_path=None,
                     rain_path=None):
    """Scenario incomes for every crop of the season that the district grows enough of.

    Ensemble crops (passed the gate): ratio = model(IMD rain of year r) + the model's
    out-of-sample error for this district and year r. Other crops: ratio = the actual ratio of
    year r (its yield over its 5-year average the same distance earlier), i.e. the 5-year average
    with the spread of its own past errors. Missing years take the crop's median."""
    today = pd.Timestamp(today)
    y = load_yields(yields_path)
    keys = keys or [k for k, v in CROPS.items() if v[1] == season]
    data_end = int(y["year"].max())
    s_year = ol.season_year(keys[0], today)
    horizon = int(min(max(s_year - data_end, 1), 6))
    model, resid, ratios = fitted(horizon, yields_path, rain_path)
    use_model = gate(yields_path, rain_path)
    rain = load_rain(rain_path)
    rain_years = [yr for yr in range(FIRST_RAIN_YEAR, today.year + 1)
                  if rain_features(district, season, yr, rain) is not None]
    crops = {}
    for k in keys:
        crop = CROPS[k][0]
        g = y[(y["district"].str.lower() == district.lower()) & (y["crop"] == crop)]
        g = g[g["area_ha"] >= MIN_AREA_HA]
        if len(g[g["year"] >= data_end - HISTORY_YEARS + 1]) < 3:
            continue          # not grown enough here lately: no outlook for it
        dname = g["district"].iloc[0]
        s = g.set_index("year")["yield_t_ha"]
        h = history_features(s, data_end)
        price = ol.price_outlook(dname, state, ol.CROPS[k][3], ol.harvest_months(k), today)
        if h is None or price is None:
            continue
        own = [ratios[(crop, dname, r)] for r in rain_years if (crop, dname, r) in ratios]
        if use_model.get(crop, False):
            X = pd.DataFrame([{**h, **rain_features(dname, season, r, rain),
                               "punjab": float(state == "Punjab"), **_crop_cols(crop)}
                              for r in rain_years])
            ratio = model.predict(X) + np.array([resid.get((crop, dname, r), 0.0)
                                                 for r in rain_years])
            method = "ensemble"
        else:
            med = float(np.median(own)) if own else 1.0
            ratio = np.array([ratios.get((crop, dname, r), med) for r in rain_years])
            method = "last5"
        crops[k] = {"crop": crop, "method": method, "rain_years": rain_years,
                    "own_years": len(own),
                    "yield_t_ha": h["lag_mean5"] * np.clip(ratio, 0.05, None), "price": price,
                    "changes": price_changes(k, today).get(state, {}),
                    "lag_mean5": h["lag_mean5"]}
    if not crops:
        return None, s_year, horizon
    years = sorted({q for c in crops.values() for q in c["changes"]}) or [None]
    table = {}
    for k, c in crops.items():
        med = float(np.median(list(c["changes"].values()))) if c["changes"] else 1.0
        inc, yld = [], []
        for i, yt in enumerate(c["yield_t_ha"]):
            mk = _to_market(c["crop"], yt, i)
            for q in years:
                ch = c["changes"].get(q, med) if q is not None else 1.0
                yld.append(mk)
                inc.append(mk * c["price"]["price"] * ch)
        table[k] = {"income": np.array(inc), "yield_market": np.array(yld),
                    "price_years": years, **c}
    return table, s_year, horizon


def summarise(table):
    """Per crop: expected yield and income with 10th-90th percentile; pairwise wins of 10."""
    out = {}
    for k, c in table.items():
        inc, yl = c["income"], c["yield_market"]
        out[k] = {"method": c["method"], "n_scenarios": int(len(inc)),
                  "yield_q_acre": round(float(np.mean(yl)), 1),
                  "yield_low": round(float(np.percentile(yl, 10)), 1),
                  "yield_high": round(float(np.percentile(yl, 90)), 1),
                  "income_rs_acre": int(round(float(np.mean(inc)), -2)),
                  "income_low": int(round(float(np.percentile(inc, 10)), -2)),
                  "income_high": int(round(float(np.percentile(inc, 90)), -2)),
                  "price": c["price"]["price"], "price_season": c["price"]["latest_season"],
                  "rain_years": (min(c["rain_years"]), max(c["rain_years"])),
                  "past_seasons_with_data": int(c["own_years"])}
    keys = list(table)
    wins = {}
    for a in keys:
        for b in keys:
            if a < b and len(table[a]["income"]) == len(table[b]["income"]):
                share = float(np.mean(table[a]["income"] > table[b]["income"]))
                wins[f"{a}|{b}"] = round(share, 3)
    return out, wins


# ------------------------------------------------------------------------------- text

NAMES = {k: (ol.CROPS[k][0], ol.CROPS[k][1]) for k in CROPS}
UNIT_EN = {"Rice": "quintal of paddy", "Cotton": "quintal of kapas"}
UNIT_HI = {"Rice": "क्विंटल धान", "Cotton": "क्विंटल कपास"}


def season_outlook(district, state, season, today, yields_path=None, rain_path=None):
    """Dict for the service, or None when the district has no crop with enough data."""
    table, s_year, horizon = season_scenarios(district, state, season, today,
                                              yields_path=yields_path, rain_path=rain_path)
    if not table:
        return None
    per_crop, wins = summarise(table)
    return {"district": district, "state": state, "season": season, "season_year": s_year,
            "years_ahead_of_data": horizon, "crops": per_crop, "wins": wins,
            "units": {k: UNIT_EN.get(CROPS[k][0], "quintal") for k in per_crop}}


def text(so):
    """English and Hindi lines."""
    if not so:
        return [], []
    season_en = "winter (rabi)" if so["season"] == "rabi" else "summer (kharif)"
    season_hi = "रबी" if so["season"] == "rabi" else "ख़रीफ़"
    n = next(iter(so["crops"].values()))["n_scenarios"]
    ry = next(iter(so["crops"].values()))["rain_years"]
    en = [f"Season-start model, {season_en} {so['season_year']}, {so['district']}: "
          f"{n} likely seasons (the weather of {ry[0]}-{ry[1]} x past price changes)."]
    hi = [f"मौसम-शुरुआत मॉडल, {season_hi} {so['season_year']}, {so['district']}: {n} संभावित "
          f"मौसम ({ry[0]}-{ry[1]} का मौसम x पिछले भाव-बदलाव)।"]
    ranked = sorted(so["crops"].items(), key=lambda kv: -kv[1]["income_rs_acre"])
    for k, c in ranked:
        name_en, name_hi = NAMES[k]
        crop = CROPS[k][0]
        tag = (f" (only {c['past_seasons_with_data']} past seasons of data)"
               if c["past_seasons_with_data"] < FEW_SEASONS else "")
        en.append(f"{name_en}: about {c['yield_q_acre']:g} {UNIT_EN.get(crop, 'quintal')} per acre "
                  f"({c['yield_low']:g}-{c['yield_high']:g}); gross income about "
                  f"Rs {c['income_rs_acre']:,} per acre (Rs {c['income_low']:,} to "
                  f"Rs {c['income_high']:,} in 8 of 10 seasons){tag}.")
        hi.append(f"{name_hi}: लगभग {c['yield_q_acre']:g} {UNIT_HI.get(crop, 'क्विंटल')} प्रति एकड़; "
                  f"कुल आमदनी लगभग {c['income_rs_acre']:,} रुपये प्रति एकड़ (10 में से 8 मौसमों में "
                  f"{c['income_low']:,} से {c['income_high']:,} रुपये)।")
    best = ranked[0][0]
    for k, _ in ranked[1:]:
        a, b = sorted((best, k))
        share = so["wins"].get(f"{a}|{b}")
        if share is None:
            continue
        s_best = share if a == best else 1 - share
        n10 = int(round(10 * s_best))
        en.append(f"{NAMES[best][0]} beats {NAMES[k][0].lower()} in {n10} of 10 likely seasons.")
        hi.append(f"10 में से {n10} संभावित मौसमों में {NAMES[best][1]} की आमदनी "
                  f"{NAMES[k][1]} से ज़्यादा रहती है।")
    model_en = [NAMES[k][0] for k, c in so["crops"].items() if c["method"] == "ensemble"]
    base_en = [NAMES[k][0] for k, c in so["crops"].items() if c["method"] != "ensemble"]
    model_hi = [NAMES[k][1] for k, c in so["crops"].items() if c["method"] == "ensemble"]
    if model_en:
        en.append(f"Yield from the ensemble model (Random Forest, XGBoost, LightGBM) for "
                  f"{', '.join(model_en)}, where it beat the 5-year average in validation"
                  + (f"; {', '.join(base_en)} from the 5-year average and its past spread, "
                     "because the model did not beat it." if base_en else "."))
        hi.append(f"पैदावार: {', '.join(model_hi)} के लिए एन्सेम्बल मॉडल से; बाक़ी फ़सलों के लिए "
                  "5 साल के औसत से।")
    else:
        en.append("Yield from the 5-year average and its past spread: the ensemble model did not "
                  "beat it in validation for these crops.")
        hi.append("पैदावार 5 साल के औसत से, क्योंकि इन फ़सलों के लिए मॉडल उससे बेहतर नहीं निकला।")
    en.append("Gross income of a district-average acre, before costs, from past weather, past "
              "price changes and the model's past errors; not a forecast for your field, and not "
              "advice on what to grow (procurement, water, the previous crop and costs are not "
              "in it).")
    hi.append("यह ज़िले के औसत एक एकड़ की कुल आमदनी है, लागत घटाने से पहले, पिछले मौसम, पिछले भाव और "
              "मॉडल की पिछली ग़लतियों से; आपके खेत का अनुमान नहीं, और क्या बोएँ इसकी सलाह नहीं।")
    return en, hi
