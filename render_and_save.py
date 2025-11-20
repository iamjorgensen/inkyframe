import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MAIN = ROOT / "main.py"
OUTPUT = ROOT / "output.png"

def run_render():
    print("Kjører main.py...")
    cmd = [sys.executable, str(MAIN), "--days", "7"]

    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print(proc.stdout)
        print(proc.stderr)
    except Exception as e:
        print("FEIL ved kjøring av main.py:", e)

    if OUTPUT.exists():
        print("Output generert:", OUTPUT)
    else:
        print("ADVARSEL: output.png ble ikke generert!")

if __name__ == "__main__":
    run_render()
