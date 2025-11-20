import subprocess
import os

INKSCAPE_PATH = r"C:\Users\a131001\Inkscape Portable\inkscapeportable.exe"

# Bruk nåværende mappe (der du kjører scriptet)
ICON_DIR = os.getcwd()  # Nåværende arbeidsmappe

for fn in os.listdir(ICON_DIR):
    if fn.lower().endswith(".svg"):
        svg_path = os.path.join(ICON_DIR, fn)
        png_path = os.path.join(ICON_DIR, os.path.splitext(fn)[0] + ".png")

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
        print(f"Laget: {png_path}")