# Irrigation baseline for rabi wheat: 10 states

24 October 2026. Branch `irrigation-baseline`. Public data only. 27 districts, 2021-22 and
2022-23 seasons, 54 district-seasons.

**What this is and is not.** For each state the calculator now uses that state's ICAR wheat zone
(sowing date, season length, irrigation stages) and real weather and soil data. Every result
below has been checked for correct arithmetic and for plausibility against official guidance. **It
has not been checked against real fields anywhere, so it has no accuracy figure.** No public
dataset of measured soil moisture and irrigation dates exists for wheat in these states (search on
24 October; see claude/ml-limitations.md).

## Settings

| Zone (ICAR) | States / parts in this run | Default sowing | Season | Calendar rule |
|---|---|---|---|---|
| North Western Plains (NWPZ) | Punjab, Haryana, west UP, north Rajasthan, Uttarakhand plains, Jammu and Kathua | 10 Nov (window 1-25 Nov) | 152 days | Punjab: PAU; others: ICAR-IIWBR |
| North Eastern Plains (NEPZ) | east UP, Bihar, West Bengal | 15 Nov (window 10-20 Nov) | 120 days | ICAR-IIWBR |
| Central Zone (CZ) | Madhya Pradesh, Gujarat, Jhansi (UP), Bundi (Rajasthan) | 15 Nov (window 10-20 Nov) | 118 days | ICAR-IIWBR |

Sources: ICAR-DWR "Wheat Cultivation in India: Pocket Guide" (2014) for zones, sowing windows and
irrigation stages (21, 45, 65, 85, 105, 120 days after sowing; 4-6 irrigations, 28-42 cm in total);
variety maturity days from the 2023 pre-rabi interface list (NWPZ 146-156, CZ 116-119) and ICAR on
DBW 187 (NEPZ, 120 days); PAU Package of Practices for Punjab. No irrigation in the last 10 days
before maturity outside Punjab (our assumption). Crop coefficients, root depth and depletion
fraction as in irrigation_baseline.md.

Districts: the largest wheat districts per state and zone in DES 2019-2022 data. Coordinates:
centroids of DataMeet Census 2011 district boundaries (Kathua: the town, as the centroid is in the
hills); the six pilot districts keep their town points. Elevation from Open-Meteo where not given.

## Results by state

FAO trigger rule, IMD rain, default sowing. "Rain" is sowing-to-harvest IMD rain.
"Open-Meteo / IMD" is rabi (Nov-Mar) rain from Open-Meteo divided by IMD's, all district-seasons.

| State | Zone | Districts | Rain (mm) | Crop water use (mm) | Irrigations, mean (range) | Irrigation (mm) | First irrigation (days after sowing) | Calendar rule irrigations | Open-Meteo / IMD rain |
|---|---|---|---|---|---|---|---|---|---|
| Punjab | NWPZ | 3 | 92 | 360 | 2.7 (1-4) | 217 | 88 | 2.3 (PAU) | 1.56 |
| Haryana | NWPZ | 3 | 78 | 392 | 2.8 (1-4) | 219 | 75 | 6.0 | 1.38 |
| Uttar Pradesh | NWPZ/NEPZ/CZ | 5 | 39 | 334 | 2.5 (1-4) | 200 | 61 | 5.4 | 2.34 |
| Madhya Pradesh | CZ | 3 | 31 | 350 | 3.0 (2-4) | 241 | 45 | 5.0 | 1.04 |
| Rajasthan | NWPZ/CZ | 3 | 57 | 386 | 3.3 (2-4) | 240 | 54 | 5.7 | 1.35 |
| Bihar | NEPZ | 2 | 23 | 299 | 2.0 (1-3) | 187 | 61 | 5.0 | 2.30 |
| Gujarat | CZ | 2 | 6 | 450 | 5.0 (4-6) | 369 | 35 | 5.0 | 1.15 |
| Uttarakhand (plains) | NWPZ | 2 | 137 | 372 | 2.0 (1-3) | 164 | 91 | 6.0 | 1.41 |
| Jammu and Kashmir (plains) | NWPZ | 2 | 268 | 317 | 0.5 (0-1) | 43 | 106 | 6.0 | 1.26 |
| West Bengal | NEPZ | 2 | 22 | 299 | 1.8 (1-2) | 171 | 56 | 5.0 | 1.94 |

