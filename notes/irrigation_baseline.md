# Irrigation baseline for rabi wheat: first results

22 October 2026. Branch `irrigation-baseline`. Public data only. This is a reference rule, not a
verified answer: nobody recorded the correct irrigation dates for these districts, so accuracy
cannot be measured. Nothing here says anything about the benefit of a sensor station.

## What was built

- `src/cropadvisor/irrigation.py`: the FAO-56 daily root-zone water balance for wheat, and two
  advice rules that run on it.
  - **FAO trigger:** irrigate when the soil has lost its "readily available" water (depletion
    reaches RAW), refilling to field capacity.
  - **PAU calendar:** Punjab Agricultural University's wheat schedule: first irrigation 4 weeks
    after sowing, then 5-6, 5-6 and 4 weeks (for sowing up to 21 November), 7.5 cm each, with
    PAU's rain rule (each cm of rain moves the next irrigation 5 days later up to January, 2 days
    after). No irrigation after 31 March for crops sown before 5 December (PAU).
- `src/cropadvisor/irrigation_eval.py`: compares irrigation dates between two runs and runs the
  stress tests. This comparison is the same one the sensor study will use later.
- `scripts/run_irrigation_baseline.py`: one command, writes four CSVs.
- `tests/test_irrigation.py`: 16 offline tests on made-up weather.

## Inputs

| Input | Value used | Source | Strength |
|---|---|---|---|
| Rain | IMD gridded (reference); Open-Meteo and NASA POWER compared | pipeline pull, 2021-2023 | IMD is gauge-based but still a grid estimate |
| ET0 | Open-Meteo (NASA POWER compared) | pipeline pull | solid (matches our FAO-56 calculation) |
| Soil water capacity | 120 to 146 mm per m by district | SoilGrids + Saxton-Rawls | model estimate, points 3 km from towns |
| Crop coefficient Kc | 0.3, 1.15, 0.25 | FAO-56 Table 12 | standard table, not local |
| Stage lengths | FAO-56 Central India 15/25/50/30 days, stretched to 152 days | FAO-56 Table 11, PAU maturity 145-158 days | stretching is our assumption |
| Root depth | 0.2 m at sowing, linear to 1.0 m at mid-season | FAO-56 Table 22 (1.0-1.5 m); growth rule is ours | assumption |
| Depletion fraction p | 0.55, adjusted for daily ETc | FAO-56 Table 22 | standard |
| Sowing | 10 November | inside PAU's optimum first fortnight | agreed default |
| Start of season | soil full (PAU heavy pre-sowing irrigation) | PAU | assumption |

12 district-seasons: Sirsa, Hisar, Kurukshetra, Bathinda, Sangrur, Tarn Taran; 2021-22 and 2022-23.

## Checks

- FAO-56 Example 37 reproduced (water-stress factor 0.97 on day 3 and 0.62 on day 10).
- A hand-worked 8-day example matches exactly.
- Water is conserved: the largest balance error over all real runs is about 1e-13 mm.
- PAU dates match the table by hand for 25 November, October and January sowing.

## Results

### 1. The baseline gives a plausible amount of irrigation

FAO trigger, IMD rain: 1 to 4 irrigations per season (mean 3.0), mean 238 mm, crop water use
(ETc) 313 to 407 mm. PAU's table recommends 4 irrigations of 7.5 cm after a 10 cm pre-sowing
irrigation. Same order of magnitude. This shows the baseline is not absurd, not that it is right.

### 2. The water balance and PAU's calendar disagree on the first irrigation

| Rule (IMD rain) | Mean irrigations | First irrigation, days after sowing | Events more than 3 days apart from the other rule |
|---|---|---|---|
| FAO trigger | 3.0 | 58 to 120 (mean about 81) | about 90 percent |
| PAU calendar | 2.7 | always 28 | |

The water balance sees no water shortage until January or later: early wheat uses little water,
roots grow into soil that the pre-sowing irrigation filled, and November-December demand is low.
PAU irrigates at 4 weeks regardless. Generally in agronomy this early irrigation is tied to a
growth stage (crown root initiation), not to soil water; this is general knowledge, not checked
in the PAU document. A water balance alone cannot see a growth-stage need. **Farmer advice built
only on the water balance would tell farmers to skip PAU's first irrigation. Do not ship that
without an agronomist's view.**

### 3. Rain source moves the dates more than the count

FAO trigger, compared with the same rule on IMD rain (tolerance 3 days, PAU's own "2 or 3 days
either way"):

| Rain source | Change in irrigation count (mean) | Irrigation events that differ |
|---|---|---|
| Open-Meteo vs IMD | -0.17 | 53 percent |
| NASA POWER vs IMD | -0.17 | 44 percent |

Open-Meteo read about 65 percent more rabi rain than IMD in these seasons, but it changes the
number of irrigations in only 2 of 12 seasons. It changes about half of the dates by more than 3
days. Open-Meteo is the source a live calculator would use.

### 4. The guessed soil and crop numbers matter more than the rain source

FAO trigger, one change at a time, mean irrigations (default 3.0):

| Change | Mean irrigations | Seasons where the count changed |
|---|---|---|
| Soil water capacity -20 percent (arbitrary) | 4.1 | 11 of 12 |
| Soil water capacity +20 percent (arbitrary) | 2.5 | 6 of 12 |
| Roots to 1.5 m (FAO-56 upper value) | 1.9 | 11 of 12 |
| Unstretched 120-day FAO season | 1.8 | 12 of 12 |
| Kc at start 0.7 (FAO-56 winter wheat) | 3.8 | 10 of 12 |
| Kc mid 1.05 / 1.25 (arbitrary) | 2.75 / 3.4 | 3 / 5 of 12 |
| Sowing 1 / 25 November | 2.9 / 3.25 | 1 / 3 of 12 |
| Open-Meteo / NASA POWER rain | 2.8 / 2.8 | 2 / 2 of 12 |
| NASA POWER ET0 | 3.25 | 3 of 12 |

Ranges marked arbitrary are stress tests, not uncertainty estimates. Even a 20 percent change in
soil capacity moves most irrigation dates by more than 3 days.

**What this suggests for the station (a hypothesis, not evidence):** soil capacity, root depth and
Kc all act through one number the model guesses, the root-zone depletion. A soil moisture sensor
measures that more directly. A rain gauge only fixes the rain input, which moved the count least.
This points to soil moisture as the station's priority measurement. It has to be tested with real
station data.

### 5. PAU calendar, as encoded, under-irrigates in March

Under the water balance, the PAU calendar gives about 35 stress days per season, mostly in March
(about 19 days), during grain filling. In wet seasons the rain rule pushes the later irrigations past
31 March, so they are dropped (Tarn Taran 2021-22: one irrigation, 179 mm IMD rain). PAU also says to
irrigate until the end of March "if needed, depending on rainfall"; the encoding does not include
that clause. This is a limit of the encoding, not a finding about PAU's advice.

## Open decisions

1. Hybrid rule: keep PAU's first irrigation at about 4 weeks as a fixed stage irrigation, then let
   the water balance time the rest? Recommended, but needs an agronomist's view.
2. How to encode PAU's "irrigate till end of March if needed".
3. Haryana's own university guidance is not checked yet; three of six districts are in Haryana.

## Run it

```
python scripts/run_irrigation_baseline.py --processed data_north_india/processed --years 2021 2022
```
