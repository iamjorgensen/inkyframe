# render_traffic_map.py
# Requires: pip install requests pillow
import os
import math
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ----------------- CONFIG -----------------
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or "AIzaSyAirKggTlZhPcxmxHf3wcNBAGBRqoO_Bxo"
ORIGIN = (59.437763437626515, 10.643026496779576)   # your house (lat, lon)
# DESTINATION can be a text address or a (lat, lon) tuple. Example: "Kransen, Moss" or (59.445, 10.65)
DESTINATION = "Kransen, Moss"
ZOOM = 16              # tune zoom for desired visible area
WIDTH, HEIGHT = 800, 480 # change to Inky resolution
TILE_URL = "https://cartodb-basemaps-a.global.ssl.fastly.net/rastertiles/voyager/{z}/{x}/{y}.png"
ATTRIBUTION = "© OpenStreetMap contributors, © Wikimedia Maps"
OUTFILE = "traffic_output.png"
TRICOLOR = True          # True => allow red, False => map to b/w (red -> black)
# ------------------------------------------

if GOOGLE_API_KEY is None or GOOGLE_API_KEY.strip() == "":
    raise SystemExit("Set GOOGLE_API_KEY environment variable or paste key in script.")

# ---------- polyline decoder (Google/OSM polyline) ----------
def decode_polyline(polyline_str):
    # returns list of (lat, lon)
    index, lat, lng = 0, 0, 0
    coordinates = []
    length = len(polyline_str)
    while index < length:
        shift, result = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift, result = 0, 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append((lat / 1e5, lng / 1e5))
    return coordinates

# ---------- mercator / tile math ----------
def latlon_to_tilexy(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = (lon + 180.0) / 360.0 * n
    ytile = (1.0 - math.log(math.tan(lat_rad) + (1/math.cos(lat_rad))) / math.pi) / 2.0 * n
    return xtile, ytile

def tilexy_to_pixels(xtile, ytile, tile_size=256):
    return xtile * tile_size, ytile * tile_size

# ---------- tile fetching & stitching ----------
def get_tile(z, x, y):
    url = TILE_URL.format(z=z, x=int(x), y=int(y))
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGBA")

def stitch_tiles(center_lat, center_lon, zoom, width, height):
    tile_size = 256
    xtile_f, ytile_f = latlon_to_tilexy(center_lat, center_lon, zoom)
    center_px, center_py = tilexy_to_pixels(xtile_f, ytile_f, tile_size=tile_size)
    top_left_px = center_px - (width / 2)
    top_left_py = center_py - (height / 2)

    left_tile = int(math.floor(top_left_px / tile_size))
    top_tile = int(math.floor(top_left_py / tile_size))
    right_tile = int(math.floor((top_left_px + width) / tile_size))
    bottom_tile = int(math.floor((top_left_py + height) / tile_size))

    cols = right_tile - left_tile + 1
    rows = bottom_tile - top_tile + 1
    canvas = Image.new("RGBA", (cols * tile_size, rows * tile_size))

    for tx in range(left_tile, right_tile + 1):
        for ty in range(top_tile, bottom_tile + 1):
            try:
                tile_img = get_tile(zoom, tx, ty)
            except Exception:
                tile_img = Image.new("RGBA", (tile_size, tile_size), (240,240,240,255))
            px = (tx - left_tile) * tile_size
            py = (ty - top_tile) * tile_size
            canvas.paste(tile_img, (px, py))

    offset_x = int(top_left_px - (left_tile * tile_size))
    offset_y = int(top_left_py - (top_tile * tile_size))
    cropped = canvas.crop((offset_x, offset_y, offset_x + width, offset_y + height))
    return cropped, (top_left_px, top_left_py)

def latlon_to_pixel_on_image(lat, lon, zoom, top_left_px, top_left_py, tile_size=256):
    xtile_f, ytile_f = latlon_to_tilexy(lat, lon, zoom)
    px, py = tilexy_to_pixels(xtile_f, ytile_f, tile_size=tile_size)
    return px - top_left_px, py - top_left_py

# ---------- Google Directions fetch ----------
def fetch_directions(origin, destination, api_key):
    if isinstance(origin, tuple):
        origin_str = f"{origin[0]},{origin[1]}"
    else:
        origin_str = origin
    if isinstance(destination, tuple):
        dest_str = f"{destination[0]},{destination[1]}"
    else:
        dest_str = destination
    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin_str,
        "destination": dest_str,
        "key": api_key,
        "departure_time": "now",  # get traffic-aware durations
        "mode": "driving",
        "alternatives": "false"
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    doc = r.json()
    if doc.get("status") != "OK":
        raise RuntimeError("Directions API error: " + str(doc.get("status")) + " - " + str(doc.get("error_message")))
    return doc

# ---------- color mapping ----------
def ratio_to_color(ratio, tricolor=True):
    # ratio = duration_in_traffic / duration (>=1)
    if ratio >= 1.5:
        return (255,0,0,255) if tricolor else (0,0,0,255)
    if ratio >= 1.2:
        return (255,140,0,255) if tricolor else (0,0,0,255)
    return (0,160,0,255) if tricolor else (0,0,0,255)

# ---------- drawing ----------
def draw_route_on_image(img, directions_doc, zoom, top_left_px, top_left_py, stroke_base=3, tricolor=True):
    draw = ImageDraw.Draw(img)
    route = directions_doc["routes"][0]
    # Use legs -> steps, each step has polyline and duration/duration_in_traffic sometimes
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            poly = step.get("polyline", {}).get("points")
            if not poly:
                continue
            points = decode_polyline(poly)  # list of (lat, lon)
            # Determine the ratio if available
            dur = step.get("duration", {}).get("value") or step.get("duration_in_traffic", {}).get("value") or 1
            dur_traffic = step.get("duration_in_traffic", {}).get("value") or step.get("duration", {}).get("value") or dur
            ratio = float(dur_traffic) / float(dur if dur>0 else 1)
            color = ratio_to_color(ratio, tricolor=tricolor)
            # Convert to pixel list
            px_pts = []
            for lat, lon in points:
                x,y = latlon_to_pixel_on_image(lat, lon, zoom, top_left_px, top_left_py)
                px_pts.append((x,y))
            # stroke width scaled by ratio for visibility
            width = int(stroke_base * (1.0 + (ratio-1.0)*3.0))
            if width < 2:
                width = 2
            draw.line(px_pts, fill=color, width=width, joint="curve")
    return img

# ---------- convert to Inky palette (simple) ----------
def to_inky_palette(img, tricolor=True):
    img = img.convert("RGBA")
    w,h = img.size
    src = img.load()
    out = Image.new("RGB", (w,h), (255,255,255))
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r,g,b,a = src[x,y]
            if a < 128:
                out_px[x,y] = (255,255,255)
                continue
            # red detection
            if tricolor and r > 150 and g < 120 and b < 120:
                out_px[x,y] = (255,0,0)
                continue
            # otherwise b/w threshold
            lum = 0.299*r + 0.587*g + 0.114*b
            out_px[x,y] = (0,0,0) if lum < 180 else (255,255,255)
    return out

def add_attribution(img, text):
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 12)
    except:
        font = ImageFont.load_default()

    # textbbox returns (left, top, right, bottom)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    w, h = img.size
    margin = 4

    # background rectangle for readability
    draw.rectangle(
        (margin, h - th - margin - 2, margin + tw + 6, h - margin),
        fill=(255, 255, 255)
    )
    draw.text(
        (margin + 3, h - th - margin - 1),
        text,
        fill=(0, 0, 0),
        font=font
    )
    return img

