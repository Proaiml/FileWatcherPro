"""Saha provası: FileWatcherPro'yu sahada kullanılıyormuş gibi uçtan uca çalıştırır ve raporlar.

Gerçek çekirdek + tarama + teslim + kontrol + izleme + bildirim süreçleri; Control-M, genel API ve mail sunucusu
yerine sahteleri; EFT gibi yazan dosyalar (açık tutamaçla parça parça, geçici adla yükleyip yeniden adlandırma,
ani yük). Canlı sisteme, gerçek klasörlere ve gerçek Control-M'e DOKUNMAZ: her şey geçici bir klasörde olur.

Akış (bir operasyon günü sıkıştırılmış):
  1 kurulum (ilk giriş admin/admin → şifre değiştir, SMTP, 3 hedef: Control-M / genel API / betik, 3 dizin
    — biri \\\\localhost\\C$ üzerinden SMB —, 4 kural, kurala bağlı mail)
  2 normal gün        3 ani yük (200 dosya)      4 Control-M kesintisi → lokal → devreyi normale al → erit
  5 betik: geçici hata, kalıcı hata → betik düzeltilir → erit
  6 teslim eklentisi öldürülür · çekirdek öldürülür (kapalıyken dosya gelir) · bakım çalışırken dosya gelir
  7 düzgün kapanış (bekleyenler varken) → açılış        8 önyüz: her sayfa tarayıcıda açılır (JS hatası / 5xx)
Sonuç: her yazılan dosya için hedefte TEK teslim (kayıp yok, çift yok; olası çift işaretli olabilir), hata logları,
CPU / bellek, veritabanı boyutları → testler\\_sonuc\\saha_provasi.json + ekran görüntüleri.

    py -3.11 araclar\\saha_provasi.py            (yaklaşık 6–8 dakika)
"""
import argparse
import json
import os
import re
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import psutil  # noqa: E402

from cekirdek import betik_sifresi  # noqa: E402
from testler.conftest import Ortam, Yazici  # noqa: E402
from testler.sahte_controlm import SahteControlM  # noqa: E402
from testler.sahte_smtp import SahteSMTP  # noqa: E402
from testler.test_adim8_kontrol_api import Istemci  # noqa: E402

SONUC = KOK / "testler" / "_sonuc"
SIFRE = "ornek-arayuz-sifresi-A"
SUPER = "ornek-super-sifre-A"
AYAR = {"tarama_araligi_sn": 1.0, "sabitlik_W_sn": 2.0, "deneme_plani": "1,2,3", "cagri_timeout_sn": 3,
        "otomatik_devre_esigi": 5, "erit_hizi": 20, "kapanis_teslim_bekleme_sn": 5, "sla_hedef_sn": 10,
        "bildirim_deneme_plani": "1,2"}
EKLENTILER = [{"ad": a, "modul": m} for a, m in (
    ("tarama", "eklentiler.tarama.tarayici"), ("teslim", "eklentiler.teslim.dagitici"),
    ("kontrol", "eklentiler.kontrol.kontrol_api"), ("izleme", "eklentiler.izleme.izleyici"),
    ("bildirim", "eklentiler.bildirim.bildirimci"), ("asistan", "eklentiler.asistan.asistan"))]
BETIK = r'''import json, os, sys
ad = os.environ["FWP_DOSYA_ADI"]
sayi = int(os.environ["FWP_DENEME_SAYISI"])
with open(os.environ["FWP_P_KAYIT"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"ad": ad, "kimlik": os.environ["FWP_KIMLIK"], "sayi": sayi, "depo": os.environ["FWP_P_DEPO"]}) + "\n")
if "GECICI" in ad and sayi < 2:
    print("hedef sistem meşgul", file=sys.stderr); sys.exit(1)
if "KALICI" in ad:
    print("HTTP 404: depo tanımsız", file=sys.stderr); sys.exit(10)
print("aktarıldı", ad)
'''


class Rapor:
    def __init__(self):
        self.adimlar, self.kontroller, self.t0 = [], [], time.time()

    @contextmanager
    def adim(self, ad):
        t0 = time.time()
        print(f"\n== {ad}", flush=True)
        try:
            yield
            self.adimlar.append({"adim": ad, "sonuc": "TAMAM", "sure_sn": round(time.time() - t0, 1)})
        except Exception as e:  # noqa: BLE001 - bir adımın hatası raporlanır, prova sürer
            self.adimlar.append({"adim": ad, "sonuc": "HATA", "hata": f"{type(e).__name__}: {e}"[:500],
                                 "sure_sn": round(time.time() - t0, 1)})
            print(f"   !! {type(e).__name__}: {e}", flush=True)

    def kontrol(self, ad, kosul, ayrinti=""):
        self.kontroller.append({"kontrol": ad, "sonuc": "GEÇTİ" if kosul else "KALDI", "ayrinti": str(ayrinti)[:800]})
        print(f"   {'✓' if kosul else '✗'} {ad}{(' · ' + str(ayrinti)[:160]) if ayrinti else ''}", flush=True)
        return kosul


def unc(yol: Path) -> str:
    s = str(Path(yol).resolve())
    return rf"\\localhost\{s[0]}$" + s[2:]


def bekle(kosul, sure=60, aralik=0.5, mesaj="koşul sağlanmadı"):
    son = time.time() + sure
    while time.time() < son:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    raise TimeoutError(mesaj)


