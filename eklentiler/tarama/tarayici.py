"""Tarama eklentisi.

Her dizin kendi thread'inde taranır; ağda asılı kalan bir dizin diğerlerini durdurmaz.

Bir tarama turu (dizin başına):
  1. Tek `os.scandir` geçişi (dosya açılmaz; ad, boyut, mtime dizin listesinden gelir).
  2. Geçici yükleme adları (.filepart/.part) ayrı izlenir; asla tetiklenmez.
  3. Uzantısı uyan dosyalar için dosya bazında fark:
       * aktif kaydı olan ve listesi değişmeyen dosya → hiçbir şey yapılmaz (hızlı yol),
       * yeni ya da değişmiş dosya → 'yukleme' tablosunda izlenir (henüz yeni dosya DEĞİL):
           - gerçek boyut/mtime W süresi boyunca sabit mi,
           - paylaşım testi: yazan süreç dosyayı hâlâ tutuyor mu,
           - eşik altındaysa içerik hash'i (okuma sırasında değişirse baştan),
           - kimlik = dizin + ad + hash (eşik üstü: + boyut + mtime),
           - aynı adla aktif dosyanın kimliği aynıysa (yalnızca tarih değişmiş) → tetik YOK,
           - değilse → dosya kaydı + kurala uyan her kural için tetik (TEK işlemde).
       * listede artık olmayan aktif dosya → 'kalktı' (kim sildiyse; alarm yok).
  4. T_askı süresinden uzun yazılan dosya → ASKIDA + önyüze alarm.

Dizine erişilemezse (ağ, izin): durum KORUNUR (hiçbir dosya silinmiş/yeni sayılmaz), 5/10/15 sn
tekrar → ERİŞİLEMEZ + alarm + kesinti kaydı → seyrek deneme; geri gelince normal fark = telafi.
Motor önyüzden durdurulursa tarama durur; başlayınca normal fark = telafi taraması.
"""
import os
import threading
import time
from dataclasses import dataclass, field

from loguru import logger

from cekirdek import loglama
from cekirdek.db_temel import js
from cekirdek.eklenti_temel import Eklenti
from cekirdek.kimlik import DosyaDegisti, dogrulanmis_hash, idempotency_uret, kimlik_uret
from cekirdek.kurallar import ad_anahtari
from cekirdek.model import (AlarmSeviye, DizinErisim, DosyaDurum, Sebep, TetikDurum, YuklemeDurum)
from cekirdek.yapilandirma import dizin_kurallari_oku
from eklentiler.tarama.tamamlanma import ERISIM, HATA, KILITLI, YOK, paylasim_testi

MB = 1024 * 1024
ASILI_KATSAYI = 10          # ilerlemeyen dizin iş parçacığı zaman aşımının bu katını aşarsa süreç yeniden başlar
DIZIN_YAZMA_ARALIGI = 5.0   # dizin istatistiği en az bu aralıkla yazılır
TEMEL_BUTCE_SN = 1.0        # TEMEL_AL ilk kurulumunda tur başına en fazla bu kadar temel alma (yeni gelenler bekletilmez)


@dataclass
class Yuk:
    dosya_adi: str
    tam_yol: str
    durum: str
    boyut: int
    mtime_ns: int
    ilk: float
    son_buyume: float
    aciklama: str = ""
    askida: bool = False
    yazildi: tuple = field(default=None)   # DB'ye en son yazılan (durum, boyut, açıklama)


