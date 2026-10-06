"""Adım 10 testleri: Windows servisi bekçisi (G4, M6).

Bekçi (servis\\windows_servisi.Bekci) servisin içinde çalışan mantığın aynısıdır; burada servis kurmadan gerçek
çekirdek + eklentilerle denenir. Servisin Windows'a kaydı (install/start) yönetici yetkisi ister; o kısım
servis_kur.bat ve araclar\\servis_dogrula.py ile hedef makinede doğrulanır.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cekirdek import win
from servis.windows_servisi import KOK, Bekci
from testler.conftest import HIZLI_TARAMA, TARAMA_EKLENTISI


def bekci_baslat(o, **kw):
    b = Bekci(o.baslangic, **kw)
    t = threading.Thread(target=b.calis, daemon=True)
    t.start()
    return b, t


def hazir(o, pid_degil=None):
    return o.bekle(lambda: (e := o.eklenti("tarama")) and e["durum"] == "CALISIYOR" and e["pid"]
                   and e["pid"] != pid_degil and win.surec_canli(e["pid"]) and e, zaman_asimi=40,
                   mesaj="tarama eklentisi çalışmıyor")


def test_cekirdek_olunce_servis_yeniden_baslatir_kayip_yok(ortam_yap, tmp_path):
    """G4 / M6: çekirdek öldürülür → eklentiler de kapanır (Job Object) → bekçi yeniden başlatır → kapalıyken gelen
    dosya telafiyle tetiklenir, eski dosya yeniden tetiklenmez; önyüz için uyarı alarmı ve denetim kaydı açılır."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    d = tmp_path / "gelen"
    dizin_id = o.dizin_kur(d, "TETIKLE", ".csv")
    o.kural_kur(dizin_id, r".*\.csv")
    b, t = bekci_baslat(o, plan=(0.5, 1))
    try:
        e = hazir(o)
        (d / "once.csv").write_text("1", encoding="utf-8")
        o.bekle(lambda: len(o.tetikler("once.csv")) == 1)
        cekirdek_pid, tarama_pid = b.proc.pid, e["pid"]
        os.kill(cekirdek_pid, signal.SIGTERM)                      # Windows'ta TerminateProcess (sert ölüm)
        o.bekle(lambda: not win.surec_canli(tarama_pid), mesaj="eklenti çekirdekle birlikte kapanmadı")
        (d / "arada.csv").write_text("2", encoding="utf-8")        # çekirdek yokken gelir
        hazir(o, pid_degil=tarama_pid)
        assert b.proc.pid != cekirdek_pid and b.yeniden_baslatma == 1
        o.bekle(lambda: len(o.tetikler("arada.csv")) == 1, mesaj="kapalıyken gelen dosya telafi edilmedi")
        time.sleep(1.5)
        assert len(o.tetikler("once.csv")) == 1 and len(o.tetikler("arada.csv")) == 1
        a = o.db.tek("SELECT * FROM alarm WHERE anahtar='servis:cekirdek_dustu' AND aktif=1")
        assert a is not None and a["seviye"] == "UYARI"
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='SERVIS_CEKIRDEK_YENIDEN'")[0] == 1
    finally:
        b.dur()
        t.join(60)
    assert not t.is_alive()


