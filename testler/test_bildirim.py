"""Bildirim (mail) testleri — kullanıcı isteği 2026-09-30: hangi olaylar, hangi dizinler, kime; SMTP + kullanıcı/şifre.

Gerçek çekirdek + tarama + kontrol + bildirim süreçleri; mailler sahte SMTP sunucusunda toplanır. Ayar ve kurallar
önyüzün kullandığı API ile yapılır.
"""
import json
import time

import pytest

from cekirdek.kullanicilar import Kullanicilar
from testler.conftest import HIZLI_TARAMA, duz_sir_yok
from testler.sahte_smtp import SahteSMTP
from testler.test_adim8_kontrol_api import SIFRE, Istemci

EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
              {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"},
              {"ad": "bildirim", "modul": "eklentiler.bildirim.bildirimci"}]
AYAR = {**HIZLI_TARAMA, "bildirim_deneme_plani": "0.5,0.5", "bildirim_tasma_esigi": 10, "bildirim_tasma_ozet_dk": 0.05}


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv("FWP_TEST_SMTP_SIFRE", "ornek-smtp-sifresi")         # çekirdek süreçleri bu ortamı devralır
    s = SahteSMTP("fwp", "ornek-smtp-sifresi").baslat()
    yield s
    s.durdur()


def kur(ortam_yap, tmp_path, smtp, **ayar):
    o = ortam_yap(eklentiler=EKLENTILER, ayarlar={**AYAR, **ayar})
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    k.ekle("yonetici", SIFRE, "YONETICI")
    k.ekle("operator", SIFRE, "OPERATOR")
    dizinler = []
    for ad in ("muhasebe", "lojistik"):
        d = tmp_path / ad
        i = o.dizin_kur(d, "TETIKLE", ".csv")
        o.kural_kur(i, r"F_\d+\.csv", ad=f"f_{ad}")
        dizinler += [d, i]
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                and json.loads(e["bilgi"] or "{}").get("port") and e)
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "bildirim")))
    y = Istemci(json.loads(s["bilgi"])["port"])
    assert y.giris("yonetici")[0] == 200
    assert y.put("/api/bildirim/smtp", smtp.ayar())[0] == 200
    return (o, y, *dizinler)


def mailler(smtp, alici, konu=""):
    return [m for m in smtp.mailler if alici in m["to"] and konu in m["konu"]]


def kural(y, **alan):
    g = {"ad": "k", "alicilar": ["ops@test.local"], "olaylar": [], "seviye": "BILGI", "dizinler": None, "ozet_dk": 0,
         "tekrar_dk": 60, "duzelince": True, "aktif": True, **alan}
    kod, r = y.post("/api/bildirim/kurallar", g)
    assert kod == 200, r
    return r["id"]


def test_smtp_ayari_dene_ve_test_maili(ortam_yap, tmp_path, smtp):
    o, y, *_ = kur(ortam_yap, tmp_path, smtp)
    assert "wincred" in y.put("/api/bildirim/smtp", smtp.ayar(sifre_ref="duz-sifre"))[1]["hata"]   # şifre yazılamaz
    assert y.put("/api/bildirim/smtp", smtp.ayar(gonderen="gecersiz"))[0] == 400
    b = y.get("/api/bildirim")[1]
    assert b["smtp"]["sunucu"] == "127.0.0.1" and "ornek-smtp-sifresi" not in json.dumps(b)
    assert y.post("/api/bildirim/smtp/dene", smtp.ayar())[1]["basarili"] is True
    r = y.post("/api/bildirim/smtp/dene", smtp.ayar(sifre_ref="env:YOK_BOYLE"))[1]
    assert r["basarili"] is False and "şifre okunamadı" in r["mesaj"]
    assert y.post("/api/bildirim/test", {"alici": "adres-degil"})[0] == 400
    op = Istemci(y.port)
    op.giris("operator")
    assert op.put("/api/bildirim/smtp", smtp.ayar())[0] == 403
    assert op.post("/api/bildirim/test", {"alici": "ops@test.local"})[0] == 200
    assert len(mailler(smtp, "ops@test.local", "Test maili")) == 1
    g = y.get("/api/bildirim")[1]["gecmis"][0]
    assert g["kural"] == "(test)" and g["durum"] == "GONDERILDI" and g["alicilar"] == ["ops@test.local"]
    smtp.durdur()
    kod, r = y.post("/api/bildirim/test", {"alici": "ops@test.local"})
    assert kod == 502 and "bağlanılamadı" in r["hata"]
    assert y.get("/api/bildirim")[1]["gecmis"][0]["durum"] == "HATA"
    assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem IN ('SMTP_AYARLA','TEST_MAILI')")[0] >= 3


