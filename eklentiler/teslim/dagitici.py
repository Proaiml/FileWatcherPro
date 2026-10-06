"""Teslim eklentisi: tetik kuyruğunu hedeflere (Control-M ve diğerleri) iletir.

Canlı akış:
  BEKLIYOR → DENENIYOR → (başarı) ILETILDI
                       → (geçici/belirsiz) TEKRAR — deneme planı 5/10/15 sn — … → LOKALDE (+JSON kayıt + alarm)
                       → (kalıcı 4xx) LOKALDE + yapılandırma alarmı (tekrar denenmez)
Kapalı hedef/kural:  KAYITLI → LOKALDE (lokale yazılır)  ·  KAYITSIZ → KAYITSIZ_KAPALI (yalnızca kayıt)
Devre kesici (H6):   hedefte art arda 'otomatik_devre_esigi' hata → KESILDI + KRİTİK alarm; yeni tetikler
                     denenmeden lokale yazılır. Yeniden açma ELLE (önyüz). Kesikken hedef 30 sn'de bir
                     tetik göndermeden yoklanır; sonuç önyüzde "şu an yanıt veriyor" olarak görünür.
Kademeli erit:       hedef açık + devre normal + erit CALISIYOR iken LOKALDE tetikler geliş sırasıyla, hız
                     sınırıyla (erit_hizi/sn) gönderilir; canlı tetikler önceliklidir. Sıra Control-M'e varışta da
                     korunsun diye hedef başına aynı anda tek erit çağrısı yoldadır; çağrı bitince döngü hemen uyanır. Erit sırasında hata olursa
                     erit otomatik duraklar (U7), kalanlar lokalde kalır.
Kurtarma (G5/H10):   açılışta DENENIYOR kalmış tetikler TEKRAR'a alınır ve 'belirsiz' işaretlenir (çağrı
                     hedefe ulaşmış olabilir: olası çift); ERITILIYOR → LOKALDE. Lokal JSON dosyası olup
                     veritabanında olmayan tetikler geri yüklenir.
"""
import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from cekirdek import betik, loglama
from cekirdek.db_temel import js
from cekirdek.eklenti_temel import Eklenti
from cekirdek.model import AlarmSeviye, DevreDurum, EritDurum, KapatmaModu, Sebep, TetikDurum
from cekirdek.yapilandirma import Yapilandirma
from eklentiler.teslim.adaptorler import adaptor_kur
from eklentiler.teslim.adaptorler.temel import Sonuc, SonucTuru
from eklentiler.teslim.lokal_kayit import LokalKayit

SAGLIK_ARALIGI_SN = 30.0
PERIYODIK_ARALIK_SN = 2.0
YAVAS_ASGARI, YAVAS_ACMA, YAVAS_KAPAMA = 5, 0.20, 0.05      # H9: hedef yavaşlama alarmı
AZAMI_IS_PARCACIGI = 64


