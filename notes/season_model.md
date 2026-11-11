# Season-start model (2 November 2026)

For each crop of the coming season in a Haryana or Punjab district: expected yield and gross income
per acre, how much they vary, and how often one crop beats another ("wheat beats mustard in 8 of
10 likely seasons").

```
python scripts/advise.py --outlook --district Bathinda               # next season to be sown
python scripts/advise.py --outlook --district Sirsa --season kharif
python scripts/check_season_model.py                                 # validation and test
```

Web: `/outlook?district=Bathinda&season=rabi` returns `season_model`. It takes about a minute the
first time (the models are trained on the spot from the committed tables).

## Crops

| Season | Crops | Yields from |
|---|---|---|
| Rabi (winter) | wheat, mustard, barley, chickpea | ICRISAT 2000-2019, DES 2020-2022 (wheat: the North India table) |
| Kharif (summer) | paddy, cotton, maize, bajra, groundnut | the same (paddy and cotton: the North India table) |

A crop is shown for a district only if it had at least 1,000 ha there in at least 3 of the last 5
years with data. Smaller areas give rounded, noisy yields. ICRISAT and DES agree within 10 percent
for 80 to 90 percent of the district-years where both report (`data/checks/yield_sources_agreement.csv`).
Moong and potato have DES yields only from 2015, too short for the model, so they are not in it.

## Model

The regression ensemble from the JISEM paper: the average of a Random Forest, XGBoost and
LightGBM, retrained on Haryana and Punjab district data (2,200 district-crop-years from 2009 to
2022). It predicts the season's yield as a ratio to the district's average of its last 5 years.

Features: that 5-year average, last year's ratio, the 10-year trend, and IMD rainfall for the
crop's own season. For rabi crops that is October-March; for kharif crops it is June-September.
Rainfall enters as the season total against IMD's normal, plus three sub-periods. The state is
also a feature. Year is not, because tree models cannot carry a year beyond the years they were
trained on. The Random Forest leans most on the 5-year average, last year's ratio and the trend.
The four rain features together carry about 0.38 of the importance (`season_model_features.csv`).

Settings are small and regularised, fixed in advance, not tuned on test years. The paper's random
5-fold cross-validation is not used, because it mixes a year's weather into both training and
testing.

## Validation, gate and test

1. **Validation** (rolling origin, 2014-2016, one year ahead). Each year is predicted by a model
   trained on all earlier years. The ensemble beat the last-5-year average only for **bajra
   (1.17 vs 1.18 quintal per acre) and maize (3.37 vs 3.43)**. So those two crops use the ensemble.
   The other seven use the 5-year average, with the spread of its own past errors. Validation four
   years ahead was not used to decide: it has only 3-4 training years.
2. **Test**, once (trained 2009-2016, scored 2017-2022). Mean absolute error in quintal per acre;
   rice is milled rice and cotton is lint.

   | Crop | Districts | Ensemble, 1 yr | 5-yr avg, 1 yr | Ensemble, 4 yrs | 5-yr avg, 4 yrs | Mean, 4 yrs | Trend, 4 yrs |
   |---|---|---|---|---|---|---|---|
   | Wheat | 38 | 1.33 | 1.34 | 1.37 | 1.29 | 1.93 | 1.48 |
   | Mustard | 32 | 0.87 | 0.97 | 1.01 | 1.28 | 1.71 | 1.07 |
   | Barley | 9 | 1.45 | 1.40 | 1.51 | 1.45 | 1.90 | 1.80 |
   | Chickpea | 6 | 0.92 | 0.88 | 1.09 | 1.21 | 1.49 | 1.32 |
   | Rice | 37 | 1.05 | 1.15 | 1.18 | 1.46 | 1.92 | 1.35 |
   | Cotton | 19 | 0.65 | 0.56 | 0.78 | 0.64 | 0.61 | 0.92 |
   | Maize | 13 | 2.62 | 2.89 | 2.73 | 2.86 | 3.33 | 3.72 |
   | Bajra | 15 | 1.18 | 1.46 | 1.29 | 1.75 | 2.21 | 1.70 |
   | Groundnut | 3 | 0.91 | 0.44 | 1.30 | 0.73 | 1.70 | 1.13 |

   The two gated crops, bajra and maize, also beat the 5-year average on the test, at both
   distances. Mustard, rice and chickpea beat it on the test too, but they failed validation, so
   they stay on the 5-year average. Switching them on the test result would be tuning on the test
   years; more years of data (DES 2023-2025 when published) can change the gate. The ensemble did
   worse than the 5-year average for wheat four years ahead, and for cotton and groundnut.
   **The model does not beat simple averages for most crops with this much data. That is a
   finding, not a bug.**

## Likely seasons and income

The coming season is replayed as each past season. The IMD rain of each year 2009-2023 goes
through the model, and the model's own out-of-sample error for that district and year is added
back. For the 5-year-average crops, it is that year's actual ratio. Either way, a scenario carries
that year's weather and everything else that happened that year (pests, heat, prices of inputs).

Price: the last harvest price (as in the outlook) times one of the past year-on-year changes in
the state's harvest price (2016-2025). Every crop in a scenario gets the same year's change.
Every rain year is paired with every price year, which gives about 150 likely seasons.

Income is the yield in the market's unit times the price:

- rice is converted to paddy at the official 67 percent out-turn;
- cotton lint is converted to kapas at a ginning outturn of 31, 34 or 37 percent, cycled across
  scenarios (north zone 33-35 percent, CAI 2021; Bt hybrid trials 30.8-36.9 percent, AICRP 2008-09).

The output shows the mean, the 10th-90th percentile, and for each pair of crops the share of
scenarios in which one earns more, rounded to "N of 10".

## Limits

- **Gross income of a district-average acre, before costs.** Costs differ a lot between crops
  (paddy and cotton cost more to grow than bajra), so "beats" in gross income is not "pays more".
  Adding cost of cultivation (CACP state data) is the obvious next step.
- **A recommendation on gross income only (from 11 November 2026 the output ranks the crops and
  names one).** Assured procurement at the minimum support price (wheat, paddy), water, the
  previous crop, machinery and labour are not in it. An agronomist and the field partner should
  review it before farmers see it (ml-limitations section 6).
- **Weather is rain only.** Temperature was tested on 11 November 2026 and did not lower the
  validation error, so a heat wave like March 2022 still enters only through the model's error for
  that year.
- Past price changes include years of MSP increases, so future prices are assumed to move as they
  did in 2016-2025.
- Districts are small samples: chickpea 6 test districts, groundnut 3. Results for those are weak.
- Kharif 2020 rain is a scaled-up estimate (IMD has 16 of 31 July days).
- Yields end in 2022, so a 2026 rabi season is 4 years ahead of the data and a 2027 kharif season
  is 5 years ahead.

## Update, 11 November 2026

See `notes/final_version.md`, "Which crops use the ensemble": the crop columns now reach the model
(they were cut off by a comment), temperature was tested and left out, the ensemble is used for
maize only, and the output is a ranked crop recommendation (score = average of expected and
poor-season income). The numbers earlier in this note are those of 2 November.
