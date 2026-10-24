# Irrigation baseline for rabi wheat: 10 states

Updated 24 October 2026 (advice rule and North Western Plains cut-off). Public data only.
27 districts, 2021-22 and 2022-23 seasons, 54 district-seasons.

**What this is and is not.** For each state the calculator uses that state's ICAR wheat zone
(sowing date, season length, irrigation stages) and real weather and soil data. Every result
below has been checked for correct arithmetic and for plausibility against official guidance. **It
has not been checked against real fields anywhere, so it has no accuracy figure.** No public
dataset of measured soil moisture and irrigation dates exists for wheat in these states (searched
24 October; the COSMOS-India portal offers no downloadable data).

## The advice rule (agreed 24 October)

Always give the first irrigation at crown root initiation, then irrigate when the soil has used its
readily available water (FAO-56 water balance), until the season's last irrigation date.

- First irrigation: Punjab, PAU, 4 weeks after a November sowing (3 weeks for October), 7.5 cm.
  Elsewhere, ICAR-IIWBR, 21 days after sowing (window 20-25 days), about 7 cm.
- Last irrigation date: North Western Plains, PAU's end of March (10 April if sown after
  5 December). North Eastern Plains and Central Zone, the last ICAR-IIWBR stage at least 10 days
  before maturity (milk stage, 105 days, about 28 February for a 15 November sowing).
- Why the North Western Plains use PAU's date for every state: ICAR-IIWBR's generic stage days put
  the last (dough) irrigation at 120 days, about 10 March, which for the zone's 152-day crop left
  about 21 days of water stress in March in Haryana, west UP and north Rajasthan. PAU, for the same
  zone, says to irrigate until the end of March to avoid heat stress at grain filling. This is our
  choice; check it with Haryana's own guidance when it can be read.

## Settings

| Zone (ICAR) | States / parts in this run | Default sowing | Season | Calendar rule compared |
|---|---|---|---|---|
| North Western Plains (NWPZ) | Punjab, Haryana, west UP, north Rajasthan, Uttarakhand plains, Jammu and Kathua | 10 Nov (window 1-25 Nov) | 152 days | Punjab: PAU; others: ICAR-IIWBR |
| North Eastern Plains (NEPZ) | east UP, Bihar, West Bengal | 15 Nov (window 10-20 Nov) | 120 days | ICAR-IIWBR |
| Central Zone (CZ) | Madhya Pradesh, Gujarat, Jhansi (UP), Bundi (Rajasthan) | 15 Nov (window 10-20 Nov) | 118 days | ICAR-IIWBR |

Sources: ICAR-DWR "Wheat Cultivation in India: Pocket Guide" (2014) for zones, sowing windows and
irrigation stages; ICAR-IIWBR advisory (November 2024) for the first irrigation at 20-25 days;
variety maturity days (NWPZ 146-156, CZ 116-119; NEPZ: DBW 187 120 days, range 118-124, and DBW 39
121 days, range 119-123); ICAR Research Complex for Eastern Region, Patna (2025) for eastern India
(timely sowing first to third week of November, 4-6 irrigations, crown root initiation first);
PAU Package of Practices for Punjab.

NEPZ season length is settled at 120 days: two eastern varieties mature in about 120 days. The
roughly 140 days in ICAR's Gorakhpur example (sown third week of November, harvested 10 April) runs
to harvest, which comes after the crop stops using water.

Districts: the largest wheat districts per state and zone in DES 2019-2022 data. Coordinates:
centroids of DataMeet Census 2011 district boundaries (Kathua: the town, as the centroid is in the
hills); the six pilot districts keep their town points. Elevation from Open-Meteo where not given.

## Results by state

Advice rule, IMD rain, default sowing. "Rain" is sowing-to-harvest IMD rain. "Water balance only"
is the same rule without the fixed first irrigation. "Dates differ" is the share of irrigation
dates that move by more than 3 days when Open-Meteo rain (the source a live calculator would use)
replaces IMD.

