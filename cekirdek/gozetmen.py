"""Gözetmen — çekirdeğin kalbi. Her zaman ayakta kalır.

Görevleri:
  * baslangic.json'daki eklentileri ayrı süreç olarak başlatmak (Job Object'e bağlı).
  * Düşen eklentiyi bekleme planına göre (1, 2, 5, 10, 30 sn) yeniden başlatmak; art arda
    'eklenti_dusme_limiti' kez düşerse ELLE_MUDAHALE durumuna alıp KRİTİK alarm vermek (M5).
  * Ana döngüsü 'eklenti_yanitsiz_sn' boyunca ilerlemeyen (takılan) eklentiyi öldürüp
    yeniden başlatmak (M3 — örn. ağ paylaşımında asılı kalan tarama).
  * Önyüzden gelen komutları işlemek: BASLAT / DURDUR / YENIDEN_BASLAT (eklenti bazında).
  * Kullanıcının durdurduğu eklenti çekirdek yeniden başlasa da durdurulmuş kalır.
  * Kendi nabzını 'cekirdek' satırına yazmak; geçmiş budamasını düzenli yapmak.

Gözetmenin kendi hatası döngüyü durdurmaz: her tur try/except içindedir.
"""
import os
import subprocess
import sys
import threading
import time

from loguru import logger

from . import loglama
from .ayarlar import Ayarlar, Baslangic
from .bakim import Bakim
from .db_canli import CanliDB
from .db_hata import HataDB
from .model import AlarmSeviye, EklentiDurum, Istenen
from .win import IsNesnesi

CREATE_NO_WINDOW = 0x08000000
KAPANMA_PAYI_SN = 8.0      # eklentinin kendi kapanışı için sabit pay; teslim boşaltma süresi bunun üstüne eklenir
BUDAMA_ARALIGI_SN = 60.0


class _Surec:
    def __init__(self, ad: str, modul: str):
        self.ad = ad
        self.modul = modul
        self.proc = None
        self.baslama = 0.0
        self.durum = EklentiDurum.BASLIYOR
        self.hedef = Istenen.CALIS          # kullanıcının/gözetmenin istediği son durum
        self.durduruluyor = False
        self.durdurma_baslangici = 0.0
        self.ardisik_dusme = 0
        self.yeniden_baslatma = 0
        self.sonraki_baslatma = 0.0
        self.yanitsiz_mesaji = None


