"""Ambient facts Aemyos works out on its own, quietly, while idle: where the PC is
(IP geolocation, city level — no Windows location permission is ever requested), the timezone, and
from that the weather. Cached in context.json and refreshed every few hours; the
lines go into the model's system prompt so it never has to ask "where are you?"."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

REFRESH_SEC = 6 * 3600
_LOCK = threading.Lock()
_CACHE = {"data": None, "loaded": False}
_bg_started = False


def _path():
    from services.paths import data_path
    return data_path("context.json")


def _load():
    if _CACHE["loaded"]:
        return _CACHE["data"]
    data = None
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = None
    _CACHE["data"] = data if isinstance(data, dict) else None
    _CACHE["loaded"] = True
    return _CACHE["data"]


def _save(data):
    _CACHE["data"] = data
    _CACHE["loaded"] = True
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _get_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "aemyos-desktop-agent"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ── Sources ──────────────────────────────────────────────────────

def _windows_location():
    """Precise position from Windows Location. OFF by default: asking for it can pop a
    privacy prompt, and city-level from the IP is enough. Opt in with DAVI_USE_WINDOWS_LOCATION=1."""
    if os.environ.get("DAVI_USE_WINDOWS_LOCATION", "0") != "1":
        return None
    try:
        import asyncio
        from winsdk.windows.devices.geolocation import Geolocator, GeolocationAccessStatus

        async def go():
            st = await Geolocator.request_access_async()
            if st != GeolocationAccessStatus.ALLOWED:
                return None
            g = Geolocator()
            p = await g.get_geoposition_async()
            c = p.coordinate.point.position
            return {"lat": round(c.latitude, 3), "lon": round(c.longitude, 3), "source": "windows"}
        return asyncio.run(go())
    except Exception:
        return None


def _ip_location():
    d = _get_json("http://ip-api.com/json/?fields=status,country,countryCode,regionName,city,lat,lon,timezone")
    if d.get("status") != "success":
        return None
    return {
        "city": d.get("city") or "", "region": d.get("regionName") or "", "country": d.get("country") or "",
        "cc": d.get("countryCode") or "", "lat": round(float(d["lat"]), 2), "lon": round(float(d["lon"]), 2),
        "tz": d.get("timezone") or "", "source": "ip",
    }


def _reverse(lat, lon):
    """City name for precise coordinates (Open-Meteo has no reverse; use BigDataCloud free endpoint)."""
    try:
        d = _get_json(f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en")
        return {"city": d.get("city") or d.get("locality") or "", "region": d.get("principalSubdivision") or "",
                "country": d.get("countryName") or "", "cc": d.get("countryCode") or ""}
    except Exception:
        return {}


def _geocode(name):
    """User said 'I live in Istanbul' → coordinates for that place."""
    try:
        d = _get_json("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name, "count": 1, "language": "en"}))
        res = (d.get("results") or [None])[0]
        if not res:
            return None
        return {"city": res.get("name") or name, "region": res.get("admin1") or "", "country": res.get("country") or "",
                "cc": res.get("country_code") or "", "lat": round(res["latitude"], 2), "lon": round(res["longitude"], 2),
                "tz": res.get("timezone") or "", "source": "user"}
    except Exception:
        return None


def _user_said_location():
    try:
        from services.personal import get_profile
        return (get_profile() or {}).get("location") or ""
    except Exception:
        return ""


# ── Refresh ──────────────────────────────────────────────────────

def refresh(force=False):
    """Work out location + timezone. Cheap when the cache is fresh."""
    with _LOCK:
        cur = _load()
        if cur and not force and time.time() - float(cur.get("ts", 0)) < REFRESH_SEC and cur.get("said") == _user_said_location():
            return cur
        loc = None
        said = _user_said_location()
        if said:
            loc = _geocode(said)
        if not loc:
            win = _windows_location()
            if win:
                loc = dict(win)
                loc.update(_reverse(win["lat"], win["lon"]))
        if not loc:
            try:
                loc = _ip_location()
            except Exception:
                loc = None
        if not loc:
            return cur
        if not loc.get("tz"):
            try:
                import tzlocal  # optional
                loc["tz"] = tzlocal.get_localzone_name()
            except Exception:
                loc["tz"] = (cur or {}).get("tz", "")
        loc["ts"] = time.time()
        loc["said"] = said
        _save(loc)
        print(f"[CONTEXT] location {label(loc)} via {loc.get('source')}")
        return loc


def start_background(delay=20):
    """Refresh once shortly after start and every REFRESH_SEC after; never blocks the UI."""
    global _bg_started
    if _bg_started:
        return
    _bg_started = True

    def loop():
        time.sleep(delay)
        while True:
            try:
                refresh()
            except Exception as e:
                print(f"[CONTEXT] refresh failed: {e}")
            time.sleep(REFRESH_SEC)
    threading.Thread(target=loop, daemon=True, name="context-facts").start()


# ── Accessors ────────────────────────────────────────────────────

def location():
    return _load()


def label(loc=None):
    loc = loc or _load()
    if not loc:
        return ""
    bits = [b for b in (loc.get("city"), loc.get("region"), loc.get("cc") or loc.get("country")) if b]
    return ", ".join(bits)


def prompt_lines():
    loc = _load()
    if not loc:
        return []
    src = {"ip": "from the IP address, city-level, may be a few km off",
           "windows": "from Windows location",
           "user": "the user told you"}.get(loc.get("source"), "approximate")
    line = f"User's location ({src}): {label(loc)}."
    if loc.get("tz"):
        line += f" Timezone: {loc['tz']}."
    line += " Use it for weather, time and local questions without asking; mention it is approximate only if precision matters."
    return [line]


# ── Weather (Open-Meteo, no key) ─────────────────────────────────

_WMO_EN = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
           51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
           61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
           71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers", 81: "showers",
           82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}
_WMO_TR = {0: "açık", 1: "az bulutlu", 2: "parçalı bulutlu", 3: "kapalı", 45: "sisli", 48: "sisli",
           51: "hafif çisenti", 53: "çisenti", 55: "yoğun çisenti", 56: "dondurucu çisenti", 57: "dondurucu çisenti",
           61: "hafif yağmur", 63: "yağmurlu", 65: "şiddetli yağmur", 66: "dondurucu yağmur", 67: "dondurucu yağmur",
           71: "hafif kar", 73: "karlı", 75: "yoğun kar", 77: "kar taneleri", 80: "sağanak", 81: "sağanak",
           82: "şiddetli sağanak", 85: "kar sağanağı", 86: "kar sağanağı", 95: "gök gürültülü fırtına", 96: "dolu ve fırtına", 99: "dolu ve fırtına"}


def weather(lang="en"):
    """One spoken line: 'The Bronx: 22° parçalı bulutlu · en yüksek 26° / en düşük 18°'."""
    loc = _load() or refresh()
    if not loc:
        return {"success": False, "error": "no location"}
    try:
        d = _get_json(
            "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
                "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto",
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 1,
            }), timeout=7)
    except Exception as e:
        return {"success": False, "error": str(e)}
    cur = d.get("current") or {}
    day = d.get("daily") or {}
    code = int(cur.get("weather_code") or 0)
    temp = cur.get("temperature_2m")
    hi = (day.get("temperature_2m_max") or [None])[0]
    lo = (day.get("temperature_2m_min") or [None])[0]
    rain = (day.get("precipitation_probability_max") or [None])[0]
    us = (loc.get("cc") or "").upper() == "US"

    def deg(c):
        if c is None:
            return "?"
        return f"{round(c * 9 / 5 + 32)}°F ({round(c)}°C)" if us else f"{round(c)}°"

    tr = (lang or "en").lower().startswith("tr")
    cond = (_WMO_TR if tr else _WMO_EN).get(code, "")
    city = loc.get("city") or label(loc)
    if tr:
        text = f"{city}: {deg(temp)} {cond} · en yüksek {deg(hi)} / en düşük {deg(lo)}"
        if rain is not None and rain >= 30:
            text += f" · yağış ihtimali %{int(rain)}"
    else:
        text = f"{city}: {deg(temp)} {cond} · high {deg(hi)} / low {deg(lo)}"
        if rain is not None and rain >= 30:
            text += f" · {int(rain)}% chance of rain"
    return {"success": True, "text": text, "code": code, "temp": temp}
