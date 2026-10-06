"""Control-M Automation API adaptörü.

Kaynak: BMC Control-M Automation API belgeleri (Run service / Session service).
  * İş başlatma:  POST {adres}/run/order
        {"ctm": "<sunucu>", "folder": "<klasör>", "jobs": "<iş>", "variables": [{"AD": "değer"}, ...]}
        200 → {"runId": "...", "statusURI": "..."}
  * Oturum:       POST {adres}/session/login {"username","password"} → {"token": "..."} (≈30 dk geçerli)
                  Sonraki çağrılarda "Authorization: Bearer <token>".
  * API anahtarı: "x-api-key: <anahtar>" (yeni sürümler).
  * Hata gövdesi: {"errors": [{"message": "...", "id": "..."}]}
  * Bilinen tuhaflık: süresi dolmuş token bazı çağrılarda 401 yerine HTTP 500 ve
    "Session token is invalid or expired" mesajı döndürebilir → bu durumda da yeniden oturum açılır.

Hedef 'ayrintilar' (JSON):
  {"ctm": "ctmsunucu", "kimlik_turu": "token" | "apikey" | "yok",
   "kullanici": "kullanici_adi", "sifre_ref": "env:FWP_CTM_SIFRE" | "wincred:FileWatcherPro/ctm",
   "apikey_ref": "env:FWP_CTM_ANAHTAR", "tls_dogrula": true}
Kural 'is_bilgisi' (JSON): {"folder": "...", "jobs": "...", "degiskenler": {"SABIT": "değer"}}
"""
import json
import threading
import time

from cekirdek.istek_sablonu import SablonHatasi, degiskenler, olustur

from .temel import HedefAdaptoru, HttpHatasi, Sonuc, SonucTuru, http_istek, kod_siniflandir, sir_oku

TOKEN_OMRU_SN = 25 * 60        # 30 dk'lık oturumu süresi dolmadan yenile


