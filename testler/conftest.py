"""Ortak test düzeneği: geçici veri/log klasörleriyle gerçek çekirdek süreci başlatır."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

from cekirdek.ayarlar import Ayarlar  # noqa: E402
from cekirdek.db_canli import CanliDB  # noqa: E402
from cekirdek.db_hata import HataDB  # noqa: E402

CREATE_NO_WINDOW = 0x08000000

# Testleri hızlandıran gözetmen ayarları
HIZLI_GOZETMEN = {
    "eklenti_nabiz_sn": 0.3,
    "eklenti_yanitsiz_sn": 3,
    "eklenti_baslama_payi_sn": 4,
    "eklenti_bekleme_plani": "0.3,0.3,0.3",
    "eklenti_dusme_limiti": 3,
    "eklenti_stabil_sn": 60,
    "kapanis_teslim_bekleme_sn": 2,
}


class Ortam:
    def __init__(self, tmp: Path, eklentiler: list):
        self.tmp = tmp
        self.veri = tmp / "veri"
        self.loglar = tmp / "loglar"
        self.baslangic = tmp / "baslangic.json"
        tmp.mkdir(parents=True, exist_ok=True)
        self.baslangic.write_text(json.dumps({
            "veri_klasoru": str(self.veri), "log_klasoru": str(self.loglar),
            "kontrol_adres": "127.0.0.1", "kontrol_port": 0, "eklentiler": eklentiler,
        }, ensure_ascii=False), encoding="utf-8")
        self.veri.mkdir(parents=True, exist_ok=True)
        self._db = None
        self._hdb = None
        self.proc = None

    # ------------------------------------------------ veritabanları
    @property
    def db(self) -> CanliDB:
        if self._db is None:
            self._db = CanliDB(self.veri / "canli.db").sema_kur()
        return self._db

    @property
    def hdb(self) -> HataDB:
        if self._hdb is None:
            self._hdb = HataDB(self.veri / "hata.db").sema_kur()
        return self._hdb

    def ayar(self, **degerler):
        a = Ayarlar(self.db)
        for k, v in degerler.items():
            a.degistir(k, v)

    # ------------------------------------------------ çekirdek süreci
    def cekirdek_komutu(self):
        return [sys.executable, str(KOK / "calistir.py"), "--baslangic", str(self.baslangic)]

    def cekirdek_baslat(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(self.cekirdek_komutu(), cwd=str(KOK), env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=CREATE_NO_WINDOW)
        return self.proc

    def cekirdek_kapat(self, zaman_asimi=30):
        if self.proc is None or self.proc.poll() is not None:
            return
        self.db.komut_gonder("cekirdek", "KAPAN", kullanici="test")
        try:
            self.proc.wait(zaman_asimi)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)
            raise AssertionError("çekirdek KAPAN komutuyla kapanmadı")

    # ------------------------------------------------ yardımcılar
    def eklenti(self, ad):
        return self.db.eklenti(ad)

    def davranis(self, ad: str, d: str):
        (self.veri / f"davranis_{ad}.txt").write_text(d, encoding="utf-8")

    @staticmethod
    def bekle(kosul, zaman_asimi=30.0, aralik=0.2, mesaj="koşul sağlanmadı"):
        son = time.time() + zaman_asimi
        while time.time() < son:
            try:
                v = kosul()
            except Exception:
                v = None
            if v:
                return v
            time.sleep(aralik)
        raise AssertionError(f"{mesaj} ({zaman_asimi:g} sn)")

    # ------------------------------------------------ yapılandırma kısayolları
    @property
    def yap(self):
        from cekirdek.yapilandirma import Yapilandirma
        return Yapilandirma(self.db, self.hdb)

    def dizin_kur(self, yol, mod="TETIKLE", uzantilar=""):
        Path(yol).mkdir(parents=True, exist_ok=True)
        return self.yap.dizin_ekle(str(yol), mod, uzantilar=uzantilar, kullanici="test")

    def hedef_kur(self, ad="controlm", adres="http://127.0.0.1:9/automation-api"):
        s = self.db.tek("SELECT id FROM hedef WHERE ad=?", (ad,))
        return s["id"] if s else self.yap.hedef_ekle(ad, adres, kullanici="test")

    def kural_kur(self, dizin_id, regex, hedef_id=None, **kw):
        return self.yap.kural_ekle(dizin_id, kw.pop("ad", regex), regex, hedef_id or self.hedef_kur(),
                                   kullanici="test", **kw)

    def tetikler(self, ad=None):
        if ad:
            return self.db.oku("SELECT * FROM tetik WHERE dosya_adi=? ORDER BY id", (ad,))
        return self.db.oku("SELECT * FROM tetik ORDER BY id")

    def yukleme(self, ad):
        return self.db.tek("SELECT * FROM yukleme WHERE dosya_adi=?", (ad,))

    def kapat(self):
        try:
            self.cekirdek_kapat()
        finally:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
            for d in (self._db, self._hdb):
                if d is not None:
                    d.kapat()


HIZLI_TARAMA = {
    "tarama_araligi_sn": 0.2,
    "sabitlik_W_sn": 1.0,
    "aski_T_dk": 5,
    "dizin_deneme_plani": "0.5,0.5,0.5",
    "dizin_seyrek_deneme_sn": 1,
    "dizin_tarama_zaman_asimi_sn": 3,
}
TARAMA_EKLENTISI = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"}]


def duz_sir_yok(o: "Ortam", sir: str):
    """Düz şifre uygulamanın yazdığı hiçbir kalıcı dosyada (veritabanları + WAL, loglar, yedekler, ayarlar) geçmemeli."""
    for f in o.tmp.rglob("*"):
        if f.is_file():
            ham = f.read_bytes()
            for kod in ("utf-8", "utf-16-le"):
                assert sir.encode(kod) not in ham, f"düz şifre dosyada görünüyor: {f}"


class Yazici:
    """EFT gibi davranan yazıcı: dosyayı açık tutarak parça parça yazar (tutamaç açıkken paylaşım testi
    KILITLI verir)."""

    def __init__(self, yol):
        self.yol = Path(yol)
        self.f = open(self.yol, "wb")

    def yaz(self, veri: bytes):
        self.f.write(veri)
        self.f.flush()
        os.fsync(self.f.fileno())

    def kapat(self):
        self.f.close()


@pytest.fixture
def ortam_yap(tmp_path):
    olusturulan = []

    def yap(eklentiler=None, ayarlar=None):
        if eklentiler is None:
            eklentiler = [{"ad": "a", "modul": "testler.yardimci_eklenti"},
                          {"ad": "b", "modul": "testler.yardimci_eklenti"}]
        o = Ortam(tmp_path / f"o{len(olusturulan)}", eklentiler)
        o.ayar(**{**HIZLI_GOZETMEN, **(ayarlar or {})})
        olusturulan.append(o)
        return o

    yield yap
    for o in olusturulan:
        o.kapat()
