"""Adım 6 testleri: kalıcı durum + haftalık bakım (I1). G1/G2 kalıcılığı test_adim2_5_tarama.py'de."""
import json
import time
from datetime import datetime

from cekirdek.ayarlar import Ayarlar
from cekirdek.bakim import Bakim, son_planli_zaman, sonraki_planli_zaman
from cekirdek.db_canli import CanliDB
from cekirdek.db_hata import HataDB
from testler.conftest import HIZLI_TARAMA, TARAMA_EKLENTISI


def test_bakim_zamani_hesabi():
    # 2026-10-03 Cumartesi
    assert son_planli_zaman(datetime(2026, 10, 3, 2, 59), "Cumartesi", "03:00") == datetime(2026, 9, 26, 3, 0)
    assert son_planli_zaman(datetime(2026, 10, 3, 3, 0), "Cumartesi", "03:00") == datetime(2026, 10, 3, 3, 0)
    assert son_planli_zaman(datetime(2026, 10, 5, 12, 0), "Cumartesi", "03:00") == datetime(2026, 10, 3, 3, 0)
    assert sonraki_planli_zaman(datetime(2026, 9, 29, 18, 0), "Cumartesi", "03:00") == datetime(2026, 10, 3, 3, 0)
    assert son_planli_zaman(datetime(2026, 9, 29, 18, 0), "Salı", "17:30") == datetime(2026, 9, 29, 17, 30)


def test_bakim_kacirilirsa_telafi_edilir_ve_bir_kez_calisir(tmp_path):
    db, hdb = CanliDB(tmp_path / "c.db").sema_kur(), HataDB(tmp_path / "h.db").sema_kur()
    assert db.pragma("auto_vacuum") == 2 and hdb.pragma("auto_vacuum") == 2   # INCREMENTAL
    a = Ayarlar(db)
    a.degistir("bakim_gunu", "Cumartesi")
    b = Bakim(db, hdb, a)
    pazartesi = datetime(2026, 10, 5, 9, 0).timestamp()          # makine Cumartesi 03:00'te kapalıydı
    db.meta_yaz("son_bakim", datetime(2026, 9, 27, 3, 0).timestamp())
    assert b.zamani_geldi_mi(pazartesi) is True                   # kaçırılan bakım telafi edilir
    db.meta_yaz("son_bakim", datetime(2026, 10, 3, 3, 1).timestamp())
    assert b.zamani_geldi_mi(pazartesi) is False                  # bu hafta yapılmış
    sonuc = b.calistir("test")
    assert sonuc["durum"] == "TAMAM" and "canli" in sonuc and "hata" in sonuc
    assert hdb.tek("SELECT islem, kullanici FROM denetim ORDER BY id DESC LIMIT 1")[:] == ("BAKIM", "test")


