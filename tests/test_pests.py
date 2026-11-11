"""Pest and disease watch. All weather here is made up: these test that the published conditions
are applied as written, not that the conditions predict outbreaks."""
import numpy as np
import pandas as pd

from cropadvisor import pests as ps
from cropadvisor import service

from test_service import fake_forecast, fake_history


def hourly(today, tmin, tmax, rh_night, rh_day, cloud=30.0, rain_days=(), past=None):
    """Made-up hourly weather around `today`; `past` (tmin, tmax, rh_night, rh_day) overrides the
    days up to today, so the forecast week can differ from the last week."""
    t0 = pd.Timestamp(today) - pd.Timedelta(days=ps.BACK_DAYS)
    rows = []
    for d in range(ps.BACK_DAYS + ps.AHEAD_DAYS + 1):
        day = t0 + pd.Timedelta(days=d)
        lo, hi, rn, rd = past if (past and day <= pd.Timestamp(today)) else (tmin, tmax, rh_night,
                                                                              rh_day)
        for h in range(24):
            temp = lo + (hi - lo) * max(0.0, np.sin((h - 6) / 12 * np.pi)) if 6 <= h <= 18 else lo
            rows.append({"time": day + pd.Timedelta(hours=h), "temp": temp,
                         "rh": rn if (h >= 20 or h <= 6) else rd,
                         "rain": 5.0 if (d in rain_days and h == 15) else 0.0, "cloud": cloud})
    return pd.DataFrame(rows)


def level(crop, sowing, today, h, key, state="Punjab", zone=None):
    res = ps.assess(crop, state, sowing, today, ps.daily(h), zone)
    return next(r for r in res if r["rule"].key == key)


def test_yellow_rust_rises_when_pau_weather_is_forecast():
    h = hourly("2027-01-20", 9, 20, 92, 70, past=(4, 17, 60, 40))
    r = level("wheat", "2026-11-10", "2027-01-20", h, "yellow_rust", zone="NWPZ")
    assert r["level"] == "rising" and r["next"] == 7 and r["past"] == 0


def test_yellow_rust_quiet_when_nights_are_dry_or_days_hot():
    dry = hourly("2027-01-20", 9, 20, 60, 40)
    hot = hourly("2027-03-25", 16, 31, 92, 70)
    assert level("wheat", "2026-11-10", "2027-01-20", dry, "yellow_rust", zone="NWPZ")["level"] \
        == "none"
    assert level("wheat", "2026-11-10", "2027-03-25", hot, "yellow_rust", zone="NWPZ")["level"] \
        == "none"


def test_high_when_both_weeks_are_favourable_and_easing_when_it_passes():
    both = hourly("2027-01-20", 9, 20, 92, 70)
    assert level("wheat", "2026-11-10", "2027-01-20", both, "yellow_rust", zone="NWPZ")["level"] \
        == "high"
    passing = hourly("2027-01-20", 4, 17, 60, 40, past=(9, 20, 92, 70))
    assert level("wheat", "2026-11-10", "2027-01-20", passing, "yellow_rust",
                 zone="NWPZ")["level"] == "easing"


def test_late_blight_follows_jhulsacast_hours():
    wet = hourly("2026-11-20", 10, 22, 95, 88)      # every hour above 85% and inside 7.2-26.6
    d = ps.daily(wet)
    last = d.iloc[-1]
    assert last.wet_hours_7 == 168 and last.temp_hours_7 == 168
    assert level("potato", "2026-10-01", "2026-11-20", wet, "late_blight")["level"] == "high"
    night_only = hourly("2026-11-20", 10, 22, 95, 60)   # 11 humid hours a day = 77 in 7 days
    assert ps.daily(night_only).iloc[-1].wet_hours_7 == 77
    assert level("potato", "2026-10-01", "2026-11-20", night_only, "late_blight")["level"] == "none"


