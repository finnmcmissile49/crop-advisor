import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "fetch_prices_local", Path(__file__).parent.parent / "scripts" / "fetch_prices_local.py")
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)


def rec(state="Maharashtra", market="Latur", commodity="Soyabean", d="16/10/2026",
        lo="4200", hi="4600", modal="4400"):
    return {"State": state, "District": "Latur", "Market": market, "Commodity": commodity,
            "Variety": "Yellow", "Grade": "FAQ", "Arrival_Date": d,
            "Min_Price": lo, "Max_Price": hi, "Modal_Price": modal}


def test_clean_parses_and_drops_bad_rows():
    df = fp.clean(pd.DataFrame([rec(), rec(), rec(modal="0"), rec(lo="5000", hi="4000"),
                                rec(market="Nanded")]))
    assert len(df) == 2                                  # duplicate, zero price, min>max removed
    assert df["arrival_date"].iloc[0] == pd.Timestamp(2026, 10, 16)   # dd/mm/yyyy
    assert df["modal_price"].dtype.kind == "f" or df["modal_price"].dtype.kind == "i"


def test_download_pages_until_total(monkeypatch):
    monkeypatch.setattr(fp, "PAGE", 2)
    monkeypatch.setattr(fp.time, "sleep", lambda s: None)
    data = [rec(market=f"M{i}") for i in range(5)]
    calls = []

    def fake(key, offset, retries=5, limit=None):
        if limit == 1:
            return {"total": 5, "records": data[:1]}
        calls.append(offset)
        return {"total": 5, "records": data[offset:offset + 2]}

    monkeypatch.setattr(fp, "get_page", fake)
    df = fp.download("k")
    assert calls == [0, 2, 4] and len(df) == 5


def test_merge_keeps_history_and_replaces_same_day(tmp_path):
    path = tmp_path / "all.csv"
    day1 = fp.clean(pd.DataFrame([rec(d="15/10/2026"), rec(d="16/10/2026", modal="4400")]))
    fp.merge_into_all(day1, path).to_csv(path, index=False)
    day2 = fp.clean(pd.DataFrame([rec(d="16/10/2026", modal="4450"),
                                  rec(d="17/10/2026", modal="4500")]))
    out = fp.merge_into_all(day2, path)
    assert len(out) == 3                                  # 15th, 16th (updated), 17th
    assert out.loc[out.arrival_date == "2026-10-16", "modal_price"].item() == 4450


def test_partial_download_is_kept_when_server_stalls(monkeypatch):
    monkeypatch.setattr(fp, "PAGE", 2)
    monkeypatch.setattr(fp.time, "sleep", lambda s: None)
    data = [rec(market=f"M{i}") for i in range(6)]

    def fake(key, offset, retries=5, limit=None):
        if limit == 1 or offset < 4:
            return {"total": 6, "records": data[offset:offset + 2]}
        return None                                       # server stops answering

    monkeypatch.setattr(fp, "get_page", fake)
    assert len(fp.download("k")) == 4


def test_no_answer_at_all_exits(monkeypatch):
    import pytest
    monkeypatch.setattr(fp, "get_page", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        fp.download("k")
