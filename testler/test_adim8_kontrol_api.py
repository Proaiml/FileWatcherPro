"""Adım 8 testleri: kontrol API'si (gerçek çekirdek + tarama + teslim + kontrol süreçleri, sahte Control-M).

Önyüzün kullanacağı her uç nokta burada gerçek HTTP ile denenir; önyüz (Adım 9) yalnızca bu uç noktaları çağırır.
"""
import http.client
import json
import os
import time
from pathlib import Path

import pytest

from cekirdek import win
from cekirdek.kullanicilar import Kullanicilar
from testler.conftest import HIZLI_TARAMA, duz_sir_yok
from testler.sahte_controlm import SahteControlM

os.environ["FWP_CTM_SIFRE"] = "gizli"
EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
              {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"},
              {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"}]
AYAR = {**HIZLI_TARAMA, "sabitlik_W_sn": 0.3, "deneme_plani": "0.5,1,1.5", "cagri_timeout_sn": 1,
        "otomatik_devre_esigi": 0, "erit_hizi": 20}
SIFRE = "ornek-arayuz-sifresi-B"


class Istemci:
    def __init__(self, port):
        self.port, self.cerez = port, None

    def istek(self, yontem, yol, govde=None, guvenlik=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        b = {"Content-Type": "application/json"}
        if guvenlik:
            b["X-FWP"] = "1"
        if self.cerez:
            b["Cookie"] = self.cerez
        c.request(yontem, yol, body=None if govde is None else json.dumps(govde), headers=b)
        r = c.getresponse()
        veri = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cerez = sc.split(";")[0]
        self.son_basliklar = dict(r.getheaders())
        c.close()
        try:
            return r.status, json.loads(veri or b"null")
        except ValueError:
            return r.status, veri.decode("utf-8", "replace")

    def giris(self, ad, sifre=SIFRE):
        return self.istek("POST", "/api/giris", {"kullanici": ad, "sifre": sifre})

    get = lambda s, y: s.istek("GET", y)                                # noqa: E731
    post = lambda s, y, g=None: s.istek("POST", y, g or {})             # noqa: E731
    put = lambda s, y, g=None: s.istek("PUT", y, g or {})               # noqa: E731


@pytest.fixture
def sahte():
    s = SahteControlM().baslat()
    yield s
    s.durdur()


@pytest.fixture
def api(ortam_yap, sahte):
    o = ortam_yap(eklentiler=EKLENTILER, ayarlar=AYAR)
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    k.ekle("yonetici", SIFRE, "YONETICI")
    k.ekle("operator", SIFRE, "OPERATOR")
    k.ekle("izleyici", SIFRE, "IZLEYICI")
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                and json.loads(e["bilgi"] or "{}").get("port") and e)
    port = json.loads(s["bilgi"])["port"]
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "teslim")))
    return o, port


def kur_api(o, port, sahte, tmp_path):
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200
    kod, h = y.post("/api/hedefler", {"ad": "controlm", "adres": sahte.adres, "tur": "CONTROLM",
                                      "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwp",
                                                     "sifre_ref": "env:FWP_CTM_SIFRE"}})
    assert kod == 200, h
    d = tmp_path / "gelen"
    d.mkdir()
    kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
    assert kod == 200, dz
    kod, k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "fatura", "regex": r"F_(?P<no>\d+)\.csv",
                                      "hedef_id": h["id"], "is_bilgisi": {"folder": "KL", "jobs": "IS"}})
    assert kod == 200, k
    return y, d, h["id"], dz["id"], k["id"]


def tetik(o, ad):
    return o.db.tek("SELECT * FROM tetik WHERE dosya_adi=?", (ad,))


