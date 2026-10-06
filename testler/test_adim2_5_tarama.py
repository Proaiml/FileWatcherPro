"""Adım 2–5 testleri: tarama, dosya durumu + kural eşleşme, hata anlamı, tamamlanma + hash kimliği.

Birim testleri süreçsizdir; entegrasyon testleri gerçek çekirdek + gerçek tarama eklentisiyle koşar.
Olay tablosu karşılıkları her testin açıklamasında yazılıdır.
"""
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from cekirdek.kimlik import icerik_hash, kimlik_uret, paylasimli_ac
from cekirdek.kurallar import (DizinKurallari, Kural, RegexHatasi, ad_anahtari, regex_derle, regex_dene,
                               regex_guvenlik_testi, son_ek, uzanti_kumesi)
from eklentiler.tarama.tamamlanma import KILITLI, SERBEST, YOK, paylasim_testi
from testler.conftest import HIZLI_TARAMA, TARAMA_EKLENTISI, Yazici


# ============================================================ birim testleri
def test_son_ek_ve_uzanti_kumesi():
    """D2, D3: gerçek son ek, harf duyarsız; ad içinde alt dize araması yok."""
    assert son_ek("Rapor.CSV") == ".csv" and son_ek("a.csv.bak") == ".bak" and son_ek("README") == ""
    assert son_ek(".gizli") == "" and son_ek("x.Txt") == ".txt"
    assert uzanti_kumesi("CSV; .Txt,") == frozenset({".csv", ".txt"})
    dk = DizinKurallari(1, "C:\\x", uzanti_kumesi(".csv"), (), frozenset({".filepart", ".part"}), True)
    assert dk.uzanti_uygun("A.CSV") and dk.uzanti_uygun("b.Csv") and not dk.uzanti_uygun("c.csv.bak")
    assert dk.parca_ic_adi("rapor.csv.FILEPART") == "rapor.csv" and dk.parca_ic_adi("rapor.csv") is None


def test_kural_eslesme_ilk_ve_hepsi():
    """K1, K4, K6: tam eşleşme, harf duyarsız, isimli gruplar, ilk/hepsi."""
    k1 = Kural(1, "fatura", regex_derle(r"FATURA_(?P<tarih>\d{8})\.csv"), 1, 10)
    k2 = Kural(2, "hepsi", regex_derle(r".*\.csv"), 2, 20)
    ilk = DizinKurallari(1, "x", frozenset(), (k1, k2), frozenset(), True, "ilk")
    hepsi = DizinKurallari(1, "x", frozenset(), (k1, k2), frozenset(), True, "hepsi")
    assert [(k.id, g) for k, g in ilk.eslestir("fatura_20260929.CSV")] == [(1, {"tarih": "20260929"})]
    assert [k.id for k, _ in hepsi.eslestir("FATURA_20260929.csv")] == [1, 2]
    assert ilk.eslestir("XFATURA_20260929.csv") == [(k2, {})]        # tam eşleşme: baştaki X k1'e uymaz
    assert regex_dene(r"IADE_.*\.txt", True, ["iade_1.TXT", "iade.txt"]) == [
        {"ad": "iade_1.TXT", "eslesti": True, "gruplar": {}}, {"ad": "iade.txt", "eslesti": False, "gruplar": {}}]


def test_regex_dogrulama_ve_yavas_regex_reddi():
    """K5, K7: geçersiz regex ve geri izleme patlaması yapan regex kaydedilemez."""
    with pytest.raises(RegexHatasi):
        regex_derle("FATURA_(\\d+", True)
    with pytest.raises(RegexHatasi):
        regex_derle("   ", True)
    regex_guvenlik_testi(r"^SEVK_(?P<tarih>\d{8})\.csv$", True, ["SEVK_20260929.csv"])
    t0 = time.time()
    with pytest.raises(RegexHatasi, match="çok yavaş"):
        regex_guvenlik_testi(r"^(a+)+$", True, sure=2.0)
    assert time.time() - t0 < 10


