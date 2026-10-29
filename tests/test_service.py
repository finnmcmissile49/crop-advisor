"""Offline tests for field location, soil types, confidence, the service and the web server.
All weather here is made up; no network is used."""
import json
import os
import sys
import threading
import urllib.request

import pandas as pd
import pytest

from cropadvisor import advisor as av
from cropadvisor import service, sites

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))


def fake_forecast(start="2025-11-10", days=200, et0=3.0):
    def f(lat, lon, days=16, past_days=0, raw_path=None):
        d = pd.DataFrame({"date": pd.date_range(start, periods=200), "rain_mm": 0.0,
                          "et0_openmeteo_mm": et0, "rh_min": 40.0, "wind_2m_ms": 1.5})
        return d
    return f


def fake_history(start="2025-11-10", et0=3.0):
    def f(lat, lon, s, e, raw_path=None):
        return pd.DataFrame({"date": pd.date_range(s, e), "rain_mm": 0.0,
                             "et0_openmeteo_mm": et0, "rh_min": 40.0, "wind_2m_ms": 1.5})
    return f


# ------------------------------------------------------------------------- sites

def test_district_site_uses_committed_soil_file():
    site, notes = sites.build_site("Ujjain", soil_files=(sites.SOIL_FILES[1],))
    assert site.awc_mm_per_m == pytest.approx(126.6) and site.soil_source == "district"
    assert notes == []


def test_field_point_soil(monkeypatch):
    monkeypatch.setattr(sites, "field_awc", lambda lat, lon, fetch=None: (150.0, 0.0))
    site, notes = sites.build_site("Hisar", 29.20, 75.65)
    assert (site.lat, site.lon, site.awc_mm_per_m, site.soil_source) == (29.20, 75.65, 150.0,
                                                                          "field")
    assert notes[0][0] == "field"


def test_field_point_soil_failure_falls_back(monkeypatch):
    def boom(lat, lon, fetch=None):
        raise RuntimeError("SoilGrids down")
    monkeypatch.setattr(sites, "field_awc", boom)
    site, notes = sites.build_site("Hisar", 29.20, 75.65)
    assert site.awc_mm_per_m == pytest.approx(122.0) and site.soil_source == "district"
    assert notes[0][0] == "field_soil_failed"


@pytest.mark.parametrize("lat,lon,msg", [(29.2, None, "both"), (40.0, 75.0, "not in India"),
                                         (31.6, 74.9, "km from Hisar")])
def test_bad_field_location(lat, lon, msg):
    with pytest.raises(av.AdviceError, match=msg):
        sites.build_site("Hisar", lat, lon)


def test_soil_type_range_and_text():
    site, notes = sites.build_site("Hisar", soil_type="loam")
    cases = av.soil_cases(site)
    assert (cases["light"], cases["heavy"]) == (130.0, 180.0)     # FAO-56 Table 19 loam
    assert cases["likely"] == 155.0          # SoilGrids 122 is outside loam's range: midpoint
    site2, _ = sites.build_site("Hisar", soil_type="light_loam")
    assert av.soil_cases(site2)["likely"] == pytest.approx(122.0)  # inside 110-150: kept
    with pytest.raises(av.AdviceError, match="Soil type"):
        sites.build_site("Hisar", soil_type="black")


# ------------------------------------------------------------------------- confidence

def test_confidence_levels():
    site, _ = sites.build_site("Hisar")
    a = {"status": "water_window", "today": pd.Timestamp("2026-01-01"),
         "likely": pd.Timestamp("2026-01-03"), "site": site, "warnings": []}
    assert av.confidence(a)[0][0] == "medium"       # district soil only
    a["soil_type"] = "loam"
    assert av.confidence(a)[0][0] == "high"
    a["likely"] = pd.Timestamp("2026-01-12")        # 11 days ahead: beyond the tested forecast
    assert av.confidence(a)[0][0] == "low"


# ------------------------------------------------------------------------- service

def test_service_end_to_end_json():
    req = {"district": "Hisar", "sowing": "2025-11-10", "watered": ["2025-12-02"],
           "today": "2026-01-05", "soil_type": "loam"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast())
    assert res["ok"], res
    js = json.loads(json.dumps(res, ensure_ascii=False))
    adv = js["advice"]
    assert adv["crop"] == "wheat" and adv["site"]["soil_type"] == "loam"
    assert adv["confidence"]["level"] in ("high", "medium", "low")
    assert "Confidence:" in res["text_en"] and "भरोसा:" in res["text_hi"]
    assert "Soil: loam (as you said)." in res["text_en"]


def test_service_other_crop_and_errors():
    req = {"district": "Bathinda", "sowing": "2025-10-25", "crop": "mustard",
           "today": "2025-11-05"}
    res = service.advise_request(req, now="2027-01-20", fetch_history=fake_history(),
                                 fetch_forecast=fake_forecast())
    assert res["ok"] and res["advice"]["status"] == "first_upcoming"
    bad = service.advise_request({"district": "Hisar", "sowing": "2025-11-10", "crop": "rice"})
    assert not bad["ok"] and "Unknown crop" in bad["error"]
    bad = service.advise_request({"district": "Hisar", "sowing": "not a date"})
    assert not bad["ok"] and bad["text_en"].startswith("I do not know")


# ------------------------------------------------------------------------- web server

@pytest.fixture
def server():
    import serve
    from http.server import ThreadingHTTPServer

    class H(serve.Handler):
        advise = staticmethod(lambda req: service.advise_request(
            req, now="2027-01-20", fetch_history=fake_history(), fetch_forecast=fake_forecast()))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_endpoints(server):
    assert get(server + "/health") == (200, {"ok": True})
    code, crops = get(server + "/crops")
    assert code == 200 and crops[0]["key"] == "wheat" and len(crops) == 12
    code, d = get(server + "/districts")
    assert code == 200 and len(d) == 27
    code, res = get(server + "/advice?district=Hisar&sowing=2025-11-10&watered=2025-12-02"
                    "&today=2026-01-05")
    assert code == 200 and res["ok"] and res["advice"]["status"]
    code, res = get(server + "/advice?district=Nowhere&sowing=2025-11-10")
    assert code == 422 and not res["ok"]
    body = json.dumps({"district": "Hisar", "sowing": "2025-11-10", "today": "2025-11-20"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(server + "/advice", data=body,
                                                      method="POST"))
    assert json.loads(r.read())["advice"]["status"] == "first_upcoming"
