# Crop Advisor: the final terminal version (11 November 2026)

This version does in the terminal everything the project brief says the software does. The Android
app, SMS or voice, and the device come after it. Nothing here has been checked against real fields
yet; that waits for the field partner.

## The two commands

**1. Before sowing: which crop?** (brief: "recommends which crop to plant, ranked by expected
income and risk")

```
python scripts/advise.py --outlook --district Hisar
python scripts/advise.py --outlook --district Bathinda --season kharif
```

**2. After sowing: today's advice** (brief: "when and how much to irrigate, when to apply
fertiliser, and when pest risk is rising")

```
python scripts/advise.py --district Hisar --sowing 2026-11-10
python scripts/advise.py --district Hisar --sowing 2026-11-10 --watered 2026-12-08
python scripts/advise.py --crop mustard --district Bathinda --sowing 2026-10-25
```

Useful additions:

| Add | What it does |
|---|---|
| `--watered 2026-12-08 2027-01-10` | waterings already given (not the pre-sowing one) |
| `--soil-card oc=low p=high k=low` | your Soil Health Card ratings: fertiliser doses follow them |
| `--soil-type sandy` / `light_loam` / `loam` / `clay` | your soil, for the watering date |
| `--lat 29.21 --lon 75.65` | weather and soil at your field instead of the district town |
| `--station readings.csv` | farm station readings (Kalman filter; shows the date without the station too) |
| `--lang en` or `--lang hi` | one language only |
| `--only water` / `fertiliser` / `pests` | show only those parts |
| `--today 2026-01-05` | test on a past date (at least 23 days ago) |
| `--json` | everything as JSON, for the app later |
| `--list`, `--crops` | districts and crops |

The first run of `--outlook` takes about a minute (the model is trained on the spot). Both commands
need internet, except the crop recommendation, which runs from the files in `data/reference`.

## What each part is built on

| Brief | Part | Built on | Where |
|---|---|---|---|
| 3 a-e | Live data | Open-Meteo, NASA POWER, IMD, SoilGrids, Soil Health Card, CEDA/Agmarknet, ICRISAT/DES | `notes/data_sources.md` |
| 3 | Crop recommendation | the JISEM ensemble retrained on Haryana and Punjab district yields, with the district's 5-year average where that is more accurate; 150 likely seasons; ranked by income and risk | `seasonmodel.py`, `notes/season_model.md` |
| 3 | When and how much to water | FAO-56 soil water balance with PAU / ICAR rules and the live forecast | `advisor.py`, `crops.py` |
| Objective | When to give fertiliser, and how much | PAU Package of Practices doses and timing; PAU's soil-test rule for the Soil Health Card; ICAR zone dose for wheat outside Punjab and Haryana | `fertiliser.py` |
| Objective | When pest risk is rising | the weather PAU gives as congenial for each disease, PAU's months and stages for insects, JHULSACAST (Punjab) for potato late blight | `pests.py` |
| 5 | Sensor fusion | Kalman filter on station readings and the water balance | `fusion.py`, `station.py` |
| 5 | Digital twin | FAO's AquaCrop model (AquaCrop-OSPy) over past seasons: `python scripts/run_digital_twin.py --district Hisar --crop wheat --years 2021-2023` | `twin.py` |
| 5 | Independent check | oven-dried soil samples: `python scripts/check_soil_samples.py ...` | `groundtruth.py` |

Coverage: the crop recommendation covers 9 crops in the 45 districts of Haryana and Punjab. The
daily advice covers wheat in 27 districts of 10 states, and 11 more crops in the six Punjab and
Haryana pilot districts.

Not switched on by default, because the brief's first version does not include them: Sentinel-2
crop health (`--satellite`, with `--lat/--lon`) and the small web service (`scripts/serve.py`).

## Crop recommendation: how the ranking works

For each crop of the season the model builds about 150 likely seasons (the weather of 2009-2023
with past year-on-year price changes) and works out the gross income per acre in each.

- Expected income: the mean. Poor season: the level the crop beats in 9 of 10. Good season: the
  level it beats in 1 of 10.
- Score = (expected income + poor-season income) / 2. Crops are ranked by score, so a steadier
  crop can rank above one that earns slightly more on average.
- Risk label: (good - poor) / expected, below 25 percent low, up to 50 percent medium, else high.
- "It earns more than wheat in 7 of 10": the share of the likely seasons, season by season.

The score and the label limits are our choices. Income is gross, before costs.

### Which crops use the ensemble (re-checked 11 November 2026)

Two changes were tested on the validation years (rolling 2014-2016, one year ahead; the baseline
to beat is the district's last-5-year average), then the test years were run once:

1. **A bug was fixed.** The columns that tell the model which crop a row is never reached it (the
   list was cut off by a comment on the same line), so the pooled model treated wheat and bajra
   alike.
2. **Temperature was added and then left out.** Mean daily maximum temperature for the same three
   periods as the rain, as a departure from the district's 1991-2008 mean (NASA POWER). It did not
   lower the validation error (1.505 quintal per acre with it, 1.501 without, 1.383 for the 5-year
   average), so it is not used. The data and the code stay for the next check.

| | Validation error, quintal per acre (all crops) | Crops where the ensemble beat the 5-year average |
|---|---|---|
| As shipped on 2 November | 1.512 | bajra, maize |
| Crop columns fixed (in use) | 1.501 | maize |
| Crop columns + temperature | 1.505 | maize |
| Last-5-year average | 1.383 | |

So the ensemble is used for **maize only**; bajra now misses by 0.011 (1.191 against 1.180), which
is noise either way. Every other crop uses the district's last-5-year average.

On the test years (trained 2009-2016, tested 2017-2022, one year ahead) the ensemble in use beat
the average for bajra (1.16 against 1.46), maize (2.70 against 2.89), mustard (0.86 against 0.97)
and rice (1.03 against 1.15), and lost for wheat (1.39 against 1.34), cotton (0.64 against 0.56),
barley, chickpea and groundnut. Those crops are **not** switched on that result: choosing by the
test years would leave no honest test. The rule stays "validation decides"; re-run when DES
publishes 2023-2025 yields (`python scripts/check_season_model.py`).

Why the ensemble struggles: 14 years of district averages, mostly irrigated crops whose yield
follows a slow trend, and a validation that trains on only 5 to 7 years.

## Fertiliser: what the numbers are

PAU's doses for a medium-fertility soil, per acre, and PAU's timing (`fertiliser.py` lists the page
for every crop). Examples: wheat 55 kg DAP at sowing, then 45 kg urea with each of the first two
waterings (by day 55 if rain delays the second); mustard 45 kg urea + 75 kg superphosphate at
sowing and 45 kg urea with the first watering; maize in three equal urea doses at sowing,
knee-high and before tasselling.

- **Soil Health Card.** PAU's soil-test table where it lists the crop (wheat, barley, raya,
  maize), otherwise PAU's general rule of 25 percent more on a low soil and 25 percent less on a
  high one. Organic carbon is PAU's index for nitrogen. Potash is advised only when the card says
  it is low (except potato, where PAU always gives it). PAU's second table, which also lowers
  phosphorus by the organic-carbon percentage, is not applied: the card gives ratings, not
  percentages.
- **Stage doses have estimated dates.** PAU says "knee-high", "before tasselling", "when flowers
  appear", "at thinning" without a day. The date range shown is our estimate from the crop's
  FAO-56 stage lengths and is labelled "our estimate"; the stage name is what the farmer should
  go by.
- **Wheat outside Punjab and Haryana** uses the all-India zone dose (150:60:40 kg N:P2O5:K2O per
  hectare in the north-western and north-eastern plains, 120:60:40 in the central zone; one third
  of the nitrogen at sowing, the rest at the first node stage, 40-45 days), turned into kg of
  DAP, urea and potash per acre with standard nutrient contents (urea 46% N, DAP 18% N and 46%
  P2O5, potash 60% K2O). The card is not applied there.
- Haryana uses PAU's doses, as it does PAU's irrigation rules.
- One default per crop: Bt hybrids for cotton, long-duration hybrids for maize, desi gram,
  irrigated bajra. The other doses are in the notes printed with the advice.

## Pest watch: what it does and does not do

It counts, in the last 7 days and the 7 forecast days, the days whose weather meets the condition
a university has published for that disease, and checks the crop is at a stage it can be attacked.

- **Rising**: 3 or more of the next 7 days are favourable, and more than in the last 7.
  **High**: 3 or more in both weeks. **Easing**: 3 or more last week, fewer ahead.
  Potato late blight needs only one day on which JHULSACAST's 7-day totals are met; grey mould and
  stalk rot need two. "3 of 7" is our choice.
- **Stage watches** (wheat aphid at ear stage, cotton sucking pests July-September, thrips in
  summer moong at flowering, shoot fly in spring maize seedlings, ergot in bajra at flowering,
  mustard aphid from January) come from PAU's months and stages, with no weather test.
- Where PAU uses a word without a number, the number is ours: "high humidity" is a daily mean of
  80 percent or more, "cloudy" a daily mean cloud cover of 70 percent or more, "intermittent
  rains" 2 or more rain days in 5, "around 20 deg C" within 3 degrees, "cold" a daily maximum of
  20 deg C or less. Rules that use one are marked `uses_our_threshold` in the JSON.
- Night humidity for yellow rust is the mean from 8 pm to 6 am. The wheat ear stage is taken as
  two thirds of the season onwards (about day 100 of a 152-day crop), our estimate.
- It names what to look for and tells the farmer to show it to the KVK or agriculture officer. It
  names no spray, because the brief asks for when risk is rising.
- Weather is Open-Meteo's on a grid of about 10 to 25 km, not the field's. Leaf wetness inside a
  crop differs from the air's humidity.
- **Not validated.** No outbreak records were used. The watch says when to look, and a quiet
  watch does not mean a clean field.

## What still has to be done on a PC with internet

This workspace could not reach the weather services, so these were tested with made-up weather
only (248 offline tests pass):

```
python -m pytest -q
python scripts/advise.py --district Hisar --sowing 2026-11-10
python scripts/advise.py --district Hisar --sowing 2025-11-10 --watered 2025-12-08 --today 2026-01-20
python scripts/advise.py --outlook --district Hisar
```

The second line is the first real run of the live forecast, NASA POWER rain and the hourly weather
for the pest watch.