# ================================================================ giriş ve güvenlik
def test_giris_kilit_ve_guvenlik_basliklari(api):
    o, port = api
    c = Istemci(port)
    assert c.get("/api/durum")[0] == 401                                          # girişsiz
    assert c.giris("yonetici", "yanlis")[0] == 401
    for _ in range(4):
        c.giris("yonetici", "yanlis")
    kod, cevap = c.giris("yonetici")                                              # doğru şifre bile kilitli
    assert kod == 429 and "hatalı deneme" in cevap["hata"]
    c2 = Istemci(port)
    kod, cevap = c2.giris("operator")
    assert kod == 200 and cevap["rol"] == "OPERATOR"
    assert "HttpOnly" in c2.son_basliklar["Set-Cookie"] and "SameSite=Strict" in c2.son_basliklar["Set-Cookie"]
    assert c2.get("/api/ben")[1] == {"kullanici": "operator", "rol": "OPERATOR", "varsayilan_sifre": False}
    assert c2.istek("POST", "/api/motor", {"aktif": True}, guvenlik=False)[0] == 403   # X-FWP başlığı yok
    kod, sayfa = c2.get("/")
    assert kod == 200 and "default-src 'self'" in c2.son_basliklar["Content-Security-Policy"]
    assert c2.get("/..%2F..%2Fconfig%2Fkullanicilar.json")[0] in (200, 404)
    assert "pbkdf2" not in str(c2.get("/../config/kullanicilar.json")[1])
    denetim = [r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE kullanici='yonetici'")]
    assert denetim.count("GIRIS_BASARISIZ") >= 5


def test_ilk_kurulum_admin_ve_sifre_degistirme(ortam_yap):
    """Kullanıcı dosyası yoksa admin/admin oluşur; değiştirilene kadar uyarı alarmı açık, değişince kapanır."""
    o = ortam_yap(eklentiler=[EKLENTILER[2]], ayarlar=AYAR)
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                and json.loads(e["bilgi"] or "{}").get("port") and e)
    port = json.loads(s["bilgi"])["port"]
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    assert [u["ad"] for u in k.liste()] == ["admin"]
    assert json.loads((o.baslangic.parent / "kullanicilar.json").read_text(encoding="utf-8"))["admin"]["sifre"].startswith("pbkdf2_sha256$")
    c = Istemci(port)
    kod, cevap = c.giris("admin", "admin")
    assert kod == 200 and cevap == {"kullanici": "admin", "rol": "YONETICI", "varsayilan_sifre": True}
    assert c.get("/api/ben")[1]["varsayilan_sifre"] is True
    o.bekle(lambda: o.db.tek("SELECT 1 FROM alarm WHERE anahtar='kontrol:varsayilan_sifre' AND aktif=1"))
    kod, h = c.post("/api/sifre", {"eski": "yanlis", "yeni": "yeni-sifre-12345"})
    assert kod == 400 and "hatalı" in h["hata"]
    assert c.post("/api/sifre", {"eski": "admin", "yeni": "kisa"})[0] == 400
    assert c.post("/api/sifre", {"eski": "admin", "yeni": "ADMIN"})[0] == 400
    assert c.post("/api/sifre", {"eski": "admin", "yeni": "yeni-sifre-12345"})[0] == 200
    assert c.get("/api/ben")[1]["varsayilan_sifre"] is False                     # oturum açık kalır
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar='kontrol:varsayilan_sifre' AND aktif=1") is None
    assert Istemci(port).giris("admin", "admin")[0] == 401
    assert Istemci(port).giris("admin", "yeni-sifre-12345")[0] == 200
    islemler = [r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE nesne='admin'")]
    assert "KULLANICI_VARSAYILAN" in islemler and "SIFRE_DEGISTIR" in islemler and "SIFRE_DEGISTIR_BASARISIZ" in islemler


def test_rol_yetkileri(api, sahte, tmp_path):
    """U10: izleyici değiştiremez; operatör eylem yapar ama yapılandırma değiştiremez; yönetici her şeyi."""
    o, port = api
    y, d, hedef_id, dizin_id, _ = kur_api(o, port, sahte, tmp_path)
    iz, op = Istemci(port), Istemci(port)
    iz.giris("izleyici")
    op.giris("operator")
    assert iz.get("/api/durum")[0] == 200
    kod, c = iz.post(f"/api/hedefler/{hedef_id}/kapat", {"mod": "KAYITLI"})
    assert kod == 403 and "OPERATOR" in c["hata"]
    assert op.post(f"/api/hedefler/{hedef_id}/kapat", {"mod": "KAYITLI"})[0] == 200
    assert op.post("/api/dizinler", {"yol": "C:\\x", "ilk_kurulum_modu": "TETIKLE"})[0] == 403
    assert op.put("/api/ayarlar", {"hash_esik_mb": 10})[0] == 403
    assert op.post(f"/api/hedefler/{hedef_id}/ac")[0] == 200
    kullanicilar = [r["kullanici"] for r in o.hdb.oku("SELECT kullanici FROM denetim WHERE islem IN ('HEDEF_KAPAT','HEDEF_AC')")]
    assert kullanicilar == ["operator", "operator"]


# ================================================================ yapılandırma ve uçtan uca teslim
def test_api_ile_yapilandirma_regex_dogrulama_ve_teslim(api, sahte, tmp_path):
    o, port = api
    y, d, hedef_id, dizin_id, _ = kur_api(o, port, sahte, tmp_path)
    kod, c = y.post("/api/kurallar", {"dizin_id": dizin_id, "regex": "^(a+)+$", "hedef_id": hedef_id})
    assert kod == 400 and "çok yavaş" in c["hata"]
    kod, c = y.post("/api/kurallar", {"dizin_id": dizin_id, "regex": "F_(\\d+", "hedef_id": hedef_id})
    assert kod == 400 and "geçersiz" in c["hata"]
    kod, c = y.post("/api/dizinler", {"yol": str(tmp_path / "x"), "ilk_kurulum_modu": ""})
    assert kod == 400 and "açıkça seçilmeli" in c["hata"]
    kod, c = y.post("/api/regex/dene", {"regex": r"F_(?P<no>\d+)\.csv", "adlar": ["f_12.CSV", "g_1.csv"]})
    assert kod == 200 and c[0]["eslesti"] and c[0]["gruplar"] == {"no": "12"} and not c[1]["eslesti"]
    (d / "F_1.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "F_1.csv")) and t["durum"] == "ILETILDI")
    o.bekle(lambda: y.get("/api/durum")[1]["sayilar"].get("iletildi", 0) >= 1)
    durum = y.get("/api/durum")[1]
    assert durum["hedefler"][0]["ad"] == "controlm" and durum["dizinler"][0]["kural_sayisi"] == 1
    assert durum["sla"]["n"] == 1 and durum["motor"] is True
    assert {e["ad"] for e in durum["eklentiler"]} >= {"cekirdek", "tarama", "teslim", "kontrol"}
    assert y.get("/api/dosyalar")[1][0]["tetik_durum"] == "ILETILDI"
    hj = json.dumps(y.get("/api/hedefler")[1], ensure_ascii=False)
    assert "gizli" not in hj and '"env:FWP_CTM_SIFRE"' in hj and "ortam değişkeni FWP_CTM_SIFRE" in hj   # referans, şifre değil


def test_api_toptan_kapat_lokal_erit(api, sahte, tmp_path):
    """HEDEF KOŞULU önyüz yolundan: toptan kapat (kayıtlı) → lokal → toptan aç → erit → hepsi tam bir kez."""
    o, port = api
    y, d, hedef_id, *_ = kur_api(o, port, sahte, tmp_path)
    op = Istemci(port)
    op.giris("operator")
    assert op.post("/api/toptan_kapat", {"mod": "KAYITLI"})[1]["kapatilan"] == [hedef_id]
    adlar = [f"F_{i}.csv" for i in range(1, 7)]
    for a in adlar:
        (d / a).write_text(a, encoding="utf-8")
    o.bekle(lambda: all((t := tetik(o, a)) and t["durum"] == "LOKALDE" for a in adlar), zaman_asimi=20)
    o.bekle(lambda: op.get("/api/durum")[1]["hedefler"][0]["lokalde"] == 6)
    assert sahte.siparisler == []
    assert len(op.get("/api/tetikler?durum=LOKALDE")[1]) == 6
    assert len(op.get("/api/gonderilemeyen?cozuldu=0")[1]) == 6
    assert op.post("/api/toptan_ac")[1]["acilan"] == [hedef_id]
    assert op.post(f"/api/hedefler/{hedef_id}/erit", {"islem": "baslat", "hiz": 10})[0] == 200
    o.bekle(lambda: all(tetik(o, a)["durum"] == "ILETILDI" for a in adlar), zaman_asimi=20)
    say = sahte.idempotency_sayilari()
    assert all(say[tetik(o, a)["idempotency"]] == 1 for a in adlar)
    o.bekle(lambda: op.get("/api/durum")[1]["hedefler"][0]["erit_durumu"] == "YOK")
    islemler = [r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE kullanici='operator' ORDER BY id")]
    assert islemler[-4:] == ["HEDEF_KAPAT", "TOPTAN_KAPAT", "HEDEF_AC", "ERIT_BASLAT"]


def test_api_motor_durdur_baslat(api, sahte, tmp_path):
    o, port = api
    y, d, *_ = kur_api(o, port, sahte, tmp_path)
    assert y.post("/api/motor", {"aktif": False})[1] == {"motor": False}
    time.sleep(1)
    (d / "F_9.csv").write_text("x", encoding="utf-8")
    time.sleep(2.5)
    assert tetik(o, "F_9.csv") is None and y.get("/api/durum")[1]["motor"] is False
    y.post("/api/motor", {"aktif": True})
    o.bekle(lambda: (t := tetik(o, "F_9.csv")) and t["durum"] == "ILETILDI")


def test_api_eklenti_komutlari_ve_cekirdek_ayakta(api):
    """HEDEF KOŞULU: bir eklenti öldürüldüğünde çekirdek ayakta kalır ve önyüzden yeniden başlatılabilir.
    Art arda öldürülen eklenti ELLE_MUDAHALE olur; önyüzdeki 'Başlat' ile geri gelir. Kontrol durdurulamaz."""
    o, port = api
    o.ayar(eklenti_dusme_limiti=2, eklenti_bekleme_plani="0.3")
    op = Istemci(port)
    op.giris("operator")
    kod, c = op.post("/api/eklentiler/kontrol/durdur")
    assert kod == 400 and "durdurulamaz" in c["hata"]
    for _ in range(2):
        pid = o.bekle(lambda: (e := o.eklenti("tarama")) and e["durum"] == "CALISIYOR" and e["pid"])
        os.kill(pid, 9)
        o.bekle(lambda: o.eklenti("tarama")["pid"] != pid)
    o.bekle(lambda: o.eklenti("tarama")["durum"] == "ELLE_MUDAHALE", zaman_asimi=15)
    assert o.proc.poll() is None and win.surec_canli(o.eklenti("cekirdek")["pid"])
    o.bekle(lambda: any(a["anahtar"] == "eklenti:tarama:elle" and a["seviye"] == "KRITIK"
                        for a in op.get("/api/durum")[1]["alarmlar"]), zaman_asimi=5,
            mesaj="KRİTİK alarm önyüz özetine yansımadı")
    kod, c = op.post("/api/eklentiler/tarama/baslat")
    assert kod == 200
    o.bekle(lambda: op.get(f"/api/komut/{c['komut_id']}")[1]["durum"] == "ISLENDI")
    o.bekle(lambda: o.eklenti("tarama")["durum"] == "CALISIYOR")
    pid = o.eklenti("teslim")["pid"]
    assert op.post("/api/eklentiler/teslim/yeniden_baslat")[0] == 200
    o.bekle(lambda: (e := o.eklenti("teslim")) and e["durum"] == "CALISIYOR" and e["pid"] != pid)
    assert op.post("/api/eklentiler/teslim/durdur")[0] == 200
    o.bekle(lambda: o.eklenti("teslim")["durum"] == "DURDURULDU")
    assert op.post("/api/eklentiler/teslim/baslat")[0] == 200
    o.bekle(lambda: o.eklenti("teslim")["durum"] == "CALISIYOR")


def test_canli_akis_sse(api):
    o, port = api
    c = Istemci(port)
    c.giris("izleyici")
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    con.request("GET", "/api/akis", headers={"Cookie": c.cerez})
    r = con.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    satir = b""
    t0 = time.time()
    while not satir.startswith(b"data: ") and time.time() - t0 < 10:
        satir = r.fp.readline()
    veri = json.loads(satir[6:])
    assert "hedefler" in veri and "eklentiler" in veri and "sayilar" in veri
    con.close()


def test_alarm_onayla_ve_ayar_atomik(api):
    o, port = api
    y = Istemci(port)
    y.giris("yonetici")
    o.db.alarm_ac("test:alarm", "deneme alarmı", "UYARI", "test")
    aid = o.db.tek("SELECT id FROM alarm WHERE anahtar='test:alarm' AND aktif=1")["id"]
    assert y.post(f"/api/alarmlar/{aid}/onayla")[0] == 200
    assert o.db.tek("SELECT aktif, onaylayan FROM alarm WHERE id=?", (aid,))[:] == (0, "yonetici")
    assert y.put("/api/ayarlar", {"hash_esik_mb": 750})[1] == {"hash_esik_mb": 750.0}
    kod, c = y.put("/api/ayarlar", {"hash_esik_mb": 600, "sla_hedef_sn": 0})
    assert kod == 400
    ayarlar = {a["anahtar"]: a["deger"] for a in y.get("/api/ayarlar")[1]}
    assert ayarlar["hash_esik_mb"] == 750.0                       # yarım uygulanmadı
    assert y.post("/api/bakim")[0] == 200
    islemler = {r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE kullanici='yonetici'")}
    assert {"ALARM_ONAYLA", "AYAR_DEGISTIR"} <= islemler


def test_kural_istegi_api_kuru_deneme_gonderim_duzenleme(api, sahte, tmp_path):
    """Kural penceresinin arka ucu: dizindeki gerçek adlar, kuru deneme (göndermez, kimlik maskeli), bozuk şablonun
    reddi, gerçek gönderim yalnız YÖNETİCİ ve denetime yazılır (tetik oluşmaz), kural düzenleme yeni dosyalara uygulanır,
    hedef bağlantı denemesi (iş tetiklemez)."""
    o, port = api
    y, d, hedef_id, dizin_id, kural_id = kur_api(o, port, sahte, tmp_path)
    (d / "F_77.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "F_77.csv")) and t["durum"] == "ILETILDI")
    assert "F_77.csv" in y.get(f"/api/dizinler/{dizin_id}/ornek_adlar")[1]
    istek = {"yontem": "POST", "yol": "/run/event/{ctm}/F_{no}_GELDI/ODAT", "govde": '{"yol": "{tam_yol}", "no": "{no}"}'}
    deneme = {"dizin_id": dizin_id, "hedef_id": hedef_id, "regex": r"F_(?<no>\d+)\.csv", "harf_duyarsiz": True,
              "ad": "fatura", "istek": istek, "ornek_ad": "F_77.csv"}
    kod, r = y.post("/api/kurallar/dene", deneme)
    assert kod == 200, r
    assert r["url"] == f"{sahte.adres}/run/event/ctmsunucu/F_77_GELDI/ODAT"
    assert "••" in r["basliklar"]["Authorization"] and "gizli" not in json.dumps(r)
    assert json.loads(r["govde"]) == {"yol": str(d / "F_77.csv"), "no": "77"}
    assert not sahte.olaylar                                                    # kuru deneme göndermez
    assert "bilinmeyen değişken" in y.post("/api/kurallar/dene", {**deneme, "istek": {**istek, "govde": '{"a": "{yok}"}'}})[1]["hata"]
    assert "uymuyor" in y.post("/api/kurallar/dene", {**deneme, "ornek_ad": "G_1.csv"})[1]["hata"]
    op = Istemci(port)
    op.giris("operator")
    assert op.post("/api/kurallar/dene", deneme)[0] == 200                     # operatör kuru deneme yapabilir
    assert op.post("/api/kurallar/dene", {**deneme, "gonder": True})[0] == 403
    kod, r = y.post("/api/kurallar/dene", {**deneme, "gonder": True})
    assert kod == 200 and r["yanit"]["basarili"] and r["yanit"]["kod"] == 200
    assert [x["olay"] for x in sahte.olaylar] == ["F_77_GELDI"]
    assert o.db.tek("SELECT COUNT(*) FROM tetik")[0] == 1                       # deneme tetik tablosuna girmez
    assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='KURAL_ISTEK_GONDER' AND kullanici='yonetici'")[0] == 1
    kod, r = y.put(f"/api/kurallar/{kural_id}", {"ad": "fatura", "regex": r"F_(?<no>\d+)\.csv", "hedef_id": hedef_id,
                                                 "harf_duyarsiz": True, "sira": 100, "istek": istek})
    assert kod == 200, r
    k = y.get("/api/dizinler")[1][0]["kurallar"][0]
    assert k["istek"]["yol"] == istek["yol"] and "(?P<no>" in k["regex"]
    assert op.put(f"/api/kurallar/{kural_id}", {"ad": "x", "regex": "x", "hedef_id": hedef_id})[0] == 403
    (d / "F_78.csv").write_text("y", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "F_78.csv")) and t["durum"] == "ILETILDI")
    assert [x["olay"] for x in sahte.olaylar] == ["F_77_GELDI", "F_78_GELDI"]
    kod, r = y.post(f"/api/hedefler/{hedef_id}/dene")
    assert kod == 200 and r["basarili"] and "iş tetiklenmedi" in r["mesaj"]
    kod, r = y.post("/api/hedefler/dene", {"adres": sahte.adres, "tur": "CONTROLM",
                                           "ayrintilar": {"kimlik_turu": "token", "kullanici": "fwp", "sifre_ref": "env:YOK_BOYLE_BIR_SIR"}})
    assert kod == 200 and r["basarili"] is False
    kod, r = y.post("/api/hedefler/dene", {"adres": sahte.adres, "tur": "CONTROLM", "ayrintilar": {"kimlik_turu": "apikey", "apikey_ref": "env:FWP_CTM_SIFRE"}})
    assert kod == 200 and r["basarili"] is False and "reddedildi" in r["mesaj"]  # yanlış anahtar: 401 başarı sayılmaz


def test_hedef_sifresi_ekrandan_girilir_uygulama_saklar(api, tmp_path):
    """Kullanıcı isteği 2026-09-30: şifre hedef penceresinde yazılır, kaydetmeden denenir, kaydedilir; uygulama
    kendisi saklar (Windows DPAPI, bu makineye bağlı). Teslim süreci (ayrı süreç) çözüp Control-M'e oturum açar.
    Düz şifre veritabanında, API yanıtında, denetimde ve logda görünmez."""
    o, port = api
    sir = "ornek-ctm-sifresi-B"
    s = SahteControlM(kullanici="fwpk", sifre=sir).baslat()
    try:
        y = Istemci(port)
        assert y.giris("yonetici")[0] == 200
        ayr = {"ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwpk"}
        kod, r = y.post("/api/hedefler/dene", {"adres": s.adres, "ayrintilar": {**ayr, "sifre": "yanlis-sifre"}})
        assert kod == 200 and not r["basarili"], r
        kod, r = y.post("/api/hedefler/dene", {"adres": s.adres, "ayrintilar": {**ayr, "sifre": sir}})
        assert kod == 200 and r["basarili"], r
        kod, r = y.post("/api/hedefler", {"ad": "ctm2", "adres": s.adres, "ayrintilar": {**ayr, "sifre_ref": "duz-sifre"}})
        assert kod == 400 and "Şifre' alanına" in r["hata"]                       # gelişmiş alana düz şifre yazılmaz
        kod, r = y.post("/api/hedefler", {"ad": "ctm2", "adres": s.adres, "tur": "CONTROLM", "ayrintilar": {**ayr, "sifre": sir}})
        assert kod == 200, r
        ham = json.loads(o.db.tek("SELECT ayrintilar FROM hedef WHERE id=?", (r["id"],))[0])
        assert ham["sifre_ref"].startswith("dpapi:") and "sifre" not in ham
        hj = json.dumps(y.get("/api/hedefler")[1], ensure_ascii=False)
        assert ham["sifre_ref"] not in hj and "uygulamada şifreli (bu sunucu)" in hj
        d = tmp_path / "gelen_sifreli"
        d.mkdir()
        kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
        assert kod == 200, dz
        kod, k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "f", "regex": r"F_\d+\.csv", "hedef_id": r["id"],
                                          "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/F_GELDI/ODAT", "govde": ""}})
        assert kod == 200, k
        (d / "F_1.csv").write_text("x", encoding="utf-8")
        o.bekle(lambda: (t := tetik(o, "F_1.csv")) and t["durum"] == "ILETILDI")
        assert s.girisler >= 1 and [x["olay"] for x in s.olaylar] == ["F_GELDI"]
        duz_sir_yok(o, sir)
    finally:
        s.durdur()



