"""Sağlamlık testleri: gerçek SMB yolu, ağ gecikmesi, patlama, kapanış/yeniden başlama anında yolda olan işler.

SMB: izlenen dizin \\\\localhost\\C$\\... (Windows yönetim paylaşımı) üzerinden okunur; yazıcı dosyayı yerel yoldan
yazar. Böylece EFT'nin sunucuda yazıp bizim ağ üzerinden okuduğumuz durum (SMB istemci önbelleği, paylaşım
kilitlerinin ağ üzerinden görünmesi) gerçek SMB yığınıyla denenir. Paylaşım yoksa SMB testleri atlanır.
Olay tablosu karşılıkları her testin açıklamasında yazılıdır.
"""
import json
import os
import time
from pathlib import Path

import pytest

from cekirdek import win
from cekirdek.kimlik import icerik_hash
from testler.conftest import HIZLI_TARAMA, TARAMA_EKLENTISI, Yazici
from testler.test_adim7_teslim import (EKLENTILER, HIZLI_TESLIM, cift_yok, durum_bekle, hepsi_durumda, kur,
                                       sahte, tetik, yaz)  # noqa: F401  (sahte: pytest fikstürü)


def unc(yol: Path) -> str:
    """C:\\a\\b → \\\\localhost\\C$\\a\\b"""
    s = str(Path(yol).resolve())
    return rf"\\localhost\{s[0]}$" + s[2:]


def smb_var(tmp_path) -> bool:
    try:
        return os.path.isdir(unc(tmp_path))
    except OSError:
        return False


def tarama_hazir(o):
    return o.bekle(lambda: (s := o.eklenti("tarama")) and s["durum"] == "CALISIYOR"
                   and json.loads(s["bilgi"] or "{}").get("dizinler"), mesaj="tarama hazır değil")


