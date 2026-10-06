"""Süper yönetici (betik) şifresi: betik hedefi eklemek, değiştirmek ve çalıştırmak için ikinci kilit.

Yalnızca sunucuda belirlenir: betik_sifresi.bat (araclar\\betik_sifresi.py). Önyüzden belirlenemez ve
değiştirilemez; böylece önyüz hesabı (ör. değiştirilmemiş admin/admin) ele geçse bile betik eklenemez.

Dosya: config/betik_sifresi.json (başlangıç dosyasının yanında). İçinde şifrenin kendisi YOK; önyüz
şifreleriyle aynı yöntemle (PBKDF2-SHA256, 200 000 tur, rastgele tuz) geri çevrilemez özeti tutulur.
Dosya yoksa betik özelliği kapalıdır.
"""
import getpass
import json
import os
import time
from pathlib import Path

from .kullanicilar import ASGARI_SIFRE, VARSAYILAN_SIFRE, Kullanicilar, sifre_dogru, sifre_ozeti

DOSYA_ADI = "betik_sifresi.json"


def dosya_yolu(config_klasoru: Path) -> Path:
    return Path(config_klasoru) / DOSYA_ADI


def _oku(dosya: Path) -> dict:
    try:
        return json.loads(Path(dosya).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def tanimli_mi(dosya: Path) -> bool:
    return bool(_oku(dosya).get("ozet"))


def dogru_mu(dosya: Path, sifre: str) -> bool:
    ozet = _oku(dosya).get("ozet")
    return bool(ozet) and sifre_dogru(str(sifre or ""), ozet)


def bilgi(dosya: Path) -> dict:
    """Şifre hakkında yalnız gösterilebilir bilgi (ne zaman, kim belirledi); özet dışarı verilmez."""
    v = _oku(dosya)
    return {"tanimli": bool(v.get("ozet")), "zaman": v.get("zaman"), "belirleyen": v.get("belirleyen")}


def belirle(dosya: Path, sifre: str, kullanicilar: Kullanicilar = None, belirleyen: str = None):
    """Şifreyi belirler / değiştirir. Kurallar: en az ASGARI_SIFRE karakter, varsayılan şifre olamaz,
    önyüz kullanıcılarından birinin şifresiyle aynı olamaz (ikinci kilit ayrı olmalı)."""
    sifre = str(sifre or "")
    if len(sifre) < ASGARI_SIFRE:
        raise ValueError(f"şifre en az {ASGARI_SIFRE} karakter olmalı")
    if sifre.casefold() == VARSAYILAN_SIFRE:
        raise ValueError("varsayılan şifre kullanılamaz")
    if kullanicilar is not None:
        for kayit in kullanicilar._oku().values():
            if sifre_dogru(sifre, kayit.get("sifre", "")):
                raise ValueError("bu şifre bir önyüz kullanıcısının şifresiyle aynı; süper yönetici şifresi ayrı olmalı")
    dosya = Path(dosya)
    dosya.parent.mkdir(parents=True, exist_ok=True)
    veri = {"ozet": sifre_ozeti(sifre), "zaman": time.strftime("%Y-%m-%d %H:%M:%S"),
            "belirleyen": belirleyen or _windows_kullanicisi()}
    gecici = dosya.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, dosya)


def kaldir(dosya: Path) -> bool:
    """Şifreyi siler: betik özelliği kapanır (var olan betik hedefleri çalışmaya devam eder, değiştirilemez)."""
    try:
        Path(dosya).unlink()
        return True
    except FileNotFoundError:
        return False


def _windows_kullanicisi() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - kullanıcı adı alınamazsa kayıt yine yazılır
        return "?"
