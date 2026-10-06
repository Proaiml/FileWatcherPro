"""Yapay zekâ asistanı testleri (kullanıcı onayı 2026-09-30: yerel model, çevrimiçi eğitim, öğreniyor mu / ezberliyor mu,
kendine güven, olaylar arası ilişki self-attention ile).

Birim: olay toplama (bir kez), modelin gömülü ilişkiyi dikkatle bulması, ezberin tespiti ve en iyi adıma dönüş,
kalibrasyon, öneriler (beklenen dosya gelmedi, kural). Uçtan uca: gerçek çekirdek + tarama + teslim + kontrol + asistan,
sahte Control-M; API ile ayar, eğitim, geri bildirim, kendini sına. PyTorch yokken: veri toplanır, eğitim yapılmaz.
"""
import json
import time

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cekirdek.kullanicilar import Kullanicilar  # noqa: E402
from eklentiler.asistan import depo, model as M, oneriler, sentetik  # noqa: E402
from eklentiler.asistan.depo import AsistanDB  # noqa: E402
from eklentiler.asistan.toplayici import Toplayici  # noqa: E402
from testler.conftest import HIZLI_TARAMA  # noqa: E402
from testler.sahte_controlm import SahteControlM  # noqa: E402
from testler.test_adim8_kontrol_api import SIFRE, Istemci  # noqa: E402

torch.set_num_threads(1)
AYAR = {k: v[0] for k, v in depo.AYARLAR.items()}


def _tetik(o, i, dosya_id, kural_id, hedef_id, olusturma, **ek):
    alan = {"dosya_id": dosya_id, "kural_id": kural_id, "hedef_id": hedef_id, "idempotency": f"id-{i}", "parametreler": "{}",
            "dosya_adi": f"F_{i}.csv", "tam_yol": f"C:\\x\\F_{i}.csv", "durum": "BEKLIYOR", "olusturma": olusturma, **ek}
    o.db.calistir(f"INSERT INTO tetik({', '.join(alan)}) VALUES({', '.join('?' * len(alan))})", tuple(alan.values()))


# ================================================================ birim
def test_toplayici_olaylari_bir_kez_toplar(ortam_yap, tmp_path):
    o = ortam_yap(eklentiler=[])
    dz = o.dizin_kur(tmp_path / "gelen", "TETIKLE", ".csv")
    hid = o.hedef_kur()
    kid = o.kural_kur(dz, r"F_\d+\.csv", hedef_id=hid)
    adb = AsistanDB(tmp_path / "asistan.db").sema_kur()
    t = time.time()
    _tetik(o, 1, 1, kid, hid, t - 30)
    _tetik(o, 2, 2, kid, hid, t - 20, iletildi_zamani=t - 19, durum="ILETILDI")
    _tetik(o, 3, 3, kid, hid, t - 10, son_deneme=t - 9, deneme_sayisi=2, durum="TEKRAR")
    o.hdb.calistir("INSERT INTO gonderilemeyen(anahtar, sebep, dosya_adi, tam_yol, dizin_yolu, ilk_zaman, son_zaman) VALUES(?,?,?,?,?,?,?)",
                   ("k1", "ESLESMEDI", "X.csv", "C:\\x\\X.csv", str(tmp_path / "gelen"), t - 5, t - 5))
    o.db.alarm_ac(f"dizin:{dz}:erisilemez", "deneme", "KRITIK", "tarama")
    o.db.alarm_kapat(f"dizin:{dz}:erisilemez")
    top = Toplayici(o.db, o.hdb, adb)
    assert top.topla() == 8
    kodlar = sorted((r["kod"], r["nesne"]) for r in adb.oku("SELECT kod, nesne FROM olay"))
    assert kodlar == sorted([("DOSYA_GELDI", f"dizin:{dz}")] * 3 + [("ILETILDI", f"hedef:{hid}"), ("YENIDEN_DENENDI", f"hedef:{hid}"),
                                                                   ("ESLESMEDI", f"dizin:{dz}"), ("ALARM_DIZIN_ERISILEMEZ", f"dizin:{dz}"),
                                                                   ("DUZELDI_DIZIN_ERISILEMEZ", f"dizin:{dz}")])
    assert Toplayici(o.db, o.hdb, adb).topla() == 0                                  # yeniden başlatmada aynı olay iki kez yazılmaz
    o.db.calistir("UPDATE tetik SET iletildi_zamani=?, durum='ILETILDI' WHERE id=1", (time.time(),))
    assert top.topla() == 1
    assert depo.etiket(f"ALARM_DIZIN_ERISILEMEZ|dizin:{dz}", depo.adlar_oku(o.db)) == "Dizine erişilemiyor · gelen"


