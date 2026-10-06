"""Asistanın deposu (veri\\asistan.db) ve PyTorch gerektirmeyen ortak parçalar: ayarlar, olay adları, güven karnesi,
önyüz özeti. Asistan eklentisi yazar; kontrol arayüzü (API) okur, öneri geri bildirimini ve ayarları yazar.

Ayrı veritabanı: asistanın biriktirdiği olaylar ve model sürümleri canli.db'yi (hıza odaklı, arayüzü besleyen)
büyütmesin; asistan verisi silinince FileWatcherPro'nun kendi kayıtları etkilenmesin.
"""
import json
import time
from pathlib import Path

from cekirdek.db_temel import DB
from cekirdek.olaylar import KODLAR

SEMA = """
CREATE TABLE IF NOT EXISTS meta (anahtar TEXT PRIMARY KEY, deger TEXT);
CREATE TABLE IF NOT EXISTS olay (                     -- toplanan olaylar (modelin eğitim verisi)
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL, kod TEXT NOT NULL, nesne TEXT NOT NULL DEFAULT '',
  seviye TEXT, kaynak TEXT NOT NULL UNIQUE);          -- kaynak: aynı olay iki kez toplanmasın (ör. tetik:12:iletildi)
CREATE INDEX IF NOT EXISTS ix_olay_zaman ON olay(zaman, id);
CREATE TABLE IF NOT EXISTS sozluk (token TEXT PRIMARY KEY, no INTEGER NOT NULL UNIQUE);   -- olay türü → model girdisi
CREATE TABLE IF NOT EXISTS surum (                    -- her eğitim turunun sonucu
  surum INTEGER PRIMARY KEY, zaman REAL NOT NULL, olay INTEGER NOT NULL, egitim REAL, dogrulama REAL, markov REAL,
  siklik REAL, durum TEXT NOT NULL, yapi TEXT, dosya TEXT);   -- durum: KULLANIMDA | ESKI | EZBER | ANLAMSIZ
CREATE TABLE IF NOT EXISTS oneri (
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL, anahtar TEXT NOT NULL UNIQUE, tur TEXT NOT NULL, nesne TEXT,
  baslik TEXT NOT NULL, metin TEXT NOT NULL, kanit TEXT, oneri TEXT, guven REAL, kaynak TEXT NOT NULL,
  surum INTEGER, durum TEXT NOT NULL DEFAULT 'ACIK', isaretleyen TEXT, kapanma REAL);   -- ACIK | FAYDALI | FAYDASIZ | KAPANDI
CREATE INDEX IF NOT EXISTS ix_oneri_durum ON oneri(durum, zaman);
CREATE TABLE IF NOT EXISTS olcum (                    -- anomali takibi: kural başına sayısal ölçüm (dosya adı yok)
  id INTEGER PRIMARY KEY, zaman REAL NOT NULL, kural_id INTEGER, hedef_id INTEGER,
  tur TEXT NOT NULL, deger REAL NOT NULL, kaynak TEXT NOT NULL UNIQUE);   -- tur: boyut (bayt) | sure (ms, hazır → iletildi)
CREATE INDEX IF NOT EXISTS ix_olcum_kural ON olcum(kural_id, tur, id);
CREATE INDEX IF NOT EXISTS ix_olcum_zaman ON olcum(zaman);
CREATE INDEX IF NOT EXISTS ix_olcum_tur ON olcum(tur, id);
CREATE TABLE IF NOT EXISTS onceden (                  -- 'önce tahmin et, sonra öğren': gün başına görmeden tahmin başarısı
  gun TEXT PRIMARY KEY, n INTEGER NOT NULL, model INTEGER NOT NULL, markov INTEGER NOT NULL);
"""


class AsistanDB(DB):
    SEMA = SEMA


def depo_yolu(canli_db_yolu) -> Path:
    return Path(canli_db_yolu).parent / "asistan.db"