# ================================================================ güvenlik taraması (2026-10-01)
def _ham_istek(port, satirlar: str, govde=b"") -> tuple:
    """Kendi başlıklarımızla ham HTTP isteği (http.client Host / Content-Length'i kendisi yazar)."""
    import socket as _s
    with _s.create_connection(("127.0.0.1", port), timeout=10) as so:
        so.sendall(satirlar.encode() + b"\r\n" + govde)
        veri = b""
        while b"\r\n\r\n" not in veri:
            parca = so.recv(4096)
            if not parca:
                break
            veri += parca
        return int(veri.split(b" ")[1]), veri


def test_host_ve_origin_denetimi_dns_rebinding(api):
    """Kötü bir site kendi alan adını 127.0.0.1'e çözdürüp (DNS rebinding) arayüze aynı kaynakmış gibi istek atamaz:
    Host bu sunucuyu göstermeyen istek reddedilir; yazma isteklerinde başka sitenin Origin'i reddedilir."""
    o, port = api
    kod, _ = _ham_istek(port, f"GET /api/durum HTTP/1.1\r\nHost: kotu-site.example:{port}\r\nConnection: close\r\n")
    assert kod == 421
    kod, _ = _ham_istek(port, f"POST /api/giris HTTP/1.1\r\nHost: kotu-site.example:{port}\r\nX-FWP: 1\r\n"
                              f"Content-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n", b"{}")
    assert kod == 421
    kod, _ = _ham_istek(port, f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port + 1}\r\nConnection: close\r\n")
    assert kod == 421                                                            # başka port
    g = json.dumps({"kullanici": "yonetici", "sifre": SIFRE}).encode()
    kod, _ = _ham_istek(port, f"POST /api/giris HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-FWP: 1\r\nOrigin: http://kotu-site.example\r\n"
                              f"Content-Type: application/json\r\nContent-Length: {len(g)}\r\nConnection: close\r\n", g)
    assert kod == 403
    kod, _ = _ham_istek(port, f"POST /api/giris HTTP/1.1\r\nHost: localhost:{port}\r\nX-FWP: 1\r\nOrigin: http://localhost:{port}\r\n"
                              f"Content-Type: application/json\r\nContent-Length: {len(g)}\r\nConnection: close\r\n", g)
    assert kod == 200
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200 and y.get("/api/durum")[0] == 200       # normal kullanım etkilenmez