def test_kimlik_kurallari(tmp_path):
    """Kimlik: 0 baytlık farklı adlı dosyalar ayrı; yalnızca tarih değişimi kimliği bozmaz; içerik değişimi bozar."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"")
    b.write_bytes(b"")
    ha, hb = icerik_hash(str(a))[0], icerik_hash(str(b))[0]
    assert ha == hb                                              # boş içerik → aynı hash
    assert kimlik_uret(1, "a.csv", ha) != kimlik_uret(1, "b.csv", hb)   # ama farklı dosya
    a.write_bytes(b"1,2,3")
    k1 = kimlik_uret(1, "a.csv", icerik_hash(str(a))[0])
    os.utime(a, (time.time() - 3600, time.time() - 3600))
    assert kimlik_uret(1, "a.csv", icerik_hash(str(a))[0]) == k1   # yalnızca tarih değişti → aynı
    a.write_bytes(b"1,2,4")
    assert kimlik_uret(1, "a.csv", icerik_hash(str(a))[0]) != k1   # içerik değişti → farklı
    assert kimlik_uret(1, "a.csv", boyut=5, mtime_ns=1) != kimlik_uret(1, "a.csv", boyut=5, mtime_ns=2)


def test_hash_okumasi_eft_yi_engellemez_ve_paylasim_testi(tmp_path):
    """J1: hash için açık tutulan dosya yeniden adlandırılabilir/silinebilir. Paylaşım testi yazan tutamacı görür."""
    p = tmp_path / "x.csv"
    p.write_bytes(b"x" * 1000)
    with paylasimli_ac(str(p)) as f:
        f.read(10)
        os.rename(p, tmp_path / "y.csv")                          # EFT/Control-M yeniden adlandırabiliyor
        os.remove(tmp_path / "y.csv")                             # ve silebiliyor
    p.write_bytes(b"abc")
    assert paylasim_testi(str(p))[0] == SERBEST
    y = Yazici(p)
    y.yaz(b"yaziliyor")
    assert paylasim_testi(str(p))[0] == KILITLI                   # yazan süreç tutuyor
    y.kapat()
    assert paylasim_testi(str(p))[0] == SERBEST
    assert paylasim_testi(str(tmp_path / "yok.csv"))[0] == YOK


# ============================================================ entegrasyon: yardımcılar
def tarama_ortami(ortam_yap, tmp_path, **ayarlar):
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar={**HIZLI_TARAMA, **ayarlar})
    return o


def yeni_dizin(o, tmp_path, ad="gelen", regex=r".*\.csv", mod="TETIKLE", uzantilar=".csv"):
    d = tmp_path / ad
    dizin_id = o.dizin_kur(d, mod, uzantilar)
    o.kural_kur(dizin_id, regex)
    return d, dizin_id


def bekle_tetik(o, ad, sayi=1, zaman_asimi=20):
    return o.bekle(lambda: len(o.tetikler(ad)) >= sayi and o.tetikler(ad), zaman_asimi=zaman_asimi,
                   mesaj=f"{ad} için {sayi} tetik oluşmadı")


def tarama_hazir(o):
    return o.bekle(lambda: (s := o.eklenti("tarama")) and s["durum"] == "CALISIYOR"
                   and json.loads(s["bilgi"] or "{}").get("dizinler"), mesaj="tarama hazır değil")


# ============================================================ entegrasyon testleri
def test_tek_dosya_tetiklenir_isimli_gruplarla(ortam_yap, tmp_path):
    """K1 / A1: kurala uyan tamamlanmış dosya → tek tetik, dosya adı + regex grupları parametrede."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d = tmp_path / "muhasebe"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    o.kural_kur(dizin_id, r"FATURA_(?P<tarih>\d{8})\.csv", ad="fatura")
    o.cekirdek_baslat()
    tarama_hazir(o)
    (d / "FATURA_20260929.csv").write_text("1;2;3", encoding="utf-8")
    t = bekle_tetik(o, "FATURA_20260929.csv")
    time.sleep(1.5)
    assert len(o.tetikler("FATURA_20260929.csv")) == 1
    p = json.loads(t[0]["parametreler"])
    assert t[0]["durum"] == "BEKLIYOR" and p["gruplar"] == {"tarih": "20260929"} and p["kural"] == "fatura"
    ds = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='FATURA_20260929.csv'")
    assert ds["durum"] == "HAZIR" and ds["icerik_hash"] and ds["hazir_zamani"] >= ds["ilk_gorulme"]
    assert o.yukleme("FATURA_20260929.csv") is None