def model_klasoru(canli_db_yolu) -> Path:
    return Path(canli_db_yolu).parent / "asistan"


# ---------------------------------------------------------------- ayarlar (asistan.db > meta 'ayarlar')
AYARLAR = {  # anahtar: (varsayılan, tür, alt, üst)
    "surekli": (True, bool, None, None),
    "egitim_sikligi": (500, int, 20, 1000000),        # bu kadar yeni olayda bir eğitim turu
    "egitim_adimi": (200, int, 10, 100000),           # tur başına en fazla adım
    "egitim_sure_sn": (90.0, float, 5, 3600),         # tur başına en fazla süre
    "baglam": (64, int, 8, 256),
    "katman": (2, int, 1, 6),
    "bas": (4, int, 1, 8),
    "boyut": (64, int, 16, 256),
    "ogrenme_orani": (0.001, float, 1e-5, 0.1),
    "dropout": (0.1, float, 0.0, 0.6),
    "agirlik_azaltma": (0.01, float, 0.0, 1.0),
    "is_parcacigi": (1, int, 1, 16),
    "asgari_olay": (2000, int, 50, 10000000),         # ilk eğitim için en az olay
    "asgari_gun": (3.0, float, 0.0, 365),             # ilk eğitim için en az gün
    "saklama_gun": (90, int, 7, 3650),
    "dogrulama_orani": (0.2, float, 0.05, 0.5),       # son %20: eğitime hiç girmez (zamana göre ayrım)
    "anomali": (True, bool, None, None),               # boyut / teslim süresi / günlük adet anomali takibi (istatistik)
    "anomali_alarm": (False, bool, None, None),        # anomaliyi alarm olarak da aç (mail kurallarına gider); varsayılan gölge
    "anomali_asgari": (20, int, 5, 100000),            # bir kuralın normalini çıkarmak için en az geçmiş dosya
}
YAPI = ("baglam", "katman", "bas", "boyut")            # değişince model sıfırdan eğitilir


def ayarlar_oku(adb: AsistanDB) -> dict:
    kayitli = json.loads(adb.meta_al("ayarlar") or "{}")
    return {k: kayitli.get(k, v[0]) for k, v in AYARLAR.items()}


def ayar_dogrula(degisen: dict) -> dict:
    sonuc = {}
    for k, v in (degisen or {}).items():
        if k not in AYARLAR:
            raise ValueError(f"bilinmeyen asistan ayarı: {k}")
        _, tur, alt, ust = AYARLAR[k]
        try:
            v = bool(v) if tur is bool else tur(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k}: sayı olmalı") from None
        if tur is not bool and ((alt is not None and v < alt) or (ust is not None and v > ust)):
            raise ValueError(f"{k} {alt} ile {ust} arasında olmalı")
        sonuc[k] = v
    if "boyut" in sonuc or "bas" in sonuc:
        boyut, bas = sonuc.get("boyut"), sonuc.get("bas")
        if boyut is not None and bas is not None and boyut % bas:
            raise ValueError("boyut, dikkat başı sayısına tam bölünmeli (ör. 64 ve 4)")
    return sonuc


def ayar_yaz(adb: AsistanDB, degisen: dict) -> dict:
    """Doğrulanmış değişiklikleri yazar; yapı değiştiyse 'yapi_surumu' artar (eklenti modeli sıfırdan kurar)."""
    degisen = ayar_dogrula(degisen)
    yeni = {**ayarlar_oku(adb), **degisen}
    if yeni["boyut"] % yeni["bas"]:
        raise ValueError("boyut, dikkat başı sayısına tam bölünmeli (ör. 64 ve 4)")
    eski = ayarlar_oku(adb)
    with adb.yaz() as con:
        adb.meta_yaz("ayarlar", json.dumps(yeni), con)
        if any(yeni[k] != eski[k] for k in YAPI):
            adb.surum_artir("yapi_surumu", con)
    return yeni