def test_gecersiz_govde_boyu_baglantiyi_kilitlemez(api):
    o, port = api
    t0 = time.time()
    kod, _ = _ham_istek(port, f"POST /api/giris HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-FWP: 1\r\nContent-Length: -1\r\nConnection: close\r\n")
    assert kod == 400 and time.time() - t0 < 5
    kod, _ = _ham_istek(port, f"POST /api/giris HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-FWP: 1\r\nContent-Length: 99999999\r\nConnection: close\r\n")
    assert kod == 413


def test_regex_denemesi_suresi_sinirli_ve_yalniz_yonetici(api):
    """Kaydedilmemiş bir desen canlı denemede de ayrı süreçte, süre sınırıyla çalışır: (a+)+ gibi geri izleme patlaması
    kontrol arayüzünü kilitlemez. Deneme uçları operatör ve üstüne açıktır (izleyici çalıştıramaz)."""
    o, port = api
    iz = Istemci(port)
    assert iz.giris("izleyici")[0] == 200
    assert iz.post("/api/regex/dene", {"regex": "a", "adlar": ["a"]})[0] == 403
    y = Istemci(port)
    assert y.giris("yonetici")[0] == 200
    kod, r = y.post("/api/regex/dene", {"regex": r"F_(?P<no>\d+)\.csv", "adlar": ["F_12.csv", "G.csv"]})
    assert kod == 200 and r[0]["gruplar"] == {"no": "12"} and not r[1]["eslesti"]
    t0 = time.time()
    kod, r = y.post("/api/regex/dene", {"regex": "(a+)+$", "harf_duyarsiz": False, "adlar": ["a" * 40 + "!"]})
    assert kod == 400 and "çok yavaş" in r["hata"] and time.time() - t0 < 10
    assert y.get("/api/durum")[0] == 200                                         # arayüz ayakta