def test_toplu_gelis_her_dosya_ayri_tetik(ortam_yap, tmp_path):
    """C1: aynı taramada 25 dosya → 25 ayrı tetik, hiçbiri kayıp değil, çift yok."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    for i in range(25):
        (d / f"d{i:02d}.csv").write_text(f"{i}", encoding="utf-8")
    o.bekle(lambda: len(o.tetikler()) >= 25, mesaj="25 tetik oluşmadı")
    time.sleep(1.5)
    adlar = [t["dosya_adi"] for t in o.tetikler()]
    assert sorted(adlar) == [f"d{i:02d}.csv" for i in range(25)]


def test_ayni_turda_gelen_ve_kalkan(ortam_yap, tmp_path):
    """C2 / T3: biri kalkarken biri geldi → yeni olan tetiklenir; kalkan dosya 'kalktı' olur, alarm yok."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    (d / "eski.csv").write_text("x", encoding="utf-8")
    bekle_tetik(o, "eski.csv")
    os.remove(d / "eski.csv")
    (d / "yeni.csv").write_text("y", encoding="utf-8")
    bekle_tetik(o, "yeni.csv")
    o.bekle(lambda: o.db.tek("SELECT kalkma_zamani FROM dosya WHERE dosya_adi='eski.csv'")["kalkma_zamani"])
    assert o.db.tek("SELECT COUNT(*) FROM alarm WHERE aktif=1")[0] == 0


def test_yazilmakta_olan_dosya_tamamlanmadan_tetiklenmez(ortam_yap, tmp_path):
    """B1/B2 (kullanıcının açık şartı): tarama sırasında yazılmaya devam eden dosya sonraki turlarda tamamlanana
    kadar yeni dosya olarak kaydedilmez ve tetiklenmez. Tutamaç açık, 4+ sn boyunca parça parça yazılır."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    y = Yazici(d / "buyuk.csv")
    durumlar = set()
    for _ in range(10):
        y.yaz(b"a" * 200_000)
        time.sleep(0.45)
        s = o.yukleme("buyuk.csv")
        if s:
            durumlar.add(s["durum"])
        assert o.tetikler("buyuk.csv") == []
        assert o.db.tek("SELECT COUNT(*) FROM dosya WHERE dosya_adi='buyuk.csv'")[0] == 0
    assert durumlar & {"YAZILIYOR", "KILITLI"}
    y.kapat()
    t = bekle_tetik(o, "buyuk.csv")
    time.sleep(2)
    assert len(o.tetikler("buyuk.csv")) == 1
    ds = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='buyuk.csv'")
    assert ds["boyut"] == 2_000_000 and ds["icerik_hash"] == icerik_hash(str(d / "buyuk.csv"))[0]


def test_duraklayan_yukleme_kilitli_kalir(ortam_yap, tmp_path):
    """B3/B7: yükleme W'dan uzun duraklar ama tutamaç açık → paylaşım testi KILITLI; tetik yok. Bitince tek tetik."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    y = Yazici(d / "durakla.csv")
    y.yaz(b"ilk yarisi;")
    o.bekle(lambda: (s := o.yukleme("durakla.csv")) and s["durum"] == "KILITLI", zaman_asimi=10,
            mesaj="duraklayan yükleme KILITLI olmadı")
    time.sleep(2)                                                # W (1 sn) çoktan geçti
    assert o.tetikler("durakla.csv") == []
    y.yaz(b"ikinci yarisi")
    y.kapat()
    bekle_tetik(o, "durakla.csv")
    time.sleep(1.5)
    assert len(o.tetikler("durakla.csv")) == 1


def test_uzun_suren_yukleme_askida_bildirilir(ortam_yap, tmp_path):
    """ASKIDA (kullanıcının açık şartı): çok uzun süren yükleme önyüze (alarm) bildirilir, bitince kapanır."""
    o = tarama_ortami(ortam_yap, tmp_path, aski_T_dk=0.1)     # 6 sn
    d, dizin_id = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    y = Yazici(d / "yavas.csv")
    y.yaz(b"x")
    o.bekle(lambda: (s := o.yukleme("yavas.csv")) and s["durum"] == "ASKIDA", zaman_asimi=15)
    alarm = o.db.tek("SELECT * FROM alarm WHERE anahtar LIKE 'askida:%' AND aktif=1")
    assert alarm is not None and "yavas.csv" in alarm["mesaj"] and alarm["seviye"] == "UYARI"
    assert o.tetikler("yavas.csv") == []
    y.kapat()
    bekle_tetik(o, "yavas.csv")
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar LIKE 'askida:%' AND aktif=1")[0] == 0,
            mesaj="askı alarmı kapanmadı")


