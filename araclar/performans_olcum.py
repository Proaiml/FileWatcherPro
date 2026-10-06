"""Performans ölçümü (optimizasyon aşaması): en kötü durum hacminde sorgular, durum özeti, hash hızı, dizin
listeleme maliyeti. Canlı sisteme dokunmaz; her şeyi geçici klasörde üretir.

    py -3.11 araclar\\performans_olcum.py [--bolum db,hash,liste] [--etiket once|sonra]

Sonuç ekrana ve testler\\_sonuc\\performans_<etiket>.json dosyasına yazılır (PROJE_DOSYALARI 'Performans' sayfası).
Hacim (bilerek abartılı): dizinde duran 50 000 dosya, uzun kesintide lokalde biriken 10 000 tetik, 10 000 çözülmemiş
gönderilemeyen kaydı, 5 000 denetim satırı, budanmayı bekleyen 5 000 bitmiş tetik.
"""
import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from cekirdek.ayarlar import Ayarlar  # noqa: E402
from cekirdek.db_canli import CanliDB  # noqa: E402
from cekirdek.db_hata import HataDB  # noqa: E402
from cekirdek.kimlik import icerik_hash  # noqa: E402

N_DOSYA, N_LOKAL, N_GON, N_DENETIM, N_BITMIS = 50_000, 10_000, 10_000, 5_000, 5_000
SONUC = {}


def olc(fn, n=30):
    fn()                                   # ısınma
    s = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        s.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(s), 2), round(max(s), 2)


def plan(con, sql, par):
    return " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, par).fetchall())


# ================================================================ veritabanı
def db_kur(klasor: Path):
    db, hdb = CanliDB(klasor / "canli.db").sema_kur(), HataDB(klasor / "hata.db").sema_kur()
    simdi = time.time()
    with db.yaz() as c:
        c.execute("INSERT INTO hedef(id, ad, adres, tur, ayrintilar, aktif, olusturma, guncelleme) "
                  "VALUES(1,'controlm','http://x','CONTROLM','{}',1,?,?)", (simdi, simdi))
        c.execute("INSERT INTO dizin(id, yol, ad, uzantilar, ilk_kurulum_modu, aktif, olusturma, guncelleme) "
                  "VALUES(1,'\\\\sunucu\\gelen','gelen','.csv','TEMEL_AL',1,?,?)", (simdi, simdi))
        c.execute("INSERT INTO kural(id, dizin_id, sira, ad, regex, harf_duyarsiz, hedef_id, olusturma, guncelleme) "
                  "VALUES(1,1,100,'fatura','.*',1,1,?,?)", (simdi, simdi))
        c.executemany("INSERT INTO dosya(dizin_id, dosya_adi, ad_anahtar, tam_yol, boyut, mtime_ns, kimlik, icerik_hash, "
                      "durum, kural_id, ilk_gorulme, hazir_zamani, kalkma_zamani) VALUES(1,?,?,?,1000,1,?,?,'HAZIR',1,?,?,?)",
                      [(f"F_{i:06d}.csv", f"f_{i:06d}.csv", f"\\\\sunucu\\gelen\\F_{i:06d}.csv", f"k{i}", f"h{i}",
                        simdi - N_DOSYA + i, simdi - N_DOSYA + i, None if i < N_DOSYA else simdi - 1)
                       for i in range(N_DOSYA + 200)])
        durumlar = (["LOKALDE"] * N_LOKAL + ["ILETILDI"] * (200 + N_BITMIS) + ["BEKLIYOR"] * 50)
        c.executemany("INSERT INTO tetik(dosya_id, kural_id, hedef_id, idempotency, parametreler, dosya_adi, tam_yol, "
                      "durum, olusturma, sonraki_deneme, iletildi_zamani, sure_ms, kapanis) VALUES(?,1,1,?,'{}',?,?,?,?,?,?,?,?)",
                      [(i + 1, f"i{i}", f"F_{i:06d}.csv", "x", d, simdi - 20000 + i, simdi,
                        simdi - 20000 + i + 1 if d == "ILETILDI" else None, 120 if d == "ILETILDI" else None,
                        simdi - 20000 + i + 1 if d == "ILETILDI" else None) for i, d in enumerate(durumlar)])
    with hdb.yaz() as c:
        c.executemany("INSERT INTO gonderilemeyen(anahtar, tetik_id, dosya_adi, tam_yol, sebep, sebep_detay, "
                      "hedef_ad, deneme_sayisi, ilk_zaman, son_zaman, cozuldu) VALUES(?,?,?,?,?,?,'controlm',3,?,?,?)",
                      [(f"a{i}", i, f"F_{i:06d}.csv", "x", "SLA_SON_DOLDU", "deneme planı bitti", simdi - i, simdi - i,
                        1 if i >= N_GON else 0) for i in range(N_GON + 1000)])
        c.executemany("INSERT INTO denetim(zaman, kullanici, islem, nesne, kaynak) VALUES(?,?,?,?,?)",
                      [(simdi - i, "deniz", "AYAR_DEGISTIR", "x", "kontrol") for i in range(N_DENETIM)])
    return db, hdb


