"""Evrensel hedef arayüzü.

Her adaptör `gonder()` ile bir tetiği hedefe iletir ve sonucu dört türden biriyle bildirir:
  BASARI   — hedef işi kabul etti.
  GECICI   — bağlantı kurulamadı, 5xx, 408, 429…: deneme planına göre tekrar denenir.
  KALICI   — 4xx (yanlış klasör/iş adı, yetki…): tekrar denenmez; lokale yazılır + yapılandırma alarmı.
  BELIRSIZ — istek gönderildi ama cevap zaman aşımına uğradı: hedef işi başlatmış olabilir. Tekrar denenir
             (kayıpsızlık önceliklidir) ve tetik 'olası çift' olarak işaretlenir.

Sırlar (şifre, API anahtarı) veritabanında TUTULMAZ; referansla okunur:
  env:DEGISKEN_ADI      → ortam değişkeni
  wincred:HEDEF_ADI     → Windows Kimlik Bilgisi Yöneticisi (Genel kimlik bilgisi)
"""
import http.client
import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class SonucTuru:
    BASARI = "BASARI"
    GECICI = "GECICI"
    KALICI = "KALICI"
    BELIRSIZ = "BELIRSIZ"


@dataclass
class Sonuc:
    tur: str
    http_kodu: int = None
    mesaj: str = ""
    cevap: dict = field(default=None)
    sure_ms: int = 0
    tekrar_sonra_sn: float = None     # 429 Retry-After


# ------------------------------------------------------------------ sırlar (cekirdek.sirlar'a taşındı)
from cekirdek.sirlar import sir_oku  # noqa: E402,F401  (adaptörler buradan içe aktarır)


# ------------------------------------------------------------------ HTTP yardımcısı
class HttpHatasi(Exception):
    def __init__(self, tur, mesaj):
        super().__init__(mesaj)
        self.tur = tur


def http_istek(url: str, yontem: str, govde=None, basliklar=None, timeout: float = 4.0,
               tls_dogrula: bool = True) -> tuple:
    """(durum_kodu, başlıklar, gövde_metni). Bağlantı aşaması hatası → HttpHatasi(GECICI);
    istek gönderildikten sonraki zaman aşımı → HttpHatasi(BELIRSIZ)."""
    u = urlsplit(url)
    if u.scheme == "https":
        ctx = ssl.create_default_context()
        if not tls_dogrula:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        con = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout, context=ctx)
    else:
        con = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    yol = (u.path or "/") + (f"?{u.query}" if u.query else "")
    veri = None if govde is None else json.dumps(govde, ensure_ascii=False).encode("utf-8")
    b = {"Accept": "application/json"}
    if veri is not None:
        b["Content-Type"] = "application/json"
    b.update(basliklar or {})
    try:
        try:
            con.connect()
        except (OSError, socket.timeout) as e:
            raise HttpHatasi(SonucTuru.GECICI, f"bağlantı kurulamadı: {e}") from None
        try:
            con.request(yontem, yol, body=veri, headers=b)
        except (OSError, socket.timeout) as e:
            raise HttpHatasi(SonucTuru.BELIRSIZ, f"istek gönderilirken koptu: {e}") from None
        try:
            r = con.getresponse()
            metin = r.read().decode("utf-8", "replace")
        except socket.timeout:
            raise HttpHatasi(SonucTuru.BELIRSIZ, f"cevap {timeout:g} sn içinde gelmedi (işlenmiş olabilir)") from None
        except (OSError, http.client.HTTPException) as e:
            raise HttpHatasi(SonucTuru.BELIRSIZ, f"cevap alınırken koptu: {e}") from None
        return r.status, dict(r.getheaders()), metin
    finally:
        con.close()


def kod_siniflandir(kod: int) -> str:
    if 200 <= kod < 300:
        return SonucTuru.BASARI
    if kod in (408, 425, 429) or kod >= 500:
        return SonucTuru.GECICI
    return SonucTuru.KALICI


class HedefAdaptoru:
    def __init__(self, hedef: dict):
        self.hedef = hedef
        self.ayrinti = json.loads(hedef.get("ayrintilar") or "{}") if isinstance(hedef.get("ayrintilar"), str) \
            else dict(hedef.get("ayrintilar") or {})

    def gonder(self, tetik: dict, timeout: float) -> Sonuc:
        raise NotImplementedError

    def saglik(self, timeout: float) -> tuple:
        """(sağlıklı_mı, mesaj). Tetik göndermeden hedefin yanıt verip vermediğini yoklar."""
        raise NotImplementedError

    @staticmethod
    def _sure(t0) -> int:
        return int((time.perf_counter() - t0) * 1000)
