import subprocess
import os
INKSCAPE_PATH = r"C:\Program Files\Inkscape\bin\inkscape.exe"

# Bruker nåværende mappe (der scriptet kjører)
ICON_DIR = os.getcwd()

for fn in os.listdir(ICON_DIR):
    if fn.lower().endswith(".svg"):
        svg_path = os.path.join(ICON_DIR, fn)
        png_path = os.path.join(ICON_DIR, os.path.splitext(fn)[0] + ".png")

        # 🚀 Sjekk om PNG finnes fra før
        if os.path.exists(png_path):
            print(f"⏩ Hopper over (eksisterer allerede): {png_path}")
            continue

        # Kommando for konvertering
        cmd = [
            INKSCAPE_PATH,
            "--export-type=png",
            "--export-width=20",
            "--export-height=20",
            f"--export-filename={png_path}",
            svg_path
        ]

        print(f"Konverterer: {svg_path} → {png_path}")
        subprocess.run(cmd, check=True)
        print(f"✔️ Laget: {png_path}")