def test_kendini_sina_verisi_saatten_bagimsiz():
    """Yapay akış her çağrıda aynı olmalı: başlangıç o anki saatten alınınca girdi kayıyor, sınama sonucu çağrıdan
    çağrıya değişiyordu (yarı yarıya kalıyordu)."""
    import time as _t
    a = sentetik.uret()
    _t.sleep(1.1)
    b = sentetik.uret()
    assert a.tok.tolist() == b.tok.tolist() and a.zaman.tolist() == b.zaman.tolist()
    assert len(a.tok) > 6000                                          # 84 günlük akış


def test_model_ogrenir_ve_gomulu_iliskiyi_dikkatle_bulur():
    """Kendini sına: 'Lojistik yanıtsız → devre kesildi' ilişkisi (arada sıradan trafik) Markov'un göremediği, self-attention'ın
    bulması gereken bir ilişkidir. Model Markov'u geçmeli ve dikkat haritasında bu ilişki ilk sırada çıkmalı."""
    r = sentetik.sina(AYAR, tohum=1)
    assert r["sonuc"] == "GECTI", r["maddeler"]
    assert r["olcum"]["iyilesme"] >= 0.05
    assert r["olcum"]["dikkat"][0][0] == "Lojistik yanıtsız" and r["olcum"]["dikkat"][0][1] > 2 * r["olcum"]["dikkat"][1][1] / 1.5
    assert len(r["egri"]["adimlar"]) == len(r["egri"]["dogrulama"]) >= 3


def test_ezber_tespit_edilir_ve_en_iyi_adima_donulur():
    """Düzensiz (rastgele) az veride model ezberler: eğitim kaybı düşerken doğrulama kaybı yükselir. Eğitim durmalı ve en iyi
    doğrulama adımındaki ağırlıklar geri yüklenmeli."""
    rng = np.random.default_rng(3)
    n = 400
    dizi = M.Dizi(rng.integers(1, 25, size=n), np.cumsum(rng.uniform(1, 300, size=n)) + 1.7e9)
    torch.manual_seed(3)
    m = M.OlayModeli(baglam=32, katman=2, bas=4, boyut=64, dropout=0.0)
    r = M.egit(m, dizi, 320, 320, adim=600, sure_sn=120, lr=3e-3, agirlik_azaltma=0.0, degerlendir_her=10, tohum=3)
    assert r["ezber_bas"] is not None, r["egri"]
    e = r["egri"]
    i = e["adimlar"].index(r["en_iyi_adim"])
    assert e["egitim"][-1] < e["egitim"][i] and e["dogrulama"][-1] > e["dogrulama"][i] * 1.01          # ezber: biri düşer, öteki yükselir
    simdi = M.ortalama(M.degerlendir(m, dizi, 320, n)["kayip"])
    assert abs(simdi - r["en_iyi_kayip"]) < 1e-4                                                       # en iyi adıma dönüldü


def test_kalibrasyon_fazla_emin_modeli_duzeltir():
    rng = np.random.default_rng(1)
    gercek = rng.dirichlet(np.ones(8) * 0.7, size=3000)
    hedef = np.array([rng.choice(8, p=p) for p in gercek])
    logit = 3.0 * np.log(gercek + 1e-9)                                        # olasılıklar aşırı keskinleştirilmiş
    T = M.sicaklik_bul(logit, hedef)
    assert 2.4 <= T <= 3.6
    def ece(lg):
        p = np.exp(lg - lg.max(1, keepdims=True))
        p /= p.sum(1, keepdims=True)
        return M.guvenilirlik(p.max(1), (p.argmax(1) == hedef).astype(float))[1]
    assert ece(logit / T) < ece(logit) / 2