def test_kapsam_seviye_duzelince_ve_alici_tekilligi(ortam_yap, tmp_path, smtp):
    """Dizin kapsamı dizine bağlı olayları süzer; aynı olaya uyan anında kuralların ortak alıcısı tek mail alır;
    'düzelince' yalnızca açıkken bildirilmiş olayda ve yalnızca bu seçenek açık kurallarda."""
    o, y, dA, idA, dB, idB = kur(ortam_yap, tmp_path, smtp)
    assert y.post("/api/bildirim/kurallar", {"ad": "x", "alicilar": ["adres-degil"], "olaylar": ["DIZIN_ERISILEMEZ"]})[0] == 400
    assert y.post("/api/bildirim/kurallar", {"ad": "x", "alicilar": ["a@b.local"], "olaylar": ["UYDURMA"]})[0] == 400
    kural(y, ad="Ops kritik", olaylar=["DIZIN_ERISILEMEZ"], seviye="KRITIK", dizinler=[idA])
    kural(y, ad="Ops yedek", alicilar=["ops@test.local", "sef@test.local"], olaylar=["DIZIN_ERISILEMEZ"], duzelince=False)
    kural(y, ad="Muhasebe", alicilar=["muh@test.local"], olaylar=["DOSYA_ESLESMEDI"], dizinler=[idA])
    # lojistik (B) düşer: yalnız 'Ops yedek' (tüm dizinler) uyar
    dB.rename(dB.with_name("lojistik_gitti"))
    o.bekle(lambda: mailler(smtp, "sef@test.local", "lojistik"), zaman_asimi=30, mesaj="B için mail gelmedi")
    assert len(mailler(smtp, "ops@test.local", "lojistik")) == 1 and "Ops yedek" in mailler(smtp, "ops@test.local", "lojistik")[0]["govde"]
    # muhasebe (A) düşer: iki kural uyar, ops bir kez alır
    dA.rename(dA.with_name("muhasebe_gitti"))
    o.bekle(lambda: mailler(smtp, "sef@test.local", "muhasebe"), zaman_asimi=30)
    time.sleep(3)
    m = mailler(smtp, "ops@test.local", "muhasebe")
    assert len(m) == 1 and "KRİTİK" in m[0]["konu"] and "Ops kritik, Ops yedek" in m[0]["govde"] and "Ne yapmalı" in m[0]["govde"]
    # A geri gelir: DÜZELDİ yalnız 'Ops kritik' (düzelince açık) üzerinden, yalnız ops'a
    dA.with_name("muhasebe_gitti").rename(dA)
    o.bekle(lambda: mailler(smtp, "ops@test.local", "DÜZELDİ"), zaman_asimi=30, mesaj="düzeldi maili gelmedi")
    time.sleep(3)
    assert not mailler(smtp, "sef@test.local", "DÜZELDİ") and len(mailler(smtp, "ops@test.local", "DÜZELDİ")) == 1
    # kurala uymayan dosya: A kapsamda (muh alır), B'ye bırakılan dosya değil (B zaten erişilemez; A'ya ikinci dosya)
    (dA / "rapor.csv").write_text("x", encoding="utf-8")
    o.bekle(lambda: mailler(smtp, "muh@test.local", "Kurala uymayan"), zaman_asimi=30)
    assert "rapor.csv" in mailler(smtp, "muh@test.local")[0]["govde"]
    # önyüz: açık B alarmında gerçekten gönderilmiş mail bilgisi
    a = next(x for x in y.get("/api/alarmlar")[1] if x["aktif"] and x["kategori"] == "DIZIN_ERISILEMEZ")
    assert "Ops yedek" in a["mail"] and "lojistik" in a["nesne"]


