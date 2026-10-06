"""Adım 7 testleri: teslim + lokal kayıt + sahte Control-M (gerçek çekirdek, tarama ve teslim süreçleri).

Olay tablosu karşılıkları her testin açıklamasında yazılıdır. Her testte 'kayıp yok' ve 'çift yok' (ya da
çift yalnızca belirsiz sonuçta ve işaretli) ayrıca doğrulanır.
"""
import json
import os
import time
from pathlib import Path

import pytest

from cekirdek import win
from testler.conftest import HIZLI_TARAMA
from testler.sahte_controlm import SahteControlM

os.environ["FWP_CTM_SIFRE"] = "gizli"          # test sırrı; adaptör env: referansıyla okur

EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
              {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"}]
HIZLI_TESLIM = {**HIZLI_TARAMA, "sabitlik_W_sn": 0.3, "deneme_plani": "0.5,1,1.5", "cagri_timeout_sn": 1,
                "otomatik_devre_esigi": 0, "erit_hizi": 20, "sla_hedef_sn": 10}


@pytest.fixture
def sahte():
    s = SahteControlM().baslat()
    yield s
    s.durdur()


def kur(ortam_yap, tmp_path, sahte, ayarlar=None, regex=r"(?P<tur>[A-Z]+)_(?P<tarih>\d{8})\.csv", tur="CONTROLM",
        adres=None):
    o = ortam_yap(eklentiler=EKLENTILER, ayarlar={**HIZLI_TESLIM, **(ayarlar or {})})
    d = tmp_path / "gelen"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    hedef_id = o.yap.hedef_ekle("controlm", adres or sahte.adres, tur=tur,
                                ayrintilar={"ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwp",
                                            "sifre_ref": "env:FWP_CTM_SIFRE"}, kullanici="test")
    kural_id = o.yap.kural_ekle(dizin_id, "fatura", regex, hedef_id,
                                is_bilgisi={"folder": "FWP_KLASOR", "jobs": "FWP_ISI", "degiskenler": {"ORTAM": "test"}},
                                kullanici="test")
    o.cekirdek_baslat()
    o.bekle(lambda: all((s := o.eklenti(a)) and s["durum"] == "CALISIYOR" for a in ("tarama", "teslim")))
    return o, d, dizin_id, hedef_id, kural_id


def yaz(d: Path, *adlar):
    for ad in adlar:
        (d / ad).write_text(ad, encoding="utf-8")


def tetik(o, ad):
    return o.db.tek("SELECT * FROM tetik WHERE dosya_adi=?", (ad,))


def durum_bekle(o, ad, durum, zaman_asimi=20):
    return o.bekle(lambda: (t := tetik(o, ad)) and t["durum"] == durum and t, zaman_asimi=zaman_asimi,
                   mesaj=f"{ad} {durum} olmadı (şu an: {(tetik(o, ad) or {}) and tetik(o, ad)['durum']})")


def hepsi_durumda(o, adlar, durum, zaman_asimi=30):
    o.bekle(lambda: all((t := tetik(o, a)) and t["durum"] == durum for a in adlar), zaman_asimi=zaman_asimi,
            mesaj=f"hepsi {durum} olmadı: {[(a, (tetik(o, a) or {}) and tetik(o, a)['durum']) for a in adlar]}")


def cift_yok(sahte, idempotencyler):
    say = sahte.idempotency_sayilari()
    assert all(say[i] == 1 for i in idempotencyler), f"kayıp/çift var: {[say[i] for i in idempotencyler]}"


# ================================================================ temel teslim
def test_normal_teslim_govde_ve_sla(ortam_yap, tmp_path, sahte):
    """H1 / K1: dosya → Control-M run/order; gövde, değişkenler, regex grupları; SLA ölçülür; tek sipariş."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    yaz(d, "FATURA_20260929.csv")
    t = durum_bekle(o, "FATURA_20260929.csv", "ILETILDI")
    assert t["sure_ms"] < 10_000 and t["sla_ihlali"] == 0 and t["deneme_sayisi"] == 1 and t["belirsiz"] == 0
    assert "runId=" in t["sonuc"]
    s = sahte.siparisler[0]["govde"]
    assert s["ctm"] == "ctmsunucu" and s["folder"] == "FWP_KLASOR" and s["jobs"] == "FWP_ISI"
    deg = {k: v for d_ in s["variables"] for k, v in d_.items()}
    assert deg["TARIH"] == "20260929" and deg["TUR"] == "FATURA" and deg["ORTAM"] == "test"
    assert deg["FWP_DOSYA"] == "FATURA_20260929.csv" and deg["FWP_KIMLIK"] == t["idempotency"]
    cift_yok(sahte, [t["idempotency"]])
    assert sahte.girisler == 1


def test_gecici_hata_sonra_basari(ortam_yap, tmp_path, sahte):
    """H2: 503, 503, sonra başarı → 3. denemede ILETILDI; deneme geçmişi tutulur; tek sipariş."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("hata503", adet=2)
    yaz(d, "IADE_20260101.csv")
    t = durum_bekle(o, "IADE_20260101.csv", "ILETILDI")
    gecmis = json.loads(t["deneme_gecmisi"])
    assert t["deneme_sayisi"] == 3 and [g["tur"] for g in gecmis] == ["GECICI", "GECICI", "BASARI"]
    assert gecmis[0]["kod"] == 503
    cift_yok(sahte, [t["idempotency"]])


def test_deneme_plani_biter_lokale_yazilir(ortam_yap, tmp_path, sahte):
    """S1: hata devam ederse plan (0.5/1/1.5 sn) bitince LOKALDE + JSON kayıt + hata.db + alarm; sipariş yok."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("hata500")
    yaz(d, "A_20260101.csv")
    t = durum_bekle(o, "A_20260101.csv", "LOKALDE")
    assert t["deneme_sayisi"] == 4 and t["sebep"] == "SLA_SON_DOLDU"
    o.bekle(lambda: tetik(o, "A_20260101.csv")["lokal_dosya"])
    kayit = json.loads(Path(tetik(o, "A_20260101.csv")["lokal_dosya"]).read_text(encoding="utf-8"))
    assert kayit["idempotency"] == t["idempotency"] and len(kayit["deneme_gecmisi"]) == 4
    g = o.hdb.tek("SELECT * FROM gonderilemeyen WHERE anahtar=?", (t["idempotency"],))
    assert g["sebep"] == "SLA_SON_DOLDU" and g["cozuldu"] == 0
    o.bekle(lambda: o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:lokalde",)))
    assert sahte.siparisler == []


def test_kalici_hata_tekrar_denenmez(ortam_yap, tmp_path, sahte):
    """H5: 400 (klasör yok) → tekrar denenmez, LOKALDE + KALICI_HATA + KRİTİK yapılandırma alarmı."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("hata400")
    yaz(d, "B_20260101.csv")
    t = durum_bekle(o, "B_20260101.csv", "LOKALDE")
    assert t["deneme_sayisi"] == 1 and t["sebep"] == "KALICI_HATA" and t["son_http_kodu"] == 400
    assert "does not exist" in t["son_hata"]
    a = o.db.tek("SELECT * FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:kalici",))
    assert a and a["seviye"] == "KRITIK"