def test_beklenen_dosya_gelmedi_onerisi_ve_kendiliginden_kapanir(ortam_yap, tmp_path):
    o = ortam_yap(eklentiler=[])
    dz = o.dizin_kur(tmp_path / "muhasebe", "TETIKLE", ".csv")
    adb = AsistanDB(tmp_path / "asistan.db").sema_kur()
    bugun = time.localtime()
    gece = time.mktime((bugun.tm_year, bugun.tm_mon, bugun.tm_mday, 0, 0, 0, 0, 0, -1))
    rng = np.random.default_rng(2)
    with adb.yaz() as con:
        for d in range(1, 22):
            t = gece - d * 86400 + 9 * 3600 + rng.uniform(-600, 600)
            con.execute("INSERT INTO olay(zaman, kod, nesne, kaynak) VALUES(?,?,?,?)", (t, "DOSYA_GELDI", f"dizin:{dz}", f"t{d}"))
    adlar = depo.adlar_oku(o.db)
    assert oneriler.beklenen_gelmedi(adb, o.db, adlar, simdi=gece + 9 * 3600) == 0                    # henüz erken
    assert oneriler.beklenen_gelmedi(adb, o.db, adlar, simdi=gece + 11.5 * 3600) == 1
    r = adb.tek("SELECT * FROM oneri")
    assert r["tur"] == "BEKLENEN_GELMEDI" and r["kaynak"] == "istatistik" and r["guven"] >= 0.85 and r["durum"] == "ACIK"
    assert "muhasebe" in r["baslik"] and "Dizin erişilebilir" not in r["kanit"]                          # dizin henüz taranmadı
    assert oneriler.beklenen_gelmedi(adb, o.db, adlar, simdi=gece + 11.6 * 3600) == 0                  # aynı öneri iki kez yazılmaz
    adb.calistir("INSERT INTO olay(zaman, kod, nesne, kaynak) VALUES(?,?,?,?)", (gece + 11.7 * 3600, "DOSYA_GELDI", f"dizin:{dz}", "bugun"))
    oneriler.beklenen_gelmedi(adb, o.db, adlar, simdi=gece + 11.8 * 3600)
    assert adb.tek("SELECT durum FROM oneri")[0] == "KAPANDI"


def test_kural_onerisi_eslesmeyen_adlardan_regex(ortam_yap, tmp_path):
    o = ortam_yap(eklentiler=[])
    d = tmp_path / "lojistik"
    dz = o.dizin_kur(d, "TETIKLE", ".csv")
    o.kural_kur(dz, r"SEVK_[A-Z]{3}_\d{8}\.csv")
    adb = AsistanDB(tmp_path / "asistan.db").sema_kur()
    t = time.time()
    for i, ad in enumerate(["SEVK_IZMIR_20260929.csv", "SEVK_IZMIR_20260930.csv", "SEVK_ANTEP_20261001.csv", "notlar.csv"]):
        o.hdb.calistir("INSERT INTO gonderilemeyen(anahtar, sebep, dosya_adi, tam_yol, dizin_yolu, ilk_zaman, son_zaman) VALUES(?,?,?,?,?,?,?)",
                       (f"k{i}", "ESLESMEDI", ad, str(d / ad), str(d), t, t))
    assert oneriler.kural_onerileri(adb, o.db, o.hdb) == 1
    r = adb.tek("SELECT * FROM oneri")
    rx = r["oneri"].split("Regex: ")[1].split(" (")[0]
    import re
    assert all(re.fullmatch(rx, a) for a in ("SEVK_IZMIR_20260929.csv", "SEVK_ANTEP_20261001.csv")) and not re.fullmatch(rx, "notlar.csv")
    assert r["kaynak"] == "kural" and r["guven"] is None
    o.kural_kur(dz, rx, ad="sevk5")                                         # kural eklendi: aynı öneri tekrar üretilmez
    adb.calistir("DELETE FROM oneri")
    assert oneriler.kural_onerileri(adb, o.db, o.hdb) == 0


