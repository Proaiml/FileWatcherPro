"""Önyüz uçtan uca testi: her düğme ve gösterge GERÇEK sistemle (çekirdek + tarama + teslim + kontrol süreçleri,
sahte Control-M) Edge tarayıcısında (Playwright, başsız) tıklanarak doğrulanır.

Her kontrol, arka uçtaki etkisiyle (veritabanı, sahte Control-M'e giden çağrı, lokal kayıt dosyası) birlikte
denetlenir: 'düğme tıklandı' yetmez, 'düğmenin yapması gereken iş oldu' aranır. Sonuç listesi
testler/_sonuc/onyuz_kontrol.json dosyasına yazılır (PROJE_DOSYALARI'ndaki kontrol listesi buradan üretilir).

Çalıştırma: py -3.11 -m pytest testler/test_onyuz_e2e.py -q -s
"""
import json
import os
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from cekirdek import win  # noqa: E402
from cekirdek.kullanicilar import Kullanicilar  # noqa: E402
from cekirdek.olaylar import KATALOG  # noqa: E402
from testler.conftest import HIZLI_TARAMA, Yazici, duz_sir_yok  # noqa: E402
from testler.sahte_controlm import SahteControlM  # noqa: E402
from testler.sahte_smtp import SahteSMTP  # noqa: E402
from testler.test_adim8_kontrol_api import Istemci  # noqa: E402

SONUC = Path(__file__).resolve().parent / "_sonuc" / "onyuz_kontrol.json"
SIFRE = "ornek-arayuz-sifresi-C"
EKLENTILER = [{"ad": "tarama", "modul": "eklentiler.tarama.tarayici"},
              {"ad": "teslim", "modul": "eklentiler.teslim.dagitici"},
              {"ad": "kontrol", "modul": "eklentiler.kontrol.kontrol_api"},
              {"ad": "izleme", "modul": "eklentiler.izleme.izleyici"},
              {"ad": "bildirim", "modul": "eklentiler.bildirim.bildirimci"}]
AYAR = {**HIZLI_TARAMA, "sabitlik_W_sn": 0.3, "aski_T_dk": 0.1, "deneme_plani": "0.5,1,1.5", "cagri_timeout_sn": 1,
        "otomatik_devre_esigi": 0, "erit_hizi": 20, "izleme_aralik_sn": 1, "izleme_normale_donus_sn": 1,
        "bildirim_deneme_plani": "0.5,0.5"}
SMTP_SIFRE = "ornek-smtp-sifresi"                     # yalnızca sahte SMTP'nin test şifresi (ortam değişkeninden okunur)
expect.set_options(timeout=20_000)