def test_stage_watches_follow_the_crop_calendar():
    quiet = hourly("2026-08-10", 26, 34, 60, 40)
    assert level("cotton", "2026-05-01", "2026-08-10", quiet, "sucking_pests")["level"] == "stage"
    june = hourly("2026-06-10", 26, 40, 40, 20)
    assert level("cotton", "2026-05-01", "2026-06-10", june, "sucking_pests")["level"] == "none"
    early = hourly("2026-12-20", 6, 18, 60, 40)
    assert level("wheat", "2026-11-10", "2026-12-20", early, "wheat_aphid",
                 zone="NWPZ")["level"] == "none"       # no ears yet at day 40
    ears = hourly("2027-03-01", 12, 26, 60, 40)
    assert level("wheat", "2026-11-10", "2027-03-01", ears, "wheat_aphid",
                 zone="NWPZ")["level"] == "stage"


def test_mustard_aphid_is_watched_from_january_whatever_the_weather():
    clear = hourly("2027-01-12", 6, 22, 60, 40, cloud=10)
    assert level("mustard", "2026-10-20", "2027-01-12", clear, "mustard_aphid")["level"] == "watch"
    grey = hourly("2027-01-12", 6, 16, 95, 80, cloud=85)
    assert level("mustard", "2026-10-20", "2027-01-12", grey, "mustard_aphid")["level"] == "high"
    december = hourly("2026-12-10", 6, 16, 95, 80, cloud=85)
    assert level("mustard", "2026-10-20", "2026-12-10", december, "mustard_aphid")["level"] \
        == "none"


def test_nothing_is_flagged_after_harvest_or_for_another_crop():
    h = hourly("2027-06-20", 9, 20, 92, 70)
    res = ps.assess("wheat", "Punjab", "2026-11-10", "2027-06-20", ps.daily(h), "NWPZ")
    assert all(r["level"] == "none" for r in res)
    assert {r["rule"].key for r in res} == {"yellow_rust", "wheat_aphid"}


def test_every_crop_has_a_rule_and_every_rule_a_source():
    from cropadvisor import crops as cr
    covered = {c for r in ps.RULES for c in r.crops}
    assert covered >= {"wheat"} | set(cr.CROPS)
    for r in ps.RULES:
        assert r.source and r.why_en and r.why_hi and r.look_en and r.look_hi
        assert (r.kind == "stage") == (r.test is None)


def test_text_names_no_spray_and_says_what_to_look_for():
    h = hourly("2027-01-20", 9, 20, 92, 70, past=(4, 17, 60, 40))
    w = ps.watch("wheat", "Punjab", "2026-11-10", "2027-01-20", 30.2, 74.9, zone="NWPZ",
                 fetch=lambda la, lo, t, now: h)
    en, hi = ps.text(w)
    joined = "\n".join(en).lower()
    assert "yellow rust: risk rising" in joined and "look for" in joined
    for word in ("spray 2", " ml ", "propiconazole", "tilt", "per acre"):
        assert word not in joined
    assert len(en) == len(hi) and "पीला रतुआ" in "\n".join(hi)
    assert ps.to_json(w)["results"][0]["source"].startswith("PAU")


def test_weather_failure_leaves_the_rest_of_the_advice_standing():
    def boom(lat, lon, today, now):
        raise OSError("open-meteo unreachable")
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2026-01-20"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast(), fetch_pest=boom)
    assert res["ok"] and "Pest watch" in res["text_en"] and "Fertiliser for wheat" in res["text_en"]
    assert res["pests"] == {"error": "open-meteo unreachable"}


def test_daily_advice_carries_the_pest_watch():
    h = hourly("2026-01-20", 9, 20, 92, 70)
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": [], "crop": "wheat",
           "today": "2026-01-20"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast(),
                                 fetch_pest=lambda la, lo, t, now: h)
    assert res["ok"] and "Yellow rust: RISK HIGH" in res["text_en"]
    assert res["pests"]["results"][0]["level"] == "high"