# ================================================================ uçtan uca
EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"}, {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"},
              {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"}, {"ad": "asistan", "modul": "eklentiler.asistan.asistan"}]


def kur(ortam_yap, eklentiler=EKLENTILER):
    o = ortam_yap(eklentiler=eklentiler, ayarlar={**HIZLI_TARAMA, "sabitlik_W_sn": 0.3})
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    k.ekle("yonetici", SIFRE, "YONETICI")
    k.ekle("operator", SIFRE, "OPERATOR")
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR" and json.loads(e["bilgi"] or "{}").get("port") and e)
    o.bekle(lambda: (e := o.eklenti("asistan")) and e["durum"] == "CALISIYOR")
    y = Istemci(json.loads(s["bilgi"])["port"])
    assert y.giris("yonetici")[0] == 200
    return o, y


def asistan(y):
    kod, v = y.get("/api/asistan")
    assert kod == 200, v
    return v


def test_asistan_eklentisi_uctan_uca(ortam_yap, tmp_path):
    sahte = SahteControlM(kimliksiz=True).baslat()
    try:
        o, y = kur(ortam_yap)
        assert asistan(y)["durum"]["model_durumu"] == "VERI_TOPLANIYOR"
        kod, r = y.put("/api/asistan/ayarlar", {"boyut": 30})
        assert kod == 400 and "tam bölünmeli" in r["hata"]
        kod, r = y.put("/api/asistan/ayarlar", {"asgari_olay": 50, "asgari_gun": 0, "baglam": 16, "egitim_adimi": 60,
                                                "egitim_sure_sn": 40, "surekli": False})
        assert kod == 200 and r["baglam"] == 16 and r["surekli"] is False
        kod, h = y.post("/api/hedefler", {"ad": "ctm", "adres": sahte.adres, "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})
        assert kod == 200, h
        d = tmp_path / "gelen"
        d.mkdir()
        kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
        kod, k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "f", "regex": r"F_\d+\.csv", "hedef_id": h["id"],
                                          "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/F_GELDI/ODAT", "govde": ""}})
        assert kod == 200, k
        for i in range(45):
            (d / f"F_{i}.csv").write_text("x", encoding="utf-8")
            time.sleep(0.05)
        o.bekle(lambda: asistan(y)["veri"]["olay_sayisi"] >= 90, zaman_asimi=60, mesaj="olaylar toplanmadı")
        v = asistan(y)
        assert {t["ad"] for t in v["veri"]["turler"]} >= {"Dosya geldi", "İletildi"}
        o.bekle(lambda: asistan(y)["durum"]["model_durumu"] == "HAZIR", zaman_asimi=20)             # veri yeterli, model yok
        assert asistan(y)["egitim"] is None                                                           # sürekli öğrenme kapalı
        assert y.post("/api/asistan/egit")[0] == 200
        o.bekle(lambda: (e := asistan(y)["egitim"]) and e["surumler"], zaman_asimi=240, mesaj="eğitim turu bitmedi")
        v = asistan(y)
        e = v["egitim"]
        assert v["durum"]["model_durumu"] in ("OGRENIYOR", "DURAGAN", "EZBERLIYOR", "ANLAMSIZ")
        assert len(e["adimlar"]) == len(e["egitim_kaybi"]) == len(e["dogrulama_kaybi"]) >= 2 and e["taban_markov"] > 0
        assert e["surumler"][0]["surum"] == 1 and e["karar"]["baslik"]
        assert v["guven_var"] and 0 <= v["guven"]["karne"]["puan"] <= 1 and len(v["guven"]["guvenilirlik"]) == 10
        assert v["durum"]["torch"] is True and v["durum"]["parametre"] > 1000
        assert (o.veri / "asistan" / "model_1.npz").exists()
        assert o.db.tek("SELECT durum FROM komut WHERE alici='asistan' AND komut='EGIT'")[0] == "ISLENDI"
        # geri bildirim
        adb = AsistanDB(o.veri / "asistan.db")
        oneriler.oneri_ekle(adb, anahtar="deneme", tur="ILISKI", baslik="Deneme önerisi", metin="m", kaynak="model", guven=0.7)
        oid = adb.tek("SELECT id FROM oneri WHERE anahtar='deneme'")[0]
        o2 = Istemci(y.port)
        assert o2.giris("operator")[0] == 200
        assert o2.post("/api/asistan/egit")[0] == 403                                             # eğitim: yönetici
        kod, r = o2.post(f"/api/asistan/oneriler/{oid}/geri_bildirim", {"faydali": True})
        assert kod == 200 and r["durum"] == "FAYDALI"
        assert o2.post(f"/api/asistan/oneriler/{oid}/geri_bildirim", {"faydali": False})[0] == 404
        assert asistan(y)["guven"]["geri_bildirim"]["toplam"] == 1
        # kendini sına (ayrı model; gerçek modele dokunmaz)
        bas = time.time()
        assert o2.post("/api/asistan/kendini_sina")[0] == 200
        ks = o.bekle(lambda: (k_ := asistan(y)["kendini_sina"]) and k_.get("son") and k_["son"]["zaman"] >= bas and not k_["suruyor"] and k_,
                     zaman_asimi=300, mesaj="kendini sına bitmedi")
        assert ks["son"]["sonuc"] == "GECTI", ks["son"]["maddeler"]
        assert asistan(y)["egitim"]["surumler"][0]["surum"] == 1                                  # gerçek model değişmedi
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem LIKE 'ASISTAN_%'")[0] >= 4
        assert o.proc.poll() is None
    finally:
        sahte.durdur()