def smb_ortami(ortam_yap, tmp_path, **ayarlar):
    if not smb_var(tmp_path):
        pytest.skip("\\\\localhost\\C$ yönetim paylaşımına erişilemiyor")
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar={**HIZLI_TARAMA, **ayarlar})
    yerel = tmp_path / "ftp_gelen"
    yerel.mkdir()
    dizin_id = o.yap.dizin_ekle(unc(yerel), "TETIKLE", uzantilar=".csv", kullanici="test")
    o.kural_kur(dizin_id, r".*\.csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    return o, yerel


# ================================================================ SMB (B7, F4, B1, B3)
def test_smb_yazilmakta_olan_dosya_tamamlanmadan_tetiklenmez(ortam_yap, tmp_path):
    """B7 (P0) + B1 + B3, gerçek SMB yolu: dosya sunucuda (yerel yoldan) tutamaç açık parça parça yazılır, arada
    W'dan uzun durur. Ağdan bakan izleyici dosya tamamlanana kadar kayıt açmaz ve tetiklemez; kapanınca tek tetik,
    hash sunucudaki son içerikle aynı."""
    o, yerel = smb_ortami(ortam_yap, tmp_path)
    y = Yazici(yerel / "buyuk.csv")
    durumlar = set()
    for i in range(12):
        y.yaz(os.urandom(150_000))
        time.sleep(2.5 if i == 5 else 0.4)                   # i=5: W (1 sn) üstü duraklama, tutamaç açık
        s = o.yukleme("buyuk.csv")
        if s:
            durumlar.add(s["durum"])
        assert o.tetikler("buyuk.csv") == [], f"yazılırken tetiklendi (tur {i})"
        assert o.db.tek("SELECT COUNT(*) FROM dosya WHERE dosya_adi='buyuk.csv'")[0] == 0
    assert "KILITLI" in durumlar, durumlar           # duraklamada boyut sabit görünse de ağdan kilit görüldü
    y.kapat()
    o.bekle(lambda: len(o.tetikler("buyuk.csv")) >= 1, zaman_asimi=20, mesaj="kapanınca tetik oluşmadı")
    time.sleep(2)
    assert len(o.tetikler("buyuk.csv")) == 1
    ds = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='buyuk.csv'")
    assert ds["boyut"] == 12 * 150_000 and ds["icerik_hash"] == icerik_hash(str(yerel / "buyuk.csv"))[0]


def test_bayat_boyut_bilgisi_hash_ile_yakalanir(tmp_path):
    """B7 ikinci güvence: SMB önbelleği eski (küçük) boyut gösterse bile hash okunan bayt sayısıyla doğrulanır;
    uyuşmazsa DosyaDegisti (tetik yok, sonraki turda yeniden denenir). Önbellek gecikme yaratır, yanlış tetik değil."""
    from cekirdek.kimlik import DosyaDegisti, dogrulanmis_hash
    f = tmp_path / "bayat.csv"
    f.write_bytes(b"x" * 5000)
    st = os.stat(f)
    with pytest.raises(DosyaDegisti):
        dogrulanmis_hash(str(f), 4096, st.st_mtime_ns)                             # önbellekteki eski boyut
    with pytest.raises(DosyaDegisti):
        dogrulanmis_hash(str(f), 5000, st.st_mtime_ns - 1)                         # önbellekteki eski tarih
    assert dogrulanmis_hash(str(f), 5000, st.st_mtime_ns)[0] == icerik_hash(str(f))[0]


def test_smb_icerik_ya_da_tarih_degisimi_tetik_degil(ortam_yap, tmp_path):
    """D9 / B5 (SMB, kullanıcı kararı 2026-09-30): tetiklenmiş dosyanın yalnızca tarihi ya da içeriği değişirse tetik
    yok; içerik değiştiyse güncel hash esas alınır (önbellek eski boyut/tarih gösterse bile gerçek içerikten)."""
    o, yerel = smb_ortami(ortam_yap, tmp_path)
    (yerel / "a.csv").write_bytes(b"1;2;3")
    o.bekle(lambda: len(o.tetikler("a.csv")) == 1)
    time.sleep(1.5)
    os.utime(yerel / "a.csv", (time.time() + 60, time.time() + 60))            # yalnızca tarih
    time.sleep(3)
    assert len(o.tetikler("a.csv")) == 1
    (yerel / "a.csv").write_bytes(b"1;2;4")                                       # aynı boyut, farklı içerik
    ds = o.bekle(lambda: (r := o.db.tek("SELECT * FROM dosya WHERE dosya_adi='a.csv'")) and r["icerik_degisim"] == 1
                 and r, zaman_asimi=20, mesaj="içerik değişimi kaydedilmedi")
    assert ds["icerik_hash"] == icerik_hash(str(yerel / "a.csv"))[0]
    time.sleep(2)
    assert len(o.tetikler("a.csv")) == 1


def test_smb_listeleme_gecikmesi_olculur(tmp_path):
    """F4: SMB istemcisinin dizin listesinde yeni dosyayı ve büyüyen boyutu ne kadar geç gösterdiği ölçülür.
    Sonuç raporlanır (testin kendisi yalnızca 'eninde sonunda görünür' ve 'gerçek stat güncel' şartını arar)."""
    if not smb_var(tmp_path):
        pytest.skip("SMB yok")
    yerel = tmp_path / "olcum"
    yerel.mkdir()
    ag = unc(yerel)
    os.listdir(ag)                                                                # önbelleği ısıt
    gecikmeler = []
    for i in range(5):
        t0 = time.perf_counter()
        (yerel / f"o{i}.csv").write_bytes(b"x")
        while f"o{i}.csv" not in os.listdir(ag):
            assert time.perf_counter() - t0 < 30, "SMB listesi 30 sn'de güncellenmedi"
            time.sleep(0.05)
        gecikmeler.append(time.perf_counter() - t0)
    y = Yazici(yerel / "buyuyen.csv")
    y.yaz(b"a" * 1000)
    time.sleep(0.3)
    y.yaz(b"a" * 99_000)
    liste_boyutu = next(e.stat().st_size for e in os.scandir(ag) if e.name == "buyuyen.csv")
    gercek = os.stat(os.path.join(ag, "buyuyen.csv")).st_size
    y.kapat()
    print(f"\nF4 ölçümü: yeni dosyanın SMB listesinde görünme süresi (sn): "
          f"{', '.join(f'{g:.2f}' for g in gecikmeler)} | büyüyen dosya: liste boyutu={liste_boyutu}, "
          f"gerçek stat={gercek}")
    (tmp_path / "f4_olcum.json").write_text(json.dumps({"gecikme_sn": gecikmeler, "liste_boyutu": liste_boyutu,
                                                        "gercek_stat": gercek}), encoding="utf-8")
    assert gercek == 100_000


def test_uzun_unc_yolu(ortam_yap, tmp_path):
    """D6: 260 karakteri aşan UNC yolundaki dizin izlenir; dosya tetiklenir."""
    if not smb_var(tmp_path):
        pytest.skip("SMB yok")
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    derin = tmp_path
    while len(unc(derin)) < 300:
        derin = derin / "uzun_klasör_adı_çğıöşü_0123456789"
    os.makedirs("\\\\?\\" + str(derin))
    ag = unc(derin)
    assert len(ag) > 260
    dizin_id = o.yap.dizin_ekle(ag, "TETIKLE", uzantilar=".csv", kullanici="test")
    o.kural_kur(dizin_id, r".*\.csv")
    o.cekirdek_baslat()
    tarama_hazir(o)
    with open("\\\\?\\" + str(derin / "uzun_yol.csv"), "wb") as f:
        f.write(b"veri")
    o.bekle(lambda: len(o.tetikler("uzun_yol.csv")) == 1, zaman_asimi=20, mesaj="uzun yoldaki dosya tetiklenmedi")
    ds = o.db.tek("SELECT * FROM dosya WHERE dosya_adi='uzun_yol.csv'")
    assert ds["icerik_hash"] and ds["boyut"] == 4
    assert o.db.tek("SELECT erisim_durumu FROM dizin WHERE id=?", (dizin_id,))[0] == "ERISILEBILIR"


def test_buyuk_dizin_temel_alinirken_yeni_dosya_bekletilmez(ortam_yap, tmp_path):
    """G3 + SLA (optimizasyon): 8 000 dosyalık dizin SMB'den TEMEL_AL ile eklenir; temel alma sürerken gelen yeni
    dosya temel alma bitmeden tetiklenir. Duran dosyalar tetiklenmez ve 'yükleniyor' diye görünmez."""
    if not smb_var(tmp_path):
        pytest.skip("SMB yok")
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    yerel = tmp_path / "birikmis"
    yerel.mkdir()
    eski = time.time() - 3600
    for i in range(8000):
        f = yerel / f"ESKI_{i:05d}.csv"
        f.write_bytes(f"{i}".encode())
        os.utime(f, (eski, eski))
    dizin_id = o.yap.dizin_ekle(unc(yerel), "TEMEL_AL", uzantilar=".csv", kullanici="test")
    o.kural_kur(dizin_id, r".*\.csv")
    o.cekirdek_baslat()
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM dosya WHERE durum='TEMEL'")[0] >= 20, zaman_asimi=60,
            mesaj="temel alma başlamadı")
    en_cok_yukleme = 0
    (yerel / "YENI.csv").write_bytes(b"yeni")
    t0 = time.time()
    while not o.tetikler("YENI.csv"):
        en_cok_yukleme = max(en_cok_yukleme, o.db.tek("SELECT COUNT(*) FROM yukleme")[0])
        assert time.time() - t0 < 20, "temel alma sürerken yeni dosya bekletildi"
        time.sleep(0.1)
    gecikme = time.time() - t0
    temel_o_an = o.db.tek("SELECT COUNT(*) FROM dosya WHERE durum='TEMEL'")[0]
    assert o.db.tek("SELECT ilk_tarama_yapildi FROM dizin WHERE id=?", (dizin_id,))[0] == 0, \
        "temel alma yeni dosyadan önce bitti; test anlamsız (dizini büyütün)"
    assert en_cok_yukleme <= 1, f"duran dosyalar 'yükleniyor' göründü ({en_cok_yukleme})"
    o.bekle(lambda: o.db.tek("SELECT ilk_tarama_yapildi FROM dizin WHERE id=?", (dizin_id,))[0] == 1,
            zaman_asimi=300, mesaj="temel alma bitmedi")
    assert o.db.tek("SELECT COUNT(*) FROM dosya WHERE durum='TEMEL'")[0] == 8000
    assert [t["dosya_adi"] for t in o.tetikler()] == ["YENI.csv"]
    print(f"\nG3: temel alma sürerken yeni dosya {gecikme:.1f} sn'de tetiklendi (o an {temel_o_an}/8000 temel "
          f"alınmıştı; tüm temel alma {time.time() - t0:.0f} sn daha sürdü)")


