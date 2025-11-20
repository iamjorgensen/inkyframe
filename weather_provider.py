# weather_provider.py
# Henter og slår sammen MET (api.met.no) og Open-Meteo.
# Returnerer JSON-serialiserbart dict med 'daily' og 'hourly_today'.
#
# Requires: requests
# pip install requests

import requests
from datetime import datetime, timedelta, timezone
import math

# Default config (kan overskrives ved kall)
DEFAULT_LAT = 59.4376
DEFAULT_LON = 10.6432
DEFAULT_DAYS = 14
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
OM_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_USER_AGENT = "InkyFrameCalendar/1.0 (contact: youremail@example.com)"

# Simple mappings
MET_SYMBOL_MAP = {
    "clearsky": "Klart", "clearsky_day": "Klart", "clearsky_night": "Klart",
    "fair_day": "Sol", "fair_night": "Klart",
    "partlycloudy_day": "Delvis skyet", "partlycloudy_night": "Delvis skyet",
    "cloudy": "Skyet",
    "rain": "Regn", "lightrain": "Lett regn", "lightrainshowers": "Lette regnbyger", "heavyrain": "Kraftig regn",
    "snow": "Snø", "heavysnow": "Kraftig snø", "sleet": "Sludd",
    "fog": "Tåke", "hail": "Hagl", "thunderstorm": "Torden"
}
OM_WEATHERCODE_MAP = {
    0: "Klart", 1: "Delvis skyet", 2: "Delvis skyet", 3: "Skyet",
    45: "Tåke", 48: "Tåke", 51: "Lett regn", 53: "Moderate regn", 55: "Tett regn",
    56: "Lett sludd", 57: "Tett sludd", 61: "Regn", 63: "Moderate regn", 65: "Kraftig regn",
    66: "Lett sludd", 67: "Tett sludd", 71: "Snø", 73: "Moderate snø", 75: "Kraftig snø",
    77: "Snøkrystaller", 80: "Regnbyger", 81: "Regnbyger", 82: "Kraftige byger",
    85: "Snøbyger", 86: "Kraftige snøbyger", 95: "Torden", 96: "Torden med hagl", 99: "Torden med kraftig hagl"
}

