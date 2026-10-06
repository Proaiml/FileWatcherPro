"""Betik hedefi uçtan uca (gerçek çekirdek + tarama + teslim): dosya gelir → kuralın betiği çalışır.

Hata sözleşmesinin teslimdeki karşılığı: 0 → İLETİLDİ · 10 → kalıcı (lokale + KRİTİK alarm, düzeltip erit) ·
diğer → yeniden deneme · süre doldu → belirsiz (olası çift işaretli, yeniden) · kapanışta sonlandırılan → açılışta yeniden.
"""
import hashlib
import json
import time
from pathlib import Path

from testler.conftest import HIZLI_TARAMA, duz_sir_yok

EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
              {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"}]
AYAR = {**HIZLI_TARAMA, "sabitlik_W_sn": 0.3, "deneme_plani": "0.5,1,1.5", "otomatik_devre_esigi": 0, "erit_hizi": 20}
SIR = "betik-gizli-anahtar-7781"

# Her çalışmayı JSON satırı olarak kayıt dosyasına yazar; davranışı dosya adındaki işaretlerle seçilir.
BETIK = r'''import hashlib, json, os, sys, time
kayit = os.environ["FWP_P_KAYIT"]
v = json.load(sys.stdin)
ad = os.environ["FWP_DOSYA_ADI"]
with open(kayit, "a", encoding="utf-8") as f:
    f.write(json.dumps({"ad": ad, "kimlik": os.environ["FWP_KIMLIK"], "deneme": os.environ["FWP_DENEME"],
                        "sayi": int(os.environ["FWP_DENEME_SAYISI"]), "tarih": os.environ.get("FWP_G_TARIH"),
                        "olay": os.environ["FWP_P_OLAY"], "sir": hashlib.sha256(os.environ["FWP_SIR_API"].encode()).hexdigest() == "%s",
                        "stdin": v["dosya_adi"]}, ensure_ascii=False) + "\n")
print("islendi", ad, os.environ["FWP_SIR_API"])
if "KALICI" in ad:
    print("HTTP 404: is bulunamadi", file=sys.stderr); sys.exit(10)
if "GECICI" in ad and int(os.environ["FWP_DENEME_SAYISI"]) < 3:
    sys.exit(1)
if "YAVAS" in ad and int(os.environ["FWP_DENEME_SAYISI"]) == 1:
    time.sleep(30)
''' % hashlib.sha256(SIR.encode()).hexdigest()


def kur(ortam_yap, tmp_path, kod=BETIK, zaman=3):
    o = ortam_yap(eklentiler=EKLENTILER, ayarlar=AYAR)
    d = tmp_path / "gelen"
    kayit = tmp_path / "kayit.jsonl"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    hedef_id = o.yap.hedef_ekle("aktarim", "", tur="BETIK", kullanici="test", ayrintilar={
        "dil": "python", "kod": kod, "zaman_asimi_sn": zaman, "eszamanli": 2, "sirlar": [{"ad": "API", "deger": SIR}]})
    o.yap.kural_ekle(dizin_id, "fatura", r"F_(?P<tarih>\d{8})_\w+\.csv", hedef_id, kullanici="test",
                     istek={"parametreler": {"OLAY": "FATURA_GELDI_{tarih}", "KAYIT": str(kayit)}})
    o.cekirdek_baslat()
    o.bekle(lambda: all((s := o.eklenti(a)) and s["durum"] == "CALISIYOR" for a in ("tarama", "teslim")))
    return o, d, kayit, hedef_id


def kayitlar(kayit: Path) -> list:
    return [json.loads(x) for x in kayit.read_text(encoding="utf-8").splitlines()] if kayit.exists() else []


def tetik(o, ad):
    return o.db.tek("SELECT * FROM tetik WHERE dosya_adi=?", (ad,))


def durum_bekle(o, ad, durum, zaman_asimi=30):
    return o.bekle(lambda: (t := tetik(o, ad)) and t["durum"] == durum and t, zaman_asimi=zaman_asimi,
                   mesaj=f"{ad} {durum} olmadı (şu an: {(tetik(o, ad) or {}) and tetik(o, ad)['durum']})")


def test_dosya_gelir_betik_calisir_degerler_ve_gizli_deger_dogru(ortam_yap, tmp_path):
    o, d, kayit, hedef_id = kur(ortam_yap, tmp_path)
    (d / "F_20261001_A.csv").write_text("x", encoding="utf-8")
    t = durum_bekle(o, "F_20261001_A.csv", "ILETILDI")
    k = kayitlar(kayit)
    assert len(k) == 1 and k[0]["kimlik"] == t["idempotency"] and k[0]["deneme"] == "0" and k[0]["sayi"] == 1
    assert k[0]["tarih"] == "20261001" and k[0]["olay"] == "FATURA_GELDI_20261001" and k[0]["sir"] is True
    assert k[0]["stdin"] == "F_20261001_A.csv"
    a = json.loads(o.db.tek("SELECT ayrintilar FROM hedef WHERE id=?", (hedef_id,))[0])
    assert a["sirlar"][0]["ref"].startswith("dpapi:") and a["surum"] and a["degistiren"] == "test"
    gecmis = json.loads(t["deneme_gecmisi"])
    assert gecmis[-1]["tur"] == "BASARI" and gecmis[-1]["mesaj"].startswith("çıkış 0")
    o.cekirdek_kapat()
    duz_sir_yok(o, SIR)                          # gizli değer hiçbir dosyada düz yok (veritabanı, log, betik klasörü)


def test_kalici_hata_lokale_alarm_betik_duzeltilip_erit(ortam_yap, tmp_path):
    o, d, kayit, hedef_id = kur(ortam_yap, tmp_path)
    (d / "F_20261001_KALICI.csv").write_text("x", encoding="utf-8")
    t = durum_bekle(o, "F_20261001_KALICI.csv", "LOKALDE")
    assert t["deneme_sayisi"] == 1 and len(kayitlar(kayit)) == 1          # kalıcı: yeniden denenmedi
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:kalici",))
    assert "çıkış 10" in o.hdb.tek("SELECT sebep_detay FROM gonderilemeyen WHERE dosya_adi=?",
                                   ("F_20261001_KALICI.csv",))[0]
    # betik düzeltilir (kalıcı hatayı kaldır), gizli değer boş bırakılır → eski değer korunur
    duzelt = BETIK.replace('if "KALICI" in ad:', 'if False:')
    o.yap.hedef_guncelle(hedef_id, "aktarim", ayrintilar={"dil": "python", "kod": duzelt, "zaman_asimi_sn": 3,
                                                          "eszamanli": 2, "sirlar": [{"ad": "API"}]}, kullanici="test")
    o.yap.erit_baslat(hedef_id, kullanici="test")
    durum_bekle(o, "F_20261001_KALICI.csv", "ILETILDI")
    assert kayitlar(kayit)[-1]["sir"] is True


def test_gecici_hata_yeniden_denenir_ayni_kimlikle(ortam_yap, tmp_path):
    o, d, kayit, _ = kur(ortam_yap, tmp_path)
    (d / "F_20261001_GECICI.csv").write_text("x", encoding="utf-8")
    t = durum_bekle(o, "F_20261001_GECICI.csv", "ILETILDI")
    k = kayitlar(kayit)
    assert [x["sayi"] for x in k] == [1, 2, 3] and len({x["kimlik"] for x in k}) == 1 and t["deneme_sayisi"] == 3


def test_sure_dolunca_belirsiz_olasi_cift_ve_yeniden(ortam_yap, tmp_path):
    o, d, kayit, _ = kur(ortam_yap, tmp_path, zaman=2)
    (d / "F_20261001_YAVAS.csv").write_text("x", encoding="utf-8")
    t = durum_bekle(o, "F_20261001_YAVAS.csv", "ILETILDI", zaman_asimi=40)
    assert t["belirsiz"] == 1 and [x["sayi"] for x in kayitlar(kayit)] == [1, 2]
    assert "süre doldu" in json.loads(t["deneme_gecmisi"])[0]["mesaj"]


def test_kapanista_calisan_betik_sonlandirilir_acilista_yeniden(ortam_yap, tmp_path):
    uzun = BETIK.replace('if "YAVAS" in ad and int(os.environ["FWP_DENEME_SAYISI"]) == 1:\n    time.sleep(30)',
                         'if "UZUN" in ad and int(os.environ["FWP_DENEME_SAYISI"]) == 1:\n    time.sleep(300)')
    o, d, kayit, _ = kur(ortam_yap, tmp_path, kod=uzun, zaman=600)
    (d / "F_20261001_UZUN.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: len(kayitlar(kayit)) == 1)
    t0 = time.time()
    o.cekirdek_kapat()                                     # kapanış payı 2 sn; 300 sn'lik betik kapanışı bekletmemeli
    assert time.time() - t0 < 25
    assert tetik(o, "F_20261001_UZUN.csv")["durum"] in ("TEKRAR", "BEKLIYOR", "DENENIYOR")
    o.cekirdek_baslat()
    t = durum_bekle(o, "F_20261001_UZUN.csv", "ILETILDI")
    assert t["belirsiz"] == 1 and [x["sayi"] for x in kayitlar(kayit)][-1] >= 2
