"""Windows'a özgü yardımcılar (ctypes; ek bağımlılık yok).

* Job Object: çekirdeğin başlattığı eklenti süreçleri bir işe bağlanır; çekirdek hangi yolla
  ölürse ölsün (çökme, görev yöneticisinden sonlandırma) Windows eklentileri de kapatır.
  Böylece sahipsiz kalmış ikinci bir tarayıcı/teslimci çalışmaz.
* Adlandırılmış mutex: aynı veri klasörü için tek çekirdek kopyası.
* Süreç canlılık kontrolü.
"""
import ctypes
import os
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259
ERROR_ALREADY_EXISTS = 183


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]


class IsNesnesi:
    """Kapanınca içindeki tüm süreçleri öldüren Windows Job Object."""

    def __init__(self):
        self.h = k32.CreateJobObjectW(None, None)
        if not self.h:
            raise ctypes.WinError(ctypes.get_last_error())
        bilgi = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        bilgi.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.h, JobObjectExtendedLimitInformation,
                                           ctypes.byref(bilgi), ctypes.sizeof(bilgi)):
            raise ctypes.WinError(ctypes.get_last_error())

    def ekle(self, popen) -> bool:
        """subprocess.Popen nesnesini işe bağlar. Başarısızsa False (üst güvence: eklentinin kendi
        çekirdek-canlılık kontrolü)."""
        return bool(k32.AssignProcessToJobObject(self.h, wintypes.HANDLE(int(popen._handle))))

    def sonlandir(self, kod: int = 1) -> bool:
        """İşteki tüm süreçleri (alt süreçler dahil) hemen sonlandırır; iş nesnesi açık kalır."""
        return bool(self.h) and bool(k32.TerminateJobObject(self.h, kod))

    def kapat(self):
        """Tutamacı kapatır (KILL_ON_JOB_CLOSE: içeride kalan süreç varsa onlar da sonlanır)."""
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


def surec_canli(pid: int) -> bool:
    if not pid:
        return False
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        kod = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(kod)):
            return False
        return kod.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


_mutexler = []


def tek_kopya_kilidi(ad: str) -> bool:
    """Adlandırılmış mutex alır. Aynı adla başka kopya çalışıyorsa False döner.
    Tutamaç süreç sonuna kadar açık kalır (süreç ölünce Windows bırakır)."""
    for on_ek in ("Global\\", "Local\\"):
        h = k32.CreateMutexW(None, False, on_ek + ad)
        hata = ctypes.get_last_error()
        if h:
            if hata == ERROR_ALREADY_EXISTS:
                k32.CloseHandle(h)
                return False
            _mutexler.append(h)
            return True
    raise ctypes.WinError(ctypes.get_last_error())


def pid() -> int:
    return os.getpid()
