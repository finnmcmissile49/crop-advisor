# Irrigation advice for 11 more crops (Punjab and Haryana)

27 October 2026. Added: mustard (raya), chickpea (gram), barley, autumn potato, spring maize,
summer moong, cotton (narma), kharif maize, bajra, kharif moong, kharif groundnut. With wheat that
makes 12 crops. Settings: `src/cropadvisor/crops.py` (every number has its source next to it).
Checks: `scripts/check_crops.py`, results in `data/checks/`.

**What this is.** The same FAO-56 soil water balance as wheat, with each crop's FAO-56 numbers
and PAU's own rules for that crop (sowing time, first watering, last watering, periods with no
watering, how many waterings at most). **It has not been checked against real fields for any
crop, so there is no accuracy figure.** What was checked: the arithmetic (the water balance closes
to 1e-13 mm in all 306 district-seasons), and whether the advice on five past seasons agrees with
the number of waterings PAU states.

## Use it

```
python scripts/advise.py --crops
python scripts/advise.py --crop mustard --district Bathinda --sowing 2026-10-15
python scripts/advise.py --crop cotton --district Hisar --sowing 2027-04-25 --watered 2027-05-30
```

The other crops work in the six Punjab and Haryana districts (Sirsa, Hisar, Kurukshetra,
Bathinda, Sangrur, Tarn Taran). Their soil numbers are now in the repo
(`data/soil_awc_pilot.csv`), so the calculator runs from a fresh copy for these districts without
the full data pull.

## Where the numbers come from

- **FAO-56** (Allen et al. 1998): stage lengths (Table 11), crop coefficients and crop height
  (Table 12), rooting depth and depletion fraction (Table 22).
- **PAU Package of Practices for Crops of Punjab**: Rabi 2025-26 (August 2025) for mustard,
  chickpea, barley, spring maize, summer moong; Kharif 2026 (March 2026) for cotton, maize, bajra,
  moong, groundnut. **PAU Package of Practices for Cultivation of Vegetables 2021** for potato.
  These were read from the PDFs on pau.edu on 27 October 2026.
- **Weather** for the checks: Open-Meteo history, daily rain, ET0, minimum humidity and wind,
  2021-2025, the six district points (`data/checks/openmeteo_daily_punjab_haryana_2021_2025.csv`).
  This is the source the live calculator uses, so the checks use it too. IMD was not used for
  these checks.
- **Soil**: SoilGrids 2.0 with Saxton-Rawls, fetched again on 27 October; the six values match the
  earlier data pull exactly (for example Hisar 122.0 and Bathinda 123.0 mm per m).

## The crops

| Crop | PAU sowing | Season (days) | First watering (days after sowing) | PAU limits used |
|---|---|---|---|---|
| Mustard (raya) | 15 Oct-15 Nov | 143 | 21-28 | at most 2; none 25 Dec-15 Jan (stem rot); none after end of February |
| Chickpea (gram) | 25 Oct-10 Nov | 156 | none | 1 watering, only between 15 Dec and 31 Jan and at least 4 weeks after sowing |
| Barley | 15 Oct-15 Nov | 141 | 35-42 | at most 2 |
| Potato (autumn) | 24 Sep-15 Oct | 95 | at planting (assumed done) | light waterings |
| Spring maize | 20 Jan-15 Feb | 118 | 25-30 | up to maturity |
| Summer moong | 20 Mar-10 Apr | 61 | 22-28 | none after day 55 |
| Cotton (narma) | 1 Apr-15 May | 165 | 28-42 | none after 30 September |
| Kharif maize | 25 May-30 Jun | 97 | none (rain) | none |
| Bajra | 1-31 Jul | 88 | none (rain) | at most 2 |
| Kharif moong | 16-31 Jul | 71 | none (rain) | none |
| Groundnut (kharif) | 25 Apr-31 May | 115 | none (PAU gives no day for flowering) | at most 3 |

Choices that are ours, applied the same way to every crop (details in `crops.py`):