def test_gecici_ad_filepart_yalnizca_son_ad_tetiklenir(ortam_yap, tmp_path):
    """B6: .filepart ile yüklenip son ada çevrilen dosya → yalnızca son ad için tek tetik; geçici ad izlenir."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path, regex=r"RAPOR_\d+\.csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    y = Yazici(d / "RAPOR_1.csv.filepart")
    y.yaz(b"yarim;")
    o.bekle(lambda: (s := o.yukleme("RAPOR_1.csv.filepart")) and s["durum"] == "GECICI_AD", zaman_asimi=10)
    time.sleep(1.5)
    y.yaz(b"tamam")
    y.kapat()
    assert o.tetikler() == []
    os.rename(d / "RAPOR_1.csv.filepart", d / "RAPOR_1.csv")
    bekle_tetik(o, "RAPOR_1.csv")
    time.sleep(1.5)
    assert [t["dosya_adi"] for t in o.tetikler()] == ["RAPOR_1.csv"]
    assert o.yukleme("RAPOR_1.csv.filepart") is None


def test_uzanti_regex_klasor_ve_eslesmeyen(ortam_yap, tmp_path):
    """D2, D3, D4, K3: harf duyarsız uzantı; .csv.bak ve 'x.csv' klasörü yok sayılır; uzantısı uyan ama regex'e
    uymayan dosya EŞLEŞMEDİ olarak kaydedilir (hata.db) ve tetiklenmez."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path, regex=r"(A|B)_\d+\.csv", uzantilar=".csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    (d / "A_1.CSV").write_text("1", encoding="utf-8")
    (d / "b_2.Csv").write_text("2", encoding="utf-8")
    (d / "A_3.csv.bak").write_text("3", encoding="utf-8")
    (d / "B_4.txt").write_text("4", encoding="utf-8")
    (d / "x.csv").mkdir()
    (d / "x.csv" / "A_5.csv").write_text("5", encoding="utf-8")   # alt klasör izlenmez (D5)
    (d / "zzz.csv").write_text("6", encoding="utf-8")
    o.bekle(lambda: len(o.tetikler()) >= 2)
    o.bekle(lambda: o.db.tek("SELECT durum FROM dosya WHERE dosya_adi='zzz.csv'"), mesaj="eşleşmeyen kaydedilmedi")
    time.sleep(1.5)
    assert sorted(t["dosya_adi"] for t in o.tetikler()) == ["A_1.CSV", "b_2.Csv"]
    assert o.db.tek("SELECT durum FROM dosya WHERE dosya_adi='zzz.csv'")["durum"] == "ESLESMEDI"
    g = o.hdb.tek("SELECT * FROM gonderilemeyen WHERE dosya_adi='zzz.csv'")
    assert g is not None and g["sebep"] == "ESLESMEDI"
    adlar = {r["dosya_adi"] for r in o.db.oku("SELECT dosya_adi FROM dosya")}
    assert not adlar & {"A_3.csv.bak", "B_4.txt", "x.csv", "A_5.csv"}


