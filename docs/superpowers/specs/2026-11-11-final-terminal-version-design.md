# Final terminal version: design (approved by Aviral, 11 November 2026)

## Goal
One version that runs in the terminal and does everything the final project brief
(`Crop_Advisor_Project_Brief_FINAL.pdf`) says the software does, before the device is built.
Outside this version: Android app, SMS or voice, device firmware. Accuracy testing waits for the
field partner.

## Decisions (Aviral)
1. Season-start model: try to improve the paper's ensemble; use it for each crop where it beats
   the 5-year district average on unseen years, the average elsewhere.
2. Crop ranking on gross income (no cost data), by expected income and risk, over all 9 crops.
3. Sentinel-2 and the web service stay in the code but are off by default.
4. Fertiliser: timing and PAU quantity per acre, adjusted by Soil Health Card ratings.
5. Pest advice: "risk is rising" alerts, no spray names.
6. Aviral checks the Hindi wording himself.

## Parts
| Part | Module | Input | Output |
|---|---|---|---|
| Crop recommendation | `seasonmodel.py` (`summarise`, `ranking`, `text`) | district, season | crops ranked by score = (expected + poor-season income) / 2, risk label, wins of 10 |
| Fertiliser | `fertiliser.py` | crop, state, zone, sowing, today, waterings, next watering date, card | dated doses with status, next dose |
| Pest watch | `pests.py` | crop, sowing, today, hourly weather (14 days back, 7 ahead) | level per rule: rising, high, easing, stage watch |
| Daily advice | `service.advise_request` | as before, plus `parts`, `satellite` | water + fertiliser + pest text (English, Hindi) and JSON |

Each part can be tested without the network: fertiliser is pure dates and tables; the pest watch
takes a fetcher; the service takes fetchers for every source.

## Rules that bind the work
- `claude/ml-limitations.md`: time split, beat the baseline, no tuning on test years, no sensor
  claims from made-up data. The gate stays "validation decides".
- Every number shown to a farmer comes from a named source with its page, or is labelled as our
  estimate or our choice.
- A failure of one source (hourly weather, NASA POWER) never blocks the rest of the advice.

## Build order (done)
1. Season model: fix found (crop columns never reached the model), temperature tested and left
   out, gate re-run, ranking and recommendation text.
2. Fertiliser schedule with tests against PAU's printed numbers.
3. Pest rules with tests on made-up weather.
4. Join into `advise.py`; `--only`, `--satellite`.
5. Notes (`notes/final_version.md`), sources, README.