def test_pytorch_yoksa_veri_toplanir_egitim_yapilmaz(ortam_yap, monkeypatch):
    monkeypatch.setenv("FWP_ASISTAN_TORCHSUZ", "1")                           # çekirdek süreçleri bu ortamı devralır
    o, y = kur(ortam_yap, [{"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"},
                           {"ad": "asistan", "modul": "eklentiler.asistan.asistan"}])
    o.db.alarm_ac("kaynak:disk", "deneme", "KRITIK", "izleme")
    o.bekle(lambda: asistan(y)["veri"]["olay_sayisi"] >= 1 and asistan(y)["durum"].get("torch") is False, zaman_asimi=30)
    v = asistan(y)
    assert "PyTorch" in v["durum"]["hata"] and v["durum"]["model_durumu"] == "VERI_TOPLANIYOR"
    y.post("/api/asistan/egit")
    o.bekle(lambda: (r := o.db.tek("SELECT durum, sonuc FROM komut WHERE alici='asistan'")) and r["durum"] == "HATA" and "PyTorch" in r["sonuc"],
            zaman_asimi=30)
    assert o.eklenti("asistan")["durum"] == "CALISIYOR"



class _Zararli:
    """Yüklenince (pickle) bir işaret dosyası oluşturur: kod çalıştırmanın zararsız kanıtı."""

    def __init__(self, isaret):
        self.isaret = str(isaret)

    def __reduce__(self):
        return (open, (self.isaret, "w"))


def test_model_dosyasi_pickle_calistirmaz(tmp_path):
    """Güvenlik (2026-10-01): model dosyası pickle değildir. Değiştirilmiş / zararlı bir dosya yüklenmeye çalışılınca
    hiçbir kod çalışmamalı, anlaşılır hata vermeli. Doğru kaydedilen model aynı tahminleri vermeli."""
    import pickle
    torch.manual_seed(0)
    m = M.OlayModeli(baglam=16, katman=1, bas=2, boyut=16)
    m.sicaklik = 1.37
    yol = tmp_path / "model_1.npz"
    M.kaydet(m, yol)
    m2 = M.yukle(yol)
    girdi = [torch.zeros((1, 8), dtype=torch.long)] * 4
    assert torch.allclose(m.eval()(*girdi)[0], m2(*girdi)[0]) and m2.sicaklik == 1.37
    isaret = tmp_path / "KOD_CALISTI"
    for ad, yaz in (("torch.save", lambda p: torch.save({"durum": _Zararli(isaret)}, str(p))),
                    ("pickle", lambda p: p.write_bytes(pickle.dumps(_Zararli(isaret))))):
        kotu = tmp_path / f"kotu_{ad}.npz"
        yaz(kotu)
        with pytest.raises(M.ModelDosyasiHatasi):
            M.yukle(kotu)
        assert not isaret.exists(), f"{ad}: yükleme sırasında kod çalıştı"
    # sınır dışı yapı (ör. bellek tüketmek için dev boyut) reddedilir
    import json as _json
    np.savez(tmp_path / "dev.npz", __ust__=np.frombuffer(_json.dumps({"yapi": {"baglam": 16, "katman": 1, "bas": 2, "boyut": 10 ** 6}}).encode(),
                                                          dtype=np.uint8))
    with pytest.raises(M.ModelDosyasiHatasi, match="geçersiz yapı"):
        M.yukle(tmp_path / "dev.npz")
