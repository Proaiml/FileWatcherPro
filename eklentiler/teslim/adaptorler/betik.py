"""Betik adaptörü: tetiği kullanıcının Python / PowerShell betiğini çalıştırarak iletir (cekirdek.betik).

Hedef 'ayrintilar': {"dil": "python" | "powershell", "kod": "…", "sirlar": [{"ad": "API_ANAHTARI", "ref": "dpapi:…"}],
                     "surum", "degistiren", "degisme_zamani"}
Hedefin timeout_sn'i betiğin zaman aşımı, esz_cagri_ust'ü aynı anda en fazla çalışma sayısıdır.
Kuralın isteği: {"parametreler": {"AD": "şablon {tarih}"}} → FWP_P_<AD>.
"""
import json
import time
from pathlib import Path

from cekirdek import betik
from cekirdek.istek_sablonu import SablonHatasi, degiskenler, parametre_olustur

from .temel import HedefAdaptoru, Sonuc, SonucTuru, sir_oku


def betik_kok(hedef_id) -> Path:
    from cekirdek.ayarlar import baslangic_oku
    return baslangic_oku().veri / "betik" / str(hedef_id)


def sir_degerleri(ayrinti: dict) -> dict:
    """{AD: düz değer}. Okunamayan gizli değer ValueError (hangisi olduğu söylenir, değeri değil)."""
    d = {}
    for s in ayrinti.get("sirlar") or []:
        try:
            d[s["ad"]] = sir_oku(s["ref"])[1]
        except Exception as e:  # noqa: BLE001 - DPAPI / env / wincred hatası tek tür mesaja çevrilir
            raise ValueError(f"gizli değer '{s.get('ad')}' okunamadı: {e}") from None
    return d


class BetikAdaptoru(HedefAdaptoru):
    def __init__(self, hedef: dict, kok: Path = None):
        super().__init__(hedef)
        self.kok = kok

    def _kok(self) -> Path:
        if self.kok is None:
            self.kok = betik_kok(self.hedef.get("id") or "yeni")
        return self.kok

    def gonder(self, tetik: dict, timeout: float) -> Sonuc:
        t0 = time.perf_counter()
        p = json.loads(tetik["parametreler"]) if isinstance(tetik["parametreler"], str) else (tetik["parametreler"] or {})
        deg = degiskenler(p, tetik["idempotency"], self.ayrinti, tetik.get("olusturma"))
        try:
            parametreler = parametre_olustur(tetik.get("istek") or {}, deg)
        except SablonHatasi as e:
            return Sonuc(SonucTuru.KALICI, mesaj=f"ek değerler: {e}", sure_ms=self._sure(t0))
        try:
            sirlar = sir_degerleri(self.ayrinti)
        except ValueError as e:
            return Sonuc(SonucTuru.KALICI, mesaj=str(e), sure_ms=self._sure(t0))
        ortam, stdin = betik.ortam_ve_stdin(deg, p.get("gruplar"), parametreler, sirlar, deneme=bool(tetik.get("deneme")),
                                            deneme_sayisi=int(tetik.get("deneme_sayisi") or 0) + 1)
        s = betik.calistir(self._kok(), self.ayrinti.get("dil"), self.ayrinti.get("kod") or "", ortam, stdin,
                           timeout, sirlar.values())
        cevap = {"cikis_kodu": s.cikis_kodu, "stdout": s.stdout[-2000:], "stderr": s.stderr[-2000:]}
        return Sonuc(s.tur, None, s.mesaj, cevap, s.sure_ms)

    def saglik(self, timeout: float) -> tuple:
        dil = self.ayrinti.get("dil")
        yol = betik.python_yolu() if dil == "python" else betik.powershell_yolu()
        if not Path(yol).exists():
            return False, f"yorumlayıcı bulunamadı: {yol}"
        return True, f"{'Python' if dil == 'python' else 'PowerShell'} hazır; betiğin bağlandığı sistem yoklanmaz"
