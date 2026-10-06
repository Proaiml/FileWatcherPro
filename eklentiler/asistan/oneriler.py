"""Öneri üreticileri. Asistan gölge modundadır: öneri yazar, hiçbir tetiği / kuralı / ayarı değiştirmez, alarm açmaz.

Her önerinin kaynağı açıkça yazılır:
  * istatistik  → BEKLENEN_GELMEDI: geçmiş günlerde dosyanın geldiği saat aralığı (PyTorch gerekmez).
  * kural       → KURAL: kurala uymayan dosya adlarından regex önerisi (PyTorch gerekmez).
  * model       → ILISKI (dikkat haritası + istatistik birlikte doğrularsa), OLAGANDISI (modelin verdiği olasılık çok düşük).
Güven: BEKLENEN_GELMEDI ve ILISKI için geçmişteki sıklık (Laplace düzeltmeli oran; kalibre edilmiş bir olasılıktır),
OLAGANDISI için modelin güven karnesi puanı, KURAL için yok (kurala dayalı).
Aynı öneri iki kez yazılmaz (anahtar); durum düzelince (ör. beklenen dosya gelince) öneri kendiliğinden kapanır.
"""
import json
import re
import statistics
import time
from collections import defaultdict

from .depo import etiket

# Sistem zaten böyle çalışır: bu ilişkiler öneriye dönüşmez (ör. devre kesilince tetikler lokale yazılır)
SISTEM_CIFTLERI = {("DOSYA_GELDI", "ILETILDI"), ("DOSYA_GELDI", "YENIDEN_DENENDI"), ("DOSYA_GELDI", "LOKALE_YAZILDI"),
                   ("YENIDEN_DENENDI", "ILETILDI"), ("YENIDEN_DENENDI", "YENIDEN_DENENDI"), ("YENIDEN_DENENDI", "LOKALE_YAZILDI"),
                   ("ALARM_HEDEF_DEVRE", "LOKALE_YAZILDI"), ("LOKALE_YAZILDI", "LOKALE_YAZILDI"), ("DOSYA_GELDI", "DOSYA_GELDI"),
                   ("ILETILDI", "DOSYA_GELDI"), ("ILETILDI", "ILETILDI"), ("ERITILDI", "ERITILDI"), ("LOKALE_YAZILDI", "ERITILDI"),
                   ("ALARM_HEDEF_DEVRE", "DUZELDI_HEDEF_DEVRE"), ("ALARM_HEDEF_KAPALI_UZUN", "LOKALE_YAZILDI"),
                   ("ALARM_DIZIN_ERISILEMEZ", "DOSYA_GELDI"), ("DUZELDI_DIZIN_ERISILEMEZ", "DOSYA_GELDI")}


def sistem_kurali(once_token: str, sonra_token: str) -> bool:
    a, b = once_token.split("|")[0], sonra_token.split("|")[0]
    if a.startswith("ALARM_") and b == "DUZELDI_" + a[6:]:
        return True
    return (a, b) in SISTEM_CIFTLERI


def oneri_ekle(adb, *, anahtar, tur, baslik, metin, kaynak, nesne=None, kanit=None, oneri=None, guven=None, surum=None, zaman=None) -> bool:
    return adb.calistir(
        "INSERT OR IGNORE INTO oneri(zaman, anahtar, tur, nesne, baslik, metin, kanit, oneri, guven, kaynak, surum) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (zaman or time.time(), anahtar, tur, nesne, baslik, metin, json.dumps(kanit or [], ensure_ascii=False), oneri, guven, kaynak, surum)) > 0


def _saat(dk: float) -> str:
    dk = int(round(dk)) % 1440
    return f"{dk // 60:02d}:{dk % 60:02d}"


def _gun(z) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(z))


def _dakika(z) -> float:
    t = time.localtime(z)
    return t.tm_hour * 60 + t.tm_min + t.tm_sec / 60