def db_olc(klasor: Path):
    from eklentiler.kontrol.kontrol_api import KontrolApi
    db, hdb = db_kur(klasor)
    con = db.baglanti()
    simdi = time.time()
    sorgular = {
        "teslim: kuyruk (her tur)": ("SELECT * FROM tetik WHERE durum IN (?,?) AND sonraki_deneme<=? ORDER BY olusturma LIMIT 500",
                                     ("BEKLIYOR", "TEKRAR", simdi)),
        "teslim: canlı var mı (erit, her tur)": ("SELECT 1 FROM tetik WHERE hedef_id=? AND durum=? AND sonraki_deneme<=? LIMIT 1",
                                                 (1, "BEKLIYOR", simdi)),
        "teslim: sıradaki erit kaydı": ("SELECT * FROM tetik WHERE hedef_id=? AND durum=? ORDER BY olusturma, id LIMIT 1",
                                        (1, "LOKALDE")),
        "teslim: kalan erit sayısı": ("SELECT COUNT(*) FROM tetik WHERE hedef_id=? AND durum IN (?,?)", (1, "LOKALDE", "ERITILIYOR")),
        "önyüz: Dosyalar listesi (200)": (
            "SELECT d.*, t.id tetik_id, t.durum tetik_durum, t.sure_ms FROM dosya d LEFT JOIN tetik t ON t.dosya_id=d.id "
            "LEFT JOIN kural k ON k.id=t.kural_id LEFT JOIN hedef h ON h.id=t.hedef_id WHERE 1=1 ORDER BY d.hazir_zamani DESC LIMIT ?",
            (200,)),
        "önyüz: Dosyalar arama": (
            "SELECT d.*, t.id tetik_id FROM dosya d LEFT JOIN tetik t ON t.dosya_id=d.id WHERE d.dosya_adi LIKE ? "
            "ORDER BY d.hazir_zamani DESC LIMIT ?", ("%F_0499%", 200)),
        "önyüz: lokaldekiler (1000)": ("SELECT t.* FROM tetik t WHERE t.durum=? ORDER BY t.olusturma DESC LIMIT ?", ("LOKALDE", 1000)),
        "durum: tetik sayımı": ("SELECT hedef_id, durum, COUNT(*) n FROM tetik WHERE durum IN (?,?,?,?,?) GROUP BY hedef_id, durum",
                                ("BEKLIYOR", "DENENIYOR", "TEKRAR", "LOKALDE", "ERITILIYOR")),
        "durum: aktif dosya sayımı": ("SELECT dizin_id, COUNT(*) n FROM dosya INDEXED BY ux_dosya_aktif WHERE kalkma_zamani IS NULL GROUP BY dizin_id", ()),
        "durum: SLA son 200": ("SELECT sure_ms FROM tetik WHERE durum='ILETILDI' AND sure_ms IS NOT NULL AND eritildi=0 "
                               "ORDER BY iletildi_zamani DESC LIMIT 200", ()),
    }
    sonuc = {}
    for ad, (sql, par) in sorgular.items():
        med, mx = olc(lambda: con.execute(sql, par).fetchall())
        sonuc[ad] = {"ms": med, "en_kotu_ms": mx, "plan": plan(con, sql, par)}
    hcon = hdb.baglanti()
    for ad, sql in {"durum: çözülmemiş sayısı": "SELECT COUNT(*) FROM gonderilemeyen WHERE cozuldu=0",
                    "önyüz: gönderilemeyenler (1000)": "SELECT * FROM gonderilemeyen WHERE cozuldu=0 ORDER BY son_zaman DESC LIMIT 1000"}.items():
        med, mx = olc(lambda: hcon.execute(sql).fetchall())
        sonuc[ad] = {"ms": med, "en_kotu_ms": mx, "plan": plan(hcon, sql, ())}
    ns = SimpleNamespace(db=db, hdb=hdb, ayar=Ayarlar(db))
    med, mx = olc(lambda: KontrolApi.durum(ns))
    sonuc["durum() özeti (saniyede 1)"] = {"ms": med, "en_kotu_ms": mx, "plan": "—"}
    t0 = time.perf_counter()
    budanan = db.gecmisi_buda(200)
    sonuc["budama (5 000 bitmiş tetik)"] = {"ms": round((time.perf_counter() - t0) * 1000, 1), "en_kotu_ms": None,
                                            "plan": json.dumps(budanan)}
    db.kapat()
    hdb.kapat()
    SONUC["db"] = sonuc


