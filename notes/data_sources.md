# How the calculator uses each data source (1 November 2026)

Every source the project collects now feeds the calculator. Only some of them can change the
watering date, because a date needs today's weather and the soil. The others are shown beside the
advice as district background, or in the season-start outlook.

| Source | Where it goes | Changes the watering date? |
|---|---|---|
| Open-Meteo | ET0 for every day; the 16-day forecast; recorded rain for the days NASA POWER does not have yet | yes |
| NASA POWER | recorded rain from sowing up to its latest day (a lag of a few days) | yes |
| SoilGrids / farmer's soil type | water-holding capacity | yes |
| IMD gridded and district rainfall | (1) the yardstick that chose NASA POWER for recorded rain; (2) IMD normals: rain so far against normal, and next month's normal | no (it arrives months late) |
| Soil Health Card | district fertility note, only where enough soils were tested | no |
| ICRISAT and DES district yields | training data for the season-start model (9 crops); district yield line under the advice | no |
| CEDA / Agmarknet mandi prices | prices and price changes in the season-start model; last harvest price in the outlook and under the advice | no |
| IMD district rainfall (again) | weather features and the "likely seasons" of the season-start model | no |

Run it:

```
python scripts/advise.py --district Hisar --sowing 2026-11-10 --watered 2026-12-08
python scripts/advise.py --outlook --district Hisar
python scripts/advise.py --district Hisar --sowing 2026-11-10 --rain-source openmeteo
python scripts/advise.py --district Hisar --sowing 2026-11-10 --no-extras
```

The web service has the same: `/advice` answers carry `extras`, and `/outlook?district=Hisar`.

## 1. Recorded rain: NASA POWER first, Open-Meteo for the latest days

**Check** (`scripts/check_weather_sources.py`, results in `data/checks/rain_source_vs_imd*.csv`).
27 districts, wheat sown on each zone's default date in November 2021 and November 2022 (54
district-seasons). The advice rule (first watering at crown root initiation, then the FAO-56
trigger) was run with the same soil and ET0 four times, changing only the rain. Each run's watering
dates were compared with the run on IMD rain (3-day tolerance).

| Rain used | Waterings that differ from the IMD run | Seasons with a different number of waterings |
|---|---|---|
| Open-Meteo | 30 percent | 20 percent |
| Open-Meteo scaled by the IMD ratio from the other season | 26 percent | 15 percent |
| NASA POWER | 17 percent | 9 percent |

NASA POWER was closer to the IMD run than Open-Meteo in 19 district-seasons, the same in 30 and
further in 5. Across November-April, Open-Meteo's rain was a median of about 1.6 times IMD's, NASA
POWER's about 1.3 times. So the calculator uses NASA POWER for rain already fallen.

**Limits.** IMD is the reference here because it is built from rain gauges, but it is itself a
grid estimate, so "closer to IMD" is not "correct for the field". Two seasons per district is a
small sample. NASA POWER's delay in live use has not been measured: the calculator uses whatever
days POWER returns and fills the rest from Open-Meteo, so the first live runs on your PC should
show how many days behind POWER is. NASA POWER's own ET0 (from its coarser grid) differed from
Open-Meteo's by an RMSE of 0.88 mm a day, and neither has been checked against a station, so ET0
stays Open-Meteo's (which matches our own FAO-56 calculation, RMSE 0.19). Scaling Open-Meteo by the
IMD ratio was tested and not adopted: a small and inconsistent gain (closer in 10, further in 7).

**What the farmer sees.** One line with the recorded rain and which source gave it. If rerunning
the advice with Open-Meteo's rain record moves the date by more than a day, a second line gives
that date and the confidence drops one level. In the 364 past-season runs of the sweep below, this
happened in 36 (10 percent). If NASA POWER cannot be reached, the advice says so and uses
Open-Meteo alone.

## 2. IMD rainfall: normals

`data/reference/imd_rain_monthly.csv`: for the 27 districts, IMD's district normal per month and
the 2009-2024 average of IMD's district rainfall (months with at least 90 percent of days
reported). The advice shows the rain since sowing against IMD's normal for the same days, and the
normal for the month after the forecast ends. The rain since sowing comes from NASA POWER and
Open-Meteo, which read above IMD here (section 1), so a season can look wetter than normal partly
because of the source.

## 3. Soil Health Card

`data/reference/soil_health_card.csv`: cycles 2023-24 to 2026-27, the share of tested samples
rated low (or deficient) in nitrogen, phosphorus, potassium, organic carbon, zinc and sulphur,
with the number tested, for the 27 calculator districts and the 45 Haryana and Punjab districts.
Rules (`src/cropadvisor/soilcard.py`):