class ControlMAdaptoru(HedefAdaptoru):
    def __init__(self, hedef: dict):
        super().__init__(hedef)
        self.adres = str(hedef["adres"]).rstrip("/")
        self.kimlik_turu = self.ayrinti.get("kimlik_turu", "token")
        self.tls = bool(self.ayrinti.get("tls_dogrula", True))
        self._token = None
        self._token_zamani = 0.0
        self._kilit = threading.Lock()

    # ------------------------------------------------------------ kimlik
    def _basliklar(self, timeout, yenile=False) -> dict:
        if self.kimlik_turu == "yok":
            return {}
        if self.kimlik_turu == "apikey":
            return {"x-api-key": sir_oku(self.ayrinti["apikey_ref"])[1]}
        with self._kilit:
            if yenile or self._token is None or time.time() - self._token_zamani > TOKEN_OMRU_SN:
                self._giris(timeout)
            return {"Authorization": f"Bearer {self._token}"}

    def _giris(self, timeout):
        kul_ref, sifre = sir_oku(self.ayrinti["sifre_ref"])
        kullanici = self.ayrinti.get("kullanici") or kul_ref
        kod, _, metin = http_istek(f"{self.adres}/session/login", "POST",
                                   {"username": kullanici, "password": sifre}, timeout=timeout, tls_dogrula=self.tls)
        if kod != 200:
            raise HttpHatasi(kod_siniflandir(kod), f"oturum açılamadı: HTTP {kod} {_hata_mesaji(metin)}")
        self._token = json.loads(metin)["token"]
        self._token_zamani = time.time()

    # ------------------------------------------------------------ gönderim
    def istek_govdesi(self, tetik: dict) -> dict:
        p = json.loads(tetik["parametreler"]) if isinstance(tetik["parametreler"], str) else tetik["parametreler"]
        isb = p.get("is_bilgisi") or {}
        degiskenler = dict(isb.get("degiskenler") or {})
        degiskenler.update({k.upper(): v for k, v in (p.get("gruplar") or {}).items()})
        degiskenler.update({"FWP_DOSYA": p["dosya_adi"], "FWP_YOL": p["tam_yol"],
                            "FWP_KIMLIK": tetik["idempotency"]})
        govde = {"ctm": self.ayrinti.get("ctm", ""), "folder": isb.get("folder", ""),
                 "variables": [{k: str(v)} for k, v in degiskenler.items()]}
        if isb.get("jobs"):
            govde["jobs"] = isb["jobs"]
        return govde

    def istek_hazirla(self, tetik: dict) -> tuple:
        """(yöntem, tam adres, gövde). Kuralın isteği varsa o (şablon + değişkenler); yoksa eski run/order."""
        if tetik.get("istek"):
            p = json.loads(tetik["parametreler"]) if isinstance(tetik["parametreler"], str) else tetik["parametreler"]
            yontem, yol, govde = olustur(tetik["istek"], degiskenler(p, tetik["idempotency"], self.ayrinti,
                                                                    tetik.get("olusturma")))
            return yontem, f"{self.adres}{yol}", govde
        return "POST", f"{self.adres}/run/order", self.istek_govdesi(tetik)

    def gonder(self, tetik: dict, timeout: float) -> Sonuc:
        t0 = time.perf_counter()
        try:
            yontem, url, govde = self.istek_hazirla(tetik)
        except SablonHatasi as e:                         # kural isteği bozuk: yeniden denemek düzeltmez
            return Sonuc(SonucTuru.KALICI, mesaj=f"istek şablonu: {e}", sure_ms=self._sure(t0))
        try:
            for deneme in (1, 2):                            # 2. deneme yalnızca token yenilemesi için
                b = self._basliklar(timeout, yenile=deneme == 2)
                b["X-Idempotency-Key"] = tetik["idempotency"]
                kod, bas, metin = http_istek(url, yontem, govde, b, timeout, self.tls)
                if self.kimlik_turu == "token" and deneme == 1 and _token_suresi_doldu(kod, metin):
                    continue
                break
        except HttpHatasi as e:
            return Sonuc(e.tur, mesaj=str(e), sure_ms=self._sure(t0))
        except (ValueError, KeyError) as e:        # sır bulunamadı / yapılandırma eksik
            return Sonuc(SonucTuru.KALICI, mesaj=f"yapılandırma hatası: {e}", sure_ms=self._sure(t0))
        tur = kod_siniflandir(kod)
        cevap = _json(metin)
        if tur == SonucTuru.BASARI:
            ozet = f"runId={cevap['runId']}" if cevap.get("runId") else f"HTTP {kod}"
            return Sonuc(tur, kod, ozet, cevap, self._sure(t0))
        tekrar = None
        if kod == 429:
            try:
                tekrar = float(bas.get("Retry-After", ""))
            except ValueError:
                tekrar = None
        return Sonuc(tur, kod, f"HTTP {kod}: {_hata_mesaji(metin)}", cevap, self._sure(t0), tekrar)

    def saglik(self, timeout: float) -> tuple:
        """Tetik göndermeden yoklama: token türünde oturum açma, diğerlerinde sunucu listesi."""
        try:
            if self.kimlik_turu == "token":
                self._basliklar(timeout, yenile=True)
                return True, "oturum açılabiliyor"
            kod, _, metin = http_istek(f"{self.adres}/config/servers", "GET", None, self._basliklar(timeout),
                                       timeout, self.tls)
            if kod in (401, 403):
                return False, f"kimlik reddedildi (HTTP {kod}): API anahtarını / kimlik türünü kontrol edin"
            return 200 <= kod < 300, f"HTTP {kod}"
        except HttpHatasi as e:
            return False, str(e)
        except (ValueError, KeyError) as e:
            return False, f"yapılandırma hatası: {e}"


def _json(metin):
    try:
        v = json.loads(metin)
        return v if isinstance(v, dict) else {"veri": v}
    except (ValueError, TypeError):
        return {"ham": (metin or "")[:500]}


def _hata_mesaji(metin) -> str:
    v = _json(metin)
    hatalar = v.get("errors") if isinstance(v, dict) else None
    if isinstance(hatalar, list) and hatalar:
        return "; ".join(str(h.get("message", h)) for h in hatalar)[:300]
    return str(v.get("message") or v.get("ham") or "")[:300]


def _token_suresi_doldu(kod, metin) -> bool:
    return kod == 401 or (kod == 500 and "token is invalid or expired" in (metin or "").lower())
