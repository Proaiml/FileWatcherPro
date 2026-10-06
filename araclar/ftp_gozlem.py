"""Test FTP gözlem aracı (YALNIZCA OKUR): dosyalar gelirken ağ yolundan ne göründüğünü zamanıyla kaydeder.

Amaç (olay tablosu B7, F4, B4, B8): canlıya geçmeden önce gerçek FTP sunucusunda şunları ölçmek:
  * SMB listesi yeni dosyayı ve büyüyen boyutu ne kadar geç gösteriyor (liste boyutu ≠ gerçek stat boyutu süresi)
  * EFT yüklerken dosyayı açık tutuyor mu (paylaşım testi KILITLI), yükleme bitince ne kadar sonra SERBEST oluyor
  * Geçici ad kullanılıyor mu (.filepart / .part → son ada yeniden adlandırma)
  * Yarım kalan (kesik) yükleme nasıl görünüyor: boyut durur, dosya SERBEST olur ama başka iz kalır mı
  * Önerilen sabitlik penceresi W (en uzun 'büyümeden durup sonra yine büyüme' aralığı + pay)

Dizine yazmaz, dosya silmez/taşımaz. Paylaşım testi FileWatcherPro'nun kullandığının aynısıdır ve yalnızca boyutu
0,5 sn değişmeyen dosyada, milisaniyelik yapılır (EFT zaten dosyayı açık tutuyorsa sadece 'KILITLI' döner).

Kullanım:
    py -3.11 araclar\\ftp_gozlem.py "\\\\sunucu\\paylasim\\gelen" --dk 30
    py -3.11 araclar\\ftp_gozlem.py "\\\\sunucu\\a" "\\\\sunucu\\b" --dk 60 --aralik 0.5 --cikti gozlem
Çıktı: <cikti>_olaylar.csv (her gözlem satırı), <cikti>_ozet.csv (dosya başına özet) ve ekrana özet.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eklentiler.tarama.tamamlanma import SERBEST, paylasim_testi  # noqa: E402

GECICI = (".filepart", ".part", ".tmp", ".partial", ".crdownload")


class Dosya:
    def __init__(self, dizin, ad, z):
        self.dizin, self.ad, self.ilk = dizin, ad, z
        self.liste_boyut = self.stat_boyut = -1
        self.son_buyume = z
        self.buyume_araliklari = []        # büyümeden duran ve sonra yine büyüyen aralıklar (sn)
        self.bayat_sure = 0.0              # liste boyutu < gerçek boyut olduğu toplam süre
        self.bayat_en_uzun = 0.0
        self._bayat_basi = None
        self.ilk_kilitli = self.ilk_serbest = self.son_kilitli = None
        self.kalkti = None
        self.son_gorulme = z


def gozle(dizinler, sure_sn, aralik, cikti):
    olay_f = open(f"{cikti}_olaylar.csv", "w", newline="", encoding="utf-8-sig")
    ow = csv.writer(olay_f, delimiter=";")
    ow.writerow(["zaman", "dizin", "dosya", "olay", "liste_boyut", "stat_boyut", "paylasim", "not"])
    dosyalar, bilinen = {}, {}
    for d in dizinler:                     # başlangıçta var olanlar: yalnızca bilinir, ölçülmez
        try:
            bilinen[d] = {e.name for e in os.scandir(d)}
        except OSError as e:
            print(f"UYARI: {d} okunamadı: {e}")
            bilinen[d] = set()
    bitis = time.time() + sure_sn
    tur = 0
    liste_sureleri = []
    print(f"Gözlem başladı ({len(dizinler)} dizin, {sure_sn / 60:.0f} dk). Yalnızca okunuyor. Durdurmak: Ctrl+C")
    try:
        while time.time() < bitis:
            tur += 1
            for d in dizinler:
                z = time.time()
                try:
                    t0 = time.perf_counter()
                    girdiler = {e.name: e for e in os.scandir(d) if e.is_file(follow_symlinks=False)}
                    liste_sureleri.append((time.perf_counter() - t0) * 1000)
                except OSError as e:
                    ow.writerow([f"{z:.3f}", d, "", "DIZIN_HATA", "", "", "", str(e)])
                    continue
                for ad, e in girdiler.items():
                    if ad in bilinen[d] and (d, ad) not in dosyalar:
                        continue
                    k = (d, ad)
                    f = dosyalar.get(k)
                    if f is None:
                        f = dosyalar[k] = Dosya(d, ad, z)
                        ow.writerow([f"{z:.3f}", d, ad, "GORULDU", "", "", "", "geçici ad" if ad.lower().endswith(GECICI) else ""])
                    f.son_gorulme = z
                    lb = e.stat().st_size
                    try:
                        sb = os.stat(os.path.join(d, ad)).st_size
                    except OSError:
                        continue
                    if sb != f.stat_boyut or lb != f.liste_boyut:
                        if sb != f.stat_boyut and f.stat_boyut >= 0:
                            ara = z - f.son_buyume
                            if ara > aralik * 1.5:
                                f.buyume_araliklari.append(ara)
                            f.son_buyume = z
                        ow.writerow([f"{z:.3f}", d, ad, "BOYUT", lb, sb, "", ""])
                        f.liste_boyut, f.stat_boyut = lb, sb
                    if lb < sb:
                        if f._bayat_basi is None:
                            f._bayat_basi = z
                    elif f._bayat_basi is not None:
                        s = z - f._bayat_basi
                        f.bayat_sure += s
                        f.bayat_en_uzun = max(f.bayat_en_uzun, s)
                        f._bayat_basi = None
                    if z - f.son_buyume >= 0.5 and f.ilk_serbest is None:
                        sonuc, kod = paylasim_testi(os.path.join(d, ad))
                        if sonuc == SERBEST:
                            f.ilk_serbest = z
                            ow.writerow([f"{z:.3f}", d, ad, "SERBEST", lb, sb, sonuc, f"son büyümeden {z - f.son_buyume:.2f} sn sonra"])
                        else:
                            f.ilk_kilitli = f.ilk_kilitli or z
                            f.son_kilitli = z
                            if tur % 10 == 0:
                                ow.writerow([f"{z:.3f}", d, ad, "KILITLI", lb, sb, f"{sonuc}/{kod}", ""])
                for (dd, ad), f in dosyalar.items():
                    if dd == d and f.kalkti is None and ad not in girdiler:
                        f.kalkti = z
                        ow.writerow([f"{z:.3f}", d, ad, "KALKTI", f.liste_boyut, f.stat_boyut, "",
                                     "tamamlanmadan kalktı (yeniden adlandırma?)" if f.ilk_serbest is None else ""])
            olay_f.flush()
            time.sleep(aralik)
    except KeyboardInterrupt:
        print("durduruldu")
    olay_f.close()

    with open(f"{cikti}_ozet.csv", "w", newline="", encoding="utf-8-sig") as g:
        w = csv.writer(g, delimiter=";")
        w.writerow(["dizin", "dosya", "son_boyut", "yukleme_sn", "en_uzun_duraklama_sn", "liste_bayat_toplam_sn",
                    "liste_bayat_en_uzun_sn", "kilitli_goruldu", "serbest_oldu_son_buyumeden_sn", "kalkti", "gecici_ad"])
        for f in dosyalar.values():
            w.writerow([f.dizin, f.ad, f.stat_boyut, f"{f.son_buyume - f.ilk:.2f}",
                        f"{max(f.buyume_araliklari, default=0):.2f}", f"{f.bayat_sure:.2f}", f"{f.bayat_en_uzun:.2f}",
                        "evet" if f.ilk_kilitli else "hayır",
                        f"{f.ilk_serbest - f.son_buyume:.2f}" if f.ilk_serbest else "—",
                        "evet" if f.kalkti else "", "evet" if f.ad.lower().endswith(GECICI) else ""])
    ozet(list(dosyalar.values()), liste_sureleri, cikti)


def ozet(dosyalar, liste_sureleri, cikti):
    print(f"\n==== ÖZET: {len(dosyalar)} yeni dosya gözlendi")
    if liste_sureleri:
        s = sorted(liste_sureleri)
        print(f"Dizin listeleme süresi: ort {sum(s) / len(s):.0f} ms, p95 {s[int(len(s) * .95)]:.0f} ms, en uzun {s[-1]:.0f} ms")
    if not dosyalar:
        print("Bu sürede yeni dosya gelmedi; gözlemi dosya trafiği olan bir saatte tekrarlayın.")
        return
    duraklama = max((max(f.buyume_araliklari, default=0) for f in dosyalar), default=0)
    bayat = max((f.bayat_en_uzun for f in dosyalar), default=0)
    kilitli = sum(1 for f in dosyalar if f.ilk_kilitli)
    gecici = sum(1 for f in dosyalar if f.ad.lower().endswith(GECICI))
    print(f"Yükleme sırasında EFT'nin dosyayı açık tuttuğu (KILITLI görülen): {kilitli}/{len(dosyalar)}")
    print(f"Liste boyutunun gerçek boyuttan geri kaldığı en uzun süre (SMB önbelleği, F4/B7): {bayat:.2f} sn")
    print(f"Yükleme içinde en uzun duraklama (büyümeden bekleyip yine büyüdü): {duraklama:.2f} sn")
    print(f"Geçici adla gelen: {gecici}")
    print(f"Öneri: sabitlik_W_sn ≥ {max(3.0, round(max(duraklama, bayat) * 1.5 + 1, 1))} sn "
          f"(en uzun duraklama/önbellek × 1,5 + 1). KILITLI hiç görülmediyse paylaşım testi tek başına yetmez; W büyük tutulmalı.")
    print(f"Ayrıntı: {cikti}_olaylar.csv, {cikti}_ozet.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Test FTP gözlem aracı (yalnızca okur)")
    ap.add_argument("dizinler", nargs="+")
    ap.add_argument("--dk", type=float, default=30, help="gözlem süresi (dakika)")
    ap.add_argument("--aralik", type=float, default=0.5, help="tarama aralığı (sn)")
    ap.add_argument("--cikti", default="ftp_gozlem", help="çıktı dosyalarının ön adı")
    a = ap.parse_args()
    gozle(a.dizinler, a.dk * 60, a.aralik, a.cikti)