# ---------------------------------------------------------------- BEKLENEN_GELMEDI (istatistik)
def beklenen_gelmedi(adb, db, adlar: dict, simdi: float = None, asgari_gun=5, tolerans_dk=20, asgari_guven=0.7) -> int:
    """Her dizin için: aynı türden (iş günü / hafta sonu) geçmiş günlerde ilk dosyanın geldiği saat. Bugün o saat
    (+ tolerans) geçtiyse ve dosya yoksa öneri. Gelince ya da gün bitince öneri kendiliğinden kapanır."""
    simdi = simdi or time.time()
    bugun, is_gunu = _gun(simdi), time.localtime(simdi).tm_wday < 5
    satirlar = adb.oku("SELECT zaman, nesne FROM olay WHERE kod='DOSYA_GELDI' AND nesne != '' AND zaman >= ? AND zaman <= ?",
                       (simdi - 29 * 86400, simdi))
    ilk = defaultdict(dict)                                   # nesne → gün → ilk geliş (dk)
    ilk_gun = {}
    for r in satirlar:
        g = _gun(r["zaman"])
        dk = _dakika(r["zaman"])
        if g not in ilk[r["nesne"]] or dk < ilk[r["nesne"]][g]:
            ilk[r["nesne"]][g] = dk
        ilk_gun[r["nesne"]] = min(ilk_gun.get(r["nesne"], r["zaman"]), r["zaman"])
    # açık önerileri kapat: dosya geldiyse ya da gün değiştiyse
    for o in adb.oku("SELECT id, anahtar FROM oneri WHERE tur='BEKLENEN_GELMEDI' AND durum='ACIK'"):
        nesne = ":".join(o["anahtar"].split(":")[1:-1])                 # anahtar: beklenen:<dizin:3>:<gün>
        if not o["anahtar"].endswith(":" + bugun) or bugun in ilk.get(nesne, {}):
            adb.calistir("UPDATE oneri SET durum='KAPANDI', kapanma=? WHERE id=?", (simdi, o["id"]))
    yazilan = 0
    simdi_dk = _dakika(simdi)
    erisim = {f"dizin:{r['id']}": r["erisim_durumu"] for r in db.oku("SELECT id, erisim_durumu FROM dizin")}
    for nesne, gunler in ilk.items():
        if bugun in gunler:
            continue
        # karşılaştırılabilir günler: ilk görülen günden dünye kadar, bugünle aynı türde (iş günü / hafta sonu)
        karsi, g = [], ilk_gun[nesne]
        while _gun(g) < bugun:
            if (time.localtime(g).tm_wday < 5) == is_gunu:
                karsi.append(_gun(g))
            g += 86400
        karsi = sorted(set(karsi))
        gelen = [gunler[d] for d in karsi if d in gunler]
        n = len(karsi)
        if n < asgari_gun or len(gelen) < max(asgari_gun, 0.8 * n):
            continue
        gelen_sirali = sorted(gelen)
        ust = gelen_sirali[min(len(gelen_sirali) - 1, int(0.9 * len(gelen_sirali)))] + tolerans_dk
        if simdi_dk <= ust:
            continue
        k = sum(1 for d in karsi if d in gunler and gunler[d] <= ust)
        guven = (k + 1) / (n + 2)
        if guven < asgari_guven:
            continue
        ad = adlar.get(nesne, nesne)
        tip = "iş günü" if is_gunu else "hafta sonu günü"
        ort, sap = statistics.mean(gelen), (statistics.pstdev(gelen) if len(gelen) > 1 else 0.0)
        kanit = [f"{k} / {n} {tip}, ortalama {_saat(ort)} (sapma {sap:.0f} dk)",
                 f"Beklenen en geç saat (tolerans {tolerans_dk} dk dahil): {_saat(ust)}"]
        e = erisim.get(nesne)
        if e:
            kanit.append("Dizin erişilebilir, tarama normal: sorun gönderen tarafta görünüyor" if e == "ERISILEBILIR"
                         else f"Dizin erişim durumu: {e} (önce bu sorunu çözün)")
        yazilan += oneri_ekle(
            adb, anahtar=f"beklenen:{nesne}:{bugun}", tur="BEKLENEN_GELMEDI", nesne=ad, kaynak="istatistik", guven=round(guven, 3),
            baslik=f"{ad}: bugünkü dosya henüz gelmedi",
            metin=f"Son {n} {tip}nün {k}'inde ilk dosya {_saat(min(gelen))}–{_saat(max(gelen))} arasında geldi. Şu an {_saat(simdi_dk)} ve bugün henüz yok.",
            kanit=kanit, oneri="Gönderen tarafa (EFT / ilgili ekip) sorun. Dosya gelince öneri kendiliğinden kapanır.", zaman=simdi)
    return yazilan


