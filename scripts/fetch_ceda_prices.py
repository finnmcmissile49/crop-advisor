"""Download monthly mandi prices (Agmarknet, cleaned by CEDA Ashoka) for many states and districts.

Source: CEDA Agri Market Data, https://agmarknet.ceda.ashoka.edu.in (Agmarknet data from the
Directorate of Marketing & Inspection, Ministry of Agriculture & Farmers Welfare). Cite both.
No key or login. The site's own JSON endpoints are used, politely (few threads, retries, pauses).

What it saves (in OUT_DIR):
  rows_prices.csv      monthly min / max / modal price (Rs per quintal), state and district level
  rows_arrivals.csv    monthly arrivals, state level
  done.jsonl           one line per finished request, so a rerun resumes where it stopped
  log.txt              progress

State and district ids are Census 2011 codes, the same as ICRISAT's
"Indian census State Code 2011" and "Indian census District Code 2011" columns.

Run in Colab:   run(out_dir="/content/ceda", background=True)  then check progress().
Run locally:    python fetch_ceda_prices.py
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = "https://agmarknet.ceda.ashoka.edu.in/api"
START, END = "2001-01-01", "2026-12-31"
THREADS = 6

# ICRISAT's 20 states (Census 2011 ids), so prices line up with the yield data
ICRISAT_STATES = [28, 18, 10, 22, 24, 6, 2, 20, 29, 32, 23, 27, 21, 3, 8, 33, 36, 9, 5, 19]

# CEDA commodity ids. State level: every field crop the advisor might rank.
STATE_CROPS = [1, 2, 3, 4, 5, 6, 7, 49, 8, 9, 10, 11, 12, 13, 14, 15, 28, 29, 30, 63, 67,
               123, 74, 23, 24]
# District level: the main crops, in priority order (soybean first, so a partial run is useful)
DISTRICT_CROPS = [13, 15, 49, 6, 1, 2, 4, 5, 28, 10, 12, 9, 8]

_state = {"done": 0, "total": 0, "rows": 0, "failed": 0, "running": False, "phase": ""}
_lock = threading.Lock()


def post(endpoint, body, retries=4, session=requests):
    """POST to a CEDA endpoint; return the list in 'data', [] if empty, None if it kept failing."""
    for attempt in range(1, retries + 1):
        try:
            r = session.post(f"{BASE}/{endpoint}", json=body, timeout=120)
            if r.status_code == 200:
                return r.json().get("data", []) or []
            if r.status_code == 400:          # bad request: retrying will not help
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * attempt)
    return None


def get(endpoint, session=requests):
    for attempt in range(1, 5):
        try:
            r = session.get(f"{BASE}/{endpoint}", timeout=60)
            if r.status_code == 200:
                return r.json().get("data", [])
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * attempt)
    raise RuntimeError(f"could not load {endpoint}")


def job_key(kind, level, state_id, district_id, commodity_id):
    return f"{kind}|{level}|{state_id}|{district_id}|{commodity_id}"


def build_jobs(districts_by_state, states=ICRISAT_STATES, state_crops=STATE_CROPS,
               district_crops=DISTRICT_CROPS):
    """Ordered list of (kind, level, state_id, district_id, commodity_id)."""
    jobs = []
    for c in state_crops:
        for s in states:
            jobs.append(("prices", "state", s, 0, c))
            jobs.append(("arrivals", "state", s, 0, c))
    for c in district_crops:
        for s in states:
            for d in districts_by_state.get(s, []):
                jobs.append(("prices", "district", s, d, c))
    return jobs


def to_rows(records, kind, level, state_id, district_id, commodity_id):
    """Flatten CEDA records into plain rows with the request ids attached."""
    out = []
    for r in records:
        row = {"level": level, "state_id": state_id, "district_id": district_id or "",
               "commodity_id": commodity_id, "commodity": r.get("cmdty", ""),
               "month": r.get("t", "")}
        for k, v in r.items():
            if k not in ("t", "cmdty", "state_id", "district_id", "state", "district"):
                row[k] = v
        row["state"] = r.get("state", "")
        row["district"] = r.get("district", "")
        out.append(row)
    return out


def _append_csv(path, rows, lock):
    import csv
    if not rows:
        return
    with lock:
        new = not path.exists()
        cols = list(rows[0].keys())
        if not new:
            with open(path, newline="") as f:
                cols = next(csv.reader(f))
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)


def _log(out, msg):
    with open(out / "log.txt", "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def _work(out, job, session, files_lock):
    kind, level, s, d, c = job
    body = {"state_id": s, "district_id": d, "commodity_id": c, "calculation_type": "m",
            "start_date": START, "end_date": END}
    data = post("prices" if kind == "prices" else "quantities", body, session=session)
    if data is None:
        return job, None
    rows = to_rows(data, kind, level, s, d, c)
    _append_csv(out / f"rows_{kind}.csv", rows, files_lock)
    return job, len(rows)


def _run(out, copy_to):
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    done_path = out / "done.jsonl"
    done = set()
    if done_path.exists():
        for line in done_path.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("n") is not None:
                done.add(rec["key"])
    districts = {}
    for s in ICRISAT_STATES:
        districts[s] = [x["census_district_id"] for x in get(f"districts?state_id={s}", session)]
    jobs = [j for j in build_jobs(districts) if job_key(*j) not in done]
    with _lock:
        _state.update(total=len(jobs) + len(done), done=len(done), running=True)
    _log(out, f"start: {len(jobs)} requests to go, {len(done)} already done")
    files_lock = threading.Lock()
    last_copy = time.time()
    with ThreadPoolExecutor(THREADS) as ex:
        futures = [ex.submit(_work, out, j, session, files_lock) for j in jobs]
        for f in as_completed(futures):
            job, n = f.result()
            with files_lock:
                with open(done_path, "a") as fh:
                    fh.write(json.dumps({"key": job_key(*job), "n": n}) + "\n")
            with _lock:
                _state["done"] += 1
                _state["phase"] = job[1]
                if n is None:
                    _state["failed"] += 1
                else:
                    _state["rows"] += n
                if _state["done"] % 200 == 0:
                    _log(out, f"{_state['done']}/{_state['total']} requests, "
                              f"{_state['rows']} rows, {_state['failed']} failed")
            if copy_to and time.time() - last_copy > 300:
                last_copy = time.time()
                copy_out(out, copy_to)
    if copy_to:
        copy_out(out, copy_to)
    _log(out, "finished")
    with _lock:
        _state["running"] = False


def copy_out(out, dest):
    """Copy results to dest (e.g. a Drive folder) if it exists."""
    import shutil
    dest = Path(dest)
    if not dest.parent.exists():
        return False
    dest.mkdir(exist_ok=True)
    for name in ("rows_prices.csv", "rows_arrivals.csv", "done.jsonl", "log.txt"):
        if (out / name).exists():
            shutil.copy(out / name, dest / name)
    return True


def run(out_dir="ceda_out", copy_to=None, background=False):
    out = Path(out_dir)
    if background:
        t = threading.Thread(target=_run, args=(out, copy_to), daemon=True)
        t.start()
        return t
    _run(out, copy_to)


def progress():
    with _lock:
        return dict(_state)


if __name__ == "__main__":
    run()
