"""Kural eşleşme: uzantı ön filtresi + dosya adı regex'i.

Uzantı: adın SON '.' işaretinden sonraki kısmı, harf duyarsız, izinli uzantılar KÜMESİNDE aranır.
Ad içinde alt dize araması yapılmaz (demo koddaki `".csv" in ad` hatası: rapor.csv.filepart ve
a.csv.bak eşleşiyordu, A.TXT eşleşmiyordu).

Regex: dosya adına TAM eşleşme (fullmatch); varsayılan harf duyarsız. İsimli gruplar
((?P<tarih>\\d{8}) gibi) tetik parametresi olarak Control-M'e gider.

Geçici yükleme adları (.filepart / .part): 'parca_dikkate_al' açıksa, geçici uzantı atıldıktan sonra
kalan ad kurala uyuyorsa dosya 'yükleniyor' olarak izlenir; kendisi asla tetiklenmez.
"""
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field

AZAMI_DESEN = 1000


class RegexHatasi(ValueError):
    pass


def son_ek(ad: str) -> str:
    """'Rapor.CSV' → '.csv'; 'a.csv.bak' → '.bak'; 'README' → ''; '.gizli' → ''."""
    i = ad.rfind(".")
    return ad[i:].casefold() if i > 0 else ""


def ad_anahtari(ad: str) -> str:
    """Windows dosya adları harf duyarsızdır: aynı dizinde 'A.csv' ile 'a.csv' aynı dosyadır."""
    return ad.casefold()


def python_bicimi(desen: str) -> str:
    """JavaScript/.NET/PCRE isimli grup yazımı (?<ad>…) → Python (?P<ad>…). Geriye bakış (?<= (?<! değişmez."""
    return re.sub(r"\(\?<(?![=!])([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", desen) if isinstance(desen, str) else desen


def regex_derle(desen: str, harf_duyarsiz: bool = True) -> re.Pattern:
    desen = python_bicimi(desen)
    if not isinstance(desen, str) or not desen.strip():
        raise RegexHatasi("regex boş olamaz")
    if len(desen) > AZAMI_DESEN:
        raise RegexHatasi(f"regex en fazla {AZAMI_DESEN} karakter olabilir")
    try:
        return re.compile(desen, re.IGNORECASE if harf_duyarsiz else 0)
    except re.error as e:
        raise RegexHatasi(f"regex geçersiz: {e}") from None


_GUVENLIK_KODU = r"""
import json, re, sys
d = json.loads(sys.stdin.read())
p = re.compile(d["desen"], re.IGNORECASE if d["hd"] else 0)
for s in d["dizgiler"]:
    p.fullmatch(s)
print("ok")
"""


def _zorlayici_dizgiler(desen: str, ornekler) -> list:
    harfler = {c for c in desen if c.isalnum()} | {"a", "0", "_", "-", "."}
    dizgiler = []
    for c in sorted(harfler):
        dizgiler += [c * 250 + "!", c * 250]
    return dizgiler + [str(o) for o in ornekler] + ["x" * 255]


