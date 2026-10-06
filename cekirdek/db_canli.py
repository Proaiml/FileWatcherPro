"""canli.db — hıza odaklı, önyüzü besleyen veritabanı.

İçerik: yapılandırma (dizin, kural, hedef, ayar), yüklenmekte olan dosyalar, aktif dosyalar +
son N geçmiş, tetik kuyruğu, eklenti sağlığı, komutlar, alarmlar.

Sınırlar (bkz. Tasarım kriterleri):
  * Dizinde hâlâ duran (aktif) dosyalar ve gönderilmeyi bekleyen tetikler ASLA budanmaz.
  * Geçmiş (dizinden kalkmış dosyalar, bitmiş tetikler, kapanmış alarmlar, işlenmiş komutlar)
    'gecmis_limit' (varsayılan 200) ile sınırlıdır.
"""
import time

from .db_temel import DB, js
from .model import TetikDurum, AlarmSeviye

SEMA = """
CREATE TABLE IF NOT EXISTS meta (anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS ayar (
  anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL, guncelleme REAL NOT NULL);

CREATE TABLE IF NOT EXISTS dizin (
  id INTEGER PRIMARY KEY,
  yol TEXT NOT NULL UNIQUE COLLATE NOCASE,
  ad TEXT NOT NULL DEFAULT '',
  aktif INTEGER NOT NULL DEFAULT 1,
  uzantilar TEXT NOT NULL DEFAULT '',                 -- '.csv,.txt' (boş = hepsi)
  ilk_kurulum_modu TEXT NOT NULL DEFAULT 'TEMEL_AL',   -- TEMEL_AL | TETIKLE
  ilk_tarama_yapildi INTEGER NOT NULL DEFAULT 0,
  erisim_durumu TEXT NOT NULL DEFAULT 'BILINMIYOR',
  erisim_degisim REAL,
  son_tarama REAL, son_tarama_ms INTEGER, dosya_sayisi INTEGER,
  ardisik_hata INTEGER NOT NULL DEFAULT 0, sonraki_deneme REAL,
  son_hata TEXT,
  olusturma REAL NOT NULL, guncelleme REAL NOT NULL);

CREATE TABLE IF NOT EXISTS hedef (
  id INTEGER PRIMARY KEY,
  ad TEXT NOT NULL UNIQUE,
  tur TEXT NOT NULL DEFAULT 'CONTROLM',
  adres TEXT NOT NULL,
  ayrintilar TEXT NOT NULL DEFAULT '{}',               -- ctm sunucu adı, kimlik_ref, kimlik türü (JSON)
  timeout_sn REAL, deneme_plani TEXT, esz_cagri_ust INTEGER,   -- boşsa genel ayar
  aktif INTEGER NOT NULL DEFAULT 1,
  kapatma_modu TEXT NOT NULL DEFAULT 'KAYITLI',
  kapatma_zamani REAL, kapatan TEXT,
  devre_durumu TEXT NOT NULL DEFAULT 'NORMAL', devre_degisim REAL,
  ardisik_hata INTEGER NOT NULL DEFAULT 0,
  erit_durumu TEXT NOT NULL DEFAULT 'YOK', erit_hizi REAL, erit_degisim REAL,
  saglik TEXT, saglik_zamani REAL,                       -- kapalı/devre kesikken yoklama sonucu
  olusturma REAL NOT NULL, guncelleme REAL NOT NULL);

CREATE TABLE IF NOT EXISTS kural (
  id INTEGER PRIMARY KEY,
  dizin_id INTEGER NOT NULL REFERENCES dizin(id) ON DELETE CASCADE,
  ad TEXT NOT NULL,
  regex TEXT NOT NULL,
  harf_duyarsiz INTEGER NOT NULL DEFAULT 1,
  sira INTEGER NOT NULL DEFAULT 100,
  hedef_id INTEGER NOT NULL REFERENCES hedef(id),
  is_bilgisi TEXT NOT NULL DEFAULT '{}',              -- eski biçim: folder, jobs (istek yoksa run/order)
  istek TEXT,                                         -- tetiklenecek istek: {yontem, yol, govde} (JSON)
  aktif INTEGER NOT NULL DEFAULT 1,
  kapatma_modu TEXT NOT NULL DEFAULT 'KAYITLI',
  kapatma_zamani REAL, kapatan TEXT,
  olusturma REAL NOT NULL, guncelleme REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_kural_dizin ON kural(dizin_id, sira);

CREATE TABLE IF NOT EXISTS yukleme (
  dizin_id INTEGER NOT NULL, ad_anahtar TEXT NOT NULL,
  dosya_adi TEXT NOT NULL, tam_yol TEXT NOT NULL,
  durum TEXT NOT NULL,
  boyut INTEGER, mtime_ns INTEGER, ilk_gorulme REAL NOT NULL, son_buyume REAL NOT NULL, son_kontrol REAL NOT NULL,
  aciklama TEXT,
  PRIMARY KEY (dizin_id, ad_anahtar));

CREATE TABLE IF NOT EXISTS dosya (
  id INTEGER PRIMARY KEY,
  dizin_id INTEGER NOT NULL,
  dosya_adi TEXT NOT NULL, ad_anahtar TEXT NOT NULL, tam_yol TEXT NOT NULL,
  boyut INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  kimlik TEXT NOT NULL, icerik_hash TEXT, hash_suresi_ms INTEGER,
  durum TEXT NOT NULL, kural_id INTEGER,
  ilk_gorulme REAL NOT NULL, hazir_zamani REAL NOT NULL, kalkma_zamani REAL,
  aciklama TEXT,
  icerik_degisim INTEGER NOT NULL DEFAULT 0, son_icerik_degisimi REAL,
  dosya_no INTEGER);          -- Windows dosya numarası (NTFS file ID): yerinde değişimde aynı, sil+yeniden yazmada farklı   -- B5: dizinde dururken içerik değişimi (tetik yok)
CREATE UNIQUE INDEX IF NOT EXISTS ux_dosya_aktif ON dosya(dizin_id, ad_anahtar) WHERE kalkma_zamani IS NULL;
CREATE INDEX IF NOT EXISTS ix_dosya_kalkma ON dosya(kalkma_zamani);
CREATE INDEX IF NOT EXISTS ix_dosya_hazir ON dosya(hazir_zamani);

CREATE TABLE IF NOT EXISTS tetik (
  id INTEGER PRIMARY KEY,
  dosya_id INTEGER NOT NULL, kural_id INTEGER NOT NULL, hedef_id INTEGER NOT NULL,
  idempotency TEXT NOT NULL UNIQUE,
  parametreler TEXT NOT NULL,
  dosya_adi TEXT NOT NULL, tam_yol TEXT NOT NULL,
  durum TEXT NOT NULL,
  olusturma REAL NOT NULL,
  deneme_sayisi INTEGER NOT NULL DEFAULT 0, sonraki_deneme REAL,
  sahip TEXT, ilk_deneme REAL, son_deneme REAL,
  iletildi_zamani REAL, sure_ms INTEGER, sla_ihlali INTEGER NOT NULL DEFAULT 0,
  son_http_kodu INTEGER, son_hata TEXT, sonuc TEXT,
  lokal_dosya TEXT, kapanis REAL,
  deneme_gecmisi TEXT NOT NULL DEFAULT '[]', belirsiz INTEGER NOT NULL DEFAULT 0, sebep TEXT,
  eritildi INTEGER NOT NULL DEFAULT 0,
  elle INTEGER NOT NULL DEFAULT 0);                    -- lokalden önyüzde seçilerek gönderildi (SLA dışı, erit gibi)
CREATE INDEX IF NOT EXISTS ix_tetik_kuyruk ON tetik(durum, sonraki_deneme);
CREATE INDEX IF NOT EXISTS ix_tetik_kapanis ON tetik(kapanis);
DROP INDEX IF EXISTS ix_tetik_hedef;                  -- yerini sıralı sürümü aldı (erit: geliş sırası O(1))
CREATE INDEX IF NOT EXISTS ix_tetik_hedef_sira ON tetik(hedef_id, durum, olusturma, id);
CREATE INDEX IF NOT EXISTS ix_tetik_durum_olusturma ON tetik(durum, olusturma);   -- önyüz listeleri
CREATE INDEX IF NOT EXISTS ix_tetik_dosya ON tetik(dosya_id);                      -- dosya → tetik birleştirme

CREATE TABLE IF NOT EXISTS eklenti (
  ad TEXT PRIMARY KEY, modul TEXT NOT NULL,
  durum TEXT NOT NULL, istenen TEXT NOT NULL DEFAULT 'CALIS',
  pid INTEGER, baslama REAL, son_nabiz REAL, son_ilerleme REAL,
  yeniden_baslatma INTEGER NOT NULL DEFAULT 0, ardisik_dusme INTEGER NOT NULL DEFAULT 0,
  son_cikis_kodu INTEGER, son_hata TEXT, sonraki_baslatma REAL,
  bilgi TEXT NOT NULL DEFAULT '{}', guncelleme REAL NOT NULL);

CREATE TABLE IF NOT EXISTS komut (
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL,
  alici TEXT NOT NULL, komut TEXT NOT NULL, parametre TEXT NOT NULL DEFAULT '{}',
  kullanici TEXT, durum TEXT NOT NULL DEFAULT 'BEKLIYOR', sonuc TEXT, isleme_zamani REAL);
CREATE INDEX IF NOT EXISTS ix_komut ON komut(alici, durum);

CREATE TABLE IF NOT EXISTS alarm (
  id INTEGER PRIMARY KEY, anahtar TEXT NOT NULL,
  seviye TEXT NOT NULL, kaynak TEXT NOT NULL, mesaj TEXT NOT NULL,
  ilk_zaman REAL NOT NULL, son_zaman REAL NOT NULL, tekrar INTEGER NOT NULL DEFAULT 1,
  aktif INTEGER NOT NULL DEFAULT 1, kapanma_zamani REAL, onaylayan TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ux_alarm_aktif ON alarm(anahtar) WHERE aktif = 1;
CREATE INDEX IF NOT EXISTS ix_alarm_kapanma ON alarm(kapanma_zamani);

CREATE TABLE IF NOT EXISTS olcum (                   -- sistem izleme: son 24 saat (izleme eklentisi yazar ve budar)
  zaman REAL PRIMARY KEY,
  sunucu_cpu REAL, sunucu_ram REAL, fwp_cpu REAL, fwp_ram_mb REAL, disk_bos_mb REAL);

CREATE TABLE IF NOT EXISTS bildirim_kural (          -- hangi olaylar, hangi dizinler, kime (önyüz: Bildirimler)
  id INTEGER PRIMARY KEY, ad TEXT NOT NULL,
  alicilar TEXT NOT NULL, olaylar TEXT NOT NULL,     -- JSON listeler (olay kodları: cekirdek/olaylar.py)
  seviye TEXT NOT NULL DEFAULT 'UYARI',              -- en az bu seviye
  dizinler TEXT,                                      -- JSON dizin id listesi; NULL = tüm dizinler
  kurallar TEXT,                                      -- JSON kural id listesi; NULL = kural kapsamı yok (kural penceresinden bağlanan)
  ozet_dk INTEGER NOT NULL DEFAULT 0,                -- 0 = anında; >0 = bu aralıkta biriken tek mailde
  tekrar_dk INTEGER NOT NULL DEFAULT 60,             -- aynı olay en fazla bu aralıkla yeniden bildirilir
  duzelince INTEGER NOT NULL DEFAULT 1, aktif INTEGER NOT NULL DEFAULT 1,
  olusturma REAL NOT NULL, guncelleme REAL NOT NULL);

CREATE TABLE IF NOT EXISTS bildirim_olay (           -- bir kurala uyan olay (mail_id NULL: özette bekliyor)
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL, kural_id INTEGER NOT NULL,
  olay_anahtar TEXT NOT NULL, kod TEXT NOT NULL, seviye TEXT NOT NULL, tur TEXT NOT NULL,   -- ACILDI | DUZELDI | SURUYOR
  baslik TEXT NOT NULL, metin TEXT NOT NULL, mail_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_bolay_kural ON bildirim_olay(kural_id, olay_anahtar, zaman);
CREATE INDEX IF NOT EXISTS ix_bolay_mail ON bildirim_olay(mail_id);

CREATE TABLE IF NOT EXISTS bildirim_mail (           -- gönderim kuyruğu + geçmiş
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL, kural_ad TEXT,
  alicilar TEXT NOT NULL, konu TEXT NOT NULL, govde TEXT NOT NULL, olay_sayisi INTEGER NOT NULL DEFAULT 1,
  durum TEXT NOT NULL DEFAULT 'BEKLIYOR',             -- BEKLIYOR | GONDERILDI | HATA
  deneme INTEGER NOT NULL DEFAULT 0, sonraki_deneme REAL, gonderim_zamani REAL, hata TEXT);
CREATE INDEX IF NOT EXISTS ix_bmail_durum ON bildirim_mail(durum, sonraki_deneme);

CREATE TABLE IF NOT EXISTS sayac (
  gun TEXT NOT NULL, anahtar TEXT NOT NULL, deger INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (gun, anahtar));
"""