class DizinIscisi(threading.Thread):
    def __init__(self, tarayici: "Tarayici", dizin: dict, kurallar):
        super().__init__(name=f"dizin-{dizin['id']}", daemon=True)
        self.t = tarayici
        self.db, self.hdb, self.ayar = tarayici.db, tarayici.hdb, tarayici.ayar
        self.dizin = dizin
        self.dizin_id = dizin["id"]
        self.kurallar = kurallar
        self.durdur_olayi = threading.Event()
        self.simdi_dene = threading.Event()
        self.son_ilerleme = time.time()
        self.dongu_basladi = None
        self.aktif = {}       # ad_anahtar → {id, boyut, mtime_ns, kimlik, liste}
        self.yukleme = {}     # ad_anahtar → Yuk
        self.gecici = {}      # ad_anahtar → Yuk (GECICI_AD)
        self.erisim = dizin.get("erisim_durumu") or DizinErisim.BILINMIYOR
        self.ardisik_hata = 0
        self.sonraki_deneme = 0.0
        self.son_hata = None
        self.son_dizin_yazma = 0.0
        self.son_tarama_ms = None
        self.liste_sayisi = None
        self.tur = 0
        self.yanitsiz_bildirildi = False
        self.temel_bekleyen = None   # TEMEL_AL: temel alınacak (ad_anahtar → (ad, boyut, mtime)); parça parça işlenir
        self.temel_sayisi = 0

    # ------------------------------------------------------------ yardımcılar
    def ilerle(self):
        self.son_ilerleme = time.time()

    @property
    def yol(self) -> str:
        return self.dizin["yol"]

    def ozet(self) -> dict:
        return {"id": self.dizin_id, "yol": self.yol, "erisim": self.erisim, "aktif": len(self.aktif),
                "yukleniyor": len(self.yukleme) + len(self.gecici), "son_tarama_ms": self.son_tarama_ms,
                "liste": self.liste_sayisi, "tur": self.tur}

    # ------------------------------------------------------------ yaşam döngüsü
    def run(self):
        try:
            self._durumu_yukle()
        except Exception:
            logger.exception(f"{self.yol}: durum yüklenemedi")
        while not self.durdur_olayi.is_set() and not self.t.durmali():
            self.ilerle()
            simdi = time.time()
            if self.ayar.al("motor_aktif") and (simdi >= self.sonraki_deneme or self.simdi_dene.is_set()):
                self.simdi_dene.clear()
                try:
                    self.dongu()
                except Exception:
                    logger.exception(f"{self.yol}: tarama turunda beklenmeyen hata")
                finally:
                    self.dongu_basladi = None
            self.ilerle()
            aralik = float(self.ayar.al("tarama_araligi_sn"))
            bekle = aralik
            if self.erisim in (DizinErisim.DENENIYOR, DizinErisim.ERISILEMEZ):
                bekle = max(0.05, min(aralik, self.sonraki_deneme - time.time()))
            self.simdi_dene.wait(bekle)

    def _durumu_yukle(self):
        with self.db.yaz() as con:
            con.execute("DELETE FROM yukleme WHERE dizin_id=?", (self.dizin_id,))   # yükleme izleri geçicidir
        for r in self.db.oku("SELECT id, ad_anahtar, boyut, mtime_ns, kimlik, dosya_no FROM dosya "
                             "WHERE dizin_id=? AND kalkma_zamani IS NULL", (self.dizin_id,)):
            self.aktif[r["ad_anahtar"]] = {"id": r["id"], "boyut": r["boyut"], "mtime_ns": r["mtime_ns"],
                                           "kimlik": r["kimlik"], "liste": (r["boyut"], r["mtime_ns"]),
                                           "no": r["dosya_no"]}
        logger.info(f"{self.yol}: {len(self.aktif)} aktif dosya kaydı yüklendi")

    # ------------------------------------------------------------ tur
    def dongu(self):
        self.dongu_basladi = time.time()
        self.ilerle()
        t0 = time.perf_counter()
        try:
            girdiler = self._listele()
        except OSError as e:
            self._erisim_hatasi(e)
            return
        self.son_tarama_ms = int((time.perf_counter() - t0) * 1000)
        self.liste_sayisi = len(girdiler)
        self._erisim_basarili()
        if not self.dizin.get("ilk_tarama_yapildi"):
            self._ilk_tarama(girdiler)
        self._farki_isle(girdiler)
        self._askida_kontrol()
        self.tur += 1
        self._dizin_yaz()

    def _listele(self) -> list:
        girdiler = []
        with os.scandir(self.yol) as it:
            for i, e in enumerate(it):
                if i % 500 == 0:
                    self.ilerle()
                try:
                    if not e.is_file(follow_symlinks=False):
                        continue                     # klasörler ve alt klasör içerikleri izlenmez (D4, D5)
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                girdiler.append((e.name, st.st_size, st.st_mtime_ns))
        return girdiler

    # ------------------------------------------------------------ ilk kurulum (G3)
    def _ilk_tarama(self, girdiler):
        """TEMEL_AL: dizin eklenirken duran dosyalar tetiklenmez (TEMEL, hash'iyle kayıt). Büyük dizinde bu iş uzun
        sürebildiği için tur başına en fazla TEMEL_BUTCE_SN yapılır ve her turda yeni gelen dosyalar da normal akışla
        işlenir (ilk kurulum sırasında gelen dosyanın SLA'sı bekletilmez). Yarıda kalırsa (yeniden başlatma) kalan
        dosyalardan devam edilir: temel alınmışlar veritabanından yüklenir."""
        mod = self.dizin.get("ilk_kurulum_modu")
        if mod == "TEMEL_AL":
            dk = self.kurallar
            if self.temel_bekleyen is None:
                sinir_ns = int((float(self.dizin["olusturma"]) - 1.0) * 1e9)
                self.temel_bekleyen = {}
                for ad, boyut, mtime in girdiler:
                    if dk.parca_ic_adi(ad) is not None or not dk.uzanti_uygun(ad) or mtime >= sinir_ns:
                        continue                          # dizin eklendikten sonra gelmiş: normal akış
                    ak = ad_anahtari(ad)
                    if ak not in self.aktif:
                        self.temel_bekleyen[ak] = (ad, boyut, mtime)
                logger.info(f"{self.yol}: {len(self.temel_bekleyen)} dosya temel alınacak")
            listede = {ad_anahtari(ad) for ad, _, _ in girdiler} if self.temel_bekleyen else set()
            bitis = time.monotonic() + TEMEL_BUTCE_SN
            for ak in list(self.temel_bekleyen):
                if self.t.durmali() or self.durdur_olayi.is_set() or time.monotonic() > bitis:
                    return                                # kalan: sonraki turda
                ad, boyut, mtime = self.temel_bekleyen.pop(ak)
                self.ilerle()
                if ak not in listede or ak in self.aktif:
                    continue                              # bu arada kalktı / zaten kayıtlı
                yol = os.path.join(self.yol, ad)
                if paylasim_testi(yol)[0] != "SERBEST":
                    continue                              # hâlâ yazılıyor: gelen dosyadır (normal akış)
                try:
                    st = os.stat(yol)
                    kimlik, icerik, sure = self._kimlik(ak, yol, st.st_size, st.st_mtime_ns)
                except (OSError, DosyaDegisti):
                    continue                              # temel alınamadı: normal akış karar verir
                simdi = time.time()
                with self.db.yaz() as con:
                    dosya_id = con.execute(
                        "INSERT INTO dosya(dizin_id, dosya_adi, ad_anahtar, tam_yol, boyut, mtime_ns, kimlik, "
                        "icerik_hash, hash_suresi_ms, durum, ilk_gorulme, hazir_zamani, aciklama, dosya_no) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.dizin_id, ad, ak, yol, st.st_size, st.st_mtime_ns, kimlik, icerik, sure,
                         DosyaDurum.TEMEL, simdi, simdi, "dizin eklenirken vardı (TEMEL_AL)", st.st_ino or None)).lastrowid
                self.aktif[ak] = {"id": dosya_id, "boyut": st.st_size, "mtime_ns": st.st_mtime_ns, "kimlik": kimlik,
                                  "liste": (boyut, mtime), "no": st.st_ino or None}
                self.temel_sayisi += 1
            if self.temel_bekleyen:
                return
        self.temel_bekleyen = None
        self.db.calistir("UPDATE dizin SET ilk_tarama_yapildi=1 WHERE id=?", (self.dizin_id,))
        self.dizin["ilk_tarama_yapildi"] = 1
        loglama.olay("DIZIN_ILK_TARAMA", dizin=self.yol, mod=mod, temel=self.temel_sayisi)

    # ------------------------------------------------------------ fark
    def _farki_isle(self, girdiler):
        dk = self.kurallar
        gorulen, gecici_gorulen, adaylar = set(), set(), []
        for ad, boyut, mtime in girdiler:
            ak = ad_anahtari(ad)
            if self.temel_bekleyen and ak in self.temel_bekleyen:
                continue                                  # ilk kurulumda temel alınmayı bekliyor
            ic = dk.parca_ic_adi(ad)
            if ic is not None:
                if dk.parca_dikkate_al and dk.uzanti_uygun(ic) and dk.eslestir(ic):
                    gecici_gorulen.add(ak)
                    self._gecici_guncelle(ak, ad, boyut, mtime, ic)
                continue
            if not dk.uzanti_uygun(ad):
                continue
            gorulen.add(ak)
            a = self.aktif.get(ak)
            if a is not None and a["liste"] == (boyut, mtime) and ak not in self.yukleme:
                continue                              # hızlı yol: değişmemiş
            adaylar.append((ak, ad, boyut, mtime))
        for ak in [k for k in self.aktif if k not in gorulen]:
            self._kalkti(ak)
        for ak in [k for k in self.yukleme if k not in gorulen]:
            self._yukleme_bitir(ak, "yükleme bitmeden dosya kayboldu")
        for ak in [k for k in self.gecici if k not in gecici_gorulen]:
            self._gecici_bitir(ak)
        for ak, ad, boyut, mtime in adaylar:
            if self.t.durmali() or self.durdur_olayi.is_set():
                return
            try:
                self._aday_isle(ak, ad, boyut, mtime)
            except Exception:
                logger.exception(f"{self.yol}\\{ad}: işlenirken hata")
            self.ilerle()

    def _aday_isle(self, ak, ad, liste_boyut, liste_mtime):
        yol = os.path.join(self.yol, ad)
        simdi = time.time()
        y = self.yukleme.get(ak)
        try:
            st = os.stat(yol)
        except FileNotFoundError:
            if y:
                self._yukleme_bitir(ak, "dosya kayboldu")
            return
        except OSError as e:
            self._okunamiyor(ak, ad, yol, y, f"durum okunamadı: {e}")
            return
        boyut, mtime = st.st_size, st.st_mtime_ns
        W = float(self.ayar.al("sabitlik_W_sn"))
        if y is None:
            y = Yuk(ad, yol, YuklemeDurum.YAZILIYOR, boyut, mtime, simdi, simdi)
            self.yukleme[ak] = y
            self._yukleme_yaz(ak, y)
            loglama.olay("YUKLENIYOR", dizin=self.yol, ad=ad, boyut=boyut)
            if W > 0:
                return
        elif (boyut, mtime) != (y.boyut, y.mtime_ns):
            y.boyut, y.mtime_ns, y.son_buyume = boyut, mtime, simdi
            self._durum(ak, y, YuklemeDurum.YAZILIYOR, "")
            return
        elif simdi - y.son_buyume < W:
            if y.durum == YuklemeDurum.OKUNAMIYOR:
                self._durum(ak, y, YuklemeDurum.YAZILIYOR, "")
            return
        sonuc, kod = paylasim_testi(yol)
        if sonuc == KILITLI:
            self._durum(ak, y, YuklemeDurum.KILITLI, "yazan süreç dosyayı hâlâ açık tutuyor")
            return
        if sonuc == YOK:
            self._yukleme_bitir(ak, "dosya kayboldu")
            return
        if sonuc in (ERISIM, HATA):
            self._okunamiyor(ak, ad, yol, y, f"paylaşım testi: Windows hata {kod}")
            return
        try:
            kimlik, icerik, sure = self._kimlik(ak, yol, boyut, mtime)
        except DosyaDegisti:
            y.son_buyume = time.time()
            self._durum(ak, y, YuklemeDurum.YAZILIYOR, "hash sırasında değişti")
            return
        except FileNotFoundError:
            self._yukleme_bitir(ak, "dosya kayboldu")
            return
        except OSError as e:
            self._okunamiyor(ak, ad, yol, y, f"okunamadı: {e}")
            return
        a = self.aktif.get(ak)
        no = st.st_ino or None
        if a is not None and a.get("no") and no and a["no"] != no:
            # Dosya numarası değişti: dosya silinip aynı adla YENİDEN yazılmış (iki tarama arasında kalkıp geldi) →
            # bu yeni bir geliştir (tetiklenir). Yerinde değişimde ve yeniden adlandırmada numara aynı kalır.
            self._hazir(ak, ad, yol, boyut, mtime, (liste_boyut, liste_mtime), kimlik, icerik, sure, y, a, no,
                        onceki_neden="dosya silinip aynı adla yeniden geldi (dosya numarası değişti)")
            return
        if a is not None and a["kimlik"] == kimlik:
            # içerik aynı: yalnızca tarih/liste bilgisi değişti → tetik yok
            self.db.calistir("UPDATE dosya SET boyut=?, mtime_ns=?, dosya_no=COALESCE(dosya_no, ?) WHERE id=?",
                             (boyut, mtime, no, a["id"]))
            a.update(boyut=boyut, mtime_ns=mtime, liste=(liste_boyut, liste_mtime), no=a.get("no") or no)
            self._yukleme_bitir(ak, None)
            loglama.olay("DEGISMEDI", dizin=self.yol, ad=ad, neden="yalnızca tarih değişti; içerik aynı")
            return
        if a is not None:
            # B5 (kullanıcı kararı 2026-09-30): dizinde duran (tetiklenmiş, temel alınmış ya da kurala uymamış)
            # dosyanın içeriği değişti → yeni geliş DEĞİL, tetik yok; güncel hâli esas alınır. Dosya dizinden
            # kalkıp yeniden gelirse o yeni geliştir (tetiklenir).
            self.db.calistir(
                "UPDATE dosya SET boyut=?, mtime_ns=?, kimlik=?, icerik_hash=?, hash_suresi_ms=?, "
                "icerik_degisim=icerik_degisim+1, son_icerik_degisimi=?, dosya_no=COALESCE(dosya_no, ?) WHERE id=?",
                (boyut, mtime, kimlik, icerik, sure, time.time(), no, a["id"]))
            a.update(boyut=boyut, mtime_ns=mtime, kimlik=kimlik, liste=(liste_boyut, liste_mtime), no=a.get("no") or no)
            self._yukleme_bitir(ak, None)
            loglama.olay("ICERIK_DEGISTI", dizin=self.yol, ad=ad, boyut=boyut,
                         neden="dizinde duran dosyanın içeriği değişti; tetik yok, güncel hâli esas alındı")
            return
        self._hazir(ak, ad, yol, boyut, mtime, (liste_boyut, liste_mtime), kimlik, icerik, sure, y, None, no)

    def _kimlik(self, ak, yol, boyut, mtime):
        esik = float(self.ayar.al("hash_esik_mb")) * MB
        if boyut < esik:
            icerik, sure = dogrulanmis_hash(yol, boyut, mtime, ilerleme=self.ilerle)
            return kimlik_uret(self.dizin_id, ak, icerik_hash=icerik), icerik, sure
        return kimlik_uret(self.dizin_id, ak, boyut=boyut, mtime_ns=mtime), None, None

    def _hazir(self, ak, ad, yol, boyut, mtime, liste, kimlik, icerik, sure, y, onceki, no=None, onceki_neden=None):
        eslesmeler = self.kurallar.eslestir(ad)
        simdi = time.time()
        durum = DosyaDurum.HAZIR if eslesmeler else DosyaDurum.ESLESMEDI
        tetikler = []
        with self.db.yaz() as con:
            if onceki is not None:
                con.execute("UPDATE dosya SET kalkma_zamani=?, aciklama=? WHERE id=?",
                            (simdi, onceki_neden or "yeni geliş geldi", onceki["id"]))
            dosya_id = con.execute(
                "INSERT INTO dosya(dizin_id, dosya_adi, ad_anahtar, tam_yol, boyut, mtime_ns, kimlik, icerik_hash, "
                "hash_suresi_ms, durum, kural_id, ilk_gorulme, hazir_zamani, aciklama, dosya_no) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.dizin_id, ad, ak, yol, boyut, mtime, kimlik, icerik, sure, durum,
                 eslesmeler[0][0].id if eslesmeler else None, y.ilk, simdi,
                 None if icerik else "hash eşiği üstü: kimlik ad + boyut + tarih", no)).lastrowid
            for kural, gruplar in eslesmeler:
                idem = idempotency_uret(kimlik, dosya_id, kural.id)
                parametreler = {"dosya_adi": ad, "tam_yol": yol, "dizin": self.yol, "boyut": boyut,
                                "icerik_hash": icerik, "kural": kural.ad, "gruplar": gruplar,
                                "is_bilgisi": kural.is_bilgisi, "istek": kural.istek}
                cur = con.execute(
                    "INSERT OR IGNORE INTO tetik(dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi, "
                    "tam_yol, durum, olusturma, sonraki_deneme) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (dosya_id, kural.id, kural.hedef_id, idem, js(parametreler), ad, yol, TetikDurum.BEKLIYOR,
                     simdi, simdi))
                if cur.rowcount:
                    tetikler.append(kural.ad)
            con.execute("DELETE FROM yukleme WHERE dizin_id=? AND ad_anahtar=?", (self.dizin_id, ak))
            self.db.sayac_artir("hazir" if eslesmeler else "eslesmedi", 1, con)
        self.aktif[ak] = {"id": dosya_id, "boyut": boyut, "mtime_ns": mtime, "kimlik": kimlik, "liste": liste, "no": no}
        self.yukleme.pop(ak, None)
        if y.askida:
            self.db.alarm_kapat(self._askida_anahtari(ak))
        if eslesmeler:
            loglama.olay("HAZIR", dizin=self.yol, ad=ad, boyut=boyut, hash_ms=sure, kural=",".join(tetikler),
                         bekleme_sn=round(simdi - y.ilk, 2), yeni_surum=onceki is not None)
        else:
            self.hdb.gonderilemeyen_yaz(kimlik, Sebep.ESLESMEDI, ad, yol, dizin_yolu=self.yol,
                                        sebep_detay="uzantı uydu ama hiçbir kuralın regex'i uymadı")
            loglama.olay("ESLESMEDI", dizin=self.yol, ad=ad)

    def _kalkti(self, ak):
        a = self.aktif.pop(ak)
        self.db.calistir("UPDATE dosya SET kalkma_zamani=? WHERE id=? AND kalkma_zamani IS NULL",
                         (time.time(), a["id"]))
        logger.debug(f"{self.yol}: dosya kalktı ({ak})")

    # ------------------------------------------------------------ yükleme izleri
    def _durum(self, ak, y: Yuk, durum, aciklama):
        y.durum = YuklemeDurum.ASKIDA if y.askida else durum
        y.aciklama = aciklama if not y.askida else (aciklama or y.aciklama)
        self._yukleme_yaz(ak, y)

    def _okunamiyor(self, ak, ad, yol, y, aciklama):
        if y is None:
            y = Yuk(ad, yol, YuklemeDurum.OKUNAMIYOR, None, None, time.time(), time.time())
            self.yukleme[ak] = y
        self._durum(ak, y, YuklemeDurum.OKUNAMIYOR, aciklama)
        logger.warning(f"{yol}: {aciklama} (önceki durum korunuyor)")

    def _yukleme_yaz(self, ak, y: Yuk):
        imza = (y.durum, y.boyut, y.aciklama)
        if imza == y.yazildi:
            return
        self.db.calistir(
            "INSERT INTO yukleme(dizin_id, ad_anahtar, dosya_adi, tam_yol, durum, boyut, mtime_ns, ilk_gorulme, "
            "son_buyume, son_kontrol, aciklama) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(dizin_id, ad_anahtar) DO UPDATE SET durum=excluded.durum, boyut=excluded.boyut, "
            "mtime_ns=excluded.mtime_ns, son_buyume=excluded.son_buyume, son_kontrol=excluded.son_kontrol, "
            "aciklama=excluded.aciklama",
            (self.dizin_id, ak, y.dosya_adi, y.tam_yol, y.durum, y.boyut, y.mtime_ns, y.ilk, y.son_buyume,
             time.time(), y.aciklama))
        y.yazildi = imza

    def _yukleme_bitir(self, ak, neden):
        y = self.yukleme.pop(ak, None)
        self.db.calistir("DELETE FROM yukleme WHERE dizin_id=? AND ad_anahtar=?", (self.dizin_id, ak))
        if y and y.askida:
            self.db.alarm_kapat(self._askida_anahtari(ak))
        if neden and y:
            loglama.olay("YUKLEME_BITTI", dizin=self.yol, ad=y.dosya_adi, neden=neden)

    def _gecici_guncelle(self, ak, ad, boyut, mtime, ic_ad):
        y = self.gecici.get(ak)
        simdi = time.time()
        if y is None:
            y = Yuk(ad, os.path.join(self.yol, ad), YuklemeDurum.GECICI_AD, boyut, mtime, simdi, simdi,
                    aciklama=f"geçici adla yükleniyor → {ic_ad}")
            self.gecici[ak] = y
            loglama.olay("GECICI_AD", dizin=self.yol, ad=ad, asil=ic_ad)
        elif (boyut, mtime) != (y.boyut, y.mtime_ns):
            y.boyut, y.mtime_ns, y.son_buyume = boyut, mtime, simdi
        self._yukleme_yaz(ak, y)

    def _gecici_bitir(self, ak):
        y = self.gecici.pop(ak, None)
        self.db.calistir("DELETE FROM yukleme WHERE dizin_id=? AND ad_anahtar=?", (self.dizin_id, ak))
        if y and y.askida:
            self.db.alarm_kapat(self._askida_anahtari(ak))

    def _askida_anahtari(self, ak):
        return f"askida:{self.dizin_id}:{ak}"

    def _askida_kontrol(self):
        sinir = float(self.ayar.al("aski_T_dk")) * 60
        simdi = time.time()
        for sozluk in (self.yukleme, self.gecici):
            for ak, y in sozluk.items():
                if not y.askida and simdi - y.ilk > sinir:
                    y.askida = True
                    y.durum = YuklemeDurum.ASKIDA
                    self._yukleme_yaz(ak, y)
                    dk = (simdi - y.ilk) / 60
                    self.db.alarm_ac(self._askida_anahtari(ak),
                                     f"{y.dosya_adi} {dk:.1f} dakikadır tamamlanmadı ({self.yol}). Yükleme yavaş, "
                                     f"takılmış ya da yarıda kalmış olabilir; tamamlanana kadar tetiklenmeyecek.",
                                     AlarmSeviye.UYARI, "tarama")
                    loglama.olay("ASKIDA", dizin=self.yol, ad=y.dosya_adi, dakika=round(dk, 1))

    # ------------------------------------------------------------ dizin erişimi
    def _erisim_hatasi(self, e: OSError):
        self.ardisik_hata += 1
        plan = self.ayar.plan("dizin_deneme_plani")
        simdi = time.time()
        onceki = self.erisim
        self.son_hata = f"{type(e).__name__}: {e}"[:300]
        if self.ardisik_hata == 1:
            self.hdb.kesinti_basla("DIZIN", self.yol, self.son_hata)
        if self.ardisik_hata <= len(plan):
            self.erisim = DizinErisim.DENENIYOR
            self.sonraki_deneme = simdi + plan[self.ardisik_hata - 1]
        else:
            self.erisim = DizinErisim.ERISILEMEZ
            self.sonraki_deneme = simdi + float(self.ayar.al("dizin_seyrek_deneme_sn"))
            if onceki != DizinErisim.ERISILEMEZ:
                self.db.alarm_ac(f"dizin:{self.dizin_id}:erisilemez",
                                 f"Dizine erişilemiyor: {self.yol} ({self.son_hata}). Durum korunuyor; bu sürede "
                                 f"gelen dosyalar dizin geri gelince yakalanacak.", AlarmSeviye.KRITIK, "tarama")
        if self.erisim != onceki or self.ardisik_hata <= len(plan) + 1:
            loglama.olay("DIZIN_HATA", dizin=self.yol, ardisik=self.ardisik_hata, durum=self.erisim, hata=self.son_hata)
        else:   # erişilemez dizinin seyrek denemeleri logu şişirmesin (I2)
            logger.debug(f"{self.yol}: hâlâ erişilemiyor ({self.ardisik_hata}. deneme)")
        self._dizin_yaz(zorla=True)

    def _erisim_basarili(self):
        if self.erisim in (DizinErisim.DENENIYOR, DizinErisim.ERISILEMEZ, DizinErisim.YANITSIZ):
            self.hdb.kesinti_bitir("DIZIN", self.yol)
            self.db.alarm_kapat(f"dizin:{self.dizin_id}:erisilemez")
            self.db.alarm_kapat(f"dizin:{self.dizin_id}:yanitsiz")
            loglama.olay("DIZIN_GERI_GELDI", dizin=self.yol, onceki=self.erisim)
            degisti = True
        else:
            degisti = self.erisim != DizinErisim.ERISILEBILIR
        self.erisim = DizinErisim.ERISILEBILIR
        self.ardisik_hata = 0
        self.sonraki_deneme = 0.0
        self.son_hata = None
        self.yanitsiz_bildirildi = False
        if degisti:
            self._dizin_yaz(zorla=True)

    def _dizin_yaz(self, zorla=False):
        simdi = time.time()
        if not zorla and simdi - self.son_dizin_yazma < DIZIN_YAZMA_ARALIGI:
            return
        self.son_dizin_yazma = simdi
        self.db.calistir(
            "UPDATE dizin SET erisim_durumu=?, erisim_degisim=CASE WHEN erisim_durumu<>? THEN ? ELSE erisim_degisim END, "
            "son_tarama=?, son_tarama_ms=?, dosya_sayisi=?, ardisik_hata=?, sonraki_deneme=?, son_hata=? WHERE id=?",
            (self.erisim, self.erisim, simdi, simdi, self.son_tarama_ms, self.liste_sayisi, self.ardisik_hata,
             self.sonraki_deneme or None, self.son_hata, self.dizin_id))