def test_token_suresi_dolunca_yeniden_oturum(ortam_yap, tmp_path, sahte):
    """Control-M tuhaflığı: süresi dolmuş token 500 döner → adaptör yeniden oturum açar, deneme sayılmaz."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    yaz(d, "C_20260101.csv")
    durum_bekle(o, "C_20260101.csv", "ILETILDI")
    sahte.mod_ayarla("token_500", adet=1)
    yaz(d, "C_20260102.csv")
    t = durum_bekle(o, "C_20260102.csv", "ILETILDI")
    assert t["deneme_sayisi"] == 1 and sahte.girisler == 2
    sahte.mod_ayarla("token_dolu", adet=1)
    yaz(d, "C_20260103.csv")
    t = durum_bekle(o, "C_20260103.csv", "ILETILDI")
    assert t["deneme_sayisi"] == 1 and sahte.girisler == 3


def test_belirsiz_sonuc_kayipsiz_ve_olasi_cift_isaretli(ortam_yap, tmp_path, sahte):
    """H4: sipariş işlenir ama cevap zaman aşımına uğrar → tekrar denenir (kayıpsızlık önce); tetik 'belirsiz'
    işaretlenir. Control-M tarafında aynı idempotency ile iki sipariş görülebilir (tespit edilebilir çift)."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("belirsiz", adet=1, gecikme=2.5)
    yaz(d, "D_20260101.csv")
    t = durum_bekle(o, "D_20260101.csv", "ILETILDI")
    assert t["belirsiz"] == 1 and t["deneme_sayisi"] == 2
    assert json.loads(t["deneme_gecmisi"])[0]["tur"] == "BELIRSIZ"
    assert sahte.idempotency_sayilari()[t["idempotency"]] == 2      # çift gerçek, ama işaretli ve anahtarı aynı


def test_baglanti_kopmasi_tekrar_denenir(ortam_yap, tmp_path, sahte):
    """Bağlantı cevapsız kapanır (Control-M süreç düştü) → belirsiz, tekrar → başarı; sipariş işlenmediği için tek."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("kopma", adet=2)
    yaz(d, "E_20260101.csv")
    t = durum_bekle(o, "E_20260101.csv", "ILETILDI")
    assert t["deneme_sayisi"] == 3
    cift_yok(sahte, [t["idempotency"]])


def test_hiz_siniri_429_bekler(ortam_yap, tmp_path, sahte):
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    sahte.mod_ayarla("hiz_siniri", adet=1)
    yaz(d, "F_20260101.csv")
    t = durum_bekle(o, "F_20260101.csv", "ILETILDI")
    g = json.loads(t["deneme_gecmisi"])
    assert g[0]["kod"] == 429 and g[1]["z"] - g[0]["z"] >= 0.95                 # Retry-After: 1 sn'ye uyuldu


def test_sla_ihlali_kaydedilir(ortam_yap, tmp_path, sahte):
    """SLA: hedef süre aşılırsa tetik yine gider ama sla_ihlali işaretlenir ve olay yazılır."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, {"sla_hedef_sn": 1, "cagri_timeout_sn": 4})
    sahte.mod_ayarla("yavas", adet=1, gecikme=1.5)
    yaz(d, "G_20260101.csv")
    t = durum_bekle(o, "G_20260101.csv", "ILETILDI")
    assert t["sla_ihlali"] == 1 and t["sure_ms"] >= 1000