class CanliDB(DB):
    SEMA = SEMA
    SEMA_SURUMU = 1
    EK_SUTUNLAR = (("dosya", "icerik_degisim", "INTEGER NOT NULL DEFAULT 0"),
                   ("dosya", "son_icerik_degisimi", "REAL"),
                   ("dosya", "dosya_no", "INTEGER"),
                   ("kural", "istek", "TEXT"),
                   ("bildirim_kural", "kurallar", "TEXT"),
                   ("tetik", "elle", "INTEGER NOT NULL DEFAULT 0"))
    SENKRON = "NORMAL"

    # ------------------------------------------------------------ ayar
    def ayar_yaz(self, anahtar: str, deger):
        with self.yaz() as con:
            con.execute("INSERT INTO ayar(anahtar, deger, guncelleme) VALUES(?,?,?) "
                        "ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger, guncelleme=excluded.guncelleme",
                        (anahtar, js(deger), time.time()))
            self.surum_artir("ayar_surumu", con)

    def yapilandirma_degisti(self, con):
        """dizin/kural/hedef değişikliklerinden sonra çağrılır; eklentiler sürümü izler."""
        self.surum_artir("yapilandirma_surumu", con)

    # ------------------------------------------------------------ eklenti sağlığı
    def eklenti_kaydet(self, ad: str, modul: str, **alanlar):
        simdi = time.time()
        with self.yaz() as con:
            con.execute("INSERT INTO eklenti(ad, modul, durum, guncelleme) VALUES(?,?,?,?) "
                        "ON CONFLICT(ad) DO UPDATE SET modul=excluded.modul",
                        (ad, modul, alanlar.get("durum", "BASLIYOR"), simdi))
            if alanlar:
                self._eklenti_guncelle(con, ad, alanlar)

    def eklenti_guncelle(self, ad: str, **alanlar):
        with self.yaz() as con:
            self._eklenti_guncelle(con, ad, alanlar)

    @staticmethod
    def _eklenti_guncelle(con, ad, alanlar):
        alanlar = dict(alanlar)
        alanlar["guncelleme"] = time.time()
        if "bilgi" in alanlar and not isinstance(alanlar["bilgi"], str):
            alanlar["bilgi"] = js(alanlar["bilgi"])
        kolonlar = ", ".join(f"{k}=?" for k in alanlar)
        con.execute(f"UPDATE eklenti SET {kolonlar} WHERE ad=?", (*alanlar.values(), ad))

    def eklenti(self, ad: str):
        return self.tek("SELECT * FROM eklenti WHERE ad=?", (ad,))

    # ------------------------------------------------------------ komutlar
    def komut_gonder(self, alici: str, komut: str, parametre=None, kullanici: str = "sistem") -> int:
        with self.yaz() as con:
            cur = con.execute("INSERT INTO komut(zaman, alici, komut, parametre, kullanici) VALUES(?,?,?,?,?)",
                              (time.time(), alici, komut, js(parametre or {}), kullanici))
            return cur.lastrowid

    def komutlari_al(self, alici: str) -> list:
        return self.oku("SELECT * FROM komut WHERE alici=? AND durum='BEKLIYOR' ORDER BY id", (alici,))

    def komut_bitir(self, komut_id: int, sonuc: str, durum: str = "ISLENDI"):
        self.calistir("UPDATE komut SET durum=?, sonuc=?, isleme_zamani=? WHERE id=?",
                      (durum, sonuc, time.time(), komut_id))

    # ------------------------------------------------------------ alarmlar
    def alarm_ac(self, anahtar: str, mesaj: str, seviye: str = AlarmSeviye.UYARI, kaynak: str = "cekirdek") -> bool:
        """Alarmı açar; aynı anahtarla aktif alarm varsa tekrar sayısını artırır. Yeni açıldıysa True."""
        simdi = time.time()
        with self.yaz() as con:
            cur = con.execute("UPDATE alarm SET son_zaman=?, tekrar=tekrar+1, mesaj=?, seviye=? "
                              "WHERE anahtar=? AND aktif=1", (simdi, mesaj, seviye, anahtar))
            if cur.rowcount:
                return False
            con.execute("INSERT INTO alarm(anahtar, seviye, kaynak, mesaj, ilk_zaman, son_zaman) VALUES(?,?,?,?,?,?)",
                        (anahtar, seviye, kaynak, mesaj, simdi, simdi))
            return True

    def alarm_kapat(self, anahtar: str, onaylayan: str = None) -> bool:
        return self.calistir("UPDATE alarm SET aktif=0, kapanma_zamani=?, onaylayan=? WHERE anahtar=? AND aktif=1",
                             (time.time(), onaylayan, anahtar)) > 0

    def aktif_alarmlar(self) -> list:
        return self.oku("SELECT * FROM alarm WHERE aktif=1 ORDER BY "
                        "CASE seviye WHEN 'KRITIK' THEN 0 WHEN 'UYARI' THEN 1 ELSE 2 END, son_zaman DESC")

    # ------------------------------------------------------------ günlük sayaçlar (önyüz: "bugün")
    def sayac_artir(self, anahtar: str, n: int = 1, con=None):
        sql = ("INSERT INTO sayac(gun, anahtar, deger) VALUES(date('now','localtime'), ?, ?) "
               "ON CONFLICT(gun, anahtar) DO UPDATE SET deger=deger+excluded.deger")
        if con is not None:
            con.execute(sql, (anahtar, n))
        else:
            self.calistir(sql, (anahtar, n))

    def sayaclar(self, gun: str = None) -> dict:
        rows = self.oku("SELECT anahtar, deger FROM sayac WHERE gun=COALESCE(?, date('now','localtime'))", (gun,))
        return {r["anahtar"]: r["deger"] for r in rows}

    # ------------------------------------------------------------ budama
    def gecmisi_buda(self, limit: int, con=None) -> dict:
        """Yalnızca geçmişi budar; aktif dosyalar ve bekleyen tetikler asla silinmez. `con` verilirse o işlemin
        içinde çalışır (bakım: budama ve kontrol tek işlem; hata olursa tamamı geri alınır)."""
        if con is None:
            with self.yaz() as c:
                return self.gecmisi_buda(limit, c)
        bitmis = ",".join(f"'{d}'" for d in TetikDurum.BITMIS)
        if True:
            d = con.execute(
                "DELETE FROM dosya WHERE kalkma_zamani IS NOT NULL AND id NOT IN ("
                " SELECT id FROM dosya WHERE kalkma_zamani IS NOT NULL ORDER BY kalkma_zamani DESC LIMIT ?)",
                (limit,)).rowcount
            t = con.execute(
                f"DELETE FROM tetik WHERE durum IN ({bitmis}) AND id NOT IN ("
                f" SELECT id FROM tetik WHERE durum IN ({bitmis}) ORDER BY kapanis DESC LIMIT ?)",
                (limit,)).rowcount
            a = con.execute(
                "DELETE FROM alarm WHERE aktif=0 AND id NOT IN ("
                " SELECT id FROM alarm WHERE aktif=0 ORDER BY kapanma_zamani DESC LIMIT ?)", (limit,)).rowcount
            k = con.execute(
                "DELETE FROM komut WHERE durum<>'BEKLIYOR' AND id NOT IN ("
                " SELECT id FROM komut WHERE durum<>'BEKLIYOR' ORDER BY id DESC LIMIT ?)", (limit,)).rowcount
            con.execute("DELETE FROM sayac WHERE gun < date('now','localtime','-90 day')")
        return {"dosya": d, "tetik": t, "alarm": a, "komut": k}
