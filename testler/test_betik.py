"""Betik çalıştırıcısı (cekirdek.betik): hata sözleşmesi, veri aktarımı, güvenlik, süre sınırı, süreç ağacı.

Gerçek python.exe ve Windows PowerShell 5.1 ile çalışır (sahte yok); sistem süreci gerekmez.
"""
import json
import os
import time
from pathlib import Path

import pytest

from cekirdek import betik, win
from cekirdek.istek_sablonu import degiskenler

TURKCE = "FATURA_ğüşıöç İĞ & \"x\" ; $env:PATH %PATH% `calc`.csv"


def _ortam(dosya=TURKCE, sirlar=None, gruplar=None, parametreler=None, deneme_sayisi=1):
    p = {"dosya_adi": dosya, "tam_yol": "\\\\SUNUCU\\gelen\\" + dosya, "dizin": "\\\\SUNUCU\\gelen", "boyut": 15342,
         "icerik_hash": "9f2c", "kural": "fatura", "gruplar": gruplar or {"tarih": "20261001"}}
    deg = degiskenler(p, "kimlik-123", {})
    return betik.ortam_ve_stdin(deg, p["gruplar"], parametreler or {"OLAY": "FATURA_GELDI"}, sirlar or {},
                                deneme=False, deneme_sayisi=deneme_sayisi)


def _kos(tmp_path, dil, kod, zaman=20, **kw):
    ortam, stdin = _ortam(**kw)
    return betik.calistir(tmp_path / "betik", dil, kod, ortam, stdin, zaman, (kw.get("sirlar") or {}).values())


# ---------------------------------------------------------------- Python
def test_python_veri_aktarimi_ozel_karakterler_metin_olarak_gelir(tmp_path):
    kod = ("import json, os, sys\n"
           "v = json.load(sys.stdin)\n"
           "print(json.dumps({'env': os.environ['FWP_DOSYA_ADI'], 'stdin': v['dosya_adi'], 'grup': os.environ['FWP_G_TARIH'],"
           " 'p': os.environ['FWP_P_OLAY'], 'kimlik': os.environ['FWP_KIMLIK'], 'deneme': os.environ['FWP_DENEME'],"
           " 'sayi': os.environ['FWP_DENEME_SAYISI'], 'boyut': v['boyut'], 'gruplar': v['gruplar']}, ensure_ascii=False))\n")
    s = _kos(tmp_path, "python", kod, deneme_sayisi=3)
    assert s.tur == "BASARI" and s.cikis_kodu == 0, s
    v = json.loads(s.stdout)
    assert v["env"] == TURKCE and v["stdin"] == TURKCE        # & " ; $ % ` metin olarak geldi, komut çalışmadı
    assert v["grup"] == "20261001" and v["p"] == "FATURA_GELDI" and v["kimlik"] == "kimlik-123"
    assert v["deneme"] == "0" and v["sayi"] == "3" and v["boyut"] == 15342 and v["gruplar"] == {"tarih": "20261001"}


@pytest.mark.parametrize("kod,tur,cikis", [
    ("import sys; sys.exit(10)", "KALICI", 10),
    ("import sys; sys.exit(3)", "GECICI", 3),
    ("raise RuntimeError('API yanıt vermedi')", "GECICI", 1),
    ("print('tamam')", "BASARI", 0),
])
def test_python_hata_sozlesmesi(tmp_path, kod, tur, cikis):
    s = _kos(tmp_path, "python", kod)
    assert (s.tur, s.cikis_kodu) == (tur, cikis), s
    if cikis == 1:
        assert "RuntimeError: API yanıt vermedi" in s.mesaj           # son stderr satırı mesajda


def test_temiz_ortam_servisin_sirlari_betige_gecmez_gizli_deger_maskelenir(tmp_path, monkeypatch):
    monkeypatch.setenv("FWP_CTM_SIFRE", "ornek-servis-sifresi")
    kod = ("import os\n"
           "print('ctm:', os.environ.get('FWP_CTM_SIFRE'))\n"
           "print('sir:', os.environ['FWP_SIR_API'])\n"
           "import sys; print('hata', os.environ['FWP_SIR_API'], file=sys.stderr); sys.exit(2)\n")
    s = _kos(tmp_path, "python", kod, sirlar={"API": "cok-gizli-token-42"})
    assert "ctm: None" in s.stdout
    assert "cok-gizli-token-42" not in s.stdout + s.stderr + s.mesaj and "sir: ***" in s.stdout
    assert s.tur == "GECICI" and "***" in s.mesaj


def test_zaman_asimi_surec_agacini_sonlandirir_belirsiz(tmp_path):
    kod = ("import subprocess, sys, time\n"
           "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
           "print(c.pid, flush=True)\n"
           "time.sleep(120)\n")
    t0 = time.time()
    s = _kos(tmp_path, "python", kod, zaman=3)
    assert s.tur == "BELIRSIZ" and s.cikis_kodu is None and "süre doldu" in s.mesaj
    assert time.time() - t0 < 20
    torun = int(s.stdout.strip().splitlines()[0])
    assert not win.surec_canli(torun), "betiğin başlattığı alt süreç de sonlanmalı"


