"""Sırlar (şifre, API anahtarı): okunması ve uygulamanın kendisinin saklaması.

Düz şifre hiçbir yere (veritabanı, log, önyüz yanıtı, denetim) yazılmaz. Saklanan şey bir referanstır:
  dpapi:<base64>        → önyüzden girilen şifre; Windows DPAPI ile BU MAKİNEYE bağlı şifrelenmiş hâli (kullanıcı isteği
                          2026-09-30: 'ekrandan gireyim, uygulama kendi kaydetsin'). Makine kapsamı bilinçli: uygulama önce
                          konsolda (kullanıcı hesabı), sonra servis olarak (başka hesap) çalışabilir; ikisi de çözebilmeli.
                          Veritabanı başka makineye kopyalanırsa çözülemez; şifre orada yeniden girilir.
  env:DEGISKEN_ADI      → ortam değişkeni (gelişmiş)
  wincred:HEDEF_ADI     → Windows Kimlik Bilgisi Yöneticisi, Genel kimlik bilgisi (gelişmiş; hesaba bağlıdır)
Teslim (Control-M / HTTP hedefleri), bildirim (SMTP) ve kontrol arayüzü bu modülü kullanır.
"""
import base64
import ctypes
import os
from ctypes import wintypes

REF_ONEKLERI = ("dpapi:", "env:", "wincred:")
# önyüzden gelen düz alan → saklanan referans alanı (hedef ayrıntıları)
SIR_ALANLARI = {"sifre": "sifre_ref", "apikey": "apikey_ref", "anahtar": "anahtar_ref"}
_ENTROPI = b"FileWatcherPro/sir/v1"
_KORUMA = 0x1 | 0x4                       # CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
GIZLI = "dpapi:(şifreli)"                # önyüze giden maskeli referans


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(veri: bytes, sifrele: bool) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    tampon, ent_tampon = ctypes.create_string_buffer(veri, len(veri)), ctypes.create_string_buffer(_ENTROPI, len(_ENTROPI))
    giris = _BLOB(len(veri), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
    ent = _BLOB(len(_ENTROPI), ctypes.cast(ent_tampon, ctypes.POINTER(ctypes.c_char)))
    cikis = _BLOB()
    islev = crypt32.CryptProtectData if sifrele else crypt32.CryptUnprotectData
    if not islev(ctypes.byref(giris), None, ctypes.byref(ent), None, None, _KORUMA, ctypes.byref(cikis)):
        raise OSError(ctypes.get_last_error())
    try:
        return ctypes.string_at(cikis.pbData, cikis.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(cikis.pbData, ctypes.c_void_p))


def sir_sifrele(duz: str) -> str:
    """Önyüzden girilen şifreyi saklanabilir referansa çevirir: 'dpapi:<base64>' (bu makineye bağlı)."""
    if not duz:
        raise ValueError("şifre boş olamaz")
    try:
        return "dpapi:" + base64.b64encode(_dpapi(str(duz).encode("utf-8"), True)).decode("ascii")
    except OSError as e:
        raise ValueError(f"şifre saklanamadı (Windows DPAPI hata {e})") from None


def sir_oku(ref: str) -> tuple:
    """(kullanıcı_adı_ya_da_None, sır). Bulunamazsa ValueError."""
    if not ref:
        raise ValueError("kimlik referansı boş")
    tur, _, ad = str(ref).partition(":")
    if tur == "dpapi":
        try:
            return None, _dpapi(base64.b64decode(ad, validate=True), False).decode("utf-8")
        except (OSError, ValueError):
            raise ValueError("kayıtlı şifre bu sunucuda çözülemedi (veritabanı başka makineden mi taşındı?); "
                             "şifreyi yeniden girin") from None
    if tur == "env":
        deger = os.environ.get(ad)
        if deger is None:
            raise ValueError(f"ortam değişkeni tanımlı değil: {ad}")
        return None, deger
    if tur == "wincred":
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        p = ctypes.POINTER(_CREDENTIAL)()
        if not advapi.CredReadW(ctypes.c_wchar_p(ad), 1, 0, ctypes.byref(p)):
            raise ValueError(f"Windows Kimlik Bilgisi Yöneticisi'nde bulunamadı: {ad}")
        try:
            c = p.contents
            blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return c.UserName, blob.decode("utf-16-le")
        finally:
            advapi.CredFree(p)
    raise ValueError(f"desteklenmeyen kimlik referansı: {ref} (env:… ya da wincred:…)")


def ref_dogrula(ref: str, alan: str = "şifre") -> str:
    """Elle yazılan referans (gelişmiş alan): yalnızca env: / wincred: kabul edilir; düz şifre buraya yazılmaz."""
    ref = str(ref or "").strip()
    if ref and not ref.startswith(("env:", "wincred:")):
        raise ValueError(f"{alan} referansı env:… ya da wincred:… biçiminde olmalı; şifrenin kendisini "
                         f"'{alan.capitalize()}' alanına yazın")
    return ref


def sirlari_isle(ayrinti: dict, eski: dict = None) -> dict:
    """Önyüzden gelen hedef ayrıntısı: düz alanlar (sifre, apikey, anahtar) şifrelenip *_ref'e yazılır ve atılır.
    Düz alan boşsa: elle yazılmış env:/wincred: referansı; o da yoksa (düzenlemede) eski referans korunur."""
    d = dict(ayrinti or {})
    for duz_k, ref_k in SIR_ALANLARI.items():
        duz = d.pop(duz_k, None)
        ref = d.get(ref_k)
        if duz:
            d[ref_k] = sir_sifrele(duz)
        elif ref and ref != GIZLI:
            d[ref_k] = ref_dogrula(ref)
        elif eski and eski.get(ref_k):
            d[ref_k] = eski[ref_k]
        else:
            d.pop(ref_k, None)
    return d


def kaynak_metni(ref: str) -> str:
    """Önyüzde gösterilecek: şifre nerede duruyor (şifrenin kendisi değil)."""
    ref = str(ref or "")
    if ref.startswith("dpapi:"):
        return "uygulamada şifreli (bu sunucu)"
    if ref.startswith("env:"):
        return f"ortam değişkeni {ref[4:]}"
    if ref.startswith("wincred:"):
        return f"Windows Kimlik Bilgisi {ref[8:]}"
    return ""


def sirlari_gizle(ayrinti: dict) -> dict:
    """Önyüze / denetime gidecek kopya: dpapi referansı maskelenir, düz sır alanları hiç yoktur; '*_kayitli' eklenir."""
    d = {}
    for k, v in (ayrinti or {}).items():
        if k in SIR_ALANLARI:
            continue
        if k == "sirlar" and isinstance(v, list):       # betik hedefi: ad + nerede saklandığı, değer/referans yok
            d[k] = [{"ad": x.get("ad"), "kayitli": bool(x.get("ref")), "kaynak": kaynak_metni(x.get("ref"))}
                    for x in v if isinstance(x, dict)]
        elif k.endswith("_ref") and v:
            d[k] = GIZLI if str(v).startswith("dpapi:") else v
            d[k[:-4] + "_kaynagi"] = kaynak_metni(v)
            d[k[:-4] + "_kayitli"] = True
        else:
            d[k] = v
    return d
