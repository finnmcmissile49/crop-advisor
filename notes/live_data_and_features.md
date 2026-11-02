# Live data inputs and technical features

What each input and feature does in the calculator, how "live" it really is, and what has and has
not been tested. Written 2 November 2026.

## Live data inputs

| Input | Used for | How live | Tested |
|---|---|---|---|
| Open-Meteo | ET0, 16-day forecast, recorded rain where nothing better | live, every run | live (earlier rounds) |
| NASA POWER | recorded rain (ahead of Open-Meteo) | live, a few days' lag | live (earlier rounds) |
| IMD gridded rain | recorded rain, ahead of NASA POWER, on any day IMD has published | IMD publishes a year's file months late, so in a live season it is usually absent; past seasons use it fully | offline with a fake; first live run still to do on the PC |
| SoilGrids | water-holding, field capacity (district or field point) | live per field point, cached | live (earlier rounds) |
| Soil Health Card, district | background: share of fields rated low | the dashboard updates once a cycle; `scripts/refresh_soil_health_card.py` rebuilds the table from a new download (checked: same 2,758 district-cycles as the current file) | offline |
| Soil Health Card, farmer's own | the ratings from the farmer's card, shown with the district share | entered per request (`--soil-card n=low zn=deficient`) | offline |
| CEDA / Agmarknet prices | monthly history: price spread, expected income | CEDA's monthly file, refreshed by `build_reference_tables.py` | yes |
| data.gov.in Agmarknet daily | "price now" line in the outlook | live, needs a free key in `DATA_GOV_IN_KEY` | offline with a fake; the server has refused some networks before |
| ICRISAT / DES yields | season model, usual yield | yearly releases, refreshed by `build_reference_tables.py` | yes |
| Sentinel-2 (crop greenness) | NDVI at the field: latest clear value and the change | live, one scene about every 5 days, often cloudy in kharif; only when the field's lat/lon are given | offline with fake scenes; first live run still to do |

Sentinel-2: Level-2A from the Microsoft Planetary Computer (free, no account). A 3 x 3 window of
10 m pixels (30 m square) around the point; a scene counts only if the scene classification says
vegetation or bare soil at the centre and at 6 of 9 pixels. Reflectance uses the -1000 offset from
processing baseline 04.00 (read per scene, so reprocessed old scenes are handled). NDVI is shown as
background; it does not change the watering date and is not calibrated against any field.

## Technical features

### Sensor fusion (Kalman filter), `fusion.py`

- State: root-zone depletion (mm). The predict step is the calculator's own FAO-56 water balance.
- Measurement: station soil moisture, two depths combined into a root-zone value.
- Station rain replaces public rain on days the gauge recorded it.
- Readings are checked first (`station.py`): out of range, stuck for 48 h or more, impossible rain.
- A reading more than 3 standard deviations from the prediction is rejected (logged, not used).
- If the sensor fails, the filter carries on with the water balance and its uncertainty grows.
- The result is applied as one water correction on the last day, so the rest of the calculator
  (forecast, rain-wait rule, confidence) is unchanged. The advice also says what the date would
  have been without the station.

The uncertainty settings (0.2 of ET, 0.2 of rain, 0.25 of irrigation, 0.03 m3/m3 per sensor) are
assumptions, not measured. Tests use made-up readings. They check the code, and they are no
evidence that the station improves advice. That needs real readings checked against oven-dried
samples.

### Digital twin (AquaCrop), `twin.py`, `scripts/run_digital_twin.py`

AquaCrop-OSPy (an open-source Python version of FAO's AquaCrop model, not FAO's official release)
plays past seasons (2021-2023 committed; any year with `--live`) under four strategies:
- the calculator's advice;
- the guidance calendar (wheat);
- no irrigation;
- frequent irrigation (below 70 percent available water).

The results are shown as a share of the best yield, alongside the water each strategy used.

AquaCrop's built-in crop settings are not calibrated for Indian varieties, so compare strategies
with each other only. The yields themselves are not predictions. Hisar wheat, 2022: the advice
reached the best yield with 350 mm, the calendar with 420 mm. This is a model result, not a field
result.

### Independent check with oven-dried samples, `groundtruth.py`, `scripts/check_soil_samples.py`

The farmer or field team weighs each soil sample wet, dries it in an oven (105 C, 24 h) and weighs
it again (template: `data/templates/soil_samples.csv`).
- Gravimetric water = water / dry soil.
- Volumetric water = gravimetric water x bulk density (from the sample if measured, else the
  district's SoilGrids value, and the output says which).

The script reports bias and RMSE against the samples for:
- each sensor;
- the public-data model;
- the fused estimate.

This is the check that can show whether the station helps. No real samples exist yet.

## Still not done

- First live runs on the PC: IMD point rain, data.gov.in price with a key, Sentinel-2.
- No real station readings or soil samples yet, so there is no result for the research question.
- Fertiliser and pest advice is not in the software. The Soil Health Card lines only tell the
  farmer to ask the agriculture office for the dose.
