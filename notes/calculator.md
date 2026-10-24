# Wheat irrigation calculator (v0): how to use it

24 October 2026. A terminal tool: you give a district, the sowing date and the dates you have
watered; it tells you when to water next, in English and Hindi.

**Test version.** Advice is for a typical field in the district, from free public data (Open-Meteo
weather and forecast, SoilGrids soil). It has not been checked against real fields.

## Run it

In PowerShell, in the code folder (`06_code_crop_advisor`):

```
python scripts/advise.py --list
python scripts/advise.py --district Hisar --sowing 2026-11-10
python scripts/advise.py --district Hisar --sowing 2026-11-10 --watered 2026-12-01 2027-01-15
```

- `--district`: one of the 27 districts (`--list` shows them).
- `--sowing`: the sowing date, YYYY-MM-DD.
- `--watered`: every date the field was irrigated after sowing (not the pre-sowing watering).
- `--depth-cm`: how much water one irrigation gives, if not the usual (7.5 cm Punjab, 7 cm
  elsewhere).
- `--lang en` or `--lang hi`: one language only.

Needs the internet, and the soil file from the 10-state data pull
(`data_10states/processed/soil.csv`).

## Try it on a past season

Add `--today` with a date at least 23 days ago. The calculator then pretends it is that day and
uses the weather that was actually recorded for the next 16 days as the "forecast" (a perfect
forecast, so real advice is less certain):

```
python scripts/advise.py --district Hisar --sowing 2025-11-10 --today 2025-11-25
python scripts/advise.py --district Hisar --sowing 2025-11-10 --watered 2025-12-08 --today 2026-01-20
```

## What it does

1. Checks the inputs. It says "I do not know" if the district is not set up, the sowing date is
   outside 15 October to 15 January, the crop is past its season, or the weather has gaps.
2. Before the first watering: tells you the first-watering window (crown root initiation: PAU
   25-31 days after a November sowing in Punjab; ICAR 20-25 days elsewhere). This watering is
   always advised.
3. After that: replays the soil water day by day from sowing to today with the recorded weather
   and your watering dates, then looks ahead with the 16-day forecast for the day the soil has used
   its easily available water.
4. Gives the most likely day, plus how it changes if your soil is light (holds 20 percent less
   water) or heavy (20 percent more). The 20 percent is a chosen range, not a measured one.
5. Stops advising after the season's last irrigation date (end of March in the North Western
   Plains; milk stage, about 105 days after sowing, in the North Eastern Plains and Central Zone).

## Checks so far

- 95 offline tests (made-up weather), including every advice message in both languages.
- Followed the advice through 16 real past seasons (8 districts in 8 states: Haryana, Punjab, MP,
  Bihar, Gujarat, J&K, West Bengal, UP). The first watering matched the season baseline exactly.
  Later waterings came 1-7 days earlier, and sometimes one extra watering, because the calculator
  assumes a fixed 7 cm per watering (what farmers usually give), which does not fully refill the
  soil mid-season; the baseline refills it exactly.
- Not checked: the live forecast download on a real date (it could not be run from Claude's
  workspace; run it on your PC), and any comparison with real fields.

## Known limits

- One weather point per district; soil from a model, not your field.
- Rain between now and the advised date changes the answer: run it again after rain.
- The Hindi text is a first version; have a native speaker and Digital Green check it before
  farmers see it.