class Liste:
    """Kontrol listesi: her satır (ekran, düğme/gösterge, beklenen iş, sonuç, süre). Her test kendi bölümünü yazar;
    dosya bütün testlerin son koşusunu birlikte tutar (PROJE_DOSYALARI > Önyüz kontrol listesi)."""

    def __init__(self, test="Ana akış"):
        self.test = test
        self.satirlar = []

    @contextmanager
    def __call__(self, ekran, oge, beklenen):
        t0 = time.time()
        try:
            yield
        except BaseException as e:
            self.satirlar.append({"ekran": ekran, "oge": oge, "beklenen": beklenen, "sonuc": "HATA",
                                  "ayrinti": str(e).splitlines()[0][:300] if str(e) else type(e).__name__})
            raise
        self.satirlar.append({"ekran": ekran, "oge": oge, "beklenen": beklenen, "sonuc": "Doğrulandı",
                              "ayrinti": f"{time.time() - t0:.1f} sn"})

    def yaz(self):
        SONUC.parent.mkdir(exist_ok=True)
        try:
            testler = json.loads(SONUC.read_text(encoding="utf-8")).get("testler", {})
        except (OSError, ValueError):
            testler = {}
        testler[self.test] = {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "satirlar": self.satirlar}
        SONUC.write_text(json.dumps({"testler": testler}, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.fixture
def liste(request):
    L = Liste(request.node.name)
    yield L
    L.yaz()


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv("FWP_TEST_SMTP_SIFRE", SMTP_SIFRE)            # çekirdek süreçleri bu ortamı devralır
    s = SahteSMTP("fwp", SMTP_SIFRE).baslat()
    yield s
    s.durdur()


@pytest.fixture
def sistem(ortam_yap, tmp_path, smtp):
    yield from _sistem_kur(ortam_yap, EKLENTILER)


@pytest.fixture
def asistanli_sistem(ortam_yap, tmp_path, smtp):
    """Yapay zekâ asistanı eklentisi de kurulu sistem (menüde 'Yapay zekâ asistanı' yalnızca o zaman görünür)."""
    yield from _sistem_kur(ortam_yap, EKLENTILER + [{"ad": "asistan", "modul": "eklentiler.asistan.asistan"}], ("asistan",))


def _sistem_kur(ortam_yap, eklentiler, ek=()):
    sahte = SahteControlM(kimliksiz=True).baslat()
    o = ortam_yap(eklentiler=eklentiler, ayarlar=AYAR)
    b = json.loads(o.baslangic.read_text(encoding="utf-8"))          # canlıdaki gibi sabit port: kontrol yeniden
    with socket.socket() as so:                                      # başlayınca tarayıcı aynı adrese döner
        so.bind(("127.0.0.1", 0))
        b["kontrol_port"] = so.getsockname()[1]
    o.baslangic.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    k = Kullanicilar(o.baslangic.parent / "kullanicilar.json")
    for ad, rol in (("yonetici", "YONETICI"), ("operator", "OPERATOR"), ("izleyici", "IZLEYICI")):
        k.ekle(ad, SIFRE, rol)
    o.cekirdek_baslat()
    s = o.bekle(lambda: (e := o.eklenti("kontrol")) and e["durum"] == "CALISIYOR"
                and json.loads(e["bilgi"] or "{}").get("port") and e)
    o.bekle(lambda: all((e := o.eklenti(a)) and e["durum"] == "CALISIYOR" for a in ("tarama", "teslim", "izleme", "bildirim", *ek)))
    try:
        yield o, sahte, f"http://127.0.0.1:{json.loads(s['bilgi'])['port']}"
    finally:
        sahte.durdur()


@pytest.fixture
def tarayici():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        yield b
        b.close()


# ---------------------------------------------------------------- yardımcılar
def giris(sayfa, url, ad, sifre=SIFRE):
    sayfa.goto(url + "/")
    sayfa.locator("#g_ad").fill(ad)
    sayfa.locator("#g_sifre").fill(sifre)
    sayfa.get_by_role("button", name="Giriş yap", exact=True).click()


def git(sayfa, ad):
    sayfa.locator("#yan a", has_text=ad).click()
    expect(sayfa.locator("#icerik h1")).to_have_text(ad if ad != "Lokal kayıt ve erit" else "Lokal kayıt ve kademeli erit")


def bildirim(sayfa, metin):
    expect(sayfa.locator(".bildirim", has_text=metin).last).to_be_visible()


def pencere(sayfa, ad):
    p = sayfa.get_by_role("dialog", name=ad)
    expect(p).to_be_visible()
    return p


def hedef_turu_sec(sayfa, tur):
    """Hedef ekle → tür seçimi penceresi (Control-M / Genel API / Betik) → Devam → türün penceresi."""
    sayfa.get_by_role("button", name="Hedef ekle", exact=True).click()
    t = sayfa.get_by_role("dialog", name="Hedef ekle", exact=True)
    expect(t).to_be_visible()
    t.locator(".secim-kart", has_text=tur).first.click()
    t.get_by_role("button", name="Devam", exact=True).click()
    return pencere(sayfa, f"Hedef ekle · {tur}")


def kpi(sayfa, ad):
    return sayfa.locator(".kpi", has_text=ad).locator(".deger")


def oturum(tarayici, url, ad="yonetici"):
    """Yeni tarayıcı bağlamında giriş yapılmış sayfa; JavaScript hataları sayfa.hatalar'da toplanır."""
    s = tarayici.new_context(viewport={"width": 1440, "height": 900}, locale="tr-TR").new_page()
    s.hatalar = []
    s.on("pageerror", lambda e: s.hatalar.append(str(e)))
    giris(s, url, ad)
    expect(s.locator("header.ust")).to_contain_text(ad)
    return s


def api(url, ad="yonetici"):
    """Önyüzün kullandığı REST API'ye giriş yapılmış istemci (test hazırlığı için)."""
    y = Istemci(int(url.rsplit(":", 1)[1]))
    assert y.giris(ad, SIFRE)[0] == 200
    return y


def eski_yap(d: Path):
    """Dizindeki dosyaları 1 saat öncesine çek: 'sabit' sayılsınlar (ilk kurulum temeli)."""
    t = time.time() - 3600
    for f in d.iterdir():
        os.utime(f, (t, t))


def tetik(o, ad):
    return o.db.tek("SELECT * FROM tetik WHERE dosya_adi=?", (ad,))


def yaz(d: Path, ad: str, veri=None):
    (d / ad).write_bytes(veri if veri is not None else ad.encode())


# ================================================================ test
def test_onyuz_her_dugme_ve_gosterge(sistem, tarayici, tmp_path, liste):
    o, sahte, url = sistem
    L = liste
    baglam = tarayici.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True, locale="tr-TR")
    s = baglam.new_page()
    hatalar = []
    s.on("pageerror", lambda e: hatalar.append(str(e)))
    d = tmp_path / "gelen"
    d.mkdir()
    try:
        _akis(o, sahte, url, s, d, L, tarayici, tmp_path)
        assert not hatalar, f"tarayıcıda JavaScript hatası: {hatalar[:3]}"
    finally:
        baglam.close()


def _akis(o, sahte, url, s, d, L, tarayici, tmp_path):
    # ------------------------------------------------------------ giriş
    with L("Giriş", "Giriş yap (hatalı şifre)", "hata mesajı görünür, oturum açılmaz"):
        giris(s, url, "yonetici", "yanlis-sifre")
        expect(s.locator(".alan.hata")).to_contain_text("hatalı")
    with L("Giriş", "Giriş yap", "uygulama açılır; üst çubukta kullanıcı adı ve rolü"):
        s.locator("#g_sifre").fill(SIFRE)
        s.get_by_role("button", name="Giriş yap", exact=True).click()
        expect(s.locator("header.ust")).to_contain_text("yonetici")
        expect(s.locator("header.ust")).to_contain_text("Yönetici")
    with L("Üst çubuk", "Genel durum göstergesi", "sorun yokken 'Her şey yolunda'"):
        expect(s.locator("#genel_durum")).to_contain_text("Her şey yolunda")
    with L("Üst çubuk", "Tema düğmesi", "açık/koyu değişir, yenilemede korunur"):
        once = s.evaluate("document.documentElement.dataset.tema")
        s.get_by_role("button", name="Tema değiştir", exact=True).click()
        sonra = s.evaluate("document.documentElement.dataset.tema")
        assert {once, sonra} == {"acik", "koyu"}
        s.reload()
        expect(s.locator("header.ust")).to_be_visible()
        assert s.evaluate("document.documentElement.dataset.tema") == sonra
        s.get_by_role("button", name="Tema değiştir", exact=True).click()
    with L("Üst çubuk", "Gönderim düğmesi (hedef yokken)", "hedef tanımlı değilken gösterilmez"):
        expect(s.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True)).to_have_count(0)
        expect(s.get_by_role("button", name="Gönderimi yeniden başlat", exact=True)).to_have_count(0)

    # ------------------------------------------------------------ hedef
    with L("Hedefler", "Hedef ekle → Bağlantıyı dene", "kaydetmeden erişim ve kimlik denenir; iş tetiklenmez"):
        git(s, "Hedefler")
        p = hedef_turu_sec(s, "Control-M")
        p.get_by_placeholder("örn. Control-M Prod").fill("controlm")
        p.get_by_placeholder("https://ctm-sunucu:8443/automation-api").fill("http://127.0.0.1:9/automation-api")
        p.get_by_placeholder("ctmprod (şablonlarda {ctm})").fill("ctmsunucu")
        p.locator("select").select_option("yok")
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.bad")).to_contain_text("✗")
        p.get_by_placeholder("https://ctm-sunucu:8443/automation-api").fill(sahte.adres)
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.ok")).to_contain_text("✓")
        assert not sahte.istekler and o.db.tek("SELECT COUNT(*) FROM hedef")[0] == 0
    with L("Hedefler", "Hedef ekle", "Control-M hedefi eklenir; kartta 'Açık'"):
        p.get_by_role("button", name="Hedefi ekle", exact=True).click()
        bildirim(s, "Hedef eklendi")
        expect(s.locator(".kart", has_text="controlm").first).to_contain_text("Açık")
        assert o.db.tek("SELECT COUNT(*) FROM hedef")[0] == 1
    with L("Üst çubuk", "Gönderimi durdur (tüm hedefler) (görünürlük)", "hedef eklenince üst çubukta görünür"):
        expect(s.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True)).to_be_visible()

    # ------------------------------------------------------------ dizin + kural
    with L("Dizinler", "Dizin ekle (seçim yapmadan)", "ilk kurulum seçimi zorunlu: hata mesajı"):
        git(s, "Dizinler ve kurallar")
        s.get_by_role("button", name="Dizin ekle", exact=True).click()
        p = pencere(s, "Dizin ekle")
        p.locator("input.mono").fill(str(d))
        p.get_by_placeholder("örn. Muhasebe gelen").fill("Muhasebe")
        p.get_by_placeholder(".csv, .txt (boş = hepsi)").fill(".csv")
        p.get_by_role("button", name="Dizini ekle", exact=True).click()
        expect(p.locator(".alan.hata")).to_contain_text("seçim yapın")
    with L("Dizinler", "Dizin ekle", "dizin eklenir, tarama başlar; kartta erişim durumu"):
        p.get_by_text("Tetikle", exact=True).click()
        p.get_by_role("button", name="Dizini ekle", exact=True).click()
        bildirim(s, "Dizin eklendi")
        expect(s.locator(".kart", has_text=str(d))).to_be_visible()
        o.bekle(lambda: o.db.tek("SELECT erisim_durumu FROM dizin")[0] == "ERISILEBILIR")
    with L("Dizinler", "Erişim göstergesi (kart)", "tarama başlayınca sayfa yenilemeden 'Erişilebilir'"):
        expect(s.locator(".kart", has_text=str(d))).to_contain_text("Erişilebilir")
    with L("Dizinler", "Kural ekle → canlı regex denemesi", "örnek adlarda eşleşme ve isimli grup anında görünür"):
        s.locator(".kart", has_text=str(d)).get_by_role("button", name="Kural ekle", exact=True).click()
        p = pencere(s, f"Kural ekle · {d}")
        p.get_by_placeholder("örn. fatura").fill("fatura")
        p.locator("#kural_regex").fill(r"FATURA_(?P<tarih>\d{8})\.csv")
        satir = p.locator("table.eslesme tr", has_text="FATURA_20260929.csv")
        expect(satir).to_contain_text("✓ eşleşiyor")
        expect(satir).to_contain_text("tarih=20260929")
        expect(p.locator("table.eslesme tr", has_text="IADE_1.txt")).to_contain_text("eşleşmiyor")
    with L("Dizinler", "Kural ekle → hatalı regex", "canlı denemede hata mesajı"):
        p.locator("#kural_regex").fill("FATURA_(")
        expect(p.locator(".alan.hata").first).to_be_visible()
        p.locator("#kural_regex").fill(r"FATURA_(?P<tarih>\d{8})\.csv")
        expect(p.locator("table.eslesme")).to_be_visible()
    with L("Dizinler", "Kural isteği → hazır şablon (run/order)", "şablon seçilince yöntem, yol ve gövde dolar"):
        p.locator("select").filter(has_text="Hazır şablon seç").select_option("siparis")
        expect(p.get_by_placeholder("/run/event/{ctm}/OLAY_ADI/ODAT")).to_have_value("/run/order")
        expect(p.get_by_placeholder("Boş bırakılabilir (gövdesiz istek)")).to_have_value(re.compile(r'"FWP_DOSYA": "\{dosya_adi\}"'))
    with L("Dizinler", "Kuralı ekle", "kural isteğiyle kaydedilir; tabloda istek ve 'Açık'"):
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        bildirim(s, "Kural eklendi")
        expect(s.locator("tr", has_text="fatura")).to_contain_text("Açık")
        expect(s.locator("tr", has_text="fatura")).to_contain_text("POST /run/order")
        assert json.loads(o.db.tek("SELECT istek FROM kural")[0])["yol"] == "/run/order"

    # ------------------------------------------------------------ normal akış ve göstergeler
    with L("Genel bakış", "Bugün iletilen / p95 / hedef ölçüleri", "dosya gelince sayılar canlı artar"):
        git(s, "Genel bakış")
        yaz(d, "FATURA_20260929.csv")
        expect(kpi(s, "Bugün iletilen")).to_have_text("1")
        expect(kpi(s, "Tetik süresi (p95)")).not_to_have_text("—")
        assert len(sahte.siparisler) == 1
    with L("Genel bakış", "İzlenen dizinler tablosu", "erişim, son tarama, liste süresi, aktif dosya canlı"):
        satir = s.locator("tr", has_text=str(d))
        expect(satir).to_contain_text("Erişilebilir")
        expect(satir).to_contain_text("ms")
        expect(satir.locator("td").nth(4)).to_have_text("1")
    with L("Genel bakış", "Bileşenler (nabız)", "çekirdek/tarama/teslim/kontrol 'Çalışıyor' ve nabız"):
        kart_ = s.locator(".kart", has_text="Bileşenler")
        for ad in ("Tarama", "Teslim", "Kontrol arayüzü", "Sistem izleme", "Bildirim (mail)"):
            expect(kart_.locator("tr", has_text=ad)).to_contain_text("Çalışıyor")
        expect(kart_).to_contain_text("nabız")
    with L("Dosyalar", "Son dosyalar sekmesi", "iletilen dosya 'İletildi' ve süresiyle listelenir"):
        git(s, "Dosyalar")
        s.get_by_role("tab", name="Son dosyalar").click()
        expect(s.locator("tr", has_text="FATURA_20260929.csv")).to_contain_text("İletildi")
    with L("Dosyalar", "Satır → zaman çizelgesi çekmecesi", "tam yol, hash, idempotency, 'Hedef kabul etti'"):
        s.locator("tr", has_text="FATURA_20260929.csv").click()
        c = s.locator("aside.cekmece")
        expect(c).to_contain_text("Hedef kabul etti")
        expect(c).to_contain_text(tetik(o, "FATURA_20260929.csv")["idempotency"])
        expect(c).to_contain_text("xxh3")
    with L("Dosyalar", "Çekmece kapat", "çekmece kapanır"):
        c.get_by_role("button", name="Kapat", exact=True).click()
        expect(s.locator("aside.cekmece")).to_have_count(0)
    with L("Dosyalar", "Arama kutusu", "ada göre süzer"):
        s.locator("#ara_dosya").fill("YOKBOYLE")
        expect(s.locator("#icerik")).to_contain_text("Kayıt yok.")
        s.locator("#ara_dosya").fill("")
        expect(s.locator("tr", has_text="FATURA_20260929.csv")).to_be_visible()
    with L("Dosyalar", "Yükleniyor sekmesi + menü rozeti", "yazılan dosya tetiklenmeden 'Yazılıyor/tutuyor' görünür"):
        s.get_by_role("tab", name="Yükleniyor").click()
        y = Yazici(d / "FATURA_20260930.csv")
        y.yaz(b"a" * 100_000)
        satir = s.locator("tr", has_text="FATURA_20260930.csv")
        expect(satir).to_contain_text("Yaz")
        expect(s.locator("#yan a", has_text="Dosyalar").locator(".say")).to_have_text("1")
        assert tetik(o, "FATURA_20260930.csv") is None
    with L("Dosyalar", "Askıda göstergesi + alarm", "T süresini aşan yükleme 'Askıda' ve uyarı alarmı"):
        expect(satir).to_contain_text("Askıda", timeout=30_000)
        expect(s.locator("#genel_durum")).to_contain_text("Dikkat")
        assert tetik(o, "FATURA_20260930.csv") is None
    with L("Dosyalar", "Yükleme bitince", "satır kalkar, tek tetik gider, askı alarmı kapanır"):
        y.yaz(b"b" * 1000)
        y.kapat()
        expect(s.locator("tr", has_text="FATURA_20260930.csv")).to_have_count(0)
        o.bekle(lambda: (t := tetik(o, "FATURA_20260930.csv")) and t["durum"] == "ILETILDI")
        expect(s.locator("#genel_durum")).to_contain_text("Her şey yolunda")

    # ------------------------------------------------------------ kayıtlı kapat → lokal → erit
    with L("Üst çubuk", "Gönderimi durdur → Kayıtsız seçimi", "'anladım' işaretlenmeden Durdur pasif"):
        s.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True).click()
        p = pencere(s, "Gönderimi durdur (tüm hedefler)")
        p.get_by_text("Kayıtsız durdur", exact=True).click()
        expect(p.get_by_role("button", name="Durdur", exact=True)).to_be_disabled()
        p.get_by_role("checkbox").check()
        expect(p.get_by_role("button", name="Durdur", exact=True)).to_be_enabled()
        p.get_by_role("checkbox").uncheck()
        expect(p.get_by_role("button", name="Durdur", exact=True)).to_be_disabled()
    with L("Üst çubuk", "Gönderimi durdur (kayıtlı)", "hedef kapanır; üst çubuk 'Gönderimi yeniden başlat' olur"):
        p.get_by_text("Kayıtlı durdur (önerilen)", exact=True).click()
        p.get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Gönderim durduruldu")
        expect(s.get_by_role("button", name="Gönderimi yeniden başlat", exact=True)).to_be_visible()
        assert o.db.tek("SELECT aktif, kapatma_modu FROM hedef")[:] == (0, "KAYITLI")
    kapali_adlar = [f"FATURA_2026100{i}.csv" for i in range(1, 7)]
    with L("Genel bakış", "Lokalde bekleyen + menü rozeti", "kapalıyken gelenler lokale yazılır, sayı görünür"):
        git(s, "Genel bakış")
        for a in kapali_adlar:
            yaz(d, a)
            time.sleep(0.05)
        expect(kpi(s, "Lokalde bekleyen")).to_have_text("6")
        expect(s.locator("#yan a", has_text="Lokal kayıt").locator(".say")).to_have_text("6")
        assert all(Path(tetik(o, a)["lokal_dosya"]).exists() for a in kapali_adlar)
        assert len(sahte.siparisler) == 2
    with L("Hedefler", "Kart durumu (kapalı)", "'Kapalı · kayıtlı', kapatan kullanıcı, 'Lokaldekiler (6)'"):
        git(s, "Hedefler")
        k = s.locator(".kart", has_text="controlm")
        expect(k).to_contain_text("Kapalı · kayıtlı")
        expect(k).to_contain_text("yonetici")
    with L("Hedefler", "Lokaldekiler (6) düğmesi", "lokal kayıt sayfasına gider"):
        k.get_by_role("button", name="Lokaldekiler (6)", exact=True).click()
        expect(s.locator("#icerik h1")).to_have_text("Lokal kayıt ve kademeli erit")
    with L("Lokal kayıt", "Bekleyen kayıtlar tablosu", "6 kayıt geliş sırasıyla, '✓ yazıldı', sebep"):
        expect(s.locator("#icerik tbody tr")).to_have_count(6)
        expect(s.locator("#icerik tbody tr").first).to_contain_text(kapali_adlar[0])
        expect(s.locator("#icerik tbody")).to_contain_text("✓ yazıldı")
        expect(s.locator("#icerik tbody")).to_contain_text("Hedef kayıtlı kapalıydı")
    with L("Lokal kayıt", "Kademeli erit başlat (hedef kapalıyken)", "pasif, ipucu 'Önce hedefi açın'"):
        b = s.get_by_role("button", name="Kademeli erit başlat", exact=True)
        expect(b).to_be_disabled()
        expect(b).to_have_attribute("title", "Önce hedefi açın")
    with L("Üst çubuk", "Gönderimi yeniden başlat", "pencere lokaldeki 6 kaydı hatırlatır; hedef açılır, erit kendiliğinden başlamaz"):
        s.get_by_role("button", name="Gönderimi yeniden başlat", exact=True).click()
        p = pencere(s, "Gönderimi yeniden başlat")
        expect(p).to_contain_text("Lokalde 6 kayıt bekliyor")
        p.get_by_role("button", name="Gönderimi aç", exact=True).click()
        bildirim(s, "Gönderim açıldı")
        expect(s.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True)).to_be_visible()
        time.sleep(1)
        assert len(sahte.siparisler) == 2
    with L("Lokal kayıt", "Kademeli erit başlat → hız + tahmin", "pencerede tahmini süre; erit başlar, 'Eritiliyor' rozeti"):
        b = s.get_by_role("button", name="Kademeli erit başlat", exact=True)
        expect(b).to_be_enabled()
        b.click()
        p = pencere(s, "controlm: kademeli erit")
        p.locator("input[type=number]").fill("0.5")
        expect(p.locator(".ipucu")).to_contain_text("saniyede 0.5")
        p.get_by_role("button", name="Eriti başlat", exact=True).click()
        bildirim(s, "Kademeli erit başladı")
        expect(s.locator("#icerik")).to_contain_text("Eritiliyor · 0.5/sn")
    with L("Lokal kayıt", "Duraklat", "erit duraklar, gönderim kesilir, 'Erit duraklatıldı'"):
        s.get_by_role("button", name="Duraklat", exact=True).click()
        bildirim(s, "Erit duraklatıldı")
        expect(s.locator("#icerik")).to_contain_text("Erit duraklatıldı")
        n = len(sahte.siparisler)
        time.sleep(2.5)
        assert len(sahte.siparisler) <= n + 1, "duraklatıldıktan sonra gönderim sürdü"
        assert len(sahte.siparisler) < 8
    with L("Lokal kayıt", "Eriti sürdür → Durdur", "sürdür çalışır; Durdur eriti bitirir, kalanlar lokalde"):
        s.get_by_role("button", name="Eriti sürdür", exact=True).click()
        p = pencere(s, "controlm: kademeli erit")
        p.locator("input[type=number]").fill("0.5")
        p.get_by_role("button", name="Eriti başlat", exact=True).click()
        expect(s.locator("#icerik")).to_contain_text("Eritiliyor")
        s.get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Erit durduruldu")
        expect(s.get_by_role("button", name="Kademeli erit başlat", exact=True)).to_be_visible()
        assert o.db.tek("SELECT erit_durumu FROM hedef")[0] == "YOK"
        assert o.db.tek("SELECT COUNT(*) FROM tetik WHERE durum='LOKALDE'")[0] >= 1
    with L("Lokal kayıt", "Kademeli erit (sonuna kadar)", "kalanlar sırayla, tam bir kez gider; tablo boşalır"):
        s.get_by_role("button", name="Kademeli erit başlat", exact=True).click()
        p = pencere(s, "controlm: kademeli erit")
        p.locator("input[type=number]").fill("20")
        p.get_by_role("button", name="Eriti başlat", exact=True).click()
        expect(s.locator("#icerik")).to_contain_text("Lokalde bekleyen kayıt yok.")
        say = sahte.idempotency_sayilari()
        assert all(say[tetik(o, a)["idempotency"]] == 1 for a in kapali_adlar)
        assert not any(Path(tetik(o, a)["lokal_dosya"]).exists() for a in kapali_adlar)
        gelen = [next(v["FWP_DOSYA"] for v in x["govde"]["variables"] if "FWP_DOSYA" in v) for x in sahte.siparisler][2:]
        sira = [r["dosya_adi"] for r in o.db.oku("SELECT dosya_adi FROM tetik WHERE dosya_adi IN (%s) ORDER BY olusturma, id"
                                                  % ",".join("?" * len(kapali_adlar)), kapali_adlar)]
        assert gelen == kapali_adlar, f"gelen={gelen} olusturma_sirasi={sira} gonderim_zamani={[round(x['zaman'] % 100, 3) for x in sahte.siparisler][2:]}"
    with L("Genel bakış", "Bugün iletilen → 'kademeli eritten'", "erit sayısı ayrı gösterilir"):
        git(s, "Genel bakış")
        expect(kpi(s, "Bugün iletilen")).to_have_text("8")
        expect(s.locator(".kpi", has_text="Bugün iletilen")).to_contain_text("6 kademeli eritten")
        expect(s.locator("#yan a", has_text="Lokal kayıt").locator(".say")).to_have_count(0)

    # ------------------------------------------------------------ kayıtsız kapat + gönderilemeyenler
    with L("Üst çubuk", "Gönderimi durdur (kayıtsız)", "kırmızı şerit; gelen dosya gönderilmez ve saklanmaz"):
        s.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True).click()
        p = pencere(s, "Gönderimi durdur (tüm hedefler)")
        p.get_by_text("Kayıtsız durdur", exact=True).click()
        p.get_by_role("checkbox").check()
        p.get_by_role("button", name="Durdur", exact=True).click()
        expect(s.locator(".serit.kayitsiz")).to_contain_text("controlm kayıtsız kapalı")
        yaz(d, "FATURA_20261101.csv")
        o.bekle(lambda: (t := tetik(o, "FATURA_20261101.csv")) and t["durum"] == "KAYITSIZ_KAPALI")
        assert tetik(o, "FATURA_20261101.csv")["lokal_dosya"] is None and len(sahte.siparisler) == 8
    with L("Gönderilemeyenler", "Durum ve sebep süzgeçleri", "kayıtsız kapalıyken gelen 'Bilerek gönderilmedi'"):
        git(s, "Gönderilemeyenler")
        s.get_by_label("Durum").select_option("")
        satir = s.locator("tr", has_text="FATURA_20261101.csv")
        expect(satir).to_contain_text("Hedef kayıtsız kapalıydı")
        expect(satir).to_contain_text("Bilerek gönderilmedi")
        s.get_by_label("Sebep").select_option("DEVRE_KESIK")
        expect(s.locator("#icerik")).to_contain_text("Bu filtreye uyan kayıt yok.")
        s.get_by_label("Sebep").select_option("")
        expect(s.locator("tr", has_text="FATURA_20261101.csv")).to_be_visible()
    with L("Gönderilemeyenler", "CSV indir", "Excel'in açacağı UTF-8 BOM'lu, ';' ayraçlı dosya iner"):
        with s.expect_download() as indir:
            s.get_by_role("button", name="CSV indir", exact=True).click()
        metin = Path(indir.value.path()).read_text(encoding="utf-8")
        assert metin.startswith("﻿dosya_adi;tam_yol;sebep") and "FATURA_20261101.csv" in metin
        assert indir.value.suggested_filename.startswith("gonderilemeyenler_")
        assert s.evaluate("csvHucre('=HYPERLINK(1)')") == '"\'=HYPERLINK(1)"'          # Excel formülü olarak çalışmaz
        assert s.evaluate("csvHucre('FATURA_1.csv')") == '"FATURA_1.csv"'
    with L("Kriz şeridi", "Gönderimi aç (şerit düğmesi)", "şeritten hedef açılır, şerit kalkar"):
        s.locator(".serit.kayitsiz").get_by_role("button", name="Gönderimi aç", exact=True).click()
        pencere(s, "controlm: gönderimi aç").get_by_role("button", name="Gönderimi aç", exact=True).click()
        bildirim(s, "Gönderim açıldı")
        expect(s.locator(".serit.kayitsiz")).to_have_count(0)

    # ------------------------------------------------------------ ayarlar
    with L("Ayarlar", "Değişiklikleri kaydet (geçersiz değer)", "doğrulama hatası pencerede; kaydedilmez"):
        git(s, "Ayarlar")
        kaydet = s.get_by_role("button", name="Değişiklikleri kaydet", exact=True)
        expect(kaydet).to_be_disabled()
        s.locator("#ay_erit_hizi").fill("100000")
        s.get_by_role("button", name="1 değişikliği kaydet", exact=True).click()
        p = pencere(s, "Ayarları kaydet")
        p.get_by_role("button", name="Ayarları kaydet", exact=True).click()
        expect(p.locator(".alan.hata")).not_to_be_empty()
        p.get_by_role("button", name="Vazgeç", exact=True).click()
        assert json.loads(o.db.tek("SELECT deger FROM ayar WHERE anahtar='erit_hizi'")[0]) == 20
    with L("Ayarlar", "Değişiklikleri kaydet", "değişiklik listesi gösterilir, kaydedilir, eklentilere yansır"):
        git(s, "Genel bakış")
        git(s, "Ayarlar")
        s.locator("#ay_otomatik_devre_esigi").fill("2")
        s.get_by_role("button", name="1 değişikliği kaydet", exact=True).click()
        p = pencere(s, "Ayarları kaydet")
        expect(p).to_contain_text("otomatik_devre_esigi → 2")
        p.get_by_role("button", name="Ayarları kaydet", exact=True).click()
        bildirim(s, "Ayarlar kaydedildi")
        assert json.loads(o.db.tek("SELECT deger FROM ayar WHERE anahtar='otomatik_devre_esigi'")[0]) == 2

    # ------------------------------------------------------------ devre kesici
    with L("Kriz şeridi", "Devre kesik şeridi + kritik gösterge", "Control-M kopunca devre kesilir; kırmızı şerit, 'Kritik'"):
        git(s, "Genel bakış")
        sahte.mod_ayarla("kopma")
        yaz(d, "FATURA_20261201.csv")
        yaz(d, "FATURA_20261202.csv")
        expect(s.locator(".serit.kritik", has_text="devre kesik")).to_be_visible(timeout=30_000)
        expect(s.locator("#genel_durum")).to_contain_text("Kritik")
        expect(s.locator("#yan a", has_text="Alarmlar").locator(".say.kirmizi")).to_be_visible()
    with L("Kriz şeridi", "Devreyi normale al", "pencere son yoklamayı gösterir; devre normale döner"):
        sahte.mod_ayarla("normal")
        s.locator(".serit.kritik", has_text="devre kesik").get_by_role("button", name="Devreyi normale al", exact=True).click()
        p = pencere(s, "Devreyi normale al")
        expect(p).to_contain_text("Son yoklamada")
        p.get_by_role("button", name="Devreyi normale al", exact=True).click()
        bildirim(s, "Devre normale alındı")
        expect(s.locator(".serit.kritik", has_text="devre kesik")).to_have_count(0)
        assert o.db.tek("SELECT devre_durumu FROM hedef")[0] == "NORMAL"
    with L("Lokal kayıt", "Devre kesikken yazılanları erit", "iki dosya da tam bir kez gider"):
        git(s, "Lokal kayıt ve erit")
        s.get_by_role("button", name="Kademeli erit başlat", exact=True).click()
        p = pencere(s, "controlm: kademeli erit")
        p.locator("input[type=number]").fill("20")
        p.get_by_role("button", name="Eriti başlat", exact=True).click()
        expect(s.locator("#icerik")).to_contain_text("Lokalde bekleyen kayıt yok.")
        for a in ("FATURA_20261201.csv", "FATURA_20261202.csv"):
            t = tetik(o, a)
            assert t["durum"] == "ILETILDI"
            assert sahte.idempotency_sayilari()[t["idempotency"]] == 1 or t["belirsiz"] == 1

    # ------------------------------------------------------------ alarmlar
    with L("Alarmlar", "Onayla", "alarm kapanır, 'Kapanmış' listesinde onaylayan görünür"):
        o.db.alarm_ac("test:arayuz", "Arayüz deneme alarmı", "UYARI", "test")
        git(s, "Alarmlar")
        a = s.locator(".alarm", has_text="Arayüz deneme alarmı")
        expect(a).to_be_visible()
        a.get_by_role("button", name="Onayla", exact=True).click()
        bildirim(s, "Alarm onaylandı")
        expect(s.locator("tr", has_text="Arayüz deneme alarmı")).to_contain_text("yonetici")
    with L("Genel bakış", "Aktif alarmlar kartı → Onayla", "genel bakıştan da onaylanır"):
        o.db.alarm_ac("test:arayuz2", "Genel bakış alarmı", "UYARI", "test")
        git(s, "Genel bakış")
        a = s.locator(".alarm", has_text="Genel bakış alarmı")
        expect(a).to_be_visible()
        a.get_by_role("button", name="Onayla", exact=True).click()
        expect(s.locator(".alarm", has_text="Genel bakış alarmı")).to_have_count(0)
        assert o.db.tek("SELECT aktif FROM alarm WHERE anahtar='test:arayuz2'")[0] == 0

    # ------------------------------------------------------------ motor
    with L("Üst çubuk", "Motor anahtarı → durdur", "tarama durur; şerit; o sırada gelen dosya tetiklenmez"):
        s.locator("#motor_ust label").click()
        p = pencere(s, "Motoru durdur")
        p.get_by_role("button", name="Motoru durdur", exact=True).click()
        bildirim(s, "Motor durduruldu")
        expect(s.locator(".serit", has_text="Tarama motoru durduruldu")).to_be_visible()
        expect(s.locator("#motor_ust")).to_contain_text("Motor durdu")
        time.sleep(1)
        yaz(d, "FATURA_20261301.csv")
        time.sleep(2)
        assert tetik(o, "FATURA_20261301.csv") is None
    with L("Kriz şeridi", "Motoru başlat (şerit düğmesi)", "motor başlar; durduğu sürede gelen dosya yakalanır"):
        s.locator(".serit", has_text="Tarama motoru durduruldu").get_by_role("button", name="Motoru başlat", exact=True).click()
        pencere(s, "Motoru başlat").get_by_role("button", name="Motoru başlat", exact=True).click()
        bildirim(s, "Motor başlatıldı")
        expect(s.locator("#motor_ust")).to_contain_text("Motor çalışıyor")
        o.bekle(lambda: (t := tetik(o, "FATURA_20261301.csv")) and t["durum"] == "ILETILDI")

    # ------------------------------------------------------------ dizin erişim
    with L("Kriz şeridi", "Dizine erişilemiyor şeridi", "dizin kaybolunca kırmızı şerit ve 'Erişilemiyor'"):
        yedek = d.with_name("gelen_yedek")
        for _ in range(50):
            try:
                d.rename(yedek)
                break
            except PermissionError:
                time.sleep(0.1)
        expect(s.locator(".serit.kritik", has_text="Dizine erişilemiyor")).to_be_visible(timeout=30_000)
        expect(s.locator("tr", has_text=str(d))).to_contain_text("Erişilemiyor")
    with L("Kriz şeridi", "Şimdi dene", "yeniden deneme komutu gider; dizin gelince şerit kalkar"):
        s.locator(".serit.kritik", has_text="Dizine erişilemiyor").get_by_role("button", name="Şimdi dene", exact=True).click()
        bildirim(s, "Yeniden deneniyor")
        yedek.rename(d)
        expect(s.locator(".serit.kritik", has_text="Dizine erişilemiyor")).to_have_count(0)
        expect(s.locator("tr", has_text=str(d))).to_contain_text("Erişilebilir")
        assert o.db.tek("SELECT COUNT(*) FROM komut WHERE komut='SIMDI_DENE'")[0] >= 1
    with L("Genel bakış", "Şimdi dene (dizin satırı)", "komut gönderilir"):
        n = o.db.tek("SELECT COUNT(*) FROM komut WHERE komut='SIMDI_DENE'")[0]
        s.locator("tr", has_text=str(d)).get_by_role("button", name="Şimdi dene", exact=True).click()
        bildirim(s, "Dizin yeniden taranıyor")
        o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM komut WHERE komut='SIMDI_DENE'")[0] == n + 1)
    with L("Genel bakış", "Şimdi bakım yap + bakım göstergesi", "bakım çalışır; 'Son bakım … yonetici · Başarılı'"):
        s.get_by_role("button", name="Şimdi bakım yap", exact=True).click()
        bildirim(s, "Bakım başlatıldı")
        bildirim(s, "Bakım bitti · başarılı")
        expect(s.locator(".kart", has_text="Bakım ve kayıt")).to_contain_text(re.compile(r"yonetici\s*Başarılı"))
    with L("Genel bakış", "Hepsini gör / Tümü / Ayrıntı", "ilgili sayfalara gider"):
        s.get_by_role("button", name="Hepsini gör", exact=True).click()
        expect(s.locator("#icerik h1")).to_have_text("Hedefler")
        git(s, "Genel bakış")
        s.get_by_role("button", name="Tümü", exact=True).click()
        expect(s.locator("#icerik h1")).to_have_text("Alarmlar")
        git(s, "Genel bakış")
        s.get_by_role("button", name="Ayrıntı", exact=True).click()
        expect(s.locator("#icerik h1")).to_have_text("Eklentiler")

    # ------------------------------------------------------------ kural ve dizin işlemleri
    with L("Dizinler", "Kural Durdur (kayıtlı) / Aç", "kural durur: gelen dosya lokale; açılır"):
        git(s, "Dizinler ve kurallar")
        s.locator("tr", has_text="fatura").get_by_role("button", name="Durdur", exact=True).click()
        p = pencere(s, "Kuralı durdur")
        p.get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Kural(lar) durduruldu")
        expect(s.locator("tr", has_text="fatura")).to_contain_text("Kapalı · kayıtlı")
        yaz(d, "FATURA_20261401.csv")
        o.bekle(lambda: (t := tetik(o, "FATURA_20261401.csv")) and t["durum"] == "LOKALDE")
        s.locator("tr", has_text="fatura").get_by_role("button", name="Aç", exact=True).click()
        bildirim(s, "Kural açıldı")
        expect(s.locator("tr", has_text="fatura")).to_contain_text("Açık")
    with L("Dizinler", "İzlemeyi kapat / aç", "dizin taranmaz, 'İzleme kapalı'; açınca telafi"):
        s.get_by_role("button", name="İzlemeyi kapat", exact=True).click()
        pencere(s, "İzlemeyi kapat").get_by_role("button", name="İzlemeyi kapat", exact=True).click()
        expect(s.locator(".kart", has_text=str(d))).to_contain_text("İzleme kapalı")
        time.sleep(1)
        yaz(d, "FATURA_20261501.csv")
        time.sleep(2)
        assert tetik(o, "FATURA_20261501.csv") is None
        s.get_by_role("button", name="İzlemeyi aç", exact=True).click()
        pencere(s, "İzlemeyi aç").get_by_role("button", name="İzlemeyi aç", exact=True).click()
        expect(s.locator(".kart", has_text=str(d))).not_to_contain_text("İzleme kapalı")
        o.bekle(lambda: (t := tetik(o, "FATURA_20261501.csv")) and t["durum"] == "ILETILDI")
    with L("Dizinler", "Kuralı sil (çöp kutusu)", "onaydan sonra kural silinir"):
        s.get_by_role("button", name="Kuralı sil", exact=True).click()
        pencere(s, "Kuralı sil").get_by_role("button", name="Kuralı sil", exact=True).click()
        expect(s.locator(".kart", has_text=str(d))).to_contain_text("Bu dizinde kural yok")
        assert o.db.tek("SELECT COUNT(*) FROM kural")[0] == 0

    # ------------------------------------------------------------ eklentiler
    with L("Eklentiler", "Durdur / Başlat (tarama)", "eklenti durur ('Durduruldu'), önyüzden yeniden başlar"):
        git(s, "Eklentiler")
        k = s.locator(".kart", has_text="Tarama")
        k.get_by_role("button", name="Durdur", exact=True).click()
        pencere(s, "Eklentiyi durdur").get_by_role("button", name="Eklentiyi durdur", exact=True).click()
        expect(k).to_contain_text("Durduruldu")
        k.get_by_role("button", name="Başlat", exact=True).click()
        pencere(s, "Eklentiyi başlat").get_by_role("button", name="Eklentiyi başlat", exact=True).click()
        expect(k).to_contain_text("Çalışıyor")
    with L("Eklentiler", "Eklenti öldürülür (dışarıdan)", "çekirdek ayakta; eklenti düşer, kendiliğinden kalkar; sayaç artar"):
        k = s.locator(".kart", has_text="Teslim")
        eski = o.eklenti("teslim")["pid"]
        os.kill(eski, 9)
        o.bekle(lambda: (e := o.eklenti("teslim"))["pid"] != eski and e["durum"] == "CALISIYOR")
        assert o.proc.poll() is None
        expect(k).to_contain_text("1 kez")
        expect(k).to_contain_text("Çalışıyor")
    with L("Eklentiler", "Yeniden başlat (teslim)", "yeni PID ile kalkar"):
        eski = o.eklenti("teslim")["pid"]
        k.get_by_role("button", name="Yeniden başlat", exact=True).click()
        pencere(s, "Eklentiyi yeniden başlat").get_by_role("button", name="Eklentiyi yeniden başlat", exact=True).click()
        o.bekle(lambda: (e := o.eklenti("teslim"))["pid"] != eski and e["durum"] == "CALISIYOR")
        expect(k).to_contain_text(f"PID {o.eklenti('teslim')['pid']}")
    with L("Eklentiler", "Kontrol arayüzü kartı", "'Durdur' yok (önyüz kendini kapatamaz); adres ve oturum bilgisi"):
        k = s.locator(".kart", has_text="Kontrol arayüzü")
        expect(k.get_by_role("button", name="Durdur", exact=True)).to_have_count(0)
        expect(k).to_contain_text("oturum")

    # ------------------------------------------------------------ denetim
    with L("Denetim", "Denetim listesi + arama", "yapılan her işlem kullanıcıyla listelenir; arama süzer"):
        git(s, "Denetim kaydı")
        expect(s.locator("#icerik tbody tr").first).to_be_visible()
        s.locator("#ara_denetim").fill("hedef_kapat")
        expect(s.locator("#icerik tbody tr").first).to_contain_text("hedef kapat")
        for r in s.locator("#icerik tbody tr").all():
            assert "hedef kapat" in r.inner_text()
        s.locator("#ara_denetim").fill("")

    # ------------------------------------------------------------ roller
    with L("Roller", "Operatör", "işlem düğmeleri açık; yapılandırma düğmeleri pasif ve ipuçlu"):
        b2 = tarayici.new_context(viewport={"width": 1440, "height": 900})
        s2 = b2.new_page()
        giris(s2, url, "operator")
        expect(s2.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True)).to_be_enabled()
        git(s2, "Dizinler ve kurallar")
        expect(s2.get_by_role("button", name="Dizin ekle", exact=True)).to_be_disabled()
        expect(s2.get_by_role("button", name="Dizin ekle", exact=True)).to_have_attribute("title", "Bu işlem için Yönetici yetkisi gerekir")
        b2.close()
    with L("Roller", "İzleyici", "her şeyi görür; hiçbir işlem düğmesi çalışmaz"):
        b3 = tarayici.new_context(viewport={"width": 1440, "height": 900})
        s3 = b3.new_page()
        giris(s3, url, "izleyici")
        expect(s3.get_by_role("button", name="Gönderimi durdur (tüm hedefler)", exact=True)).to_be_disabled()
        expect(s3.locator("#motor_ust input")).to_be_disabled()
        expect(s3.get_by_role("button", name="Şimdi bakım yap", exact=True)).to_be_disabled()
        git(s3, "Eklentiler")
        expect(s3.get_by_role("button", name="Yeniden başlat", exact=True).first).to_be_disabled()
        b3.close()

    # ------------------------------------------------------------ bağlantı ve oturum
    with L("Üst çubuk", "Bağlantı göstergesi (kontrol yeniden başlar)", "kopunca 'Bağlantı koptu'; oturum düşünce giriş ekranı"):
        eski = o.eklenti("kontrol")["pid"]
        o.db.komut_gonder("gozetmen", "YENIDEN_BASLAT", {"ad": "kontrol"}, kullanici="test")
        o.bekle(lambda: (e := o.eklenti("kontrol"))["pid"] != eski and e["durum"] == "CALISIYOR")
        expect(s.locator("#g_ad")).to_be_visible(timeout=30_000)
        expect(s.locator(".alan.hata")).to_contain_text("yeniden giriş")
    with L("Üst çubuk", "Şifre değiştir", "şifre değişir; eski şifreyle giriş reddedilir, yeniyle açılır"):
        giris(s, url, "yonetici")
        expect(s.locator("header.ust")).to_contain_text("yonetici")
        s.get_by_role("button", name="Şifre değiştir", exact=True).click()
        p = pencere(s, "Şifre değiştir: yonetici")
        p.locator("#s_eski").fill(SIFRE)
        p.locator("#s_yeni").fill("yepyeni-sifre-2026")
        p.locator("#s_tekrar").fill("yepyeni-sifre-2026")
        p.get_by_role("button", name="Şifreyi değiştir", exact=True).click()
        bildirim(s, "Şifre değiştirildi")
    with L("Üst çubuk", "Çıkış", "oturum kapanır; giriş ekranı"):
        s.get_by_role("button", name="Çıkış", exact=True).click()
        expect(s.locator("#g_ad")).to_be_visible()
        giris(s, url, "yonetici")
        expect(s.locator(".alan.hata")).to_contain_text("hatalı")
        s.locator("#g_sifre").fill("yepyeni-sifre-2026")
        s.get_by_role("button", name="Giriş yap", exact=True).click()
        expect(s.locator("header.ust")).to_contain_text("yonetici")
    with L("Dizinler", "Dizini sil", "yol aynen yazılmadan Sil pasif; silinince dizin kalkar"):
        git(s, "Dizinler ve kurallar")
        s.get_by_role("button", name="Sil", exact=True).click()
        p = pencere(s, "Dizini sil")
        expect(p.get_by_role("button", name="Sil", exact=True)).to_be_disabled()
        p.locator("input.mono").fill(str(d)[:-1])
        expect(p.get_by_role("button", name="Sil", exact=True)).to_be_disabled()
        p.locator("input.mono").fill(str(d))
        p.get_by_role("button", name="Sil", exact=True).click()
        bildirim(s, "Dizin silindi")
        expect(s.locator("#icerik")).to_contain_text("Henüz dizin yok.")

    # ------------------------------------------------------------ genel doğrulama
    with L("Bütün akış", "Kayıp / çift / yanlış dosya", "her tetik tam bir kez; eşleşmeyen tetiklenmedi"):
        say = sahte.idempotency_sayilari()
        for t in o.db.oku("SELECT * FROM tetik WHERE durum='ILETILDI'"):
            assert say[t["idempotency"]] == 1 or t["belirsiz"] == 1, t["dosya_adi"]
        assert all(t["dosya_adi"].startswith("FATURA_") for t in o.db.oku("SELECT dosya_adi FROM tetik"))


