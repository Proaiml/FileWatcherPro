"""Anomali takibi (istatistik; PyTorch / model gerektirmez): her kural (dosya türü) için geçmişten 'normal' çıkarılır;
yeni değer bunun dışına düşerse öneri yazılır (ayarla açılırsa alarm da — varsayılan kapalı, gölge modu korunur).

Yöntem (sağlam istatistik, açıklanabilir; her öneri kanıtıyla gelir):
  * Boyut: log ölçeğinde medyan ve MAD (ortanca mutlak sapma); sağlam z = 0,6745 · (x − medyan) / MAD.
    |z| ≥ 4 VE oran ≥ 1,5× (büyük) ya da ≤ 1/1,5 (küçük) → anomali. MAD alt sınırı %10: hep aynı boyutta gelen
    dosyada küçük oynama anomali sayılmaz. Normal aralık = geçmişin %5–%95 dilimi. En az 'anomali_asgari' (20)
    geçmiş dosya ister; geçmiş penceresi 60 gün, en yeni 500 dosya. Aynı kuralda aynı yönde 24 saat içinde gelen
    anomaliler tek açık öneride toplanır ("Toplanan: N dosya"); geri bildirim verilince sonraki anomali yeni öneri açar.
  * Teslim süresi (dosya hazır → hedef kabul etti, canlı yol): son 10 tetiğin medyanı geçmiş medyanın ≥ 3 katı ve
    ≥ 2 sn → anomali; 1,5 katın altına inince düzelmiş sayılır.
  * Günlük adet: dün gelen adet, önceki 14 günün medyanının yarısı ya da altı / iki katı ya da üstü (en az 7 gün
    geçmiş, medyan ≥ 3) → anomali. Gün bitince bir kez değerlendirilir.
Dosya adı ve içerik toplanmaz; yalnız kural kimliği, boyut, süre, zaman. Öneri metnindeki dosya adı o an canlı
veritabanından okunur (asistan.db'ye yazılmaz).
"""
import json
import math
import statistics
import time

from cekirdek.model import AlarmSeviye

from .oneriler import oneri_ekle

BOYUT_Z, BOYUT_ORAN, MAD_ALT = 4.0, 1.5, math.log10(1.10)
SURE_KAT, SURE_KAPAT, SURE_ASGARI_MS, SURE_SON = 3.0, 1.5, 2000.0, 10
ADET_GUN, ADET_ASGARI_GUN, ADET_ASGARI_MEDYAN = 14, 7, 3
GECMIS_GUN, GECMIS_AZAMI = 60, 500


def boyut_metni(b) -> str:
    b = float(b or 0)
    for birim, k in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if b >= k:
            return f"{b / k:.1f} {birim}".replace(".", ",")
    return f"{int(b)} bayt"


def sayi_metni(x, basamak=1) -> str:
    """Türkçe sayı: 5.213 · 2,4 · 0,6"""
    x = float(x)
    if abs(x) >= 100:
        return f"{x:,.0f}".replace(",", ".")
    return f"{x:.{basamak}f}".replace(".", ",")


def _dilim(s, q):
    return s[int(round(q * (len(s) - 1)))]


# ---------------------------------------------------------------- saf hesaplar (birim testli)
def boyut_degerlendir(gecmis, x, asgari=20):
    if len(gecmis) < asgari:
        return None
    lg = [math.log10(float(v) + 1) for v in gecmis]
    med = statistics.median(lg)
    mad = max(statistics.median([abs(v - med) for v in lg]), MAD_ALT)
    z = 0.6745 * (math.log10(float(x) + 1) - med) / mad
    medyan = 10 ** med - 1
    oran = (float(x) + 1) / (medyan + 1)
    s = sorted(float(v) for v in gecmis)
    return {"anomali": abs(z) >= BOYUT_Z and (oran >= BOYUT_ORAN or oran <= 1 / BOYUT_ORAN), "z": round(z, 1),
            "oran": oran, "medyan": medyan, "p5": _dilim(s, 0.05), "p95": _dilim(s, 0.95), "n": len(s),
            "yon": "büyük" if z > 0 else "küçük"}