# ---------------------------------------------------------------- olay adları
KOD_ADI = {"DOSYA_GELDI": "Dosya geldi", "ILETILDI": "İletildi", "ERITILDI": "Eritildi", "YENIDEN_DENENDI": "Yeniden denendi",
           "LOKALE_YAZILDI": "Lokale yazıldı", "ESLESMEDI": "Eşleşmedi", "KAYITSIZ_KAPALI": "Kayıtsız kapalıyken geldi"}
TUR_GRUBU = {"DOSYA_GELDI": "Dosya geldi", "ILETILDI": "İletildi", "ERITILDI": "Eritildi (lokalden)", "YENIDEN_DENENDI": "Yeniden denendi",
             "LOKALE_YAZILDI": "Lokale yazıldı", "ESLESMEDI": "Eşleşmedi", "KAYITSIZ_KAPALI": "Kayıtsız kapalıyken geldi"}


def kod_adi(kod: str) -> str:
    if kod.startswith("ALARM_"):
        return (KODLAR.get(kod[6:]) or {"ad": kod[6:]})["ad"]
    if kod.startswith("DUZELDI_"):
        return "Düzeldi: " + (KODLAR.get(kod[8:]) or {"ad": kod[8:]})["ad"]
    return KOD_ADI.get(kod, kod)


def tur_grubu(kod: str) -> str:
    return "Alarm açıldı" if kod.startswith("ALARM_") else "Alarm kapandı" if kod.startswith("DUZELDI_") else TUR_GRUBU.get(kod, kod)


def adlar_oku(db) -> dict:
    """canli.db'den nesne adları: {'dizin:3': 'Muhasebe', 'hedef:1': 'Control-M Prod'}."""
    adlar = {}
    for r in db.oku("SELECT id, yol, ad FROM dizin"):
        adlar[f"dizin:{r['id']}"] = r["ad"] or Path(str(r["yol"]).rstrip("\\/")).name or r["yol"]
    for r in db.oku("SELECT id, ad FROM hedef"):
        adlar[f"hedef:{r['id']}"] = r["ad"]
    return adlar


def etiket(token: str, adlar: dict) -> str:
    kod, _, nesne = token.partition("|")
    ad = kod_adi(kod)
    return f"{ad} · {adlar.get(nesne, nesne)}" if nesne else ad


