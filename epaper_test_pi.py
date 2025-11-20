#!/usr/bin/env python3
# epaper_test_pi.py - test for Waveshare 1.54" V2 on Raspberry Pi

from waveshare_epd import epd1in54_V2
from PIL import Image, ImageDraw, ImageFont
import time, requests, os
import os
os.environ.setdefault('GPIOZERO_PIN_FACTORY','rpigpio')

STATUS_URL = "http://127.0.0.1:8000/status"  # endre hvis du har server-endpoint

def get_status():
    try:
        r = requests.get(STATUS_URL, timeout=1)
        return r.json()
    except:
        return {"cpu":"-", "temp":"-", "requests":"-", "last_sync":"offline"}

def render_image(W, H, status):
    image = Image.new('1', (W, H), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
    except:
        font = ImageFont.load_default()

    draw.text((6, 6), "Pi Status", font=font, fill=0)
    draw.text((6, 28), f"CPU: {status.get('cpu','-')}", font=font, fill=0)
    draw.text((6, 46), f"Temp: {status.get('temp','-')} C", font=font, fill=0)
    draw.text((6, 64), f"Req: {status.get('requests','-')}", font=font, fill=0)
    draw.text((6, 82), f"Sync: {status.get('last_sync','-')}", font=font, fill=0)
    draw.text((6, 100), time.strftime("Time %H:%M:%S"), font=font, fill=0)
    draw.rectangle((0,0,W-1,H-1), outline=0)
    return image

def main():
    epd = epd1in54_V2.EPD()
    epd.init()
    # en gang Clear for å være sikker
    epd.Clear()
    W = epd.width
    H = epd.height

    try:
        while True:
            status = get_status()
            img = render_image(W, H, status)
            # waveshare expects epd.getbuffer(image)
            epd.display(epd.getbuffer(img))
            epd.sleep()
            time.sleep(30)  # juster frekvens etter behov
    except KeyboardInterrupt:
        print("Stopping and clearing display...")
        epd.init()
        epd.Clear()
        epd.sleep()

if __name__ == '__main__':
    main()