# ================================================================ bakım: sonuç bildirimi ve hata olursa geri alma
def _bakim_akisi(sistem, tarayici, basarili, L):
    o, sahte, url = sistem
    s = oturum(tarayici, url)
    kart_ = s.locator(".kart", has_text="Bakım ve kayıt")
    expect(kart_).to_contain_text("Sonraki bakım")
    ilk = float(o.db.meta_al("son_bakim") or 0)
    if basarili:
        with L("Genel bakış", "Şimdi bakım yap → sonuç", "'başlatıldı' ardından 'bitti · başarılı'; kartta budanan ve boyut"):
            s.get_by_role("button", name="Şimdi bakım yap", exact=True).click()
            bildirim(s, "Bakım başlatıldı")
            bildirim(s, "Bakım bitti · başarılı")
            expect(kart_).to_contain_text("Başarılı")
            expect(kart_).to_contain_text("Budanan")
    else:
        with L("Genel bakış", "Şimdi bakım yap → adım hata verir", "adım geri alınır; 'izleme etkilenmedi'; kart 'Başarısız'"):
            s.get_by_role("button", name="Şimdi bakım yap", exact=True).click()
            bildirim(s, "Bakım başlatıldı")
            bildirim(s, "adımı hata verdi ve geri alındı")
            expect(s.locator(".bildirim", has_text="izleme etkilenmedi").last).to_be_visible()
            expect(kart_).to_contain_text("Başarısız")
            expect(kart_).to_contain_text("geri alındı")
    assert float(o.db.meta_al("son_bakim")) > ilk
    with L("Genel bakış", "Bakım geçmişi", "son bakım kullanıcı ve sonucuyla listelenir"):
        s.get_by_role("button", name="Bakım geçmişi", exact=True).click()
        p = pencere(s, "Bakım geçmişi")
        expect(p.locator("tbody tr").first).to_contain_text("yonetici")
        expect(p.locator("tbody tr").first).to_contain_text("Başarılı" if basarili else "Adım geri alındı")
        p.get_by_role("button", name="Kapat", exact=True).click()
    assert not s.hatalar, s.hatalar
    return o