# ---------------------------------------------------------------- KURAL (kurala dayalı)
_PARCA = re.compile(r"\d+|[A-Za-zÇĞİÖŞÜçğıöşü]+|.")


def _parcala(ad):
    return [("r" if t[0].isdigit() else "h" if t[0].isalpha() else "d", t) for t in _PARCA.findall(ad)]


def imza(ad: str) -> str:
    return "".join(t[0] + (t[1] if t[0] == "d" else "") for t in _parcala(ad))


def regex_oner(adlar: list) -> str:
    """Aynı yapıdaki adlardan tam eşleşen regex: sabit parçalar aynen, değişen harfler [A-Z]{n}/{a,b}, rakamlar \\d{n};
    8 haneli tarih (?P<tarih>\\d{8}). Önyüzdeki 'Örnekten öner' ile aynı yaklaşım."""
    listeler = [_parcala(a) for a in adlar]
    tarih = False
    cikti = []
    for i, (tur, t) in enumerate(listeler[0]):
        hepsi = [l_[i][1] for l_ in listeler]
        if tur == "d":
            cikti.append(re.escape(t))
        elif tur == "h":
            if len(set(hepsi)) == 1:
                cikti.append(re.escape(t))
            else:
                uz = sorted({len(x) for x in hepsi})
                sinif = "[A-Z]" if all(x == x.upper() for x in hepsi) else "[A-Za-z]"
                cikti.append(f"{sinif}{{{uz[0]}}}" if len(uz) == 1 else f"{sinif}{{{uz[0]},{uz[-1]}}}")
        else:
            uz = {len(x) for x in hepsi}
            if uz == {8} and all(re.fullmatch(r"(19|20)\d{6}", x) for x in hepsi) and not tarih:
                tarih = True
                cikti.append(r"(?P<tarih>\d{8})")
            elif len(set(hepsi)) == 1:
                cikti.append(re.escape(t))
            else:
                cikti.append(rf"\d{{{uz.pop()}}}" if len(uz) == 1 else r"\d+")
    return "".join(cikti)


def kural_onerileri(adb, db, hdb, simdi: float = None, gun=7, asgari=3) -> int:
    simdi = simdi or time.time()
    yollar = {str(r["yol"]).lower(): r for r in db.oku("SELECT id, yol, ad FROM dizin")}
    kurallar = defaultdict(list)
    for r in db.oku("SELECT dizin_id, regex, harf_duyarsiz FROM kural"):
        kurallar[r["dizin_id"]].append(re.compile(r["regex"], re.IGNORECASE if r["harf_duyarsiz"] else 0))
    gruplar = defaultdict(list)
    for r in hdb.oku("SELECT dosya_adi, dizin_yolu FROM gonderilemeyen WHERE sebep='ESLESMEDI' AND son_zaman >= ?", (simdi - gun * 86400,)):
        gruplar[str(r["dizin_yolu"] or "").lower()].append(r["dosya_adi"])
    yazilan = 0
    for yol, adlar in gruplar.items():
        dz = yollar.get(yol)
        adlar = sorted(set(adlar))
        if dz is None or len(adlar) < asgari:
            continue
        imzalar = defaultdict(list)
        for a in adlar:
            imzalar[imza(a)].append(a)
        grup = max(imzalar.values(), key=len)
        if len(grup) < asgari:
            continue
        rx = regex_oner(grup)
        if any(all(k.fullmatch(a) for a in grup) for k in kurallar[dz["id"]]):
            continue                                            # artık bir kural bunları karşılıyor
        ad = dz["ad"] or dz["yol"]
        mevcut = [k.pattern for k in kurallar[dz["id"]]]
        yazilan += oneri_ekle(
            adb, anahtar=f"kural:{dz['id']}:{rx}", tur="KURAL", nesne=dz["yol"], kaynak="kural",
            baslik=f"{ad}: {len(grup)} dosya adı hiçbir kurala uymuyor",
            metin=f"Son {gun} günde {len(adlar)} dosya 'kurala uymadı' olarak kaldı; {len(grup)} tanesi aynı kalıpta.",
            kanit=[f"Örnek: {', '.join(grup[:3])}"] + ([f"Mevcut kural: {mevcut[0]}"] if mevcut else ["Bu dizinde kural yok"]),
            oneri=f"Regex: {rx} (kural penceresinde canlı deneyin)", zaman=simdi)
    return yazilan


