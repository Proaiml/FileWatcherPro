"""Dosya kimliği ve içerik hash'i.

Kimlik (bkz. Tasarım kriterleri):
  * Eşik altı dosya:  dizin + dosya adı + içerik hash'i (xxh3-128).
      - 0 baytlık dosyaların hash'i hep aynıdır; ad kimliğin parçası olduğu için farklı adlı boş
        dosyalar ayrı dosyadır.
      - Yalnızca tarihi (mtime) değişen dosya aynı kimliği korur → yeniden tetiklenmez.
  * Eşik üstü dosya: dizin + ad + boyut + mtime (hash alınmaz).

Hash okuması EFT ve Control-M'i ENGELLEMEZ: dosya FILE_SHARE_READ | WRITE | DELETE ile açılır
(Python'un open() fonksiyonu DELETE paylaşımı vermez; okurken başkası dosyayı yeniden
adlandıramaz/silemezdi). Okuma sıralı ve tek bir yeniden kullanılan tamponla yapılır.
"""
import ctypes
import msvcrt
import os
import threading
import time
from ctypes import wintypes

import xxhash

GENERIC_READ = 0x80000000
FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

# Okuma parçası (ölçüm: araclar/performans_olcum.py, 256 MB): yerel diskte 1 MB en hızlı (4 MB'a göre +%14),
# ağ yolunda (SMB) 8 MB en hızlı (+%13): daha az gidiş-dönüş. Algoritma xxh3_128 (bellekte ~20 GB/sn; darboğaz G/Ç).
PARCA_YEREL = 1 * 1024 * 1024
PARCA_AG = 8 * 1024 * 1024
DRIVE_REMOTE = 4
_k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]


def ag_yolu_mu(yol: str) -> bool:
    r"""UNC (\\sunucu\paylasim, \\?\UNC\sunucu\...) ya da ağ sürücüsüne eşlenmiş harf (Z:)."""
    s = str(yol)
    if s.startswith("\\\\"):
        return not s.startswith("\\\\?\\") or s[4:8].upper() == "UNC\\"
    return len(s) >= 2 and s[1] == ":" and _k32.GetDriveTypeW(s[:2] + "\\") == DRIVE_REMOTE


def parca_boyu(yol: str) -> int:
    return PARCA_AG if ag_yolu_mu(yol) else PARCA_YEREL


class DosyaDegisti(Exception):
    """Hash alınırken dosyanın boyutu/zamanı değişti (hâlâ yazılıyor)."""


def paylasimli_ac(yol: str):
    """Başkalarının yazmasını, yeniden adlandırmasını ve silmesini engellemeden okuma için açar."""
    h = _k32.CreateFileW(str(yol), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING,
                         FILE_FLAG_SEQUENTIAL_SCAN, None)
    if h is None or h == INVALID_HANDLE_VALUE:
        hata = ctypes.get_last_error()
        raise OSError(hata, ctypes.FormatError(hata).strip(), str(yol))
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
    except Exception:
        _k32.CloseHandle(h)
        raise
    return os.fdopen(fd, "rb", buffering=0)


_yerel = threading.local()


def _tampon(n: int) -> memoryview:
    """Thread başına bir kez ayrılan okuma tamponu (her dosyada 8 MB sıfırlanmış bellek ayırmamak için)."""
    t = getattr(_yerel, "tampon", None)
    if t is None or len(t) != n:
        t = _yerel.tampon = memoryview(bytearray(n))
    return t


def icerik_hash(yol: str, ilerleme=None, parca: int = None) -> tuple:
    """(hex, okunan_bayt, süre_ms). `ilerleme` her parçada çağrılır (takılma tespiti için)."""
    t0 = time.perf_counter()
    h = xxhash.xxh3_128()
    mv = _tampon(parca or parca_boyu(yol))
    toplam = 0
    with paylasimli_ac(yol) as f:
        while True:
            n = f.readinto(mv)
            if not n:
                break
            h.update(mv[:n])
            toplam += n
            if ilerleme is not None:
                ilerleme()
    return h.hexdigest(), toplam, int((time.perf_counter() - t0) * 1000)


def dogrulanmis_hash(yol: str, beklenen_boyut: int, beklenen_mtime_ns: int, ilerleme=None) -> tuple:
    """Hash'i alır ve okuma sırasında dosyanın değişmediğini doğrular; değiştiyse DosyaDegisti."""
    hx, okunan, sure = icerik_hash(yol, ilerleme)
    st = os.stat(yol)
    if okunan != beklenen_boyut or st.st_size != beklenen_boyut or st.st_mtime_ns != beklenen_mtime_ns:
        raise DosyaDegisti(f"hash sırasında değişti ({beklenen_boyut}→{st.st_size} bayt)")
    return hx, sure


def kimlik_uret(dizin_id: int, ad_anahtar: str, icerik_hash: str = None,
                boyut: int = None, mtime_ns: int = None) -> str:
    if icerik_hash is not None:
        taban = f"H|{dizin_id}|{ad_anahtar}|{icerik_hash}"
    else:
        taban = f"M|{dizin_id}|{ad_anahtar}|{boyut}|{mtime_ns}"
    return xxhash.xxh3_128_hexdigest(taban.encode("utf-8"))


def idempotency_uret(kimlik: str, dosya_id: int, kural_id: int) -> str:
    """Tetik başına tekil anahtar. Aynı dosyanın aynı kurala ikinci tetiği tabloya giremez (H7);
    Control-M'e de gönderilir (H4 belirsiz sonuçta tekrar)."""
    return xxhash.xxh3_128_hexdigest(f"{kimlik}|{dosya_id}|{kural_id}".encode("utf-8"))