def test_onyuz_bakim_sonucu_bildirilir(sistem, tarayici, liste):
    """Kullanıcı isteği 2026-09-30: 'bakım başlatıldı' yetmez; bitince sonuç (başarılı, süre, budanan, boyut) bildirilir,
    kart güncellenir, bakım geçmişi görülür."""
    _bakim_akisi(sistem, tarayici, True, liste)


@pytest.fixture
def bakim_hatasi(monkeypatch):
    monkeypatch.setenv("FWP_TEST_BAKIM_HATA", "reindex_canli")       # çekirdek süreci bu ortamı devralır


def test_onyuz_bakim_hatasi_geri_alinir_ve_bildirilir(bakim_hatasi, sistem, tarayici, liste):
    """Kullanıcı isteği 2026-09-30: bakım bir adımda hata verirse o adım geri alınır, sistem sekteye uğramaz; önyüz bunu
    açıkça söyler. İzleme sürer: bakım sonrası gelen dosya da Control-M'e gider."""
    o = _bakim_akisi(sistem, tarayici, False, liste)
    assert o.proc.poll() is None and all(o.eklenti(a)["durum"] == "CALISIYOR"
                                         for a in ("tarama", "teslim", "kontrol", "izleme", "bildirim"))


# ================================================================ kural penceresi: regex canlı deneme + API isteği
def test_onyuz_kural_penceresi(sistem, tarayici, tmp_path, liste):
    """Kullanıcı isteği 2026-09-30: kuralda Control-M klasör / iş adı alanları yok; kural kendi API isteğini (yöntem, yol,
    gövde şablonu) taşır ve penceresinden denenir. Regex, dizindeki gerçek adlar ve örnek adlar üzerinde canlı denenir;
    regex'in ne olduğu, evrensel olup olmadığı ve nasıl yazılacağı pencerede anlatılır."""
    o, sahte, url = sistem
    L = liste
    d = tmp_path / "sevk"
    d.mkdir()
    for a in ("FATURA_20260929.csv", "SEVK_IST_20260929.csv", "notlar.csv"):
        yaz(d, a)
    eski_yap(d)
    y = api(url)
    kod, r = y.post("/api/hedefler", {"ad": "controlm", "adres": sahte.adres, "tur": "CONTROLM",
                                      "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})
    assert kod == 200, r
    kod, r = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TEMEL_AL", "uzantilar": ".csv"})
    assert kod == 200, r
    dizin_id = r["id"]
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM dosya WHERE dizin_id=?", (dizin_id,))[0] == 3)
    s = oturum(tarayici, url)
    regex = s.locator("#kural_regex")
    yol = s.get_by_placeholder("/run/event/{ctm}/OLAY_ADI/ODAT")
    govde = s.get_by_placeholder("Boş bırakılabilir (gövdesiz istek)")
    sonuc = s.locator(".deneme-sonuc")
    satir = lambda ad: s.locator("table.eslesme tr", has_text=ad)                           # noqa: E731

    with L("Kural penceresi", "Dizindeki gerçek adlar sekmesi", "dizinde görülen adlar canlı denemeye gelir (seçili sekme)"):
        git(s, "Dizinler ve kurallar")
        s.locator(".kart", has_text=str(d)).get_by_role("button", name="Kural ekle", exact=True).click()
        p = pencere(s, f"Kural ekle · {d}")
        expect(p.get_by_role("tab", name="Dizindeki gerçek adlar (3)")).to_have_class(re.compile("secili"))
        expect(p.locator(".canli-sonuc")).to_contain_text("Regex yazın")
        regex.fill(r".*\.csv")
        for a in ("FATURA_20260929.csv", "SEVK_IST_20260929.csv", "notlar.csv"):
            expect(satir(a)).to_contain_text("✓ eşleşiyor")
        expect(p).to_contain_text("3 addan 3 tanesi eşleşiyor.")
    with L("Kural penceresi", "Örnekten öner", "seçilen addan kalıp çıkarılır; tarih isimli grup olur"):
        satir("SEVK_IST_20260929.csv").click()
        expect(satir("SEVK_IST_20260929.csv")).to_have_class(re.compile("secili-satir"))
        p.get_by_role("button", name="Örnekten öner", exact=True).click()
        expect(regex).to_have_value(r"SEVK_IST_(?P<tarih>\d{8})\.csv")
        expect(satir("SEVK_IST_20260929.csv")).to_contain_text("tarih=20260929")
        expect(satir("FATURA_20260929.csv")).to_contain_text("eşleşmiyor")
        expect(p).to_contain_text("3 addan 1 tanesi eşleşiyor.")
    with L("Kural penceresi", "Regex açıklaması", "ne yazılır, evrensel mi, nereden yazdırılır açılır"):
        p.get_by_text("Regex nasıl yazılır? Hangi kurallar geçerli?").click()
        yardim = p.locator("details.yardim")
        expect(yardim).to_have_attribute("open", "")
        for metin in ("Ne yazılır?", "Evrensel mi?", "Nereden yazdırırım?", "SEVK_IST_20260929.csv"):
            expect(yardim).to_contain_text(metin)
        p.get_by_text("Regex nasıl yazılır? Hangi kurallar geçerli?").click()
    with L("Kural penceresi", "(?<ad>…) yazımı + regex grupları", "diğer dillerdeki yazım çevrilir; gruplar değişken düğmesi olur"):
        regex.fill(r"SEVK_(?<depo>[A-Z]{3})_(?<tarih>\d{8})\.csv")
        expect(satir("SEVK_IST_20260929.csv")).to_contain_text("depo=IST")
        expect(satir("SEVK_IST_20260929.csv")).to_contain_text("tarih=20260929")
        expect(p.locator("button.degisken.grup")).to_have_count(2)
    with L("Kural penceresi", "Yalnız eşleşenler", "eşleşmeyen adlar gizlenir"):
        p.get_by_text("Yalnız eşleşenler", exact=True).click()
        expect(p.locator("table.eslesme tr")).to_have_count(1)
        p.get_by_text("Yalnız eşleşenler", exact=True).click()
        expect(p.locator("table.eslesme tr")).to_have_count(3)
    with L("Kural penceresi", "Örnek adlarım sekmesi", "kendi yazdığınız adlarda canlı sonuç"):
        p.get_by_role("tab", name="Örnek adlarım").click()
        ornek = p.get_by_placeholder("Kendi örnek adlarınız (her satıra bir tane)")
        expect(ornek).to_be_visible()
        ornek.fill("SEVK_ANK_20261001.csv\nSEVK_IZMIR_20261001.csv")
        expect(satir("SEVK_ANK_20261001.csv")).to_contain_text("depo=ANK")
        expect(satir("SEVK_IZMIR_20261001.csv")).to_contain_text("eşleşmiyor")
        p.get_by_role("tab", name="Dizindeki gerçek adlar (3)").click()
        expect(ornek).to_be_hidden()
        expect(p.locator(".ipucu", has_text="Deneme dosyası")).to_contain_text("SEVK_IST_20260929.csv")
    with L("Kural penceresi", "İstek: değişken düğmesi", "tıklanan {değişken} imlecin olduğu yere eklenir"):
        expect(yol).to_have_value("/run/event/{ctm}/FATURA_GELDI/ODAT")
        yol.fill("/run/event/{ctm}/SEVK_")
        p.get_by_role("button", name="{depo}", exact=True).click()
        expect(yol).to_have_value("/run/event/{ctm}/SEVK_{depo}")
        yol.press("End")
        yol.press_sequentially("/ODAT")
        expect(yol).to_have_value("/run/event/{ctm}/SEVK_{depo}/ODAT")
    with L("Kural penceresi", "Kuru deneme", "gönderilecek istek (adres, başlık, gövde) gösterilir; gönderilmez"):
        p.get_by_role("button", name="Kuru deneme", exact=True).click()
        expect(sonuc).to_contain_text("Kuru deneme (gönderilmedi)")
        expect(sonuc).to_contain_text(f"POST {sahte.adres}/run/event/ctmsunucu/SEVK_IST/ODAT")
        assert not sahte.istekler
    with L("Kural penceresi", "Kuru deneme (bilinmeyen değişken)", "hata açıkça söylenir"):
        govde.fill('{"x": "{yok_boyle}"}')
        p.get_by_role("button", name="Kuru deneme", exact=True).click()
        expect(sonuc.locator(".alan.hata")).to_contain_text("bilinmeyen değişken {yok_boyle}")
        govde.fill("")
    with L("Kural penceresi", "Bağlantıyı dene", "yalnızca erişim/kimlik denenir; iş tetiklenmez"):
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(sonuc.locator(".yanit.ok")).to_contain_text("iş tetiklenmedi")
        assert not sahte.istekler
    with L("Kural penceresi", "Gerçekten gönder…", "onay kutusu işaretlenmeden gönderilmez; gönderince Control-M yanıtı, "
                                                     "denetim kaydı; tetik tablosuna girmez"):
        p.get_by_role("button", name="Gerçekten gönder…", exact=True).click()
        g = pencere(s, "İsteği gerçekten gönder")
        expect(g).to_contain_text("SEVK_IST_20260929.csv")
        expect(g.get_by_role("button", name="Gönder", exact=True)).to_be_disabled()
        g.get_by_role("checkbox").check()
        g.get_by_role("button", name="Gönder", exact=True).click()
        expect(g).to_be_hidden()
        expect(sonuc).to_contain_text("GÖNDERİLDİ")
        expect(sonuc).to_contain_text("hedef kabul etti")
        assert [x["olay"] for x in sahte.olaylar] == ["SEVK_IST"]
        assert o.db.tek("SELECT COUNT(*) FROM tetik")[0] == 0
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='KURAL_ISTEK_GONDER'")[0] == 1
    with L("Kural penceresi", "Kuralı ekle", "kural isteğiyle kaydedilir; gelen dosya bu isteği tetikler"):
        p.get_by_placeholder("örn. fatura").fill("sevk")
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        bildirim(s, "Kural eklendi")
        expect(s.locator("tr", has_text="sevk")).to_contain_text("POST /run/event/{ctm}/SEVK_{depo}/ODAT")
        yaz(d, "SEVK_ANK_20261002.csv")
        o.bekle(lambda: (t := tetik(o, "SEVK_ANK_20261002.csv")) and t["durum"] == "ILETILDI")
        assert sahte.olaylar[-1]["olay"] == "SEVK_ANK"
        assert sahte.olaylar[-1]["idempotency"] == tetik(o, "SEVK_ANK_20261002.csv")["idempotency"]
    with L("Kural penceresi", "Kuralı düzenle", "kayıtlı regex ve istek gelir; değişiklik sonraki dosyaya uygulanır"):
        s.locator("tr", has_text="sevk").get_by_role("button", name="Kuralı düzenle", exact=True).click()
        p = pencere(s, f"Kuralı düzenle · {d}")
        expect(regex).to_have_value(r"SEVK_(?P<depo>[A-Z]{3})_(?P<tarih>\d{8})\.csv")
        expect(yol).to_have_value("/run/event/{ctm}/SEVK_{depo}/ODAT")
        yol.fill("/run/event/{ctm}/SEVK_{depo}_{tarih}/ODAT")
        p.get_by_role("button", name="Değişiklikleri kaydet", exact=True).click()
        bildirim(s, "Kural güncellendi")
        expect(s.locator("tr", has_text="sevk")).to_contain_text("SEVK_{depo}_{tarih}")
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='KURAL_GUNCELLE'")[0] == 1
        yaz(d, "SEVK_IZM_20261003.csv")
        o.bekle(lambda: (t := tetik(o, "SEVK_IZM_20261003.csv")) and t["durum"] == "ILETILDI")
        assert sahte.olaylar[-1]["olay"] == "SEVK_IZM_20261003"
    with L("Kural penceresi", "Hatalı istek / çakışan grup adı", "uyarı görünür; kural kaydedilmez"):
        s.locator(".kart", has_text=str(d)).get_by_role("button", name="Kural ekle", exact=True).click()
        p = pencere(s, f"Kural ekle · {d}")
        regex.fill(r"X_(?P<boyut>\d+)\.csv")
        expect(p.locator(".degiskenler")).to_contain_text("yerleşik bir değişkenle aynı adı")
        regex.fill(r"X_\d+\.csv")
        p.get_by_placeholder("örn. fatura").fill("x")
        yol.fill("run/order")
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        expect(p.get_by_role("alert")).to_contain_text("'/' ile başlamalı")
        p.get_by_role("button", name="Vazgeç", exact=True).click()
        assert o.db.tek("SELECT COUNT(*) FROM kural")[0] == 1
    assert not s.hatalar, s.hatalar


# ================================================================ sistem izleme
def test_onyuz_sistem_izleme(sistem, tarayici, liste):
    """Kullanıcı isteği 2026-09-30: sunucunun ve uygulamanın CPU/RAM kullanımı ayrı sekmede; kendi CPU/RAM'i için özenli
    alarmlar (eşik + süre, dalgalanmada aç-kapa yok). Eşik aşılınca alarm açılır, düzelince kapanır."""
    o, sahte, url = sistem
    L = liste
    s = oturum(tarayici, url)
    with L("Sistem izleme", "Göstergeler (KPI)", "sunucu ve FileWatcherPro CPU/bellek, disk, çalışma süresi ölçümden gelir"):
        expect(s.locator("#yan a", has_text="Yapay zekâ asistanı")).to_have_count(0)      # asistan eklentisi kurulu değil
        git(s, "Sistem izleme")
        expect(kpi(s, "Sunucu CPU")).to_have_text(re.compile(r"^%\d"))
        expect(kpi(s, "Sunucu bellek")).to_have_text(re.compile(r"^%\d"))
        expect(kpi(s, "FileWatcherPro CPU")).to_have_text(re.compile(r"^%\d"))
        expect(kpi(s, "FileWatcherPro bellek")).to_have_text(re.compile(r"\d+(,\d)? (MB|GB)$"))
        expect(kpi(s, "Disk (veri)")).to_have_text(re.compile(r"\d+(,\d)? (MB|GB)$"))
        expect(kpi(s, "Çalışma süresi")).to_have_text(re.compile(r"\d+ (dk|sa|gün)"))
    with L("Sistem izleme", "Bileşenler tablosu", "her süreç PID, CPU, bellek ile; toplam satırı"):
        tablo = s.locator(".kart").filter(has=s.locator("th", has_text="Tepe CPU"))
        surec = lambda ad: tablo.locator("tbody tr").filter(has=s.locator("td:first-child", has_text=re.compile(f"^{re.escape(ad)}$")))  # noqa: E731
        for ad in ("Çekirdek", "Tarama", "Teslim", "Kontrol arayüzü", "Sistem izleme", "Bildirim (mail)"):
            expect(surec(ad)).to_contain_text("MB")
        expect(surec("Tarama")).to_contain_text(str(o.eklenti("tarama")["pid"]))
        expect(tablo.locator("tfoot")).to_contain_text("Toplam")
    with L("Sistem izleme", "Grafikler (son 1 saat)", "işlemci, sunucu belleği, uygulama belleği çizgileri ölçümlerle dolar"):
        expect(s.locator("svg.grafik")).to_have_count(3)
        expect(s.locator("svg.grafik polyline.seri")).to_have_count(4, timeout=30_000)
    with L("Sistem izleme", "Son 24 saat sekmesi", "sunucudan 24 saatlik (4 dk ortalama) seri istenir"):
        with s.expect_response(lambda r: "/api/izleme?aralik=24s" in r.url) as yanit:
            s.get_by_role("tab", name="Son 24 saat").click()
        assert yanit.value.ok
        expect(s.get_by_role("tab", name="Son 24 saat")).to_have_class(re.compile("secili"))
        s.get_by_role("tab", name="Son 1 saat").click()
        expect(s.get_by_role("tab", name="Son 1 saat")).to_have_class(re.compile("secili"))
    with L("Sistem izleme", "Eşikleri düzenle → kendi belleği", "eşik düşürülünce 'Alarm' açılır; genel durum değişir"):
        s.get_by_role("button", name="Eşikleri düzenle", exact=True).click()
        p = pencere(s, "Kaynak eşiklerini düzenle")
        r_ = p.locator("tbody tr", has_text="FileWatcherPro bellek")
        r_.locator("input[type=number]").nth(0).fill("50")
        r_.locator("input[type=number]").nth(1).fill("0")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "Eşikler kaydedildi")
        assert json.loads(o.db.tek("SELECT deger FROM ayar WHERE anahtar='izleme_fwp_ram_mb'")[0]) == 50
        o.bekle(lambda: o.db.tek("SELECT aktif FROM alarm WHERE anahtar='kaynak:fwp_ram'") is not None
                and o.db.tek("SELECT aktif FROM alarm WHERE anahtar='kaynak:fwp_ram'")[0] == 1)
        esik = s.locator(".kart", has_text="Eşikler ve alarmlar").locator("tr", has_text="FileWatcherPro bellek")
        expect(esik).to_contain_text("Alarm · Uyarı")
        expect(s.locator(".kpi", has_text="FileWatcherPro bellek")).to_have_class(re.compile("warn|bad"))
        expect(s.locator("#genel_durum")).to_contain_text("Dikkat")
    with L("Alarmlar", "Tür, nesne ve 'Ne yapmalı'", "alarm kataloğundan tür adı ve öneri gösterilir"):
        git(s, "Alarmlar")
        a = s.locator(".alarm", has_text="FileWatcherPro bellek eşiği aşıldı")
        expect(a).to_contain_text("Ne yapmalı:")
        expect(a).to_contain_text("Bileşeni yeniden başlatmak")
    with L("Alarmlar", "Seviye / tür süzgeci ve arama", "kritikler üstte; süzgeçler ve arama listeyi daraltır"):
        o.db.alarm_ac("dizin:999:erisilemez", "Deneme dizini erişilemiyor", "KRITIK", "tarama")
        expect(s.locator(".alarm").first).to_contain_text("Deneme dizini erişilemiyor")
        expect(s.locator(".alarm").first).to_contain_text("Dizine erişilemiyor")
        s.get_by_label("Seviye").select_option("UYARI")
        expect(s.locator(".alarm", has_text="Deneme dizini")).to_have_count(0)
        expect(s.locator(".alarm", has_text="FileWatcherPro bellek")).to_have_count(1)
        s.get_by_label("Seviye").select_option("")
        s.get_by_label("Tür").select_option("Dizin / dosya")
        expect(s.locator(".alarm", has_text="FileWatcherPro bellek")).to_have_count(0)
        expect(s.locator(".alarm", has_text="Deneme dizini")).to_have_count(1)
        s.get_by_label("Tür").select_option("")
        s.locator("#ara_alarm").fill("bellek")
        expect(s.locator(".alarm")).to_have_count(1)
        s.locator("#ara_alarm").fill("")
        expect(s.locator(".alarm")).to_have_count(2)
        s.locator(".alarm", has_text="Deneme dizini").get_by_role("button", name="Onayla", exact=True).click()
        bildirim(s, "Alarm onaylandı")
    with L("Sistem izleme", "Eşik geri alınınca", "değer eşiğin altında kalınca alarm kendiliğinden kapanır ('Normal')"):
        git(s, "Sistem izleme")
        s.get_by_role("button", name="Eşikleri düzenle", exact=True).click()
        p = pencere(s, "Kaynak eşiklerini düzenle")
        p.locator("tbody tr", has_text="FileWatcherPro bellek").locator("input[type=number]").nth(0).fill("100000")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "Eşikler kaydedildi")
        o.bekle(lambda: o.db.tek("SELECT aktif FROM alarm WHERE anahtar='kaynak:fwp_ram'")[0] == 0)
        expect(s.locator(".kart", has_text="Eşikler ve alarmlar").locator("tr", has_text="FileWatcherPro bellek")).to_contain_text("Normal")
        expect(s.locator("#genel_durum")).to_contain_text("Her şey yolunda")
    with L("Sistem izleme", "Ölçüm eskiyince uyarı", "izleme durursa 'Ölçümler güncel değil' şeridi; başlayınca kalkar"):
        git(s, "Eklentiler")
        k = s.locator(".kart", has_text="Sistem izleme")
        k.get_by_role("button", name="Durdur", exact=True).click()
        pencere(s, "Eklentiyi durdur").get_by_role("button", name="Eklentiyi durdur", exact=True).click()
        expect(k).to_contain_text("Durduruldu")
        anlik = json.loads(o.db.meta_al("izleme_anlik"))
        anlik["zaman"] = time.time() - 600
        o.db.meta_yaz("izleme_anlik", json.dumps(anlik))
        git(s, "Sistem izleme")
        expect(s.locator(".serit.uyari", has_text="Ölçümler güncel değil")).to_be_visible()
        git(s, "Eklentiler")
        k.get_by_role("button", name="Başlat", exact=True).click()
        pencere(s, "Eklentiyi başlat").get_by_role("button", name="Eklentiyi başlat", exact=True).click()
        expect(k).to_contain_text("Çalışıyor")
        o.bekle(lambda: json.loads(o.db.meta_al("izleme_anlik"))["zaman"] > time.time() - 30)
        git(s, "Sistem izleme")
        expect(s.locator(".serit.uyari", has_text="Ölçümler güncel değil")).to_have_count(0)
    assert not s.hatalar, s.hatalar


