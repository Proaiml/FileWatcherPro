"""Kuralın tetiklediği API isteği: şablon, değişkenler, doğrulama ve oluşturma.

Kural 'istek' (JSON): {"yontem": "POST", "yol": "/run/event/{ctm}/FATURA_GELDI/ODAT", "govde": "{…JSON şablonu…}"}
  * yol   : hedefin temel adresinin (ör. https://ctm:8443/automation-api) ÜSTÜNE eklenir. Değişkenler URL kodlanır.
  * govde : JSON metni; değişkenler "{dosya_adi}" gibi TIRNAK İÇİNDE yazılır, değer JSON'a uygun kaçırılır
            (ağ yolundaki ters bölü JSON'u bozmaz). Boş = gövdesiz istek.
Değişkenler: aşağıdaki yerleşikler + kuralın regex'indeki isimli gruplar (?P<ad>…). Grup adı yerleşiklerle çakışamaz.
Teslim, önyüzdeki 'kuru deneme' ve kural kaydederken yapılan doğrulama bu tek modülü kullanır: önyüzde görülen
istek, Control-M'e giden istekle birebir aynıdır.
"""
import json
import re
import time
from urllib.parse import quote

YERLESIK = {
    "dosya_adi": "Dosya adı",
    "tam_yol": "Tam yol (ağ yolu dahil)",
    "dizin": "Dizin yolu",
    "boyut": "Boyut (bayt)",
    "icerik_hash": "İçerik hash'i (xxh3-128)",
    "kimlik": "Tetik kimliği (idempotency): Control-M'de olası çifti ayırt etmek için",
    "kural": "Kural adı",
    "zaman": "Dosyanın hazır olduğu an (YYYY-AA-GG SS:DD:ss)",
    "bugun": "Bugünün tarihi (YYYYAAGG)",
    "ctm": "Hedefte tanımlı Control-M sunucusu",
}
YONTEMLER = ("POST", "PUT", "GET", "DELETE")
DESEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
AZAMI_GOVDE = 20_000


class SablonHatasi(ValueError):
    pass


def normallestir(istek) -> dict:
    if not isinstance(istek, dict):
        raise SablonHatasi("istek tanımı eksik (yöntem, yol, gövde)")
    yontem = str(istek.get("yontem") or "POST").upper().strip()
    yol = str(istek.get("yol") or "/").strip()
    govde = str(istek.get("govde") or "")
    if yontem not in YONTEMLER:
        raise SablonHatasi(f"yöntem şunlardan biri olmalı: {', '.join(YONTEMLER)}")
    if not yol.startswith("/"):
        raise SablonHatasi("yol '/' ile başlamalı (hedefin temel adresinin üstüne eklenir), ör. /run/order")
    if len(govde) > AZAMI_GOVDE:
        raise SablonHatasi(f"gövde en fazla {AZAMI_GOVDE} karakter olabilir")
    return {"yontem": yontem, "yol": yol, "govde": govde}


def dogrula(istek, gruplar=()) -> dict:
    """Kaydederken: bilinmeyen değişken, grup adı çakışması ve (örnek değerlerle) geçersiz JSON reddedilir."""
    ist = normallestir(istek)
    gruplar = set(gruplar)
    cakisan = gruplar & set(YERLESIK)
    if cakisan:
        raise SablonHatasi(f"regex grubu yerleşik değişkenle aynı adı taşıyor: {', '.join(sorted(cakisan))}; başka ad verin")
    ornek = {k: "ornek" for k in YERLESIK} | {g: "ornek" for g in gruplar}
    olustur(ist, ornek)
    return ist


