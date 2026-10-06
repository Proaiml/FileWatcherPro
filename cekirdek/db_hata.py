"""hata.db — Control-M'e gitmeyen dosyalar, denetim kaydı ve kesinti kaydı.

Kayıpsızlık önemli olduğu için synchronous=FULL.

Sınırlar:
  * gonderilemeyen: toplam 'hata_limit' (varsayılan 1000). Çözülmemiş (hiç gönderilmemiş) kayıtlar
    ASLA silinmez; budama yalnızca çözülmüşlerden yapılır. Çözülmemişler sınırı aşarsa alarm verilir.
  * denetim: 'denetim_limit' (varsayılan 2000).
  * kesinti: son 500.
"""
import time

from .db_temel import DB, js

SEMA = """
CREATE TABLE IF NOT EXISTS meta (anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS gonderilemeyen (
  id INTEGER PRIMARY KEY,
  anahtar TEXT NOT NULL,                 -- tetik idempotency anahtarı ya da (ESLESMEDI için) dosya kimliği
  sebep TEXT NOT NULL,
  tetik_id INTEGER,
  dosya_adi TEXT NOT NULL, tam_yol TEXT NOT NULL,
  dizin_yolu TEXT, kural_ad TEXT, hedef_ad TEXT,
  sebep_detay TEXT,
  ilk_zaman REAL NOT NULL, son_zaman REAL NOT NULL,
  deneme_sayisi INTEGER NOT NULL DEFAULT 0,
  deneme_gecmisi TEXT NOT NULL DEFAULT '[]',
  lokal_dosya TEXT,
  cozuldu INTEGER NOT NULL DEFAULT 0, cozulme_zamani REAL, cozum TEXT,
  UNIQUE(anahtar, sebep));
CREATE INDEX IF NOT EXISTS ix_gon_cozuldu ON gonderilemeyen(cozuldu, son_zaman);
CREATE INDEX IF NOT EXISTS ix_gon_tetik ON gonderilemeyen(tetik_id);

CREATE TABLE IF NOT EXISTS denetim (
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL,
  kullanici TEXT NOT NULL, kaynak TEXT NOT NULL,
  islem TEXT NOT NULL, nesne TEXT,
  eski TEXT, yeni TEXT);
CREATE INDEX IF NOT EXISTS ix_denetim_zaman ON denetim(zaman);

CREATE TABLE IF NOT EXISTS kesinti (
  id INTEGER PRIMARY KEY, tur TEXT NOT NULL, nesne TEXT NOT NULL,
  basladi REAL NOT NULL, bitti REAL, aciklama TEXT);
CREATE INDEX IF NOT EXISTS ix_kesinti ON kesinti(tur, nesne, basladi);
"""


class HataDB(DB):
    SEMA = SEMA
    SEMA_SURUMU = 1
    SENKRON = "FULL"

    # ------------------------------------------------------------ gönderilemeyen
    def gonderilemeyen_yaz(self, anahtar: str, sebep: str, dosya_adi: str, tam_yol: str, *,
                           tetik_id=None, dizin_yolu=None, kural_ad=None, hedef_ad=None,
                           sebep_detay=None, deneme_sayisi=0, deneme_gecmisi=None, lokal_dosya=None) -> int:
        simdi = time.time()
        with self.yaz() as con:
            con.execute(
                "INSERT INTO gonderilemeyen(anahtar, sebep, tetik_id, dosya_adi, tam_yol, dizin_yolu, kural_ad, "
                " hedef_ad, sebep_detay, ilk_zaman, son_zaman, deneme_sayisi, deneme_gecmisi, lokal_dosya) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(anahtar, sebep) DO UPDATE SET son_zaman=excluded.son_zaman, "
                " sebep_detay=excluded.sebep_detay, deneme_sayisi=excluded.deneme_sayisi, "
                " deneme_gecmisi=excluded.deneme_gecmisi, lokal_dosya=COALESCE(excluded.lokal_dosya, lokal_dosya), "
                " cozuldu=0, cozulme_zamani=NULL, cozum=NULL",
                (anahtar, sebep, tetik_id, dosya_adi, tam_yol, dizin_yolu, kural_ad, hedef_ad, sebep_detay,
                 simdi, simdi, deneme_sayisi, js(deneme_gecmisi or []), lokal_dosya))
            return con.execute("SELECT id FROM gonderilemeyen WHERE anahtar=? AND sebep=?",
                               (anahtar, sebep)).fetchone()[0]

    def cozuldu_isaretle(self, anahtar: str, cozum: str) -> int:
        return self.calistir("UPDATE gonderilemeyen SET cozuldu=1, cozulme_zamani=?, cozum=? "
                             "WHERE anahtar=? AND cozuldu=0", (time.time(), cozum, anahtar))

    def cozulmemis_sayisi(self) -> int:
        return self.tek("SELECT COUNT(*) FROM gonderilemeyen WHERE cozuldu=0")[0]

    # ------------------------------------------------------------ denetim
    def denetim_yaz(self, islem: str, nesne: str = None, eski=None, yeni=None,
                    kullanici: str = "sistem", kaynak: str = "cekirdek"):
        self.calistir("INSERT INTO denetim(zaman, kullanici, kaynak, islem, nesne, eski, yeni) VALUES(?,?,?,?,?,?,?)",
                      (time.time(), kullanici, kaynak, islem, nesne,
                       None if eski is None else js(eski), None if yeni is None else js(yeni)))

    # ------------------------------------------------------------ kesinti
    def kesinti_basla(self, tur: str, nesne: str, aciklama: str = None) -> int:
        with self.yaz() as con:
            acik = con.execute("SELECT id FROM kesinti WHERE tur=? AND nesne=? AND bitti IS NULL",
                               (tur, nesne)).fetchone()
            if acik:
                return acik[0]
            return con.execute("INSERT INTO kesinti(tur, nesne, basladi, aciklama) VALUES(?,?,?,?)",
                               (tur, nesne, time.time(), aciklama)).lastrowid

    def kesinti_bitir(self, tur: str, nesne: str) -> int:
        return self.calistir("UPDATE kesinti SET bitti=? WHERE tur=? AND nesne=? AND bitti IS NULL",
                             (time.time(), tur, nesne))

    # ------------------------------------------------------------ budama
    def buda(self, hata_limit: int, denetim_limit: int, con=None) -> dict:
        if con is None:
            with self.yaz() as c:
                return self.buda(hata_limit, denetim_limit, c)
        if True:
            toplam = con.execute("SELECT COUNT(*) FROM gonderilemeyen").fetchone()[0]
            fazla = max(0, toplam - hata_limit)
            g = 0
            if fazla:
                g = con.execute("DELETE FROM gonderilemeyen WHERE id IN ("
                                " SELECT id FROM gonderilemeyen WHERE cozuldu=1 ORDER BY son_zaman LIMIT ?)",
                                (fazla,)).rowcount
            d = con.execute("DELETE FROM denetim WHERE id NOT IN (SELECT id FROM denetim ORDER BY id DESC LIMIT ?)",
                            (denetim_limit,)).rowcount
            k = con.execute("DELETE FROM kesinti WHERE bitti IS NOT NULL AND id NOT IN ("
                            " SELECT id FROM kesinti ORDER BY id DESC LIMIT 500)").rowcount
            cozulmemis = con.execute("SELECT COUNT(*) FROM gonderilemeyen WHERE cozuldu=0").fetchone()[0]
        return {"gonderilemeyen": g, "denetim": d, "kesinti": k, "cozulmemis": cozulmemis,
                "sinir_asildi": cozulmemis > hata_limit}
