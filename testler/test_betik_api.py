"""Kontrol API'si: betik hedefi (süper yönetici kilidi, maskeleme, deneme, düzenleme) ve Genel API (Basic, düzenleme).

Gerçek HTTP ile; çekirdek + tarama + teslim + kontrol süreçleri, sahte Control-M (webhook başlıklarını kaydeder).
"""
import base64
import json

from cekirdek import betik_sifresi
from testler.conftest import duz_sir_yok
from testler.test_adim8_kontrol_api import AYAR, EKLENTILER, Istemci, api, sahte  # noqa: F401 (fikstürler)

SUPER = "ornek-super-sifre-C"
SIR = "betik-api-gizli-5521"
BETIK = ("import json, os, sys\n"
         "v = json.load(sys.stdin)\n"
         "print('dosya', v['dosya_adi'], 'olay', os.environ.get('FWP_P_OLAY'), 'sir', os.environ['FWP_SIR_API'])\n")


def _sil(y, yol):
    return y.istek("DELETE", yol)


def test_betik_kilidi_hedef_kural_deneme_ve_maskeleme(api, tmp_path):
    o, port = api
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200
    kod, dur = y.get("/api/betik/durum")
    assert kod == 200 and not dur["sifre_tanimli"] and not dur["kilit_acik"]
    assert "Python" in dur["diller"]["python"]["surum"] and "PowerShell" in dur["diller"]["powershell"]["surum"]
    assert y.post("/api/betik/kilit", {"sifre": SUPER})[0] == 400                   # şifre belirlenmemiş: özellik kapalı
    betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), SUPER, belirleyen="test")

    tanim = {"ad": "aktarim", "tur": "BETIK", "adres": "",
             "ayrintilar": {"dil": "python", "kod": BETIK, "zaman_asimi_sn": 10, "eszamanli": 2,
                            "sirlar": [{"ad": "API", "deger": SIR}]}}
    kod, h = y.post("/api/hedefler", tanim)
    assert kod == 403 and "kilidi kapalı" in h["hata"]                              # kilit kapalıyken eklenemez
    kod, h = y.post("/api/betik/kilit", {"sifre": "yanlis-sifre-123"})
    assert kod == 403 and "Kalan deneme: 4" in h["hata"]
    kod, dur = y.post("/api/betik/kilit", {"sifre": SUPER})
    assert kod == 200 and dur["kilit_acik"] and 590 <= dur["kalan_sn"] <= 600

    op = Istemci(port)
    assert op.giris("operator")[0] == 200
    assert op.post("/api/betik/kilit", {"sifre": SUPER})[0] == 200                  # operatör de açar (lokal işlemler)
    assert op.post("/api/hedefler", tanim)[0] == 403                                # ama betik eklemek yönetici işi
    assert op.get("/api/hedefler/1")[0] == 403

    kod, h = y.post("/api/hedefler", tanim)
    assert kod == 200, h
    hid = h["id"]
    for liste in (y.get("/api/hedefler")[1], y.get("/api/durum?taze=1")[1]["hedefler"]):
        a = next(x for x in liste if x["id"] == hid)["ayrintilar"]
        assert "kod" not in a and a["kod_satir"] == 3                               # metin her saniye gönderilmez
        assert a["sirlar"] == [{"ad": "API", "kayitli": True, "kaynak": "uygulamada şifreli (bu sunucu)"}]
    kod, tek = y.get(f"/api/hedefler/{hid}")
    assert kod == 200 and tek["ayrintilar"]["kod"] == BETIK and tek["timeout_sn"] == 10 and tek["esz_cagri_ust"] == 2
    assert "ref" not in json.dumps(tek["ayrintilar"]["sirlar"]) and SIR not in json.dumps(tek)

    kod, r = y.post("/api/betik/denetle", {"dil": "python", "kod": "print((1,\n"})
    assert kod == 200 and not r["gecerli"] and r["satir"] == 1
    deneme = {"hedef_id": hid, "dil": "python", "kod": BETIK, "zaman_asimi_sn": 10, "sirlar": [{"ad": "API"}],
              "ornek": {"dosya_adi": "F_1.csv", "ek": {"P_OLAY": "DENEME", "G_TARIH": "20261001"}}}
    kod, r = y.post("/api/betik/dene", deneme)
    assert kod == 200 and "sonuc" not in r                                          # kuru: çalıştırmadı
    assert r["ortam"]["FWP_SIR_API"] == "*** (gizli)" and r["ortam"]["FWP_G_TARIH"] == "20261001" and r["stdin"]["deneme"]
    kod, r = y.post("/api/betik/dene", {**deneme, "calistir": True})
    assert kod == 200 and r["sonuc"] == "BASARI", r
    assert "dosya F_1.csv olay DENEME sir ***" in r["stdout"] and SIR not in json.dumps(r)   # kayıtlı gizli değer kullanıldı

    # düzenleme: gizli değer boş bırakılır → eskisi korunur; sürüm değişir
    yeni = BETIK + "print('v2')\n"
    kod, _ = y.put(f"/api/hedefler/{hid}", {**tanim, "ayrintilar": {**tanim["ayrintilar"], "kod": yeni, "sirlar": [{"ad": "API"}]}})
    assert kod == 200
    tek2 = y.get(f"/api/hedefler/{hid}")[1]
    assert tek2["ayrintilar"]["kod"] == yeni and tek2["ayrintilar"]["surum"] != tek["ayrintilar"]["surum"]
    assert y.put(f"/api/hedefler/{hid}", {**tanim, "tur": "HTTP"})[1]["hata"].startswith("hedef türü değiştirilemez")

    # kural: betik hedefine bağlamak kilit ister
    d = tmp_path / "gelen"
    d.mkdir()
    kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
    kural = {"dizin_id": dz["id"], "ad": "fatura", "regex": r"F_(?P<no>\d+)\.csv", "hedef_id": hid,
             "istek": {"parametreler": {"OLAY": "GELDI_{no}"}}}
    assert _sil(y, "/api/betik/kilit")[1]["kilit_acik"] is False
    kod, r = y.post("/api/kurallar", kural)
    assert kod == 403 and "kilidi" in r["hata"]
    y.post("/api/betik/kilit", {"sifre": SUPER})
    kod, r = y.post("/api/kurallar", {**kural, "istek": {"parametreler": {"kucuk": "x"}}})
    assert kod == 400 and "büyük harf" in r["hata"]
    kod, k = y.post("/api/kurallar", kural)
    assert kod == 200, k

    # kural penceresi denemesi: operatör kuru deneme görür, gerçek çalıştırma yönetici + kilit
    dene = {**kural, "ornek_ad": "F_42.csv"}
    kod, r = op.post("/api/kurallar/dene", dene)
    assert kod == 200 and r["tur"] == "BETIK" and r["ortam"]["FWP_P_OLAY"] == "GELDI_42" and r["ortam"]["FWP_DENEME"] == "0"
    assert op.post("/api/kurallar/dene", {**dene, "gonder": True})[0] == 403
    kod, r = y.post("/api/kurallar/dene", {**dene, "gonder": True})
    assert kod == 200 and r["sonuc"] == "BASARI" and "olay GELDI_42 sir ***" in r["stdout"]

    # gerçek dosya: teslim betiği çalıştırır
    (d / "F_7.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := o.db.tek("SELECT durum FROM tetik WHERE dosya_adi='F_7.csv'")) and t[0] == "ILETILDI")

    islemler = {r[0] for r in o.hdb.oku("SELECT islem FROM denetim")}
    assert {"BETIK_EKLE", "BETIK_DEGISTI", "BETIK_KILIDI_ACILDI", "BETIK_KILIDI_HATALI", "BETIK_KILITLENDI",
            "BETIK_CANLI_TEST"} <= islemler
    kayit = json.loads(o.hdb.tek("SELECT yeni FROM denetim WHERE islem='BETIK_DEGISTI'")[0])
    assert kayit["kod"] == yeni and kayit["sirlar"] == ["API"]                       # çalışan neydi: betik denetimde

    for i in range(5):                          # başarılı açılış sayacı sıfırlar; 5. hatalı deneme → 15 dk bekleme
        kod, r = y.post("/api/betik/kilit", {"sifre": "yanlis-sifre-123"})
        assert kod == 403 and (i < 4 or "15 dakika" in r["hata"])
    kod, r = y.post("/api/betik/kilit", {"sifre": SUPER})                          # doğru şifre de beklemede reddedilir
    assert kod == 429 and "dk sonra" in r["hata"]
    o.cekirdek_kapat()
    duz_sir_yok(o, SIR)
    duz_sir_yok(o, SUPER)


def test_genel_api_basic_apikey_duzenleme_ve_gizli_baslik_reddi(api, sahte, tmp_path):
    o, port = api
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200
    taban = f"http://127.0.0.1:{sahte.port}"
    tanim = {"ad": "rapor", "tur": "HTTP", "adres": taban,
             "ayrintilar": {"kimlik_turu": "basic", "kullanici": "fwp", "sifre": "ornek-basic-sifresi",
                            "basliklar": {"X-Kaynak": "FileWatcherPro"}, "tls_dogrula": True, "saglik_yolu": "/webhook"}}
    kod, r = y.post("/api/hedefler", {**tanim, "ayrintilar": {**tanim["ayrintilar"], "basliklar": {"Authorization": "x"}}})
    assert kod == 400 and "sabit başlıkta olamaz" in r["hata"]
    kod, r = y.post("/api/hedefler", {**tanim, "ayrintilar": {**tanim["ayrintilar"], "sifre": ""}})
    assert kod == 400 and "Basic kimlik için şifre" in r["hata"]
    kod, h = y.post("/api/hedefler", tanim)
    assert kod == 200, h
    hid = h["id"]
    kod, s = y.post(f"/api/hedefler/{hid}/dene")
    assert kod == 200 and s["basarili"], s
    d = tmp_path / "gelen"
    d.mkdir()
    dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
    assert y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "r", "regex": r"R_\d+\.csv", "hedef_id": hid,
                                    "istek": {"yontem": "POST", "yol": "/webhook", "govde": '{"dosya": "{dosya_adi}"}'}})[0] == 200
    (d / "R_1.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: len(sahte.webhook) == 1)
    w = sahte.webhook[0]
    assert w["govde"] == {"dosya": "R_1.csv"} and w["basliklar"]["x-kaynak"] == "FileWatcherPro"
    assert w["basliklar"]["authorization"] == "Basic " + base64.b64encode(b"fwp:ornek-basic-sifresi").decode()

    # düzenleme: API anahtarı (özel başlık) — başlık adı önyüzde görünür, anahtar görünmez
    kod, r = y.put(f"/api/hedefler/{hid}", {"ad": "rapor", "adres": taban, "tur": "HTTP", "ayrintilar": {
        "kimlik_turu": "apikey", "anahtar_basligi": "X-API-Key", "anahtar_on_eki": "", "anahtar": "anahtar-999",
        "basliklar": {}}})
    assert kod == 200, r
    a = next(x for x in y.get("/api/hedefler")[1] if x["id"] == hid)["ayrintilar"]
    assert a["anahtar_basligi"] == "X-API-Key" and a["anahtar_kayitli"] and "anahtar-999" not in json.dumps(a)
    (d / "R_2.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: len(sahte.webhook) == 2)
    assert sahte.webhook[1]["basliklar"]["x-api-key"] == "anahtar-999"
    # anahtar boş bırakılarak yeniden kaydedilir → eskisi korunur
    assert y.put(f"/api/hedefler/{hid}", {"ad": "rapor2", "adres": taban, "tur": "HTTP", "ayrintilar": {
        "kimlik_turu": "apikey", "anahtar_basligi": "X-API-Key", "anahtar_on_eki": "", "basliklar": {}}})[0] == 200
    (d / "R_3.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: len(sahte.webhook) == 3)
    assert sahte.webhook[2]["basliklar"]["x-api-key"] == "anahtar-999"
    kod, r = y.post("/api/kurallar/dene", {"dizin_id": dz["id"], "ad": "r", "regex": r"R_\d+\.csv", "hedef_id": hid,
                                           "ornek_ad": "R_9.csv", "istek": {"yontem": "POST", "yol": "/webhook", "govde": ""}})
    assert kod == 200 and r["basliklar"]["X-API-Key"] == "••••••"
    assert {"HEDEF_EKLE", "HEDEF_GUNCELLE"} <= {r[0] for r in o.hdb.oku("SELECT islem FROM denetim")}
    o.cekirdek_kapat()
    for s_ in ("ornek-basic-sifresi", "anahtar-999"):
        duz_sir_yok(o, s_)



def test_hedef_silme_kayip_olmasin_diye_korumali(api, sahte, tmp_path):
    """Hedef silinir; ama bağlı kural ya da gönderilmeyi bekleyen (lokal dahil) tetik varsa silinmez. Betik hedefi
    silmek süper yönetici kilidi ister; silinen betiğin çalışma klasörü temizlenir; işlem denetime yazılır."""
    o, port = api
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200
    kapali = y.post("/api/hedefler", {"ad": "erisilemez", "adres": "http://127.0.0.1:9/automation-api", "tur": "CONTROLM",
                                      "ayrintilar": {"kimlik_turu": "yok"}})[1]["id"]
    d = tmp_path / "gelen"
    d.mkdir()
    dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
    k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "s", "regex": r"S_\d+\.csv", "hedef_id": kapali,
                                 "istek": {"yontem": "POST", "yol": "/run/event/x/S/ODAT", "govde": ""}})[1]["id"]
    kod, r = y.istek("DELETE", f"/api/hedefler/{kapali}")
    assert kod == 400 and "bağlı 1 kural" in r["hata"]
    (d / "S_1.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := o.db.tek("SELECT durum FROM tetik WHERE dosya_adi='S_1.csv'")) and t[0] == "LOKALDE", zaman_asimi=30)
    assert y.istek("DELETE", f"/api/kurallar/{k}")[0] == 200
    kod, r = y.istek("DELETE", f"/api/hedefler/{kapali}")
    assert kod == 400 and "bekleyen 1 tetik" in r["hata"]                         # lokaldeki tetik kaybolmasın

    betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), SUPER, belirleyen="test")
    y.post("/api/betik/kilit", {"sifre": SUPER})
    bid = y.post("/api/hedefler", {"ad": "b", "tur": "BETIK", "adres": "", "ayrintilar": {
        "dil": "python", "kod": "print(1)", "zaman_asimi_sn": 5, "eszamanli": 1, "sirlar": []}})[1]["id"]
    y.post("/api/betik/dene", {"hedef_id": bid, "dil": "python", "kod": "print(1)", "sirlar": [],
                               "ornek": {"dosya_adi": "a.csv"}, "calistir": True})
    y.istek("DELETE", "/api/betik/kilit")
    kod, r = y.istek("DELETE", f"/api/hedefler/{bid}")
    assert kod == 403 and "kilidi" in r["hata"]
    y.post("/api/betik/kilit", {"sifre": SUPER})
    assert y.istek("DELETE", f"/api/hedefler/{bid}")[0] == 200
    assert not (o.veri / "betik" / str(bid)).exists()
    assert o.db.tek("SELECT COUNT(*) FROM hedef WHERE id=?", (bid,))[0] == 0
    assert {"BETIK_SIL"} <= {r[0] for r in o.hdb.oku("SELECT islem FROM denetim")}
