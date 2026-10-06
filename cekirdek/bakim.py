"""Haftalık bakım (varsayılan Cumartesi 03:00; gün ve saat önyüzden değişir).

Yapılanlar (her iki veritabanında):
  * limit budaması (canli: gecmis_limit, hata: hata_limit / denetim_limit),
  * REINDEX (index'leri baştan kurar), ANALYZE (sorgu planlayıcı istatistikleri),
  * WAL checkpoint (TRUNCATE) — WAL dosyasını sıfırlar,
  * incremental_vacuum — silinen satırların disk alanını geri verir,
  * boyut kontrolü: veritabanı beklenmedik şekilde büyümüşse alarm.

Zamanlama: gözetmen her turda `zamani_geldi_mi()` sorar. Makine bakım saatinde kapalıysa bakım açılışta
yapılır (kaçırılan son bakım zamanından sonra hiç bakım yapılmadıysa). Önyüzden 'şimdi bakım yap' da vardır.
"""
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from . import loglama
from .model import AlarmSeviye

GUNLER = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
BOYUT_ALARM_MB = 256


def son_planli_zaman(simdi: datetime, gun: str, saat: str) -> datetime:
    """`simdi`den önceki (ya da eşit) en son planlı bakım anı."""
    hedef_gun = GUNLER.index(gun)
    ss, dd = (int(x) for x in saat.split(":"))
    aday = simdi.replace(hour=ss, minute=dd, second=0, microsecond=0) - timedelta(days=(simdi.weekday() - hedef_gun) % 7)
    if aday > simdi:
        aday -= timedelta(days=7)
    return aday


def sonraki_planli_zaman(simdi: datetime, gun: str, saat: str) -> datetime:
    return son_planli_zaman(simdi, gun, saat) + timedelta(days=7)