def test_betik_bitince_geride_kalan_alt_surec_sonlanir(tmp_path):
    kod = ("import subprocess, sys\n"
           "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdout=subprocess.DEVNULL)\n"
           "print(c.pid)\n")
    t0 = time.time()
    s = _kos(tmp_path, "python", kod)
    assert s.tur == "BASARI" and time.time() - t0 < 15
    assert not win.surec_canli(int(s.stdout.strip()))


def test_cikti_son_64kb_tutulur(tmp_path):
    s = _kos(tmp_path, "python", "import sys\nfor i in range(40000): print('satir', i)\nprint('SON SATIR')\n")
    assert s.tur == "BASARI" and s.kesildi and len(s.stdout.encode()) <= betik.AZAMI_CIKTI
    assert s.stdout.rstrip().endswith("SON SATIR")


def test_kapanista_hepsini_sonlandir_belirsiz_doner(tmp_path):
    import threading
    sonuc = {}
    t = threading.Thread(target=lambda: sonuc.update(s=_kos(tmp_path, "python", "import time; time.sleep(60)", zaman=60)))
    t.start()
    o = time.time()
    while betik.calisan_sayisi() == 0 and time.time() - o < 10:
        time.sleep(0.05)
    assert betik.hepsini_sonlandir() == 1
    t.join(20)
    assert sonuc["s"].tur == "BELIRSIZ" and "kapanırken" in sonuc["s"].mesaj


def test_yorumlayici_yoksa_kalici(tmp_path, monkeypatch):
    monkeypatch.setattr(betik, "python_yolu", lambda: str(tmp_path / "yok" / "python.exe"))
    s = _kos(tmp_path, "python", "print(1)")
    assert s.tur == "KALICI" and "başlatılamadı" in s.mesaj


# ---------------------------------------------------------------- PowerShell
def test_powershell_turkce_stdin_ve_hata_sozlesmesi(tmp_path):
    kod = ("$v = [Console]::In.ReadToEnd() | ConvertFrom-Json\n"
           "Write-Output (\"env=\" + $env:FWP_DOSYA_ADI)\n"
           "Write-Output (\"stdin=\" + $v.dosya_adi)\n"
           "Write-Output (\"p=\" + $env:FWP_P_OLAY + \" g=\" + $env:FWP_G_TARIH)\n")
    s = _kos(tmp_path, "powershell", kod)
    assert s.tur == "BASARI", s
    assert f"env={TURKCE}" in s.stdout and f"stdin={TURKCE}" in s.stdout and "p=FATURA_GELDI g=20261001" in s.stdout


@pytest.mark.parametrize("kod,tur,cikis", [
    ("Get-Item 'C:\\yok\\yok.txt'; Write-Output 'buraya gelmemeli'", "GECICI", 1),   # Stop: hata betiği durdurur
    ("throw 'özel hata'", "GECICI", 1),
    ("Write-Output 'x'; exit 10", "KALICI", 10),
    ("cmd.exe /c exit 7", "GECICI", 7),                     # exit yazılmadı: son harici komutun kodu
    ("cmd.exe /c exit 7; exit 0", "BASARI", 0),             # bilerek başarı
])
def test_powershell_hata_sozlesmesi(tmp_path, kod, tur, cikis):
    s = _kos(tmp_path, "powershell", kod)
    assert (s.tur, s.cikis_kodu) == (tur, cikis), s
    assert "buraya gelmemeli" not in s.stdout


# ---------------------------------------------------------------- sözdizimi, doğrulama
def test_sozdizimi_denetimi_calistirmadan(tmp_path):
    isaret = tmp_path / "calisti.txt"
    kod = f"open(r'{isaret}', 'w').write('x')\nprint((1, 2\n"
    r = betik.sozdizimi_denetle("python", kod)
    assert not r["gecerli"] and r["satir"] == 2 and not isaret.exists()
    assert betik.sozdizimi_denetle("python", "print('ok')\n")["gecerli"]
    r = betik.sozdizimi_denetle("powershell", f"Set-Content '{isaret}' x\nif ($a -eq 1) {{\n  'x'\n")
    assert not r["gecerli"] and r["satir"] in (2, 3) and not isaret.exists()
    assert betik.sozdizimi_denetle("powershell", "Write-Output 'ğüş'")["gecerli"]


def test_tanim_dogrulama():
    assert betik.tanim_dogrula("PYTHON", "print(1)", 30, 2, ["API"])[0] == "python"
    for arg, mesaj in ((("cmd", "x", 30, 1), "dil"), (("python", "  ", 30, 1), "boş"),
                       (("python", "x", 0, 1), "zaman aşımı"), (("python", "x", 601, 1), "zaman aşımı"),
                       (("python", "x", 30, 9), "aynı anda"), (("python", "x" * 200_001, 30, 1), "en fazla")):
        with pytest.raises(ValueError, match=mesaj):
            betik.tanim_dogrula(*arg)
    with pytest.raises(ValueError, match="iki kez"):
        betik.tanim_dogrula("python", "x", 30, 1, ["A", "A"])
    with pytest.raises(ValueError, match="büyük harf"):
        betik.tanim_dogrula("python", "x", 30, 1, ["kucuk"])
