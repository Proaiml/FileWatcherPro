"""Anomali takibi (kullanıcı isteği 2026-10-01: 'bu dosya hep şu MB'lar arasında geliyorken şuna çıktı / düştü; dosyaların
tetik sayısı, süresi'). İstatistik (medyan / MAD), PyTorch gerektirmez; dosya adı toplanmaz.
"""
import json
import random
import time

from eklentiler.asistan import anomali as A, depo
from eklentiler.asistan.depo import AsistanDB
from testler.test_adim7_teslim import EKLENTILER, HIZLI_TESLIM, sahte  # noqa: F401 (fikstür)


def _ay(**ek):
    return {**{k: v[0] for k, v in depo.AYARLAR.items()}, **ek}


def _ogle(gun_once=0):
    t = time.localtime(time.time() - gun_once * 86400)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 12, 0, 0, 0, 0, -1))


def test_istatistik_esikleri():
    random.seed(3)
    g = [random.uniform(1.2e6, 1.8e6) for _ in range(40)]
    assert not A.boyut_degerlendir(g, 1.5e6)["anomali"]
    s = A.boyut_degerlendir(g, 3000)
    assert s["anomali"] and s["yon"] == "küçük" and s["p5"] < 1.5e6 < s["p95"]
    assert A.boyut_degerlendir(g, 14e6)["anomali"] and A.boyut_degerlendir(g, 14e6)["yon"] == "büyük"
    assert A.boyut_degerlendir(g, 0)["anomali"]                                    # boş dosya
    assert A.boyut_degerlendir(g[:10], 0) is None                                  # geçmiş yetersiz: görüş yok
    assert not A.boyut_degerlendir([1000] * 30, 1050)["anomali"]                    # hep aynı boyutta: %5 oynama normal
    assert A.boyut_degerlendir([1000] * 30, 2000)["anomali"]
    assert A.sure_degerlendir([500] * 30, [5000] * 10)["anomali"]
    assert A.sure_degerlendir([500] * 30, [700] * 10)["normal"]
    assert not A.sure_degerlendir([100] * 30, [900] * 10)["anomali"]               # 9 kat ama 2 sn altında
    assert A.adet_degerlendir([10] * 14, 3)["anomali"] and A.adet_degerlendir([10] * 14, 25)["yon"] == "çok"
    assert not A.adet_degerlendir([10] * 14, 9)["anomali"]
    assert A.adet_degerlendir([1] * 14, 0) is None                                 # seyrek kural: görüş yok
    assert A.boyut_metni(3170) == "3,1 KB" and A.boyut_metni(1.52e6) == "1,4 MB" and A.boyut_metni(0) == "0 bayt"
    assert A.sayi_metni(5212.9) == "5.213" and A.sayi_metni(0.64) == "0,6" and A.sayi_metni(-38.24) == "-38,2"


