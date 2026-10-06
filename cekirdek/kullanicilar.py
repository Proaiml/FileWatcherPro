"""Önyüz kullanıcıları ve rolleri (U10: yetki + denetim).

Roller (her biri bir öncekinin yetkilerini de içerir):
  IZLEYICI  — her şeyi görür, hiçbir şeyi değiştiremez.
  OPERATOR  — Control-M (hedef) aç/kapat, kural aç/kapat, kademeli erit, motor durdur/başlat,
              dizini şimdi dene, eklenti başlat/durdur/yeniden başlat, alarm onayla, bakım.
  YONETICI  — dizin/kural/hedef ekle-değiştir-sil, ayarlar.

Dosya: config/kullanicilar.json (başlangıç dosyasının yanında). Şifreler PBKDF2-SHA256 (200 000 tur,
rastgele tuz) ile saklanır; dosyayı açan biri şifreyi okuyamaz. Girişte düz şifre yazılır.

İlk kurulum: hiç kullanıcı yoksa kontrol eklentisi 'admin' / 'admin' hesabını (YÖNETİCİ) oluşturur.
Bu hesap 'varsayılan şifre' olarak işaretlenir; önyüzde şifre değiştirilene kadar uyarı ve alarm görünür.
Önyüz: üst çubuk → Şifre değiştir.  Komut satırı: py -3.11 araclar\\kullanici.py ekle <ad> <ROL>
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

ROLLER = ("IZLEYICI", "OPERATOR", "YONETICI")
TUR = 200_000
ASGARI_SIFRE = 10
VARSAYILAN_AD = VARSAYILAN_SIFRE = "admin"


def rol_yeterli(rol: str, gereken: str) -> bool:
    return ROLLER.index(rol) >= ROLLER.index(gereken)


def sifre_ozeti(sifre: str, tuz: bytes = None) -> str:
    tuz = tuz or secrets.token_bytes(16)
    ozet = hashlib.pbkdf2_hmac("sha256", sifre.encode("utf-8"), tuz, TUR)
    return f"pbkdf2_sha256${TUR}${tuz.hex()}${ozet.hex()}"


def sifre_dogru(sifre: str, kayit: str) -> bool:
    try:
        _, tur, tuz, ozet = kayit.split("$")
        yeni = hashlib.pbkdf2_hmac("sha256", sifre.encode("utf-8"), bytes.fromhex(tuz), int(tur))
        return hmac.compare_digest(yeni.hex(), ozet)
    except (ValueError, TypeError):
        return False


def _sifre_kurali(sifre: str):
    if len(sifre) < ASGARI_SIFRE:
        raise ValueError(f"şifre en az {ASGARI_SIFRE} karakter olmalı")
    if sifre.casefold() == VARSAYILAN_SIFRE:
        raise ValueError("varsayılan şifre yeni şifre olarak kullanılamaz")


class Kullanicilar:
    def __init__(self, dosya: Path):
        self.dosya = Path(dosya)
        self._kilit = threading.Lock()

    def _oku(self) -> dict:
        try:
            return json.loads(self.dosya.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _yaz(self, veri: dict):
        self.dosya.parent.mkdir(parents=True, exist_ok=True)
        gecici = self.dosya.with_suffix(".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, self.dosya)

    def ekle(self, ad: str, sifre: str, rol: str):
        ad = str(ad).strip()
        if not ad or any(c in ad for c in ' "\'<>&'):
            raise ValueError("kullanıcı adı boş olamaz ve boşluk/özel karakter içeremez")
        rol = str(rol).upper()
        if rol not in ROLLER:
            raise ValueError(f"rol şunlardan biri olmalı: {', '.join(ROLLER)}")
        _sifre_kurali(sifre)
        with self._kilit:
            v = self._oku()
            v[ad] = {"rol": rol, "sifre": sifre_ozeti(sifre)}
            self._yaz(v)

    def varsayilan_ekle(self) -> bool:
        """'admin' / 'admin' (YÖNETİCİ, varsayılan şifre işaretli). Bu adla kullanıcı varsa dokunmaz."""
        with self._kilit:
            v = self._oku()
            if VARSAYILAN_AD in v:
                return False
            v[VARSAYILAN_AD] = {"rol": "YONETICI", "sifre": sifre_ozeti(VARSAYILAN_SIFRE), "varsayilan": True}
            self._yaz(v)
            return True

    def ilk_kurulum(self) -> bool:
        """Hiç kullanıcı yoksa varsayılan hesabı oluşturur."""
        return not self._oku() and self.varsayilan_ekle()

    def sifre_degistir(self, ad: str, eski: str, yeni: str):
        with self._kilit:
            v = self._oku()
            k = v.get(ad)
            if k is None or not sifre_dogru(eski, k["sifre"]):
                raise ValueError("mevcut şifre hatalı")
            _sifre_kurali(yeni)
            k["sifre"] = sifre_ozeti(yeni)
            k.pop("varsayilan", None)
            self._yaz(v)

    def sil(self, ad: str):
        with self._kilit:
            v = self._oku()
            if v.pop(ad, None) is None:
                raise ValueError("kullanıcı yok")
            self._yaz(v)

    def dogrula(self, ad: str, sifre: str):
        """Doğruysa rolü, değilse None döner (sabit süreli karşılaştırma)."""
        k = self._oku().get(str(ad))
        if k is None:
            sifre_dogru(sifre, sifre_ozeti("zamanlama-esitleme"))   # kullanıcı yokken de aynı süre
            return None
        return k["rol"] if sifre_dogru(sifre, k["sifre"]) else None

    def varsayilan_mi(self, ad: str) -> bool:
        return bool(self._oku().get(ad, {}).get("varsayilan"))

    def varsayilan_kullananlar(self) -> list:
        return [a for a, k in self._oku().items() if k.get("varsayilan")]

    def liste(self) -> list:
        return [{"ad": a, "rol": k["rol"], "varsayilan_sifre": bool(k.get("varsayilan"))} for a, k in sorted(self._oku().items())]

    def var_mi(self) -> bool:
        return bool(self._oku())