# ================================================================ kapatma, lokal kayıt, kademeli erit
def test_controlm_kapat_lokal_kayit_kademeli_erit(ortam_yap, tmp_path, sahte):
    """HEDEF KOŞULU (U1, U5, U6, S1): Control-M kapat (kayıtlı) → gelenler lokale yazılır, hiç çağrı gitmez →
    aç → yeni dosya canlı yoldan hemen gider, eskiler lokalde bekler → kademeli erit (hız 5/sn) → hepsi geliş
    sırasıyla tam bir kez iletilir; lokal dosyalar silinir; hata.db çözüldü; erit biter; alarmlar kapanır."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="deniz")
    adlar = [f"H_2026010{i}.csv" for i in range(1, 10)] + ["H_20260110.csv"]
    for a in adlar:
        yaz(d, a)
        time.sleep(0.05)
    hepsi_durumda(o, adlar, "LOKALDE")
    o.bekle(lambda: all(tetik(o, a)["lokal_dosya"] for a in adlar))
    assert all(Path(tetik(o, a)["lokal_dosya"]).exists() for a in adlar)
    assert sahte.siparisler == [] and len(sahte.istekler) == 0
    assert all(tetik(o, a)["sebep"] == "HEDEF_KAPALI_KAYITLI" for a in adlar)
    o.yap.hedef_ac(hedef_id, kullanici="deniz")
    yaz(d, "CANLI_20260201.csv")
    durum_bekle(o, "CANLI_20260201.csv", "ILETILDI")
    time.sleep(1)
    assert all(tetik(o, a)["durum"] == "LOKALDE" for a in adlar)           # erit kendiliğinden başlamaz
    t0 = time.time()
    o.yap.erit_baslat(hedef_id, hiz=5, kullanici="deniz")
    hepsi_durumda(o, adlar, "ILETILDI")
    sure = time.time() - t0
    assert sure >= 1.5, f"hız sınırına uyulmadı ({sure:.2f} sn)"
    sirali = [s["govde"]["variables"] for s in sahte.siparisler]
    gelen = [next(v["FWP_DOSYA"] for v in s if "FWP_DOSYA" in v) for s in sirali][1:]
    assert gelen == adlar                                                      # geliş sırasıyla (FIFO)
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar + ["CANLI_20260201.csv"]])
    assert not any(Path(tetik(o, a)["lokal_dosya"]).exists() for a in adlar)
    assert o.hdb.tek("SELECT COUNT(*) FROM gonderilemeyen WHERE cozuldu=0")[0] == 0
    o.bekle(lambda: o.db.tek("SELECT erit_durumu FROM hedef WHERE id=?", (hedef_id,))["erit_durumu"] == "YOK")
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM alarm WHERE aktif=1 AND anahtar LIKE ?", (f"hedef:{hedef_id}:%",))[0]
            == 0, mesaj="hedef alarmları kapanmadı")
    islemler = [r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE kullanici='deniz' ORDER BY id")]
    assert islemler == ["HEDEF_KAPAT", "HEDEF_AC", "ERIT_BASLAT"]


def test_kayitsiz_kapatma_lokale_yazmaz(ortam_yap, tmp_path, sahte):
    """U2 / U3: kayıtsız kapalıyken gelenler KAYITSIZ_KAPALI olur; lokal dosya yok; hata.db'de sebep görünür
    (çözüldü: kayıtsız kapatma); açınca erit edilecek bir şey yoktur."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITSIZ", kullanici="deniz")
    yaz(d, "K_20260101.csv", "K_20260102.csv")
    hepsi_durumda(o, ["K_20260101.csv", "K_20260102.csv"], "KAYITSIZ_KAPALI")
    assert all(tetik(o, a)["lokal_dosya"] is None for a in ["K_20260101.csv", "K_20260102.csv"])
    g = o.hdb.oku("SELECT * FROM gonderilemeyen WHERE sebep='HEDEF_KAPALI_KAYITSIZ'")
    assert len(g) == 2 and all(r["cozuldu"] == 1 and r["cozum"] == "KAYITSIZ_KAPATMA" for r in g)
    assert list(Path(o.veri / "lokal_kayit").rglob("*.json")) == []
    o.yap.hedef_ac(hedef_id, kullanici="deniz")
    yaz(d, "K_20260103.csv")
    durum_bekle(o, "K_20260103.csv", "ILETILDI")
    assert len(sahte.siparisler) == 1


def test_kural_kapatma_kayitli(ortam_yap, tmp_path, sahte):
    """U1 (kural bazında): yalnızca kapatılan kuralın dosyaları lokale gider."""
    o, d, dizin_id, hedef_id, kural_id = kur(ortam_yap, tmp_path, sahte)
    o.yap.kural_ekle(dizin_id, "diger", r"DIGER_\d+\.csv", hedef_id, sira=5,
                     is_bilgisi={"folder": "F2", "jobs": "J2"}, kullanici="test")
    o.yap.kural_kapat(kural_id, "KAYITLI", kullanici="deniz")
    yaz(d, "L_20260101.csv", "DIGER_1.csv")
    durum_bekle(o, "L_20260101.csv", "LOKALDE")
    durum_bekle(o, "DIGER_1.csv", "ILETILDI")
    assert tetik(o, "L_20260101.csv")["sebep"] == "KURAL_KAPALI_KAYITLI"