def test_mail_yagmuru_ozete_gecer(ortam_yap, tmp_path, smtp):
    """Anında kural kısa sürede eşikten çok mail üretirse kalanlar tek özet mailde toplanır (hiçbir olay kaybolmaz)."""
    o, y, dA, idA, dB, idB = kur(ortam_yap, tmp_path, smtp, bildirim_tasma_esigi=2)
    kural(y, ad="Hepsi", olaylar=["DOSYA_ESLESMEDI"])
    for i in range(6):
        (dA / f"rapor{i}.csv").write_text(str(i), encoding="utf-8")
    o.bekle(lambda: mailler(smtp, "ops@test.local", "Özet"), zaman_asimi=40, mesaj="özet maili gelmedi")
    time.sleep(3)
    m = mailler(smtp, "ops@test.local")
    ozet = [x for x in m if "Özet" in x["konu"]]
    assert len(m) == 3 and len(ozet) == 1 and "Özet: 4 olay" in ozet[0]["konu"]
    assert "geçici olarak özetlendi" in ozet[0]["govde"]
    assert all(f"rapor{i}.csv" in "".join(x["govde"] for x in m) for i in range(6))


def test_ozet_kurali_tek_mailde_toplar(ortam_yap, tmp_path, smtp):
    """Özet kural (1 dk): süre dolmadan mail yok; dolunca biriken olaylar tek mailde (bu test ~1 dk sürer)."""
    o, y, dA, idA, dB, idB = kur(ortam_yap, tmp_path, smtp)
    kural(y, ad="Günlük özet", olaylar=["DOSYA_ESLESMEDI"], ozet_dk=1)
    for i in range(3):
        (dA / f"x{i}.csv").write_text(str(i), encoding="utf-8")
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM bildirim_olay")[0] == 3, zaman_asimi=20)
    time.sleep(20)
    assert not smtp.mailler
    o.bekle(lambda: smtp.mailler, zaman_asimi=60, mesaj="özet süresi dolunca mail gelmedi")
    assert len(smtp.mailler) == 1 and "Özet: 3 olay (Günlük özet)" in smtp.mailler[0]["konu"]


def test_gonderilemeyen_mail_yeniden_denenir_sonra_alarm(ortam_yap, tmp_path, smtp):
    """SMTP geçici hata verirse plan kadar yeniden denenir, sonra HATA + 'Mail gönderilemiyor' alarmı (bu alarm maille
    bildirilmez); SMTP düzelince sonraki mail gider ve alarm kapanır. İzleme bu sürede etkilenmez."""
    o, y, dA, idA, dB, idB = kur(ortam_yap, tmp_path, smtp)
    kural(y, ad="Ops", olaylar=["DIZIN_ERISILEMEZ", "MAIL_GONDERILEMIYOR"])
    smtp.mod_ayarla("gecici")
    o.db.alarm_ac(f"dizin:{idA}:erisilemez", "deneme: dizin erişilemez", "KRITIK", "test")
    o.bekle(lambda: o.db.tek("SELECT 1 FROM bildirim_mail WHERE durum='HATA' AND deneme=3"), zaman_asimi=30)
    a = o.bekle(lambda: o.db.tek("SELECT * FROM alarm WHERE anahtar='bildirim:gonderilemiyor' AND aktif=1"))
    assert "451" in a["mesaj"]
    (dA / "F_1.csv").write_text("1", encoding="utf-8")                        # izleme sürüyor
    o.bekle(lambda: o.tetikler("F_1.csv"))
    smtp.mod_ayarla("normal")
    o.db.alarm_ac(f"dizin:{idB}:erisilemez", "deneme: ikinci dizin", "KRITIK", "test")
    o.bekle(lambda: mailler(smtp, "ops@test.local", "lojistik"), zaman_asimi=30)
    o.bekle(lambda: o.db.tek("SELECT 1 FROM alarm WHERE anahtar='bildirim:gonderilemiyor' AND aktif=1") is None)
    assert not mailler(smtp, "ops@test.local", "Mail gönderilemiyor")


def test_kural_eklenince_acik_alarm_bir_kez_bildirilir(ortam_yap, tmp_path, smtp):
    o, y, dA, idA, dB, idB = kur(ortam_yap, tmp_path, smtp)
    o.db.alarm_ac(f"dizin:{idA}:erisilemez", "önceden açık alarm", "KRITIK", "test")
    time.sleep(3)
    assert not smtp.mailler                                                     # kural yokken mail yok
    kural(y, ad="Sonradan", olaylar=["DIZIN_ERISILEMEZ"])
    o.bekle(lambda: smtp.mailler, zaman_asimi=60, mesaj="açık alarm yeni kurala bildirilmedi")
    time.sleep(35)                                                             # bir hatırlatma turu daha geçer
    assert len(smtp.mailler) == 1