# ================================================================ patlama (H8, C1)
def test_patlama_300_dosya_kayipsiz_ve_cift_yok(ortam_yap, tmp_path, sahte):
    """H8: aynı anda 300 dosya → 300 ayrı tetik, hepsi Control-M'e tam bir kez gider; kayıp ve çift yok."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte)
    adlar = [f"P_{20260000 + i:08d}.csv" for i in range(300)]
    t0 = time.time()
    for a in adlar:
        (d / a).write_bytes(a.encode())
    hepsi_durumda(o, adlar, "ILETILDI", zaman_asimi=90)
    sure = time.time() - t0
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])
    assert len(sahte.siparisler) == 300
    assert o.db.tek("SELECT COUNT(*) FROM tetik")[0] == 300
    sla = o.db.oku("SELECT sure_ms FROM tetik WHERE durum='ILETILDI'")
    print(f"\nH8: 300 dosya {sure:.1f} sn'de iletildi; en uzun geliş→iletim {max(r[0] for r in sla)} ms")


# ================================================================ kapanış ve yeniden başlama (U4, H10, U8)
def test_duzgun_kapanista_yoldaki_cagri_kesilmez(ortam_yap, tmp_path, sahte):
    """U4 / H10: Control-M yavaşken (3 sn) çağrı yoldayken izleyici düzgün kapatılır → çağrı yarıda kesilmez,
    sonucu (ILETILDI) kaydedilir; kapanırken bekleyen tetik kaybolmaz, açılışta gönderilir; çift yok."""
    o, d, *_ = kur(ortam_yap, tmp_path, sahte, ayarlar={"cagri_timeout_sn": 10})
    sahte.mod_ayarla("yavas", gecikme=3)
    yaz(d, "Y_20260101.csv")
    durum_bekle(o, "Y_20260101.csv", "DENENIYOR")
    o.cekirdek_kapat()
    assert tetik(o, "Y_20260101.csv")["durum"] == "ILETILDI"
    assert tetik(o, "Y_20260101.csv")["belirsiz"] == 0
    sahte.mod_ayarla("normal")
    yaz(d, "Y_20260102.csv")                                                     # kapalıyken gelir
    o.cekirdek_baslat()
    durum_bekle(o, "Y_20260102.csv", "ILETILDI")
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in ("Y_20260101.csv", "Y_20260102.csv")])


def test_erit_sirasinda_yeniden_baslama_kaldigi_yerden_devam(ortam_yap, tmp_path, sahte):
    """U8: kademeli erit sürerken izleyici yeniden başlatılır → lokal kayıtlar diskte kalır, erit kaldığı yerden
    devam eder, her kayıt tam bir kez gider (düzgün kapanışta yoldaki çağrı bitirilir, çift yok)."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, ayarlar={"erit_hizi": 3})
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    adlar = [f"E_202601{i:02d}.csv" for i in range(1, 21)]
    for a in adlar:
        yaz(d, a)
        time.sleep(0.03)
    hepsi_durumda(o, adlar, "LOKALDE")
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.yap.erit_baslat(hedef_id, hiz=3, kullanici="test")
    o.bekle(lambda: 3 <= len(sahte.siparisler) <= 12, mesaj="erit başlamadı")
    o.cekirdek_kapat()
    gonderilen = len(sahte.siparisler)
    assert gonderilen < 20
    assert all(Path(t["lokal_dosya"]).exists() for t in (tetik(o, a) for a in adlar) if t["durum"] == "LOKALDE")
    o.cekirdek_baslat()
    hepsi_durumda(o, adlar, "ILETILDI", zaman_asimi=40)
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])
    gelen = [next(v["FWP_DOSYA"] for v in s["govde"]["variables"] if "FWP_DOSYA" in v) for s in sahte.siparisler]
    assert gelen == adlar                                                        # sıra bozulmadı