def test_controlm_coker_sonra_erit(ortam_yap, tmp_path, sahte):
    """Control-M tamamen kapandı (bağlantı reddi) → plan sonunda lokale → sunucu geri geldi → erit → kayıpsız."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    sahte.durdur()
    adlar = ["M_20260101.csv", "M_20260102.csv", "M_20260103.csv"]
    yaz(d, *adlar)
    hepsi_durumda(o, adlar, "LOKALDE")
    assert all(json.loads(tetik(o, a)["deneme_gecmisi"])[0]["tur"] == "GECICI" for a in adlar)
    sahte.yeniden_baslat()
    o.yap.erit_baslat(hedef_id, kullanici="deniz")
    hepsi_durumda(o, adlar, "ILETILDI")
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])


def test_erit_sirasinda_controlm_yine_coker(ortam_yap, tmp_path, sahte):
    """U7: erit sürerken hata → erit otomatik duraklar + alarm; kalanlar lokalde; tekrar başlatınca tamamlanır."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, {"erit_hizi": 2})
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="deniz")
    adlar = [f"N_202601{i:02d}.csv" for i in range(1, 9)]
    yaz(d, *adlar)
    hepsi_durumda(o, adlar, "LOKALDE")
    o.yap.hedef_ac(hedef_id, kullanici="deniz")
    o.yap.erit_baslat(hedef_id, kullanici="deniz")
    o.bekle(lambda: sum(tetik(o, a)["durum"] == "ILETILDI" for a in adlar) >= 2)
    sahte.mod_ayarla("hata503")
    o.bekle(lambda: o.db.tek("SELECT erit_durumu FROM hedef WHERE id=?", (hedef_id,))["erit_durumu"] == "DURAKLATILDI",
            zaman_asimi=15, mesaj="erit duraklamadı")
    o.bekle(lambda: o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:erit",)))
    kalan = [a for a in adlar if tetik(o, a)["durum"] != "ILETILDI"]
    assert kalan and all(tetik(o, a)["durum"] == "LOKALDE" for a in kalan)
    sahte.mod_ayarla("normal")
    o.yap.erit_baslat(hedef_id, kullanici="deniz")
    hepsi_durumda(o, adlar, "ILETILDI")
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])


def test_devre_kesici_ve_elle_normale_alma(ortam_yap, tmp_path, sahte):
    """H6: art arda 3 hata → devre KESILDI + KRİTİK alarm; sonraki dosyalar denenmeden lokale (DEVRE_KESIK);
    kesikken sağlık yoklaması 'yanıt veriyor' gösterir; elle normale alınca yeni dosyalar canlı gider."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, {"otomatik_devre_esigi": 3})
    sahte.mod_ayarla("hata503")
    yaz(d, "P_20260101.csv")
    o.bekle(lambda: o.db.tek("SELECT devre_durumu FROM hedef WHERE id=?", (hedef_id,))["devre_durumu"] == "KESILDI",
            zaman_asimi=15)
    assert o.db.tek("SELECT seviye FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:devre",))["seviye"] == "KRITIK"
    istek_sayisi = len(sahte.istekler)
    yaz(d, "P_20260102.csv")
    t = durum_bekle(o, "P_20260102.csv", "LOKALDE")
    assert t["sebep"] == "DEVRE_KESIK" and t["deneme_sayisi"] == 0
    assert len(sahte.istekler) == istek_sayisi                                   # hiç denenmedi
    o.bekle(lambda: (o.db.tek("SELECT saglik FROM hedef WHERE id=?", (hedef_id,))["saglik"] or "").startswith("YANIT_VERIYOR"),
            zaman_asimi=10, mesaj="sağlık yoklaması yapılmadı")
    sahte.mod_ayarla("normal")
    o.yap.devre_sifirla(hedef_id, kullanici="deniz")
    yaz(d, "P_20260103.csv")
    durum_bekle(o, "P_20260103.csv", "ILETILDI")
    o.yap.erit_baslat(hedef_id, kullanici="deniz")
    hepsi_durumda(o, ["P_20260101.csv", "P_20260102.csv"], "ILETILDI")


# ================================================================ dayanıklılık
def _alti_tetik(o, d, onek):
    adlar = [f"{onek}_2026060{i}.csv" for i in range(1, 7)]
    for a in adlar:
        yaz(d, a)
    o.bekle(lambda: all(tetik(o, a) for a in adlar), mesaj="tetikler oluşmadı")
    return adlar


def test_kapanista_bekleyenler_sure_icinde_gonderilir(ortam_yap, tmp_path, sahte):
    """H10 (kullanıcı kararı 2026-09-30): kapanırken bekleyen tetiklere süre tanınır; bu sürede hepsi gönderilir,
    kuyruk boşalınca kapanış beklemeden biter."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, ayarlar={"kapanis_teslim_bekleme_sn": 20, "esz_cagri_ust": 1,
                                                          "cagri_timeout_sn": 3})
    sahte.mod_ayarla("yavas", gecikme=0.5)                   # 6 × 0,5 sn: kapanış anında çoğu bekliyor
    adlar = _alti_tetik(o, d, "K")
    assert sum(tetik(o, a)["durum"] == "ILETILDI" for a in adlar) < 6
    t0 = time.time()
    o.cekirdek_kapat(zaman_asimi=60)
    assert all(tetik(o, a)["durum"] == "ILETILDI" for a in adlar), [tetik(o, a)["durum"] for a in adlar]
    assert time.time() - t0 < 15, "kuyruk boşaldığı hâlde süre sonuna kadar beklendi"
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])