# --- helper functions ------------------------------------------------------
def _to_local(dt_utc):
    """Convert aware UTC datetime to local system timezone (or keep tz-aware)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone()  # system local tz (usually Europe/Oslo on your machine)

def _day_key_06_to_06(dt_local):
    """Return 'YYYY-MM-DD' day key using 06:00..05:59 definition."""
    if dt_local.hour < 6:
        day = (dt_local.date() - timedelta(days=1))
    else:
        day = dt_local.date()
    return day.strftime("%Y-%m-%d")

def _deg_to_cardinal(deg):
    if deg is None:
        return None
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    ix = int((deg % 360) / 22.5 + 0.5) % 16
    return dirs[ix]

# ---------------- parse MET timeseries -------------------------------------
def _parse_met_timeseries_json(j):
    out = {}
    hourly_today = []  # detailed hour-for-hour for current day (06-06 grouping we will slice later)
    props = j.get("properties", {})
    timeseries = props.get("timeseries", [])
    for t in timeseries:
        time_str = t.get("time")
        if not time_str:
            continue
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except Exception:
            continue
        dt_local = _to_local(dt)
        day_key = _day_key_06_to_06(dt_local)

        # init day dict
        day = out.setdefault(day_key, {
            "temp_max": None, "temp_min": None, "precip": 0.0,
            "wind_max": None, "wind_dirs": [], "symbols": []
        })

        data = t.get("data", {})
        instant = data.get("instant", {}).get("details", {})

        # temperature
        inst_temp = instant.get("air_temperature")
        if inst_temp is not None:
            try:
                tval = float(inst_temp)
                if day["temp_max"] is None or tval > day["temp_max"]:
                    day["temp_max"] = tval
                if day["temp_min"] is None or tval < day["temp_min"]:
                    day["temp_min"] = tval
            except Exception:
                pass

        # wind
        wind_sp = instant.get("wind_speed")
        wind_dir = instant.get("wind_from_direction")
        if wind_sp is not None:
            try:
                wsp = float(wind_sp)
                if day["wind_max"] is None or wsp > day["wind_max"]:
                    day["wind_max"] = wsp
            except Exception:
                pass
        if wind_dir is not None:
            try:
                day["wind_dirs"].append(float(wind_dir))
            except Exception:
                pass

        # precipitation from period details
        for period in ("next_1_hours", "next_6_hours", "next_12_hours"):
            p = data.get(period)
            if p and isinstance(p, dict):
                details = p.get("details", {})
                p_amt = details.get("precipitation_amount")
                if p_amt is not None:
                    try:
                        day["precip"] += float(p_amt)
                    except Exception:
                        pass

        # symbol
        symbol = None
        if "next_6_hours" in data and data["next_6_hours"] and "summary" in data["next_6_hours"]:
            symbol = data["next_6_hours"]["summary"].get("symbol_code")
        if not symbol:
            for period in ("next_1_hours", "next_12_hours"):
                if period in data and data[period] and "summary" in data[period]:
                    symbol = data[period]["summary"].get("symbol_code")
                    if symbol:
                        break
        if symbol:
            day["symbols"].append(symbol)

        # capture hourly detail for current-day view (we store local-time hour, temp, precip_period, wind)
        hourly_detail = {
            "time": dt_local.isoformat(),
            "temp": instant.get("air_temperature"),
            "wind_speed": instant.get("wind_speed"),
            "wind_dir": instant.get("wind_from_direction"),
            "precip_next_1h": None
        }
        # attempt to fill precipit next_1_hours
        if "next_1_hours" in data and data["next_1_hours"] and "details" in data["next_1_hours"]:
            hourly_detail["precip_next_1h"] = data["next_1_hours"]["details"].get("precipitation_amount")
        hourly_today.append(hourly_detail)

    # finalize daily entries: compute symbol (most common) and dominant wind dir
    for k, v in out.items():
        v["symbol"] = None
        if v.get("symbols"):
            v["symbol"] = max(set(v["symbols"]), key=v["symbols"].count)
        # wind dir mean
        if v.get("wind_dirs"):
            sin_sum = sum(math.sin(math.radians(d)) for d in v["wind_dirs"])
            cos_sum = sum(math.cos(math.radians(d)) for d in v["wind_dirs"])
            mean_angle = math.degrees(math.atan2(sin_sum / len(v["wind_dirs"]), cos_sum / len(v["wind_dirs"])))
            mean_angle = (mean_angle + 360) % 360
            v["wind_dir_deg"] = round(mean_angle, 1)
        else:
            v["wind_dir_deg"] = None
        v["precip"] = round(v.get("precip", 0.0), 2)
        # cleanup
        v.pop("symbols", None)
        v.pop("wind_dirs", None)
    # sort hourly_today by time
    hourly_today.sort(key=lambda x: x["time"])
    return out, hourly_today

# ---------------- fetch MET & OM ------------------------------------------------
def _fetch_met(lat, lon, user_agent=DEFAULT_USER_AGENT, timeout=20):
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    params = {"lat": str(lat), "lon": str(lon)}
    r = requests.get(MET_URL, headers=headers, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"MET HTTP {r.status_code}: {r.text[:400]}")
    j = r.json()
    return _parse_met_timeseries_json(j)

def _fetch_open_meteo(lat, lon, days, timeout=15):
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode,windspeed_10m_max,winddirection_10m_dominant",
        "forecast_days": days,
        "timezone": "auto"
    }
    r = requests.get(OM_URL, params=params, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"OpenMeteo HTTP {r.status_code}: {r.text[:400]}")
    j = r.json()
    out = {}
    daily = j.get("daily", {})
    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    wcode = daily.get("weathercode", [])
    wmax = daily.get("windspeed_10m_max", [])
    wdir = daily.get("winddirection_10m_dominant", [])
    for i, d in enumerate(dates):
        out[d] = {
            "temp_max": float(tmax[i]) if i < len(tmax) and tmax[i] is not None else None,
            "temp_min": float(tmin[i]) if i < len(tmin) and tmin[i] is not None else None,
            "precip": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
            "symbol": int(wcode[i]) if i < len(wcode) and wcode[i] is not None else None,
            "wind_max": float(wmax[i]) if i < len(wmax) and wmax[i] is not None else None,
            "wind_dir_deg": float(wdir[i]) if i < len(wdir) and wdir[i] is not None else None,
            "source": "OpenMeteo"
        }
    return out

# ---------------- merge & return JSON -----------------------------------------
def get_forecast_json(lat=DEFAULT_LAT, lon=DEFAULT_LON, days=DEFAULT_DAYS, user_agent=DEFAULT_USER_AGENT, keep_debug_hourly=False):
    """
    Return dict:
      { 'daily': [ {date, temp_max, temp_min, precip, symbol, wind_max, wind_dir_deg, source}, ... ],
        'hourly_today': [ {time, temp, wind_speed, wind_dir, precip_next_1h}, ... ],
        'meta': { 'met_days': n, 'om_days': n }
      }
    """
    result = {"daily": [], "hourly_today": [], "meta": {}}
    met_dict = {}
    hourly_today = []
    om_dict = {}
    # try MET
    try:
        met_dict, hourly_today = _fetch_met(lat, lon, user_agent=user_agent)
    except Exception as e:
        met_dict = {}
        hourly_today = []
        result["meta"]["met_error"] = str(e)
    # try Open-Meteo
    try:
        om_dict = _fetch_open_meteo(lat, lon, days)
    except Exception as e:
        om_dict = {}
        result["meta"]["om_error"] = str(e)

    # build merged daily list for requested days (today..today+days-1)
    today = datetime.now().date()
    for i in range(days):
        d = today + timedelta(days=i)
        ks = d.strftime("%Y-%m-%d")
        m = met_dict.get(ks)
        o = om_dict.get(ks)
        entry = {"date": ks, "temp_max": None, "temp_min": None, "precip": None,
                 "symbol": None, "wind_max": None, "wind_dir_deg": None, "source": "none"}
        if m:
            entry.update({
                "temp_max": m.get("temp_max"),
                "temp_min": m.get("temp_min"),
                "precip": m.get("precip"),
                "symbol": m.get("symbol"),
                "wind_max": m.get("wind_max"),
                "wind_dir_deg": m.get("wind_dir_deg"),
                "source": "MET"
            })
        if o:
            if entry["temp_max"] is None:
                entry["temp_max"] = o.get("temp_max")
            if entry["temp_min"] is None:
                entry["temp_min"] = o.get("temp_min")
            if entry["precip"] is None or entry["precip"] == 0:
                entry["precip"] = o.get("precip")
            if entry["symbol"] is None:
                # map Open-Meteo weathercode to label
                entry["symbol"] = OM_WEATHERCODE_MAP.get(o.get("symbol"))
            if entry["wind_max"] is None:
                entry["wind_max"] = o.get("wind_max")
            if entry["wind_dir_deg"] is None:
                entry["wind_dir_deg"] = o.get("wind_dir_deg")
            if entry["source"] == "none":
                entry["source"] = "OpenMeteo"
        # normalize MET symbol to human label if string
        sym = entry.get("symbol")
        if isinstance(sym, str):
            label = MET_SYMBOL_MAP.get(sym)
            if not label and "_" in sym:
                base = sym.split("_")[0]
                label = MET_SYMBOL_MAP.get(base)
            entry["symbol"] = label if label else sym
        # rounding
        try:
            if entry["precip"] is not None:
                entry["precip"] = round(float(entry["precip"]), 2)
        except Exception:
            pass
        try:
            if entry["temp_max"] is not None:
                entry["temp_max"] = round(float(entry["temp_max"]), 1)
            if entry["temp_min"] is not None:
                entry["temp_min"] = round(float(entry["temp_min"]), 1)
            if entry["wind_max"] is not None:
                entry["wind_max"] = round(float(entry["wind_max"]), 1)
        except Exception:
            pass

        result["daily"].append(entry)

    # hourly_today: filter hourly_today list to entries that belong to today (06-06 rule)
    if hourly_today:
        filtered = []
        for h in hourly_today:
            try:
                dt = datetime.fromisoformat(h["time"])
            except Exception:
                continue
            dt_local = _to_local = dt.astimezone()
            day_key = _day_key_06_to_06(dt_local)
            if day_key == today.strftime("%Y-%m-%d"):
                filtered.append(h)
        # optionally trim/convert values to simple types
        result["hourly_today"] = filtered if keep_debug_hourly else filtered

    result["meta"]["met_days"] = len(met_dict)
    result["meta"]["om_days"] = len(om_dict)
    result["meta"]["generated_at"] = datetime.now().isoformat()
    result["meta"]["lat"] = lat
    result["meta"]["lon"] = lon
    return result

# ---------------- debug print (same stil som tidligere) -----------------------
def debug_print(forecast_json):
    daily = forecast_json.get("daily", [])
    print("="*100)
    print(f"Forecast debug (days={len(daily)}) lat={forecast_json['meta'].get('lat')} lon={forecast_json['meta'].get('lon')}")
    print("="*100)
    for e in daily:
        wind_dir_card = _deg_to_cardinal(e.get("wind_dir_deg")) if e.get("wind_dir_deg") is not None else "-"
        sym = e.get("symbol") or "-"
        tmin = f"{e.get('temp_min')}°C" if e.get("temp_min") is not None else "-"
        tmax = f"{e.get('temp_max')}°C" if e.get("temp_max") is not None else "-"
        precip = f"{e.get('precip')} mm" if e.get("precip") is not None else "-"
        wind = f"{e.get('wind_max')} m/s {wind_dir_card}" if e.get('wind_max') is not None else "-"
        print(f"{e['date']:10s} | {sym:20s} | Tmin {tmin:8s} | Tmax {tmax:8s} | Nedbør {precip:10s} | Vind {wind:18s} | source={e.get('source')}")
    print("="*100)
    # hourly debug
    if forecast_json.get("hourly_today"):
        print("\nDetaljert time-for-time (i dag):")
        for h in forecast_json["hourly_today"][:24]:
            time_str = h.get("time")
            temp = h.get("temp")
            p = h.get("precip_next_1h")
            ws = h.get("wind_speed")
            wd = h.get("wind_dir")
            print(f" {time_str} | temp={temp}C | precip_next_1h={p} | wind={ws} m/s dir={wd}")
    print("="*100)

# ---------------- convenience small test ------------------------------
if __name__ == "__main__":
    print("Test run of weather_provider.get_forecast_json()")
    res = get_forecast_json()
    #debug_print(res)
    print(res)