def test_smtp_sifresi_ekrandan_girilir_uygulama_saklar(ortam_yap, tmp_path, smtp):
    """Kullanıcı isteği 2026-09-30: SMTP şifresi pencerede yazılır, kaydetmeden denenir, kaydedilir; uygulama kendisi
    saklar (DPAPI). Boş bırakılırsa kayıtlı şifre korunur ve denemede kullanılır. Bildirim süreci (ayrı süreç) çözüp
    mail gönderir. Düz şifre hiçbir dosyada, API yanıtında ya da denetimde görünmez."""
    o, y, *_ = kur(ortam_yap, tmp_path, smtp)
    a = smtp.ayar()
    a.pop("sifre_ref")
    kod, r = y.post("/api/bildirim/smtp/dene", {**a, "sifre": "yanlis-sifre"})
    assert kod == 200 and not r["basarili"] and "kimlik doğrulama başarısız" in r["mesaj"], r
    kod, r = y.post("/api/bildirim/smtp/dene", {**a, "sifre": "ornek-smtp-sifresi"})
    assert kod == 200 and r["basarili"], r
    kod, r = y.put("/api/bildirim/smtp", {**a, "sifre_ref": "ornek-smtp-sifresi"})
    assert kod == 400 and "Şifre' alanına" in r["hata"]                    # gelişmiş alana düz şifre yazılmaz
    kod, r = y.put("/api/bildirim/smtp", {**a, "sifre": "ornek-smtp-sifresi"})
    assert kod == 200 and "sifre" not in r and r["sifre_kayitli"] and r["sifre_ref"] == "", r
    ref = json.loads(o.db.meta_al("smtp"))["sifre_ref"]
    assert ref.startswith("dpapi:")
    b = y.get("/api/bildirim")[1]["smtp"]
    assert b["sifre_kaynagi"] == "uygulamada şifreli (bu sunucu)" and ref not in json.dumps(b)
    assert y.put("/api/bildirim/smtp", {**a, "gonderen_ad": "FWP Deneme"})[0] == 200          # şifre alanı boş
    assert json.loads(o.db.meta_al("smtp"))["sifre_ref"] == ref
    assert y.post("/api/bildirim/smtp/dene", a)[1]["basarili"]                                 # kayıtlı şifreyle
    kural(y, olaylar=["KAYNAK_DISK"], alicilar=["ops@test.local"])
    o.db.alarm_ac("kaynak:disk", "Disk boş alanı azaldı (deneme)", "KRITIK", "izleme")
    o.bekle(lambda: mailler(smtp, "ops@test.local", "Disk"), mesaj="bildirim süreci kayıtlı şifreyle gönderemedi")
    denetim = o.hdb.oku("SELECT eski, yeni FROM denetim WHERE islem='SMTP_AYARLA' ORDER BY id")
    for r_ in denetim:
        assert "dpapi:" not in (r_["eski"] or "") + (r_["yeni"] or ""), dict(r_)             # şifreli hâli de yazılmaz
    assert [json.loads(r_["yeni"]).get("sifre_degisti") for r_ in denetim][-2:] == [True, False]
    duz_sir_yok(o, "ornek-smtp-sifresi")



def test_mail_konusunda_satir_sonu_baslik_eklemez(smtp):
    """Konuya dışarıdan gelen metin (ör. hata mesajı) satır sonu içerse bile ek başlık (Bcc) eklenemez."""
    from cekirdek import eposta
    a = {**smtp.ayar(), "sifre_ref": "env:FWP_TEST_SMTP_SIFRE"}
    eposta.gonder(eposta.ayar_dogrula(a), ["ops@test.local"], "Uyarı\r\nBcc: gizli@kotu.example", "gövde")
    m = smtp.mailler[-1]
    assert m["to"] == ["ops@test.local"] and "\n" not in m["konu"] and m["konu"].startswith("Uyarı")