def test_degerlendirme_oneri_alarm_kapanma_ozet_ve_golge_modu(ortam_yap, tmp_path):
    o = ortam_yap(eklentiler=[])
    dz = o.dizin_kur(tmp_path / "gelen", "TETIKLE", ".csv")
    hid = o.hedef_kur()
    kid = o.kural_kur(dz, r"F_\d+\.csv", hedef_id=hid, ad="fatura")
    kid2 = o.kural_kur(dz, r"G_\d+\.csv", hedef_id=hid, ad="sevk")
    adb = AsistanDB(tmp_path / "asistan.db").sema_kur()
    sayac = [0]

    def olc(z, tur, deger, kural=kid, tetik=None):
        sayac[0] += 1
        adb.calistir("INSERT INTO olcum(zaman, kural_id, hedef_id, tur, deger, kaynak) VALUES(?,?,?,?,?,?)",
                     (z, kural, hid, tur, deger, f"olcum:{tetik or 100000 + sayac[0]}:{tur}"))

    random.seed(5)
    for gun in range(16, 1, -1):                                     # 15 gün, günde 10 dosya (~1,5 MB)
        for k in range(10):
            olc(_ogle(gun) + k * 300, "boyut", random.uniform(1.2e6, 1.8e6))
            olc(_ogle(gun) + k * 300, "boyut", random.uniform(40e3, 60e3), kural=kid2)
    olc(_ogle(1), "boyut", 1.5e6)                                    # dün yalnız 2 dosya
    olc(_ogle(1) + 60, "boyut", 1.5e6)
    for k in range(10):                                              # 'sevk' dün de normal: 10 dosya
        olc(_ogle(1) + k * 300, "boyut", random.uniform(40e3, 60e3), kural=kid2)
    simdi = _ogle(0) + 3600
    an = A.Anomali(adb, o.db)
    an.tur(_ay(anomali_alarm=True), simdi)
    on = {r["anahtar"]: dict(r) for r in adb.oku("SELECT * FROM oneri WHERE tur='ANOMALI'")}
    assert any(a.startswith(f"anomali:{kid}:adet:") for a in on), on                 # dün 2 (genelde 10)
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:adet",))

    # boyut: 3 KB dosya → öneri (dosya adı canlı veritabanından) + alarm; normal dosya gelince alarm kapanır
    o.db.calistir("INSERT INTO tetik(id, dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi, tam_yol, durum, "
                  "olusturma) VALUES(777, 0, ?, ?, 'idm', '{}', 'FATURA_KUCUK.csv', 'C:\\x', 'BEKLIYOR', ?)", (kid, hid, simdi))
    olc(simdi, "boyut", 3100, tetik=777)
    an.tur(_ay(anomali_alarm=True), simdi + 1)
    o_ = next(dict(r) for r in adb.oku("SELECT * FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",)))
    assert "FATURA_KUCUK.csv 3,0 KB geldi" in o_["metin"] and "küçük" in o_["baslik"] and o_["kaynak"] == "istatistik"
    assert "kat daha küçük" in o_["metin"] and "." not in o_["metin"].split("Yaklaşık")[1].split("kat")[0], o_["metin"]
    assert any("Normal aralık" in k for k in json.loads(o_["kanit"]))
    assert "FATURA_KUCUK" not in json.dumps([dict(r) for r in adb.oku("SELECT * FROM olcum")])   # ad asistan.db'ye yazılmaz
    al = o.db.tek("SELECT mesaj, seviye FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:boyut",))
    assert al and al["seviye"] == "UYARI" and "alışılmadık küçük" in al["mesaj"]
    for i in range(5):                                               # küçük dosya seli: tek öneride toplanır
        olc(simdi + 1 + i * 0.1, "boyut", 2900 + i)
    an.tur(_ay(anomali_alarm=True), simdi + 1.9)
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",))[0] == 1
    o_ = next(dict(r) for r in adb.oku("SELECT * FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",)))
    assert json.loads(o_["kanit"])[0].startswith("Toplanan: 6 dosya") and o_["metin"].startswith("Bir dosya 2,8 KB"), o_
    assert "6. dosya" in o.db.tek("SELECT mesaj FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:boyut",))[0]
    olc(simdi + 2, "boyut", 1.6e6)
    an.tur(_ay(anomali_alarm=True), simdi + 3)
    assert not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:boyut",))
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",))[0] == 1
    adb.calistir("UPDATE oneri SET durum='FAYDALI' WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",))
    olc(simdi + 3.5, "boyut", 3000)                                  # geri bildirim verildi: sonraki anomali yeni öneri
    an.tur(_ay(anomali_alarm=True), simdi + 3.6)
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:boyut:%",))[0] == 2
    olc(simdi + 3.7, "boyut", 1.5e6)
    an.tur(_ay(anomali_alarm=True), simdi + 3.8)

    # teslim süresi: 40 geçmiş 600 ms → son 10 6 sn: öneri + alarm; sonra 10 × 600 ms: kapanır
    for i in range(40):
        olc(simdi - 3600 + i, "sure", 600)
    an.tur(_ay(anomali_alarm=True), simdi + 4)
    for i in range(10):
        olc(simdi + 5 + i, "sure", 6000)
    an.tur(_ay(anomali_alarm=True), simdi + 20)
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid}:sure:%",))[0] == 1
    assert o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:sure",))
    for i in range(10):
        olc(simdi + 30 + i, "sure", 600)
    an.tur(_ay(anomali_alarm=True), simdi + 50)
    assert not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:sure",))

    # özet (Anomaliler sekmesi)
    oz = {x["kural"]: x for x in json.loads(adb.meta_al("anomali_ozet"))}
    assert oz["fatura"]["yeterli"] and oz["fatura"]["boyut_p5"] < 1.5e6 < oz["fatura"]["boyut_p95"] and oz["fatura"]["anomali"]["adet"]
    assert oz["sevk"]["boyut_p95"] < 70e3 and not any(oz["sevk"]["anomali"].values())

    # gölge modu (varsayılan): öneri yazılır, alarm açılmaz
    olc(simdi + 60, "boyut", 5e6, kural=kid2)
    an.tur(_ay(), simdi + 61)
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE anahtar LIKE ?", (f"anomali:{kid2}:boyut:%",))[0] == 1
    assert not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=?", (f"anomali:{kid2}:boyut",))