class Gozetmen:
    def __init__(self, b: Baslangic):
        self.b = b
        self.db = CanliDB(b.canli_db).sema_kur()
        self.hdb = HataDB(b.hata_db).sema_kur()
        self.ayar = Ayarlar(self.db)
        self.ayar.tazele(zorla=True)
        self._dur = threading.Event()
        self._son_budama = 0.0
        self.bakim = Bakim(self.db, self.hdb, self.ayar)
        self.db.meta_yaz("bakim_suruyor", "")          # önceki çalışmada yarıda kalan bakımın izi kalmasın
        self._bakim_thread = None
        try:
            self.is_nesnesi = IsNesnesi()
        except OSError as e:
            logger.warning(f"Job Object kurulamadı, eklentilerin çekirdek kontrolüne güvenilecek: {e}")
            self.is_nesnesi = None
        self.surecler = {}
        for e in b.eklentiler:
            s = _Surec(e["ad"], e["modul"])
            onceki = self.db.eklenti(s.ad)
            if onceki is not None and onceki["durum"] == EklentiDurum.DURDURULDU:
                s.hedef = Istenen.DUR          # kullanıcı durdurmuştu: öyle kalsın
                s.durum = EklentiDurum.DURDURULDU
            self.surecler[s.ad] = s
            self.db.eklenti_kaydet(s.ad, s.modul, durum=s.durum, istenen=s.hedef, pid=None,
                                   ardisik_dusme=0, sonraki_baslatma=None)
        self.db.eklenti_kaydet("cekirdek", "cekirdek.gozetmen", durum=EklentiDurum.CALISIYOR,
                               istenen=Istenen.CALIS, pid=os.getpid(), baslama=time.time())

    # ------------------------------------------------------------ ana döngü
    def calis(self):
        logger.info(f"gözetmen başladı (pid={os.getpid()}, eklentiler: {', '.join(self.surecler)})")
        loglama.olay("CEKIRDEK_BASLADI", pid=os.getpid())
        self.hdb.denetim_yaz("CEKIRDEK_BASLADI", "cekirdek", yeni={"pid": os.getpid()})
        while not self._dur.is_set():
            try:
                self.tur()
            except Exception:
                logger.exception("gözetmen turunda hata (döngü devam ediyor)")
            self._dur.wait(0.5)
        self.kapan()

    def dur(self):
        self._dur.set()

    def tur(self):
        self.ayar.tazele()
        self._komutlari_isle()
        simdi = time.time()
        for s in self.surecler.values():
            try:
                self._denetle(s, simdi)
            except Exception:
                logger.exception(f"{s.ad} denetlenirken hata")
        self.db.eklenti_guncelle("cekirdek", son_nabiz=simdi, son_ilerleme=simdi,
                                 durum=EklentiDurum.CALISIYOR, pid=os.getpid())
        if simdi - self._son_budama > BUDAMA_ARALIGI_SN:
            self._son_budama = simdi
            self._buda()
            try:
                if self.bakim.zamani_geldi_mi(simdi):
                    self._bakim_baslat("zamanlayıcı")
            except Exception:
                logger.exception("bakım zamanı hesaplanamadı")

    def _bakim_baslat(self, kullanici: str) -> bool:
        if self._bakim_thread is not None and self._bakim_thread.is_alive():
            return False
        self._bakim_thread = threading.Thread(target=self.bakim.calistir, args=(kullanici,), name="bakim",
                                              daemon=True)
        self._bakim_thread.start()
        return True

    # ------------------------------------------------------------ eklenti denetimi
    def _denetle(self, s: _Surec, simdi: float):
        if s.proc is not None:
            kod = s.proc.poll()
            if kod is not None:
                self._cikti(s, kod, simdi)
            else:
                self._calisani_denetle(s, simdi)
        if s.proc is None and not s.durduruluyor and s.hedef == Istenen.CALIS \
                and s.durum != EklentiDurum.ELLE_MUDAHALE and simdi >= s.sonraki_baslatma:
            self._baslat(s)

    def kapanma_payi(self) -> float:
        """Durdurulan eklentiye zorla sonlandırmadan önce tanınan süre: teslim eklentisi bekleyen tetikleri bu sürede
        göndermeye devam eder (kapanis_teslim_bekleme_sn) ve yoldaki son çağrının bitmesi beklenir."""
        try:
            return (KAPANMA_PAYI_SN + float(self.ayar.al("kapanis_teslim_bekleme_sn"))
                    + float(self.ayar.al("cagri_timeout_sn")))
        except Exception:
            return KAPANMA_PAYI_SN

    def _calisani_denetle(self, s: _Surec, simdi: float):
        if s.durduruluyor:
            pay = self.kapanma_payi()
            if simdi - s.durdurma_baslangici > pay:
                logger.warning(f"{s.ad} {pay:g} sn içinde kapanmadı; zorla sonlandırılıyor")
                s.proc.kill()
            return
        satir = self.db.eklenti(s.ad)
        if satir is None:
            return
        nabiz, ilerleme = satir["son_nabiz"], satir["son_ilerleme"]
        taze_nabiz = nabiz is not None and nabiz >= s.baslama
        if taze_nabiz and s.durum == EklentiDurum.BASLIYOR:
            s.durum = EklentiDurum.CALISIYOR
            self.db.eklenti_guncelle(s.ad, durum=s.durum)
            logger.info(f"{s.ad} çalışıyor (pid={s.proc.pid})")
        if simdi - s.baslama < float(self.ayar.al("eklenti_baslama_payi_sn")):
            return
        yanitsiz = float(self.ayar.al("eklenti_yanitsiz_sn"))
        if not taze_nabiz:
            s.yanitsiz_mesaji = "başladıktan sonra hiç nabız yazmadı"
        elif ilerleme is None or simdi - ilerleme > yanitsiz:
            s.yanitsiz_mesaji = f"ana döngü {simdi - (ilerleme or s.baslama):.0f} sn ilerlemedi (takıldı)"
        elif simdi - nabiz > yanitsiz:
            s.yanitsiz_mesaji = f"{simdi - nabiz:.0f} sn nabız yok"
        else:
            if (s.ardisik_dusme and simdi - s.baslama > float(self.ayar.al("eklenti_stabil_sn"))):
                s.ardisik_dusme = 0
                self.db.eklenti_guncelle(s.ad, ardisik_dusme=0)
                self.db.alarm_kapat(f"eklenti:{s.ad}:dustu")
            return
        logger.error(f"{s.ad} yanıtsız: {s.yanitsiz_mesaji}; sonlandırılıyor")
        loglama.olay("EKLENTI_YANITSIZ", ad=s.ad, pid=s.proc.pid, neden=s.yanitsiz_mesaji)
        s.proc.kill()

    def _cikti(self, s: _Surec, kod: int, simdi: float):
        pid = s.proc.pid
        s.proc = None
        if s.durduruluyor:
            s.durduruluyor = False
            loglama.olay("EKLENTI_DURDU", ad=s.ad, pid=pid, kod=kod)
            if s.hedef == Istenen.CALIS:           # yeniden başlatma isteği
                s.durum = EklentiDurum.BASLIYOR
                s.sonraki_baslatma = 0.0
            else:
                s.durum = EklentiDurum.DURDURULDU
                self.db.eklenti_guncelle(s.ad, durum=s.durum, pid=None, son_cikis_kodu=kod)
            return
        # beklenmeyen çıkış = düşme
        satir = self.db.eklenti(s.ad)
        neden = s.yanitsiz_mesaji or (satir["son_hata"] if satir and satir["son_hata"] else None) \
            or f"çıkış kodu {kod}"
        s.yanitsiz_mesaji = None
        if simdi - s.baslama >= float(self.ayar.al("eklenti_stabil_sn")):
            s.ardisik_dusme = 0
        s.ardisik_dusme += 1
        s.yeniden_baslatma += 1
        limit = int(self.ayar.al("eklenti_dusme_limiti"))
        loglama.olay("EKLENTI_DUSTU", ad=s.ad, pid=pid, kod=kod, ardisik=s.ardisik_dusme, neden=neden)
        if s.ardisik_dusme >= limit:
            s.durum = EklentiDurum.ELLE_MUDAHALE
            mesaj = (f"'{s.ad}' eklentisi art arda {s.ardisik_dusme} kez düştü; otomatik yeniden başlatma "
                     f"durduruldu. Son neden: {neden}. Önyüzden 'Başlat' ile yeniden deneyin.")
            logger.critical(mesaj)
            self.db.alarm_kapat(f"eklenti:{s.ad}:dustu")
            self.db.alarm_ac(f"eklenti:{s.ad}:elle", mesaj, AlarmSeviye.KRITIK, "gozetmen")
            self.db.eklenti_guncelle(s.ad, durum=s.durum, pid=None, son_cikis_kodu=kod, son_hata=neden,
                                     ardisik_dusme=s.ardisik_dusme, yeniden_baslatma=s.yeniden_baslatma,
                                     sonraki_baslatma=None)
            return
        plan = self.ayar.plan("eklenti_bekleme_plani") or [1.0]
        bekleme = plan[min(s.ardisik_dusme - 1, len(plan) - 1)]
        s.sonraki_baslatma = simdi + bekleme
        s.durum = EklentiDurum.DUSTU
        logger.error(f"{s.ad} düştü ({neden}); {bekleme:g} sn sonra yeniden başlatılacak "
                     f"({s.ardisik_dusme}/{limit})")
        self.db.alarm_ac(f"eklenti:{s.ad}:dustu",
                         f"'{s.ad}' eklentisi düştü ({neden}); otomatik yeniden başlatılıyor "
                         f"({s.ardisik_dusme}/{limit}).", AlarmSeviye.UYARI, "gozetmen")
        self.db.eklenti_guncelle(s.ad, durum=s.durum, pid=None, son_cikis_kodu=kod, son_hata=neden,
                                 ardisik_dusme=s.ardisik_dusme, yeniden_baslatma=s.yeniden_baslatma,
                                 sonraki_baslatma=s.sonraki_baslatma)

    def _baslat(self, s: _Surec):
        env = dict(os.environ)
        env.update({
            "FWP_BASLANGIC": str(self.b.dosya),
            "FWP_EKLENTI_AD": s.ad,
            "FWP_CEKIRDEK_PID": str(os.getpid()),
            "PYTHONPATH": os.pathsep.join(p for p in (str(self.b.kok), env.get("PYTHONPATH", "")) if p),
            "PYTHONIOENCODING": "utf-8",
        })
        konsol = open(self.b.loglar / f"{s.ad}_konsol.log", "ab")
        try:
            s.proc = subprocess.Popen([sys.executable, "-m", s.modul], cwd=str(self.b.kok), env=env,
                                      stdin=subprocess.DEVNULL, stdout=konsol, stderr=subprocess.STDOUT,
                                      creationflags=CREATE_NO_WINDOW)
        finally:
            konsol.close()
        if self.is_nesnesi is not None and not self.is_nesnesi.ekle(s.proc):
            logger.warning(f"{s.ad} Job Object'e eklenemedi")
        s.baslama = time.time()
        s.durum = EklentiDurum.BASLIYOR
        self.db.eklenti_guncelle(s.ad, durum=s.durum, istenen=Istenen.CALIS, pid=s.proc.pid, baslama=s.baslama,
                                 son_nabiz=None, son_ilerleme=None, sonraki_baslatma=None,
                                 yeniden_baslatma=s.yeniden_baslatma)
        loglama.olay("EKLENTI_BASLATILDI", ad=s.ad, pid=s.proc.pid)

    def _durdur(self, s: _Surec, yeniden: bool):
        s.hedef = Istenen.CALIS if yeniden else Istenen.DUR
        if s.proc is None:
            if yeniden:
                s.durum = EklentiDurum.BASLIYOR
                s.sonraki_baslatma = 0.0
            else:
                s.durum = EklentiDurum.DURDURULDU
                self.db.eklenti_guncelle(s.ad, durum=s.durum, istenen=Istenen.DUR, pid=None)
            return
        s.durduruluyor = True
        s.durdurma_baslangici = time.time()
        s.durum = EklentiDurum.DURDURULUYOR
        self.db.eklenti_guncelle(s.ad, durum=s.durum, istenen=Istenen.DUR)

    # ------------------------------------------------------------ komutlar
    def _komutlari_isle(self):
        for k in self.db.komutlari_al("cekirdek"):
            # KAPAN yalnızca servis sarmalayıcısı ve testler içindir; önyüz çekirdeği kapatamaz
            if k["komut"] == "KAPAN":
                self.db.komut_bitir(k["id"], "kapanıyor")
                self.hdb.denetim_yaz("CEKIRDEK_KAPAN_KOMUTU", "cekirdek", kullanici=k["kullanici"] or "sistem")
                self.dur()
            elif k["komut"] == "BAKIM_YAP":
                baslatildi = self._bakim_baslat(k["kullanici"] or "sistem")
                self.db.komut_bitir(k["id"], "bakım başlatıldı" if baslatildi else "bakım zaten sürüyor",
                                    durum="ISLENDI" if baslatildi else "HATA")
            else:
                self.db.komut_bitir(k["id"], f"bilinmeyen komut: {k['komut']}", durum="HATA")
        for k in self.db.komutlari_al("gozetmen"):
            try:
                sonuc = self._komut(k["komut"], k["parametre"], k["kullanici"] or "sistem")
                self.db.komut_bitir(k["id"], sonuc)
            except Exception as e:
                logger.exception(f"komut işlenemedi: {k['komut']}")
                self.db.komut_bitir(k["id"], str(e), durum="HATA")

    def _komut(self, komut: str, parametre: str, kullanici: str) -> str:
        import json
        p = json.loads(parametre or "{}")
        ad = p.get("ad")
        s = self.surecler.get(ad)
        if s is None:
            raise ValueError(f"bilinmeyen eklenti: {ad}")
        eski = s.durum
        if komut == "BASLAT":
            s.ardisik_dusme = 0
            s.sonraki_baslatma = 0.0
            s.hedef = Istenen.CALIS
            if s.proc is None and not s.durduruluyor:
                s.durum = EklentiDurum.BASLIYOR
                self._baslat(s)
            self.db.alarm_kapat(f"eklenti:{ad}:elle", kullanici)
            self.db.alarm_kapat(f"eklenti:{ad}:dustu", kullanici)
            self.db.eklenti_guncelle(ad, ardisik_dusme=0)
        elif komut == "DURDUR":
            self._durdur(s, yeniden=False)
        elif komut == "YENIDEN_BASLAT":
            s.ardisik_dusme = 0
            self.db.alarm_kapat(f"eklenti:{ad}:elle", kullanici)
            self.db.alarm_kapat(f"eklenti:{ad}:dustu", kullanici)
            self.db.eklenti_guncelle(ad, ardisik_dusme=0)
            if s.durum == EklentiDurum.ELLE_MUDAHALE:
                s.durum = EklentiDurum.BASLIYOR
            self._durdur(s, yeniden=True)
        else:
            raise ValueError(f"bilinmeyen komut: {komut}")
        self.hdb.denetim_yaz(f"EKLENTI_{komut}", ad, eski={"durum": eski}, yeni={"durum": s.durum},
                             kullanici=kullanici, kaynak="gozetmen")
        loglama.olay("EKLENTI_KOMUTU", komut=komut, ad=ad, kullanici=kullanici)
        return f"{ad}: {eski} → {s.durum}"

    # ------------------------------------------------------------ bakım işleri
    def _buda(self):
        try:
            self.db.gecmisi_buda(int(self.ayar.al("gecmis_limit")))
            r = self.hdb.buda(int(self.ayar.al("hata_limit")), int(self.ayar.al("denetim_limit")))
            if r["sinir_asildi"]:
                self.db.alarm_ac("hata_db:sinir", f"Çözülmemiş gönderilemeyen kayıt sayısı ({r['cozulmemis']}) "
                                 f"sınırı ({self.ayar.al('hata_limit')}) aştı; hiçbiri silinmedi.",
                                 AlarmSeviye.KRITIK, "gozetmen")
            else:
                self.db.alarm_kapat("hata_db:sinir")
        except Exception:
            logger.exception("budama hatası")

    # ------------------------------------------------------------ kapanış
    def kapan(self):
        logger.info("gözetmen kapanıyor; eklentiler durduruluyor")
        simdi = time.time()
        for s in self.surecler.values():
            if s.proc is not None and not s.durduruluyor:
                s.durduruluyor = True
                s.durdurma_baslangici = simdi
                self.db.eklenti_guncelle(s.ad, durum=EklentiDurum.DURDURULUYOR, istenen=Istenen.DUR)
        son = time.time() + self.kapanma_payi()
        while time.time() < son and any(s.proc and s.proc.poll() is None for s in self.surecler.values()):
            time.sleep(0.2)
        for s in self.surecler.values():
            if s.proc and s.proc.poll() is None:
                s.proc.kill()
            if s.proc:
                s.proc.wait(5)
                s.proc = None
            # kullanıcının durdurduğu eklenti DURDURULDU kalır; diğerleri açılışta yeniden başlar
            son_durum = EklentiDurum.DURDURULDU if s.hedef == Istenen.DUR else EklentiDurum.KAPANDI
            self.db.eklenti_guncelle(s.ad, durum=son_durum, pid=None)
        self.db.eklenti_guncelle("cekirdek", durum=EklentiDurum.KAPANDI, pid=None)
        self.hdb.denetim_yaz("CEKIRDEK_KAPANDI", "cekirdek")
        loglama.olay("CEKIRDEK_KAPANDI")
