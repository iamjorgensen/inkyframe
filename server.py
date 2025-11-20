from flask import Flask, send_file, abort, jsonify
from pathlib import Path
import subprocess

app = Flask(__name__)
ROOT = Path(__file__).parent
IMG = ROOT / "output.jpg"   # sørg for at dette matcher hva main.py lager

@app.get("/")
def home():
    return "WeekCalendar Server OK - GET /image for PNG"

@app.get("/image")
def image():
    if not IMG.exists():
        abort(404, "No image found")
    return send_file(str(IMG), mimetype="image/jpeg")

# Trigger main.py via systemd service (non-blocking)
@app.post("/run-main")
def run_main():
    # bruker sudo systemctl, derfor må sudoers settes opp for dette kommandoet
    subprocess.run(["sudo", "systemctl", "start", "weekcalendar-main.service"])
    return jsonify({"status": "started"}), 202

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