def test_kapanista_sure_dolarsa_kalanlar_acilista_gider(ortam_yap, tmp_path, sahte):
    """H10: süre dolunca kapanış tamamlanır; gönderilemeyenler kaybolmaz ve lokale de yazılmaz (veritabanında
    bekler), açılışta kendiliğinden gönderilir; yoldaki çağrı kesilmez; çift yok."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, ayarlar={"kapanis_teslim_bekleme_sn": 1, "esz_cagri_ust": 1,
                                                          "cagri_timeout_sn": 5})
    sahte.mod_ayarla("yavas", gecikme=1.5)
    adlar = _alti_tetik(o, d, "S")
    t0 = time.time()
    o.cekirdek_kapat(zaman_asimi=60)
    assert time.time() - t0 < 15
    durumlar = [tetik(o, a)["durum"] for a in adlar]
    assert 1 <= durumlar.count("ILETILDI") < 6, durumlar
    assert set(durumlar) <= {"ILETILDI", "BEKLIYOR"}, durumlar          # lokale yazılmadı, yarıda kalan yok
    assert all(tetik(o, a)["belirsiz"] == 0 for a in adlar)
    sahte.mod_ayarla("normal")
    o.cekirdek_baslat()
    hepsi_durumda(o, adlar, "ILETILDI")
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])


def test_teslim_sureci_cagri_sirasinda_olurse_kurtarilir(ortam_yap, tmp_path, sahte):
    """G5 / M4: teslim süreci çağrı sırasında öldürülür → gözetmen yeniden başlatır → yarım çağrı TEKRAR +
    'belirsiz' işaretli → iletilir. Kayıp yok; olası çift işaretli."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, {"cagri_timeout_sn": 10})
    sahte.mod_ayarla("yavas", adet=1, gecikme=4)
    yaz(d, "R_20260101.csv")
    o.bekle(lambda: (t := tetik(o, "R_20260101.csv")) and t["durum"] == "DENENIYOR")
    eski = o.eklenti("teslim")["pid"]
    os.kill(eski, 9)
    t = durum_bekle(o, "R_20260101.csv", "ILETILDI", zaman_asimi=30)
    assert t["belirsiz"] == 1
    assert o.eklenti("teslim")["pid"] != eski and o.proc.poll() is None
    assert sahte.idempotency_sayilari()[t["idempotency"]] in (1, 2)


def test_lokal_kayittan_geri_yukleme_ve_bozuk_kayit(ortam_yap, tmp_path, sahte):
    """S4 + çift güvence: veritabanından kaybolan LOKALDE tetik JSON'dan geri yüklenir; bozuk JSON
    karantinaya alınır + KRİTİK alarm + hata.db kaydı."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    yaz(d, "S_20260101.csv")
    t = durum_bekle(o, "S_20260101.csv", "LOKALDE")
    o.bekle(lambda: tetik(o, "S_20260101.csv")["lokal_dosya"])
    yol = Path(tetik(o, "S_20260101.csv")["lokal_dosya"])
    bozuk = yol.parent / "9999_bozukkayit.json"
    bozuk.write_text("{ yarım json", encoding="utf-8")
    o.db.komut_gonder("gozetmen", "DURDUR", {"ad": "teslim"}, kullanici="test")
    o.bekle(lambda: o.eklenti("teslim")["durum"] == "DURDURULDU")
    o.db.calistir("DELETE FROM tetik WHERE dosya_adi='S_20260101.csv'")           # veritabanı kaybı
    o.db.komut_gonder("gozetmen", "BASLAT", {"ad": "teslim"}, kullanici="test")
    t2 = o.bekle(lambda: tetik(o, "S_20260101.csv"), mesaj="geri yüklenmedi")
    assert t2["durum"] == "LOKALDE" and t2["idempotency"] == t["idempotency"]
    o.bekle(lambda: not bozuk.exists(), mesaj="bozuk kayıt karantinaya alınmadı")   # aynı turda, iyi kayıttan sonra
    assert list(Path(o.veri / "karantina").glob("*bozukkayit.json"))
    assert o.db.tek("SELECT seviye FROM alarm WHERE anahtar LIKE 'lokal:bozuk:%' AND aktif=1")["seviye"] == "KRITIK"
    assert o.hdb.tek("SELECT COUNT(*) FROM gonderilemeyen WHERE sebep='LOKAL_KAYIT_BOZUK'")[0] == 1
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.yap.erit_baslat(hedef_id, kullanici="test")
    durum_bekle(o, "S_20260101.csv", "ILETILDI")
    cift_yok(sahte, [t["idempotency"]])


def test_lokal_kayit_yazilamazsa_veritabaninda_guvende(ortam_yap, tmp_path, sahte):
    """S3: lokal kayıt klasörü yazılamaz → KRİTİK alarm; tetik veritabanında LOKALDE (kayıp yok);
    sorun giderilince yazım otomatik tamamlanır ve alarm kapanır."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    engel = o.veri / "lokal_kayit" / "controlm"
    engel.parent.mkdir(parents=True, exist_ok=True)
    engel.write_text("klasör olması gereken yerde dosya", encoding="utf-8")   # mkdir başarısız olur
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    yaz(d, "T_20260101.csv")
    t = durum_bekle(o, "T_20260101.csv", "LOKALDE")
    o.bekle(lambda: o.db.tek("SELECT seviye FROM alarm WHERE anahtar='lokal:yazilamadi' AND aktif=1"))
    assert tetik(o, "T_20260101.csv")["lokal_dosya"] is None
    engel.unlink()
    o.bekle(lambda: tetik(o, "T_20260101.csv")["lokal_dosya"], mesaj="yazım yeniden denenmedi")
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar='lokal:yazilamadi' AND aktif=1")[0] == 0)