- Rooting depth: the lower end of FAO-56's range (FAO-56: smaller values "may be used for
  irrigation scheduling"), capped at 1 m where the soil data stop. Exceptions inside FAO's range:
  the upper end for summer moong, kharif moong and groundnut, because at the lower end past seasons
  needed clearly more waterings than PAU states (summer moong: mean 7.0 against PAU's 3-5); and for
  chickpea, because PAU says the pre-sowing irrigation "will ensure deep rooting". **Matching PAU's
  numbers is a check against guidance, not against fields.**
- Stage split: FAO-56 Table 11 has no row for mustard or chickpea. Stand-ins: small grains
  (Pakistan, October/November) for mustard and lentil (arid region, October/November) for chickpea.
- Each watering refills the root zone; the advice says how many cm the soil is short of.
- Kc mid and Kc end are adjusted for humidity and wind (FAO-56 eq. 62), using Open-Meteo's daily
  minimum humidity and wind. This is new; wheat keeps it off because its results were checked
  without it.
- Haryana uses PAU's guidance; HAU's own package could not be read online.

## Past-season check

Six districts, the seasons from 2021 to 2025 that the weather covers, PAU's default sowing date,
Open-Meteo weather. 306 district-seasons in total.

| Crop | District-seasons | Rain (mm) | Waterings, mean (range) | PAU says | Inside PAU's range | Water given (mm) | Stress days |
|---|---|---|---|---|---|---|---|
| Mustard | 24 | 91 | 1.9 (1-2) | 1-2 | 100% | 109 | 16.0 |
| Chickpea | 24 | 111 | 0.9 (0-1) | 0-1 | 100% | 68 | 35.3 |
| Barley | 24 | 97 | 1.9 (1-2) | 1-2 | 100% | 110 | 13.0 |
| Potato | 24 | 44 | 7.8 (4-10) | 7-8 | 33% | 171 | 1.8 |
| Spring maize | 30 | 87 | 9.7 (5-14) | calendar: about 10* | - | 533 | 0.0 |
| Summer moong | 30 | 45 | 4.5 (3-6) | 3-5 | 77% | 233 | 8.6 |
| Cotton | 30 | 504 | 3.7 (1-7) | 4-6 | 47% | 254 | 10.6 |
| Kharif maize | 30 | 424 | 1.3 (0-4) | 4-6 | 7% | 86 | 0.4 |
| Bajra | 30 | 359 | 0.8 (0-2) | about 2 | 100% | 54 | 2.8 |
| Kharif moong | 30 | 310 | 1.1 (0-4) | only if rain fails | 83% (0-2) | 60 | 0.5 |
| Groundnut | 30 | 411 | 2.5 (1-3) | 2-3 | 80% | 92 | 14.9 |

\* PAU gives spring maize a calendar, not a number: first watering at 25-30 days, then every two
weeks to 10 April, then weekly to maturity. For a 1 February sowing that is about 10 waterings.

Water stress days follow FAO-56's definition (soil drier than the readily available water). For
mustard, barley, chickpea and groundnut they come from PAU's limits on the number of waterings:
PAU accepts some dryness in these crops (for chickpea it warns that extra water lowers grain
yield). They are not predicted yield losses.

What the check says:

1. **Eight of eleven crops agree with PAU most of the time.** Mustard, chickpea, barley and bajra
   always fall in PAU's range (partly because PAU's limits are built into the rule); summer moong,
   groundnut and kharif moong in 77-83 percent of seasons; potato averages exactly PAU's 7-8 but
   varies with rain.
2. **Cotton follows rainfall.** In the drier south-west (Sirsa, Hisar, Bathinda) it gives 3-7
   waterings, mostly inside PAU's 4-6; in the wetter Kurukshetra, Sangrur and Tarn Taran 1-4, below
   PAU's range. 2025, a very wet monsoon in Punjab, gives the fewest (1-4). PAU's "depending upon
   the seasonal rainfall" allows fewer in wet years; whether 1-2 is enough in practice is a
   question for an agronomist.
3. **Kharif maize disagrees with PAU.** Mean 1.3 waterings against 4-6: 3-4 in dry seasons, 0-1 in
   wet ones. Two possible reasons, not resolved: Open-Meteo's monsoon rain in Punjab has not been
   checked against IMD (it reads 65 percent above IMD in rabi for these districts), and FAO-56's
   starting Kc of 0.3 is low for a soil wetted by frequent rain. **Kharif maize is marked lower
   confidence** in the calculator until this is checked.
4. **The guessed inputs still move the dates a lot**, as for wheat. Soil water-holding 20 percent
   lower or higher moves 20-79 percent of watering dates by more than 3 days (most for chickpea,
   whose single watering jumps between the trigger day and the end of PAU's window). The other end
   of FAO's rooting range moves 38-92 percent. The Kc humidity adjustment moves 0-29 percent (most
   for maize). A soil moisture reading in the field is still the input that would change the
   advice most.

## The live forecast

Checked on 27 October 2026 with today's real Open-Meteo forecast for Bathinda (24 days of
recorded weather plus 16 days of forecast), run through the calculator's own weather code. Potato
planted 5 October and watered 20 October: next watering around 31 October (28 October on light
soil, 1 November on heavy soil), about 2 cm. Mustard sown 15 October: first watering 5-12
November. The live download itself was made from a browser, because this workspace cannot reach
Open-Meteo; it still needs one run on your PC (`python scripts/advise.py ...`).

## Known limits

- Not checked against any real field, for any crop.
- PAU's guidance is for Punjab; Haryana farmers may follow HAU's, which could differ.
- One weather point and one soil value per district; soil from a model.
- Kharif maize: lower confidence (above).
- Sowing after PAU's window is accepted for 10 days with a warning; later sowing is refused,
  because the crop settings are for timely sowing.
- Potato: the advice assumes the planting irrigation was given.
- Groundnut: PAU's "first irrigation at flowering" is not encoded (PAU gives no day for it).
- Not done: paddy (needs a flooded-field model, not a soil water balance), sugarcane (PAU gives no
  season length for Punjab spring cane, and FAO-56's stage rows are for the tropics), guar (no
  readable official guidance for Haryana found), vegetables other than potato.
- The Hindi text needs a native speaker and Digital Green to check it before farmers see it.