def test_dizinde_duran_dosyanin_tarihi_ya_da_icerigi_degisirse_tetik_yok(ortam_yap, tmp_path):
    """D10 / T2 / B5 (kullanıcı kararı 2026-09-30): tetiklenmiş dosyanın yalnızca tarihi değişirse tetik yok; içeriği
    değişirse de yeni geliş sayılmaz, tetik yok: güncel hâli (yeni hash) esas alınır ve değişim kaydedilir."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    p = d / "gunluk.csv"
    p.write_text("gun1", encoding="utf-8")
    bekle_tetik(o, "gunluk.csv")
    ilk_id = o.db.tek("SELECT id FROM dosya WHERE dosya_adi='gunluk.csv'")["id"]
    os.utime(p, (time.time() + 60, time.time() + 60))           # yalnızca tarih
    time.sleep(3.5)
    assert len(o.tetikler("gunluk.csv")) == 1
    assert o.db.tek("SELECT COUNT(*) FROM dosya WHERE dosya_adi='gunluk.csv'")[0] == 1
    eski_hash = o.db.tek("SELECT icerik_hash FROM dosya WHERE id=?", (ilk_id,))[0]
    p.write_text("gun2", encoding="utf-8")                      # aynı boyut, farklı içerik
    ds = o.bekle(lambda: (r := o.db.tek("SELECT * FROM dosya WHERE id=?", (ilk_id,))) and r["icerik_degisim"] == 1 and r,
                 mesaj="içerik değişimi kaydedilmedi")
    assert ds["icerik_hash"] == icerik_hash(str(p))[0] != eski_hash and ds["kalkma_zamani"] is None
    assert ds["son_icerik_degisimi"] and o.yukleme("gunluk.csv") is None
    p.write_text("gun3!", encoding="utf-8")                     # boyut da değişir
    o.bekle(lambda: o.db.tek("SELECT icerik_degisim FROM dosya WHERE id=?", (ilk_id,))[0] == 2)
    time.sleep(1.5)
    assert len(o.tetikler("gunluk.csv")) == 1
    assert o.db.tek("SELECT COUNT(*) FROM dosya WHERE dosya_adi='gunluk.csv'")[0] == 1
    os.remove(p)                                                # kalkıp yeniden gelirse: o yeni geliştir
    o.bekle(lambda: o.db.tek("SELECT kalkma_zamani FROM dosya WHERE id=?", (ilk_id,))[0])
    p.write_text("gun4", encoding="utf-8")
    bekle_tetik(o, "gunluk.csv", 2)


def test_iki_tarama_arasinda_silinip_ayni_adla_gelen_dosya_yeni_gelistir(ortam_yap, tmp_path):
    """E5 + B5: dosya iki tarama arasında silinip aynı adla yeniden yazılırsa (tarayıcı yokluğunu hiç görmez)
    Windows dosya numarası değişir → yeni geliş, tetiklenir. Yerinde değişimde numara aynıdır → tetik yok (B5)."""
    o = tarama_ortami(ortam_yap, tmp_path, tarama_araligi_sn=1.0)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    p = d / "rapor.csv"
    p.write_text("ilk", encoding="utf-8")
    bekle_tetik(o, "rapor.csv")
    ilk = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='rapor.csv'")
    assert ilk["dosya_no"] == os.stat(p).st_ino
    os.remove(p)
    p.write_text("yeni dosya", encoding="utf-8")                  # aynı ad, yeni dosya (yeni dosya numarası)
    bekle_tetik(o, "rapor.csv", 2)
    eski = o.db.tek("SELECT * FROM dosya WHERE id=?", (ilk["id"],))
    assert eski["kalkma_zamani"] and "silinip aynı adla" in eski["aciklama"]
    yeni = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='rapor.csv' AND kalkma_zamani IS NULL")
    assert yeni["dosya_no"] == os.stat(p).st_ino != ilk["dosya_no"]
    with open(p, "r+b") as f:                                      # yerinde değişim: aynı dosya
        f.write(b"YENI")
    o.bekle(lambda: o.db.tek("SELECT icerik_degisim FROM dosya WHERE id=?", (yeni["id"],))[0] == 1)
    time.sleep(2.5)
    assert len(o.tetikler("rapor.csv")) == 2


def test_bos_dosyalar_ad_farkliysa_ayri_dosyadir(ortam_yap, tmp_path):
    """Kullanıcı kuralı: 0 baytlık dosyaların hash'i aynıdır; ad farklıysa yeni dosyadır."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    for ad in ("bos1.csv", "bos2.csv", "bos3.csv"):
        (d / ad).write_bytes(b"")
    o.bekle(lambda: len(o.tetikler()) >= 3)
    time.sleep(1.5)
    assert sorted(t["dosya_adi"] for t in o.tetikler()) == ["bos1.csv", "bos2.csv", "bos3.csv"]