def test_calisirken_bakim_komutu_tarama_kayipsiz_surer(ortam_yap, tmp_path):
    """I1: önyüzden 'şimdi bakım yap' (BAKIM_YAP) tarama sürerken çalışır; dosyalar kayıpsız tetiklenir."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    d = tmp_path / "gelen"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    o.kural_kur(dizin_id, r".*\.csv")
    o.cekirdek_baslat()
    o.bekle(lambda: (s := o.eklenti("tarama")) and s["durum"] == "CALISIYOR")
    o.bekle(lambda: o.db.meta_al("son_bakim"), mesaj="ilk açılış bakımı yapılmadı")   # hiç bakım yoksa açılışta
    ilk = float(o.db.meta_al("son_bakim"))
    for i in range(30):
        (d / f"b{i:02d}.csv").write_text(str(i), encoding="utf-8")
        if i == 10:
            o.db.komut_gonder("cekirdek", "BAKIM_YAP", kullanici="deniz")
        time.sleep(0.05)
    o.bekle(lambda: float(o.db.meta_al("son_bakim") or 0) > ilk, mesaj="komutla bakım yapılmadı")
    sonuc = json.loads(o.db.meta_al("son_bakim_sonucu"))
    assert sonuc["durum"] == "TAMAM" and sonuc["kullanici"] == "deniz"
    o.bekle(lambda: len(o.tetikler()) >= 30, zaman_asimi=30)
    time.sleep(1)
    assert sorted(t["dosya_adi"] for t in o.tetikler()) == [f"b{i:02d}.csv" for i in range(30)]
    assert o.proc.poll() is None


def _bakim_ortami(tmp_path, bitmis=300):
    db, hdb = CanliDB(tmp_path / "veri" / "canli.db").sema_kur(), HataDB(tmp_path / "veri" / "hata.db").sema_kur()
    simdi = time.time()
    with db.yaz() as c:
        c.executemany("INSERT INTO tetik(dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi, tam_yol, durum, "
                      "olusturma, kapanis) VALUES(?,1,1,?,'{}',?,'x','ILETILDI',?,?)",
                      [(i, f"i{i}", f"f{i}.csv", simdi - i, simdi - i) for i in range(bitmis)])
    return db, hdb, Bakim(db, hdb, Ayarlar(db))


def test_bakim_adimi_hata_verirse_o_adim_geri_alinir_kalanlar_yapilmaz(tmp_path, monkeypatch):
    """Kullanıcı isteği 2026-09-30: bakım hata verirse son çalışan hâle dönülür, sistem sekteye uğramaz.
    Budama adımı (300 → 200) silme yaptıktan SONRA hata verir → işlem geri alınır: 300 satır yerinde; sonraki adımlar
    (REINDEX, checkpoint) çalıştırılmaz; son kontrol sağlam; alarm 'geri alındı' der; sağlam kopya alınmıştır."""
    db, hdb, b = _bakim_ortami(tmp_path)
    monkeypatch.setenv("FWP_TEST_BAKIM_HATA", "budama_canli")
    s = b.calistir("test")
    assert db.tek("SELECT COUNT(*) FROM tetik")[0] == 300                       # silme geri alındı
    assert s["durum"] == "HATA" and s["geri_alinan"] == "Budama: canli.db" and s["son_kontrol"] == "SAGLAM"
    assert s["sistem_etkilenmedi"] is True
    assert [(a["adim"], a["durum"]) for a in s["adimlar"]] == [("on_kontrol", "TAMAM"), ("yedek", "TAMAM"),
                                                                ("budama_canli", "GERI_ALINDI")]
    a = db.tek("SELECT * FROM alarm WHERE anahtar='bakim:hata' AND aktif=1")
    assert a["seviye"] == "UYARI" and "geri alındı" in a["mesaj"] and "izleme etkilenmedi" in a["mesaj"]
    yedek = tmp_path / "veri" / "yedek" / "canli.db"
    import sqlite3
    ro = sqlite3.connect(f"file:{yedek.as_posix()}?mode=ro", uri=True)
    assert ro.execute("SELECT COUNT(*) FROM tetik").fetchone()[0] == 300
    ro.close()
    assert db.meta_al("bakim_suruyor") == ""
    monkeypatch.delenv("FWP_TEST_BAKIM_HATA")                                    # sonraki bakım başarılı
    s = b.calistir("test")
    assert s["durum"] == "TAMAM" and db.tek("SELECT COUNT(*) FROM tetik")[0] == 200
    assert db.tek("SELECT 1 FROM alarm WHERE anahtar='bakim:hata' AND aktif=1") is None
    assert (tmp_path / "veri" / "yedek" / "canli.onceki.db").exists()             # önceki sağlam kopya da saklanır


def test_yedek_dosyasi_aciksa_bakim_yine_de_yapilir(tmp_path):
    """Önceki yedek başka bir programda açık (kilitli) olsa da bakım durmaz: yeni kopya zaman damgalı ada yazılır."""
    db, hdb, b = _bakim_ortami(tmp_path)
    assert b.calistir("test")["durum"] == "TAMAM"
    kilit = open(tmp_path / "veri" / "yedek" / "canli.db", "rb")            # görüntüleyici / antivirüs gibi
    try:
        s = b.calistir("test")
    finally:
        kilit.close()
    assert s["durum"] == "TAMAM" and s["yedek"]["canli"]["not"] and ".2" in s["yedek"]["canli"]["yol"]


def test_bakim_reindex_hatasi_yalniz_o_adimi_geri_alir(tmp_path, monkeypatch):
    """REINDEX + ANALYZE adımı hata verirse yalnızca o adım geri alınır; daha önce biten budama geçerli kalır."""
    db, hdb, b = _bakim_ortami(tmp_path)
    monkeypatch.setenv("FWP_TEST_BAKIM_HATA", "reindex_canli")
    s = b.calistir("test")
    assert s["geri_alinan"] == "REINDEX + ANALYZE: canli.db" and s["son_kontrol"] == "SAGLAM"
    assert db.tek("SELECT COUNT(*) FROM tetik")[0] == 200                       # budama tamamlanmış adımdı
    assert db.tek("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'")[0] == 0   # ANALYZE geri alındı
    assert [a["adim"] for a in s["adimlar"]][-1] == "reindex_canli"


def test_bozuk_veritabaninda_bakim_baslamaz_saglam_kopya_ezilmez(tmp_path, monkeypatch):
    """Ön kontrol başarısızsa hiçbir adım yapılmaz ve önceki sağlam kopyanın üstüne bozuk kopya yazılmaz; KRİTİK alarm."""
    db, hdb, b = _bakim_ortami(tmp_path)
    assert b.calistir("test")["durum"] == "TAMAM"
    yedek = tmp_path / "veri" / "yedek" / "canli.db"
    zaman = yedek.stat().st_mtime_ns
    monkeypatch.setenv("FWP_TEST_BAKIM_HATA", "on_kontrol")
    s = b.calistir("test")
    assert s["durum"] == "HATA" and [a["durum"] for a in s["adimlar"]] == ["ATLANDI_BOZUK"]
    assert yedek.stat().st_mtime_ns == zaman
    assert db.tek("SELECT seviye FROM alarm WHERE anahtar='bakim:hata' AND aktif=1")[0] == "KRITIK"


def test_bakim_hata_verirken_izleme_surer(ortam_yap, tmp_path, monkeypatch):
    """Canlı sistem: bakım hata verse de tarama ve tetikleme kesilmeden sürer; çekirdek ayakta."""
    monkeypatch.setenv("FWP_TEST_BAKIM_HATA", "reindex_canli")          # çekirdek süreci bu ortamı devralır
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    d = tmp_path / "gelen"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    o.kural_kur(dizin_id, r".*\.csv")
    o.cekirdek_baslat()
    o.bekle(lambda: (s := o.eklenti("tarama")) and s["durum"] == "CALISIYOR")
    o.bekle(lambda: o.db.meta_al("son_bakim"))
    ilk = float(o.db.meta_al("son_bakim"))
    o.db.komut_gonder("cekirdek", "BAKIM_YAP", kullanici="deniz")
    for i in range(10):
        (d / f"h{i}.csv").write_text(str(i), encoding="utf-8")
        time.sleep(0.05)
    o.bekle(lambda: float(o.db.meta_al("son_bakim") or 0) > ilk)
    s = json.loads(o.db.meta_al("son_bakim_sonucu"))
    assert s["durum"] == "HATA" and s["sistem_etkilenmedi"] is True and s["kullanici"] == "deniz"
    o.bekle(lambda: len(o.tetikler()) >= 10, zaman_asimi=30)
    assert o.proc.poll() is None and o.eklenti("tarama")["durum"] == "CALISIYOR"
