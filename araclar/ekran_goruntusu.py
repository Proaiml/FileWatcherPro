"""Önyüz prototipinin ekran görüntülerini Edge başsız moduyla alır (tasarım onayı için).

    py -3.11 araclar\\ekran_goruntusu.py            # önyüzü 8790'da sunar, tasarim\\*.png üretir

Yalnızca prototip modunu (örnek veri) kullanır; gerçek sisteme bağlanmaz.
"""
import functools
import subprocess
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
ONYUZ = KOK / "eklentiler" / "kontrol" / "onyuz"
CIKTI = KOK / "tasarim"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

GORUNTULER = [
    ("01_genel_bakis_acik", "serit=0#/genel"),
    ("02_genel_bakis_kriz_koyu", "serit=0&tema=koyu&senaryo=kriz#/genel"),
    ("03_gonderimi_durdur_penceresi", "serit=0&pencere=kayitsiz#/genel"),
    ("04_lokal_kayit_kriz", "serit=0&senaryo=kriz#/lokal"),
    ("05_kademeli_erit_penceresi", "serit=0&senaryo=kriz&pencere=erit#/lokal"),
    ("06_dosya_ayrintisi", "serit=0&pencere=dosya#/dosyalar"),
    ("07_kural_ekle_regex_deneme", "serit=0&pencere=kural#/dizinler"),
    ("08_hedefler_kriz_koyu", "serit=0&tema=koyu&senaryo=kriz#/hedefler"),
    ("09_eklentiler", "serit=0#/eklentiler"),
    ("10_ayarlar", "serit=0#/ayarlar"),
]


def main():
    CIKTI.mkdir(exist_ok=True)
    isleyici = functools.partial(SimpleHTTPRequestHandler, directory=str(ONYUZ))
    isleyici.log_message = lambda *a: None
    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), isleyici)
    port = sunucu.server_address[1]
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    for ad, parametre in GORUNTULER:
        with tempfile.TemporaryDirectory() as profil:
            hedef = CIKTI / f"{ad}.png"
            url = f"http://127.0.0.1:{port}/index.html?prototip&{parametre}"
            subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={profil}", "--window-size=1440,900", "--force-device-scale-factor=1",
                            "--virtual-time-budget=6000", f"--screenshot={hedef}", url],
                           capture_output=True, timeout=120)
            print(("✓ " if hedef.exists() else "✗ ") + str(hedef))
    sunucu.shutdown()


if __name__ == "__main__":
    sys.exit(main())