# ================================================================ hash
def hash_olc(klasor: Path):
    import xxhash
    sonuc = {}
    veri = os.urandom(64 * 1024 * 1024)
    for ad, f in (("xxh3_64", xxhash.xxh3_64), ("xxh3_128", xxhash.xxh3_128), ("xxh64", xxhash.xxh64)):
        med, _ = olc(lambda: f(veri).digest(), n=5)
        sonuc[f"bellekte {ad} (GB/sn)"] = round(64 / 1024 / (med / 1000), 2)
    dosya = klasor / "buyuk.bin"
    with open(dosya, "wb") as g:
        for _ in range(4):
            g.write(veri)                                   # 256 MB
    yollar = {"yerel": str(dosya)}
    s = str(dosya.resolve())
    unc = "\\\\localhost\\" + s[0] + "$" + s[2:]
    if os.path.exists(unc):
        yollar["SMB (loopback)"] = unc
    for yer, yol in yollar.items():
        for mb in (1, 4, 8, 16):
            med, _ = olc(lambda: icerik_hash(yol, parca=mb * 1024 * 1024), n=3)
            sonuc[f"{yer} 256 MB, parça {mb} MB (MB/sn)"] = round(256 / (med / 1000))
    kucuk = klasor / "kucuk.csv"
    kucuk.write_bytes(os.urandom(1024 * 1024))
    med, _ = olc(lambda: icerik_hash(str(kucuk)), n=50)
    sonuc["tipik 1 MB dosya (ms)"] = med
    SONUC["hash"] = sonuc


