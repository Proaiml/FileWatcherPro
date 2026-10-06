"""FileWatcherPro giriş noktası.

    py -3.11 calistir.py                       # config/baslangic.json ile
    py -3.11 calistir.py --baslangic yol.json  # başka bir başlangıç dosyasıyla (testler)

Başlangıç ayarlarını okur, loglamayı kurar, aynı veri klasörü için ikinci bir kopyanın çalışmasını
engeller (G7) ve gözetmeni başlatır. Ctrl+C / Ctrl+Break / servis durdurma isteğinde gözetmen
eklentileri düzgünce kapatır.
"""
import argparse
import hashlib
import signal
import sys

from loguru import logger

from cekirdek import loglama, win
from cekirdek.ayarlar import Ayarlar, baslangic_oku
from cekirdek.db_canli import CanliDB
from cekirdek.gozetmen import Gozetmen

TEK_KOPYA_CIKIS_KODU = 3


def mutex_adi(veri_yolu) -> str:
    ozet = hashlib.sha1(str(veri_yolu).casefold().encode("utf-8")).hexdigest()[:16]
    return f"FileWatcherPro_{ozet}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FileWatcherPro çekirdeği")
    ap.add_argument("--baslangic", help="başlangıç ayar dosyası (varsayılan: config/baslangic.json)")
    args = ap.parse_args(argv)

    b = baslangic_oku(args.baslangic)
    ayar = Ayarlar(CanliDB(b.canli_db).sema_kur())
    loglama.kur("cekirdek", b.loglar, ayar.al("log_saklama_gun"), ayar.al("log_azami_mb"))

    if not win.tek_kopya_kilidi(mutex_adi(b.veri)):
        logger.error(f"Bu veri klasörü için FileWatcherPro zaten çalışıyor: {b.veri}")
        loglama.olay("TEK_KOPYA_REDDI", veri=b.veri)
        logger.complete()
        return TEK_KOPYA_CIKIS_KODU

    g = Gozetmen(b)

    def durdur(signum, frame):
        logger.info(f"durdurma sinyali alındı ({signum})")
        g.dur()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            signal.signal(sig, durdur)
    try:
        g.calis()
    except KeyboardInterrupt:
        g.kapan()
    logger.complete()
    return 0


if __name__ == "__main__":
    sys.exit(main())
