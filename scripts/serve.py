"""A small web service for the irrigation advice (Python standard library only).

    python scripts/serve.py              (http://localhost:8000)
    python scripts/serve.py --port 8080

Endpoints (all return JSON):
    GET  /health
    GET  /crops                          crops, seasons and PAU sowing windows
    GET  /districts                      districts set up, with state and zone
    GET  /soil-types                     soil types a farmer can choose
    GET  /advice?district=Hisar&sowing=2026-11-10&watered=2026-12-01,2027-01-10
                &crop=wheat&lat=29.2&lon=75.6&soil_type=loam&today=2026-12-20
    POST /advice                         the same fields as a JSON body (watered as a list)

The answer has "advice" (status, dates, soil numbers, confidence), "text_en" and "text_hi". One
service can feed the Android app, a chat channel and a test web page. It is for local testing and
a pilot: there is no login, no rate limit and no HTTPS here; put it behind a proper server before
it is public.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import advisor, service, sites  # noqa: E402
from cropadvisor import crops as cr  # noqa: E402

FIELDS = ("district", "sowing", "crop", "lat", "lon", "soil_type", "today", "depth_cm")


def crops_list():
    out = [{"key": "wheat", "name": "Wheat", "name_hi": "गेहूं", "season": "rabi (winter)",
            "regions": "27 districts in 10 states", "confidence": "normal"}]
    for k, s in cr.CROPS.items():
        (m1, d1), (m2, d2) = s.sowing_window
        out.append({"key": k, "name": s.en, "name_hi": s.hi, "season": s.season_en,
                    "sowing_window": [f"{m1:02d}-{d1:02d}", f"{m2:02d}-{d2:02d}"],
                    "regions": "Punjab and Haryana", "confidence": s.confidence})
    return out


def parse_query(qs):
    q = {k: v[0] for k, v in parse_qs(qs).items()}
    req = {k: q[k] for k in FIELDS if k in q and q[k] != ""}
    if q.get("watered"):
        req["watered"] = [d for d in q["watered"].split(",") if d]
    for k in ("lat", "lon", "depth_cm"):
        if k in req:
            req[k] = float(req[k])
    return req


class Handler(BaseHTTPRequestHandler):
    advise = staticmethod(service.advise_request)

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"ok": True})
        if u.path == "/crops":
            return self._send(200, crops_list())
        if u.path == "/districts":
            loc = pd.read_csv(sites.LOCATIONS)
            return self._send(200, loc[["name", "state", "zone"]].to_dict("records"))
        if u.path == "/soil-types":
            return self._send(200, [{"key": k, "en": v["en"], "hi": v["hi"],
                                     "fao_class": v["fao_class"], "awc_mm_per_m": list(v["range"])}
                                    for k, v in advisor.SOIL_TYPES.items()])
        if u.path == "/advice":
            try:
                req = parse_query(u.query)
            except ValueError as e:
                return self._send(400, {"ok": False, "error": f"bad input ({e})"})
            res = self.advise(req)
            return self._send(200 if res["ok"] else 422, res)
        return self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/advice":
            return self._send(404, {"ok": False, "error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("body must be a JSON object")
        except ValueError as e:
            return self._send(400, {"ok": False, "error": f"bad JSON ({e})"})
        res = self.advise(req)
        return self._send(200 if res["ok"] else 422, res)

    def log_message(self, fmt, *args):   # one short line per request
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Crop Advisor service on http://{a.host}:{a.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