# ================================================================ bildirimler (mail) ve alarm → mail
def test_onyuz_bildirimler(sistem, tarayici, tmp_path, smtp, liste):
    """Kullanıcı isteği 2026-09-30: mail arayüzü; hangi olayların maile gideceği ayrıntılı seçilir, her dizin için
    seçilebilir. SMTP + kullanıcı/şifre (şifre yalnızca wincred:/env: referansı)."""
    o, sahte, url = sistem
    L = liste
    d1, d2 = tmp_path / "muhasebe", tmp_path / "lojistik"
    y = api(url)
    ids = {}
    for d in (d1, d2):
        d.mkdir()
        kod, r = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
        assert kod == 200, r
        ids[d] = r["id"]
    o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM dizin WHERE erisim_durumu='ERISILEBILIR'")[0] == 2)
    s = oturum(tarayici, url)
    ekle = s.get_by_role("button", name="Bildirim kuralı ekle", exact=True)
    ksatir = s.locator(".kart").filter(has=s.locator("th", has_text="Kapsam")).locator("tbody tr", has_text="Muhasebe ekibi")
    with L("Bildirimler", "SMTP tanımsızken", "bilgi kutusu; 'Bildirim kuralı ekle' ve 'Test maili' pasif, ipuçlu"):
        git(s, "Bildirimler (mail)")
        expect(s.locator("#icerik")).to_contain_text("Mail sunucusu tanımlı değil")
        expect(ekle).to_be_disabled()
        expect(ekle).to_have_attribute("title", "Önce SMTP ayarlayın")
        expect(s.get_by_role("button", name="Test maili gönder", exact=True)).to_be_disabled()
    with L("Bildirimler", "SMTP ayarla → şifre alanı + Bağlantıyı dene", "yazılan şifreyle kaydetmeden denenir: yanlışta ✗, doğruda ✓; mail gitmez"):
        s.get_by_role("button", name="SMTP ayarla", exact=True).click()
        p = pencere(s, "Mail sunucusu (SMTP)")
        p.get_by_placeholder("mail.sirket.local").fill("127.0.0.1")
        p.get_by_placeholder("587").fill(str(smtp.port))
        p.locator("select").select_option("YOK")
        p.get_by_placeholder("fwp@sirket.local").nth(0).fill("fwp")
        p.get_by_placeholder("fwp@sirket.local").nth(1).fill("fwp@test.local")
        sifre = p.locator("#smtp_sifre")
        expect(sifre).to_have_attribute("type", "password")
        sifre.fill("yanlis-sifre")
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.bad")).to_contain_text("kimlik doğrulama başarısız")
        sifre.fill(SMTP_SIFRE)
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.ok")).to_contain_text("✓")
        assert not smtp.mailler and o.db.meta_al("smtp") is None
    with L("Bildirimler", "SMTP → Gelişmiş referans alanı", "düz şifre yazılırsa kaydedilmez, 'Şifre alanına yazın' der"):
        sifre.fill("")
        p.get_by_text("Gelişmiş: şifreyi dışarıdan oku").click()
        ref = p.get_by_placeholder("wincred:FileWatcherPro/smtp  ya da  env:FWP_SMTP_SIFRE")
        ref.fill("duz-yazilmis-sifre")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        expect(p.get_by_role("alert")).to_contain_text("'Şifre' alanına yazın")
        assert o.db.meta_al("smtp") is None
        ref.fill("")
    with L("Bildirimler", "SMTP Kaydet", "uygulama şifreyi kendisi saklar (bu sunucuda şifreli); kartta kaynağı, hiçbir dosyada düz hâli yok"):
        sifre.fill(SMTP_SIFRE)
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "SMTP ayarları kaydedildi")
        kart_ = s.locator(".kart", has_text="Mail sunucusu (SMTP)")
        expect(kart_).to_contain_text(f"127.0.0.1:{smtp.port} · YOK")
        expect(kart_).to_contain_text("fwp · şifre: uygulamada şifreli (bu sunucu)")
        expect(kart_).to_contain_text("Henüz gönderim yok")
        assert json.loads(o.db.meta_al("smtp"))["sifre_ref"].startswith("dpapi:")
        duz_sir_yok(o, SMTP_SIFRE)
        expect(ekle).to_be_enabled()
    with L("Bildirimler", "SMTP Düzenle (şifre boş)", "'kayıtlı' ipucu; boş bırakılınca kayıtlı şifre korunur ve denemede kullanılır"):
        ref_once = json.loads(o.db.meta_al("smtp"))["sifre_ref"]
        kart_.get_by_role("button", name="Düzenle", exact=True).click()
        p = pencere(s, "Mail sunucusu (SMTP)")
        expect(p.locator("#smtp_sifre")).to_have_value("")
        expect(p.locator("#smtp_sifre")).to_have_attribute("placeholder", re.compile("kayıtlı"))
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.ok")).to_contain_text("✓")
        p.get_by_placeholder("FileWatcherPro", exact=True).fill("FWP Deneme")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "SMTP ayarları kaydedildi")
        assert json.loads(o.db.meta_al("smtp"))["sifre_ref"] == ref_once
    with L("Bildirimler", "Test maili gönder", "mail sahte SMTP'ye ulaşır; kartta 'Son gönderim başarılı', geçmişte satır"):
        s.get_by_role("button", name="Test maili gönder", exact=True).click()
        p = pencere(s, "Test maili gönder")
        p.get_by_placeholder("ad.soyad@sirket.local").fill("ops@test.local")
        p.get_by_role("button", name="Gönder", exact=True).click()
        bildirim(s, "Test maili gönderildi")
        assert [m["to"] for m in smtp.mailler] == [["ops@test.local"]] and "Test maili" in smtp.mailler[0]["konu"]
        expect(kart_).to_contain_text("Son gönderim başarılı")
        expect(s.locator(".kart", has_text="Gönderim geçmişi").locator("tbody tr").first).to_contain_text("Gönderildi")
    with L("Bildirimler", "Test maili (SMTP geçici hata)", "hata pencerede söylenir; geçmişte 'Hata', kartta 'Son hata'"):
        smtp.mod_ayarla("gecici")
        s.get_by_role("button", name="Test maili gönder", exact=True).click()
        p = pencere(s, "Test maili gönder")
        p.get_by_placeholder("ad.soyad@sirket.local").fill("ops@test.local")
        p.get_by_role("button", name="Gönder", exact=True).click()
        expect(p.get_by_role("alert")).to_contain_text("gönderilemedi")
        p.get_by_role("button", name="Vazgeç", exact=True).click()
        smtp.mod_ayarla("normal")
        git(s, "Genel bakış")
        git(s, "Bildirimler (mail)")
        expect(kart_).to_contain_text("Son hata")
        expect(s.locator(".kart", has_text="Gönderim geçmişi").locator("tbody tr").first).to_contain_text("Hata")
    with L("Bildirimler", "Bildirim kuralı ekle → hazır seçimler", "'Yalnız kritikler' / 'Hiçbiri' olay kutularını topluca seçer"):
        ekle.click()
        p = pencere(s, "Bildirim kuralı ekle")
        kutular = p.locator(".katalog input[type=checkbox]")
        expect(kutular).to_have_count(len(KATALOG))
        onerilen = sum(1 for x in KATALOG if x["onerilen"])
        expect(p.locator(".katalog input[type=checkbox]:checked")).to_have_count(onerilen)
        p.get_by_role("button", name="Yalnız kritikler", exact=True).click()
        expect(p.locator(".katalog input[type=checkbox]:checked")).to_have_count(sum(1 for x in KATALOG if x["seviye"] == "KRITIK"))
        p.get_by_role("button", name="Hiçbiri", exact=True).click()
        expect(p.locator(".katalog input[type=checkbox]:checked")).to_have_count(0)
        expect(p.locator(".onizleme")).to_contain_text("Olay seçin")
    with L("Bildirimler", "Bildirim kuralı ekle (olay + dizin seçimi)", "seçilen olay ve dizinle kaydedilir; örnek mail önizlenir"):
        p.get_by_placeholder("örn. Operasyon ekibi · kritikler").fill("Muhasebe ekibi")
        p.get_by_placeholder("Her satıra bir adres (ya da ; ile ayırın)").fill("ops@test.local\nsef@test.local")
        p.locator("label.katalog-oge", has_text="Dizine erişilemiyor").locator("input").check()
        expect(p.locator(".onizleme")).to_contain_text("Dizine erişilemiyor")
        expect(p.locator(".onizleme")).to_contain_text("Ne yapmalı")
        p.locator("input[name=kapsam]").nth(1).check()
        p.locator(".secim-liste label", has_text=str(d1)).locator("input").check()
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "Bildirim kuralı kaydedildi")
        r_ = ksatir
        for metin in ("ops@test.local, sef@test.local", "Dizine erişilemiyor", "1 dizin", "Anında", "+ düzelince", "Açık"):
            expect(r_).to_contain_text(metin)
        k = o.db.tek("SELECT * FROM bildirim_kural")
        assert json.loads(k["olaylar"]) == ["DIZIN_ERISILEMEZ"] and json.loads(k["dizinler"]) == [ids[d1]]
    n0 = len(smtp.mailler)
    with L("Bildirimler", "Alarm → mail (yalnız seçili dizin)", "seçili dizine erişilemeyince iki alıcıya mail; seçilmeyen dizin için mail yok"):
        yedekler = []
        for d in (d1, d2):
            y_ = d.with_name(d.name + "_yedek")
            for _ in range(50):
                try:
                    d.rename(y_)
                    break
                except PermissionError:
                    time.sleep(0.1)
            yedekler.append(y_)
        o.bekle(lambda: all(o.db.tek("SELECT aktif FROM alarm WHERE anahtar=?", (f"dizin:{ids[d]}:erisilemez",)) is not None
                            for d in (d1, d2)), zaman_asimi=45)
        o.bekle(lambda: len(smtp.mailler) >= n0 + 1, zaman_asimi=30)         # tek mail, iki alıcı
        time.sleep(2)
        yeni = smtp.mailler[n0:]
        assert sorted(a for m in yeni for a in m["to"]) == ["ops@test.local", "sef@test.local"], yeni
        assert all("Dizine erişilemiyor" in m["konu"] and str(d1) in m["konu"] + m["govde"] for m in yeni)
        assert not any(str(d2) in m["konu"] + m["govde"] for m in yeni)
    with L("Alarmlar", "'mail gitti' göstergesi", "maili giden alarmda görünür; mail gitmeyende görünmez"):
        git(s, "Alarmlar")
        expect(s.locator(".alarm", has_text=str(d1))).to_contain_text("mail gitti")
        expect(s.locator(".alarm", has_text=str(d2))).to_be_visible()
        expect(s.locator(".alarm", has_text=str(d2))).not_to_contain_text("mail gitti")
    with L("Bildirimler", "Düzelince bildir", "dizin geri gelince 'DÜZELDİ' maili gider"):
        for d, y_ in zip((d1, d2), yedekler):
            y_.rename(d)
        o.bekle(lambda: any("DÜZELDİ" in m["konu"] for m in smtp.mailler[n0:]), zaman_asimi=45)
        assert all(str(d2) not in m["konu"] + m["govde"] for m in smtp.mailler[n0:])
        git(s, "Bildirimler (mail)")
        expect(s.locator(".kart", has_text="Gönderim geçmişi").locator("tbody tr", has_text="DÜZELDİ")).to_contain_text("Muhasebe ekibi")
    with L("Bildirimler", "Kuralı düzenle (özet)", "özet seçilince 'Özet · N dk' kaydedilir"):
        ksatir.get_by_role("button", name="Düzenle", exact=True).click()
        p = pencere(s, "Bildirim kuralını düzenle")
        expect(p.get_by_placeholder("örn. Operasyon ekibi · kritikler")).to_have_value("Muhasebe ekibi")
        p.locator("input[name=gonderim]").nth(1).check()
        p.locator("input[type=number]").nth(0).fill("30")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "Bildirim kuralı kaydedildi")
        expect(ksatir).to_contain_text("Özet · 30 dk")
        assert o.db.tek("SELECT ozet_dk FROM bildirim_kural")[0] == 30
    with L("Bildirimler", "Kuralı sil", "onaydan sonra silinir; denetim kaydına yazılır"):
        ksatir.get_by_role("button", name="Sil", exact=True).click()
        pencere(s, "Bildirim kuralını sil").get_by_role("button", name="Bildirim kuralını sil", exact=True).click()
        expect(s.locator("#icerik")).to_contain_text("Henüz bildirim kuralı yok.")
        assert o.db.tek("SELECT COUNT(*) FROM bildirim_kural")[0] == 0
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='BILDIRIM_KURAL_SIL'")[0] == 1
    with L("Roller", "Operatör (Bildirimler)", "test maili gönderebilir; SMTP ve kural düzenleyemez"):
        s2 = oturum(tarayici, url, "operator")
        git(s2, "Bildirimler (mail)")
        expect(s2.get_by_role("button", name="Test maili gönder", exact=True)).to_be_enabled()
        expect(s2.get_by_role("button", name="Düzenle", exact=True)).to_be_disabled()
        expect(s2.get_by_role("button", name="Bildirim kuralı ekle", exact=True)).to_be_disabled()
        assert not s2.hatalar, s2.hatalar
    assert not s.hatalar, s.hatalar


