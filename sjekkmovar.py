# movar_auth_debug.py
# Kjøre: python movar_auth_debug.py
from dotenv import load_dotenv
import os, requests, textwrap

load_dotenv()

BASE = os.getenv("MOVAR_BASE", "https://mdt-proxy.movar.no/api").rstrip("/")
TOKEN = os.getenv("MOVAR_API_TOKEN", "")
KOM = os.getenv("KOMMUNENR", "3103")
GATE = os.getenv("MOVAR_GATENAVN", "Dokkveien")
HUS = os.getenv("MOVAR_HUSNR", "19")

print("MOVAR_BASE:", BASE)
print("MOVAR_API_TOKEN present:", bool(TOKEN))
print("MOVAR_API_TOKEN repr:", repr(TOKEN))
print("MOVAR_API_TOKEN length:", len(TOKEN))
print("KOMMUNENR:", KOM)
print("GATE/HUS:", GATE, HUS)
print()

s = requests.Session()
s.headers.update({"Kommunenr": KOM})

def try_request(path, params=None, headers=None):
    url = BASE + path
    try:
        r = s.get(url, params=params, headers=headers or {}, timeout=15)
        body = r.text or ""
        preview = body if len(body) < 1500 else body[:1500] + "\n...[truncated]..."
        print(f"-> GET {r.url}")
        print(f"   Status: {r.status_code}")
        print("   Headers sent:", headers or {})
        print("   Body preview:")
        print(textwrap.indent(preview, "   "))
        print("-" * 70)
        return r
    except Exception as e:
        print("Exception:", e)
        return None

print("=== TEST 1: query param apitoken (som i din kode) ===")
try_request("/Fraksjoner", params={"apitoken": TOKEN})

print("=== TEST 2: query param token (alternate key) ===")
try_request("/Fraksjoner", params={"token": TOKEN})

print("=== TEST 3: header Authorization: Bearer ===")
try_request("/Fraksjoner", headers={"Kommunenr": KOM, "Authorization": "Bearer " + TOKEN})

print("=== TEST 4: header apitoken ===")
try_request("/Fraksjoner", headers={"Kommunenr": KOM, "apitoken": TOKEN})

print("=== TEST 5: no token (control) ===")
try_request("/Fraksjoner", headers={"Kommunenr": KOM})

print("\n=== NOW: same tests for /Tommekalender ===")
print("Note: using gatenavn/husnr as params like in your code.")
path = f"/Tommekalender?gatenavn={GATE}&husnr={HUS}"
print("=== QUERY apitoken ===")
try_request(path, params={"apitoken": TOKEN})
print("=== HEADER Authorization: Bearer ===")
try_request(path, headers={"Kommunenr": KOM, "Authorization": "Bearer " + TOKEN})
print("=== HEADER apitoken ===")
try_request(path, headers={"Kommunenr": KOM, "apitoken": TOKEN})
print("=== NO TOKEN ===")
try_request(path, headers={"Kommunenr": KOM})