def test_kapali_unutulan_hedef_hatirlatilir(ortam_yap, tmp_path, sahte):
    """U13: hedef 'kapali_hatirlatma_dk'dan uzun kapalı kalırsa hatırlatma alarmı; açınca kapanır."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    o.db.calistir("UPDATE hedef SET kapatma_zamani=? WHERE id=?", (time.time() - 3 * 3600, hedef_id))

    with o.db.yaz() as con:
        o.db.yapilandirma_degisti(con)
    o.bekle(lambda: o.db.tek("SELECT mesaj FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:kapali",)),
            mesaj="hatırlatma yok")
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{hedef_id}:kapali",))[0] == 0)


def test_genel_http_adaptoru(ortam_yap, tmp_path, sahte):
    """Evrensel hedef: HTTP webhook adaptörü de aynı kuyrukla çalışır."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, tur="HTTP", adres=f"http://127.0.0.1:{sahte.port}/webhook")
    yaz(d, "W_20260101.csv")
    t = durum_bekle(o, "W_20260101.csv", "ILETILDI")
    assert sahte.webhook[0]["idempotency"] == t["idempotency"]
    assert sahte.webhook[0]["govde"]["gruplar"] == {"tur": "W", "tarih": "20260101"}


def test_kapali_hedef_yeniden_baslatmada_kapali_kalir(ortam_yap, tmp_path, sahte):
    """U9: hedef kapalıyken çekirdek yeniden başlarsa kapalı kalır; Control-M'e yığılma olmaz."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    yaz(d, "U_20260101.csv")
    durum_bekle(o, "U_20260101.csv", "LOKALDE")
    o.cekirdek_kapat()
    yaz(d, "U_20260102.csv")
    o.cekirdek_baslat()
    durum_bekle(o, "U_20260102.csv", "LOKALDE")
    time.sleep(1)
    assert sahte.siparisler == [] and o.db.tek("SELECT aktif FROM hedef WHERE id=?", (hedef_id,))["aktif"] == 0


def test_lokal_kayit_atomik_ve_yarim_kalan_temizligi(tmp_path):
    """S2: yazım geçici ad + fsync + os.replace ile atomiktir; yarım kalmış .tmp dosyaları temizlenir."""
    from eklentiler.teslim.lokal_kayit import LokalKayit
    lk = LokalKayit(tmp_path / "lk", tmp_path / "kar")
    k = {"idempotency": "abcdef0123456789xx", "hedef": "controlm", "dosya_adi": "a.csv", "tam_yol": "x\a.csv",
         "parametreler": {"a": 1}, "olusturma": time.time()}
    yol = lk.yaz(k)
    assert lk.oku(yol)["parametreler"] == {"a": 1} and not list((tmp_path / "lk").rglob("*.tmp"))
    yarim = Path(yol).with_name("yarim.tmp")
    yarim.write_text("{", encoding="utf-8")
    assert lk.yarim_kalanlari_temizle() == 1 and not yarim.exists() and Path(yol).exists()


# ================================================================ kuralın kendi isteği (2026-09-30)
ISTEK_OLAY = {"yontem": "POST", "yol": "/run/event/{ctm}/SEVK_{depo}_GELDI/ODAT",
              "govde": '{"dosya": "{tam_yol}", "tarih": "{tarih}", "kimlik": "{kimlik}"}'}


def test_kural_istegi_olay_ekle_ile_teslim(ortam_yap, tmp_path, sahte):
    """Kullanıcı kararı 2026-09-30: kural kendi isteğini taşır (yöntem, yol, gövde şablonu). Değişkenler yerleşir:
    {ctm} hedeften, {depo}/{tarih} regex'ten ((?<ad>…) yazımı da kabul), {tam_yol} ters bölüleriyle JSON'u bozmaz."""
    o, d, dizin_id, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.kural_ekle(dizin_id, "sevk", r"SEVK_(?<depo>[A-Z]{3})_(?P<tarih>\d{8})\.csv", hedef_id, istek=ISTEK_OLAY,
                     kullanici="test")
    time.sleep(1)
    yaz(d, "SEVK_IST_20260930.csv")
    t = durum_bekle(o, "SEVK_IST_20260930.csv", "ILETILDI")
    assert len(sahte.olaylar) == 1
    ol = sahte.olaylar[0]
    assert (ol["ctm"], ol["olay"], ol["tarih"]) == ("ctmsunucu", "SEVK_IST_GELDI", "ODAT")
    assert ol["govde"] == {"dosya": str(d / "SEVK_IST_20260930.csv"), "tarih": "20260930", "kimlik": t["idempotency"]}
    assert ol["idempotency"] == t["idempotency"]
    assert "(?P<depo>" in o.db.tek("SELECT regex FROM kural WHERE ad='sevk'")[0]            # Python biçiminde saklandı


def test_yanlis_istek_kalici_hata_duzeltilip_erit(ortam_yap, tmp_path, sahte):
    """Kuralın isteği yanlışsa (ör. olmayan Control-M sunucusu) kalıcı hata → lokal; kural düzeltilir, erit edilince
    kuralın GÜNCEL (düzeltilmiş) isteği gider; tetik yeniden oluşturulmaz, çift yok."""
    o, d, dizin_id, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    yanlis = {"yontem": "POST", "yol": "/run/event/YOK_SUNUCU/SEVK_{depo}_GELDI/ODAT", "govde": ""}
    kid = o.yap.kural_ekle(dizin_id, "sevk", r"SEVK_(?P<depo>[A-Z]{3})_(?P<tarih>\d{8})\.csv", hedef_id,
                           istek=yanlis, kullanici="test")
    time.sleep(1)
    yaz(d, "SEVK_ANK_20260930.csv")
    t = durum_bekle(o, "SEVK_ANK_20260930.csv", "LOKALDE")
    assert t["sebep"] == "KALICI_HATA" and "not found" in t["son_hata"] and not sahte.olaylar
    o.yap.kural_guncelle(kid, "sevk", r"SEVK_(?P<depo>[A-Z]{3})_(?P<tarih>\d{8})\.csv", hedef_id, istek=ISTEK_OLAY,
                         kullanici="deniz")
    o.yap.erit_baslat(hedef_id, hiz=5, kullanici="deniz")
    t = durum_bekle(o, "SEVK_ANK_20260930.csv", "ILETILDI")
    assert [x["olay"] for x in sahte.olaylar] == ["SEVK_ANK_GELDI"] and t["eritildi"] == 1
    assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='KURAL_GUNCELLE' AND kullanici='deniz'")[0] == 1


def test_istek_sablonu_dogrulamasi_kayitta(ortam_yap, tmp_path, sahte):
    """Kural kaydedilirken bozuk istek reddedilir: bilinmeyen değişken, geçersiz JSON, '/' ile başlamayan yol,
    yerleşik değişkenle çakışan regex grubu."""
    o, d, dizin_id, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    for istek, regex, mesaj in (
            ({"yol": "/x/{yok}"}, r"A\.csv", "bilinmeyen değişken"),
            ({"yol": "/x", "govde": '{"a": {dosya_adi}}'}, r"A\.csv", "JSON"),
            ({"yol": "run/order"}, r"A\.csv", "'/' ile başlamalı"),
            ({"yol": "/x"}, r"(?P<kimlik>\w+)\.csv", "yerleşik değişkenle aynı")):
        with pytest.raises(ValueError, match=mesaj):
            o.yap.kural_ekle(dizin_id, "bozuk", regex, hedef_id, istek=istek, kullanici="test")



def test_bir_dizinde_uc_kural_her_dosya_kendi_istegini_tetikler(ortam_yap, tmp_path, sahte):
    """Kullanıcı sorusu 2026-10-01: bir dizinde farklı regex'lere bakan 3 kural var. A dosyası A kuralının, B dosyası
    B'nin, C dosyası C'nin Control-M isteğini tetikler (her kural kendi isteğini taşır); hiçbirine uymayan dosya
    tetiklenmez, 'kurala uymadı' olarak kaydedilir."""
    o, d, dizin_id, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, regex=r"YOK_\d+\.csv")
    for ad, sira in (("A", 10), ("B", 20), ("C", 30)):
        o.yap.kural_ekle(dizin_id, f"kural_{ad}", rf"{ad}_\d+\.csv", hedef_id, sira=sira,
                         istek={"yontem": "POST", "yol": f"/run/event/{{ctm}}/{ad}_GELDI/ODAT", "govde": ""}, kullanici="test")
    time.sleep(1)
    for ad in ("A_1.csv", "B_1.csv", "C_1.csv", "X_1.csv"):
        yaz(d, ad)
    tetikler = {ad: durum_bekle(o, ad, "ILETILDI") for ad in ("A_1.csv", "B_1.csv", "C_1.csv")}
    o.bekle(lambda: o.hdb.tek("SELECT 1 FROM gonderilemeyen WHERE dosya_adi='X_1.csv' AND sebep='ESLESMEDI'"))
    assert sorted(x["olay"] for x in sahte.olaylar) == ["A_GELDI", "B_GELDI", "C_GELDI"]
    for ad, t in tetikler.items():                                   # her dosya kendi kuralıyla ve kendi isteğiyle gitti
        assert o.db.tek("SELECT ad FROM kural WHERE id=?", (t["kural_id"],))[0] == f"kural_{ad[0]}"
        assert next(x for x in sahte.olaylar if x["idempotency"] == t["idempotency"])["olay"] == f"{ad[0]}_GELDI"
    assert o.tetikler("X_1.csv") == [] and len(sahte.olaylar) == 3



def test_hedef_yavaslayinca_uyari_duzelince_kapanir(ortam_yap, tmp_path, sahte):
    """H9: hedef yavaşlıyor → pencerede SLA aşım oranı ≥ %20 (en az 5 tetik) uyarı alarmı; hedef hızlanınca ve
    yavaş tetikler pencereden çıkınca kendiliğinden kapanır. Kayıp yok: yavaş da olsa hepsi iletilir."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, {"sla_hedef_sn": 1, "cagri_timeout_sn": 4,
                                                             "hedef_yavas_pencere_dk": 0.15})
    anahtar = f"hedef:{hedef_id}:yavas"
    sahte.mod_ayarla("yavas", gecikme=1.5)
    adlar = [f"Y_2026010{i}.csv" for i in range(1, 7)]
    for a in adlar:
        yaz(d, a)
    hepsi_durumda(o, adlar, "ILETILDI", zaman_asimi=60)
    a = o.bekle(lambda: o.db.tek("SELECT mesaj FROM alarm WHERE anahtar=? AND aktif=1", (anahtar,)), zaman_asimi=20)
    assert "yavaşladı" in a[0] and "SLA hedefini (1 sn) aştı" in a[0]
    sahte.mod_ayarla("normal")
    yaz(d, "H_20260101.csv")
    durum_bekle(o, "H_20260101.csv", "ILETILDI")
    o.bekle(lambda: not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (anahtar,)), zaman_asimi=40)