# ================================================================ hedef şifresi: ekrandan girilir, uygulama saklar
def test_onyuz_hedef_sifresi(sistem, tarayici, tmp_path, liste):
    """Kullanıcı isteği 2026-09-30: 'şifreyi o ekrandan deneyebilmeli, kaydedebilmeliyim; env vs. gerek yok, uygulama
    kendisi kaydetsin'. Kimlik isteyen sahte Control-M ile: yanlış / doğru şifre denemesi, kayıt, kartta şifrenin
    kaynağı, gelen dosyanın bu şifreyle açılan oturumla iletilmesi; düz şifre hiçbir dosyada yok."""
    o, _, url = sistem
    L = liste
    sir = "ornek-ctm-sifresi-B"
    ctm = SahteControlM(kullanici="fwpk", sifre=sir).baslat()
    try:
        s = oturum(tarayici, url)
        with L("Hedefler", "Hedef ekle → şifre alanı + Bağlantıyı dene", "yazılan şifreyle kaydetmeden denenir: yanlışta ✗, doğruda ✓"):
            git(s, "Hedefler")
            p = hedef_turu_sec(s, "Control-M")
            p.get_by_placeholder("örn. Control-M Prod").fill("ctm-kimlikli")
            p.get_by_placeholder("https://ctm-sunucu:8443/automation-api").fill(ctm.adres)
            p.get_by_placeholder("ctmprod (şablonlarda {ctm})").fill("ctmsunucu")
            p.get_by_placeholder("API kullanıcısı").fill("fwpk")
            sifre = p.locator("#hedef_sifre")
            expect(sifre).to_have_attribute("type", "password")
            sifre.fill("yanlis-sifre")
            p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
            expect(p.locator(".yanit.bad")).to_contain_text("✗")
            sifre.fill(sir)
            p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
            expect(p.locator(".yanit.ok")).to_contain_text("✓")
            assert o.db.tek("SELECT COUNT(*) FROM hedef")[0] == 0
        with L("Hedefler", "Kimlik türü → API anahtarı", "kullanıcı alanı gizlenir, şifre alanının adı 'API anahtarı' olur"):
            p.locator("select").select_option("apikey")
            expect(p.get_by_placeholder("API kullanıcısı")).to_be_hidden()
            expect(p.locator("label[for=hedef_sifre]")).to_have_text("API anahtarı")
            p.locator("select").select_option("token")
            expect(p.get_by_placeholder("API kullanıcısı")).to_be_visible()
            expect(p.locator("label[for=hedef_sifre]")).to_have_text("Şifre")
        with L("Hedefler", "Hedefi ekle (şifreli)", "uygulama şifreyi kendisi saklar; kartta 'fwpk · şifre: uygulamada şifreli'"):
            p.get_by_role("button", name="Hedefi ekle", exact=True).click()
            bildirim(s, "Hedef eklendi")
            expect(s.locator(".kart", has_text="ctm-kimlikli")).to_contain_text("fwpk · şifre: uygulamada şifreli (bu sunucu)")
            ham = json.loads(o.db.tek("SELECT ayrintilar FROM hedef WHERE ad='ctm-kimlikli'")[0])
            assert ham["sifre_ref"].startswith("dpapi:") and "sifre" not in ham
        with L("Hedefler", "Kayıtlı şifreyle teslim", "gelen dosya, teslim sürecinin çözdüğü şifreyle açılan oturumla Control-M'e gider"):
            y = api(url)
            d = tmp_path / "sifreli"
            d.mkdir()
            kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
            assert kod == 200, dz
            hid = o.db.tek("SELECT id FROM hedef WHERE ad='ctm-kimlikli'")[0]
            kod, k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "f", "regex": r"F_\d+\.csv", "hedef_id": hid,
                                              "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/F_GELDI/ODAT", "govde": ""}})
            assert kod == 200, k
            yaz(d, "F_1.csv")
            o.bekle(lambda: (t := tetik(o, "F_1.csv")) and t["durum"] == "ILETILDI")
            assert ctm.girisler >= 1 and [x["olay"] for x in ctm.olaylar] == ["F_GELDI"]
            duz_sir_yok(o, sir)
        assert not s.hatalar, s.hatalar
    finally:
        ctm.durdur()


# ================================================================ yapay zekâ asistanı
def kpi_ad(sayfa, ad):
    return sayfa.locator(".kpi").filter(has=sayfa.locator(".ad", has_text=re.compile(f"^{ad}$"))).locator(".deger")