# ----------------- MAIN -----------------
def main():
    # 1) fetch directions
    print("Fetching directions from Google...")
    directions = fetch_directions(ORIGIN, DESTINATION, GOOGLE_API_KEY)

    # 2) determine center lat/lon for map: use origin or compute route midpoint
    route = directions["routes"][0]
    # choose center as midpoint of first leg's midpoint if available
    try:
        leg = route["legs"][0]
        center_lat = (float(ORIGIN[0]) + float(leg["end_location"]["lat"]))/2.0
        center_lon = (float(ORIGIN[1]) + float(leg["end_location"]["lng"]))/2.0
    except Exception:
        center_lat, center_lon = ORIGIN

    # 3) stitch OSM tiles
    print("Stitching base tiles...")
    base_img, (top_left_px, top_left_py) = stitch_tiles(center_lat, center_lon, ZOOM, WIDTH, HEIGHT)

    # 4) draw the route with per-step colors
    print("Drawing route with traffic colors...")
    composite = draw_route_on_image(base_img.copy(), directions, ZOOM, top_left_px, top_left_py, stroke_base=3, tricolor=TRICOLOR)

    # 5) mark origin (your house) and destination
    draw = ImageDraw.Draw(composite)
    ox, oy = latlon_to_pixel_on_image(ORIGIN[0], ORIGIN[1], ZOOM, top_left_px, top_left_py)
    # origin marker
    r = max(6, int(WIDTH * 0.012))
    draw.ellipse((ox-r, oy-r, ox+r, oy+r), fill=(30,144,255,255), outline=(0,0,0,255))
    # destination: use route end location if available
    try:
        end = route["legs"][-1]["end_location"]
        dx, dy = latlon_to_pixel_on_image(float(end["lat"]), float(end["lng"]), ZOOM, top_left_px, top_left_py)
        rr = r
        draw.ellipse((dx-rr, dy-rr, dx+rr, dy+rr), fill=(200,30,30,255), outline=(0,0,0,255))
    except Exception:
        pass

    # 6) convert to Inky palette
    print("Converting to Inky palette...")
    inky_img = to_inky_palette(composite, tricolor=TRICOLOR)

    # 7) attribution & save
    inky_img = add_attribution(inky_img, ATTRIBUTION)
    inky_img.save(OUTFILE)
    print("Saved", OUTFILE)

if __name__ == "__main__":
    main()