def test_kurala_bagli_mail_yalniz_o_kuralin_ve_dizininin_olaylari(ortam_yap, tmp_path, smtp):
    """Kullanıcı isteği 2026-10-01: kural eklerken o kurala bağlanacak mail adresi seçilebilsin; ör. X dizinindeki
    regex'e uymayan dosya ya da o kuralın gönderilemeyen dosyası bu adrese gitsin. Başka kuralın / dizinin olayı gitmez."""
    o = ortam_yap(eklentiler=[*EKLENTILER, {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"}],
                  ayarlar={**AYAR, "sabitlik_W_sn": 0.3, "deneme_plani": "0.2,0.2", "cagri_timeout_sn": 0.5,
                           "otomatik_devre_esigi": 0})
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    k.ekle("yonetici", SIFRE, "YONETICI")
    hedef = o.yap.hedef_ekle("kapali-ctm", "http://127.0.0.1:9/automation-api", ayrintilar={"kimlik_turu": "yok"},
                             kullanici="test")
    d1, d2 = tmp_path / "muhasebe", tmp_path / "lojistik"
    i1, i2 = o.dizin_kur(d1, "TETIKLE", ".csv"), o.dizin_kur(d2, "TETIKLE", ".csv")
    ka = o.kural_kur(i1, r"A_\d+\.csv", hedef, ad="kural_a")
    o.kural_kur(i1, r"B_\d+\.csv", hedef, ad="kural_b")
    o.kural_kur(i2, r"C_\d+\.csv", hedef, ad="kural_c")
    o.cekirdek_baslat()
    s_ = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                 and json.loads(e["bilgi"] or "{}").get("port") and e)
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "teslim", "bildirim")))
    y = Istemci(json.loads(s_["bilgi"])["port"])
    assert y.giris("yonetici")[0] == 200
    assert y.put("/api/bildirim/smtp", smtp.ayar())[0] == 200
    bid = kural(y, ad="Kural: kural_a", alicilar=["a@test.local"], olaylar=["DOSYA_GONDERILEMEDI", "DOSYA_ESLESMEDI"],
                dizinler=[i1], kurallar=[ka])
    b = next(x for x in y.get("/api/bildirim")[1]["kurallar"] if x["id"] == bid)
    assert b["kurallar"] == [ka] and b["dizinler"] == [i1] and b["kural_adlari"] == [f"kural_a ({d1})"]
    kr = {x["ad"]: x for x in next(dz for dz in y.get("/api/dizinler")[1] if dz["id"] == i1)["kurallar"]}
    assert kr["kural_a"]["mail"] == ["a@test.local"] and kr["kural_b"]["mail"] == []
    assert y.post("/api/bildirim/kurallar", {"ad": "x", "alicilar": ["a@test.local"], "olaylar": ["DOSYA_SLA"],
                                             "kurallar": [99999]})[0] == 400

    for d, ad in ((d1, "A_1.csv"), (d1, "B_1.csv"), (d1, "X_1.csv"), (d2, "Y_1.csv"), (d2, "C_1.csv")):
        (d / ad).write_text(ad, encoding="utf-8")
    o.bekle(lambda: all((t := o.db.tek("SELECT durum FROM tetik WHERE dosya_adi=?", (a,))) and t[0] == "LOKALDE"
                        for a in ("A_1.csv", "B_1.csv", "C_1.csv")), zaman_asimi=40)
    o.bekle(lambda: all(any(x in m["govde"] for m in mailler(smtp, "a@test.local")) for x in ("A_1.csv", "X_1.csv")),
            zaman_asimi=30)
    time.sleep(3)                                                    # yanlış kapsamdan gelecek mail için pay
    govdeler = " ".join(m["konu"] + m["govde"] for m in mailler(smtp, "a@test.local"))
    assert "A_1.csv" in govdeler and "kural: kural_a" in govdeler   # kuralın gönderilemeyen dosyası
    assert "X_1.csv" in govdeler                                     # kuralın dizininde hiçbir regex'e uymayan dosya
    for yok in ("B_1.csv", "Y_1.csv", "C_1.csv"):                    # başka kural / başka dizin
        assert yok not in govdeler, yok

    assert y.istek("DELETE", f"/api/kurallar/{ka}")[0] == 200      # kural silinince ona bağlı bildirim de silinir
    assert not any(x["id"] == bid for x in y.get("/api/bildirim")[1]["kurallar"])