All runs: water balance closes to within 2e-13 mm. Irrigation totals exclude the pre-sowing
irrigation, which the model assumes fills the soil.

## What the results say

1. **The pattern across states is physically sensible.** Irrigation need follows dryness: Gujarat
   (almost no winter rain, highest crop water use) needs 4-6 irrigations, the same as ICAR's
   normal 4-6. Jammu and Kathua (200-300 mm of winter rain) need 0-1. The 120-day eastern season
   (Bihar, West Bengal) needs about 2, which matches the ICAR example of DBW 187 in Gorakhpur
   ("applied the irrigation two times"). These are plausibility checks, not accuracy.
2. **Public rain data is least reliable in the east.** Open-Meteo reports about twice IMD's rabi rain
   in UP (2.3x), Bihar (2.3x) and West Bengal (1.9x). In 43 of 54 rabi district-seasons two rain
   sources differ by more than 30 percent. Example: Shahjahanpur 2021-22, IMD 44 mm, Open-Meteo
   161 mm, NASA POWER 253 mm. Because rabi rain is small in absolute terms, the count of
   irrigations changed in 26 percent of seasons with Open-Meteo instead of IMD, but 41 percent of
   dates moved by more than 3 days. A live calculator can only use Open-Meteo or NASA POWER, so the
   eastern states are where on-farm rain or soil-moisture sensing could matter most.
3. **The calendar rules and the water balance disagree everywhere except the driest states.**
   ICAR's calendar irrigates 5-6 times on fixed days and ignores rain; the water balance gives
   0.5-3.3 in most states. The gap is widest where it rains (J&K: 6 vs 0.5). In Gujarat they agree
   on the count (5 vs 5). The ICAR calendar is meant for "adequate water"; it is a ceiling, not a
   target.
4. **Guessed inputs still move the advice the most.** Across all 54 district-seasons (mean 2.6
   irrigations): soil capacity -20 percent gives 3.4; roots to 1.5 m give 1.6; season -15 percent
   gives 1.8; Kc at start 0.7 gives 3.3. Rain source changes it least (Open-Meteo 2.35, NASA POWER
   2.5).

## Weak spots by state

- **Haryana:** uses national ICAR guidance; Haryana's own university guidance (HAU Hisar) not read.
- **Uttar Pradesh:** the western, eastern and Bundelkhand districts are placed in zones by the
  ICAR guide's division names; which districts count as "western UP" is our reading.
- **Madhya Pradesh:** Ujjain soil is 52 percent clay (black soil). The soil-water formula is used up
  to 60 percent clay, but as far as we know black soils often hold more water than it gives; Ujjain
  may need fewer irrigations than shown.
- **Rajasthan:** Ganganagar is sandy (100 mm per m), the lowest water-holding of all 27 districts.
- **Bihar, West Bengal, east UP:** NEPZ season length is uncertain: DBW 187 is "120 days", but the
  ICAR Gorakhpur example ran from the third week of November to 10 April, about 140 days. A
  15 percent longer season raises the mean from 2.6 to 3.2 irrigations across all districts.
- **Uttarakhand, J&K:** plains districts only (about half of each state's wheat). Hill wheat is a
  different, mostly rainfed system and is not covered.
- **Everywhere:** one point per district (district centroid), weather on 25 km and 0.25 degree
  grids, soil from a 250 m model. Advice is for a typical field in the district, not a farm.

Not covered: Himachal Pradesh (only about 18 percent of its wheat is in the plains districts Una and
Paonta), Maharashtra (excluded by the project brief), the Peninsular and hill zones.

## Run it

```
python scripts/refresh_data.py --start 2021 --end 2023 --locations data/locations_wheat_10states.csv --data-dir data_10states
python scripts/run_irrigation_baseline.py --processed data_10states/processed --locations data/locations_wheat_10states.csv --years 2021 2022
```
