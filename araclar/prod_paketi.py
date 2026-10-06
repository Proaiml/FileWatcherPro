"""Prod paketi: sunucuya kopyalanacak temiz zip'i üretir ve paketlemeden önce denetler.

Pakete GİRMEZ (sunucuda sıfırdan oluşur ya da orada belirlenir):
  veri\\ (canli.db, hata.db, asistan.db, lokal kayıt) — içindeki şifreler DPAPI ile BU makineye bağlı şifreli; başka
         sunucuda çözülemez, ayrıca geliştirme hedefleri / dizinleri taşınmamalı
  loglar\\, testler\\_sonuc\\, __pycache__, *.pyc, *.db*, *.log
  config\\kullanicilar.json (sunucuda ilk açılışta admin / admin oluşur, hemen değiştirilir)
  config\\betik_sifresi.json (süper yönetici şifresi sunucuda betik_sifresi.bat ile belirlenir)
  tasarim\\ (tasarım onayı görselleri; --tasarim ile eklenir), dagitim\\ (önceki paketler)

Denetimler (biri kalırsa paket üretilmez): tüm .py dosyaları derlenir; .bat dosyaları CRLF; baslangic.json geçerli
ve önyüz yalnız bu sunucuya açık (127.0.0.1); pakette veritabanı / log / kullanıcı / şifre dosyası yok.
Zip'in içine MANIFEST_SHA256.txt yazılır (her dosyanın SHA-256 özeti ve boyutu): sunucuda kopyanın bozulmadığı
`py -3.11 araclar\\prod_paketi.py --dogrula <klasör>` ile denetlenir.

Kullanım:  py -3.11 araclar\\prod_paketi.py [--cikti <zip>] [--tasarim]
           py -3.11 araclar\\prod_paketi.py --dogrula C:\\FileWatcherPro
"""
import argparse
import hashlib
import json
import py_compile
import sys
import tempfile
import time
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
MANIFEST = "MANIFEST_SHA256.txt"
DISLA_KLASOR = {"veri", "loglar", "dagitim", "__pycache__", ".pytest_cache", ".git"}
DISLA_YOL = {("testler", "_sonuc"), ("config", "kullanicilar.json"), ("config", "betik_sifresi.json")}
DISLA_UZANTI = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log", ".tmp"}
YASAK_AD = ("canli.db", "hata.db", "asistan.db", "kullanicilar.json", "betik_sifresi.json")


def _disla(goreli: Path, tasarim: bool) -> bool:
    p = goreli.parts
    if any(x in DISLA_KLASOR for x in p[:-1]) or (not tasarim and p[0] == "tasarim"):
        return True
    if any(p[:len(d)] == d for d in DISLA_YOL):
        return True
    return goreli.suffix.lower() in DISLA_UZANTI or goreli.name.endswith((".db-wal", ".db-shm"))


def dosyalar(tasarim=False) -> list:
    return sorted(f.relative_to(KOK) for f in KOK.rglob("*") if f.is_file() and not _disla(f.relative_to(KOK), tasarim))


def _ozet(yol: Path) -> str:
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()


def denetle(liste) -> list:
    sorunlar = []
    with tempfile.TemporaryDirectory() as tmp:
        for g in liste:
            if g.suffix == ".py":
                try:
                    py_compile.compile(str(KOK / g), cfile=str(Path(tmp) / "x.pyc"), doraise=True)
                except py_compile.PyCompileError as e:
                    sorunlar.append(f"derlenmiyor: {g}: {e.msg.strip()[:200]}")
    for g in liste:
        if g.suffix.lower() == ".bat":
            b = (KOK / g).read_bytes()
            if b.count(b"\n") != b.count(b"\r\n"):
                sorunlar.append(f".bat dosyası CRLF değil (cmd yanlış okuyabilir): {g}")
        if g.name.lower() in YASAK_AD or g.suffix.lower() in DISLA_UZANTI:
            sorunlar.append(f"pakete girmemesi gereken dosya: {g}")
    try:
        b = json.loads((KOK / "config" / "baslangic.json").read_text(encoding="utf-8"))
        if b.get("kontrol_adres") not in ("127.0.0.1", "localhost"):
            sorunlar.append(f"config\\baslangic.json: önyüz ağa açık ({b.get('kontrol_adres')}); arayüz HTTP, önerilmez")
        if not any(e.get("ad") == "teslim" for e in b.get("eklentiler", [])):
            sorunlar.append("config\\baslangic.json: teslim eklentisi listede yok")
    except (OSError, ValueError) as e:
        sorunlar.append(f"config\\baslangic.json okunamadı: {e}")
    for gerekli in ("calistir.py", "requirements.txt", "KURULUM_VE_KULLANIM.md", "betik_sifresi.bat",
                    "servis/windows_servisi.py", "config/baslangic.json"):
        if Path(gerekli) not in liste:
            sorunlar.append(f"eksik: {gerekli}")
    return sorunlar