def test_erit_sirasinda_cekirdek_oldurulur_kayip_yok(ortam_yap, tmp_path, sahte):
    """U8 + G4 (sert): erit sürerken çekirdek öldürülür (Job Object eklentileri de kapatır) → açılışta yarım kalan
    erit kayıtları lokale döner, erit devam eder; hiçbiri kaybolmaz. Çift yalnızca 'belirsiz' işaretlilerde olabilir."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte, ayarlar={"erit_hizi": 4})
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    adlar = [f"K_202602{i:02d}.csv" for i in range(1, 16)]
    for a in adlar:
        yaz(d, a)
        time.sleep(0.03)
    hepsi_durumda(o, adlar, "LOKALDE")
    sahte.mod_ayarla("yavas", gecikme=0.5)
    o.yap.hedef_ac(hedef_id, kullanici="test")
    o.yap.erit_baslat(hedef_id, hiz=4, kullanici="test")
    o.bekle(lambda: len(sahte.istekler) >= 4, mesaj="erit başlamadı")
    o.proc.kill()
    o.proc.wait(10)
    o.bekle(lambda: not any(win.surec_canli(o.eklenti(a)["pid"]) for a in ("tarama", "teslim") if o.eklenti(a)["pid"]),
            mesaj="eklentiler çekirdekle kapanmadı")
    sahte.mod_ayarla("normal")
    o.cekirdek_baslat()
    hepsi_durumda(o, adlar, "ILETILDI", zaman_asimi=40)
    say = sahte.idempotency_sayilari()
    for a in adlar:
        t = tetik(o, a)
        assert say[t["idempotency"]] >= 1, f"{a} kayboldu"
        if say[t["idempotency"]] > 1:
            assert t["belirsiz"] == 1, f"{a} işaretsiz çift gitti"


def test_erit_varis_sirasi_dalgali_gecikmede_korunur(ortam_yap, tmp_path, sahte):
    """U6 / S1: Control-M'in yanıt süresi dalgalıyken (0–150 ms) erit edilen kayıtlar Control-M'e geliş sırasıyla
    VARIR (aynı anda tek erit çağrısı); hız sınırı yine uygulanır ve canlı olmayan kayıt atlanmaz."""
    o, d, _, hedef_id, _ = kur(ortam_yap, tmp_path, sahte)
    o.yap.hedef_kapat(hedef_id, "KAYITLI", kullanici="test")
    adlar = [f"S_202603{i:02d}.csv" for i in range(1, 21)]
    for a in adlar:
        yaz(d, a)
        time.sleep(0.03)
    hepsi_durumda(o, adlar, "LOKALDE")
    sahte.mod_ayarla("titrek", gecikme=0.15)
    o.yap.hedef_ac(hedef_id, kullanici="test")
    t0 = time.time()
    o.yap.erit_baslat(hedef_id, hiz=50, kullanici="test")
    hepsi_durumda(o, adlar, "ILETILDI", zaman_asimi=40)
    sure = time.time() - t0
    gelen = [next(v["FWP_DOSYA"] for v in x["govde"]["variables"] if "FWP_DOSYA" in v) for x in sahte.siparisler]
    assert gelen == adlar, gelen
    cift_yok(sahte, [tetik(o, a)["idempotency"] for a in adlar])
    print(f"\nU6: 20 kayıt dalgalı gecikmeyle sıralı eritildi: {sure:.1f} sn")


# ================================================================ eşzamanlı ayar (U12)
def test_iki_kisi_ayni_anda_ayar_degistirir(ortam_yap):
    """U12: iki kullanıcı aynı anda farklı ayarları değiştirir → ikisi de sırayla uygulanır, ayar sürümü her
    değişiklikte artar, son durum ikisini de içerir, denetimde iki kayıt var."""
    import threading
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    o.cekirdek_baslat()
    o.bekle(lambda: (e := o.eklenti("tarama")) and e["durum"] == "CALISIYOR")
    surum0 = int(o.db.meta_al("ayar_surumu", "0"))
    hatalar = []

    def degistir(k, v, kim):
        try:
            for i in range(20):
                o.db.ayar_yaz(k, v + i)
                o.hdb.denetim_yaz("AYAR_DEGISTIR", k, yeni=v + i, kullanici=kim, kaynak="test")
        except Exception as e:
            hatalar.append(e)

    t1 = threading.Thread(target=degistir, args=("gecmis_limit", 300, "ali"))
    t2 = threading.Thread(target=degistir, args=("hata_limit", 2000, "ayse"))
    t1.start(); t2.start(); t1.join(); t2.join()                                    # noqa: E702
    assert not hatalar, hatalar
    assert int(o.db.meta_al("ayar_surumu")) == surum0 + 40
    assert json.loads(o.db.tek("SELECT deger FROM ayar WHERE anahtar='gecmis_limit'")[0]) == 319
    assert json.loads(o.db.tek("SELECT deger FROM ayar WHERE anahtar='hata_limit'")[0]) == 2019
    assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='AYAR_DEGISTIR'")[0] == 40
