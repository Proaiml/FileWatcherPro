"""Eklenti tabanı. Her eklenti ayrı bir süreçtir ve bu sınıftan türetilir.

Sözleşme:
  * `calis()` ana döngüdür; her turda `self.ilerle()` çağrılır ve `self.durmali()` kontrol edilir.
    Bekleme için `self.bekle(sn)` kullanılır (durdurma isteğinde hemen uyanır).
  * Arka plandaki nabız thread'i her `eklenti_nabiz_sn`'de canli.db > eklenti satırına
    son_nabiz (süreç yaşıyor) ve son_ilerleme (ana döngü en son ne zaman ilerledi) yazar.
    Ana döngü takılırsa son_ilerleme durur → gözetmen eklentiyi öldürüp yeniden başlatır.
  * Gözetmen durdurmak istediğinde satırdaki `istenen` alanını DUR yapar; eklenti düzgünce kapanır.
  * Çekirdek süreci ölürse (Job Object'e rağmen) eklenti bunu fark edip kendini kapatır.
  * Eklentiler birbirini çağırmaz; yalnızca veritabanları üzerinden konuşur.
"""
import os
import sys
import threading
import time
import traceback

from loguru import logger

from . import loglama, win
from .ayarlar import Ayarlar, baslangic_oku
from .db_canli import CanliDB
from .db_hata import HataDB
from .model import Istenen


class Eklenti:
    AD = "eklenti"

    def __init__(self):
        self.ad = os.environ.get("FWP_EKLENTI_AD") or self.AD
        self.b = baslangic_oku()
        self.db = CanliDB(self.b.canli_db).sema_kur()
        self.hdb = HataDB(self.b.hata_db).sema_kur()
        self.ayar = Ayarlar(self.db)
        self.ayar.tazele(zorla=True)
        loglama.kur(self.ad, self.b.loglar, self.ayar.al("log_saklama_gun"), self.ayar.al("log_azami_mb"),
                    konsol=False)
        self.cekirdek_pid = int(os.environ.get("FWP_CEKIRDEK_PID", "0") or 0)
        self._dur = threading.Event()
        self._son_ilerleme = time.time()
        self._nabiz = threading.Thread(target=self._nabiz_dongusu, name="nabiz", daemon=True)

    # ------------------------------------------------------------ alt sınıfın kullandıkları
    def calis(self):
        raise NotImplementedError

    def bilgi(self) -> dict:
        """Önyüzde gösterilecek kısa durum bilgisi (JSON'a çevrilebilir)."""
        return {}

    def ilerle(self):
        self._son_ilerleme = time.time()

    def durmali(self) -> bool:
        return self._dur.is_set()

    def bekle(self, sn: float) -> bool:
        """sn kadar bekler; durdurma istenirse hemen döner (True)."""
        return self._dur.wait(max(0.0, sn))

    def durdur(self):
        self._dur.set()

    # ------------------------------------------------------------ nabız
    def _nabiz_dongusu(self):
        while True:
            try:
                satir = self.db.eklenti(self.ad)
                if satir is not None and satir["istenen"] == Istenen.DUR and not self._dur.is_set():
                    logger.info("gözetmen durdurma istedi")
                    self._dur.set()
                if self.cekirdek_pid and not win.surec_canli(self.cekirdek_pid):
                    logger.warning("çekirdek süreci yok; eklenti kapanıyor")
                    os._exit(4)
                try:
                    bilgi = self.bilgi()
                except Exception as e:  # bilgi() hatası nabzı durdurmasın
                    bilgi = {"bilgi_hatasi": str(e)}
                self.db.eklenti_guncelle(self.ad, son_nabiz=time.time(), son_ilerleme=self._son_ilerleme,
                                         pid=os.getpid(), bilgi=bilgi)
            except Exception as e:
                logger.warning(f"nabız yazılamadı: {e}")
            try:
                aralik = float(self.ayar.al("eklenti_nabiz_sn"))
            except Exception:
                aralik = 1.0
            time.sleep(aralik)

    # ------------------------------------------------------------ yaşam döngüsü
    def kapanis(self):
        """Alt sınıf kaynaklarını bırakmak için geçersiz kılabilir."""

    @classmethod
    def baslat(cls):
        e = cls()
        logger.info(f"{e.ad} eklentisi başladı (pid={os.getpid()})")
        loglama.olay("EKLENTI_BASLADI", ad=e.ad, pid=os.getpid())
        e._nabiz.start()
        kod = 0
        try:
            e.calis()
        except Exception as hata:
            kod = 1
            logger.exception("eklenti beklenmeyen hatayla düştü")
            try:
                e.db.eklenti_guncelle(e.ad, son_hata=f"{type(hata).__name__}: {hata}"[:500])
            except Exception:
                pass
            traceback.print_exc()
        finally:
            try:
                e.kapanis()
            except Exception:
                logger.exception("kapanışta hata")
            loglama.olay("EKLENTI_KAPANDI", ad=e.ad, kod=kod)
            logger.complete()
        sys.exit(kod)