def test_kalkip_ayni_icerikle_geri_gelen_dosya_yeni_gelistir(ortam_yap, tmp_path):
    """D8: dosya kalktı, sonra aynı ad ve içerikle yeniden geldi → yeni yükleme → yeni tetik."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    p = d / "tekrar.csv"
    p.write_text("ayni", encoding="utf-8")
    bekle_tetik(o, "tekrar.csv")
    os.remove(p)
    o.bekle(lambda: o.db.tek("SELECT kalkma_zamani FROM dosya WHERE dosya_adi='tekrar.csv'")["kalkma_zamani"])
    p.write_text("ayni", encoding="utf-8")
    bekle_tetik(o, "tekrar.csv", 2)


def test_yeniden_baslatma_telafi_ve_cift_tetik_yok(ortam_yap, tmp_path):
    """G1, G2: izleyici kapalıyken gelen dosya açılışta tetiklenir; eski dosyalar yeniden tetiklenmez."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    (d / "once.csv").write_text("1", encoding="utf-8")
    bekle_tetik(o, "once.csv")
    o.cekirdek_kapat()
    (d / "kapaliyken.csv").write_text("2", encoding="utf-8")
    o.cekirdek_baslat()
    bekle_tetik(o, "kapaliyken.csv")
    time.sleep(2)
    assert len(o.tetikler("once.csv")) == 1 and len(o.tetikler("kapaliyken.csv")) == 1


def test_ilk_kurulum_temel_al_ve_tetikle(ortam_yap, tmp_path):
    """G3: TEMEL_AL → dizin eklenirken var olan dosyalar tetiklenmez (TEMEL); TETIKLE → tetiklenir."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d1, d2 = tmp_path / "temel", tmp_path / "tetikle"
    for d in (d1, d2):
        d.mkdir()
        (d / "vardi.csv").write_text("eski", encoding="utf-8")
        eski = time.time() - 600
        os.utime(d / "vardi.csv", (eski, eski))
    k1 = o.dizin_kur(d1, "TEMEL_AL", ".csv")
    k2 = o.dizin_kur(d2, "TETIKLE", ".csv")
    o.kural_kur(k1, r".*\.csv")
    o.kural_kur(k2, r".*\.csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    o.bekle(lambda: len(o.tetikler("vardi.csv")) >= 1)
    (d1 / "yeni.csv").write_text("yeni", encoding="utf-8")
    bekle_tetik(o, "yeni.csv")
    time.sleep(1.5)
    tet = o.tetikler("vardi.csv")
    assert len(tet) == 1 and str(d2) in tet[0]["tam_yol"]
    assert o.db.tek("SELECT durum FROM dosya WHERE dizin_id=? AND dosya_adi='vardi.csv'", (k1,))["durum"] == "TEMEL"
    with pytest.raises(ValueError, match="açıkça seçilmeli"):
        o.yap.dizin_ekle(str(tmp_path / "secimsiz"), "", kullanici="test")


def test_motor_durdur_ve_telafi(ortam_yap, tmp_path):
    """M1: motor durdurulunca tarama durur; başlayınca durduğu sürede gelen dosya tetiklenir."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    o.ayar(motor_aktif=False)
    time.sleep(1)
    (d / "durgun.csv").write_text("x", encoding="utf-8")
    time.sleep(3)
    assert o.tetikler("durgun.csv") == [] and o.yukleme("durgun.csv") is None
    o.ayar(motor_aktif=True)
    bekle_tetik(o, "durgun.csv")


def test_dizin_erisilemez_durum_korunur_geri_gelince_telafi(ortam_yap, tmp_path):
    """M2 / F1: dizine erişilemez → 5/10/15 benzeri tekrar → ERİŞİLEMEZ + KRİTİK alarm + kesinti kaydı; aktif
    dosyalar 'kalktı' SAYILMAZ; geri gelince yalnızca kesintide gelen dosya tetiklenir; alarm/kesinti kapanır."""
    o = tarama_ortami(ortam_yap, tmp_path)
    d, dizin_id = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    (d / "onceden.csv").write_text("1", encoding="utf-8")
    bekle_tetik(o, "onceden.csv")
    uzak = tmp_path / "gelen_uzakta"
    os.rename(d, uzak)                                          # paylaşım düştü
    o.bekle(lambda: o.db.tek("SELECT erisim_durumu FROM dizin WHERE id=?", (dizin_id,))["erisim_durumu"]
            == "ERISILEMEZ", zaman_asimi=15, mesaj="ERISILEMEZ olmadı")
    alarm = o.db.tek("SELECT * FROM alarm WHERE anahtar=? AND aktif=1", (f"dizin:{dizin_id}:erisilemez",))
    assert alarm and alarm["seviye"] == "KRITIK"
    assert o.hdb.tek("SELECT COUNT(*) FROM kesinti WHERE bitti IS NULL")[0] == 1
    assert o.db.tek("SELECT kalkma_zamani FROM dosya WHERE dosya_adi='onceden.csv'")["kalkma_zamani"] is None
    (uzak / "kesintide.csv").write_text("2", encoding="utf-8")
    os.rename(uzak, d)                                          # paylaşım geri geldi
    bekle_tetik(o, "kesintide.csv", zaman_asimi=15)
    o.bekle(lambda: o.db.tek("SELECT erisim_durumu FROM dizin WHERE id=?", (dizin_id,))["erisim_durumu"]
            == "ERISILEBILIR")
    time.sleep(1.5)
    assert len(o.tetikler("onceden.csv")) == 1
    assert o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar=? AND aktif=1", (f"dizin:{dizin_id}:erisilemez",))[0] == 0
    assert o.hdb.tek("SELECT COUNT(*) FROM kesinti WHERE bitti IS NULL")[0] == 0