def regex_guvenlik_testi(desen: str, harf_duyarsiz: bool = True, ornekler=(), sure: float = 3.0):
    """K7: aşırı yavaş (geri izleme patlaması yapan) regex'i yakalar. Deneme AYRI süreçte yapılır;
    süre aşılırsa süreç öldürülür ve RegexHatasi fırlatılır. Tarayıcı bu kontrolden geçmemiş
    regex'i hiç çalıştırmaz (kurallar önyüzden kaydedilirken çağrılır)."""
    desen = python_bicimi(desen)
    regex_derle(desen, harf_duyarsiz)
    girdi = json.dumps({"desen": desen, "hd": bool(harf_duyarsiz),
                        "dizgiler": _zorlayici_dizgiler(desen, ornekler)})
    try:
        r = subprocess.run([sys.executable, "-c", _GUVENLIK_KODU], input=girdi, capture_output=True,
                           text=True, timeout=sure, creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        raise RegexHatasi(f"regex çok yavaş: {sure:g} sn içinde bitmedi (iç içe tekrar, örn. (a+)+). "
                          f"Deseni sadeleştirin.") from None
    if r.returncode != 0 or r.stdout.strip() != "ok":
        raise RegexHatasi(f"regex denenemedi: {r.stderr.strip()[-200:]}")


_DENE_KODU = r"""
import json, re, sys
d = json.loads(sys.stdin.read())
p = re.compile(d["desen"], re.IGNORECASE if d["hd"] else 0)
s = []
for ad in d["adlar"]:
    m = p.fullmatch(ad)
    s.append({"ad": ad, "eslesti": bool(m), "gruplar": m.groupdict() if m else {}})
sys.stdout.write(json.dumps(s))
"""


def regex_dene(desen: str, harf_duyarsiz: bool, adlar, sure: float = 2.0) -> list:
    """Önyüzdeki canlı deneme için: her ad için eşleşme ve isimli gruplar. Kaydedilmemiş (henüz güvenlik testinden
    geçmemiş) bir desen çalıştırıldığı için eşleştirme AYRI süreçte, süre sınırıyla yapılır: geri izleme patlaması
    yapan bir desen kontrol arayüzünü kilitleyemez (güvenlik taraması 2026-10-01)."""
    desen = python_bicimi(desen)
    regex_derle(desen, harf_duyarsiz)                                  # söz dizimi ve uzunluk burada denetlenir
    adlar = [str(a)[:1024] for a in adlar][:200]
    girdi = json.dumps({"desen": desen, "hd": bool(harf_duyarsiz), "adlar": adlar})
    try:
        r = subprocess.run([sys.executable, "-I", "-S", "-c", _DENE_KODU], input=girdi, capture_output=True, text=True,
                           encoding="utf-8", timeout=sure, creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        raise RegexHatasi(f"regex çok yavaş: {sure:g} sn içinde bitmedi (iç içe tekrar, örn. (a+)+). Deseni sadeleştirin.") from None
    if r.returncode != 0:
        raise RegexHatasi(f"regex denenemedi: {r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)


@dataclass
class Kural:
    id: int
    ad: str
    desen: re.Pattern
    hedef_id: int
    sira: int
    aktif: bool = True
    kapatma_modu: str = "KAYITLI"
    is_bilgisi: dict = field(default_factory=dict)
    istek: dict = None


@dataclass
class DizinKurallari:
    """Bir dizinin eşleşme bilgisi. Değişmez nesne gibi kullanılır: yapılandırma değişince
    yenisi kurulup tek atamayla değiştirilir (yarım döngüde kural değişmez)."""
    dizin_id: int
    yol: str
    uzantilar: frozenset          # boş = hepsi
    kurallar: tuple               # sıraya göre
    parca_uzantilari: frozenset
    parca_dikkate_al: bool
    coklu: str = "ilk"            # 'ilk' | 'hepsi'

    def uzanti_uygun(self, ad: str) -> bool:
        return not self.uzantilar or son_ek(ad) in self.uzantilar

    def parca_ic_adi(self, ad: str):
        """Geçici yükleme adıysa asıl adı döner ('rapor.csv.filepart' → 'rapor.csv'), değilse None."""
        ek = son_ek(ad)
        if ek and ek in self.parca_uzantilari:
            return ad[: len(ad) - len(ek)]
        return None

    def eslestir(self, ad: str) -> list:
        """[(Kural, gruplar)] — 'ilk' modunda en fazla bir eleman."""
        sonuc = []
        for k in self.kurallar:
            m = k.desen.fullmatch(ad)
            if m:
                sonuc.append((k, {a: v for a, v in m.groupdict().items() if v is not None}))
                if self.coklu == "ilk":
                    break
        return sonuc

    def izlenecek_mi(self, ad: str) -> bool:
        """Uzantısı uygun mu (regex'ten bağımsız). Uygun ama regex'e uymayan → EŞLEŞMEDİ olur."""
        return self.uzanti_uygun(ad)


def uzanti_kumesi(metin: str) -> frozenset:
    parca = [p.strip().casefold() for p in str(metin or "").replace(";", ",").split(",")]
    return frozenset(p if p.startswith(".") else "." + p for p in parca if p)