# ---------------------------------------------------------------- güven karnesi (önyüz: Güven sekmesi)
def karne(g: dict, geri: dict, model_durumu: str, veri: dict) -> dict:
    """Beş ölçütün ağırlıklı ortalaması. g: eklentinin son eğitimden sonra yazdığı ölçümler."""
    def durum(s):
        return "iyi" if s >= 0.75 else "orta" if s >= 0.4 else "kotu"
    iyi = g.get("iyilesme", 0.0)
    s1 = max(0.0, min(1.0, iyi / 0.25)) if g.get("ga_alt", 0) > 0 else max(0.0, min(0.35, iyi / 0.25))
    fark = g.get("fark", 0.0)
    s2 = 0.15 if model_durumu == "EZBERLIYOR" else max(0.0, min(1.0, 1 - max(0.0, fark) / 0.6))
    ece = g.get("ece", 0.2)
    s3 = max(0.0, min(1.0, 1 - ece / 0.15))
    s4 = 0.5 * min(1.0, veri.get("gun_sayisi", 0) / 28) + 0.5 * min(1.0, veri.get("olay_sayisi", 0) / 20000)
    n = geri.get("faydali", 0) + geri.get("faydasiz", 0)
    s5 = geri["faydali"] / n if n >= 5 else 0.5
    yz = lambda v: f"%{v * 100:.0f}"                                                                   # noqa: E731
    olcutler = [
        {"ad": "Tabanı geçiyor", "agirlik": 0.3, "puan": s1, "deger": yz(iyi),
         "aciklama": f"Doğrulama kaybı Markov tabanından {yz(iyi)} düşük (güven aralığı {yz(g.get('ga_alt', 0))}–{yz(g.get('ga_ust', 0))})"
         if iyi > 0 else "Doğrulama kaybı Markov tabanının altına inemedi"},
        {"ad": "Ezber yok", "agirlik": 0.2, "puan": s2, "deger": f"{fark:.2f}".replace(".", ","),
         "aciklama": "Son eğitimde ezber başladı; en iyi adıma dönüldü" if model_durumu == "EZBERLIYOR"
         else "Eğitim–doğrulama farkı küçük" if fark < 0.3 else "Eğitim–doğrulama farkı büyük"},
        {"ad": "Kalibrasyon", "agirlik": 0.2, "puan": s3, "deger": f"ECE %{ece * 100:.1f}".replace(".", ","),
         "aciklama": "Söylediği güven ile gerçek isabet arasındaki ortalama fark (iyi: %5 altı)"},
        {"ad": "Veri yeterliliği", "agirlik": 0.15, "puan": s4, "deger": yz(s4),
         "aciklama": f"{veri.get('gun_sayisi', 0):.1f} gün, {veri.get('olay_sayisi', 0)} olay; haftalık düzen için 4 hafta önerilir".replace(".", ",", 1)},
        {"ad": "Geri bildirim isabeti", "agirlik": 0.15, "puan": s5, "deger": yz(s5) if n >= 5 else "—",
         "aciklama": f"{n} öneriden {geri.get('faydali', 0)}'i faydalı bulundu" + (" (az örnek)" if n < 5 else "")},
    ]
    for o in olcutler:
        o["durum"] = durum(o["puan"])
    puan = sum(o["agirlik"] * o["puan"] for o in olcutler)
    if model_durumu == "ANLAMSIZ":
        puan = min(puan, 0.35)
    derece = "Yüksek" if puan >= 0.8 else "Orta-iyi" if puan >= 0.65 else "Orta" if puan >= 0.45 else "Düşük"
    ozet = {"Yüksek": "Öneriler genelde isabetli; yine de kanıtına bakın.", "Orta-iyi": "Önerileri dikkate alın; önemli bir karardan önce kanıtına bakın.",
            "Orta": "Önerileri ipucu olarak kullanın; doğrulamadan işlem yapmayın.", "Düşük": "Model şu an güvenilir değil; önerileri yalnızca ipucu sayın."}[derece]
    return {"puan": round(puan, 3), "derece": derece, "ozet": ozet, "olcutler": olcutler}


# ---------------------------------------------------------------- önyüz özeti (GET /api/asistan)
def _dosya_mb(yol: Path) -> float:
    toplam = 0
    for f in [yol, Path(str(yol) + "-wal")]:
        try:
            toplam += f.stat().st_size
        except OSError:
            pass
    return toplam / 1048576