class Bakim:
    def __init__(self, db, hdb, ayar):
        self.db, self.hdb, self.ayar = db, hdb, ayar

    def zamani_geldi_mi(self, simdi: float = None) -> bool:
        simdi = simdi or time.time()
        planli = son_planli_zaman(datetime.fromtimestamp(simdi), self.ayar.al("bakim_gunu"), self.ayar.al("bakim_saati"))
        son = float(self.db.meta_al("son_bakim", "0") or 0)
        return son < planli.timestamp() <= simdi

    # (anahtar, önyüzde görünen ad)
    ADIMLAR = (("on_kontrol", "Ön kontrol (bütünlük)"), ("yedek", "Son sağlam kopya (yedek)"),
               ("budama_canli", "Budama: canli.db"), ("budama_hata", "Budama: hata.db"),
               ("reindex_canli", "REINDEX + ANALYZE: canli.db"), ("reindex_hata", "REINDEX + ANALYZE: hata.db"),
               ("checkpoint", "WAL checkpoint + boş alan"))

    def calistir(self, kullanici: str = "zamanlayıcı") -> dict:
        """Bakım adım adım yapılır; her adım kendi SQLite işlemi içindedir. Bir adım hata verirse O ADIM tamamen
        geri alınır (veritabanı o adımdan önceki çalışan hâlinde kalır), kalan adımlar çalıştırılmaz, son kontrol
        yapılır ve alarm açılır. Tarama ve teslim bu sürede çalışmaya devam eder (kilitler milisaniyelerdir)."""
        t0 = time.perf_counter()
        sonuc = {"basladi": time.time(), "kullanici": kullanici, "adimlar": []}
        self.db.meta_yaz("bakim_suruyor", _kisa({"basladi": sonuc["basladi"], "kullanici": kullanici}))
        dbler = (("canli", self.db), ("hata", self.hdb))
        once = {ad: round(d.boyut_mb(), 2) for ad, d in dbler}
        yedek_klasoru = Path(self.db.yol).parent / "yedek"
        isler = {
            "on_kontrol": lambda: self._butunluk_denetle(dbler, "on"),
            "yedek": lambda: {ad: d.yedekle(yedek_klasoru / f"{ad}.db") for ad, d in dbler},
            "budama_canli": lambda: self._islemde(self.db, "budama_canli",
                                                  lambda con: self.db.gecmisi_buda(int(self.ayar.al("gecmis_limit")), con)),
            "budama_hata": lambda: self._islemde(self.hdb, "budama_hata", lambda con: self.hdb.buda(
                int(self.ayar.al("hata_limit")), int(self.ayar.al("denetim_limit")), con)),
            "reindex_canli": lambda: self._islemde(self.db, "reindex_canli", _reindex_analyze),
            "reindex_hata": lambda: self._islemde(self.hdb, "reindex_hata", _reindex_analyze),
            "checkpoint": lambda: self._checkpoint(dbler),
        }
        for anahtar, etiket in self.ADIMLAR:
            a0 = time.perf_counter()
            try:
                ayrinti = isler[anahtar]()
                sonuc["adimlar"].append({"adim": anahtar, "ad": etiket, "durum": "TAMAM",
                                         "sure_ms": int((time.perf_counter() - a0) * 1000)})
                if anahtar == "budama_canli":
                    sonuc["budama_canli"] = ayrinti
                elif anahtar == "budama_hata":
                    sonuc["budama_hata"] = ayrinti
                elif anahtar == "yedek":
                    sonuc["yedek"] = ayrinti
            except Exception as e:
                logger.exception(f"bakım adımı başarısız: {etiket}")
                durum = "ATLANDI_BOZUK" if anahtar == "on_kontrol" else "GERI_ALINDI"
                sonuc["adimlar"].append({"adim": anahtar, "ad": etiket, "durum": durum, "hata": str(e)[:400],
                                         "sure_ms": int((time.perf_counter() - a0) * 1000)})
                sonuc.update(durum="HATA", hata_mesaji=str(e)[:400], geri_alinan=etiket, hatali_adim=anahtar)
                break
        # son kontrol her durumda: bakım (ya da geri alınan adım) veritabanını bozmadı mı?
        try:
            self._butunluk_denetle(dbler, "son")
            sonuc["son_kontrol"] = "SAGLAM"
        except Exception as e:
            sonuc["son_kontrol"] = f"SORUNLU: {e}"
            sonuc["durum"] = "HATA"
            sonuc.setdefault("hata_mesaji", str(e)[:400])
        for ad, d in dbler:
            try:
                boyut = d.boyut_mb()
            except Exception:
                boyut = None
            sonuc[ad] = {"once_mb": once[ad], "boyut_mb": round(boyut, 2) if boyut is not None else None}
            if boyut is not None and boyut > BOYUT_ALARM_MB:
                self.db.alarm_ac(f"db:{ad}:boyut", f"{ad}.db beklenenden büyük: {boyut:.0f} MB", AlarmSeviye.UYARI, "bakim")
            elif boyut is not None:
                self.db.alarm_kapat(f"db:{ad}:boyut")
        sonuc.setdefault("durum", "TAMAM")
        sonuc["sistem_etkilenmedi"] = sonuc["son_kontrol"] == "SAGLAM"
        if sonuc["durum"] == "TAMAM":
            self.db.alarm_kapat("bakim:hata")
        elif sonuc.get("hatali_adim") == "on_kontrol":
            self.db.alarm_ac("bakim:hata", f"Bakım başlamadı: veritabanı ön bütünlük kontrolünden geçemedi "
                             f"({sonuc.get('hata_mesaji')}). Hiçbir değişiklik yapılmadı; son sağlam kopya korunuyor: "
                             f"{yedek_klasoru}. İzleme sürüyor; destek alın.", AlarmSeviye.KRITIK, "bakim")
        elif sonuc["son_kontrol"] != "SAGLAM":
            self.db.alarm_ac("bakim:hata", f"Veritabanı bütünlük kontrolünden geçemedi ({sonuc['son_kontrol']}). Son sağlam kopya: "
                             f"{yedek_klasoru}. İzlemeyi durdurmadan önce destek alın; kopyadan dönüş elle yapılır.",
                             AlarmSeviye.KRITIK, "bakim")
        else:
            self.db.alarm_ac("bakim:hata", f"Bakım '{sonuc.get('geri_alinan')}' adımında hata verdi; bu adım geri alındı ve kalan "
                             f"adımlar yapılmadı. Veritabanı bakımdan önceki çalışan hâliyle devam ediyor, izleme etkilenmedi. "
                             f"Hata: {sonuc.get('hata_mesaji')}", AlarmSeviye.UYARI, "bakim")
        sonuc["sure_ms"] = int((time.perf_counter() - t0) * 1000)
        sonuc["bitti"] = time.time()
        self.db.meta_yaz("son_bakim", sonuc["basladi"])
        self.db.meta_yaz("son_bakim_sonucu", _kisa(sonuc))
        self.db.meta_yaz("bakim_suruyor", "")
        self.hdb.denetim_yaz("BAKIM", "veritabanlari", yeni=sonuc, kullanici=kullanici, kaynak="bakim")
        loglama.olay("BAKIM", durum=sonuc["durum"], sure_ms=sonuc["sure_ms"], kullanici=kullanici,
                     geri_alinan=sonuc.get("geri_alinan"))
        return sonuc

    def _islemde(self, d, anahtar, fn):
        """fn tek bir yazma işlemi (BEGIN IMMEDIATE … COMMIT) içinde çalışır; hata olursa ROLLBACK: değişiklik kalmaz."""
        with d.yaz() as con:
            r = fn(con)
            _test_hatasi(anahtar)
        return r

    def _butunluk_denetle(self, dbler, ne):
        _test_hatasi(f"{ne}_kontrol")
        for ad, d in dbler:
            sorun = d.butunluk()
            if sorun:
                raise RuntimeError(f"{ad}.db bütünlük kontrolü: {'; '.join(sorun[:3])}")
        return True

    def _checkpoint(self, dbler):
        for ad, d in dbler:
            d.calistir("PRAGMA incremental_vacuum")
            d.tek("PRAGMA wal_checkpoint(TRUNCATE)")
        _test_hatasi("checkpoint")
        return True


def _reindex_analyze(con):
    con.execute("REINDEX")
    con.execute("ANALYZE")
    return True


def _test_hatasi(anahtar: str):
    """YALNIZCA TESTLER: FWP_TEST_BAKIM_HATA=<adım> ise o adımda (işlem geri alınmadan hemen önce) hata üretir."""
    if os.environ.get("FWP_TEST_BAKIM_HATA") == anahtar:
        raise RuntimeError(f"test: '{anahtar}' adımında yapay hata")


def _kisa(s: dict) -> str:
    import json
    return json.dumps(s, ensure_ascii=False, default=str)[:2000]