def test_okunamayan_dosya_bilinmiyor_sayilir_izin_gelince_tetiklenir(ortam_yap, tmp_path):
    """F2 / C4: okunamayan (erişim reddedilen) dosya OKUNAMIYOR olarak izlenir, tetiklenmez, diğer dosyaları
    etkilemez; izin gelince tek tetik."""
    import subprocess
    o = tarama_ortami(ortam_yap, tmp_path)
    d, _ = yeni_dizin(o, tmp_path)
    o.cekirdek_baslat()
    tarama_hazir(o)
    p = d / "yasak.csv"
    p.write_text("gizli", encoding="utf-8")
    kul = os.environ["USERNAME"]
    subprocess.run(["icacls", str(p), "/deny", f"{kul}:(R)"], capture_output=True, check=True)
    try:
        o.bekle(lambda: (s := o.yukleme("yasak.csv")) and s["durum"] == "OKUNAMIYOR", zaman_asimi=10,
                mesaj="OKUNAMIYOR olmadı")
        (d / "serbest.csv").write_text("acik", encoding="utf-8")
        bekle_tetik(o, "serbest.csv")
        assert o.tetikler("yasak.csv") == []
    finally:
        subprocess.run(["icacls", str(p), "/remove:d", kul], capture_output=True)
    bekle_tetik(o, "yasak.csv")
    time.sleep(1.5)
    assert len(o.tetikler("yasak.csv")) == 1 and len(o.tetikler("serbest.csv")) == 1


def test_ag_yolu_asili_ya_da_yok_digerleri_calismaya_devam_eder(ortam_yap, tmp_path):
    """Ağ hataları: yanıt vermeyen (asılı) UNC yolu ve var olmayan sunucu. Yerel dizin tetiklemeye devam eder;
    asılı dizin YANITSIZ/ERİŞİLEMEZ + alarm; çift tetik yok."""
    o = tarama_ortami(ortam_yap, tmp_path, dizin_tarama_zaman_asimi_sn=2)
    d, _ = yeni_dizin(o, tmp_path)
    asili = o.yap.dizin_ekle(r"\\10.255.255.1\fwp_test_paylasim", "TETIKLE", ".csv", kullanici="test")
    yok = o.yap.dizin_ekle(r"\\fwp-olmayan-sunucu-xyz\paylasim", "TETIKLE", ".csv", kullanici="test")
    for k in (asili, yok):
        o.kural_kur(k, r".*\.csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    for i in range(6):
        (d / f"ag{i}.csv").write_text(str(i), encoding="utf-8")
        time.sleep(1.5)
    o.bekle(lambda: len(o.tetikler()) >= 6, zaman_asimi=40, mesaj="yerel dizin tetiklemeyi sürdürmedi")
    o.bekle(lambda: o.db.tek("SELECT erisim_durumu FROM dizin WHERE id=?", (yok,))["erisim_durumu"]
            in ("DENENIYOR", "ERISILEMEZ"), zaman_asimi=30)
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM alarm WHERE aktif=1 AND (anahtar=? OR anahtar=?)",
                             (f"dizin:{asili}:yanitsiz", f"dizin:{asili}:erisilemez"))[0] >= 1,
            zaman_asimi=40, mesaj="asılı dizin için alarm yok")
    time.sleep(1)
    adlar = [t["dosya_adi"] for t in o.tetikler()]
    assert sorted(adlar) == [f"ag{i}.csv" for i in range(6)]      # kayıp yok, çift yok
    assert o.proc.poll() is None