def test_onyuz_asistan(asistanli_sistem, tarayici, tmp_path, liste):
    """Kullanıcı onayı 2026-09-30: yerel yapay zekâ asistanı kendi penceresinde; çevrimiçi eğitim, loss eğrileri (öğreniyor
    mu / ezberliyor mu), güven, olaylar arası ilişki (self-attention), öneriler ve geri bildirim. Gerçek çekirdek + asistan."""
    o, sahte, url = asistanli_sistem
    L = liste
    y = api(url)
    s = oturum(tarayici, url)
    with L("Yapay zekâ", "Menü + boş durum", "eklenti kurulu olunca menüde görünür; 'Veri toplanıyor', ilerleme, 'Şimdi eğit' pasif"):
        expect(s.locator("#yan a", has_text="Yapay zekâ asistanı")).to_be_visible()
        git(s, "Yapay zekâ asistanı")
        expect(kpi_ad(s, "Model")).to_have_text("Veri toplanıyor")
        b = s.get_by_role("button", name="Şimdi eğit", exact=True)
        expect(b).to_be_disabled()
        expect(b).to_have_attribute("title", "Önce yeterli veri toplanmalı (Veri sekmesi)")
        expect(s.locator("section.kart", has_text="Veri toplanıyor")).to_contain_text("/ 2.000 olay")
        expect(s.locator(".serit.bilgi")).to_contain_text("Gölge modu")
    with L("Yapay zekâ", "Kendini sına", "yapay veriyle ayrı model eğitilir; 'Geçti', gömülü ilişki ve eğri pencerede; gerçek modele dokunulmaz"):
        s.get_by_role("button", name="Kendini sına", exact=True).first.click()
        p = pencere(s, "Kendini sına")
        p.get_by_role("button", name="Sınamayı başlat", exact=True).click()
        expect(p.locator(".karar")).to_contain_text("Geçti", timeout=240_000)
        expect(p.locator(".karar")).to_contain_text("Gömülen ilişki bulundu")
        expect(p.locator("svg.grafik")).to_be_visible()
        p.get_by_role("button", name="Kapat", exact=True).click()
        expect(s.locator("section.kart", has_text="Beklerken")).to_contain_text("geçti ✓")
        assert o.db.tek("SELECT COUNT(*) FROM komut WHERE alici='asistan' AND komut='KENDINI_SINA' AND durum='ISLENDI'")[0] == 1
        assert not (o.veri / "asistan" / "model_1.npz").exists()
    with L("Yapay zekâ", "Eğitim sekmesi (ilk eğitimden önce)", "sürekli öğrenme anahtarı ve gelişmiş ayarlar erişilebilir; kaydedilir, denetime yazılır"):
        assert y.put("/api/asistan/ayarlar", {"asgari_olay": 60, "asgari_gun": 0, "egitim_adimi": 60, "egitim_sure_sn": 40})[0] == 200
        s.get_by_role("tab", name="Eğitim", exact=True).click()
        s.get_by_text("Sürekli öğrenme (çevrimiçi)", exact=True).click()
        bildirim(s, "Sürekli öğrenme kapatıldı")
        s.get_by_text("Gelişmiş ayarlar (model yapısı ve eğitim)").click()
        s.locator("input[data-anahtar=baglam]").fill("16")
        s.get_by_role("button", name="Ayarları kaydet", exact=True).click()
        bildirim(s, "Asistan ayarları kaydedildi")
        a = y.get("/api/asistan")[1]["ayarlar"]
        assert a["surekli"] is False and a["baglam"] == 16
        assert o.hdb.tek("SELECT COUNT(*) FROM denetim WHERE islem='ASISTAN_AYAR'")[0] == 3
    with L("Yapay zekâ", "Şimdi eğit", "veri yeterli olunca 'Eğitime hazır'; eğitim turu sonrası eğri, karar, sürüm 1 'Kullanımda'"):
        kod, h_ = y.post("/api/hedefler", {"ad": "ctm", "adres": sahte.adres, "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})
        d = tmp_path / "asistan_gelen"
        d.mkdir()
        kod, dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})
        kod, k = y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "f", "regex": r"F_\d+\.csv", "hedef_id": h_["id"],
                                          "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/F_GELDI/ODAT", "govde": ""}})
        assert kod == 200, k
        for i in range(40):
            yaz(d, f"F_{i}.csv")
            time.sleep(0.05)
        o.bekle(lambda: y.get("/api/asistan")[1]["veri"]["olay_sayisi"] >= 70, zaman_asimi=60)
        expect(kpi_ad(s, "Model")).to_have_text("Eğitime hazır", timeout=30_000)
        s.get_by_role("button", name="Şimdi eğit", exact=True).click()
        bildirim(s, "Eğitim başladı")
        expect(kpi_ad(s, "Model")).not_to_have_text("Eğitime hazır", timeout=180_000)
        s.get_by_role("tab", name="Eğitim", exact=True).click()
        expect(s.locator("section.kart", has_text="Kayıp eğrisi (loss)").locator("svg.grafik")).to_be_visible()
        expect(s.locator(".karar").first).not_to_be_empty()
        expect(s.locator("section.kart", has_text="Sürümler").locator("tbody tr").first).to_contain_text("Kullanımda")
        assert (o.veri / "asistan" / "model_1.npz").exists()
    with L("Yapay zekâ", "Güven sekmesi", "güven karnesi (5 ölçüt), kalibrasyon diyagramı, görmeden tahmin başarısı"):
        s.get_by_role("tab", name="Güven", exact=True).click()
        karne = s.locator("section.kart", has_text="Güven karnesi")
        for olcut in ("Tabanı geçiyor", "Ezber yok", "Kalibrasyon", "Veri yeterliliği", "Geri bildirim isabeti"):
            expect(karne).to_contain_text(olcut)
        expect(s.locator("section.kart", has_text="Kalibrasyon: söylediği güven gerçek mi?").locator("svg.grafik")).to_be_visible()
        expect(s.locator("section.kart", has_text="Tahmin başarısı")).to_contain_text("Markov tabanı")
    with L("Yapay zekâ", "İlişkiler sekmesi", "dikkat haritası (oran) ya da ilişki yoksa açıklayıcı boş durum"):
        s.get_by_role("tab", name="İlişkiler", exact=True).click()
        expect(s.locator("#icerik")).to_contain_text(re.compile("Dikkat haritası|İlk eğitimden sonra"))
    with L("Yapay zekâ", "Veri sekmesi", "toplanan olay türleri ve sayıları; ne toplanır / toplanmaz"):
        s.get_by_role("tab", name="Veri", exact=True).click()
        expect(s.locator(".cubuk-liste")).to_contain_text("Dosya geldi")
        expect(s.locator("section.kart", has_text="Ne toplanır")).to_contain_text("dosya içerikleri hiçbir zaman okunmaz")
    with L("Yapay zekâ", "Anomaliler sekmesi", "kural başına boyut aralığı / teslim süresi / günlük adet; 'Normal'; anomali alarmı anahtarı kaydedilir"):
        s.get_by_role("tab", name=re.compile("^Anomaliler")).click()
        satir = s.locator("table.tablo tbody tr", has_text="f")
        expect(satir).to_contain_text("40 dosya", timeout=30_000)
        expect(satir).to_contain_text("Normal")
        s.screenshot(path=str(SONUC.parent / "onyuz_anomaliler.png"), full_page=True)
        expect(s.locator(".serit.bilgi", has_text="İstatistik, model değil")).to_contain_text("Dosya adı ve içerik toplanmaz")
        s.get_by_text("Anomaliyi alarm olarak da aç", exact=False).click()
        bildirim(s, "Anomali alarmı açıldı")
        assert y.get("/api/asistan")[1]["ayarlar"]["anomali_alarm"] is True
        expect(s.locator(".serit.bilgi").first).to_contain_text("Anomali alarmı açık")
        s.get_by_text("Anomaliyi alarm olarak da aç", exact=False).click()
        bildirim(s, "Anomali alarmı kapatıldı")
    with L("Yapay zekâ", "Öneri → Faydalı", "geri bildirim kaydedilir; öneri 'geri bildirim verilen' listesine geçer"):
        from eklentiler.asistan.depo import AsistanDB
        from eklentiler.asistan.oneriler import oneri_ekle
        oneri_ekle(AsistanDB(o.veri / "asistan.db"), anahtar="e2e", tur="ILISKI", baslik="Deneme ilişkisi", metin="açıklama",
                   kaynak="model", guven=0.7, kanit=["kanıt satırı"])
        git(s, "Genel bakış")
        git(s, "Yapay zekâ asistanı")
        s.get_by_role("tab", name=re.compile("^Öneriler")).click()
        kart_ = s.locator(".oneri-kart", has_text="Deneme ilişkisi")
        expect(kart_).to_contain_text("%70")
        expect(kart_).to_contain_text("kanıt satırı")
        kart_.get_by_role("button", name="Faydalı", exact=True).click()
        bildirim(s, "Kaydedildi: faydalı")
        expect(s.locator(".oneri-kart", has_text="Deneme ilişkisi")).to_have_count(0)
        s.get_by_role("tab", name="Geri bildirim verilen / kapanan").click()
        expect(s.locator(".oneri-kart", has_text="Deneme ilişkisi")).to_contain_text("✓ Faydalı · yonetici")
    with L("Roller", "İzleyici (asistan)", "sayfayı görür; eğit / sına düğmeleri pasif"):
        s3 = oturum(tarayici, url, "izleyici")
        git(s3, "Yapay zekâ asistanı")
        expect(s3.get_by_role("button", name="Şimdi eğit", exact=True)).to_be_disabled()
        expect(s3.get_by_role("button", name="Kendini sına", exact=True).first).to_be_disabled()
        assert not s3.hatalar, s3.hatalar
    assert not s.hatalar, s.hatalar



# ================================================================ evrensel hedefler: betik + genel API
def test_onyuz_betik_ve_genel_api(sistem, tarayici, tmp_path, liste):
    """Kullanıcı isteği 2026-10-01: hedef eklemede Control-M dışında genel API'ler ve Python / PowerShell betikleri;
    betik ekstra süper yönetici şifresiyle (betik_sifresi.bat) açılır ve o ekrandan canlı denenir. Gerçek sistem."""
    from cekirdek import betik_sifresi
    o, sahte, url = sistem
    L = liste
    s = oturum(tarayici, url)
    s.on("dialog", lambda d: d.accept())                       # 'örnek betikle değiştirilsin mi?' onayı
    ust = "ornek-super-sifre-E"
    ad = "fatura-betigi"

    with L("Hedefler", "Hedef ekle → Betik kartı (şifre yok)", "süper yönetici şifresi belirlenmemişken betik seçilemez; betik_sifresi.bat yönlendirmesi"):
        git(s, "Hedefler")
        s.get_by_role("button", name="Hedef ekle", exact=True).click()
        t = pencere(s, "Hedef ekle")
        kart = t.locator(".secim-kart", has_text="Betik")
        expect(kart).to_have_class(re.compile("kapali"))
        expect(kart).to_contain_text("betik_sifresi.bat")
        expect(kart.locator("input")).to_be_disabled()
        t.get_by_role("button", name="Vazgeç", exact=True).click()
        betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), ust, belirleyen="test")

    with L("Betik penceresi", "Kilit kapalı", "editör salt okunur, 'Canlı çalıştır' ve 'Hedefi ekle' kapalı; yanlış şifre → kalan deneme"):
        p = hedef_turu_sec(s, "Betik")
        expect(p.locator(".kilit-serit")).to_contain_text("Süper yönetici kilidi kapalı")
        assert p.locator("#betik_kod").evaluate("e => e.readOnly")
        expect(p.get_by_role("button", name="Hedefi ekle", exact=True)).to_be_disabled()
        expect(p.get_by_role("button", name="Canlı çalıştır…", exact=True)).to_be_disabled()
        p.locator("#betik_kilit_sifre").fill("yanlis-sifre-000")
        p.get_by_role("button", name="Kilidi aç", exact=True).click()
        expect(p.locator(".kilit-serit .hata")).to_contain_text("Kalan deneme: 4")

    with L("Betik penceresi", "Kilidi aç", "doğru şifreyle 10 dk açılır; editör yazılabilir, sayaç görünür, denetime yazılır"):
        p.locator("#betik_kilit_sifre").fill(ust)
        p.get_by_role("button", name="Kilidi aç", exact=True).click()
        expect(p.locator(".serit.basari")).to_contain_text("Süper yönetici kilidi açık")
        expect(p.locator(".serit.basari")).to_contain_text(re.compile(r"[0-9]:[0-5][0-9] kaldı"))
        assert not p.locator("#betik_kod").evaluate("e => e.readOnly")
        expect(p.get_by_role("button", name="Hedefi ekle", exact=True)).to_be_enabled()
        expect(p).to_contain_text("servisle aynı yorumlayıcı")
        assert o.hdb.tek("SELECT 1 FROM denetim WHERE islem='BETIK_KILIDI_ACILDI'")

    with L("Betik penceresi", "Örnek + sözdizimi denetimi", "örnek yüklenir; bozuk betikte hata satırı işaretlenir, düzelince ✓ (çalıştırmadan)"):
        p.locator("#betik_ad").fill(ad)
        p.locator("select[aria-label='Örnek yükle']").select_option(label="Python · en sade (yalnız yazdırır)")
        ed = p.locator("#betik_kod")
        expect(ed).to_have_value(re.compile("FWP_DOSYA_ADI"))
        sade = ed.input_value()
        ed.fill(sade + "print((1,\n")
        p.get_by_role("button", name="Sözdizimini denetle", exact=True).click()
        expect(p.locator(".betik-denetim")).to_contain_text("✗")
        expect(p.locator(".satirno .hatali")).to_have_count(1)
        ed.fill(sade + "try:\n    x = 1\nexcept Exception:\n    pass\n")
        expect(p.locator(".betik-uyarilar")).to_contain_text("hatayı yutar")
        ed.fill(sade)
        p.get_by_role("button", name="Sözdizimini denetle", exact=True).click()
        expect(p.locator(".betik-denetim")).to_contain_text("✓ Sözdizimi geçerli")

    with L("Betik penceresi", "Gizli değer + kuru deneme", "gizli değer FWP_SIR_ olarak, maskeli gösterilir; çalıştırılmaz"):
        p.get_by_role("button", name="Gizli değer ekle", exact=True).click()
        p.locator(".sir-satir input[type=text]").last.fill("api anahtari")
        expect(p.locator(".sir-satir input[type=text]").last).to_have_value("API_ANAHTARI")
        p.locator(".sir-satir input[type=password]").last.fill("ornek-betik-sir-degeri")
        p.get_by_role("button", name="Kuru deneme", exact=True).click()
        expect(p.locator(".deneme-sonuc")).to_contain_text("FWP_SIR_API_ANAHTARI")
        expect(p.locator(".deneme-sonuc")).to_contain_text("*** (gizli)")
        expect(p.locator(".deneme-sonuc")).not_to_contain_text("ornek-betik-sir-degeri")
        expect(p.locator(".test-durum")).to_contain_text("henüz canlı denenmedi")

    with L("Betik penceresi", "Canlı çalıştır…", "onay kutusu işaretlenmeden çalışmaz; betik gerçekten çalışır, çıkış 0 · stdout · 'bu içerik denendi'"):
        p.get_by_role("button", name="Canlı çalıştır…", exact=True).click()
        onay = pencere(s, "Betiği gerçekten çalıştır")
        expect(onay.get_by_role("button", name="Çalıştır", exact=True)).to_be_disabled()
        onay.locator("input[type=checkbox]").check()
        onay.get_by_role("button", name="Çalıştır", exact=True).click()
        expect(p.locator(".deneme-sonuc .rozet")).to_have_text("Başarılı")
        expect(p.locator(".deneme-sonuc")).to_contain_text("Dosya: FATURA_20260930.csv")
        expect(p.locator(".deneme-sonuc")).to_contain_text("canlı test: 1")
        expect(p.locator(".test-durum")).to_contain_text("Bu içerik canlı denendi")
        assert o.hdb.tek("SELECT 1 FROM denetim WHERE islem='BETIK_CANLI_TEST'")

    with L("Betik penceresi", "Hedefi ekle", "betik + gizli değer kaydedilir (DPAPI); kartta tür, sürüm, gizli değer adı"):
        p.get_by_role("button", name="Hedefi ekle", exact=True).click()
        bildirim(s, "Betik hedefi eklendi")
        k = s.locator(".kart", has_text=ad).first
        expect(k).to_contain_text("Betik · Python")
        expect(k).to_contain_text("API_ANAHTARI (şifreli)")
        expect(k).to_contain_text("zaman aşımı 30 sn")
        ham = json.loads(o.db.tek("SELECT ayrintilar FROM hedef WHERE ad=?", (ad,))[0])
        assert ham["sirlar"][0]["ref"].startswith("dpapi:") and ham["kod"] == sade

    with L("Hedefler", "Betiği aç → Kilitle", "betik sunucudan açılır; kilitlenince editör salt okunur ve kaydet kapalı"):
        k.get_by_role("button", name="Betiği aç", exact=True).click()
        p = pencere(s, f"Betik hedefi: {ad}")
        expect(p.locator("#betik_kod")).to_have_value(sade)
        p.get_by_role("button", name="Kilitle", exact=True).click()
        expect(p.locator(".kilit-serit")).to_contain_text("Süper yönetici kilidi kapalı")
        assert p.locator("#betik_kod").evaluate("e => e.readOnly")
        expect(p.get_by_role("button", name="Değişiklikleri kaydet", exact=True)).to_be_disabled()
        p.get_by_role("button", name="Vazgeç", exact=True).click()

    d = tmp_path / "betikli"
    d.mkdir()
    y = api(url)
    assert y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[0] == 200
    with L("Kural penceresi", "Betik hedefi seçilir", "istek alanı yerine 'betiğe gidecek ek değerler'; kuru denemede FWP_P_ değerleri"):
        git(s, "Dizinler ve kurallar")
        s.locator(".kart", has_text=str(d)).get_by_role("button", name="Kural ekle", exact=True).click()
        p = pencere(s, f"Kural ekle · {d}")
        p.get_by_placeholder("örn. fatura").fill("betikli")
        p.locator("#kural_regex").fill(r"F_(?P<no>\d+)\.csv")
        p.get_by_placeholder("Kendi örnek adlarınız (her satıra bir tane)").fill("F_42.csv")
        p.locator("select").filter(has=s.locator("option", has_text=ad)).select_option(label=ad)
        expect(p.locator("#kural_betik_param")).to_be_visible()
        expect(p.get_by_placeholder("/run/event/{ctm}/OLAY_ADI/ODAT")).to_be_hidden()
        p.locator("#kural_betik_param").fill("OLAY=GELDI_{no}")
        expect(p.locator("table.eslesme tr", has_text="F_42.csv")).to_contain_text("eşleşiyor")
        p.get_by_role("button", name="Kuru deneme", exact=True).click()
        expect(p.locator(".deneme-sonuc")).to_contain_text("FWP_P_OLAY")
        expect(p.locator(".deneme-sonuc")).to_contain_text("GELDI_42")

    with L("Kural penceresi", "Betik hedefli kuralı kaydet", "kilit kapalıyken reddedilir; pencereden kilit açılınca kaydedilir"):
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        expect(p.locator(".alan.hata[role=alert]")).to_contain_text("süper yönetici kilidini açın")
        p.locator("#betik_kilit_sifre").fill(ust)
        p.get_by_role("button", name="Kilidi aç", exact=True).click()
        expect(p.locator(".serit.basari")).to_contain_text("Süper yönetici kilidi açık")
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        bildirim(s, "Kural eklendi")

    with L("Teslim", "Dosya gelir → betik çalışır", "kurala uyan dosya için betik teslimde çalışır; İLETİLDİ, deneme geçmişinde 'çıkış 0'"):
        yaz(d, "F_7.csv")
        t = o.bekle(lambda: (t_ := tetik(o, "F_7.csv")) and t_["durum"] == "ILETILDI" and t_)
        assert json.loads(t["deneme_gecmisi"])[-1]["mesaj"].startswith("çıkış 0")

    tok = "Bearer-Token-5566"
    taban = f"http://127.0.0.1:{sahte.port}"
    with L("Hedefler", "Hedef ekle → Genel API", "gizli başlık reddedilir; Bearer token ile bağlantı denenir, kaydedilir; kartta tür ve kimlik"):
        git(s, "Hedefler")
        p = hedef_turu_sec(s, "Genel API (REST)")
        p.get_by_placeholder("örn. Raporlama API").fill("rapor-api")
        p.get_by_placeholder("https://api.sirket.local/v1").fill(taban)
        p.locator("#api_anahtar").fill(tok)
        p.get_by_placeholder("X-Kaynak: FileWatcherPro\nX-Ortam: prod").fill("Authorization: elle")
        p.get_by_role("button", name="Hedefi ekle", exact=True).click()
        expect(p.locator(".alan.hata[role=alert]")).to_contain_text("sabit başlıkta olmamalı")
        p.get_by_placeholder("X-Kaynak: FileWatcherPro\nX-Ortam: prod").fill("X-Kaynak: FWP")
        p.get_by_role("button", name="Bağlantıyı dene", exact=True).click()
        expect(p.locator(".yanit.ok")).to_contain_text("✓")
        p.get_by_role("button", name="Hedefi ekle", exact=True).click()
        bildirim(s, "Hedef eklendi")
        k = s.locator(".kart", has_text="rapor-api").first
        expect(k).to_contain_text("Genel API (REST) · " + taban)
        expect(k).to_contain_text("Bearer token · uygulamada şifreli (bu sunucu)")

    with L("Hedefler", "Düzenle → API anahtarı", "token boş bırakılınca eskisi korunur; başlık adı görünür; gelen dosya bu başlıkla gider"):
        k.get_by_role("button", name="Düzenle", exact=True).click()
        p = pencere(s, "Hedefi düzenle: rapor-api")
        expect(p.locator("#api_anahtar")).to_have_attribute("placeholder", re.compile("kayıtlı"))
        p.locator("#api_kimlik").select_option("apikey")
        p.get_by_role("button", name="Değişiklikleri kaydet", exact=True).click()
        bildirim(s, "Hedef güncellendi")
        expect(s.locator(".kart", has_text="rapor-api").first).to_contain_text("API anahtarı (X-API-Key)")
        hid = o.db.tek("SELECT id FROM hedef WHERE ad='rapor-api'")[0]
        d2 = tmp_path / "apili"
        d2.mkdir()
        dz = y.post("/api/dizinler", {"yol": str(d2), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
        assert y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "r", "regex": r"R_\d+\.csv", "hedef_id": hid,
                                        "istek": {"yontem": "POST", "yol": "/webhook", "govde": '{"dosya": "{dosya_adi}"}'}})[0] == 200
        yaz(d2, "R_1.csv")
        o.bekle(lambda: any(w["govde"] == {"dosya": "R_1.csv"} for w in sahte.webhook))
        w = next(w for w in sahte.webhook if w["govde"] == {"dosya": "R_1.csv"})
        assert w["basliklar"]["x-api-key"] == tok and w["basliklar"]["x-kaynak"] == "FWP"
    o.cekirdek_kapat()
    for gizli in ("ornek-betik-sir-degeri", tok, ust):
        duz_sir_yok(o, gizli)
    assert not s.hatalar, s.hatalar