class Kaynak(threading.Thread):
    """FileWatcherPro süreçlerinin CPU / bellek örnekleri (2 sn'de bir)."""

    def __init__(self, o):
        super().__init__(daemon=True)
        self.o, self.ornekler, self.dur = o, [], threading.Event()

    def run(self):
        onceki = {}
        while not self.dur.wait(2):
            try:
                kok = psutil.Process(self.o.proc.pid)
                surecler = [kok, *kok.children(recursive=True)]
            except (psutil.Error, AttributeError):
                continue
            cpu = bellek = 0.0
            for p in surecler:
                try:
                    t = p.cpu_times()
                    top = t.user + t.system
                    cpu += max(0.0, top - onceki.get(p.pid, top))
                    onceki[p.pid] = top
                    bellek += p.memory_info().rss
                except psutil.Error:
                    pass
            self.ornekler.append({"z": time.time(), "cpu_yuzde": round(cpu / 2 * 100, 1), "bellek_mb": round(bellek / 2 ** 20, 1),
                                  "surec": len(surecler)})


def main():
    arg = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arg.add_argument("--klasor", help="geçici çalışma klasörü (varsayılan: sistem geçici klasörü)")
    arg.add_argument("--sakla", action="store_true", help="bitince çalışma klasörünü silme")
    a = arg.parse_args()
    tmp = Path(a.klasor or tempfile.mkdtemp(prefix="fwp_saha_"))
    tmp.mkdir(parents=True, exist_ok=True)
    R = Rapor()
    beklenen = {}                   # dosya adı → hedef türü ('CTM' | 'API' | 'BETIK')
    yazilan_eslesmeyen = []
    silinen = []                    # lokalden elle (tutanakla) silinenler: hiçbir hedefe gitmemeli
    ctm = SahteControlM(kullanici="fwp", sifre="ornek-ctm-sifresi-A").baslat()
    webapi = SahteControlM(kimliksiz=True).baslat()
    smtp = SahteSMTP("fwp", "ornek-smtp-sifresi").baslat()
    os.environ["FWP_TEST_SMTP_SIFRE"] = "ornek-smtp-sifresi"
    o = Ortam(tmp / "fwp", EKLENTILER)
    o.ayar(**AYAR)
    b = json.loads(o.baslangic.read_text(encoding="utf-8"))
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        b["kontrol_port"] = so.getsockname()[1]
    o.baslangic.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    port = b["kontrol_port"]
    url = f"http://127.0.0.1:{port}"
    dz = {ad: tmp / "ftp" / ad for ad in ("muhasebe", "lojistik", "ik")}
    for d in dz.values():
        d.mkdir(parents=True)
    betik_kayit = tmp / "betik_kayit.jsonl"
    kaynak = Kaynak(o)
    y = None

    def tetik(ad):
        return o.db.tek("SELECT * FROM tetik WHERE dosya_adi=?", (ad,))

    def iletildi_bekle(adlar, sure=120):
        try:
            bekle(lambda: all((t := tetik(x)) and t["durum"] == "ILETILDI" for x in adlar), sure)
            return True
        except TimeoutError:
            kalan = [(x, (tetik(x) or {}) and tetik(x)["durum"]) for x in adlar
                     if not ((t := tetik(x)) and t["durum"] == "ILETILDI")]
            R.kontrol(f"{len(adlar)} dosya iletildi", False, f"iletilmeyen {len(kalan)}: {kalan[:10]}")
            return False

    def eft_yaz(d, ad, boyut=200_000, sure=1.5):
        """EFT gibi: dosya açık tutularak parça parça yazılır."""
        yz = Yazici(d / ad)
        parca = max(1, boyut // 6)
        for _ in range(6):
            yz.yaz(os.urandom(parca))
            time.sleep(sure / 6)
        yz.kapat()

    def gecici_adla_yaz(d, ad):
        g = d / (ad + ".filepart")
        g.write_bytes(os.urandom(50_000))
        time.sleep(0.5)
        os.replace(g, d / ad)

    try:
        # ------------------------------------------------------------ 1 kurulum
        with R.adim("1 · Kurulum (ilk giriş, şifre, SMTP, hedefler, dizinler, kurallar)"):
            o.cekirdek_baslat()
            kaynak.start()
            bekle(lambda: all((e := o.eklenti(x)) and e["durum"] == "CALISIYOR"
                              for x in ("tarama", "teslim", "kontrol", "izleme", "bildirim", "asistan")), 90, mesaj="eklentiler başlamadı")
            y = Istemci(port)
            bekle(lambda: y.giris("admin", "admin")[0] == 200, 30, mesaj="ilk giriş (admin/admin) olmadı")
            R.kontrol("İlk kurulum: admin/admin ile giriş + varsayılan şifre alarmı",
                      bool(o.db.tek("SELECT 1 FROM alarm WHERE anahtar LIKE 'kontrol:varsayilan_sifre%' AND aktif=1")))
            R.kontrol("Şifre değiştirildi", y.post("/api/sifre", {"eski": "admin", "yeni": SIFRE})[0] == 200)
            y = Istemci(port)
            assert y.giris("admin", SIFRE)[0] == 200
            assert y.put("/api/bildirim/smtp", smtp.ayar())[0] == 200
            R.kontrol("Test maili", y.post("/api/bildirim/test", {"alici": "ops@sirket.test"})[0] == 200)
            k, h_ctm = y.post("/api/hedefler", {"ad": "Control-M", "adres": ctm.adres, "tur": "CONTROLM", "ayrintilar": {
                "ctm": "ctmsunucu", "kimlik_turu": "token", "kullanici": "fwp", "sifre": "ornek-ctm-sifresi-A"}})
            assert k == 200, h_ctm
            k, h_api = y.post("/api/hedefler", {"ad": "Rapor API", "adres": f"http://127.0.0.1:{webapi.port}", "tur": "HTTP",
                                                "ayrintilar": {"kimlik_turu": "bearer", "anahtar": "ornek-api-anahtari",
                                                               "basliklar": {"X-Kaynak": "FWP"}}})
            assert k == 200, h_api
            betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), SUPER, belirleyen="saha")
            assert y.post("/api/betik/kilit", {"sifre": SUPER})[0] == 200
            betik_tanim = {"ad": "Sevk aktarım", "tur": "BETIK", "adres": "", "ayrintilar": {
                "dil": "python", "kod": BETIK, "zaman_asimi_sn": 20, "eszamanli": 3, "sirlar": []}}
            k, h_betik = y.post("/api/hedefler", betik_tanim)
            assert k == 200, h_betik
            smb = dz["lojistik"]
            try:
                smb_yolu = unc(smb) if os.path.isdir(unc(smb)) else str(smb)
            except OSError:
                smb_yolu = str(smb)
            R.kontrol("Lojistik dizini SMB yolu üzerinden izleniyor", smb_yolu.startswith("\\\\"), smb_yolu)
            idler = {}
            for ad, yol in (("muhasebe", str(dz["muhasebe"])), ("lojistik", smb_yolu), ("ik", str(dz["ik"]))):
                k, r = y.post("/api/dizinler", {"yol": yol, "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv,.txt,.xlsx"})
                assert k == 200, r
                idler[ad] = r["id"]
            govde = json.dumps({"ctm": "{ctm}", "folder": "MUHASEBE", "jobs": "FATURA_YUKLE",
                                "variables": [{"FWP_DOSYA": "{dosya_adi}"}, {"FWP_KIMLIK": "{kimlik}"}]})
            for kural in ({"dizin_id": idler["muhasebe"], "ad": "fatura", "regex": r"FATURA_(?P<tarih>\d{8})_(?P<no>\d+)\.csv",
                           "hedef_id": h_ctm["id"], "istek": {"yontem": "POST", "yol": "/run/order", "govde": govde}},
                          {"dizin_id": idler["muhasebe"], "ad": "iade", "regex": r"IADE_(?P<no>\d+)\.txt", "hedef_id": h_api["id"],
                           "istek": {"yontem": "POST", "yol": "/webhook", "govde": '{"dosya": "{dosya_adi}", "no": "{no}"}'}},
                          {"dizin_id": idler["lojistik"], "ad": "sevk", "regex": r"SEVK_(?P<depo>[A-Z]{3})_\w+\.csv",
                           "hedef_id": h_betik["id"], "istek": {"parametreler": {"KAYIT": str(betik_kayit), "DEPO": "{depo}"}}},
                          {"dizin_id": idler["ik"], "ad": "bordro", "regex": r"BORDRO_(?P<donem>\d{6})\.xlsx", "hedef_id": h_ctm["id"],
                           "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/BORDRO_{donem}/ODAT", "govde": ""}}):
                k, r = y.post("/api/kurallar", kural)
                assert k == 200, r
                if kural["ad"] == "sevk":
                    sevk_id = r["id"]
                if kural["ad"] == "fatura":
                    fatura_id = r["id"]
            assert y.post("/api/bildirim/kurallar", {"ad": "Kural: sevk", "alicilar": ["lojistik@sirket.test"],
                                                     "olaylar": ["DOSYA_GONDERILEMEDI", "DOSYA_ESLESMEDI", "DOSYA_KAYITSIZ"],
                                                     "seviye": "BILGI", "dizinler": [idler["lojistik"]], "kurallar": [sevk_id],
                                                     "ozet_dk": 0, "tekrar_dk": 60, "duzelince": True, "aktif": True})[0] == 200
            assert y.post("/api/bildirim/kurallar", {"ad": "Kural: fatura anomali", "alicilar": ["muhasebe@sirket.test"],
                                                     "olaylar": ["DOSYA_ANOMALI"], "seviye": "BILGI",
                                                     "dizinler": [idler["muhasebe"]], "kurallar": [fatura_id],
                                                     "ozet_dk": 0, "tekrar_dk": 60, "duzelince": True, "aktif": True})[0] == 200
            assert y.post("/api/bildirim/kurallar", {"ad": "Operasyon", "alicilar": ["ops@sirket.test"],
                                                     "olaylar": ["HEDEF_DEVRE", "HEDEF_KALICI", "EKLENTI_ELLE", "CEKIRDEK_YENIDEN"],
                                                     "seviye": "UYARI", "dizinler": None, "ozet_dk": 0, "tekrar_dk": 60,
                                                     "duzelince": True, "aktif": True})[0] == 200
            bekle(lambda: len(json.loads((o.eklenti("tarama") or {})["bilgi"] or "{}").get("dizinler") or []) == 3, 30,
                  mesaj="tarama 3 dizini almadı")

        # ------------------------------------------------------------ 2 normal gün
        with R.adim("2 · Normal gün (EFT gibi yazım, geçici adla yükleme, eşleşmeyen dosya)"):
            adlar = []
            for i in range(1, 16):
                ad = f"FATURA_20261001_{i:03d}.csv"
                eft_yaz(dz["muhasebe"], ad, sure=0.6)
                beklenen[ad] = "CTM"
                adlar.append(ad)
            for i in range(1, 6):
                ad = f"IADE_{i}.txt"
                gecici_adla_yaz(dz["muhasebe"], ad)
                beklenen[ad] = "API"
                adlar.append(ad)
            for i in range(1, 8):
                ad = f"SEVK_IST_{i:03d}.csv"
                (dz["lojistik"] / ad).write_bytes(os.urandom(30_000))
                beklenen[ad] = "BETIK"
                adlar.append(ad)
            ad = "BORDRO_202609.xlsx"
            eft_yaz(dz["ik"], ad, boyut=2_000_000, sure=3)
            beklenen[ad] = "CTM"
            adlar.append(ad)
            for ad in ("notlar.txt", "FATURA_hatali.csv", "SEVK_x.csv"):
                (dz["muhasebe" if ad != "SEVK_x.csv" else "lojistik"] / ad).write_text("x", encoding="utf-8")
                yazilan_eslesmeyen.append(ad)
            R.kontrol("Normal gün: hepsi iletildi", iletildi_bekle(adlar), f"{len(adlar)} dosya")
            bekle(lambda: o.hdb.tek("SELECT COUNT(*) FROM gonderilemeyen WHERE sebep='ESLESMEDI'")[0] >= 3, 30)
            R.kontrol("Kurala uymayan 3 dosya 'eşleşmedi' kaydında, tetiklenmedi",
                      all(not tetik(x) for x in yazilan_eslesmeyen))
            bekle(lambda: any("SEVK_x.csv" in m["govde"] for m in smtp.mailler if "lojistik@sirket.test" in m["to"]), 40,
                  mesaj="kurala bağlı mail gelmedi")
            R.kontrol("Kurala bağlı mail: lojistik'te regex'e uymayan dosya lojistik@ adresine gitti", True)
            R.kontrol("Muhasebe'deki eşleşmeyen dosya lojistik@ adresine GİTMEDİ",
                      not any("FATURA_hatali.csv" in m["govde"] for m in smtp.mailler if "lojistik@sirket.test" in m["to"]))

        # ------------------------------------------------------------ 3 ani yük
        with R.adim("3 · Ani yük: 200 dosya aynı anda"):
            adlar = [f"FATURA_20261002_{i:03d}.csv" for i in range(1, 201)]
            t0 = time.time()
            for ad in adlar:
                (dz["muhasebe"] / ad).write_bytes(ad.encode() * 50)
                beklenen[ad] = "CTM"
            iletildi_bekle(adlar, 180)
            sureler = sorted(r[0] for r in o.db.oku(
                "SELECT sure_ms FROM tetik WHERE dosya_adi LIKE 'FATURA_20261002_%' AND sure_ms IS NOT NULL"))
            p95 = sureler[int(len(sureler) * 0.95) - 1] if sureler else None
            R.kontrol("Ani yük: 200 dosya iletildi", len(sureler) == 200,
                      f"toplam {time.time() - t0:.1f} sn · hazır→iletim p95 {p95} ms · en uzun {sureler[-1] if sureler else None} ms")
            R.kontrol("Ani yükte SLA (10 sn) aşılmadı", p95 is not None and p95 < 10_000, f"p95 {p95} ms")

        # ------------------------------------------------------------ 4 Control-M kesintisi
        with R.adim("4 · Control-M kesintisi → lokal → devreyi normale al → kademeli erit"):
            ctm.durdur()
            adlar = []
            for i in range(1, 13):
                ad = f"FATURA_20261003_{i:03d}.csv"
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "CTM"
                adlar.append(ad)
                time.sleep(0.3)
            bekle(lambda: all((t := tetik(x)) and t["durum"] == "LOKALDE" for x in adlar), 120, mesaj="lokale düşmediler")
            R.kontrol("Kesintide 12 dosya kaybolmadı: lokal kayıtta", True)
            hd = o.db.tek("SELECT devre_durumu FROM hedef WHERE id=?", (h_ctm["id"],))[0]
            R.kontrol("Art arda hatada devre kesildi + KRİTİK alarm", hd == "KESILDI"
                      and bool(o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{h_ctm['id']}:devre",))), hd)
            lokal_dosyalar = list((o.veri / "lokal_kayit").rglob("*.json"))
            R.kontrol("Lokal kayıt dosyaları diskte", len(lokal_dosyalar) >= 12, f"{len(lokal_dosyalar)} dosya")
            ctm.yeniden_baslat()
            assert y.post(f"/api/hedefler/{h_ctm['id']}/devre_sifirla")[0] == 200
            assert y.post(f"/api/hedefler/{h_ctm['id']}/erit", {"islem": "baslat", "hiz": 20})[0] == 200
            R.kontrol("Erit: lokaldekilerin hepsi iletildi", iletildi_bekle(adlar, 120))
            sira = [x["govde"]["variables"][0]["FWP_DOSYA"] for x in ctm.siparisler
                    if x.get("govde", {}).get("variables") and str(x["govde"]["variables"][0].get("FWP_DOSYA", "")).startswith("FATURA_20261003_")]
            R.kontrol("Erit geliş sırasını korudu", sira == sorted(sira), sira[:5])
            R.kontrol("Lokal kayıt dosyaları eritten sonra temizlendi",
                      not list((o.veri / "lokal_kayit").rglob("*.json")))

        # ------------------------------------------------------------ 4b lokal: seçerek gönder / sil
        with R.adim("4b · Lokal birikenler: seçerek gönder · seçerek sil (süper yönetici + tutanak) · kalanı erit"):
            assert y.post(f"/api/hedefler/{h_ctm['id']}/kapat", {"mod": "KAYITLI"})[0] == 200
            adlar = [f"FATURA_20261008_{i:03d}.csv" for i in range(1, 9)]
            for ad in adlar:
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                time.sleep(0.2)
            bekle(lambda: all((t := tetik(x)) and t["durum"] == "LOKALDE" and t["lokal_dosya"] for x in adlar), 60,
                  mesaj="hedef kapalıyken lokale yazılmadılar")
            assert y.post(f"/api/hedefler/{h_ctm['id']}/ac")[0] == 200
            time.sleep(3)
            R.kontrol("Hedef açılınca lokaldekiler kendiliğinden gitmedi (erit ya da seçim bekler)",
                      all(tetik(x)["durum"] == "LOKALDE" for x in adlar))
            tid = {x: tetik(x)["id"] for x in adlar}
            y = Istemci(port)                              # yeni oturum: süper yönetici kilidi kapalı (kilit oturuma bağlı)
            assert y.giris("admin", SIFRE)[0] == 200
            k, r = y.post("/api/lokal/gonder", {"idler": [tid[adlar[0]]]})
            R.kontrol("Yeni oturumda süper yönetici kilidi kapalı: seçerek gönderme reddedildi", k == 403, r)
            assert y.post("/api/betik/kilit", {"sifre": SUPER})[0] == 200
            secilen, silinecek, kalan = adlar[:3], adlar[3:6], adlar[6:]
            k, r = y.post("/api/lokal/gonder", {"idler": [tid[x] for x in secilen]})
            R.kontrol("Seçilen 3 kayıt gönderime alındı", k == 200 and len(r.get("gonderilen") or []) == 3, r)
            for x in secilen + kalan:
                beklenen[x] = "CTM"
            R.kontrol("Seçilen 3 kayıt iletildi", iletildi_bekle(secilen, 60))
            R.kontrol("Seçilmeyen 5 kayıt lokalde bekliyor", all(tetik(x)["durum"] == "LOKALDE" for x in silinecek + kalan))
            k, r = y.post("/api/lokal/sil", {"idler": [tid[x] for x in silinecek], "neden": "kısa"})
            R.kontrol("Gerekçesiz (5 karakterden kısa) silme reddedildi", k == 400, r)
            k, r = y.post("/api/lokal/sil", {"idler": [tid[x] for x in silinecek],
                                             "neden": "saha provası: yanlış güne ait dosyalar, iş birimi onayladı"})
            R.kontrol("Seçilen 3 kayıt silindi", k == 200 and len(r.get("silinen") or []) == 3, r)
            silinen.extend(silinecek)
            tut = json.loads(Path(r["tutanak"]).read_text(encoding="utf-8")) if k == 200 else {}
            R.kontrol("Tutanak: TAMAMLANDI · kullanıcı · gerekçe · her kaydın tam dökümü",
                      tut.get("durum") == "TAMAMLANDI" and tut.get("kullanici") == "admin" and "iş birimi" in str(tut.get("neden"))
                      and {kk["tetik"]["dosya_adi"] for kk in tut.get("kayitlar", [])} == set(silinecek), Path(r.get("tutanak", "")).name)
            R.kontrol("Silinenler 'SILINDI'; lokal dosyaları arşivde; denetim + gönderilemeyen kaydı kapandı",
                      all((t := tetik(x))["durum"] == "SILINDI" and "lokal_silinen" in (t["lokal_dosya"] or "")
                          and Path(t["lokal_dosya"]).exists() for x in silinecek)
                      and bool(o.hdb.tek("SELECT 1 FROM denetim WHERE islem='LOKAL_SIL'"))
                      and all("ELLE_SILINDI" in (o.hdb.tek("SELECT cozum FROM gonderilemeyen WHERE anahtar=?", (tetik(x)["idempotency"],)) or [""])[0]
                              for x in silinecek))
            assert y.post(f"/api/hedefler/{h_ctm['id']}/erit", {"islem": "baslat", "hiz": 20})[0] == 200
            R.kontrol("Kalan 2 kayıt eritle iletildi; silinenler eritle gitmedi",
                      iletildi_bekle(kalan, 60) and all(tetik(x)["durum"] == "SILINDI" for x in silinecek))

        # ------------------------------------------------------------ 5 betik hataları
        with R.adim("5 · Betik: geçici hata (yeniden) · kalıcı hata (lokal + alarm) → betik düzeltilir → erit"):
            for ad in ("SEVK_ANK_GECICI1.csv", "SEVK_ANK_KALICI1.csv"):
                (dz["lojistik"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "BETIK"
            R.kontrol("Geçici hata yeniden denendi, iletildi", iletildi_bekle(["SEVK_ANK_GECICI1.csv"], 60))
            bekle(lambda: (t := tetik("SEVK_ANK_KALICI1.csv")) and t["durum"] == "LOKALDE", 60)
            R.kontrol("Kalıcı hata (çıkış 10): yeniden denenmedi, lokalde + alarm",
                      tetik("SEVK_ANK_KALICI1.csv")["deneme_sayisi"] == 1
                      and bool(o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"hedef:{h_betik['id']}:kalici",))))
            bekle(lambda: any("SEVK_ANK_KALICI1.csv" in m["govde"] for m in smtp.mailler if "lojistik@sirket.test" in m["to"]),
                  40, mesaj="kalıcı hata maili gelmedi")
            R.kontrol("Kalıcı hata kurala bağlı adrese maillendi", True)
            duzelt = BETIK.replace('if "KALICI" in ad:', 'if False:')
            k, r = y.put(f"/api/hedefler/{h_betik['id']}", {**betik_tanim, "ayrintilar": {**betik_tanim["ayrintilar"], "kod": duzelt}})
            R.kontrol("Betik düzeltildi (süper yönetici kilidiyle)", k == 200, r)
            assert y.post(f"/api/hedefler/{h_betik['id']}/erit", {"islem": "baslat", "hiz": 20})[0] == 200
            R.kontrol("Düzeltilen betikle erit: iletildi", iletildi_bekle(["SEVK_ANK_KALICI1.csv"], 60))

        # ------------------------------------------------------------ 6 çökmeler + bakım
        with R.adim("6 · Teslim eklentisi öldürülür · çekirdek öldürülür · bakım sürerken dosya gelir"):
            pid = o.eklenti("teslim")["pid"]
            psutil.Process(pid).kill()
            adlar = []
            for i in range(1, 6):
                ad = f"FATURA_20261004_{i:03d}.csv"
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "CTM"
                adlar.append(ad)
            bekle(lambda: (e := o.eklenti("teslim")) and e["durum"] == "CALISIYOR" and e["pid"] != pid, 90,
                  mesaj="teslim yeniden başlamadı")
            R.kontrol("Öldürülen teslim eklentisi yeniden başladı; o sırada gelenler iletildi", iletildi_bekle(adlar))
            o.proc.kill()
            o.proc.wait(30)
            time.sleep(3)
            canli = [p for p in psutil.process_iter(["cmdline"]) if str(o.baslangic) in " ".join(p.info["cmdline"] or [])]
            R.kontrol("Çekirdek ölünce eklentiler de kapandı (sahipsiz süreç yok)", not canli, len(canli))
            adlar = []
            for i in range(1, 6):
                ad = f"FATURA_20261005_{i:03d}.csv"
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "CTM"
                adlar.append(ad)
            o.cekirdek_baslat()
            bekle(lambda: all((e := o.eklenti(x)) and e["durum"] == "CALISIYOR" for x in ("tarama", "teslim", "kontrol")), 90)
            R.kontrol("Kapalıyken gelen dosyalar açılışta yakalandı ve iletildi", iletildi_bekle(adlar))
            y = Istemci(port)
            bekle(lambda: y.giris("admin", SIFRE)[0] == 200, 30)
            k, r = y.post("/api/bakim")
            R.kontrol("Bakım komutu kabul edildi", k == 200, r)
            adlar = []
            for i in range(1, 11):
                ad = f"FATURA_20261006_{i:03d}.csv"
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "CTM"
                adlar.append(ad)
            R.kontrol("Bakım sırasında gelenler iletildi", iletildi_bekle(adlar))
            son = bekle(lambda: json.loads(o.db.meta_al("son_bakim_sonucu") or "null"), 120, mesaj="bakım bitmedi")
            R.kontrol("Bakım başarıyla bitti", son.get("durum") == "TAMAM", son)

        # ------------------------------------------------------------ 7 düzgün kapanış
        with R.adim("7 · Düzgün kapanış (bekleyenler varken) → açılış"):
            adlar = []
            for i in range(1, 9):
                ad = f"FATURA_20261007_{i:03d}.csv"
                (dz["muhasebe"] / ad).write_text(ad, encoding="utf-8")
                beklenen[ad] = "CTM"
                adlar.append(ad)
            time.sleep(1.5)
            t0 = time.time()
            o.cekirdek_kapat()
            R.kontrol("Kapanış süresi", time.time() - t0 < 60, f"{time.time() - t0:.1f} sn")
            o.cekirdek_baslat()
            bekle(lambda: all((e := o.eklenti(x)) and e["durum"] == "CALISIYOR" for x in ("tarama", "teslim", "kontrol")), 90)
            R.kontrol("Kapanış sırasında bekleyenler iletildi (kayıp yok)", iletildi_bekle(adlar))
            y = Istemci(port)
            bekle(lambda: y.giris("admin", SIFRE)[0] == 200, 30)

        # ------------------------------------------------------------ 7b anomali takibi
        with R.adim("7b · Anomali: alışılmadık boyutta fatura (gölge modu → alarm + kurala bağlı mail → normal dosyayla kapanır)"):
            from eklentiler.asistan.depo import AsistanDB
            adb = AsistanDB(o.veri / "asistan.db")
            bekle(lambda: adb.tek("SELECT COUNT(*) FROM olcum WHERE tur='boyut' AND kural_id=?", (fatura_id,))[0] >= 250, 60,
                  mesaj="fatura boyut ölçümleri toplanmadı")
            n_sure = adb.tek("SELECT COUNT(*) FROM olcum WHERE tur='sure' AND kural_id=?", (fatura_id,))[0]
            R.kontrol("Asistan ölçüm topluyor (boyut + teslim süresi; dosya adı yok)", n_sure >= 200
                      and not adb.tek("SELECT 1 FROM olcum WHERE kaynak LIKE '%FATURA%'"), f"süre ölçümü {n_sure}")
            buyuk = lambda: adb.oku("SELECT * FROM oneri WHERE tur='ANOMALI' AND anahtar LIKE ? AND baslik LIKE '%büyük%'",
                                    (f"anomali:{fatura_id}:boyut:%",))
            ad = "FATURA_20261009_001.csv"
            (dz["muhasebe"] / ad).write_bytes(os.urandom(6_000_000))
            beklenen[ad] = "CTM"
            on = bekle(lambda: buyuk(), 90, mesaj="büyük dosya önerisi gelmedi")
            R.kontrol("6 MB fatura: 'alışılmadık büyük dosya' önerisi, kanıtıyla", ad in on[0]["metin"]
                      and "Normal aralık" in on[0]["kanit"], on[0]["metin"][:160])
            R.kontrol("Gölge modu (varsayılan): alarm açılmadı",
                      not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=?", (f"anomali:{fatura_id}:boyut",)))
            assert y.put("/api/asistan/ayarlar", {"anomali_alarm": True})[0] == 200
            ad = "FATURA_20261009_002.csv"
            (dz["muhasebe"] / ad).write_bytes(os.urandom(6_000_000))
            beklenen[ad] = "CTM"
            al = bekle(lambda: o.db.tek("SELECT mesaj FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{fatura_id}:boyut",)), 90,
                       mesaj="anomali alarmı açılmadı")
            R.kontrol("Anomali alarmı açık ayarla: UYARI alarmı, ikinci dosya aynı öneride toplandı",
                      ad in al[0] and len(buyuk()) == 1 and "Toplanan: 2" in buyuk()[0]["kanit"], al[0][:160])
            bekle(lambda: any(ad in m["govde"] for m in smtp.mailler if "muhasebe@sirket.test" in m["to"]), 60,
                  mesaj="anomali maili kurala bağlı adrese gelmedi")
            R.kontrol("Anomali maili kurala bağlı adrese (muhasebe@) gitti; lojistik@ adresine gitmedi",
                      not any(ad in m["govde"] for m in smtp.mailler if "lojistik@sirket.test" in m["to"]))
            ad = "FATURA_20261009_003.csv"
            (dz["muhasebe"] / ad).write_bytes(ad.encode() * 50)
            beklenen[ad] = "CTM"
            bekle(lambda: not o.db.tek("SELECT 1 FROM alarm WHERE anahtar=? AND aktif=1", (f"anomali:{fatura_id}:boyut",)), 90,
                  mesaj="normal dosya gelince alarm kapanmadı")
            R.kontrol("Normal boyutta dosya gelince anomali alarmı kendiliğinden kapandı", True)
            R.kontrol("Anomali dosyaları teslimi engellemedi (tetik yoluna karışmaz)",
                      iletildi_bekle([f"FATURA_20261009_{i:03d}.csv" for i in (1, 2, 3)], 60))

        # ------------------------------------------------------------ 8 önyüz taraması
        with R.adim("8 · Önyüz: her sayfa ve ana pencereler tarayıcıda"):
            from playwright.sync_api import sync_playwright
            gorsel = SONUC / "saha_provasi"
            shutil.rmtree(gorsel, ignore_errors=True)
            gorsel.mkdir(parents=True)
            hatalar, kotu_yanit = [], []
            with sync_playwright() as pw:
                tar = pw.chromium.launch(channel="msedge", headless=True)
                s = tar.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR").new_page()
                s.on("pageerror", lambda e: hatalar.append(str(e)))
                s.on("console", lambda m: hatalar.append(m.text) if m.type == "error" else None)
                s.on("response", lambda r: kotu_yanit.append(f"{r.status} {r.url}") if r.status >= 500 else None)
                s.goto(url + "/")
                s.locator("#g_ad").fill("admin")
                s.locator("#g_sifre").fill(SIFRE)
                s.get_by_role("button", name="Giriş yap", exact=True).click()
                s.locator("header.ust").wait_for()
                for k in ("genel", "dosyalar", "lokal", "gonderilemeyen", "dizinler", "hedefler", "ayarlar", "eklentiler",
                          "izleme", "alarmlar", "bildirimler", "denetim", "asistan"):
                    s.goto(f"{url}/#/{k}")
                    s.locator("#icerik h1").wait_for(timeout=15000)
                    s.wait_for_timeout(900)
                    s.screenshot(path=str(gorsel / f"{k}.png"), full_page=True)
                s.goto(f"{url}/#/hedefler")
                s.locator(".kart", has_text="Sevk aktarım").get_by_role("button", name="Betiği aç").click()
                s.get_by_role("dialog").wait_for()
                s.wait_for_timeout(800)
                s.screenshot(path=str(gorsel / "betik_penceresi.png"))
                s.keyboard.press("Escape")
                s.goto(f"{url}/#/dizinler")
                s.locator("tr", has_text="sevk").get_by_role("button", name="Kuralı düzenle").click()
                s.get_by_role("dialog").wait_for()
                s.wait_for_timeout(800)
                s.screenshot(path=str(gorsel / "kural_penceresi.png"))
                s.keyboard.press("Escape")
                s.goto(f"{url}/#/asistan")
                s.locator("#icerik h1").wait_for(timeout=15000)
                s.get_by_role("tab", name="Anomaliler").click()
                s.wait_for_timeout(800)
                s.screenshot(path=str(gorsel / "asistan_anomaliler.png"), full_page=True)
                s.goto(f"{url}/#/lokal")
                s.locator("#icerik h1").wait_for(timeout=15000)
                s.wait_for_timeout(800)
                s.screenshot(path=str(gorsel / "lokal_secim.png"), full_page=True)
                tar.close()
            R.kontrol("Önyüzde JavaScript hatası yok", not hatalar, hatalar[:5])
            R.kontrol("Önyüzde sunucu hatası (5xx) yok", not kotu_yanit, kotu_yanit[:5])

        # ------------------------------------------------------------ sonuç: kayıp / çift
        with R.adim("Sonuç: her dosya hedefte tek teslim"):
            teslim = Counter()
            for x in ctm.siparisler:
                g = x.get("govde") or {}
                if "variables" in g:
                    teslim[g["variables"][0]["FWP_DOSYA"]] += 1
                elif x.get("olay", "").startswith("BORDRO_"):
                    teslim[f"BORDRO_{x['olay'][7:]}.xlsx"] += 1
            for w in webapi.webhook:
                teslim[w["govde"]["dosya"]] += 1
            betik_satirlari = [json.loads(s_) for s_ in betik_kayit.read_text(encoding="utf-8").splitlines()]
            basarili = {}
            for s_ in betik_satirlari:                      # betik her denemede yazar; başarılı deneme = son deneme
                basarili[s_["ad"]] = s_
            for ad in basarili:
                teslim[ad] += 1
            kayip = sorted(x for x in beklenen if teslim[x] == 0)
            cift = {x: n for x, n in teslim.items() if n > 1}
            belirsiz = {r[0] for r in o.db.oku("SELECT dosya_adi FROM tetik WHERE belirsiz=1")}
            R.kontrol(f"Kayıp yok ({len(beklenen)} dosya)", not kayip, kayip[:10])
            R.kontrol("Çift teslim yok (olası çift işaretliler hariç)", not (set(cift) - belirsiz), cift)
            R.kontrol("Kurala uymayanlar hiçbir hedefe gitmedi", not any(teslim[x] for x in yazilan_eslesmeyen))
            R.kontrol("Lokalden elle silinenler hiçbir hedefe gitmedi (yeniden başlatmalar dahil)",
                      len(silinen) == 3 and not any(teslim[x] for x in silinen)
                      and all(tetik(x)["durum"] == "SILINDI" for x in silinen), silinen)

        # ------------------------------------------------------------ loglar, kaynak, boyut
        with R.adim("Loglar, kaynak kullanımı, veritabanı boyutu"):
            hatali, beklenen_hata = [], []
            for f in sorted(o.loglar.glob("*.log")):
                for satir in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    if re.search(r"\| (ERROR|CRITICAL) ", satir) or "Traceback" in satir:
                        # 6. adımda teslim eklentisi bilerek öldürüldü: gözetmenin 'düştü' kaydı beklenen
                        (beklenen_hata if "teslim düştü" in satir else hatali).append(f"{f.name}: {satir[:300]}")
            R.kontrol("Loglarda beklenmeyen ERROR / Traceback yok", not hatali,
                      f"{len(hatali)} satır · " + " || ".join(hatali[:6]) + f" · beklenen (bilerek öldürülen eklenti): {len(beklenen_hata)}")
            if kaynak.ornekler:
                cpu = [x["cpu_yuzde"] for x in kaynak.ornekler]
                mb = [x["bellek_mb"] for x in kaynak.ornekler]
                R.kontrol("Kaynak kullanımı (tüm FileWatcherPro süreçleri)", True,
                          f"CPU ortalama %{statistics.mean(cpu):.1f} (tek çekirdek) · en yüksek %{max(cpu):.1f} · "
                          f"bellek en yüksek {max(mb):.0f} MB · süreç {kaynak.ornekler[-1]['surec']}")
            boyut = {f.name: round(f.stat().st_size / 2 ** 20, 2) for f in o.veri.glob("*.db")}
            R.kontrol("Veritabanı boyutları (MB)", all(v < 50 for v in boyut.values()), boyut)
    finally:
        kaynak.dur.set()
        try:
            o.cekirdek_kapat()
        except Exception:  # noqa: BLE001
            pass
        ctm.durdur()
        webapi.durdur()
        smtp.durdur()
        SONUC.mkdir(parents=True, exist_ok=True)
        cikti = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "sure_sn": round(time.time() - R.t0, 1),
                 "adimlar": R.adimlar, "kontroller": R.kontroller,
                 "ozet": {"gecti": sum(k["sonuc"] == "GEÇTİ" for k in R.kontroller),
                          "kaldi": sum(k["sonuc"] == "KALDI" for k in R.kontroller),
                          "adim_hatasi": sum(a["sonuc"] == "HATA" for a in R.adimlar)},
                 "kaynak": kaynak.ornekler}
        (SONUC / "saha_provasi.json").write_text(json.dumps(cikti, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nÖZET: {cikti['ozet']} · {cikti['sure_sn']} sn · rapor: {SONUC / 'saha_provasi.json'}")
        if not a.sakla:
            o.kapat()
            shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not cikti["ozet"]["kaldi"] and not cikti["ozet"]["adim_hatasi"] else 1


if __name__ == "__main__":
    sys.exit(main())