def ozet(adb: AsistanDB, canli_db) -> dict:
    ay = ayarlar_oku(adb)
    durum = json.loads(adb.meta_al("durum") or "{}")
    ilk, son, n = adb.tek("SELECT MIN(zaman), MAX(zaman), COUNT(*) FROM olay")
    gun = ((son - ilk) / 86400) if n else 0.0
    turler = {}
    for r in adb.oku("SELECT kod, COUNT(*) FROM olay GROUP BY kod"):
        g_ = tur_grubu(r[0])
        turler[g_] = turler.get(g_, 0) + r[1]
    gunluk = [{"gun": r[0][8:10] + "/" + r[0][5:7], "sayi": r[1]} for r in adb.oku(
        "SELECT date(zaman, 'unixepoch', 'localtime') g, COUNT(*) FROM olay WHERE zaman >= ? GROUP BY g ORDER BY g",
        (time.time() - 14 * 86400,))]
    mdir = model_klasoru(canli_db.yol)
    model_mb = sum(f.stat().st_size for f in mdir.glob("model_*.npz")) / 1048576 if mdir.exists() else 0.0
    veri = {"olay_sayisi": n, "gun_sayisi": round(gun, 2), "ilk_zaman": ilk, "son_zaman": son, "boyut_mb": round(_dosya_mb(adb.yol), 2),
            "model_mb": round(model_mb, 2), "saklama_gun": ay["saklama_gun"], "asgari_olay": ay["asgari_olay"], "asgari_gun": ay["asgari_gun"],
            "turler": sorted(({"ad": k, "sayi": v} for k, v in turler.items()), key=lambda x: -x["sayi"]), "gunluk": gunluk}
    model_durumu = durum.get("model_durumu") or "VERI_TOPLANIYOR"
    oneriler = []
    for r in adb.oku("SELECT * FROM oneri WHERE durum='ACIK' OR zaman >= ? ORDER BY zaman DESC LIMIT 200", (time.time() - 30 * 86400,)):
        o = dict(r)
        o["kanit"] = json.loads(o["kanit"] or "[]")
        oneriler.append(o)
    geri = {"faydali": 0, "faydasiz": 0}
    gturler = {}
    for r in adb.oku("SELECT tur, durum, COUNT(*) FROM oneri WHERE durum IN ('FAYDALI','FAYDASIZ') GROUP BY tur, durum"):
        t = gturler.setdefault(r[0], {"tur": r[0], "faydali": 0, "faydasiz": 0})
        k = "faydali" if r[1] == "FAYDALI" else "faydasiz"
        t[k] += r[2]
        geri[k] += r[2]
    toplam = geri["faydali"] + geri["faydasiz"]
    guven = None
    g = json.loads(adb.meta_al("guven") or "null")
    if g and model_durumu != "VERI_TOPLANIYOR":
        onceden = adb.oku("SELECT gun, n, model, markov FROM onceden ORDER BY gun DESC LIMIT 14")[::-1]
        guven = {**g, "karne": karne(g, geri, model_durumu, veri),
                 "onceden": {"gunler": [r[0][8:10] + "/" + r[0][5:7] for r in onceden], "model": [r[2] / r[1] if r[1] else None for r in onceden],
                             "markov": [r[3] / r[1] if r[1] else None for r in onceden]}}
    guven_gb = {"toplam": toplam, "oran": geri["faydali"] / toplam if toplam else None, "turler": list(gturler.values())}
    if guven is not None:
        guven["geri_bildirim"] = guven_gb
    egri = json.loads(adb.meta_al("egri") or "null")
    egitim = None
    if egri and model_durumu != "VERI_TOPLANIYOR":
        surumler = [dict(r) for r in adb.oku("SELECT surum, zaman, olay, egitim, dogrulama, markov, siklik, durum FROM surum ORDER BY surum DESC LIMIT 12")]
        for s in surumler:
            s["markova_gore"] = (s["dogrulama"] / s["markov"] - 1) if s["dogrulama"] and s["markov"] else 0.0
        egitim = {**{k: v for k, v in egri.items() if k not in ("egitim", "dogrulama")}, "egitim_kaybi": egri["egitim"],
                  "dogrulama_kaybi": egri["dogrulama"], "surumler": surumler,
                  "karar": json.loads(adb.meta_al("karar") or "null") or {"baslik": "", "maddeler": []}}
    iliskiler = json.loads(adb.meta_al("iliskiler") or "null") if model_durumu != "VERI_TOPLANIYOR" else None
    return {"durum": {"model_durumu": model_durumu, **{k: v for k, v in durum.items() if k != "model_durumu"}},
            "veri": veri, "egitim": egitim, "guven": guven or {"geri_bildirim": guven_gb}, "guven_var": guven is not None,
            "iliskiler": iliskiler, "oneriler": oneriler, "ayarlar": ay,
            "anomali": json.loads(adb.meta_al("anomali_ozet") or "[]"),
            "kendini_sina": json.loads(adb.meta_al("kendini_sina") or "null") or {"son": None, "suruyor": False}}
