"""Adım 1 testleri: çekirdek (gözetmen, loglama, iki veritabanı) ve eklenti iskeleti.

Olay tablosu karşılıkları:
  M3 takılan eklenti · M4 düşen eklenti · M5 art arda düşen eklenti · M6 çekirdek ölümü
  G7 tek kopya · I1 veritabanı sınırları · U9/eklenti durumunun kalıcılığı
"""
import os
import signal
import subprocess
import time

import pytest

from cekirdek import win
from cekirdek.ayarlar import Ayarlar, dogrula
from cekirdek.db_canli import CanliDB
from cekirdek.db_hata import HataDB
from cekirdek.model import EklentiDurum, TetikDurum


# ============================================================ veritabanı ve ayarlar (süreçsiz)
def test_sema_ve_pragmalar(tmp_path):
    c = CanliDB(tmp_path / "canli.db").sema_kur()
    h = HataDB(tmp_path / "hata.db").sema_kur()
    assert c.pragma("journal_mode") == "wal" and h.pragma("journal_mode") == "wal"
    assert c.pragma("synchronous") == 1        # NORMAL
    assert h.pragma("synchronous") == 2        # FULL
    tablolar = {r[0] for r in c.oku("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ayar", "dizin", "kural", "hedef", "yukleme", "dosya", "tetik", "eklenti", "komut", "alarm"} <= tablolar
    tablolar = {r[0] for r in h.oku("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"gonderilemeyen", "denetim", "kesinti"} <= tablolar
    a = Ayarlar(c)
    assert a.al("hash_esik_mb") == 500.0 and a.al("gecmis_limit") == 200 and a.al("hata_limit") == 1000
    assert a.plan("deneme_plani") == [5.0, 10.0, 15.0]
    assert a.uzantilar("parca_uzantilari") == [".filepart", ".part"]


def test_ayar_dogrulama_ve_surum(tmp_path):
    assert dogrula("deneme_plani", "5, 10;15") == "5,10,15"
    assert dogrula("parca_uzantilari", "FILEPART; .Part") == ".filepart,.part"
    assert dogrula("bakim_saati", "3:0") == "03:00"
    assert dogrula("motor_aktif", "kapalı") is False
    for anahtar, kotu in [("hash_esik_mb", "abc"), ("sla_hedef_sn", 0), ("coklu_kural", "bazen"),
                          ("deneme_plani", "5,-1"), ("bakim_saati", "25:00"), ("gecmis_limit", 2.5),
                          ("parca_uzantilari", ".a/b"), ("yok_boyle_ayar", 1)]:
        with pytest.raises(ValueError):
            dogrula(anahtar, kotu)
    c = CanliDB(tmp_path / "canli.db").sema_kur()
    a1, a2 = Ayarlar(c), Ayarlar(c)
    a1.tazele(zorla=True), a2.tazele(zorla=True)
    assert a1.degistir("hash_esik_mb", "750") == (500.0, 750.0)
    assert a2.tazele() is True and a2.al("hash_esik_mb") == 750.0     # başka süreç sürüm değişimini görür
    assert a2.tazele() is False


def test_budama_aktifleri_ve_bekleyenleri_korur(tmp_path):
    c = CanliDB(tmp_path / "canli.db").sema_kur()
    simdi = time.time()
    with c.yaz() as con:
        for i in range(305):
            kalkma = None if i < 5 else simdi - i
            con.execute("INSERT INTO dosya(dizin_id, dosya_adi, ad_anahtar, tam_yol, boyut, mtime_ns, kimlik, durum,"
                        " ilk_gorulme, hazir_zamani, kalkma_zamani) VALUES(1,?,?,?,0,0,?, 'HAZIR', ?, ?, ?)",
                        (f"f{i}", f"f{i}", f"x\\f{i}", f"k{i}", simdi, simdi, kalkma))
        for i in range(260):
            durum = TetikDurum.ILETILDI if i >= 10 else (TetikDurum.BEKLIYOR if i % 2 else TetikDurum.LOKALDE)
            con.execute("INSERT INTO tetik(dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi,"
                        " tam_yol, durum, olusturma, kapanis) VALUES(1,1,1,?, '{}', 'f', 'x', ?, ?, ?)",
                        (f"i{i}", durum, simdi, simdi - i if durum == TetikDurum.ILETILDI else None))
    sonuc = c.gecmisi_buda(200)
    assert sonuc["dosya"] == 100 and sonuc["tetik"] == 50
    assert c.tek("SELECT COUNT(*) FROM dosya WHERE kalkma_zamani IS NULL")[0] == 5
    assert c.tek("SELECT COUNT(*) FROM dosya WHERE kalkma_zamani IS NOT NULL")[0] == 200
    assert c.tek("SELECT COUNT(*) FROM tetik WHERE durum IN ('BEKLIYOR','LOKALDE')")[0] == 10


def test_hata_db_cozulmemis_kayit_silinmez(tmp_path):
    h = HataDB(tmp_path / "hata.db").sema_kur()
    for i in range(1200):
        h.gonderilemeyen_yaz(f"a{i}", "SLA_SON_DOLDU", f"f{i}", f"x\\f{i}")
    for i in range(50):
        h.gonderilemeyen_yaz(f"c{i}", "SLA_SON_DOLDU", f"g{i}", f"x\\g{i}")
        h.cozuldu_isaretle(f"c{i}", "ERIT")
    r = h.buda(1000, 2000)
    assert r["gonderilemeyen"] == 50 and r["cozulmemis"] == 1200 and r["sinir_asildi"] is True
    assert h.cozulmemis_sayisi() == 1200
    h.gonderilemeyen_yaz("a1", "SLA_SON_DOLDU", "f1", "x\\f1", deneme_sayisi=4)   # aynı kayıt güncellenir
    assert h.tek("SELECT COUNT(*) FROM gonderilemeyen WHERE anahtar='a1'")[0] == 1


# ============================================================ gözetmen (gerçek süreçler)
def _calisiyor(o, ad):
    s = o.eklenti(ad)
    return s if s and s["durum"] == EklentiDurum.CALISIYOR and s["pid"] and win.surec_canli(s["pid"]) else None


def test_gozetmen_eklentileri_baslatir_ve_nabiz_yazilir(ortam_yap):
    o = ortam_yap()
    o.cekirdek_baslat()
    a = o.bekle(lambda: _calisiyor(o, "a"), mesaj="a çalışmadı")
    b = o.bekle(lambda: _calisiyor(o, "b"), mesaj="b çalışmadı")
    assert a["pid"] != b["pid"] != o.proc.pid
    o.bekle(lambda: time.time() - o.eklenti("a")["son_nabiz"] < 2, mesaj="nabız taze değil")
    ck = o.eklenti("cekirdek")
    assert ck["durum"] == EklentiDurum.CALISIYOR and ck["pid"] == o.proc.pid


def test_olen_eklenti_yeniden_baslar_digeri_etkilenmez(ortam_yap):
    """M4: eklenti süreci öldürülür → gözetmen yeniden başlatır; çekirdek ve diğer eklenti etkilenmez."""
    o = ortam_yap()
    o.cekirdek_baslat()
    a = o.bekle(lambda: _calisiyor(o, "a"))
    b = o.bekle(lambda: _calisiyor(o, "b"))
    os.kill(a["pid"], signal.SIGTERM)                       # Windows'ta TerminateProcess
    yeni = o.bekle(lambda: (s := _calisiyor(o, "a")) and s["pid"] != a["pid"] and s, mesaj="a yeniden başlamadı")
    assert yeni["yeniden_baslatma"] >= 1
    assert o.eklenti("b")["pid"] == b["pid"] and win.surec_canli(b["pid"])
    assert o.proc.poll() is None
    assert o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar='eklenti:a:dustu'")[0] == 1


def test_takilan_eklenti_oldurulup_yeniden_baslatilir(ortam_yap):
    """M3: ana döngüsü takılan eklenti (nabız thread'i yaşasa da) öldürülür ve yeniden başlatılır."""
    o = ortam_yap()
    o.cekirdek_baslat()
    a = o.bekle(lambda: _calisiyor(o, "a"))
    o.davranis("a", "takil")
    s = o.bekle(lambda: (s := o.eklenti("a")) and s["yeniden_baslatma"] >= 1 and s, zaman_asimi=40,
                mesaj="takılan eklenti yeniden başlatılmadı")
    assert "ilerlemedi" in (s["son_hata"] or "")
    assert not win.surec_canli(a["pid"])
    o.davranis("a", "normal")
    o.bekle(lambda: _calisiyor(o, "a"), zaman_asimi=40)
    assert o.proc.poll() is None


def test_surekli_coken_eklenti_elle_mudahaleye_gecer(ortam_yap):
    """M5: art arda düşen eklenti ELLE_MUDAHALE + KRİTİK alarm; önyüz BASLAT komutuyla geri gelir."""
    o = ortam_yap()
    o.davranis("a", "coker")
    o.cekirdek_baslat()
    s = o.bekle(lambda: (s := o.eklenti("a")) and s["durum"] == EklentiDurum.ELLE_MUDAHALE and s,
                zaman_asimi=40, mesaj="ELLE_MUDAHALE durumuna geçmedi")
    assert s["pid"] is None and "bilerek çöktü" in (s["son_hata"] or "")
    alarm = o.db.tek("SELECT * FROM alarm WHERE anahtar='eklenti:a:elle' AND aktif=1")
    assert alarm is not None and alarm["seviye"] == "KRITIK"
    time.sleep(2)
    assert o.eklenti("a")["durum"] == EklentiDurum.ELLE_MUDAHALE      # kendiliğinden denemiyor
    assert _calisiyor(o, "b")                                            # diğeri etkilenmedi
    o.davranis("a", "normal")
    o.db.komut_gonder("gozetmen", "BASLAT", {"ad": "a"}, kullanici="test")
    o.bekle(lambda: _calisiyor(o, "a"), mesaj="BASLAT komutuyla geri gelmedi")
    assert o.db.tek("SELECT COUNT(*) FROM alarm WHERE anahtar='eklenti:a:elle' AND aktif=1")[0] == 0


def test_durdur_baslat_yeniden_baslat_komutlari_ve_denetim(ortam_yap):
    o = ortam_yap()
    o.cekirdek_baslat()
    b = o.bekle(lambda: _calisiyor(o, "b"))
    o.db.komut_gonder("gozetmen", "DURDUR", {"ad": "b"}, kullanici="deniz")
    o.bekle(lambda: o.eklenti("b")["durum"] == EklentiDurum.DURDURULDU, mesaj="durmadı")
    o.bekle(lambda: not win.surec_canli(b["pid"]), mesaj="süreç hâlâ yaşıyor")
    time.sleep(1.5)
    assert o.eklenti("b")["durum"] == EklentiDurum.DURDURULDU            # kendiliğinden başlamadı
    o.db.komut_gonder("gozetmen", "BASLAT", {"ad": "b"}, kullanici="deniz")
    b2 = o.bekle(lambda: _calisiyor(o, "b"))
    o.db.komut_gonder("gozetmen", "YENIDEN_BASLAT", {"ad": "b"}, kullanici="deniz")
    o.bekle(lambda: (s := _calisiyor(o, "b")) and s["pid"] != b2["pid"], mesaj="yeniden başlamadı")
    islemler = [r["islem"] for r in o.hdb.oku("SELECT islem FROM denetim WHERE kullanici='deniz' ORDER BY id")]
    assert islemler == ["EKLENTI_DURDUR", "EKLENTI_BASLAT", "EKLENTI_YENIDEN_BASLAT"]
    bilinmeyen = o.db.komut_gonder("gozetmen", "BASLAT", {"ad": "yok"}, kullanici="deniz")
    o.bekle(lambda: o.db.tek("SELECT durum FROM komut WHERE id=?", (bilinmeyen,))["durum"] == "HATA")
    assert o.proc.poll() is None


def test_kullanicinin_durdurdugu_eklenti_yeniden_acilista_durur(ortam_yap):
    o = ortam_yap()
    o.cekirdek_baslat()
    o.bekle(lambda: _calisiyor(o, "a"))
    o.bekle(lambda: _calisiyor(o, "b"))
    o.db.komut_gonder("gozetmen", "DURDUR", {"ad": "b"}, kullanici="test")
    o.bekle(lambda: o.eklenti("b")["durum"] == EklentiDurum.DURDURULDU)
    o.cekirdek_kapat()
    assert o.eklenti("a")["durum"] == EklentiDurum.KAPANDI
    assert o.eklenti("b")["durum"] == EklentiDurum.DURDURULDU
    o.cekirdek_baslat()
    o.bekle(lambda: _calisiyor(o, "a"))
    time.sleep(2)
    assert o.eklenti("b")["durum"] == EklentiDurum.DURDURULDU


def test_tek_kopya_kilidi(ortam_yap):
    """G7: aynı veri klasörü için ikinci çekirdek çalışmaz."""
    o = ortam_yap()
    o.cekirdek_baslat()
    o.bekle(lambda: _calisiyor(o, "a"))
    ikinci = subprocess.run(o.cekirdek_komutu(), capture_output=True, timeout=60,
                            creationflags=0x08000000)
    assert ikinci.returncode == 3
    assert o.proc.poll() is None


def test_cekirdek_olurse_eklentiler_de_kapanir(ortam_yap):
    """Çekirdek aniden ölürse (Job Object) eklentiler sahipsiz kalmaz; yeniden açılışta temiz başlar."""
    o = ortam_yap()
    o.cekirdek_baslat()
    a = o.bekle(lambda: _calisiyor(o, "a"))
    b = o.bekle(lambda: _calisiyor(o, "b"))
    o.proc.kill()
    o.proc.wait(10)
    o.bekle(lambda: not win.surec_canli(a["pid"]) and not win.surec_canli(b["pid"]), zaman_asimi=15,
            mesaj="eklentiler çekirdekle birlikte kapanmadı")
    o.cekirdek_baslat()
    a2 = o.bekle(lambda: _calisiyor(o, "a"))
    assert a2["pid"] != a["pid"]


def test_log_dosyalari_ve_olay_satirlari(ortam_yap):
    o = ortam_yap()
    o.cekirdek_baslat()
    o.bekle(lambda: _calisiyor(o, "a"))
    o.cekirdek_kapat()
    cekirdek_log = list(o.loglar.glob("cekirdek_*.log"))
    a_log = list(o.loglar.glob("a_*.log"))
    assert cekirdek_log and a_log
    icerik = cekirdek_log[0].read_text(encoding="utf-8")
    assert "EVENT | CEKIRDEK_BASLADI |" in icerik and "EVENT | EKLENTI_BASLATILDI |" in icerik
    assert "EVENT | CEKIRDEK_KAPANDI |" in icerik
    assert "EVENT | EKLENTI_BASLADI |" in a_log[0].read_text(encoding="utf-8")



def test_olay_satiri_disaridan_gelen_satir_sonunu_kacirir():
    """Güvenlik (2026-10-01): olay alanına dışarıdan gelen metin (sunucu yanıtı, hata mesajı) satır sonu içerse bile
    tek satır kalır; sahte bir 'EVENT | ...' satırı uyduramaz."""
    from cekirdek.loglama import _temiz
    s = _temiz("hata\r\nEVENT | TETIK | yol=sahte")
    assert "\n" not in s and "\r" not in s and s == '"hata\\r\\nEVENT | TETIK | yol=sahte"'



def test_log_boyut_sinirinda_doner_eskiler_ziplenir_ve_silinir(tmp_path):
    """I2: log şişmez. Dosya boyut sınırını aşınca yeni dosyaya geçilir, eskisi zip'lenir; saklama süresinden eski
    log dosyaları silinir."""
    import os
    import time as _t
    from loguru import logger
    from cekirdek import loglama
    eski = tmp_path / "deneme_2026-01-01.log"
    eski.write_text("eski", encoding="utf-8")
    gecmis = _t.time() - 30 * 86400
    os.utime(eski, (gecmis, gecmis))
    loglama.kur("deneme", tmp_path, saklama_gun=1, azami_mb=1, konsol=False)
    satir = "x" * 1000
    for _ in range(2600):
        logger.info(satir)
    logger.complete()
    logger.remove()
    dosyalar = list(tmp_path.iterdir())
    assert any(f.suffix == ".zip" for f in dosyalar), dosyalar                  # dönüşen dosya sıkıştırıldı
    assert all(f.stat().st_size <= 1024 * 1024 + 4096 for f in dosyalar if f.suffix == ".log")
    assert not eski.exists()                                                    # saklama süresinden eski silindi



def test_olay_satiri_tur_adli_alani_kabul_eder(tmp_path):
    """Saha provası 2026-10-01: olay(tur, **alanlar) imzası 'tur=' alanıyla çakışıp TypeError veriyordu; TEKRAR ve
    KAYITSIZ_KAPALI olay satırları yazılmıyor, teslim turu yarıda kalıyordu."""
    from loguru import logger
    from cekirdek import loglama
    loglama.kur("olay", tmp_path, konsol=False)
    loglama.olay("TEKRAR", ad="F_1.csv", tur="GECICI", deneme=2)
    loglama.olay("KAYITSIZ_KAPALI", ad="F_2.csv", tur="HEDEF")
    logger.complete()
    logger.remove()
    metin = "".join(f.read_text(encoding="utf-8") for f in tmp_path.glob("olay_*.log"))
    assert "EVENT | TEKRAR | ad=F_1.csv tur=GECICI deneme=2" in metin
    assert "EVENT | KAYITSIZ_KAPALI | ad=F_2.csv tur=HEDEF" in metin
