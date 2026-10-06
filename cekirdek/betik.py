"""Betik hedefi çalıştırıcısı: her tetik için kullanıcının Python ya da PowerShell betiği bu sunucuda ayrı bir süreçte
çalışır. Teslim (gerçek tetik) ve kontrol (önyüzde canlı test) bu tek modülü kullanır: önyüzde denenen, sahada
çalışanla aynıdır.

Veri betiğe METNİN İÇİNE YAZILMADAN verilir (dosya adındaki özel karakterler komut çalıştıramaz):
  * ortam değişkenleri: FWP_DOSYA_ADI, FWP_TAM_YOL, …, FWP_G_<GRUP> (regex grupları), FWP_P_<AD> (kuralın ek
    değerleri), FWP_SIR_<AD> (gizli değerler, yalnız ortamda)
  * stdin: aynı bilgiler JSON olarak (gizli değerler hariç)
Ortam temizdir: sistemin çalışması için gerekenler + FWP_*; servisin diğer değişkenleri (ör. env: şifreleri) geçmez.

Hata sözleşmesi (sonucu yalnız çıkış kodu belirler):
  0 → BASARI · 10 → KALICI · diğer → GECICI · süre doldu ya da kapanışta sonlandırıldı → BELIRSIZ ·
  başlatılamadı → KALICI
PowerShell'e sistem başa 'Stop' (her hata betiği durdurur), UTF-8 ve trap (yakalanmayan hata → 1) ekler; betik
exit yazmadan biterse son harici komutun çıkış kodu (hiç yoksa 0) kullanılır. Ölçüldü: Windows PowerShell 5.1.
Süre dolunca betik ve başlattığı tüm süreçler (Job Object) sonlandırılır; betik bitince geride kalanlar da.
Çıktı: stdout / stderr'in son 64 KB'ı tutulur, gizli değerler *** ile maskelenir.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

DILLER = ("python", "powershell")
CIKIS_KALICI = 10
AZAMI_CIKTI = 64 * 1024
AZAMI_KOD = 200_000
ZAMAN_ASIMI_ALT, ZAMAN_ASIMI_UST = 1, 600
ESZAMANLI_UST = 8
AZAMI_SIR = 20
AD_DESENI = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
CREATE_NO_WINDOW = 0x08000000

# ortam değişkeni → stdin JSON alanı
DEGISKENLER = (("FWP_DOSYA_ADI", "dosya_adi"), ("FWP_TAM_YOL", "tam_yol"), ("FWP_DIZIN", "dizin"),
               ("FWP_BOYUT", "boyut"), ("FWP_ICERIK_HASH", "icerik_hash"), ("FWP_KIMLIK", "kimlik"),
               ("FWP_KURAL", "kural"), ("FWP_ZAMAN", "zaman"), ("FWP_BUGUN", "bugun"),
               ("FWP_DENEME_SAYISI", "deneme_sayisi"), ("FWP_DENEME", "deneme"))
# servisin ortamından betiğe geçen değişkenler (Windows'un ve PowerShell'in çalışması + vekil sunucu)
TEMIZ_ORTAM = ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "PROGRAMDATA",
               "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
               "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN",
               "COMPUTERNAME", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "PSMODULEPATH",
               "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY")

PS_ONSOZ = """$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); [Console]::InputEncoding = [Text.UTF8Encoding]::new($false) } catch { }
$OutputEncoding = [Text.UTF8Encoding]::new($false)
trap { [Console]::Error.WriteLine($_); exit 1 }
. (Join-Path $PSScriptRoot 'betik.ps1')
if ($LASTEXITCODE) { exit $LASTEXITCODE }
exit 0
"""


class SonucTuru:                     # teslim adaptörlerinin türleriyle aynı adlar
    BASARI = "BASARI"
    GECICI = "GECICI"
    KALICI = "KALICI"
    BELIRSIZ = "BELIRSIZ"


@dataclass
class BetikSonucu:
    tur: str
    cikis_kodu: int = None
    sure_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    kesildi: bool = False
    mesaj: str = ""

    def sozluk(self) -> dict:
        return {"sonuc": self.tur, "cikis_kodu": self.cikis_kodu, "sure_ms": self.sure_ms, "stdout": self.stdout,
                "stderr": self.stderr, "kesildi": self.kesildi, "mesaj": self.mesaj}


# ---------------------------------------------------------------- yorumlayıcılar
def python_yolu() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def powershell_yolu() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0"
               / "powershell.exe")


def komut(dil: str, klasor: Path) -> list:
    if dil == "python":
        return [python_yolu(), "-X", "utf8", "-I", "-B", str(Path(klasor) / "betik.py")]
    return [powershell_yolu(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(Path(klasor) / "calistir.ps1")]


def komut_metni(dil: str) -> str:
    return ("python.exe -X utf8 -I -B betik.py" if dil == "python" else
            "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File calistir.ps1")


_surumler = {}
_surum_kilidi = threading.Lock()


def diller() -> dict:
    """Önyüz için: her dilin yorumlayıcısı, sürümü ve komutu (PowerShell sürümü bir kez ölçülür)."""
    with _surum_kilidi:
        if "powershell" not in _surumler:
            surum = None
            try:
                p = subprocess.run([powershell_yolu(), "-NoProfile", "-NonInteractive", "-Command",
                                    "$PSVersionTable.PSVersion.ToString()"], capture_output=True, timeout=20,
                                   creationflags=CREATE_NO_WINDOW)
                if p.returncode == 0:
                    surum = p.stdout.decode("ascii", "replace").strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
            _surumler["powershell"] = surum
    ps = _surumler["powershell"]
    return {"python": {"yol": python_yolu(), "komut": komut_metni("python"),
                       "surum": f"Python {sys.version.split()[0]} (servisle aynı yorumlayıcı)"},
            "powershell": {"yol": powershell_yolu(), "komut": komut_metni("powershell"),
                           "surum": f"Windows PowerShell {ps}" if ps else "PowerShell bulunamadı"}}


# ---------------------------------------------------------------- doğrulama
def tanim_dogrula(dil: str, kod: str, zaman_asimi_sn, eszamanli, sir_adlari=()) -> tuple:
    """Betik hedefi tanımı: (dil, kod, zaman_asimi_sn, eszamanli). Hatalıysa ValueError (Türkçe)."""
    dil = str(dil or "").lower()
    if dil not in DILLER:
        raise ValueError("dil python ya da powershell olmalı")
    kod = str(kod or "")
    if not kod.strip():
        raise ValueError("betik boş olamaz")
    if len(kod) > AZAMI_KOD:
        raise ValueError(f"betik en fazla {AZAMI_KOD} karakter olabilir")
    try:
        z = float(zaman_asimi_sn if zaman_asimi_sn not in (None, "") else 30)
        e = int(eszamanli if eszamanli not in (None, "") else 2)
    except (TypeError, ValueError):
        raise ValueError("zaman aşımı ve eşzamanlılık sayı olmalı") from None
    if not ZAMAN_ASIMI_ALT <= z <= ZAMAN_ASIMI_UST:
        raise ValueError(f"zaman aşımı {ZAMAN_ASIMI_ALT}–{ZAMAN_ASIMI_UST} sn olmalı")
    if not 1 <= e <= ESZAMANLI_UST:
        raise ValueError(f"aynı anda çalışma sayısı 1–{ESZAMANLI_UST} olmalı")
    adlar = list(sir_adlari)
    if len(adlar) > AZAMI_SIR:
        raise ValueError(f"en fazla {AZAMI_SIR} gizli değer")
    for a in adlar:
        if not AD_DESENI.match(a):
            raise ValueError(f"gizli değer adı büyük harf, rakam ve _ olmalı (harfle başlar): {a}")
    cift = {a for a in adlar if adlar.count(a) > 1}
    if cift:
        raise ValueError(f"gizli değer adı iki kez: {', '.join(sorted(cift))}")
    return dil, kod, z, e


def surum(dil: str, kod: str) -> str:
    return hashlib.sha256(f"{dil}\n{kod}".encode("utf-8")).hexdigest()[:7]


# ---------------------------------------------------------------- ortam ve stdin
def ortam_ve_stdin(deg: dict, gruplar: dict, parametreler: dict, sirlar: dict, deneme: bool,
                   deneme_sayisi: int = 1) -> tuple:
    """(FWP_* ortam değişkenleri, stdin nesnesi). deg = istek_sablonu.degiskenler() çıktısı."""
    stdin = {}
    for _, k in DEGISKENLER:
        if k == "deneme":
            stdin[k] = bool(deneme)
        elif k == "deneme_sayisi":
            stdin[k] = int(deneme_sayisi)
        elif k == "boyut":
            try:
                stdin[k] = int(deg.get("boyut") or 0)
            except (TypeError, ValueError):
                stdin[k] = 0
        else:
            stdin[k] = "" if deg.get(k) is None else str(deg.get(k))
    gruplar = {str(k): "" if v is None else str(v) for k, v in (gruplar or {}).items()}
    parametreler = {str(k): "" if v is None else str(v) for k, v in (parametreler or {}).items()}
    stdin.update(gruplar=gruplar, parametreler=parametreler)
    ortam = {v: ("1" if stdin[k] is True else "0" if stdin[k] is False else str(stdin[k])) for v, k in DEGISKENLER}
    for k, v in gruplar.items():
        ortam[f"FWP_G_{k.upper()}"] = v
    for k, v in parametreler.items():
        ortam[f"FWP_P_{k}"] = v
    for k, v in (sirlar or {}).items():
        ortam[f"FWP_SIR_{k}"] = str(v)
    return ortam, stdin


def gorunur_ortam(ortam: dict) -> dict:
    """Önyüze gösterilecek kopya: gizli değerler maskeli."""
    return {k: ("*** (gizli)" if k.startswith("FWP_SIR_") else v) for k, v in ortam.items()}


def _maskele(metin: str, sirlar) -> str:
    for s in sorted({str(x) for x in sirlar if x and len(str(x)) >= 3}, key=len, reverse=True):
        metin = metin.replace(s, "***")
    return metin


# ---------------------------------------------------------------- dosyalar
def hazirla(kok: Path, dil: str, kod: str) -> Path:
    """Betiği kok/<sürüm>/ klasörüne yazar (bir kez; eşzamanlı çalışmalarda aynı dosya). PowerShell: UTF-8 BOM'lu
    (5.1 BOM'suz dosyayı ANSI okur) + calistir.ps1 sarmalayıcısı."""
    klasor = Path(kok) / surum(dil, kod)
    hedef = klasor / ("betik.py" if dil == "python" else "betik.ps1")
    with _hazirlik_kilidi:                # aynı süreçte eşzamanlı ilk yazım: çalışmakta olan dosyanın üstüne yazılmasın
        if hedef.exists() and (dil == "python" or (klasor / "calistir.ps1").exists()):
            return klasor
        return _yaz(Path(kok), klasor, hedef, dil, kod)


def _yaz(kok: Path, klasor: Path, hedef: Path, dil: str, kod: str) -> Path:
    klasor.mkdir(parents=True, exist_ok=True)
    kodlama = "utf-8" if dil == "python" else "utf-8-sig"
    dosyalar = [(hedef, kod)] + ([(klasor / "calistir.ps1", PS_ONSOZ)] if dil == "powershell" else [])
    for yol, icerik in dosyalar:
        gecici = yol.with_name(f"{yol.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        gecici.write_text(icerik, encoding=kodlama, newline="\r\n" if dil == "powershell" else None)
        os.replace(gecici, yol)
    _eskileri_temizle(kok, klasor.name)
    return klasor


def _eskileri_temizle(kok: Path, guncel: str, sakla: int = 3):
    """Aynı hedefin eski sürüm klasörleri: en yeni birkaçı kalır (çalışan bir eski sürüm silinemezse dokunulmaz)."""
    try:
        eskiler = sorted((d for d in kok.iterdir() if d.is_dir() and d.name != guncel),
                         key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return
    for d in eskiler[sakla:]:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- çalıştırma
_hazirlik_kilidi = threading.Lock()
_calisanlar = {}                       # kimlik → {"is": IsNesnesi, "durduruldu": bool}
_kilit = threading.Lock()


def hepsini_sonlandir() -> int:
    """Kapanış: çalışan tüm betikleri (alt süreçleriyle) sonlandırır; sonuçları BELİRSİZ döner (tekrar denenir)."""
    with _kilit:
        kayitlar = list(_calisanlar.values())
        for k in kayitlar:
            k["durduruldu"] = True
    for k in kayitlar:
        try:
            k["sonlandir"]()
        except Exception:  # noqa: BLE001 - kapanışta biri başarısız olsa da diğerleri sonlandırılır
            pass
    return len(kayitlar)


def calisan_sayisi() -> int:
    with _kilit:
        return len(_calisanlar)


def _okuyucu(akis, tampon: deque, sayac: list):
    try:
        while True:
            parca = akis.read1(65536)
            if not parca:
                break
            tampon.append(parca)
            sayac[0] += len(parca)
            while sum(len(x) for x in tampon) > AZAMI_CIKTI and len(tampon) > 1:
                tampon.popleft()
    except (OSError, ValueError):
        pass


def _yazici(akis, veri: bytes):
    try:
        akis.write(veri)
    except (OSError, ValueError):
        pass                            # betik stdin'i okumadan bitti
    finally:
        try:
            akis.close()
        except OSError:
            pass


def _metin(tampon: deque, sayac: list, sirlar) -> tuple:
    ham = b"".join(tampon)
    kesildi = sayac[0] > len(ham) or len(ham) > AZAMI_CIKTI
    ham = ham[-AZAMI_CIKTI:]
    return _maskele(ham.decode("utf-8", "replace"), sirlar), kesildi


def calistir(kok: Path, dil: str, kod: str, ortam_fwp: dict, stdin_nesnesi: dict, zaman_asimi_sn: float,
             sir_degerleri=()) -> BetikSonucu:
    """Betiği çalıştırır ve sözleşmeye göre sınıflandırır. Hiçbir zaman istisna fırlatmaz."""
    from .win import IsNesnesi
    t0 = time.perf_counter()
    sure = lambda: int((time.perf_counter() - t0) * 1000)  # noqa: E731
    sirlar = list(sir_degerleri)
    try:
        klasor = hazirla(kok, dil, kod)
    except OSError as e:
        return BetikSonucu(SonucTuru.GECICI, sure_ms=sure(), mesaj=f"betik dosyası yazılamadı: {e}")
    ortam = {k: v for k, v in os.environ.items() if k.upper() in TEMIZ_ORTAM}
    ortam.update(ortam_fwp)
    try:
        is_ = IsNesnesi()
    except OSError:
        is_ = None
    try:
        p = subprocess.Popen(komut(dil, klasor), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=ortam, cwd=str(klasor), creationflags=CREATE_NO_WINDOW)
    except OSError as e:
        if is_:
            is_.kapat()
        return BetikSonucu(SonucTuru.KALICI, sure_ms=sure(), mesaj=f"betik başlatılamadı: {e}")
    baglandi = bool(is_ and is_.ekle(p))

    def sonlandir():
        if baglandi and is_.sonlandir():
            return
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)          # yedek: iş nesnesine bağlanamadıysa ağaçla birlikte

    kimlik = id(p)
    kayit = {"sonlandir": sonlandir, "durduruldu": False}
    with _kilit:
        _calisanlar[kimlik] = kayit
    cikti, hata, say_o, say_h = deque(), deque(), [0], [0]
    is_parcaciklari = [threading.Thread(target=_okuyucu, args=(p.stdout, cikti, say_o), daemon=True),
                       threading.Thread(target=_okuyucu, args=(p.stderr, hata, say_h), daemon=True),
                       threading.Thread(target=_yazici, args=(p.stdin, json.dumps(stdin_nesnesi, ensure_ascii=False)
                                                              .encode("utf-8")), daemon=True)]
    for t in is_parcaciklari:
        t.start()
    zaman_doldu = False
    try:
        p.wait(timeout=float(zaman_asimi_sn))
    except subprocess.TimeoutExpired:
        zaman_doldu = True
        sonlandir()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    finally:
        if baglandi and not zaman_doldu:
            is_.sonlandir()             # betik bitti: geride kalan alt süreçler de kapanır (çıktı akışları serbest kalır)
        for t in is_parcaciklari:
            t.join(timeout=5)
        with _kilit:
            _calisanlar.pop(kimlik, None)
        if is_:
            is_.kapat()
    stdout, k1 = _metin(cikti, say_o, sirlar)
    stderr, k2 = _metin(hata, say_h, sirlar)
    s = BetikSonucu(SonucTuru.GECICI, p.returncode, sure(), stdout, stderr, k1 or k2)
    if kayit["durduruldu"]:
        s.tur, s.cikis_kodu, s.mesaj = SonucTuru.BELIRSIZ, None, "servis kapanırken betik sonlandırıldı (işi yapmış olabilir)"
    elif zaman_doldu:
        s.tur, s.cikis_kodu = SonucTuru.BELIRSIZ, None
        s.mesaj = f"süre doldu ({float(zaman_asimi_sn):g} sn): betik ve başlattığı süreçler sonlandırıldı (işi yapmış olabilir)"
    else:
        s.tur = (SonucTuru.BASARI if p.returncode == 0 else SonucTuru.KALICI if p.returncode == CIKIS_KALICI
                 else SonucTuru.GECICI)
        son = next((x for x in reversed((stderr or stdout).splitlines()) if x.strip()), "")
        s.mesaj = f"çıkış {p.returncode}" + (f": {son.strip()[:180]}" if son and p.returncode != 0 else "")
    return s


# ---------------------------------------------------------------- sözdizimi denetimi (çalıştırmadan)
_PY_DENETIM = """import json, sys
kaynak = sys.stdin.buffer.read().decode('utf-8', 'replace')
try:
    compile(kaynak, 'betik.py', 'exec')
    print(json.dumps({'gecerli': True}))
except SyntaxError as e:
    print(json.dumps({'gecerli': False, 'satir': e.lineno, 'mesaj': f'satır {e.lineno}: {e.msg}'}, ensure_ascii=False))
except (ValueError, RecursionError, MemoryError) as e:
    print(json.dumps({'gecerli': False, 'satir': None, 'mesaj': str(e)}, ensure_ascii=False))
"""
_PS_DENETIM = """$okur = New-Object IO.StreamReader([Console]::OpenStandardInput(), (New-Object Text.UTF8Encoding $false))
$kaynak = $okur.ReadToEnd()
$t = $null; $e = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($kaynak, [ref]$t, [ref]$e)
if ($e.Count) { $i = $e[0]; $s = @{gecerli=$false; satir=$i.Extent.StartLineNumber; mesaj=('satır ' + $i.Extent.StartLineNumber + ': ' + $i.Message)} }
else { $s = @{gecerli=$true} }
$yaz = New-Object IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object Text.UTF8Encoding $false))
$yaz.Write(($s | ConvertTo-Json -Compress)); $yaz.Flush()
"""


def sozdizimi_denetle(dil: str, kod: str, sure_sn: float = 20) -> dict:
    """Betiği ÇALIŞTIRMADAN derler / ayrıştırır (ayrı süreçte, süre sınırıyla). {gecerli, satir?, mesaj}."""
    dil = str(dil or "").lower()
    if dil == "python":
        k = [python_yolu(), "-I", "-S", "-c", _PY_DENETIM]
        ad = "Python derleyicisi"
    elif dil == "powershell":
        k = [powershell_yolu(), "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(_PS_DENETIM.encode("utf-16-le")).decode("ascii")]
        ad = "PowerShell ayrıştırıcısı"
    else:
        raise ValueError("dil python ya da powershell olmalı")
    try:
        p = subprocess.run(k, input=str(kod or "").encode("utf-8"), capture_output=True, timeout=sure_sn,
                           creationflags=CREATE_NO_WINDOW)
        r = json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"gecerli": False, "satir": None, "mesaj": f"denetim {sure_sn:g} sn içinde bitmedi"}
    except (OSError, ValueError, IndexError) as e:
        return {"gecerli": False, "satir": None, "mesaj": f"denetlenemedi: {e}"}
    if r.get("gecerli"):
        r["mesaj"] = f"Sözdizimi geçerli ({ad}; çalıştırılmadı)"
    return r
