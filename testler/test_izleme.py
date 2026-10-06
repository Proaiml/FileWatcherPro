"""Sistem izleme eklentisi testleri (kullanıcı isteği 2026-09-30: sunucu ve FileWatcherPro kaynakları, eşik alarmları).

Gerçek çekirdek + izleme + kontrol süreçleri; ölçümler gerçek psutil değerleridir.
"""
import json
import time

from cekirdek.kullanicilar import Kullanicilar
from testler.conftest import HIZLI_TARAMA
from testler.test_adim8_kontrol_api import SIFRE, Istemci

EKLENTILER = [{"ad": "izleme", "modul": "eklentiler.izleme.izleyici"},
              {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"}]
HIZLI = {**HIZLI_TARAMA, "izleme_aralik_sn": 1, "izleme_normale_donus_sn": 2}


def kur(ortam_yap, **ayar):
    o = ortam_yap(eklentiler=EKLENTILER, ayarlar={**HIZLI, **ayar})
    Kullanicilar(o.baslangic.parent / "kullanicilar.json").ekle("yonetici", SIFRE, "YONETICI")
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                and json.loads(e["bilgi"] or "{}").get("port") and e)
    y = Istemci(json.loads(s["bilgi"])["port"])
    assert y.giris("yonetici")[0] == 200
    return o, y


def test_olcum_ve_api(ortam_yap):
    """Her ölçümde sunucu ve bileşen değerleri yazılır; /api/izleme anlık özet, geçmiş ve eşikleri verir."""
    o, y = kur(ortam_yap)
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM olcum")[0] >= 3, mesaj="ölçüm yazılmadı")
    kod, v = y.get("/api/izleme")
    assert kod == 200, v
    s = v["simdi"]
    assert 0 <= s["sunucu"]["cpu"] <= 100 and 0 < s["sunucu"]["ram_yuzde"] < 100 and s["sunucu"]["cekirdek"] >= 1
    assert s["sunucu"]["diskler"] and s["sunucu"]["diskler"][0]["bos_mb"] > 0
    adlar = {p["ad"]: p for p in s["fwp"]["surecler"]}
    assert {"cekirdek", "izleme", "kontrol"} <= set(adlar)
    assert all(adlar[a]["ram_mb"] > 5 and adlar[a]["thread"] >= 1 and adlar[a]["pid"] for a in ("cekirdek", "izleme", "kontrol"))
    assert abs(s["fwp"]["ram_mb"] - sum(p["ram_mb"] or 0 for p in s["fwp"]["surecler"])) < 1
    assert s["depo"]["canli_mb"] > 0 and "log_mb" in s["depo"]
    assert len(v["gecmis"]["zaman"]) >= 3 and len(v["gecmis"]["zaman"]) == len(v["gecmis"]["fwp_ram"])
    assert {e["anahtar"] for e in v["esikler"]} >= {"sunucu_cpu", "sunucu_ram", "disk", "fwp_cpu", "fwp_ram", "log", "tarama_suresi"}
    assert all(e["durum"] == "NORMAL" for e in v["esikler"])
    assert y.get("/api/izleme?aralik=24s")[0] == 200
    assert time.time() - v["olcum_zamani"] < 10


def test_esik_sure_dolunca_alarm_normale_donunce_kapanir(ortam_yap):
    """Eşik aşılınca önce 'Aşıldı' (alarm yok); süre dolunca alarm; değer normale dönüp beklenen süre geçince kapanır.
    Eşik önyüzdeki gibi /api/ayarlar ile değiştirilir."""
    o, y = kur(ortam_yap, izleme_fwp_ram_mb=50, izleme_fwp_ram_mb_dk=0.1)      # 3 süreç ~90+ MB > 50 MB, 6 sn sonra
    def fwp():
        return next(e for e in y.get("/api/izleme")[1]["esikler"] if e["anahtar"] == "fwp_ram")
    o.bekle(lambda: fwp()["durum"] == "ASILDI", zaman_asimi=15, mesaj="eşik aşıldı görünmedi")
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar='kaynak:fwp_ram' AND aktif=1") is None      # henüz süre dolmadı
    a = o.bekle(lambda: o.db.tek("SELECT * FROM alarm WHERE anahtar='kaynak:fwp_ram' AND aktif=1"), zaman_asimi=20)
    assert a["seviye"] == "UYARI" and a["kaynak"] == "izleme" and "eşiği aştı" in a["mesaj"]
    assert fwp()["durum"] == "ALARM"
    assert y.put("/api/ayarlar", {"izleme_fwp_ram_mb": 100000})[0] == 200
    o.bekle(lambda: o.db.tek("SELECT aktif FROM alarm WHERE anahtar='kaynak:fwp_ram' ORDER BY id DESC LIMIT 1")[0] == 0,
            zaman_asimi=20, mesaj="alarm normale dönünce kapanmadı")
    assert fwp()["durum"] == "NORMAL"


def test_kisa_siçrama_alarm_uretmez_ve_kapali_esik_izlenmez(ortam_yap):
    """Süre dolmadan geçen aşım alarm üretmez; kapatılan eşik (…_aktif = hayır) hiç izlenmez."""
    o, y = kur(ortam_yap, izleme_fwp_ram_mb=50, izleme_fwp_ram_mb_dk=60, izleme_log_mb=10, izleme_log_mb_aktif=False)
    time.sleep(6)
    es = {e["anahtar"]: e for e in y.get("/api/izleme")[1]["esikler"]}
    assert es["fwp_ram"]["durum"] == "ASILDI" and es["log"]["durum"] == "NORMAL" and es["log"]["aktif"] is False
    assert o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar LIKE 'kaynak:%'")[0] == 0


def test_disk_esigi_aninda_kritik_alarm(ortam_yap):
    """G8: veri/log diskinde boş alan eşiğin altına düşünce (süre beklemeden) KRİTİK alarm; eşik geri alınınca kapanır.
    Gerçek diski doldurmak yerine eşik gerçek boş alanın üstüne çekilir."""
    o, y = kur(ortam_yap)
    assert y.put("/api/ayarlar", {"izleme_disk_bos_gb": 100000})[0] == 200
    a = o.bekle(lambda: o.db.tek("SELECT * FROM alarm WHERE anahtar='kaynak:disk' AND aktif=1"), zaman_asimi=15)
    assert a["seviye"] == "KRITIK" and "eşiğin altına düştü" in a["mesaj"]
    assert y.put("/api/ayarlar", {"izleme_disk_bos_gb": 0.1})[0] == 200
    o.bekle(lambda: o.db.tek("SELECT aktif FROM alarm WHERE anahtar='kaynak:disk'")[0] == 0, zaman_asimi=15)


def test_tarama_suresi_uc_olcum_ust_uste_asarsa_alarm(ortam_yap, tmp_path):
    """F3: bir dizinin listelemesi 3 ölçüm üst üste eşiği aşarsa o dizin için uyarı alarmı (tek yavaş tur alarm
    üretmez); süre normale dönünce kapanır. Liste süresini tarama eklentisi yazar; burada tarama çalışmadığından
    değer veritabanına elle yazılır."""
    o, y = kur(ortam_yap, izleme_tarama_sn=0.5)
    i = o.dizin_kur(tmp_path / "yavas", "TETIKLE", ".csv")
    o.db.calistir("UPDATE dizin SET son_tarama_ms=2000 WHERE id=?", (i,))
    time.sleep(1.2)
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar=?", (f"kaynak:tarama:{i}",)) is None      # henüz 3 ölçüm yok
    a = o.bekle(lambda: o.db.tek("SELECT * FROM alarm WHERE anahtar=? AND aktif=1", (f"kaynak:tarama:{i}",)), zaman_asimi=15)
    assert a["seviye"] == "UYARI" and str(tmp_path / "yavas") in a["mesaj"]
    es = next(e for e in y.get("/api/izleme")[1]["esikler"] if e["anahtar"] == "tarama_suresi")
    assert es["durum"] == "ALARM" and "yavas" in es["aciklama"]
    o.db.calistir("UPDATE dizin SET son_tarama_ms=20 WHERE id=?", (i,))
    o.bekle(lambda: o.db.tek("SELECT aktif FROM alarm WHERE anahtar=?", (f"kaynak:tarama:{i}",))[0] == 0, zaman_asimi=15)
