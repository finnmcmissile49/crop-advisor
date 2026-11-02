"""Crop greenness (NDVI) at the field from Sentinel-2, as background beside the advice.

Source: Sentinel-2 Level-2A surface reflectance (ESA Copernicus), searched and read through the
Microsoft Planetary Computer STAC API (free, no account; files are read with a short-lived
access token from its SAS endpoint). One scene every ~5 days, 10 m pixels, often cloudy in
kharif.

What is computed, per scene:
- a 3 x 3 window of 10 m pixels (30 m x 30 m) around the field point, red (B04) and near-infrared
  (B08);
- the scene classification (SCL, 20 m) decides whether the point is clear: the centre pixel and
  at least 6 of the 3 x 3 SCL pixels must be vegetation (4) or bare soil (5); anything else
  (cloud, shadow, cirrus, water, no data) skips the scene;
- reflectance = (DN - 1000) / 10000 for processing baseline 04.00 and later (scenes from
  25 Jan 2022), DN / 10000 before;
- NDVI = (NIR - red) / (NIR + red), averaged over the window.

Limits (stated in the output): NDVI is only greenness, not yield or water stress on its own; a
30 m window can include a neighbour's field or a bund on a small plot; it is not calibrated against
this project's fields and it does not change the watering date.
"""
import datetime as dt

import requests

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-2-l2a"
COLLECTION = "sentinel-2-l2a"
CLEAR_SCL = {4, 5}           # vegetation, bare soil
MIN_CLEAR = 6                # of the 9 SCL pixels around the point
MAX_SCENE_CLOUD = 80         # scene-level cloud %, only to skip hopeless scenes early
BASELINE_OFFSET_FROM = 4.0   # processing baseline from which DN carry a +1000 offset
LOOKBACK_DAYS = 45
TIMEOUT = 60

_token = {"value": None, "expires": None}


def search(lat, lon, start, end, post=None):
    """Scenes covering the point, newest first: [{id, date, cloud, baseline, red, nir, scl}]."""
    post = post or (lambda url, body: _post(url, body))
    body = {"collections": [COLLECTION],
            "intersects": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "datetime": f"{start:%Y-%m-%d}T00:00:00Z/{end:%Y-%m-%d}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
            "sortby": [{"field": "datetime", "direction": "desc"}], "limit": 50}
    items = post(STAC, body).get("features", [])
    out = []
    for it in items:
        p, a = it.get("properties", {}), it.get("assets", {})
        if not all(k in a for k in ("B04", "B08", "SCL")):
            continue
        try:
            baseline = float(p.get("s2:processing_baseline", "0"))
        except ValueError:
            baseline = 0.0
        out.append({"id": it.get("id"), "date": p.get("datetime", "")[:10],
                    "cloud": p.get("eo:cloud_cover"), "baseline": baseline,
                    "red": a["B04"]["href"], "nir": a["B08"]["href"], "scl": a["SCL"]["href"]})
    out.sort(key=lambda s: s["date"], reverse=True)
    return out


