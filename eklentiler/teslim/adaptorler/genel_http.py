"""Genel HTTP (webhook) adaptörü: tetiği JSON olarak POST eder. Control-M dışındaki hedefler için
evrensel başlangıç noktası.

Hedef 'ayrintilar': {"kimlik_turu": "yok" | "bearer" | "apikey" | "basic", "basliklar": {"X-Ozel": "…"},
                     "anahtar_ref": "dpapi:…", "anahtar_basligi": "Authorization", "anahtar_on_eki": "Bearer ",
                     "kullanici": "…", "sifre_ref": "dpapi:…" (basic), "tls_dogrula": true, "saglik_yolu": "/health"}
Gövde: {"idempotency", "dosya_adi", "tam_yol", "dizin", "boyut", "icerik_hash", "kural", "gruplar", "is_bilgisi"}
"""
import base64
import json
import time

from cekirdek.istek_sablonu import SablonHatasi, degiskenler, olustur

from .temel import HedefAdaptoru, HttpHatasi, Sonuc, SonucTuru, http_istek, kod_siniflandir, sir_oku


class GenelHttpAdaptoru(HedefAdaptoru):
    def _basliklar(self) -> dict:
        b = dict(self.ayrinti.get("basliklar") or {})
        tur = self.ayrinti.get("kimlik_turu")
        if tur == "yok":
            return b
        if tur == "basic":
            kimlik = f"{self.ayrinti.get('kullanici', '')}:{sir_oku(self.ayrinti['sifre_ref'])[1]}"
            b["Authorization"] = "Basic " + base64.b64encode(kimlik.encode("utf-8")).decode("ascii")
            return b
        if self.ayrinti.get("anahtar_ref"):
            b[self.ayrinti.get("anahtar_basligi", "Authorization")] = \
                self.ayrinti.get("anahtar_on_eki", "Bearer ") + sir_oku(self.ayrinti["anahtar_ref"])[1]
        return b

    def gonder(self, tetik: dict, timeout: float) -> Sonuc:
        t0 = time.perf_counter()
        p = json.loads(tetik["parametreler"]) if isinstance(tetik["parametreler"], str) else tetik["parametreler"]
        yontem, url, govde = "POST", self.hedef["adres"], {"idempotency": tetik["idempotency"], **p}
        if tetik.get("istek"):
            try:
                yontem, yol, govde = olustur(tetik["istek"], degiskenler(p, tetik["idempotency"], self.ayrinti,
                                                                        tetik.get("olusturma")))
            except SablonHatasi as e:
                return Sonuc(SonucTuru.KALICI, mesaj=f"istek şablonu: {e}", sure_ms=self._sure(t0))
            url = str(self.hedef["adres"]).rstrip("/") + yol
        try:
            b = self._basliklar()
            b["X-Idempotency-Key"] = tetik["idempotency"]
            kod, _, metin = http_istek(url, yontem, govde, b, timeout, bool(self.ayrinti.get("tls_dogrula", True)))
        except HttpHatasi as e:
            return Sonuc(e.tur, mesaj=str(e), sure_ms=self._sure(t0))
        except (ValueError, KeyError) as e:
            return Sonuc(SonucTuru.KALICI, mesaj=f"yapılandırma hatası: {e}", sure_ms=self._sure(t0))
        return Sonuc(kod_siniflandir(kod), kod, f"HTTP {kod}", None, self._sure(t0))

    def saglik(self, timeout: float) -> tuple:
        try:
            yol = self.ayrinti.get("saglik_yolu")
            url = str(self.hedef["adres"]).rstrip("/") + yol if yol else self.hedef["adres"]
            kod, _, _ = http_istek(url, "HEAD", None, self._basliklar(), timeout,
                                   bool(self.ayrinti.get("tls_dogrula", True)))
            return kod < 500, f"HTTP {kod}"
        except HttpHatasi as e:
            return False, str(e)
        except (ValueError, KeyError) as e:
            return False, f"yapılandırma hatası: {e}"