def degiskenler(parametreler: dict, idempotency: str, hedef_ayrinti: dict, hazir_zamani: float = None) -> dict:
    p = parametreler or {}
    z = hazir_zamani or time.time()
    d = {"dosya_adi": p.get("dosya_adi", ""), "tam_yol": p.get("tam_yol", ""), "dizin": p.get("dizin", ""),
         "boyut": p.get("boyut", ""), "icerik_hash": p.get("icerik_hash") or "", "kimlik": idempotency or "",
         "kural": p.get("kural", ""), "zaman": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(z)),
         "bugun": time.strftime("%Y%m%d"), "ctm": (hedef_ayrinti or {}).get("ctm", "")}
    for k, v in (p.get("gruplar") or {}).items():
        if k not in YERLESIK:
            d[k] = "" if v is None else v
    return d


def _yerlestir(metin: str, deg: dict, kac) -> str:
    def f(m):
        ad = m.group(1)
        if ad not in deg:
            raise SablonHatasi(f"bilinmeyen değişken {{{ad}}}: yerleşik değişkenlerden ya da regex grubu olmalı")
        return kac(str(deg[ad]))
    return DESEN.sub(f, metin)


def olustur(istek: dict, deg: dict) -> tuple:
    """(yöntem, yol, gövde_nesnesi ya da None). Gövde geçerli JSON değilse SablonHatasi."""
    ist = normallestir(istek)
    yol = _yerlestir(ist["yol"], deg, lambda v: quote(v, safe=""))
    govde = None
    if ist["govde"].strip():
        metin = _yerlestir(ist["govde"], deg, lambda v: json.dumps(v, ensure_ascii=False)[1:-1])
        try:
            govde = json.loads(metin)
        except ValueError as e:
            raise SablonHatasi(f"gövde geçerli JSON değil: {e}") from None
    return ist["yontem"], yol, govde


# ---------------------------------------------------------------- betik hedefi: kuralın ek değerleri
# Kural 'istek' (betik hedefi): {"parametreler": {"OLAY": "FATURA_GELDI", "DONEM": "{tarih}"}}
# Her değer betiğe FWP_P_<AD> ortam değişkeni ve stdin 'parametreler' olarak gider; değişkenler kaçırılmadan yerleşir
# (betik metnine yazılmadığı için kaçırma gerekmez).
PARAMETRE_ADI = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
AZAMI_PARAMETRE = 50
AZAMI_PARAMETRE_DEGERI = 2000


def parametre_normallestir(istek) -> dict:
    if not isinstance(istek, dict):
        istek = {}
    p = istek.get("parametreler") or {}
    if not isinstance(p, dict):
        raise SablonHatasi("ek değerler AD → değer biçiminde olmalı")
    if len(p) > AZAMI_PARAMETRE:
        raise SablonHatasi(f"en fazla {AZAMI_PARAMETRE} ek değer")
    sonuc = {}
    for ad, deger in p.items():
        ad = str(ad).strip()
        if not PARAMETRE_ADI.match(ad):
            raise SablonHatasi(f"ek değer adı büyük harf, rakam ve _ olmalı (harfle başlar): {ad}")
        deger = "" if deger is None else str(deger)
        if len(deger) > AZAMI_PARAMETRE_DEGERI:
            raise SablonHatasi(f"'{ad}' değeri en fazla {AZAMI_PARAMETRE_DEGERI} karakter olabilir")
        sonuc[ad] = deger
    return {"parametreler": sonuc}


def parametre_dogrula(istek, gruplar=()) -> dict:
    ist = parametre_normallestir(istek)
    gruplar = set(gruplar)
    cakisan = gruplar & set(YERLESIK)
    if cakisan:
        raise SablonHatasi(f"regex grubu yerleşik değişkenle aynı adı taşıyor: {', '.join(sorted(cakisan))}; başka ad verin")
    parametre_olustur(ist, {k: "ornek" for k in YERLESIK} | {g: "ornek" for g in gruplar})
    return ist


def parametre_olustur(istek, deg: dict) -> dict:
    return {ad: _yerlestir(v, deg, str) for ad, v in parametre_normallestir(istek)["parametreler"].items()}
