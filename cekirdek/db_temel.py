"""SQLite ortak tabanı (canli.db ve hata.db ikisi de bunu kullanır).

* WAL günlük modu: okuyanlar ve yazan birbirini beklemez.
* Her thread kendi bağlantısını kullanır (sqlite3 bağlantıları thread'ler arası paylaşılmaz).
* Yazmalar `with db.yaz() as con:` ile kısa, açık işlemler (BEGIN IMMEDIATE) içinde yapılır.
* Birden çok süreç (çekirdek + eklentiler) aynı dosyayı kullanır; busy_timeout + ek tekrar ile
  kilit çakışmaları beklenir.
* Veritabanı dosyaları YEREL diskte olmalıdır (SQLite ağ paylaşımı üzerinde güvenilir değildir).
"""
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class DB:
    SEMA = ""            # alt sınıf doldurur
    SEMA_SURUMU = 1
    EK_SUTUNLAR = ()     # (tablo, sütun, tanım): eski veritabanına sonradan eklenen sütunlar
    SENKRON = "NORMAL"   # alt sınıf değiştirebilir

    def __init__(self, yol):
        self.yol = Path(yol)
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        self._yerel = threading.local()
        self._tum_baglantilar = []
        self._kilit = threading.Lock()

    # ------------------------------------------------------------ bağlantı
    def baglanti(self) -> sqlite3.Connection:
        con = getattr(self._yerel, "con", None)
        if con is None:
            con = sqlite3.connect(str(self.yol), timeout=10, isolation_level=None)
            con.row_factory = sqlite3.Row
            # WAL'den ÖNCE: yalnızca boş (yeni) dosyada etkilidir; silinen satırların alanı
            # incremental_vacuum ile geri alınabilsin. Dolu veritabanında yok sayılır.
            con.execute("PRAGMA auto_vacuum=INCREMENTAL")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(f"PRAGMA synchronous={self.SENKRON}")
            con.execute("PRAGMA busy_timeout=10000")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA temp_store=MEMORY")
            self._yerel.con = con
            with self._kilit:
                self._tum_baglantilar.append(con)
        return con

    def kapat(self):
        with self._kilit:
            for c in self._tum_baglantilar:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
            self._tum_baglantilar.clear()
        self._yerel = threading.local()

    # ------------------------------------------------------------ çalıştırma
    def _tekrarla(self, fn):
        bekle = 0.05
        for deneme in range(8):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if "locked" not in str(e) and "busy" not in str(e):
                    raise
                if deneme == 7:
                    raise
                time.sleep(bekle)
                bekle = min(bekle * 2, 1.0)

    @contextmanager
    def yaz(self):
        """Kısa yazma işlemi. Hata olursa geri alınır."""
        con = self.baglanti()
        self._tekrarla(lambda: con.execute("BEGIN IMMEDIATE"))
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        else:
            self._tekrarla(lambda: con.execute("COMMIT"))

    def oku(self, sql: str, params=()) -> list:
        con = self.baglanti()
        return self._tekrarla(lambda: con.execute(sql, params).fetchall())

    def tek(self, sql: str, params=()):
        con = self.baglanti()
        return self._tekrarla(lambda: con.execute(sql, params).fetchone())

    def calistir(self, sql: str, params=()) -> int:
        """Tek ifadelik yazma; etkilenen satır sayısını döner."""
        with self.yaz() as con:
            return con.execute(sql, params).rowcount

    # ------------------------------------------------------------ şema ve meta
    def sema_kur(self):
        con = self.baglanti()
        self._tekrarla(lambda: con.executescript(self.SEMA))
        for tablo, sutun, tanim in self.EK_SUTUNLAR:        # eski sürümle oluşturulmuş veritabanı: eksik sütunu ekle
            if sutun not in {r[1] for r in con.execute(f"PRAGMA table_info({tablo})")}:
                try:
                    self._tekrarla(lambda: con.execute(f"ALTER TABLE {tablo} ADD COLUMN {sutun} {tanim}"))
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e):     # başka süreç aynı anda eklediyse sorun yok
                        raise
        with self.yaz() as c:
            c.execute("INSERT OR IGNORE INTO meta(anahtar, deger) VALUES('sema_surumu', ?)",
                      (str(self.SEMA_SURUMU),))
        return self

    def meta_al(self, anahtar: str, varsayilan=None):
        s = self.tek("SELECT deger FROM meta WHERE anahtar=?", (anahtar,))
        return s["deger"] if s else varsayilan

    def meta_yaz(self, anahtar: str, deger, con=None):
        sql = ("INSERT INTO meta(anahtar, deger) VALUES(?, ?) "
               "ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger")
        if con is not None:
            con.execute(sql, (anahtar, str(deger)))
        else:
            self.calistir(sql, (anahtar, str(deger)))

    def surum_artir(self, anahtar: str, con):
        con.execute("INSERT INTO meta(anahtar, deger) VALUES(?, '1') "
                    "ON CONFLICT(anahtar) DO UPDATE SET deger=CAST(CAST(deger AS INTEGER)+1 AS TEXT)",
                    (anahtar,))

    # ------------------------------------------------------------ bakım
    def bakim(self) -> dict:
        """REINDEX + ANALYZE + WAL checkpoint (TRUNCATE). Süre bilgisi döner."""
        con = self.baglanti()
        t0 = time.perf_counter()
        self._tekrarla(lambda: con.execute("REINDEX"))
        self._tekrarla(lambda: con.execute("ANALYZE"))
        cp = self._tekrarla(lambda: con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        return {"sure_ms": int((time.perf_counter() - t0) * 1000), "checkpoint": tuple(cp) if cp else None}

    def pragma(self, ad: str):
        return self.tek(f"PRAGMA {ad}")[0]

    def boyut_mb(self) -> float:
        return self.pragma("page_count") * self.pragma("page_size") / 1024 / 1024

    def butunluk(self) -> list:
        """PRAGMA quick_check: sağlamsa boş liste, değilse sorun satırları (en fazla 20)."""
        satirlar = [r[0] for r in self._tekrarla(lambda: self.baglanti().execute("PRAGMA quick_check(20)").fetchall())]
        return [] if satirlar == ["ok"] else satirlar

    def yedekle(self, hedef: Path) -> dict:
        """SQLite çevrimiçi yedek (çalışan sistemi durdurmadan, tutarlı anlık kopya). Önceki yedek '.onceki'
        adıyla saklanır; yeni yedek önce geçici dosyaya yazılır, bütünlüğü doğrulanınca yerine konur."""
        hedef = Path(hedef)
        hedef.parent.mkdir(parents=True, exist_ok=True)
        gecici = hedef.with_suffix(".yaziliyor")
        t0 = time.perf_counter()
        if gecici.exists():
            gecici.unlink()
        dst = sqlite3.connect(str(gecici))
        try:
            self._tekrarla(lambda: self.baglanti().backup(dst))
            kontrol = [r[0] for r in dst.execute("PRAGMA quick_check(5)").fetchall()]
        finally:
            dst.close()
        if kontrol != ["ok"]:
            gecici.unlink(missing_ok=True)
            raise RuntimeError(f"yedek doğrulanamadı: {kontrol}")
        not_ = None
        try:
            if hedef.exists():
                os.replace(hedef, hedef.with_name(hedef.stem + ".onceki" + hedef.suffix))
            os.replace(gecici, hedef)
        except PermissionError:
            # önceki yedek başka bir program tarafından açık (görüntüleyici, antivirüs): onu bozmadan yeni kopyayı
            # zaman damgalı ada yaz; bakım bu yüzden durmasın. Eski zaman damgalı kopyalardan son 3'ü kalır.
            yedek_ad = hedef.with_name(f"{hedef.stem}.{time.strftime('%Y%m%d_%H%M%S')}{hedef.suffix}")
            os.replace(gecici, yedek_ad)
            for eski in sorted(hedef.parent.glob(f"{hedef.stem}.2*{hedef.suffix}"))[:-3]:
                try:
                    eski.unlink()
                except OSError:
                    pass
            hedef, not_ = yedek_ad, "önceki yedek başka bir programda açık; yeni kopya ayrı adla yazıldı"
        return {"yol": str(hedef), "mb": round(hedef.stat().st_size / 1024 / 1024, 2),
                "sure_ms": int((time.perf_counter() - t0) * 1000), "not": not_}


def js(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