def sure_degerlendir(gecmis, son, asgari=20):
    if len(gecmis) < asgari or len(son) < 5:
        return None
    mg, ms = statistics.median(gecmis), statistics.median(son)
    return {"anomali": ms >= SURE_KAT * mg and ms >= SURE_ASGARI_MS, "normal": ms < SURE_KAPAT * mg or ms < SURE_ASGARI_MS,
            "gecmis_medyan": mg, "son_medyan": ms, "n": len(gecmis)}


def adet_degerlendir(gunluk, dun):
    if len(gunluk) < ADET_ASGARI_GUN:
        return None
    m = statistics.median(gunluk)
    if m < ADET_ASGARI_MEDYAN:
        return None
    return {"anomali": dun <= m * 0.5 or dun >= m * 2, "medyan": m, "dun": dun, "gun": len(gunluk),
            "yon": "az" if dun <= m * 0.5 else "çok"}


# ---------------------------------------------------------------- değerlendirme turu
class Anomali:
    def __init__(self, adb, db):
        self.adb, self.db = adb, db
        self.iz = json.loads(adb.meta_al("anomali_iz") or "{}")
        self.son_ozet = 0.0
        self.ozet_kirli = False

    def _kurallar(self) -> dict:
        return {r["id"]: (r["ad"], r["yol"]) for r in self.db.oku("SELECT k.id, k.ad, d.yol FROM kural k JOIN dizin d ON d.id=k.dizin_id")}

    def _alarm(self, ay, anahtar, mesaj):
        if ay["anomali_alarm"]:
            self.db.alarm_ac(anahtar, mesaj, AlarmSeviye.UYARI, "asistan")

    def _alarm_kapat(self, anahtar):
        if self.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (anahtar,)):
            self.db.alarm_kapat(anahtar)

    def _dosya_adi(self, kaynak):
        try:
            tid = int(str(kaynak).split(":")[1])
        except (IndexError, ValueError):
            return None
        r = self.db.tek("SELECT dosya_adi FROM tetik WHERE id=?", (tid,))
        return r[0] if r else None

    def tur(self, ay, simdi=None) -> int:
        """Yeni ölçümleri değerlendirir; yazılan öneri sayısını döner."""
        simdi = simdi or time.time()
        asgari = int(ay["anomali_asgari"])
        adlar = self._kurallar()
        yazilan = 0
        onceki_iz = (self.iz.get("boyut_id", 0), self.iz.get("sure_id", 0))
        # 1) boyut: her yeni dosya geçmişine göre
        for r in self.adb.oku("SELECT id, zaman, kural_id, deger, kaynak FROM olcum WHERE tur='boyut' AND id > ? ORDER BY id LIMIT 5000",
                              (self.iz.get("boyut_id", 0),)):
            self.iz["boyut_id"] = r["id"]
            kid = r["kural_id"]
            gecmis = [x[0] for x in self.adb.oku(
                "SELECT deger FROM olcum WHERE tur='boyut' AND kural_id=? AND id < ? AND zaman >= ? ORDER BY id DESC LIMIT ?",
                (kid, r["id"], r["zaman"] - GECMIS_GUN * 86400, GECMIS_AZAMI))]
            s = boyut_degerlendir(gecmis, r["deger"], asgari)
            anahtar = f"anomali:{kid}:boyut"
            if s is None:
                continue
            if not s["anomali"]:
                self._alarm_kapat(anahtar)                    # bu türden normal bir dosya geldi: önceki uyarı kapanır
                continue
            ad, yol = adlar.get(kid, (f"kural {kid}", ""))
            dosya = self._dosya_adi(r["kaynak"])
            kat = s["oran"] if s["yon"] == "büyük" else 1 / max(s["oran"], 1e-9)
            metin = (f"{dosya or 'Bir dosya'} {boyut_metni(r['deger'])} geldi; bu kuralın dosyaları genelde "
                     f"{boyut_metni(s['p5'])} – {boyut_metni(s['p95'])} arasında (medyan {boyut_metni(s['medyan'])}). "
                     f"Yaklaşık {sayi_metni(kat)} kat daha {s['yon']}.")
            # aynı kuralda aynı yönde 24 saat içinde açık öneri varsa yenisi açılmaz, o öneride toplanır (öneri seli olmaz)
            grup = self.adb.tek("SELECT id, kanit FROM oneri WHERE tur='ANOMALI' AND durum='ACIK' AND anahtar LIKE ? AND baslik LIKE ? "
                                "AND zaman >= ? ORDER BY id DESC LIMIT 1", (f"{anahtar}:%", f"%alışılmadık {s['yon']} dosya", r["zaman"] - 86400))
            if grup:
                kanit = json.loads(grup["kanit"] or "[]")
                n = next((int(k.split()[1]) for k in kanit if k.startswith("Toplanan: ")), 1) + 1
                kanit = [f"Toplanan: {n} dosya (24 saat içinde aynı yönde; metin en sonuncusunu anlatır)"] + [
                    k for k in kanit if not k.startswith("Toplanan: ")]
                self.adb.calistir("UPDATE oneri SET zaman=?, metin=?, kanit=? WHERE id=?",
                                  (r["zaman"], metin, json.dumps(kanit, ensure_ascii=False), grup["id"]))
                self._alarm(ay, anahtar, f"'{ad}' kuralında alışılmadık {s['yon']} dosya ({n}. dosya, 24 saat içinde): {metin}")
                continue
            if oneri_ekle(self.adb, anahtar=f"{anahtar}:{r['id']}", tur="ANOMALI", nesne=f"kural:{kid}", zaman=r["zaman"],
                          baslik=f"'{ad}' kuralında alışılmadık {s['yon']} dosya", metin=metin,
                          kanit=[f"Geçmiş: son {s['n']} dosya (en çok {GECMIS_GUN} gün)", f"Normal aralık (%5–%95): {boyut_metni(s['p5'])} – {boyut_metni(s['p95'])}",
                                 f"Sağlam z = {sayi_metni(s['z'])} (eşik ±{BOYUT_Z:g}; log ölçeği, medyan / MAD)", f"Dizin: {yol}"],
                          oneri=("Dosyayı açıp kontrol edin: yarım / boş yükleme ya da yanlış dosya olabilir. Normalse 'Faydasız' işaretleyin."
                                 if s["yon"] == "küçük" else "Dosyayı ve gönderen tarafı kontrol edin (birleşik / tekrarlı veri olabilir). Normalse 'Faydasız' işaretleyin."),
                          kaynak="istatistik"):
                yazilan += 1
                self._alarm(ay, anahtar, f"'{ad}' kuralında alışılmadık {s['yon']} dosya: {metin}")
        # 2) teslim süresi: yeni ölçümü olan kurallar
        yeni = self.adb.oku("SELECT DISTINCT kural_id FROM olcum WHERE tur='sure' AND id > ?", (self.iz.get("sure_id", 0),))
        self.iz["sure_id"] = self.adb.tek("SELECT COALESCE(MAX(id), 0) FROM olcum WHERE tur='sure'")[0]
        for (kid,) in yeni:
            satir = [x[0] for x in self.adb.oku("SELECT deger FROM olcum WHERE tur='sure' AND kural_id=? AND zaman >= ? "
                                                "ORDER BY id DESC LIMIT ?", (kid, simdi - GECMIS_GUN * 86400, GECMIS_AZAMI))]
            s = sure_degerlendir(satir[SURE_SON:], satir[:SURE_SON], asgari)
            anahtar = f"anomali:{kid}:sure"
            if s is None:
                continue
            if s["normal"]:
                self._alarm_kapat(anahtar)
                continue
            if not s["anomali"]:
                continue
            ad, yol = adlar.get(kid, (f"kural {kid}", ""))
            metin = (f"Son {SURE_SON} dosyanın teslim süresi medyanı {sayi_metni(s['son_medyan'] / 1000)} sn; bu kuralda genelde "
                     f"{sayi_metni(s['gecmis_medyan'] / 1000)} sn ({sayi_metni(s['son_medyan'] / max(s['gecmis_medyan'], 1))} kat).")
            if oneri_ekle(self.adb, anahtar=f"{anahtar}:{time.strftime('%Y%m%d%H', time.localtime(simdi))}", tur="ANOMALI",
                          nesne=f"kural:{kid}", baslik=f"'{ad}' dosyalarının teslimi yavaşladı", metin=metin, zaman=simdi,
                          kanit=[f"Geçmiş: {s['n']} teslim (en çok {GECMIS_GUN} gün)", f"Eşik: {SURE_KAT:g} kat ve en az {SURE_ASGARI_MS / 1000:g} sn", f"Dizin: {yol}"],
                          oneri="Hedefin (Control-M / API / betik) yanıt sürelerine ve Sistem izleme'ye bakın.", kaynak="istatistik"):
                yazilan += 1
                self._alarm(ay, anahtar, f"'{ad}' dosyalarının teslimi yavaşladı: {metin}")
        # 3) günlük adet: gün değişince dün için bir kez
        bugun = time.strftime("%Y-%m-%d", time.localtime(simdi))
        if self.iz.get("adet_gun") != bugun:
            self.iz["adet_gun"] = bugun
            yazilan += self._adet(ay, adlar, simdi)
        self.adb.meta_yaz("anomali_iz", json.dumps(self.iz))
        self.ozet_kirli = self.ozet_kirli or onceki_iz != (self.iz.get("boyut_id", 0), self.iz.get("sure_id", 0))
        # özet 300 kuralda ~0,5 sn: akışta en çok 15 sn'de bir; yeni ölçüm işlendiyse en geç 15 sn sonra mutlaka
        if yazilan or simdi - self.son_ozet >= (15 if self.ozet_kirli else 60):
            self.ozet_kirli = False
            self.son_ozet = simdi
            self.adb.meta_yaz("anomali_ozet", json.dumps(self.ozet(adlar, asgari, simdi), ensure_ascii=False))
        return yazilan

    def _gunluk(self, kid, simdi) -> dict:
        bas = simdi - (ADET_GUN + 2) * 86400
        return {r[0]: r[1] for r in self.adb.oku(
            "SELECT date(zaman, 'unixepoch', 'localtime') g, COUNT(*) FROM olcum WHERE tur='boyut' AND kural_id=? AND zaman >= ? "
            "GROUP BY g", (kid, bas))}

    def _adet(self, ay, adlar, simdi) -> int:
        yazilan = 0
        dun = time.strftime("%Y-%m-%d", time.localtime(simdi - 86400))
        for (kid,) in self.adb.oku("SELECT DISTINCT kural_id FROM olcum WHERE tur='boyut' AND zaman >= ?", (simdi - (ADET_GUN + 2) * 86400,)):
            ilk = self.adb.tek("SELECT MIN(zaman) FROM olcum WHERE tur='boyut' AND kural_id=?", (kid,))[0]
            say = self._gunluk(kid, simdi)
            gunler = [time.strftime("%Y-%m-%d", time.localtime(simdi - i * 86400)) for i in range(2, ADET_GUN + 2)]
            gunler = [g for g in gunler if g >= time.strftime("%Y-%m-%d", time.localtime(ilk))]   # kural yokken sıfır sayılmaz
            s = adet_degerlendir([say.get(g, 0) for g in gunler], say.get(dun, 0))
            anahtar = f"anomali:{kid}:adet"
            if s is None:
                continue
            if not s["anomali"]:
                self._alarm_kapat(anahtar)
                continue
            ad, yol = adlar.get(kid, (f"kural {kid}", ""))
            metin = f"Dün ({dun}) {s['dun']} dosya geldi; bu kuralda günde genelde {sayi_metni(s['medyan'], 0) if s['medyan'] == int(s['medyan']) else sayi_metni(s['medyan'])} dosya gelir (son {s['gun']} gün medyanı)."
            if oneri_ekle(self.adb, anahtar=f"{anahtar}:{dun}", tur="ANOMALI", nesne=f"kural:{kid}", zaman=simdi,
                          baslik=f"'{ad}' kuralında günlük dosya sayısı alışılmadık ({s['yon']})", metin=metin,
                          kanit=[f"Son {s['gun']} günün medyanı: {sayi_metni(s['medyan'], 0) if s['medyan'] == int(s['medyan']) else sayi_metni(s['medyan'])}", "Eşik: medyanın yarısı ya da iki katı", f"Dizin: {yol}"],
                          oneri="Gönderen tarafla kontrol edin (eksik / fazla gönderim, tatil, yeni iş akışı).", kaynak="istatistik"):
                yazilan += 1
                self._alarm(ay, anahtar, f"'{ad}' kuralında günlük dosya sayısı alışılmadık: {metin}")
        return yazilan

    def ozet(self, adlar, asgari, simdi) -> list:
        """Anomaliler sekmesi: kural başına normal aralık, son değer, durum."""
        sonuc = []
        bas = simdi - GECMIS_GUN * 86400
        aktif = {r[0] for r in self.db.oku("SELECT anahtar FROM alarm WHERE anahtar LIKE 'anomali:%' AND aktif=1")}
        acik_oneri = {}
        for r in self.adb.oku("SELECT anahtar FROM oneri WHERE tur='ANOMALI' AND durum='ACIK'"):
            p = r[0].split(":")
            if len(p) >= 3:
                acik_oneri.setdefault(f"{p[1]}:{p[2]}", 0)
                acik_oneri[f"{p[1]}:{p[2]}"] += 1
        for (kid,) in self.adb.oku("SELECT DISTINCT kural_id FROM olcum WHERE zaman >= ?", (bas,)):
            boy = [x[0] for x in self.adb.oku("SELECT deger FROM olcum WHERE tur='boyut' AND kural_id=? AND zaman >= ? ORDER BY id DESC LIMIT ?",
                                              (kid, bas, GECMIS_AZAMI))]
            sur = [x[0] for x in self.adb.oku("SELECT deger FROM olcum WHERE tur='sure' AND kural_id=? AND zaman >= ? ORDER BY id DESC LIMIT ?",
                                              (kid, bas, GECMIS_AZAMI))]
            say = self._gunluk(kid, simdi)
            gunler = [time.strftime("%Y-%m-%d", time.localtime(simdi - i * 86400)) for i in range(2, ADET_GUN + 2)]
            gunluk = [say[g] for g in gunler if g in say]
            sb = sorted(boy)
            ad, yol = adlar.get(kid, (f"kural {kid}", ""))
            sonuc.append({
                "kural_id": kid, "kural": ad, "dizin": yol, "n": len(boy), "yeterli": len(boy) >= asgari,
                "boyut_p5": _dilim(sb, 0.05) if sb else None, "boyut_p95": _dilim(sb, 0.95) if sb else None,
                "boyut_medyan": statistics.median(sb) if sb else None, "son_boyut": boy[0] if boy else None,
                "sure_medyan": statistics.median(sur[SURE_SON:]) if len(sur) > SURE_SON else (statistics.median(sur) if sur else None),
                "sure_son": statistics.median(sur[:SURE_SON]) if sur else None,
                "gunluk_medyan": statistics.median(gunluk) if gunluk else None,
                "dun": say.get(time.strftime("%Y-%m-%d", time.localtime(simdi - 86400)), 0),
                "bugun": say.get(time.strftime("%Y-%m-%d", time.localtime(simdi)), 0),
                "anomali": {t: (f"anomali:{kid}:{t}" in aktif) or bool(acik_oneri.get(f"{kid}:{t}")) for t in ("boyut", "sure", "adet")}})
        return sorted(sonuc, key=lambda x: (not any(x["anomali"].values()), x["kural"]))