def _post(url, body):
    r = requests.post(url, json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def sign(href, get=None):
    """Add the Planetary Computer access token to a file link (token reused until it expires)."""
    now = dt.datetime.now(dt.timezone.utc)
    if _token["value"] is None or _token["expires"] is None or now >= _token["expires"]:
        get = get or (lambda url: _get(url))
        j = get(SAS)
        _token["value"] = j["token"]
        exp = j.get("msft:expiry")
        try:
            _token["expires"] = dt.datetime.fromisoformat(exp.replace("Z", "+00:00")) - \
                dt.timedelta(minutes=5)
        except (AttributeError, ValueError):
            _token["expires"] = now + dt.timedelta(minutes=30)
    return f"{href}?{_token['value']}"


def _get(url):
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def read_window(href, lat, lon, size=3):
    """size x size pixel values around the point (rasterio; reads only that window over HTTP)."""
    import rasterio
    from rasterio.warp import transform
    from rasterio.windows import Window
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
        with rasterio.open(href) as src:
            xs, ys = transform("EPSG:4326", src.crs, [float(lon)], [float(lat)])
            row, col = src.index(xs[0], ys[0])
            half = size // 2
            if not (half <= row < src.height - half and half <= col < src.width - half):
                return None
            return src.read(1, window=Window(col - half, row - half, size, size))


def scene_ndvi(scene, lat, lon, reader=None, signer=None):
    """{"date", "ndvi", "clear_pixels"} for a clear scene, or {"date", "skipped": reason}."""
    reader = reader or read_window
    signer = signer or sign
    scl = reader(signer(scene["scl"]), lat, lon)
    if scl is None:
        return {"date": scene["date"], "skipped": "edge of the scene"}
    scl_vals = [int(v) for v in scl.ravel()]
    centre = scl_vals[len(scl_vals) // 2]
    n_clear = sum(v in CLEAR_SCL for v in scl_vals)
    if centre not in CLEAR_SCL or n_clear < MIN_CLEAR:
        return {"date": scene["date"], "skipped": "cloud or shadow over the field"}
    red = reader(signer(scene["red"]), lat, lon)
    nir = reader(signer(scene["nir"]), lat, lon)
    if red is None or nir is None:
        return {"date": scene["date"], "skipped": "edge of the scene"}
    off = 1000.0 if scene.get("baseline", 0) >= BASELINE_OFFSET_FROM else 0.0
    vals = []
    for r, n in zip(red.ravel(), nir.ravel()):
        r, n = (float(r) - off) / 10000.0, (float(n) - off) / 10000.0
        if r <= 0 or n <= 0 or r + n == 0:   # no data or saturated
            continue
        vals.append((n - r) / (n + r))
    if len(vals) < 5:
        return {"date": scene["date"], "skipped": "too few valid pixels"}
    return {"date": scene["date"], "ndvi": round(sum(vals) / len(vals), 2),
            "clear_pixels": n_clear}


def field_ndvi(lat, lon, today, days=LOOKBACK_DAYS, post=None, reader=None, signer=None,
               max_clear=2):
    """The latest clear NDVI at the field and the one before it, over the last `days` days.
    {"latest", "previous", "change", "scenes", "clear", "skipped", "source"}."""
    end = today.date() if hasattr(today, "date") else today
    start = end - dt.timedelta(days=days)
    scenes = search(lat, lon, start, end, post=post)
    clear, skipped, seen = [], 0, set()
    for s in scenes:
        if s["date"] in seen:      # same day, overlapping tile: one is enough
            continue
        r = scene_ndvi(s, lat, lon, reader=reader, signer=signer)
        if "ndvi" in r:
            clear.append(r)
            seen.add(s["date"])
            if len(clear) >= max_clear:
                break
        else:
            skipped += 1
    out = {"scenes": len(scenes), "clear": len(clear), "skipped": skipped, "days": days,
           "latest": clear[0] if clear else None, "previous": clear[1] if len(clear) > 1 else None,
           "change": None, "source": "Sentinel-2 L2A via Microsoft Planetary Computer"}
    if out["previous"]:
        out["change"] = round(out["latest"]["ndvi"] - out["previous"]["ndvi"], 2)
    return out


def _d(s):
    return dt.date.fromisoformat(s).strftime("%d %b").lstrip("0")


def text(res):
    """English and Hindi lines."""
    if not res:
        return [], []
    if res.get("error"):
        return (["Satellite crop greenness (Sentinel-2): could not be reached this time."],
                ["उपग्रह से फ़सल की हरियाली (Sentinel-2): इस बार डेटा नहीं मिल सका।"])
    if not res.get("latest"):
        return ([f"Satellite crop greenness (Sentinel-2): no clear view of your field in the last "
                 f"{res['days']} days (cloud)."],
                [f"उपग्रह से फ़सल की हरियाली (Sentinel-2): पिछले {res['days']} दिनों में बादलों के "
                 "कारण आपका खेत साफ़ नहीं दिखा।"])
    lt, pv = res["latest"], res.get("previous")
    en = f"Satellite crop greenness (Sentinel-2 NDVI, 30 m around your field point): " \
         f"{lt['ndvi']:.2f} on {_d(lt['date'])}"
    hi = f"उपग्रह से फ़सल की हरियाली (Sentinel-2 NDVI, खेत के बिंदु के आसपास 30 मीटर): " \
         f"{_d(lt['date'])} को {lt['ndvi']:.2f}"
    if pv:
        word_en = "up from" if res["change"] > 0.02 else "down from" if res["change"] < -0.02 \
            else "about the same as"
        word_hi = "बढ़ी" if res["change"] > 0.02 else "घटी" if res["change"] < -0.02 \
            else "लगभग वैसी ही"
        en += f", {word_en} {pv['ndvi']:.2f} on {_d(pv['date'])}"
        hi += f" ({_d(pv['date'])} को {pv['ndvi']:.2f}; हरियाली {word_hi})"
    en += ". Greenness only; it does not change the date. A sudden drop is worth a look at the field."
    hi += "। यह केवल हरियाली है, इससे तारीख़ नहीं बदलती। अचानक गिरावट दिखे तो खेत देख लें।"
    return [en], [hi]