def paketle(cikti: Path, tasarim=False) -> int:
    liste = dosyalar(tasarim)
    sorunlar = denetle(liste)
    if sorunlar:
        print("PAKET ÜRETİLMEDİ — düzeltilmesi gerekenler:")
        for s in sorunlar:
            print("  -", s)
        return 1
    satirlar = []
    toplam = 0
    cikti.parent.mkdir(parents=True, exist_ok=True)
    gecici = cikti.with_suffix(".tmp")
    with zipfile.ZipFile(gecici, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for g in liste:
            z.write(KOK / g, "FileWatcherPro/" + g.as_posix())
            boy = (KOK / g).stat().st_size
            toplam += boy
            satirlar.append(f"{_ozet(KOK / g)}  {boy:>10}  {g.as_posix()}")
        z.writestr("FileWatcherPro/" + MANIFEST, "\n".join([
            f"# FileWatcherPro prod paketi · {time.strftime('%Y-%m-%d %H:%M:%S')} · {len(liste)} dosya",
            "# sha256  bayt  yol", *satirlar]) + "\n")
    gecici.replace(cikti)
    print(f"paket: {cikti}")
    print(f"  {len(liste)} dosya, {toplam / 2 ** 20:.1f} MB (sıkıştırılmış {cikti.stat().st_size / 2 ** 20:.1f} MB)")
    print("  pakette yok: veri\\, loglar\\, kullanıcılar, süper yönetici şifresi" + ("" if tasarim else ", tasarim\\"))
    print("Sunucuda: KURULUM_VE_KULLANIM.md bölüm 3 (kopyalama → paketler → betik_sifresi.bat → NSSM → doğrulama)")
    return 0


def dogrula(klasor: Path) -> int:
    m = klasor / MANIFEST
    if not m.exists():
        print(f"{MANIFEST} yok: {klasor}")
        return 1
    bozuk, eksik, n = [], [], 0
    for satir in m.read_text(encoding="utf-8").splitlines():
        if not satir or satir.startswith("#"):
            continue
        ozet, boy, yol = satir.split(None, 2)
        n += 1
        f = klasor / yol
        if not f.exists():
            eksik.append(yol)
        elif f.stat().st_size != int(boy) or _ozet(f) != ozet:
            bozuk.append(yol)
    print(f"{n} dosya denetlendi: eksik {len(eksik)}, farklı {len(bozuk)}")
    for y in (eksik + bozuk)[:20]:
        print("  -", y)
    return 0 if not eksik and not bozuk else 1


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--cikti", help="zip yolu (varsayılan: dagitim\\FileWatcherPro_<zaman>.zip)")
    a.add_argument("--tasarim", action="store_true", help="tasarım onayı görsellerini de ekle")
    a.add_argument("--dogrula", metavar="KLASOR", help="kopyalanmış kurulumu manifestle karşılaştır")
    g = a.parse_args()
    if g.dogrula:
        return dogrula(Path(g.dogrula))
    cikti = Path(g.cikti) if g.cikti else KOK / "dagitim" / f"FileWatcherPro_{time.strftime('%Y%m%d_%H%M')}.zip"
    return paketle(cikti, g.tasarim)


if __name__ == "__main__":
    sys.exit(main())