- a cycle counts for a nutrient only if at least 500 samples were tested for it;
- if the counted cycles differ by more than 30 percentage points, no figure is given, only that
  the results vary (Bathinda potassium: 96, 40 and 8 percent);
- the note always says these are district figures and to get the field tested.

It is never an input to the water balance or to a model (the limitations file says the card is
not model-grade here). Hisar and Ganganagar, for example, have too few nitrogen tests for a
figure. No fertiliser dose is given: the farmer is sent to their own test and agriculture office.

## 4. Season outlook: district yields and mandi prices

(Since 2 November `--outlook` leads with the season-start model, `notes/season_model.md`: the
JISEM ensemble retrained on 9 crops, expected income per acre, its spread, and how often one crop
beats another. The outlook below it then shows only the last harvest prices. The simple yield
outlook described here is still what appears under the irrigation advice.)

`python scripts/advise.py --outlook --district Bathinda`. Haryana and Punjab only. For each crop:

- **Yield**: the average of the district's last 5 years with data (ICRISAT 2009-2019, DES
  2020-2022), only years before the season. Chosen on 2015-2018 against the district's long-run
  mean and a linear trend, then tested once on 2019-2022 (`scripts/check_outlook.py`,
  `data/checks/yield_outlook_check.csv`):

  | Crop | Districts | Test error, quintal per acre (mean absolute) | Long-run mean | Trend |
  |---|---|---|---|---|
  | Wheat | 43 | 1.12 | 1.10 | 1.69 |
  | Rice (milled) | 42 | 1.36 | 1.59 | 1.10 |
  | Cotton (lint) | 22 | 0.60 | 0.67 | 0.80 |

  The 5-year average was best or within 0.02 of best on the validation years for all three crops,
  so it was kept for all three. On the test years the trend did better for rice (rice yields kept
  rising; the 5-year average was 0.75 quintal per acre low on average), so the rice figure is
  probably a little low. The range shown is the 10th to 90th percentile of past errors at the same
  distance ahead of the data (the data end in 2022, so a 2026 season is 4 years ahead;
  `data/checks/yield_outlook_by_horizon.csv`).
- **Price**: the mean monthly modal mandi price in the crop's harvest months (from its PAU season
  in `crops.py`; wheat April-May, paddy October-November), for the last three harvests. District
  prices are used unless a season is more than 25 percent from the state price that season (then
  that season is dropped; Sangrur cotton showed Rs 2,500 in 2022), and the district must have the
  latest season, else the state price is used. No price is shown if the latest harvest with a
  price is more than two years old. Wheat and Punjab paddy prices match the minimum support price
  (for example wheat Rs 2,125, 2,275 and 2,425 for 2023 to 2025). Haryana's district paddy prices
  are well above it in some years (Hisar Rs 3,333 in 2023), possibly basmati sold under "common"
  paddy (not confirmed).
- **Gross value per acre**: expected yield times the last harvest price, with a range from the
  yield range and the price range. Before costs, not profit. Rice yields are milled rice, turned
  into paddy at the official 67 percent out-turn. None for cotton: the yield is lint, the price is
  for kapas, and the lint share of kapas varies too much (22 to 44 percent) to convert.

This is district information, not a recommendation of what to grow (procurement, water, the
previous crop and costs are not in it). Under the irrigation advice, the same yield and price
lines appear for that crop.

## 5. Checks run

- 188 offline tests (20 new, `tests/test_data_sources.py`): POWER rain replaces only recorded days,
  lag days fall back to Open-Meteo, POWER failure is reported, the Open-Meteo date appears only
  when the records disagree, the service keeps POWER off with made-up weather, IMD normals pro
  rata, Soil Health Card rules, outlook yield, price outlier and staleness rules, paddy conversion,
  no cotton value, the web `/outlook` endpoint, and that the committed tables cover every district.
- Past-season sweep with the real 2021-2023 weather from the 10-state pull (Open-Meteo and NASA
  POWER fed in as if live): 27 districts x 2 wheat seasons x 7 dates (364 runs) and 11 crops in 4
  Punjab and Haryana districts (88 runs). No failures other than dates after harvest, which are
  correctly refused.
- Not checked: the live NASA POWER download on a real date (this workspace cannot reach it; run
  the calculator once on your PC), and anything against real fields.

## Rebuilding the tables

```
python scripts/build_reference_tables.py --agri-dir "C:/Users/Aviral/OneDrive/Desktop/agri-project"
python scripts/check_weather_sources.py --daily data_10states/processed/daily_weather.csv
python scripts/check_outlook.py
```
