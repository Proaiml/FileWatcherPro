"""Dosya tamamlandı mı?

Sinyaller (bkz. olay tablosu B1–B3, B7, B8):
  1. Gerçek boyut + mtime (os.stat dosyanın kendisinden okur; dizin listesindeki boyut NTFS'te
     dosya kapanana kadar eski kalabilir) W süresi boyunca değişmemeli.
  2. Paylaşım testi: dosya "okuma + silmeye izin ver, yazmaya izin verme" modunda açılmaya çalışılır.
     Yazan süreç (EFT) dosyayı yazmak için açık tutuyorsa Windows paylaşım ihlali (32) verir →
     dosya hâlâ yazılıyor demektir. Test milisaniyeler sürer; silme/yeniden adlandırma engellenmez.
     Bu test sunucuya gider, SMB önbelleğine takılmaz.
"""
import ctypes
from ctypes import wintypes

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x1
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

SERBEST = "SERBEST"      # kimse yazmak için tutmuyor
KILITLI = "KILITLI"      # yazan süreç hâlâ açık tutuyor
YOK = "YOK"              # dosya kaybolmuş
ERISIM = "ERISIM"        # erişim reddedildi (izin / başka tür kilit)
HATA = "HATA"            # diğer (ağ hatası vb.)


def paylasim_testi(yol: str) -> tuple:
    """(sonuç, windows_hata_kodu)."""
    h = _k32.CreateFileW(str(yol), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, None,
                         OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h is not None and h != INVALID_HANDLE_VALUE:
        _k32.CloseHandle(h)
        return SERBEST, 0
    kod = ctypes.get_last_error()
    if kod in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION):
        return KILITLI, kod
    if kod in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        return YOK, kod
    if kod == ERROR_ACCESS_DENIED:
        return ERISIM, kod
    return HATA, kod
