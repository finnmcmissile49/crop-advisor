# Forecast backtest, rain-wait rule, soil type, field location, confidence, web service

29 October 2026. What changed in the calculator, why, and what was checked. Code:
`scripts/backtest_forecast.py`, `src/cropadvisor/rainrule.py`, `sites.py`, `service.py`,
`scripts/serve.py`. Results: `data/checks/`.

## 1. How far can the forecast be trusted? (backtest)

Until now, "test mode" used the weather that was later recorded as if it were the forecast (a
perfect forecast). This backtest uses the forecasts **as they were really issued**: Open-Meteo's
Previous Runs API keeps the rain forecast made 1 to 7 days before each day. Six Punjab and Haryana
districts, 1 January 2024 to 22 October 2026, compared with Open-Meteo's recorded rain. Hindsight
is Open-Meteo's record, not a field rain gauge. Only rain forecasts are archived, so ET0 is taken
as known; that flatters the forecast a little.

**Rain forecast skill (a rain day = at least 2.5 mm, IMD's definition)**

| Days ahead | Rain days caught | False alarms | Forecast / recorded rain |
|---|---|---|---|
| 1 | 71% | 39% | 1.19 |
| 2 | 69% | 42% | 1.26 |
| 3 | 69% | 43% | 1.23 |
| 4 | 67% | 46% | 1.21 |
| 5 | 66% | 48% | 1.23 |
| 6 | 64% | 49% | 1.20 |

Lead 7 is incomplete in the archive and is not used.

**"At least 20 mm in the next 3 days" — did at least 10 mm fall?**

| Season | Cases | Came true |
|---|---|---|
| Rabi (Nov-Mar) | 39 | 79% |
| April-May | 25 | **20%** |
| Kharif (Jun-Oct) | 607 | 72% |

April-May forecasts of heavy rain mostly did not come true (pre-monsoon storms are hard to
forecast).

**The advice date itself.** On every day of every season (12 crop settings, 186 district-seasons),
the day the soil would reach the watering point was predicted with the forecast available that
morning and compared with the day it really did.

| Watering really due in | Cases | Predicted within 1 day | Predicted more than 6 days away |
|---|---|---|---|
| 2 days | 595 | 97% | 1% |
| 3 days | 602 | 96% | 2% |
| 4 days | 594 | 93% | 5% |
| 5 days | 552 | 91% | 8% |
| 6 days | 511 | 79% | 19% |

So the near-term date is robust to forecast errors. Beyond 6 days it could not be tested (the
archive stops at 7 days ahead), and the calculator's dates further out should be treated as
rough. This is the basis of the new confidence line (section 5). **The forecast is not the
weakest input; the soil and the rain record are** (wheat stress tests: soil plus or minus 20
percent moves most dates).

## 2. Waiting for forecast rain (fix for the 26 October finding)

The calculator used to say "water today" even with 30 mm of rain forecast for two days later. Now,
when a watering is due within 3 days, it **waits** if all of these hold:

- at least 20 mm of rain is forecast over those 3 days;
- it is not April or May;
- the soil would not get too dry before the rain arrives: depletion stays within a quarter of the
  way from the watering point to wilting point (water stress coefficient Ks at least 0.75; our
  choice).

The advice then says: "WAIT FOR THE RAIN: about 30 mm is forecast by 10 Jan. Do not water before
then. If less than 1 cm falls by 10 Jan, water on 11 Jan." The first watering at a fixed crop stage
(for example wheat crown root) never waits.

**Replay through real seasons with the forecasts as issued** (186 district-seasons, all 12 crop
settings, 2024-2026): the rule waited **7 times**; the rain came 4 times and failed 3 times (each
time the field was watered the day after); total waterings 613 to 611; severe water-stress days
did not increase. **The case is rare in these districts and seasons, so the rule's real effect is
small.** It still removes the most obviously wrong advice, and its thresholds are measured rather
than guessed. 7 cases are too few to tune it further; revisit after a season of live use.

## 3. The farmer's soil type

`--soil-type sandy | light_loam | loam | clay` (web service: `soil_type`). Instead of the
arbitrary plus or minus 20 percent, the earliest and latest dates now cover the water-holding range
FAO-56 Table 19 gives for that soil (loamy sand 60-120, sandy loam 110-150, loam 130-180, clay
120-200 mm per metre). The likely date uses the soil map's value if it falls inside that range,
else the middle of the range.

**Watch this:** the soil map (SoilGrids with Saxton-Rawls) gives lower water-holding than FAO-56's
typical ranges. Hisar is mapped as loam at 122 mm per m, below FAO's loam range (130-180). So a
Hisar farmer who says "loam" gets advice based on 155 mm per m: later waterings. Which is closer
to real fields is unknown until soil is measured; it is the strongest reason for the soil
moisture sensor.

## 4. The field's own location

`--lat` and `--lon` (web service: `lat`, `lon`): weather at the field's point and soil from
SoilGrids at the field (nearest point with soil data within 10 km; cached). If SoilGrids cannot
be reached, the district's soil is used and the advice says so. A point more than 60 km from the
district centre, or outside India, is refused. Weather is still on a grid of about 25 km, so the
gain is mostly in the soil.

## 5. Confidence line

Every advice now ends with "Confidence: high / medium / low (reasons)". It starts at high and
drops for:
- a date 4-6 days away (one step) or more than 6 days away (two steps), from the backtest above;
- waiting for forecast rain, or advice that depends on the long-range forecast;
- soil from the district map only (no field point, no soil type from the farmer);
- a lower-confidence crop (kharif maize);
- late sowing.

It describes how stable the date is, not whether the water balance matches a real field (not
checked anywhere yet).

## 6. Web service and JSON

`python scripts/serve.py` starts a small web service (standard library only):
`/advice` (GET with query parameters or POST JSON), `/crops`, `/districts`, `/soil-types`,
`/health`. The answer has the advice as JSON (status, dates, soil numbers, confidence) plus the
English and Hindi text. `python scripts/advise.py ... --json` prints the same. The calculator
script and the service share one code path (`service.advise_request`). For local testing and a
pilot only: no login, rate limit or HTTPS.

## 7. Other changes

- **Wheat late sowing:** accepted up to 10 days after the zone's timely window (North Western
  Plains 25 November, so up to 5 December) with a warning; later sowing is refused, because the
  settings are for timely-sown varieties.
- **Soil for all 27 districts** is now in the repo (`data/soil_awc.csv`), so wheat advice works
  from a fresh copy everywhere.
- **Package versions** have ranges, and the tests run automatically on GitHub (Python 3.11 and
  3.13) on every push.
- **Kc ini from wetting frequency (FAO-56 Figs 29-30, Annex 7)** is available as an option
  (`kc_ini_wetting`) but **off**: it was tested as a possible fix for kharif maize, and it moved
  kharif maize only from 1.3 to 1.6 waterings (PAU: 4-6) while cutting groundnut from 2.4 to 1.5.
  It does not explain the gap. The remaining suspect is Open-Meteo's monsoon rain, which needs an
  IMD comparison.

## Not done here (needs Digital Green)

Agronomist and Hindi review, farmer logging and reminders, farmer-friendly inputs (tubewell
hours, canal turns) and Punjabi.
