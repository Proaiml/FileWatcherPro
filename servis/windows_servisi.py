"""FileWatcherPro Windows servisi (Adım 10; olay tablosu G4, M6).

Servis çekirdeği (calistir.py) ayrı bir süreç olarak çalıştırır ve bekçilik eder:
  * Çekirdek beklenmedik biçimde kapanırsa (çökme, öldürülme) artan beklemeyle (1, 2, 5, 10, 30 sn) yeniden
    başlatır. Eklentiler Job Object ile çekirdekle birlikte kapandığı için sahipsiz süreç kalmaz; durum diskten
    okunur (yarım kalan çağrılar kurtarılır, kapalıyken gelen dosyalar telafi taramasıyla yakalanır).
    Önyüzde 'Çekirdek beklenmedik biçimde kapandı' uyarı alarmı açılır (operatör onaylayana kadar görünür).
  * Çekirdek 10 dk kesintisiz çalışırsa bekleme sırası başa döner.
  * Çıkış kodu 3 ('bu veri klasörü için zaten çalışıyor', ör. baslat.bat ile konsolda açılmış kopya) çökme
    sayılmaz: 30 sn'de bir yeniden denenir, loga yazılır.
  * Servis durdurulunca ya da Windows kapanırken çekirdeğe KAPAN komutu gider (canli.db komut tablosu): gözetmen
    eklentileri düzgün kapatır; teslim bekleyen tetikleri 'kapanis_teslim_bekleme_sn' (varsayılan 15 sn) boyunca
    göndermeye devam eder, bitmeyenler veritabanında kalır ve açılışta gider (H10). Bu süre + pay içinde (en az
    45 sn) kapanmazsa sonlandırılır.
  * Servis sürecinin kendisi düşerse ikinci katman: Windows kurtarma ayarı (servis_kur.bat: 5/10/30 sn'de yeniden
    başlat).

Kurulum/kaldırma: servis_kur.bat / servis_kaldir.bat (yönetici olarak). Elle:
    py -3.11 servis\\windows_servisi.py --startup delayed install | remove | start | stop | restart
Servis kurmadan aynı bekçiyi bu pencerede denemek için (Ctrl+C ile düzgün kapanır):
    py -3.11 servis\\windows_servisi.py konsol [--baslangic yol.json]
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from loguru import logger  # noqa: E402

from cekirdek import loglama  # noqa: E402
from cekirdek.ayarlar import Ayarlar, baslangic_oku  # noqa: E402
from cekirdek.db_canli import CanliDB  # noqa: E402
from cekirdek.db_hata import HataDB  # noqa: E402
from cekirdek.model import AlarmSeviye  # noqa: E402

try:
    import servicemanager
    import win32service
    import win32serviceutil
except ImportError:                      # pywin32 yoksa yalnızca 'konsol' kipi çalışır
    win32serviceutil = None

SERVIS_ADI = "FileWatcherPro"
TEK_KOPYA_CIKIS_KODU = 3                  # calistir.py ile aynı
CREATE_NO_WINDOW = 0x08000000


class Bekci:
    """Çekirdek sürecini çalıştırır, beklenmedik kapanışta yeniden başlatır, durdurulunca düzgün kapatır."""

    def __init__(self, baslangic=None, python=None, plan=(1, 2, 5, 10, 30), stabil_sn=600.0,
                 tek_kopya_bekleme_sn=30.0, kapanma_sn=45.0, komut=None):
        self.baslangic = str(baslangic) if baslangic else None
        self.b = baslangic_oku(self.baslangic)
        self.python = python or sys.executable
        self.plan, self.stabil_sn = tuple(plan), stabil_sn
        self.tek_kopya_bekleme_sn, self.kapanma_sn = tek_kopya_bekleme_sn, kapanma_sn
        self._komut = komut                   # yalnızca testler: çekirdek yerine başka komut
        self.dur_olayi = threading.Event()
        self.proc = None
        self.yeniden_baslatma = 0
        self.ardisik = 0
        self.son_cikis_kodu = None

    def komut(self) -> list:
        if self._komut:
            return list(self._komut)
        k = [self.python, str(KOK / "calistir.py")]
        return k + ["--baslangic", self.baslangic] if self.baslangic else k

    # ------------------------------------------------------------ çalışma
    def calis(self):
        logger.info(f"servis bekçisi başladı: {' '.join(self.komut())}")
        try:
            while not self.dur_olayi.is_set():
                baslama = time.time()
                self.proc = subprocess.Popen(self.komut(), cwd=str(KOK), creationflags=CREATE_NO_WINDOW,
                                             env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                logger.info(f"çekirdek başlatıldı (pid {self.proc.pid})")
                while self.proc.poll() is None and not self.dur_olayi.wait(0.5):
                    pass
                if self.dur_olayi.is_set():
                    break
                kod = self.son_cikis_kodu = self.proc.returncode
                sure = time.time() - baslama
                if kod == TEK_KOPYA_CIKIS_KODU:
                    logger.warning(f"bu veri klasörü için FileWatcherPro zaten çalışıyor (konsolda açık bir kopya "
                                   f"olabilir); {self.tek_kopya_bekleme_sn:g} sn sonra yeniden denenecek")
                    if self.dur_olayi.wait(self.tek_kopya_bekleme_sn):
                        break
                    continue
                if sure >= self.stabil_sn:
                    self.ardisik = 0
                bekle = self.plan[min(self.ardisik, len(self.plan) - 1)]
                self.ardisik += 1
                self.yeniden_baslatma += 1
                logger.error(f"çekirdek beklenmedik biçimde kapandı (çıkış kodu {kod}, {sure:.0f} sn çalıştı); "
                             f"{bekle:g} sn sonra yeniden başlatılıyor ({self.yeniden_baslatma}. kez)")
                self._kaydet(kod, sure)
                if self.dur_olayi.wait(bekle):
                    break
        finally:
            self._kapat()
            logger.info("servis bekçisi durdu")

    def dur(self):
        self.dur_olayi.set()

    def kapanma_suresi(self) -> float:
        """KAPAN'dan sonra çekirdeğe tanınan süre: teslimin kapanışta bekleyen tetikleri gönderme süresi
        (kapanis_teslim_bekleme_sn) + çağrı zaman aşımı + gözetmen ve eklenti payları. En az kapanma_sn."""
        try:
            db = CanliDB(self.b.canli_db)
            ayar = Ayarlar(db)
            sure = float(ayar.al("kapanis_teslim_bekleme_sn")) + float(ayar.al("cagri_timeout_sn")) + 25.0
            db.kapat()
            return max(self.kapanma_sn, sure)
        except Exception:
            return self.kapanma_sn

    # ------------------------------------------------------------ yardımcılar
    def _kaydet(self, kod, sure):
        try:
            db = CanliDB(self.b.canli_db).sema_kur()     # çekirdek hiç açılamadan çökmüş olabilir
            db.alarm_ac("servis:cekirdek_dustu",
                        f"Çekirdek beklenmedik biçimde kapandı (çıkış kodu {kod}, {sure:.0f} sn çalışmıştı); servis "
                        f"yeniden başlattı (toplam {self.yeniden_baslatma} kez). Kayıp yok: durum diskten okunur. "
                        f"Sık tekrarlanıyorsa loglar klasöründeki cekirdek loguna bakın.", AlarmSeviye.UYARI, "servis")
            db.kapat()
            h = HataDB(self.b.hata_db).sema_kur()
            h.denetim_yaz("SERVIS_CEKIRDEK_YENIDEN", "cekirdek", eski={"cikis_kodu": kod, "sure_sn": round(sure)},
                          yeni={"yeniden_baslatma": self.yeniden_baslatma}, kullanici="servis", kaynak="servis")
            h.kapat()
        except Exception:
            logger.exception("çekirdek kapanışı kaydedilemedi (yeniden başlatma yine yapılacak)")

    def _kapat(self):
        p = self.proc
        if p is None or p.poll() is not None:
            return
        logger.info("çekirdeğe KAPAN komutu gönderiliyor (eklentiler düzgün kapanacak)")
        try:
            db = CanliDB(self.b.canli_db)
            db.komut_gonder("cekirdek", "KAPAN", kullanici="servis")
            db.kapat()
            p.wait(self.kapanma_suresi())
            logger.info(f"çekirdek düzgün kapandı (çıkış kodu {p.returncode})")
        except subprocess.TimeoutExpired:
            logger.error(f"çekirdek {self.kapanma_sn:g} sn içinde kapanmadı; sonlandırılıyor")
            p.kill()
            p.wait(10)
        except Exception:
            logger.exception("KAPAN gönderilemedi; çekirdek sonlandırılıyor")
            p.kill()
            p.wait(10)


def _loglama(baslangic=None, konsol=True):
    b = baslangic_oku(baslangic)
    ayar = Ayarlar(CanliDB(b.canli_db).sema_kur())
    loglama.kur("servis", b.loglar, ayar.al("log_saklama_gun"), ayar.al("log_azami_mb"), konsol=konsol)


if win32serviceutil is not None:
    class FileWatcherProServisi(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVIS_ADI
        _svc_display_name_ = "FileWatcherPro"
        _svc_description_ = ("FTP dizinlerine gelen dosyaları kayıpsız ve yanlış dosyaya tepki vermeden Control-M "
                             "tetiğine dönüştürür. Önyüz: http://127.0.0.1:8770")
        # python.exe servisi doğrudan barındırır (pythonservice.exe ve DLL kopyalama gerekmez)
        _exe_name_ = sys.executable
        _exe_args_ = f'"{Path(__file__).resolve()}"'

        def __init__(self, args):
            super().__init__(args)
            _loglama(konsol=False)
            self.bekci = Bekci()

        def SvcDoRun(self):
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_name_, ""))
            self.bekci.calis()
            logger.complete()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING,
                                     waitHint=int((self.bekci.kapanma_suresi() + 15) * 1000))
            self.bekci.dur()

        def SvcShutdown(self):                # Windows kapanıyor: aynı düzgün kapanış
            self.SvcStop()


def konsol(argv):
    import argparse
    import signal
    ap = argparse.ArgumentParser(description="Servis bekçisini bu pencerede çalıştırır (deneme)")
    ap.add_argument("--baslangic")
    a = ap.parse_args(argv)
    _loglama(a.baslangic)
    bekci = Bekci(a.baslangic)
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            signal.signal(sig, lambda *_: bekci.dur())
    t = threading.Thread(target=bekci.calis, name="bekci")
    t.start()
    while t.is_alive():
        t.join(0.5)
    logger.complete()
    return 0


def main(argv):
    if argv[1:2] == ["konsol"]:
        return konsol(argv[2:])
    if win32serviceutil is None:
        print("pywin32 kurulu değil: py -3.11 -m pip install pywin32")
        return 1
    if len(argv) == 1:                        # hizmet denetim yöneticisi (SCM) başlattı
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(FileWatcherProServisi)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    return win32serviceutil.HandleCommandLine(FileWatcherProServisi, argv=argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