class Dagitici(Eklenti):
    AD = "teslim"

    def __init__(self):
        super().__init__()
        self.lokal = LokalKayit(self.b.lokal_kayit, self.b.karantina)
        self.yap = Yapilandirma(self.db, self.hdb)
        self.havuz = ThreadPoolExecutor(max_workers=AZAMI_IS_PARCACIGI, thread_name_prefix="gonder")
        self.kilit = threading.Lock()
        self.hedefler = {}
        self.kurallar = {}
        self.adaptorler = {}          # hedef_id → (imza, adaptör)
        self.yolda = defaultdict(set)
        self.erit_yolda = defaultdict(set)   # hedef başına en fazla 1 (varış sırası = geliş sırası)
        self.uyandir = threading.Event()     # çağrı bitince ana döngüyü beklemeden uyandırır
        self.kova = {}                # hedef_id → [jeton, son_zaman]
        self.son_saglik = {}
        self.saglik_yolda = set()
        self.son_periyodik = 0.0
        self.son_lokal_sayisi = {}
        self.yavas = {}                # hedef_id → (son kontrol, alarm açık mı)
        self._surum = None
        self.sayac = defaultdict(int)

    def bilgi(self) -> dict:
        return {"yolda": {str(k): len(v) for k, v in list(self.yolda.items())}, "sayac": dict(self.sayac)}

    # ================================================================ yaşam döngüsü
    def calis(self):
        self._kurtar()
        while not self.durmali():
            self.ilerle()
            self.ayar.tazele()
            surum = f"{self.db.meta_al('yapilandirma_surumu', '0')}|{self.ayar._surum}"
            if surum != self._surum:
                self._surum = surum
                self._yapilandir()
            try:
                self._kuyrugu_isle()
                self._erit()
                if time.time() - self.son_periyodik > PERIYODIK_ARALIK_SN:
                    self.son_periyodik = time.time()
                    self._periyodik()
            except Exception:
                logger.exception("teslim turunda hata (döngü devam ediyor)")
            self.uyandir.wait(0.1)
            self.uyandir.clear()
        self._kapanista_bosalt()
        n = betik.hepsini_sonlandir()          # süresi uzun betikler kapanışı bekletmesin: BELİRSİZ → açılışta yeniden
        if n:
            logger.warning(f"kapanış: çalışan {n} betik sonlandırıldı; tetikleri belirsiz işaretli, açılışta yeniden denenecek")
        logger.info("teslim kapanıyor: yoldaki çağrıların bitmesi bekleniyor")
        self.havuz.shutdown(wait=True)

    def _kapanista_bosalt(self):
        """H10 (kullanıcı kararı): kapanırken bekleyen tetiklere kapanis_teslim_bekleme_sn kadar süre tanınır; bu sürede
        kuyruk (yeniden denemeler dahil) normal akışla gönderilir, erit yeni çağrı başlatmaz. Kuyruk boşalınca hemen
        çıkılır. Süre dolunca kalanlar veritabanında kalır ve açılışta kendiliğinden gönderilir (kayıp yok)."""
        try:
            sure = float(self.ayar.al("kapanis_teslim_bekleme_sn"))
        except Exception:
            sure = 0.0
        if sure <= 0:
            return
        sayim = ("SELECT COUNT(*) FROM tetik WHERE durum IN (?,?)", (TetikDurum.BEKLIYOR, TetikDurum.TEKRAR))
        baslangic = self.db.tek(*sayim)[0]
        with self.kilit:
            yolda = sum(len(v) for v in self.yolda.values())
        if not baslangic and not yolda:
            return
        logger.info(f"kapanış: {baslangic} bekleyen tetik için en fazla {sure:g} sn gönderime devam ediliyor")
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            try:
                self._kuyrugu_isle()
            except Exception:
                logger.exception("kapanış boşaltmasında hata")
            with self.kilit:
                yolda = sum(len(v) for v in self.yolda.values())
            if not yolda and not self.db.tek(*sayim)[0]:
                break
            self.uyandir.wait(0.1)
            self.uyandir.clear()
        kalan = self.db.tek(*sayim)[0]
        loglama.olay("KAPANIS_BOSALTMA", bekleyen=baslangic, kalan=kalan)
        if kalan:
            logger.warning(f"kapanış: {kalan} tetik süre içinde gönderilemedi; veritabanında bekliyor, açılışta gönderilecek")

    def _yapilandir(self):
        self.hedefler = {r["id"]: dict(r) for r in self.db.oku("SELECT * FROM hedef")}
        self.kurallar = {r["id"]: dict(r) for r in self.db.oku("SELECT id, ad, aktif, kapatma_modu, kapatma_zamani, "
                                                                "hedef_id, istek FROM kural")}

    def _adaptor(self, h: dict):
        imza = (h["adres"], h["tur"], h["ayrintilar"], h["guncelleme"])
        kayit = self.adaptorler.get(h["id"])
        if kayit is None or kayit[0] != imza:
            kayit = (imza, adaptor_kur(h))
            self.adaptorler[h["id"]] = kayit
        return kayit[1]

    def _esz(self, h) -> int:
        return int(h.get("esz_cagri_ust") or self.ayar.al("esz_cagri_ust"))

    def _plan(self, h) -> list:
        from cekirdek.ayarlar import _plan
        return _plan(h["deneme_plani"]) if h.get("deneme_plani") else self.ayar.plan("deneme_plani")

    def _timeout(self, h) -> float:
        return float(h.get("timeout_sn") or self.ayar.al("cagri_timeout_sn"))

    # ================================================================ kurtarma (G5, H10, S1–S4)
    def _kurtar(self):
        with self.db.yaz() as con:
            n1 = con.execute("UPDATE tetik SET durum=?, sonraki_deneme=?, sahip=NULL, belirsiz=1, "
                             "son_hata='teslim süreci çağrı sırasında yeniden başladı (hedefe ulaşmış olabilir)' "
                             "WHERE durum=?", (TetikDurum.TEKRAR, time.time(), TetikDurum.DENENIYOR)).rowcount
            n2 = con.execute("UPDATE tetik SET durum=?, sahip=NULL, belirsiz=1 WHERE durum=?",
                             (TetikDurum.LOKALDE, TetikDurum.ERITILIYOR)).rowcount
        if n1 or n2:
            logger.warning(f"kurtarma: {n1} yarım kalan çağrı yeniden denenecek, {n2} erit kaydı lokale döndü")
            loglama.olay("KURTARMA", deneniyor=n1, eritiliyor=n2)
        self.lokal.yarim_kalanlari_temizle()
        self._yapilandir()
        self._ice_aktar()

    def _ice_aktar(self):
        """Lokal JSON'da olup veritabanında olmayan tetikleri geri yükler (veritabanı kaybı / bozulması)."""
        hedef_ad = {h["ad"]: h["id"] for h in self.hedefler.values()}
        geri, bozuk, artik = 0, 0, 0
        for yol in self.lokal.tum_dosyalar():
            try:
                k = self.lokal.oku(yol)
            except (OSError, ValueError, UnicodeDecodeError) as e:
                bozuk += 1
                self._bozuk_lokal(yol, e)
                continue
            r = self.db.tek("SELECT durum, lokal_dosya FROM tetik WHERE idempotency=?", (k["idempotency"],))
            if r:
                guncel = r["lokal_dosya"]
                if r["durum"] in (TetikDurum.ILETILDI, TetikDurum.SILINDI) or (
                        guncel and os.path.normcase(os.path.abspath(guncel)) != os.path.normcase(os.path.abspath(str(yol)))
                        and os.path.exists(guncel)):
                    # artık kopya: tetik teslim edildi / elle silindi (silme tutanakta) ya da güncel kopyası başka yerde
                    # (çağrı bitti ile dosya silme arasında süreç öldü). Kalsaydı tetik satırı budandıktan sonra burada
                    # diriltilir, çift tetik olurdu.
                    self.lokal.sil(str(yol))
                    artik += 1
                continue
            hid = hedef_ad.get(k["hedef"])
            if hid is None:
                logger.warning(f"lokal kayıt tanımsız hedefe ait, geri yüklenemedi: {yol}")
                continue
            with self.db.yaz() as con:
                con.execute("INSERT INTO tetik(dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi, "
                            "tam_yol, durum, olusturma, deneme_sayisi, lokal_dosya, deneme_gecmisi, sebep, son_hata) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (k.get("dosya_id") or 0, k.get("kural_id") or 0, hid, k["idempotency"],
                             js(k["parametreler"]), k["dosya_adi"], k["tam_yol"], TetikDurum.LOKALDE,
                             k["olusturma"], k.get("deneme_sayisi", 0), yol, js(k.get("deneme_gecmisi", [])),
                             k.get("sebep"), "lokal kayıttan geri yüklendi"))
            geri += 1
        if geri:
            logger.warning(f"{geri} tetik lokal kayıttan veritabanına geri yüklendi")
            loglama.olay("LOKALDEN_GERI_YUKLENDI", adet=geri)
        if artik:
            logger.warning(f"{artik} artık lokal kopya silindi (tetik teslim edilmiş / silinmiş ya da güncel kopyası başka yerde)")
            loglama.olay("LOKAL_ARTIK_SILINDI", adet=artik)
        return geri, bozuk

    def _bozuk_lokal(self, yol, hata):
        try:
            yeni = self.lokal.karantinaya_al(yol)
        except OSError:
            yeni = yol
        self.hdb.gonderilemeyen_yaz(f"bozuk:{yol}", Sebep.LOKAL_KAYIT_BOZUK, "?", yol,
                                    sebep_detay=f"{hata}; karantina: {yeni}", lokal_dosya=yeni)
        self.db.alarm_ac(f"lokal:bozuk:{yol}", f"Okunamayan lokal kayıt karantinaya alındı: {yeni} ({hata}). "
                         f"Elle inceleyin.", AlarmSeviye.KRITIK, "teslim")
        loglama.olay("LOKAL_KAYIT_BOZUK", yol=yol, karantina=yeni)

    # ================================================================ canlı kuyruk
    def _sahiplen(self, tetik_id, eski_durumlar, yeni_durum) -> bool:
        yer = ",".join("?" * len(eski_durumlar))
        return self.db.calistir(f"UPDATE tetik SET durum=?, sahip='teslim', son_deneme=? WHERE id=? AND durum IN ({yer})",
                                (yeni_durum, time.time(), tetik_id, *eski_durumlar)) == 1

    def _kuyrugu_isle(self):
        simdi = time.time()
        satirlar = self.db.oku("SELECT * FROM tetik WHERE durum IN (?,?) AND sonraki_deneme<=? ORDER BY olusturma "
                               "LIMIT 500", (TetikDurum.BEKLIYOR, TetikDurum.TEKRAR, simdi))
        for t in satirlar:
            t = dict(t)
            h = self.hedefler.get(t["hedef_id"])
            if h is None:
                self._lokale(t, Sebep.KALICI_HATA, "hedef tanımı bulunamadı (silinmiş olabilir)")
                continue
            k = self.kurallar.get(t["kural_id"])
            if not h["aktif"]:
                self._kapali(t, h, "HEDEF", h["kapatma_modu"])
                continue
            if k is not None and not k["aktif"]:
                self._kapali(t, h, "KURAL", k["kapatma_modu"])
                continue
            if h["devre_durumu"] == DevreDurum.KESILDI:
                self._lokale(t, Sebep.DEVRE_KESIK, "devre kesik: hedef art arda yanıt vermedi; denenmeden lokale yazıldı")
                continue
            with self.kilit:
                if len(self.yolda[h["id"]]) >= self._esz(h):
                    continue
            if not self._sahiplen(t["id"], (TetikDurum.BEKLIYOR, TetikDurum.TEKRAR), TetikDurum.DENENIYOR):
                continue
            with self.kilit:
                self.yolda[h["id"]].add(t["id"])
            self.havuz.submit(self._gonder, t, h, False)

    def _kapali(self, t, h, tur, mod):
        if mod == KapatmaModu.KAYITSIZ:
            sebep = Sebep.HEDEF_KAPALI_KAYITSIZ if tur == "HEDEF" else Sebep.KURAL_KAPALI_KAYITSIZ
            with self.db.yaz() as con:
                con.execute("UPDATE tetik SET durum=?, sebep=?, kapanis=?, sahip=NULL, "
                            "son_hata='kayıtsız kapalıyken geldi; gönderilmedi' WHERE id=?",
                            (TetikDurum.KAYITSIZ_KAPALI, sebep, time.time(), t["id"]))
                self.db.sayac_artir("kayitsiz", 1, con)
            gid = self.hdb.gonderilemeyen_yaz(t["idempotency"], sebep, t["dosya_adi"], t["tam_yol"], tetik_id=t["id"],
                                              hedef_ad=h["ad"], sebep_detay=f"{tur.lower()} kayıtsız kapalıydı")
            self.hdb.calistir("UPDATE gonderilemeyen SET cozuldu=1, cozulme_zamani=?, cozum='KAYITSIZ_KAPATMA' "
                              "WHERE id=?", (time.time(), gid))
            self.sayac["kayitsiz"] += 1
            loglama.olay("KAYITSIZ_KAPALI", ad=t["dosya_adi"], hedef=h["ad"], tur=tur)
        else:
            sebep = Sebep.HEDEF_KAPALI_KAYITLI if tur == "HEDEF" else Sebep.KURAL_KAPALI_KAYITLI
            self._lokale(t, sebep, f"{tur.lower()} kayıtlı kapalı: lokale yazıldı, erit bekliyor")

    def _lokale(self, t, sebep, detay, gecmis=None):
        simdi = time.time()
        gecmis = gecmis if gecmis is not None else json.loads(t.get("deneme_gecmisi") or "[]")
        h = self.hedefler.get(t["hedef_id"]) or {"ad": f"hedef{t['hedef_id']}"}
        with self.db.yaz() as con:
            con.execute("UPDATE tetik SET durum=?, sebep=?, son_hata=?, sahip=NULL, deneme_gecmisi=? WHERE id=?",
                        (TetikDurum.LOKALDE, sebep, detay[:500], js(gecmis), t["id"]))
            if t.get("durum") != TetikDurum.LOKALDE:
                self.db.sayac_artir("lokale", 1, con)
        yol = None
        try:
            yol = self.lokal.yaz({"idempotency": t["idempotency"], "tetik_id": t["id"], "dosya_id": t["dosya_id"],
                                  "kural_id": t["kural_id"], "hedef": h["ad"], "dosya_adi": t["dosya_adi"],
                                  "tam_yol": t["tam_yol"], "parametreler": json.loads(t["parametreler"]),
                                  "olusturma": t["olusturma"], "lokale_yazilma": simdi, "sebep": sebep,
                                  "detay": detay, "deneme_sayisi": t.get("deneme_sayisi", 0),
                                  "deneme_gecmisi": gecmis})
            self.db.calistir("UPDATE tetik SET lokal_dosya=? WHERE id=?", (yol, t["id"]))
            eski = t.get("lokal_dosya")
            if eski and os.path.normcase(os.path.abspath(eski)) != os.path.normcase(os.path.abspath(yol)):
                # hedef adı değiştiyse eski kopya başka klasörde kalır: yetim kalırsa tetik satırı budandıktan sonra
                # açılıştaki geri yükleme onu diriltir (çift tetik). Yeni kopya yazıldıktan sonra silinir.
                self.lokal.sil(eski)
            self.db.alarm_kapat("lokal:yazilamadi")
        except OSError as e:
            logger.error(f"lokal kayıt yazılamadı ({t['dosya_adi']}): {e}")
            self.db.alarm_ac("lokal:yazilamadi", f"Lokal kayıt dosyası yazılamıyor ({e}). Tetikler veritabanında "
                             f"LOKALDE olarak güvende; yazım düzenli olarak yeniden denenecek. Disk alanını ve "
                             f"izinleri kontrol edin.", AlarmSeviye.KRITIK, "teslim")
        self.hdb.gonderilemeyen_yaz(t["idempotency"], sebep, t["dosya_adi"], t["tam_yol"], tetik_id=t["id"],
                                    hedef_ad=h["ad"], sebep_detay=detay[:500], deneme_sayisi=t.get("deneme_sayisi", 0),
                                    deneme_gecmisi=gecmis, lokal_dosya=yol)
        self.sayac["lokale"] += 1
        loglama.olay("LOKALE_YAZILDI", ad=t["dosya_adi"], hedef=h["ad"], sebep=sebep)

    # ================================================================ gönderim (iş parçacığında)
    def _istek(self, t: dict):
        """Kuralın GÜNCEL isteği (düzeltilmiş istekle erit edilebilsin); kural silindiyse tetikteki kopya."""
        k = self.kurallar.get(t["kural_id"])
        if k is not None:
            return json.loads(k["istek"]) if k.get("istek") else None
        p = json.loads(t["parametreler"]) if isinstance(t["parametreler"], str) else (t["parametreler"] or {})
        return p.get("istek")

    def _gonder(self, t: dict, h: dict, erit: bool):
        try:
            try:
                t = {**t, "istek": self._istek(t)}
                sonuc = self._adaptor(h).gonder(t, self._timeout(h))
            except Exception as e:
                logger.exception("adaptör hatası")
                sonuc = Sonuc(SonucTuru.GECICI, mesaj=f"adaptör hatası: {e}")
            self._sonucu_isle(t, h, erit, sonuc)
        except Exception:
            logger.exception(f"{t['dosya_adi']}: sonuç işlenemedi")
        finally:
            with self.kilit:
                self.yolda[h["id"]].discard(t["id"])
                self.erit_yolda[h["id"]].discard(t["id"])
            self.uyandir.set()

    def _sonucu_isle(self, t, h, erit, s: Sonuc):
        simdi = time.time()
        gecmis = json.loads(t.get("deneme_gecmisi") or "[]")
        gecmis.append({"z": round(simdi, 3), "tur": s.tur, "kod": s.http_kodu, "mesaj": s.mesaj[:200],
                       "ms": s.sure_ms, "erit": erit})
        gecmis = gecmis[-20:]
        n = t["deneme_sayisi"] + 1
        belirsiz = 1 if (t.get("belirsiz") or s.tur == SonucTuru.BELIRSIZ) else 0
        if s.tur == SonucTuru.BASARI:
            elle = bool(t.get("elle"))                      # lokalden seçerek gönderildi: erit gibi SLA dışı
            sure_ms = int((simdi - t["olusturma"]) * 1000)
            ihlal = int(sure_ms > float(self.ayar.al("sla_hedef_sn")) * 1000) and not elle
            with self.db.yaz() as con:
                con.execute("UPDATE tetik SET durum=?, iletildi_zamani=?, sure_ms=?, sla_ihlali=?, sonuc=?, "
                            "son_http_kodu=?, son_hata=NULL, deneme_sayisi=?, deneme_gecmisi=?, belirsiz=?, kapanis=?, "
                            "sahip=NULL, eritildi=? WHERE id=?", (TetikDurum.ILETILDI, simdi, sure_ms, ihlal and not erit,
                                                      s.mesaj[:200], s.http_kodu, n, js(gecmis), belirsiz, simdi,
                                                      int(erit or elle), t["id"]))
                con.execute("UPDATE hedef SET ardisik_hata=0 WHERE id=? AND ardisik_hata<>0", (h["id"],))
                self.db.sayac_artir("iletildi", 1, con)
                if ihlal and not erit:
                    self.db.sayac_artir("sla_ihlali", 1, con)
                if erit:
                    self.db.sayac_artir("eritildi", 1, con)
                if belirsiz:
                    self.db.sayac_artir("olasi_cift", 1, con)
            if erit or t.get("lokal_dosya") or t["durum"] == TetikDurum.LOKALDE:
                self.hdb.cozuldu_isaretle(t["idempotency"], "ERIT" if erit else "ELLE" if elle else "TEKRAR")
                if t.get("lokal_dosya"):
                    self.lokal.sil(t["lokal_dosya"])
            self.sayac["iletildi"] += 1
            if belirsiz:
                self.sayac["olasi_cift"] += 1
            loglama.olay("ILETILDI", ad=t["dosya_adi"], hedef=h["ad"], sure_ms=sure_ms, deneme=n, erit=erit, elle=elle,
                         sonuc=s.mesaj, olasi_cift=bool(belirsiz))
            if ihlal and not erit:
                loglama.olay("SLA_IHLALI", ad=t["dosya_adi"], sure_ms=sure_ms)
            return
        # ---------------- başarısız
        self.sayac["hata"] += 1
        if s.tur == SonucTuru.KALICI:
            t.update(deneme_sayisi=n, belirsiz=belirsiz)
            self.db.calistir("UPDATE tetik SET deneme_sayisi=?, son_http_kodu=?, belirsiz=? WHERE id=?",
                             (n, s.http_kodu, belirsiz, t["id"]))
            self._lokale(t, Sebep.KALICI_HATA, f"kalıcı hata (tekrar denenmez): {s.mesaj}", gecmis)
            self.db.alarm_ac(f"hedef:{h['id']}:kalici",
                             f"'{h['ad']}' kalıcı hata döndürdü ({s.mesaj}). Kural/hedef yapılandırmasını (klasör, iş adı, "
                             f"yetki) kontrol edin; düzeltince kademeli erit ile gönderin.", AlarmSeviye.KRITIK, "teslim")
            if erit:
                self._erit_durdur(h, f"kalıcı hata: {s.mesaj}")
            return
        kesildi = self._hata_say(h, s)
        if erit:
            with self.db.yaz() as con:
                con.execute("UPDATE tetik SET durum=?, sahip=NULL, deneme_sayisi=?, deneme_gecmisi=?, son_hata=?, "
                            "son_http_kodu=?, belirsiz=? WHERE id=?", (TetikDurum.LOKALDE, n, js(gecmis), s.mesaj[:500],
                                                                     s.http_kodu, belirsiz, t["id"]))
            self._erit_durdur(h, f"erit sırasında hata: {s.mesaj}")
            return
        plan = self._plan(h)
        if n <= len(plan) and not kesildi:
            bekleme = plan[n - 1]
            if s.tekrar_sonra_sn:
                bekleme = max(bekleme, s.tekrar_sonra_sn)
            with self.db.yaz() as con:
                con.execute("UPDATE tetik SET durum=?, sahip=NULL, deneme_sayisi=?, sonraki_deneme=?, deneme_gecmisi=?, "
                            "son_hata=?, son_http_kodu=?, belirsiz=? WHERE id=?",
                            (TetikDurum.TEKRAR, n, simdi + bekleme, js(gecmis), s.mesaj[:500], s.http_kodu, belirsiz,
                             t["id"]))
            self.sayac["tekrar"] += 1
            loglama.olay("TEKRAR", ad=t["dosya_adi"], hedef=h["ad"], deneme=n, bekleme_sn=bekleme, tur=s.tur,
                         mesaj=s.mesaj)
            return
        t.update(deneme_sayisi=n, belirsiz=belirsiz)
        self.db.calistir("UPDATE tetik SET deneme_sayisi=?, son_http_kodu=?, belirsiz=? WHERE id=?",
                         (n, s.http_kodu, belirsiz, t["id"]))
        sebep = Sebep.DEVRE_KESIK if kesildi and n <= len(plan) else Sebep.SLA_SON_DOLDU
        self._lokale(t, sebep, f"{n} deneme başarısız; son hata: {s.mesaj}", gecmis)

    def _hata_say(self, h, s: Sonuc) -> bool:
        """Hedefin ardışık hata sayacını artırır; eşik aşılırsa devreyi keser. Devre kesikse True."""
        esik = int(self.ayar.al("otomatik_devre_esigi"))
        with self.db.yaz() as con:
            r = con.execute("UPDATE hedef SET ardisik_hata=ardisik_hata+1 WHERE id=? RETURNING ardisik_hata, devre_durumu",
                            (h["id"],)).fetchone()
            ardisik, devre = r[0], r[1]
            if esik > 0 and ardisik >= esik and devre != DevreDurum.KESILDI:
                con.execute("UPDATE hedef SET devre_durumu=?, devre_degisim=?, saglik=NULL WHERE id=?",
                            (DevreDurum.KESILDI, time.time(), h["id"]))
                devre = DevreDurum.KESILDI
                yeni_kesildi = True
            else:
                yeni_kesildi = False
        if yeni_kesildi:
            h["devre_durumu"] = DevreDurum.KESILDI
            if h["id"] in self.hedefler:
                self.hedefler[h["id"]]["devre_durumu"] = DevreDurum.KESILDI
            self.db.alarm_ac(f"hedef:{h['id']}:devre",
                             f"'{h['ad']}' art arda {ardisik} kez yanıt vermedi; devre kesildi. Yeni tetikler denenmeden "
                             f"lokale yazılıyor. Hedef yanıt vermeye başlayınca önyüzden 'Devreyi normale al' ve "
                             f"'Kademeli erit' kullanın. Son hata: {s.mesaj}", AlarmSeviye.KRITIK, "teslim")
            self.hdb.denetim_yaz("DEVRE_KESILDI", h["ad"], yeni={"ardisik_hata": ardisik, "son_hata": s.mesaj},
                                 kullanici="sistem", kaynak="teslim")
            loglama.olay("DEVRE_KESILDI", hedef=h["ad"], ardisik=ardisik)
        return devre == DevreDurum.KESILDI

    # ================================================================ kademeli erit
    def _erit(self):
        simdi = time.time()
        for h in list(self.hedefler.values()):
            if h["erit_durumu"] != EritDurum.CALISIYOR:
                self.kova.pop(h["id"], None)
                continue
            if not h["aktif"] or h["devre_durumu"] != DevreDurum.NORMAL:
                self._erit_durdur(h, "hedef kapalı ya da devre kesik")
                continue
            if self.db.tek("SELECT 1 FROM tetik WHERE hedef_id=? AND durum=? AND sonraki_deneme<=? LIMIT 1",
                           (h["id"], TetikDurum.BEKLIYOR, simdi)):
                continue                                          # canlı tetikler önce
            hiz = float(h.get("erit_hizi") or self.ayar.al("erit_hizi"))
            jeton, son = self.kova.get(h["id"], [1.0, simdi])
            jeton = min(max(1.0, hiz), jeton + (simdi - son) * hiz)
            gonderilen = 0
            while jeton >= 1.0:
                with self.kilit:
                    if self.erit_yolda[h["id"]] or len(self.yolda[h["id"]]) >= self._esz(h):
                        break
                t = self.db.tek("SELECT * FROM tetik WHERE hedef_id=? AND durum=? ORDER BY olusturma, id LIMIT 1",
                                (h["id"], TetikDurum.LOKALDE))
                if t is None:
                    break
                t = dict(t)
                if not self._sahiplen(t["id"], (TetikDurum.LOKALDE,), TetikDurum.ERITILIYOR):
                    break
                with self.kilit:
                    self.yolda[h["id"]].add(t["id"])
                    self.erit_yolda[h["id"]].add(t["id"])
                self.havuz.submit(self._gonder, t, h, True)
                jeton -= 1.0
                gonderilen += 1
            self.kova[h["id"]] = [jeton, simdi]
            if gonderilen == 0:
                kalan = self.db.tek("SELECT COUNT(*) FROM tetik WHERE hedef_id=? AND durum IN (?,?)",
                                    (h["id"], TetikDurum.LOKALDE, TetikDurum.ERITILIYOR))[0]
                with self.kilit:
                    yolda = len(self.yolda[h["id"]])
                if kalan == 0 and yolda == 0:
                    self.yap.erit_durdur(h["id"], kullanici="sistem")
                    self.hedefler[h["id"]]["erit_durumu"] = EritDurum.YOK
                    self.db.alarm_kapat(f"hedef:{h['id']}:erit")
                    loglama.olay("ERIT_BITTI", hedef=h["ad"])

    def _erit_durdur(self, h, neden):
        mevcut = self.db.tek("SELECT erit_durumu FROM hedef WHERE id=?", (h["id"],))
        if mevcut and mevcut["erit_durumu"] == EritDurum.CALISIYOR:
            self.yap.erit_duraklat(h["id"], kullanici="sistem", neden=neden)
            if h["id"] in self.hedefler:
                self.hedefler[h["id"]]["erit_durumu"] = EritDurum.DURAKLATILDI
            self.db.alarm_ac(f"hedef:{h['id']}:erit", f"'{h['ad']}' için kademeli erit durdu: {neden}. Kalan kayıtlar "
                             f"lokalde güvende; hedef düzelince eriti yeniden başlatın.", AlarmSeviye.UYARI, "teslim")
            loglama.olay("ERIT_DURAKLADI", hedef=h["ad"], neden=neden)

    # ================================================================ periyodik işler
    def _periyodik(self):
        simdi = time.time()
        sayilar = {r["hedef_id"]: r["n"] for r in self.db.oku(
            "SELECT hedef_id, COUNT(*) n FROM tetik WHERE durum IN (?,?) GROUP BY hedef_id",
            (TetikDurum.LOKALDE, TetikDurum.ERITILIYOR))}
        for h in list(self.hedefler.values()):
            hid = h["id"]
            n = sayilar.get(hid, 0)
            if n != self.son_lokal_sayisi.get(hid):
                self.son_lokal_sayisi[hid] = n
                if n:
                    self.db.alarm_ac(f"hedef:{hid}:lokalde",
                                     f"'{h['ad']}' için {n} tetik lokalde bekliyor. Hedef erişilebilir olduğunda "
                                     f"'Kademeli erit' ile gönderin.", AlarmSeviye.UYARI, "teslim")
                else:
                    self.db.alarm_kapat(f"hedef:{hid}:lokalde")
            # sağlık yoklaması: kapalı hedef ya da kesik devre (tetik GÖNDERMEZ)
            if (not h["aktif"] or h["devre_durumu"] == DevreDurum.KESILDI) and hid not in self.saglik_yolda \
                    and simdi - self.son_saglik.get(hid, 0) > SAGLIK_ARALIGI_SN:
                self.son_saglik[hid] = simdi
                self.saglik_yolda.add(hid)
                self.havuz.submit(self._saglik_yokla, dict(h))
            self._yavaslik(h, simdi)
            # kapalı kalma hatırlatması (U13)
            self._kapali_hatirlat(f"hedef:{hid}:kapali", h, "hedef")
        for k in list(self.kurallar.values()):
            self._kapali_hatirlat(f"kural:{k['id']}:kapali", k, "kural")
        # yazılamamış lokal kayıtları yeniden dene (S3)
        for t in self.db.oku("SELECT * FROM tetik WHERE durum=? AND lokal_dosya IS NULL LIMIT 50",
                             (TetikDurum.LOKALDE,)):
            t = dict(t)
            h = self.hedefler.get(t["hedef_id"]) or {"ad": f"hedef{t['hedef_id']}"}
            try:
                yol = self.lokal.yaz({"idempotency": t["idempotency"], "tetik_id": t["id"], "dosya_id": t["dosya_id"],
                                      "kural_id": t["kural_id"], "hedef": h["ad"], "dosya_adi": t["dosya_adi"],
                                      "tam_yol": t["tam_yol"], "parametreler": json.loads(t["parametreler"]),
                                      "olusturma": t["olusturma"], "lokale_yazilma": simdi, "sebep": t["sebep"],
                                      "deneme_sayisi": t["deneme_sayisi"],
                                      "deneme_gecmisi": json.loads(t["deneme_gecmisi"] or "[]")})
                self.db.calistir("UPDATE tetik SET lokal_dosya=? WHERE id=?", (yol, t["id"]))
                self.db.alarm_kapat("lokal:yazilamadi")
            except OSError:
                break

    def _yavaslik(self, h, simdi):
        """H9: hedef yavaşlıyor. Pencerede canlı yoldan iletilen (erit hariç) tetiklerin SLA aşım oranı: ≥ %20 → uyarı
        (en az 5 tetik), < %5 ya da pencerede tetik yoksa → kapanır. Tek tek aşımlar ayrıca 'SLA aşıldı' olayıdır."""
        pencere = float(self.ayar.al("hedef_yavas_pencere_dk")) * 60
        son, acik = self.yavas.get(h["id"], (0.0, None))
        if simdi - son < min(30.0, pencere / 4):          # her turda değil; yazma yalnız durum değişince
            return
        r = self.db.tek("SELECT COUNT(*), COALESCE(SUM(sla_ihlali),0), AVG(sure_ms) FROM tetik WHERE hedef_id=? AND durum=? "
                        "AND eritildi=0 AND iletildi_zamani > ?", (h["id"], TetikDurum.ILETILDI, simdi - pencere))
        n, ihlal, ort = r[0], r[1], r[2]
        anahtar = f"hedef:{h['id']}:yavas"
        if n >= YAVAS_ASGARI and ihlal / n >= YAVAS_ACMA:
            self.db.alarm_ac(anahtar, f"'{h['ad']}' yavaşladı: son {pencere / 60:g} dakikada iletilen {n} tetikten {ihlal} "
                                      f"tanesi SLA hedefini ({float(self.ayar.al('sla_hedef_sn')):g} sn) aştı; ortalama "
                                      f"{(ort or 0) / 1000:.1f} sn.", AlarmSeviye.UYARI, "teslim")
            acik = True
        elif (n == 0 or ihlal / n < YAVAS_KAPAMA) and acik is not False:
            self.db.alarm_kapat(anahtar)                    # açılışta bir kez (eski alarm kalmışsa) ya da düzelince
            acik = False
        self.yavas[h["id"]] = (simdi, acik)

    def _kapali_hatirlat(self, anahtar, satir, tur):
        esik = float(self.ayar.al("kapali_hatirlatma_dk")) * 60
        if not satir["aktif"] and satir.get("kapatma_zamani") and time.time() - satir["kapatma_zamani"] > esik:
            dk = (time.time() - satir["kapatma_zamani"]) / 60
            self.db.alarm_ac(anahtar, f"{tur.capitalize()} '{satir['ad']}' {dk:.0f} dakikadır kapalı "
                             f"({satir['kapatma_modu']}). Unutulmadıysa sorun yok.", AlarmSeviye.UYARI, "teslim")
        elif satir["aktif"]:
            self.db.alarm_kapat(anahtar)

    def _saglik_yokla(self, h):
        try:
            ok, mesaj = self._adaptor(h).saglik(self._timeout(h))
        except Exception as e:
            ok, mesaj = False, f"yoklama hatası: {e}"
        finally:
            self.saglik_yolda.discard(h["id"])
        self.db.calistir("UPDATE hedef SET saglik=?, saglik_zamani=? WHERE id=?",
                         (("YANIT_VERIYOR: " if ok else "YANITSIZ: ") + mesaj[:200], time.time(), h["id"]))


if __name__ == "__main__":
    Dagitici.baslat()