def test_onyuz_kurala_bagli_mail(sistem, tarayici, tmp_path, smtp, liste):
    """Kullanıcı isteği 2026-10-01: kural eklerken bu kurala bağlanacak mail adresi seçilebilsin; o kuralın ve
    dizininin hataları (ör. regex'e uymayan dosya) bu adrese gitsin."""
    o, sahte, url = sistem
    L = liste
    y = api(url)
    assert y.put("/api/bildirim/smtp", smtp.ayar())[0] == 200
    kod, h_ = y.post("/api/hedefler", {"ad": "controlm", "adres": sahte.adres, "tur": "CONTROLM",
                                       "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})
    assert kod == 200, h_
    d = tmp_path / "postali"
    d.mkdir()
    assert y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[0] == 200
    s = oturum(tarayici, url)
    with L("Kural penceresi", "3 · Bildirim (mail)", "alıcı ve olaylar seçilir; geçersiz adres kaydı engeller; kural kaydedilince bağlı bildirim kurulur"):
        git(s, "Dizinler ve kurallar")
        s.locator(".kart", has_text=str(d)).get_by_role("button", name="Kural ekle", exact=True).click()
        p = pencere(s, f"Kural ekle · {d}")
        p.get_by_placeholder("örn. fatura").fill("postali")
        p.locator("#kural_regex").fill(r"P_\d+\.csv")
        expect(p.locator(".kural-bildirim")).to_contain_text("Bu dizinde hiçbir kuralın regex'ine uymayan dosya geldi")
        expect(p.locator(".kural-bildirim input[value=DOSYA_ESLESMEDI]")).to_be_checked()
        expect(p.locator(".kural-bildirim input[value=DOSYA_SLA]")).not_to_be_checked()
        p.locator("#kural_mail").fill("ekip@test.local\nadres-degil")
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        expect(p.locator(".alan.hata[role=alert]")).to_contain_text("Geçersiz e-posta adresi: adres-degil")
        assert o.db.tek("SELECT COUNT(*) FROM kural")[0] == 0
        p.locator("#kural_mail").fill("ekip@test.local")
        p.get_by_role("button", name="Kuralı ekle", exact=True).click()
        bildirim(s, "Kural eklendi")
        expect(s.locator("tr", has_text="postali")).to_contain_text("ekip@test.local")
        b = json.loads(o.db.tek("SELECT kurallar FROM bildirim_kural")[0])
        assert b == [o.db.tek("SELECT id FROM kural WHERE ad='postali'")[0]]
    with L("Teslim + mail", "Regex'e uymayan dosya", "o dizine gelen ve hiçbir kurala uymayan dosya, kurala bağlı adrese mail olarak gider"):
        yaz(d, "BASKA_1.csv")
        o.bekle(lambda: any("BASKA_1.csv" in m["govde"] for m in smtp.mailler if "ekip@test.local" in m["to"]), zaman_asimi=40)
    with L("Bildirimler", "Kural kapsamlı bildirim", "listede 'Kural: postali (dizin)'; düzenleme penceresi kural bağını gösterir ve korur"):
        git(s, "Bildirimler (mail)")
        satir = s.locator("tr", has_text="ekip@test.local").filter(has_text="Anında")
        expect(satir).to_contain_text("Kural: postali")
        satir.get_by_role("button", name="Düzenle").click()
        p = pencere(s, "Bildirim kuralını düzenle")
        expect(p).to_contain_text("kuralına bağlandı")
        p.get_by_role("button", name="Kaydet", exact=True).click()
        bildirim(s, "Bildirim kuralı kaydedildi")
        assert o.db.tek("SELECT kurallar FROM bildirim_kural")[0] is not None
    with L("Kural penceresi", "Alıcıyı boşalt", "kural düzenlenip alıcılar boşaltılınca bağlı bildirim kuralı silinir"):
        git(s, "Dizinler ve kurallar")
        s.locator("tr", has_text="postali").get_by_role("button", name="Kuralı düzenle").click()
        p = pencere(s, f"Kuralı düzenle · {d}")
        expect(p.locator("#kural_mail")).to_have_value("ekip@test.local")
        p.locator("#kural_mail").fill("")
        p.get_by_role("button", name="Değişiklikleri kaydet", exact=True).click()
        bildirim(s, "Kural güncellendi")
        o.bekle(lambda: o.db.tek("SELECT COUNT(*) FROM bildirim_kural")[0] == 0)
    assert not s.hatalar, s.hatalar



def test_onyuz_kurallari_durdur(sistem, tarayici, tmp_path, liste):
    """Kullanıcı isteği 2026-10-01: kurallar ekrandan durdurulabilmeli, tamamını durdurma da olmalı; kurallar
    dizinlerin altında da görünmeli (Genel bakış)."""
    o, sahte, url = sistem
    L = liste
    y = api(url)
    hid = y.post("/api/hedefler", {"ad": "controlm", "adres": sahte.adres, "tur": "CONTROLM",
                                   "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})[1]["id"]
    dizinler = []
    for ad, rx in (("satis", r"S_\d+\.csv"), ("stok", r"T_\d+\.csv")):
        d = tmp_path / ad
        d.mkdir()
        dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
        assert y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": f"kural_{ad}", "regex": rx, "hedef_id": hid,
                                        "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/X/ODAT", "govde": ""}})[0] == 200
        dizinler.append(d)
    s = oturum(tarayici, url)
    aktif = lambda ad: o.db.tek("SELECT aktif FROM kural WHERE ad=?", (ad,))[0]          # noqa: E731
    with L("Dizinler", "Tüm kuralları durdur", "onaylı pencere (kayıtlı / kayıtsız); bütün kurallar durur, hedef açık kalır"):
        git(s, "Dizinler ve kurallar")
        s.get_by_role("button", name="Tüm kuralları durdur", exact=True).click()
        p = pencere(s, "Tüm kuralları durdur")
        expect(p).to_contain_text("kural_satis")
        p.get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Kural(lar) durduruldu")
        o.bekle(lambda: aktif("kural_satis") == 0 and aktif("kural_stok") == 0)
        expect(s.locator("tr", has_text="kural_satis")).to_contain_text("Kapalı · kayıtlı")
    with L("Dizinler", "Tüm kuralları aç", "durdurulmuş kuralların hepsi açılır"):
        s.get_by_role("button", name="Tüm kuralları aç", exact=True).click()
        pencere(s, "Tüm kuralları aç").get_by_role("button", name="Tüm kuralları aç", exact=True).click()
        bildirim(s, "Kurallar açıldı")
        o.bekle(lambda: aktif("kural_satis") == 1 and aktif("kural_stok") == 1)
    with L("Dizinler", "Dizin kartı → Kuralları durdur", "yalnız o dizinin kuralları durur; diğer dizin etkilenmez"):
        s.locator(".kart", has_text=str(dizinler[0])).get_by_role("button", name="Kuralları durdur", exact=True).click()
        pencere(s, f"Kuralları durdur: {dizinler[0]}").get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Kural(lar) durduruldu")
        o.bekle(lambda: aktif("kural_satis") == 0)
        assert aktif("kural_stok") == 1
    with L("Genel bakış", "Dizinin altında kurallar", "her dizinin altında kuralları, durumları; Aç / Durdur düğmesi"):
        git(s, "Genel bakış")
        satir = s.locator(".dizin-kurali", has_text="kural_satis")
        expect(satir).to_contain_text("durduruldu (kayıtlı)")
        satir.get_by_role("button", name="Aç", exact=True).click()
        bildirim(s, "Kural açıldı")
        o.bekle(lambda: aktif("kural_satis") == 1)
        expect(s.locator(".dizin-kurali", has_text="kural_stok")).to_contain_text("→ controlm")
        s.locator(".dizin-kurali", has_text="kural_stok").get_by_role("button", name="Durdur", exact=True).click()
        pencere(s, "Kuralı durdur").get_by_role("button", name="Durdur", exact=True).click()
        bildirim(s, "Kural(lar) durduruldu")
        o.bekle(lambda: aktif("kural_stok") == 0)
    assert not s.hatalar, s.hatalar



def test_onyuz_lokal_secerek_gonder_ve_sil(sistem, tarayici, tmp_path, liste):
    """Kullanıcı isteği 2026-10-01: lokalde birikenleri seçerek gönder / sil; süper yönetici şifresi; tutanak."""
    from cekirdek import betik_sifresi
    o, sahte, url = sistem
    L = liste
    y = api(url)
    hid = y.post("/api/hedefler", {"ad": "controlm", "adres": sahte.adres, "tur": "CONTROLM",
                                   "ayrintilar": {"ctm": "ctmsunucu", "kimlik_turu": "yok"}})[1]["id"]
    d = tmp_path / "lokalli"
    d.mkdir()
    dz = y.post("/api/dizinler", {"yol": str(d), "ilk_kurulum_modu": "TETIKLE", "uzantilar": ".csv"})[1]
    assert y.post("/api/kurallar", {"dizin_id": dz["id"], "ad": "l", "regex": r"L_\d+\.csv", "hedef_id": hid,
                                    "istek": {"yontem": "POST", "yol": "/run/event/{ctm}/L/ODAT", "govde": ""}})[0] == 200
    assert y.post(f"/api/hedefler/{hid}/kapat", {"mod": "KAYITLI"})[0] == 200
    for a in ("L_1.csv", "L_2.csv", "L_3.csv"):
        yaz(d, a)
    o.bekle(lambda: all((t := tetik(o, a)) and t["durum"] == "LOKALDE" for a in ("L_1.csv", "L_2.csv", "L_3.csv")), zaman_asimi=30)
    assert y.post(f"/api/hedefler/{hid}/ac")[0] == 200
    super_ = "ornek-super-sifre-F"
    betik_sifresi.belirle(betik_sifresi.dosya_yolu(o.baslangic.parent), super_, belirleyen="test")
    s = oturum(tarayici, url)
    with L("Lokal kayıt", "Seçim", "kayıtlar tek tek seçilir; 'N seçili'; düğmeler seçim yokken pasif"):
        git(s, "Lokal kayıt ve erit")
        expect(s.get_by_role("button", name="Seçilenleri gönder", exact=True)).to_be_disabled()
        s.get_by_role("checkbox", name="L_1.csv seç").check()
        s.get_by_role("checkbox", name="L_2.csv seç").check()
        expect(s.locator("#lokal_secili")).to_have_text("2 seçili")
        s.screenshot(path=str(SONUC.parent / "onyuz_lokal_secim.png"), full_page=True)
    with L("Lokal kayıt", "Seçilenleri gönder", "süper yönetici kilidi açılmadan gönderilmez; açılınca yalnız seçilenler gider"):
        s.get_by_role("button", name="Seçilenleri gönder", exact=True).click()
        p = pencere(s, "Seçilenleri gönder (2)")
        expect(p.get_by_role("button", name="Gönder", exact=True)).to_be_disabled()
        p.locator("#betik_kilit_sifre").fill(super_)
        p.get_by_role("button", name="Kilidi aç", exact=True).click()
        expect(p.get_by_role("button", name="Gönder", exact=True)).to_be_enabled()
        p.get_by_role("button", name="Gönder", exact=True).click()
        bildirim(s, "2 kayıt gönderime alındı")
        o.bekle(lambda: tetik(o, "L_1.csv")["durum"] == "ILETILDI" and tetik(o, "L_2.csv")["durum"] == "ILETILDI")
        assert tetik(o, "L_3.csv")["durum"] == "LOKALDE"
    with L("Lokal kayıt", "Seçilenleri sil", "neden + 'anladım' olmadan silinmez; tutanak yazılır, tetik 'Elle silindi'"):
        s.get_by_role("checkbox", name="L_3.csv seç").check()
        s.get_by_role("button", name="Seçilenleri sil", exact=True).click()
        p = pencere(s, "Seçilenleri sil (1)")
        sil = p.get_by_role("button", name="Kalıcı olarak sil", exact=True)
        expect(p.locator(".kilit-serit")).to_contain_text("Süper yönetici kilidi açık")
        expect(sil).to_be_disabled()
        p.locator("#lokal_sil_neden").fill("yanlış dosya, ekip onayladı")
        expect(sil).to_be_disabled()
        p.get_by_role("checkbox", name="Bu dosyaların hedefe hiç gönderilmeyeceğini anladım.").check()
        expect(sil).to_be_enabled()
        sil.click()
        bildirim(s, "1 kayıt silindi")
        o.bekle(lambda: tetik(o, "L_3.csv")["durum"] == "SILINDI")
        assert list((o.veri / "lokal_silinen").glob("tutanak_*.json"))
        expect(s.locator("#icerik")).to_contain_text("Lokalde bekleyen kayıt yok")
    assert not s.hatalar, s.hatalar