def test_sifre_degisince_diger_oturumlar_duser(api):
    o, port = api
    a, b = Istemci(port), Istemci(port)
    assert a.giris("operator")[0] == 200 and b.giris("operator")[0] == 200
    assert a.post("/api/sifre", {"eski": SIFRE, "yeni": "ornek-arayuz-sifresi-E"})[0] == 200
    assert a.get("/api/ben")[0] == 200                                           # değiştiren oturum sürer
    assert b.get("/api/ben")[0] == 401                                           # başka yerde açık kalan düşer



def test_kurallar_toplu_durdur_ac_dizin_ve_tumu(api, sahte, tmp_path):
    """Kullanıcı isteği 2026-10-01: kurallar ekrandan durdurulabilmeli, tamamını durdurma da olmalı. Dizin bazında
    ve tümü için toplu durdur / aç (operatör); kayıtlı → uyan dosya lokale, kayıtsız → gönderilmez; hedefler açık kalır."""
    o, port = api
    y, d, hedef_id, dizin_id, kural_id = kur_api(o, port, sahte, tmp_path)
    d2 = tmp_path / "gelen2"
    d2.mkdir()
    dz2 = y.post("/api/dizinler", {"yol": str(d2), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
    k2 = y.post("/api/kurallar", {"dizin_id": dz2["id"], "ad": "g", "regex": r"G_\d+\.csv", "hedef_id": hedef_id,
                                  "is_bilgisi": {"folder": "KL", "jobs": "IS"}})[1]["id"]
    izl, op = Istemci(port), Istemci(port)
    izl.giris("izleyici")
    op.giris("operator")
    assert izl.post("/api/kurallar/toptan_kapat", {"mod": "KAYITLI"})[0] == 403
    kod, r = op.post("/api/kurallar/toptan_kapat", {"mod": "KAYITLI", "dizin_id": dizin_id})
    assert kod == 200 and r["kapatilan"] == [kural_id]
    aktif = lambda i: o.db.tek("SELECT aktif FROM kural WHERE id=?", (i,))[0]          # noqa: E731
    assert aktif(kural_id) == 0 and aktif(k2) == 1
    dz = {x["id"]: x for x in y.get("/api/durum?taze=1")[1]["dizinler"]}
    assert [(k["ad"], k["aktif"], k["kapatma_modu"]) for k in dz[dizin_id]["kurallar"]] == [("fatura", 0, "KAYITLI")]
    (d / "F_1.csv").write_text("x", encoding="utf-8")
    (d2 / "G_1.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "F_1.csv")) and t["durum"] == "LOKALDE")      # kayıtlı: kaybolmaz
    o.bekle(lambda: (t := tetik(o, "G_1.csv")) and t["durum"] == "ILETILDI")      # diğer dizin etkilenmedi
    kod, r = op.post("/api/kurallar/toptan_kapat", {"mod": "KAYITSIZ"})                # tümü: yalnız açık olanlar
    assert kod == 200 and r["kapatilan"] == [k2]
    (d2 / "G_2.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "G_2.csv")) and t["durum"] == "KAYITSIZ_KAPALI")
    kod, r = op.post("/api/kurallar/toptan_ac", {})
    assert kod == 200 and sorted(r["acilan"]) == sorted([kural_id, k2])
    (d / "F_2.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: (t := tetik(o, "F_2.csv")) and t["durum"] == "ILETILDI")
    assert o.db.tek("SELECT 1 FROM hedef WHERE id=? AND aktif=1", (hedef_id,))           # hedef açık kaldı
    assert {"KURAL_TOPTAN_KAPAT", "KURAL_TOPTAN_AC"} <= {r[0] for r in o.hdb.oku("SELECT islem FROM denetim")}



def test_lokal_secerek_gonder_ve_sil_super_yonetici_tutanakli(api, sahte, tmp_path):
    """Kullanıcı isteği 2026-10-01: lokalde birikenlerden istediklerimi seçerek gönderebilmeli, istemediklerimi tek tek ya
    da toplu silebilmeliyim; her ikisi süper yönetici şifresi ister, kayıtlar çok sağlam olmalı."""
    from cekirdek import betik_sifresi
    o, port = api
    y, d, hedef_id, dizin_id, kural_id = kur_api(o, port, sahte, tmp_path)
    assert y.post(f"/api/hedefler/{hedef_id}/kapat", {"mod": "KAYITLI"})[0] == 200
    adlar = [f"F_{i}.csv" for i in range(1, 6)]
    for a in adlar:
        (d / a).write_text(a, encoding="utf-8")
    o.bekle(lambda: all((t := tetik(o, a)) and t["durum"] == "LOKALDE" and t["lokal_dosya"] for a in adlar), zaman_asimi=30)
    idler = {a: tetik(o, a)["id"] for a in adlar}
    op = Istemci(port)
    op.giris("operator")
    kod, r = op.post("/api/lokal/gonder", {"idler": [idler["F_1.csv"]]})
    assert kod == 403 and "kilidi kapalı" in r["hata"]                              # süper yönetici şifresi şart
    super_ = "ornek-super-sifre-B"
    betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), super_, belirleyen="test")
    assert op.post("/api/betik/kilit", {"sifre": super_})[0] == 200
    assert y.post(f"/api/hedefler/{hedef_id}/ac")[0] == 200                         # hedef açılır; lokaldekiler bekler
    time.sleep(1.5)
    assert all(tetik(o, a)["durum"] == "LOKALDE" for a in adlar)
    lokal_1 = tetik(o, "F_1.csv")["lokal_dosya"]
    kod, r = op.post("/api/lokal/gonder", {"idler": [idler["F_1.csv"], idler["F_2.csv"]]})
    assert kod == 200 and sorted(r["gonderilen"]) == sorted([idler["F_1.csv"], idler["F_2.csv"]]) and r["atlanan"] == []
    o.bekle(lambda: all(tetik(o, a)["durum"] == "ILETILDI" for a in ("F_1.csv", "F_2.csv")))
    t1 = tetik(o, "F_1.csv")
    assert t1["eritildi"] == 1 and t1["elle"] == 1 and t1["sla_ihlali"] == 0           # SLA istatistiğine girmez
    assert not Path(lokal_1).exists()
    assert o.hdb.tek("SELECT cozum FROM gonderilemeyen WHERE anahtar=?", (t1["idempotency"],))[0] == "ELLE"
    assert len(sahte.siparisler) == 2                                              # yalnız seçilen iki dosya gitti
    assert all(tetik(o, a)["durum"] == "LOKALDE" for a in ("F_3.csv", "F_4.csv", "F_5.csv"))   # seçilmeyenler bekliyor

    sil = [idler["F_3.csv"], idler["F_4.csv"], idler["F_1.csv"]]                   # F_1 artık lokalde değil
    assert op.post("/api/lokal/sil", {"idler": sil, "neden": "test dosyaları"})[0] == 403   # silme yönetici işi
    kod, r = y.post("/api/lokal/sil", {"idler": sil, "neden": "x"})
    assert kod == 403                                                              # yöneticinin oturumunda kilit kapalı
    y.post("/api/betik/kilit", {"sifre": super_})
    kod, r = y.post("/api/lokal/sil", {"idler": sil, "neden": "x"})
    assert kod == 400 and "neden" in r["hata"]
    lokal_3 = tetik(o, "F_3.csv")["lokal_dosya"]
    kod, r = y.post("/api/lokal/sil", {"idler": sil, "neden": "yanlış kuralla tetiklenmiş deneme dosyaları"})
    assert kod == 200, r
    assert sorted(r["silinen"]) == sorted([idler["F_3.csv"], idler["F_4.csv"]]) and r["lokalde_degildi"] == [idler["F_1.csv"]]
    t3 = tetik(o, "F_3.csv")
    assert t3["durum"] == "SILINDI" and "yanlış kuralla" in t3["son_hata"] and "lokal_silinen" in t3["lokal_dosya"]
    assert not Path(lokal_3).exists() and Path(t3["lokal_dosya"]).exists()            # arşive taşındı
    tutanak = json.loads(Path(r["tutanak"]).read_text(encoding="utf-8"))
    assert tutanak["durum"] == "TAMAMLANDI" and tutanak["kullanici"] == "yonetici" and tutanak["adet"] == 2
    assert {k["tetik"]["dosya_adi"] for k in tutanak["kayitlar"]} == {"F_3.csv", "F_4.csv"}
    assert all(k["lokal_kayit"]["idempotency"] == k["tetik"]["idempotency"] for k in tutanak["kayitlar"])
    assert "ELLE_SILINDI (yonetici)" in o.hdb.tek("SELECT cozum FROM gonderilemeyen WHERE anahtar=?", (t3["idempotency"],))[0]
    den = json.loads(o.hdb.tek("SELECT yeni FROM denetim WHERE islem='LOKAL_SIL'")[0])
    assert den["tutanak"] == r["tutanak"] and {x["dosya"] for x in den["tetikler"]} == {"F_3.csv", "F_4.csv"}
    assert o.hdb.tek("SELECT 1 FROM denetim WHERE islem='LOKAL_SECILI_GONDER'")

    # silinen tetiğin satırı budansa bile açılıştaki geri yükleme onu diriltmez (lokal dosya arşivde)
    o.cekirdek_kapat()
    o.db.calistir("DELETE FROM tetik WHERE dosya_adi IN ('F_3.csv','F_4.csv')")
    o.cekirdek_baslat()
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "teslim")))
    time.sleep(2)
    assert tetik(o, "F_3.csv") is None and tetik(o, "F_4.csv") is None
    assert tetik(o, "F_5.csv")["durum"] == "LOKALDE"                               # seçilmeyen hâlâ güvende