class Tarayici(Eklenti):
    AD = "tarama"

    def __init__(self):
        super().__init__()
        self.isciler = {}
        self._surum = None

    def bilgi(self) -> dict:
        return {"motor": bool(self.ayar.al("motor_aktif")), "dizinler": [i.ozet() for i in list(self.isciler.values())]}

    def calis(self):
        while not self.durmali():
            self.ilerle()
            self.ayar.tazele()
            surum = self.db.meta_al("yapilandirma_surumu", "0") + "|" + str(self.ayar._surum)
            if surum != self._surum:
                self._surum = surum
                self._yapilandir()
            self._komutlar()
            self._asili_kontrol()
            self.bekle(0.3)
        for i in self.isciler.values():
            i.durdur_olayi.set()
            i.simdi_dene.set()
        for i in self.isciler.values():
            i.join(3)

    def _yapilandir(self):
        harita = dizin_kurallari_oku(self.db, self.ayar)
        for dizin_id, (satir, kurallar) in harita.items():
            isci = self.isciler.get(dizin_id)
            if isci is None:
                isci = DizinIscisi(self, satir, kurallar)
                self.isciler[dizin_id] = isci
                isci.start()
                logger.info(f"dizin izleniyor: {satir['yol']} ({len(kurallar.kurallar)} kural)")
            else:
                isci.kurallar = kurallar                  # tek atama: yarım turda kural değişmez
                isci.dizin.update({k: satir[k] for k in ("uzantilar", "ad")})
        for dizin_id in [d for d in self.isciler if d not in harita]:
            isci = self.isciler.pop(dizin_id)
            isci.durdur_olayi.set()
            isci.simdi_dene.set()
            logger.info(f"dizin izlemesi bırakıldı: {isci.yol}")

    def _komutlar(self):
        for k in self.db.komutlari_al("tarama"):
            import json
            p = json.loads(k["parametre"] or "{}")
            if k["komut"] == "SIMDI_DENE":
                hedefler = [self.isciler[p["dizin_id"]]] if p.get("dizin_id") in self.isciler else \
                    list(self.isciler.values()) if p.get("dizin_id") is None else []
                for i in hedefler:
                    i.sonraki_deneme = 0.0
                    i.simdi_dene.set()
                self.db.komut_bitir(k["id"], f"{len(hedefler)} dizin yeniden denenecek")
            else:
                self.db.komut_bitir(k["id"], f"bilinmeyen komut: {k['komut']}", durum="HATA")

    def _asili_kontrol(self):
        """İlerlemeyen dizin iş parçacıkları: YANITSIZ + alarm; çok uzun asılıysa süreç yeniden başlar (M3)."""
        zaman_asimi = float(self.ayar.al("dizin_tarama_zaman_asimi_sn"))
        simdi = time.time()
        for i in list(self.isciler.values()):
            if i.dongu_basladi is None:
                continue
            sessiz = simdi - i.son_ilerleme
            if sessiz > zaman_asimi and not i.yanitsiz_bildirildi:
                i.yanitsiz_bildirildi = True
                i.erisim = DizinErisim.YANITSIZ
                self.db.calistir("UPDATE dizin SET erisim_durumu=?, erisim_degisim=?, son_hata=? WHERE id=?",
                                 (DizinErisim.YANITSIZ, simdi, f"{sessiz:.0f} sn yanıt yok", i.dizin_id))
                self.db.alarm_ac(f"dizin:{i.dizin_id}:yanitsiz",
                                 f"Dizin yanıt vermiyor: {i.yol} ({sessiz:.0f} sn). Ağ paylaşımı takılmış olabilir; "
                                 f"diğer dizinler taranmaya devam ediyor.", AlarmSeviye.KRITIK, "tarama")
                loglama.olay("DIZIN_YANITSIZ", dizin=i.yol, sn=round(sessiz))
            if sessiz > zaman_asimi * ASILI_KATSAYI:
                logger.critical(f"{i.yol}: {sessiz:.0f} sn asılı; tarama süreci yeniden başlatılmak üzere kapanıyor")
                loglama.olay("TARAMA_YENIDEN_BASLIYOR", dizin=i.yol, sn=round(sessiz))
                logger.complete()
                os._exit(5)


if __name__ == "__main__":
    Tarayici.baslat()