def test_servis_durdurulunca_duzgun_kapanir(ortam_yap):
    """Servis durdur / Windows kapanışı: çekirdeğe KAPAN gider, eklentiler düzgün kapanır (zorla öldürülmez),
    çekirdek 0 ile çıkar; yeniden başlatma yapılmaz."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    b, t = bekci_baslat(o)
    e = hazir(o)
    p = b.proc
    t0 = time.time()
    b.dur()
    t.join(60)
    assert not t.is_alive() and p.returncode == 0, p.returncode
    assert time.time() - t0 < 30
    assert not win.surec_canli(e["pid"])
    assert o.eklenti("cekirdek")["durum"] == "KAPANDI" and o.eklenti("tarama")["durum"] == "KAPANDI"
    assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='CEKIRDEK_KAPAN_KOMUTU' AND kullanici='servis'")[0] == 1
    assert b.yeniden_baslatma == 0


def test_surekli_coken_cekirdek_artan_beklemeyle_denenir(ortam_yap):
    """Çekirdek hemen çöküyorsa bekçi art arda sıkışmaz: 1, 2, 5… gibi artan bekleme (burada 0,2/0,4/0,8)."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    b, t = bekci_baslat(o, plan=(0.2, 0.4, 0.8), komut=[sys.executable, "-c", "import sys; sys.exit(7)"])
    try:
        o.bekle(lambda: b.yeniden_baslatma >= 4, zaman_asimi=20)
    finally:
        b.dur()
        t.join(20)
    assert b.son_cikis_kodu == 7 and b.ardisik >= 4
    zaman = [r["zaman"] for r in o.hdb.oku("SELECT zaman FROM denetim WHERE islem='SERVIS_CEKIRDEK_YENIDEN' ORDER BY id")]
    araliklar = [b_ - a_ for a_, b_ in zip(zaman, zaman[1:])]
    assert araliklar[0] >= 0.35 and araliklar[1] >= 0.7 and araliklar[2] >= 0.7, araliklar


def test_konsolda_acik_kopya_varken_servis_bekler(ortam_yap):
    """G7 + servis: aynı veri klasörüyle konsolda çalışan kopya varken servis ikinci kopya açmaz ve bunu çökme
    saymaz; konsol kopyası kapanınca servis çekirdeği devralır."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    o.cekirdek_baslat()                                              # "baslat.bat ile açılmış" kopya
    hazir(o)
    b, t = bekci_baslat(o, tek_kopya_bekleme_sn=0.5)
    try:
        o.bekle(lambda: b.son_cikis_kodu == 3, mesaj="servis tek kopya kilidine takılmadı")
        assert b.yeniden_baslatma == 0
        eski = o.eklenti("tarama")["pid"]
        o.cekirdek_kapat()
        hazir(o, pid_degil=eski)
        assert b.proc.poll() is None and b.yeniden_baslatma == 0
    finally:
        b.dur()
        t.join(60)


def test_konsol_kipi_ctrl_break_ile_duzgun_kapanir(ortam_yap):
    """'windows_servisi.py konsol' (servis kurmadan deneme): bekçi çekirdeği açar; Ctrl+Break ile düzgün kapanır."""
    o = ortam_yap(eklentiler=TARAMA_EKLENTISI, ayarlar=HIZLI_TARAMA)
    p = subprocess.Popen([sys.executable, str(KOK / "servis" / "windows_servisi.py"), "konsol", "--baslangic",
                          str(o.baslangic)], cwd=str(KOK), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        e = hazir(o)
        p.send_signal(signal.CTRL_BREAK_EVENT)
        assert p.wait(60) == 0
        o.bekle(lambda: not win.surec_canli(e["pid"]))
        assert o.eklenti("cekirdek")["durum"] == "KAPANDI"
        assert list(o.loglar.glob("servis*.log")), "servis logu yazılmadı"
    finally:
        if p.poll() is None:
            p.kill()


def test_servis_sinifi_ve_komut_satiri():
    """Servis tanımı: ad, python.exe ile barındırma, durdur + Windows kapanışı kabulü; komut satırı yardımı çalışır."""
    ws = pytest.importorskip("win32service")
    from servis.windows_servisi import FileWatcherProServisi as S
    assert S._svc_name_ == "FileWatcherPro" and Path(S._exe_name_).name.lower() == "python.exe"
    assert "windows_servisi.py" in S._exe_args_
    kabul = S.GetAcceptedControls(S.__new__(S))
    assert kabul & ws.SERVICE_ACCEPT_STOP and kabul & ws.SERVICE_ACCEPT_SHUTDOWN
    r = subprocess.run([sys.executable, str(KOK / "servis" / "windows_servisi.py"), "--help"], cwd=str(KOK),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert "install" in (r.stdout + r.stderr)