| State | Zone | Districts | Rain (mm) | Crop water use (mm) | Irrigations, mean (range) | Irrigation (mm) | Water balance only | Official calendar | Dates differ, Open-Meteo vs IMD |
|---|---|---|---|---|---|---|---|---|---|
| Punjab | NWPZ | 3 | 92 | 360 | 3.5 (2-5) | 275 | 2.7 | 2.3 (PAU) | 0.27 |
| Haryana | NWPZ | 3 | 78 | 392 | 4.2 (3-5) | 315 | 3.3 | 6.0 | 0.44 |
| Uttar Pradesh | NWPZ/NEPZ/CZ | 5 | 39 | 334 | 3.6 (2-5) | 278 | 2.7 | 5.4 | 0.40 |
| Madhya Pradesh | CZ | 3 | 31 | 350 | 3.8 (3-5) | 302 | 3.0 | 5.0 | 0.15 |
| Rajasthan | NWPZ/CZ | 3 | 57 | 386 | 4.7 (3-6) | 323 | 4.2 | 5.7 | 0.41 |
| Bihar | NEPZ | 2 | 23 | 299 | 3.0 (2-4) | 248 | 2.0 | 5.0 | 0.12 |
| Gujarat | CZ | 2 | 6 | 450 | 5.5 (5-6) | 409 | 5.0 | 5.0 | 0.04 |
| Uttarakhand (plains) | NWPZ | 2 | 137 | 372 | 3.5 (3-4) | 280 | 2.5 | 6.0 | 0.35 |
| Jammu and Kashmir (plains) | NWPZ | 2 | 268 | 317 | 2.0 (2-2) | 156 | 1.2 | 6.0 | 0.38 |
| West Bengal | NEPZ | 2 | 22 | 299 | 2.8 (2-3) | 238 | 1.8 | 5.0 | 0.29 |

All 54 district-seasons: mean 3.7 irrigations, 285 mm, 0.7 days of water stress per season. The
water balance closes to within 2e-13 mm. Irrigation totals exclude the pre-sowing irrigation,
which the model assumes fills the soil.

## What the results say

1. **Totals sit inside ICAR's normal range for dry states.** ICAR gives 4-6 irrigations totalling
   28-42 cm. Haryana (4.2, 32 cm), Rajasthan (4.7, 32 cm) and Gujarat (5.5, 41 cm) fall in it;
   wetter or shorter-season states need less (J&K 2.0, West Bengal 2.8). Irrigation need follows
   dryness. These are plausibility checks, not accuracy.
2. **Public rain data is least reliable in the east.** Open-Meteo reports about twice IMD's rabi
   rain in UP (2.3x), Bihar (2.3x) and West Bengal (1.9x). In 43 of 54 rabi district-seasons two
   rain sources differ by more than 30 percent (Shahjahanpur 2021-22: IMD 44 mm, Open-Meteo 161 mm,
   NASA POWER 253 mm). With the advice rule, Open-Meteo instead of IMD changes the irrigation count
   in 20 percent of seasons and moves 30 percent of dates by more than 3 days.
3. **The fixed first irrigation makes rain matter less**, because it does not depend on rain; the
   water balance alone moved 43 percent of dates with Open-Meteo rain.
4. **The official calendars irrigate more** (5-6 times on fixed days, ignoring rain); they are for
   "adequate water", a ceiling rather than a target. The gap is widest where it rains (J&K: 6 vs 2).
5. **Guessed inputs still move the advice the most.** Across all 54 district-seasons (mean 3.7):
   soil capacity -20 percent gives 4.6; roots to 1.5 m give 2.7; season -15 percent gives 2.7;
   season +15 percent gives 4.5. Rain source changes it least (Open-Meteo 3.5, NASA POWER 3.6).

## Weak spots by state

- **Haryana, Uttar Pradesh:** national ICAR guidance; the state university or department
  guidance could not be read online (HAU's package of practices is not online in readable form; one
  HAU recommendations file gives only a 25 October-15 November sowing window; the UP agriculture
  department site blocks automated reading).
- **Uttar Pradesh:** the western, eastern and Bundelkhand districts are placed in zones by the
  ICAR guide's division names; which districts count as "western UP" is our reading.
- **Madhya Pradesh:** Ujjain soil is 52 percent clay (black soil). The soil-water formula is used up
  to 60 percent clay, but as far as we know black soils often hold more water than it gives; Ujjain
  may need fewer irrigations than shown.
- **Rajasthan:** Ganganagar is sandy (100 mm per m), the lowest water-holding of all 27 districts.
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