# ---------------------------------------------------------------- ILISKI (model + istatistik)
def iliski_onerileri(adb, liste: list, tokenler: dict, gun: float, surum: int, simdi: float = None) -> int:
    yazilan = 0
    for x in liste:
        if not x["uyumlu"] or x["sistem"]:
            continue
        once, sonra = tokenler[x["once_tok"]], tokenler[x["sonra_tok"]]
        if once == sonra:
            continue
        yazilan += oneri_ekle(
            adb, anahtar=f"iliski:{once}>{sonra}", tur="ILISKI", nesne=f"{x['once']} → {x['sonra']}", kaynak="model", surum=surum,
            guven=x["olasilik"], baslik=f"'{x['once']}' olayından sonra '{x['sonra']}' geliyor",
            metin=(f"Son {gun:.0f} günde '{x['once']}' olayından sonra tipik olarak {x['aralik']} içinde {x['birlikte']} kez '{x['sonra']}' görüldü; "
                   f"tesadüfe göre {x['lift']:.1f} kat sık.").replace(".0 kat", " kat"),
            kanit=[f"Dikkat oranı {x['dikkat']:.1f}×: model '{x['sonra']}' olayını beklerken '{x['once']}' olayına sıklığının {x['dikkat']:.1f} katı bakıyor",
                   f"Güven: '{x['once']}' sonrası '{x['sonra']}' görülme oranı (geçmiş sıklık)"],
            oneri="Ortak bir neden olabilir; bu saatleri ilgili ekiple paylaşın. İlişki neden-sonuç demek değildir.", zaman=simdi)
    return yazilan


# ---------------------------------------------------------------- OLAGANDISI (model)
def olagandisi_onerisi(adb, *, token: str, adlar: dict, zaman: float, olasilik: float, esik: float, adet: int, guven: float, surum: int) -> bool:
    if adb.tek("SELECT COUNT(*) FROM oneri WHERE tur='OLAGANDISI' AND durum='ACIK'")[0] >= 5:
        return False                                            # öneri yağmuru olmasın
    ad = etiket(token, adlar)
    saat = time.strftime("%H:%M", time.localtime(zaman))
    return oneri_ekle(
        adb, anahtar=f"olagandisi:{token}:{int(zaman // 3600)}", tur="OLAGANDISI", nesne=ad, kaynak="model", surum=surum, guven=round(guven, 3),
        baslik=f"Olağandışı: '{ad}' ({saat}{f', {adet} kez' if adet > 1 else ''})",
        metin=f"Model bu olayı bu anda beklemiyordu: verdiği olasılık %{olasilik * 100:.1f} (olağan olayların en düşük %0,5'lik diliminin altı).",
        kanit=[f"Modelin olasılığı %{olasilik * 100:.2f}; olağan eşik %{esik * 100:.2f}", f"Aynı saatte {adet} kez görüldü"],
        oneri="Beklenen bir değişiklik değilse (toplu gönderim, yeni iş) ilgili ekiple kontrol edin.", zaman=zaman)
