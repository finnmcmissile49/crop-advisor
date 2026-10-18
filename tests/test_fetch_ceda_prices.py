import csv
import importlib.util
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fetch_ceda_prices", Path(__file__).parent.parent / "scripts" / "fetch_ceda_prices.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


def test_build_jobs_orders_state_level_first_and_soybean_first_for_districts():
    jobs = fc.build_jobs({27: [524, 521], 23: [400]}, states=[27, 23],
                         state_crops=[13, 1], district_crops=[13, 15])
    assert jobs[0] == ("prices", "state", 27, 0, 13)
    assert ("arrivals", "state", 23, 0, 1) in jobs
    dist = [j for j in jobs if j[1] == "district"]
    assert [j[4] for j in dist] == [13, 13, 13, 15, 15, 15]
    assert len(jobs) == 2 * 2 * 2 + 6


def test_to_rows_keeps_ids_and_prices():
    recs = [{"t": "2024-12", "cmdty": "Soyabean", "district_id": 524, "district": "Latur",
             "p_min": 3688.9, "p_max": 4245.8, "p_modal": 4077.0}]
    rows = fc.to_rows(recs, "prices", "district", 27, 524, 13)
    assert rows[0]["month"] == "2024-12" and rows[0]["district_id"] == 524
    assert rows[0]["p_modal"] == 4077.0 and rows[0]["district"] == "Latur"


def test_append_csv_writes_header_once(tmp_path):
    p = tmp_path / "x.csv"
    lock = threading.Lock()
    fc._append_csv(p, [{"a": 1, "b": 2}], lock)
    fc._append_csv(p, [{"a": 3, "b": 4}], lock)
    rows = list(csv.DictReader(open(p)))
    assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_post_returns_none_on_bad_request(monkeypatch):
    class R:
        status_code = 400
    class S:
        def post(self, *a, **k):
            return R()
    monkeypatch.setattr(fc.time, "sleep", lambda s: None)
    assert fc.post("prices", {}, session=S()) is None


def test_stop_skips_remaining_work(tmp_path):
    fc.STOP.set()
    try:
        job, n = fc._work(tmp_path, ("prices", "state", 27, 0, 13), None, threading.Lock())
        assert n is None and not (tmp_path / "rows_prices.csv").exists()
    finally:
        fc.STOP.clear()


def test_reverse_run_starts_from_the_end(tmp_path, monkeypatch):
    seen = []
    jobs = [("prices", "state", 27, 0, 13), ("prices", "district", 27, 1, 13),
            ("prices", "district", 27, 1, 15)]
    monkeypatch.setattr(fc, "get", lambda ep, session=None: [{"census_district_id": 1}])
    monkeypatch.setattr(fc, "build_jobs", lambda districts: list(jobs))
    monkeypatch.setattr(fc, "_work", lambda out, job, s, l: (seen.append(job), (job, 0))[1])
    monkeypatch.setattr(fc, "THREADS", 1)
    fc._run(tmp_path, None, reverse=True)
    assert seen == list(reversed(jobs))