def test_lokale_geri_donen_tetigin_eski_kopyasi_yetim_kalmaz(ortam_yap, tmp_path, sahte):
    """Saha provası bulgusu 2026-10-01: lokaldeki tetik, hedefin adı değiştikten sonra yeniden lokale düşerse (seçerek
    gönder hedef kapalıyken / erit hatası) yeni kopya yeni hedef klasörüne yazılır; eski kopya kalsaydı tetik satırı
    budandıktan sonra açılıştaki geri yükleme onu diriltir ve çift tetik olurdu."""
    from cekirdek import lokal_islem
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    (d / "FATURA_20261001.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "FATURA_20261001.csv")) and t["durum"] == "LOKALDE" and t["lokal_dosya"])
    t = tetik(o, "FATURA_20261001.csv")
    eski = t["lokal_dosya"]
    o.yap.hedef_guncelle(hedef_id, "controlm-yeni", sahte.adres, ayrintilar={
        "ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwp", "sifre_ref": "env:FWP_CTM_SIFRE"}, kullanici="test")
    time.sleep(1.5)                                                   # teslim yeni tanımı alsın
    assert lokal_islem.secilenleri_gonder(o.db, o.hdb, [t["id"]], "test")["gonderilen"] == [t["id"]]
    o.bekle(lambda: (x := tetik(o, "FATURA_20261001.csv")) and x["durum"] == "LOKALDE" and x["lokal_dosya"] != eski)
    yeni = tetik(o, "FATURA_20261001.csv")["lokal_dosya"]
    assert "controlm-yeni" in yeni and Path(yeni).exists()
    assert not Path(eski).exists()                                    # yetim kopya yok
    kopyalar = [f for f in (o.veri / "lokal_kayit").rglob("*.json") if t["idempotency"] in f.read_text(encoding="utf-8")]
    assert kopyalar == [Path(yeni)]
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.yap.erit_baslat(hedef_id, kullanici="test")
    o.bekle(lambda: tetik(o, "FATURA_20261001.csv")["durum"] == "ILETILDI")
    o.bekle(lambda: not list((o.veri / "lokal_kayit").rglob("*.json")), mesaj="lokal kopya silinmedi")  # iletildi'den hemen sonra
    cift_yok(sahte, [t["idempotency"]])



def test_iletildi_ile_dosya_silme_arasinda_olunurse_artik_kopya_acilista_silinir(ortam_yap, tmp_path, sahte):
    """İnceleme bulgusu 2026-10-01: teslim 'iletildi'yi yazdıktan sonra, lokal dosyayı silmeden süreç ölürse artık kopya
    kalır; tetik satırı budandıktan sonra açılıştaki geri yükleme onu diriltip ikinci kez gönderirdi. Açılışta, tetiği
    teslim edilmiş (ya da elle silinmiş) kopya silinir; yeniden gönderilmez."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    (d / "FATURA_20261002.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "FATURA_20261002.csv")) and t["durum"] == "LOKALDE" and t["lokal_dosya"])
    t = tetik(o, "FATURA_20261002.csv")
    yol = Path(t["lokal_dosya"])
    kopya = yol.read_bytes()
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.yap.erit_baslat(hedef_id, kullanici="test")
    o.bekle(lambda: tetik(o, "FATURA_20261002.csv")["durum"] == "ILETILDI" and not yol.exists())
    o.db.komut_gonder("gozetmen", "DURDUR", {"ad": "teslim"}, kullanici="test")
    o.bekle(lambda: o.eklenti("teslim")["durum"] == "DURDURULDU")
    yol.parent.mkdir(parents=True, exist_ok=True)                     # boşalan gün klasörü silinmiş olabilir
    yol.write_bytes(kopya)                                            # çökme penceresi: dosya silinmeden ölmüş gibi
    o.db.komut_gonder("gozetmen", "BASLAT", {"ad": "teslim"}, kullanici="test")
    o.bekle(lambda: not yol.exists(), mesaj="artık kopya açılışta silinmedi")
    o.db.calistir("DELETE FROM tetik WHERE dosya_adi='FATURA_20261002.csv'")      # sonra budama olsa bile
    o.db.komut_gonder("gozetmen", "YENIDEN_BASLAT", {"ad": "teslim"}, kullanici="test")
    time.sleep(3)
    assert tetik(o, "FATURA_20261002.csv") is None                     # diriltilmedi
    cift_yok(sahte, [t["idempotency"]])                               # hedefte tam bir kez