# ================================================================ dizin listeleme
def liste_olc(klasor: Path):
    sonuc = {}
    for n in (1_000, 20_000):
        d = klasor / f"dizin_{n}"
        d.mkdir()
        for i in range(n):
            (d / f"F_{i:06d}.csv").write_bytes(b"x")
        s = str(d.resolve())
        yollar = {"yerel": str(d)}
        unc = "\\\\localhost\\" + s[0] + "$" + s[2:]
        if os.path.exists(unc):
            yollar["SMB"] = unc

        def listele(yol):
            with os.scandir(yol) as it:
                return [(e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in it if e.is_file(follow_symlinks=False)]
        for yer, yol in yollar.items():
            med, mx = olc(lambda: listele(yol), n=10)
            sonuc[f"{yer} {n:,} dosya listeleme (ms)".replace(",", ".")] = med
    SONUC["liste"] = sonuc


# ================================================================ boşta yük (J2)
def bosta_olc(klasor: Path, sure_sn=60, n_dosya=20_000):
    """Gerçek sistem (çekirdek + tarama + teslim + kontrol), VARSAYILAN ayarlar, SMB yolundan izlenen 20 000 dosyalık
    dizin: ilk taramadan sonra süreç başına CPU ve bellek."""
    import psutil
    import subprocess
    from cekirdek.yapilandirma import Yapilandirma
    d = klasor / "izlenen"
    d.mkdir()
    eski = time.time() - 3600              # dizin eklenmeden çok önce gelmiş (TEMEL_AL: temel alınır, tetiklenmez)
    for i in range(n_dosya):
        f = d / f"F_{i:06d}.csv"
        f.write_bytes(b"x")
        os.utime(f, (eski, eski))
    s = str(d.resolve())
    unc = "\\\\localhost\\" + s[0] + "$" + s[2:]
    yol = unc if os.path.exists(unc) else str(d)
    b = klasor / "baslangic.json"
    b.write_text(json.dumps({"veri_klasoru": str(klasor / "veri"), "log_klasoru": str(klasor / "loglar"),
                             "kontrol_adres": "127.0.0.1", "kontrol_port": 0,
                             "eklentiler": [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
                                            {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"},
                                            {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"}]}), encoding="utf-8")
    (klasor / "veri").mkdir()
    db, hdb = CanliDB(klasor / "veri" / "canli.db").sema_kur(), HataDB(klasor / "veri" / "hata.db").sema_kur()
    y = Yapilandirma(db, hdb)
    hid = y.hedef_ekle("controlm", "http://127.0.0.1:9/automation-api", kullanici="olcum")
    did = y.dizin_ekle(yol, "TEMEL_AL", uzantilar=".csv", kullanici="olcum")
    y.kural_ekle(did, "hepsi", r".*\.csv", hid, kullanici="olcum")
    p = subprocess.Popen([sys.executable, str(KOK / "calistir.py"), "--baslangic", str(b)], cwd=str(KOK),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    try:
        son = time.time() + 600                # 20 000 dosyanın temel alınması (ilk kurulum) bitsin
        while time.time() < son and not (db.tek("SELECT ilk_tarama_yapildi FROM dizin WHERE id=?", (did,))[0]
                                         and all(r["durum"] == "CALISIYOR" for r in db.oku("SELECT durum FROM eklenti"))
                                         and len(db.oku("SELECT 1 FROM eklenti")) == 4):
            time.sleep(0.5)
        time.sleep(5)
        ana = psutil.Process(p.pid)
        surecler = {"cekirdek": ana}
        for r in db.oku("SELECT ad, pid FROM eklenti WHERE ad<>'cekirdek'"):
            surecler[r["ad"]] = psutil.Process(r["pid"])
        bas = {k: sum(v.cpu_times()[:2]) for k, v in surecler.items()}
        time.sleep(sure_sn)
        sonuc = {}
        for k, v in surecler.items():
            cpu = (sum(v.cpu_times()[:2]) - bas[k]) / sure_sn * 100
            sonuc[f"{k}: CPU (% tek çekirdek)"] = round(cpu, 2)
            sonuc[f"{k}: bellek (MB)"] = round(v.memory_info().rss / 1048576, 1)
        dz = db.tek("SELECT son_tarama_ms, dosya_sayisi FROM dizin WHERE id=?", (did,))
        sonuc["tarama turu süresi (ms, 20 000 dosya, SMB)"] = dz[0]
        sonuc["canli.db (MB)"] = round((klasor / "veri" / "canli.db").stat().st_size / 1048576, 2)
        sonuc["izlenen yol"] = "SMB" if yol == unc else "yerel"
    finally:
        db.komut_gonder("cekirdek", "KAPAN", kullanici="olcum")
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            p.kill()
        db.kapat()
        hdb.kapat()
    SONUC["bosta"] = sonuc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bolum", default="db,hash,liste")
    ap.add_argument("--etiket", default="olcum")
    a = ap.parse_args()
    klasor = Path(tempfile.mkdtemp(prefix="fwp_perf_"))
    try:
        for b in a.bolum.split(","):
            {"db": db_olc, "hash": hash_olc, "liste": liste_olc, "bosta": bosta_olc}[b](klasor)
    finally:
        shutil.rmtree(klasor, ignore_errors=True)
    for bolum, v in SONUC.items():
        print(f"\n== {bolum}")
        for k, x in v.items():
            if isinstance(x, dict):
                print(f"  {k:42s} {x['ms']:>9} ms (en kötü {x['en_kotu_ms']})   {x['plan'][:110]}")
            else:
                print(f"  {k:42s} {x}")
    cikti = KOK / "testler" / "_sonuc" / f"performans_{a.etiket}.json"
    cikti.parent.mkdir(exist_ok=True)
    cikti.write_text(json.dumps({"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), **SONUC}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"\nkaydedildi: {cikti}")


if __name__ == "__main__":
    main()