def test_uctan_uca_gercek_dosyalarla(ortam_yap, tmp_path, sahte, monkeypatch):
    """Gerçek çekirdek + tarama + teslim + asistan (PyTorch'suz): 22 dosya ~100 KB, sonra 1 KB'lık dosya → anomali
    önerisi ve (ayar açıkken) alarm; normal dosya gelince alarm kapanır; teslim süreleri de toplanır."""
    monkeypatch.setenv("FWP_ASISTAN_TORCHSUZ", "1")
    o = ortam_yap(eklentiler=[*EKLENTILER, {"ad": "asistan", "modul": "eklentiler.asistan.asistan"}], ayarlar=HIZLI_TESLIM)
    d = tmp_path / "gelen"
    dz = o.dizin_kur(d, "TETIKLE", ".csv")
    hid = o.yap.hedef_ekle("controlm", sahte.adres, ayrintilar={"ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwp",
                                                                   "sifre_ref": "env:FWP_CTM_SIFRE"}, kullanici="test")
    kid = o.yap.kural_ekle(dz, "fatura", r"F_\d+\.csv", hid, kullanici="test",
                           istek={"yontem": "POST", "yol": "/run/event/{ctm}/F/ODAT", "govde": ""})
    adb = AsistanDB(o.veri / "asistan.db").sema_kur()
    depo.ayar_yaz(adb, {"anomali_alarm": True, "anomali_asgari": 20})
    o.cekirdek_baslat()
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "teslim", "asistan")), zaman_asimi=60)
    random.seed(9)
    for i in range(22):
        (d / f"F_{i}.csv").write_bytes(b"x" * random.randint(95_000, 110_000))
    o.bekle(lambda: adb.tek("SELECT COUNT(*) FROM olcum WHERE tur='boyut' AND kural_id=?", (kid,))[0] == 22, zaman_asimi=60)
    o.bekle(lambda: adb.tek("SELECT COUNT(*) FROM olcum WHERE tur='sure' AND kural_id=?", (kid,))[0] == 22, zaman_asimi=60)
    (d / "F_99.csv").write_bytes(b"x" * 1024)
    a = o.bekle(lambda: o.db.tek("SELECT mesaj FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:boyut",)), zaman_asimi=60)
    assert "F_99.csv 1,0 KB" in a[0]
    assert adb.tek("SELECT COUNT(*) FROM oneri WHERE tur='ANOMALI' AND anahtar LIKE ?", (f"anomali:{kid}:boyut:%",))[0] == 1
    (d / "F_100.csv").write_bytes(b"x" * 100_000)
    o.bekle(lambda: not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{kid}:boyut",)), zaman_asimi=60)
    assert all(x[0] is not None for x in o.db.oku("SELECT iletildi_zamani FROM tetik"))      # tetik yoluna karışmadı
