"""Ayarlar.

İki tür ayar vardır:
  * Başlangıç ayarları (config/baslangic.json): veritabanına erişmeden önce bilinmesi gerekenler
    (veri/log klasörü, kontrol arayüzü adresi, eklenti listesi). Çalışırken değişmez.
  * Çalışma ayarları (canli.db > ayar): önyüzden canlı değişir. Her değişiklik doğrulanır ve
    'ayar_surumu' artırılır; eklentiler sürüm değişince ayarlarını yeniden okur.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ başlangıç ayarları
@dataclass(frozen=True)
class Baslangic:
    kok: Path
    veri: Path
    loglar: Path
    kontrol_adres: str
    kontrol_port: int
    eklentiler: tuple
    dosya: Path
    kontrol_izinli_adlar: tuple = ()      # Host başlığında kabul edilecek ek adlar (ör. DNS takma adı)

    @property
    def canli_db(self) -> Path:
        return self.veri / "canli.db"

    @property
    def hata_db(self) -> Path:
        return self.veri / "hata.db"

    @property
    def lokal_kayit(self) -> Path:
        return self.veri / "lokal_kayit"

    @property
    def karantina(self) -> Path:
        return self.veri / "karantina"


def baslangic_oku(yol=None) -> Baslangic:
    """Başlangıç ayarlarını okur. Öncelik: argüman > FWP_BASLANGIC ortam değişkeni > config/baslangic.json."""
    yol = Path(yol or os.environ.get("FWP_BASLANGIC") or (KOK / "config" / "baslangic.json")).resolve()
    d = json.loads(yol.read_text(encoding="utf-8"))

    def mutlak(p):
        p = Path(p)
        return p if p.is_absolute() else (KOK / p)

    b = Baslangic(
        kok=KOK,
        veri=mutlak(d.get("veri_klasoru", "veri")),
        loglar=mutlak(d.get("log_klasoru", "loglar")),
        kontrol_adres=str(d.get("kontrol_adres", "127.0.0.1")),
        kontrol_port=int(d.get("kontrol_port", 8770)),
        eklentiler=tuple(dict(e) for e in d.get("eklentiler", [])),
        dosya=yol,
        kontrol_izinli_adlar=tuple(str(x).lower() for x in d.get("kontrol_izinli_adlar", [])),
    )
    for p in (b.veri, b.loglar, b.lokal_kayit, b.karantina):
        p.mkdir(parents=True, exist_ok=True)
    return b


# ------------------------------------------------------------------ çalışma ayarları
@dataclass(frozen=True)
class Tanim:
    varsayilan: object
    tur: type
    grup: str
    aciklama: str
    alt: float = None
    ust: float = None
    secenekler: tuple = field(default=None)


def _plan(s) -> list:
    """'5,10,15' → [5.0, 10.0, 15.0]. Boş plan geçerlidir (tekrar yok)."""
    if isinstance(s, (list, tuple)):
        parca = list(s)
    else:
        parca = [p for p in str(s).replace(";", ",").split(",") if p.strip()]
    sonuc = []
    for p in parca:
        v = float(p)
        if not (0 < v <= 3600):
            raise ValueError(f"plan değeri 0–3600 sn arasında olmalı: {p}")
        sonuc.append(v)
    if len(sonuc) > 10:
        raise ValueError("planda en fazla 10 adım olabilir")
    return sonuc


def _uzanti_listesi(s) -> list:
    """'.csv, TXT' → ['.csv', '.txt'] (harf duyarsız, noktalı)."""
    parca = s if isinstance(s, (list, tuple)) else str(s).replace(";", ",").split(",")
    sonuc = []
    for p in parca:
        p = str(p).strip().casefold()
        if not p:
            continue
        if not p.startswith("."):
            p = "." + p
        if any(c in p for c in '\\/:*?"<>| '):
            raise ValueError(f"geçersiz uzantı: {p}")
        if p not in sonuc:
            sonuc.append(p)
    return sonuc


TANIMLAR = {
    # --- motor / tarama
    "motor_aktif": Tanim(True, bool, "Motor", "Tarama motoru çalışsın mı (önyüzden durdur/başlat)."),
    "tarama_araligi_sn": Tanim(2.0, float, "Motor", "Dizin listeleme sıklığı.", 0.2, 600),
    "dizin_tarama_zaman_asimi_sn": Tanim(20.0, float, "Motor", "Tek dizin listelemesi bu süreyi aşarsa dizin YANITSIZ sayılır.", 1, 600),
    "dizin_deneme_plani": Tanim("5,10,15", "plan", "Motor", "Dizine erişilemezse bekleme planı (sn); bitince ERİŞİLEMEZ + alarm."),
    "dizin_seyrek_deneme_sn": Tanim(30.0, float, "Motor", "ERİŞİLEMEZ dizin için seyrek deneme aralığı.", 1, 3600),
    # --- tamamlanma / kimlik
    "sabitlik_W_sn": Tanim(10.0, float, "Tamamlanma", "Boyut ve mtime bu süre değişmezse dosya tamamlanmış sayılabilir (paylaşım testiyle birlikte).", 0, 3600),
    "aski_T_dk": Tanim(30.0, float, "Tamamlanma", "Yazılmakta olan dosya bu süreyi aşarsa ASKIDA + önyüze bildirim.", 0.1, 1440),
    "hash_esik_mb": Tanim(500.0, float, "Tamamlanma", "Bu boyutun altındaki dosyaların içerik hash'i (xxh3) alınır; kimlik = dizin + ad + hash.", 0, 1_000_000),
    "parca_dikkate_al": Tanim(True, bool, "Tamamlanma", ".filepart/.part gibi geçici adları 'yükleniyor' olarak izle (asla tetiklenmez)."),
    "parca_uzantilari": Tanim(".filepart,.part", "uzantilar", "Tamamlanma", "Geçici yükleme uzantıları."),
    "coklu_kural": Tanim("ilk", str, "Kural", "Bir dosya birden çok kurala uyarsa: 'ilk' eşleşen ya da 'hepsi'.", secenekler=("ilk", "hepsi")),
    # --- teslim
    "sla_hedef_sn": Tanim(10.0, float, "Teslim", "HAZIR → ilk başarılı API çağrısı hedef süresi; aşılırsa SLA ihlali kaydı.", 1, 3600),
    "deneme_plani": Tanim("5,10,15", "plan", "Teslim", "API hatasında bekleme planı (sn); bitince lokal kayıt + alarm."),
    "cagri_timeout_sn": Tanim(4.0, float, "Teslim", "Tek API çağrısı için azami süre.", 0.5, 120),
    "esz_cagri_ust": Tanim(4, int, "Teslim", "Hedef başına aynı anda en fazla çağrı.", 1, 64),
    "otomatik_devre_esigi": Tanim(5, int, "Teslim", "Hedefte art arda bu kadar hata olursa devre kesilir; yeni tetikler denenmeden lokale yazılır (0 = kapalı).", 0, 1000),
    "erit_hizi": Tanim(5.0, float, "Teslim", "Kademeli eritmede saniyede en fazla çağrı.", 0.1, 100),
    "kapanis_teslim_bekleme_sn": Tanim(15.0, float, "Teslim", "Kapanırken (servis durdurma, Windows kapanışı, teslim "
                                       "eklentisini durdurma) bekleyen tetiklerin gönderilmesi için verilen süre. Bitmeyenler "
                                       "kaybolmaz: veritabanında kalır, açılışta kendiliğinden gönderilir.", 0, 60),
    "hedef_yavas_pencere_dk": Tanim(10.0, float, "Teslim", "Hedef yavaşlama alarmı: son bu kadar dakikada canlı yoldan "
                                    "iletilen en az 5 tetiğin %20'si SLA hedefini aşarsa uyarı açılır; %5'in altına inince "
                                    "kapanır.", 0.1, 1440),
    "kapali_hatirlatma_dk": Tanim(30.0, float, "Teslim", "Hedef/kural bu süreden uzun kapalı kalırsa hatırlatma alarmı.", 1, 10080),
    # --- depolama / bakım
    "gecmis_limit": Tanim(200, int, "Depolama", "canli.db: dizinden kalkmış dosya ve bitmiş tetik geçmişi (aktif ve bekleyenler hariç).", 10, 100000),
    "hata_limit": Tanim(1000, int, "Depolama", "hata.db: gönderilemeyen kayıt sınırı (çözülmemişler asla silinmez).", 10, 1_000_000),
    "denetim_limit": Tanim(2000, int, "Depolama", "hata.db: denetim kaydı sınırı.", 100, 1_000_000),
    "bakim_gunu": Tanim("Cumartesi", str, "Depolama", "Haftalık bakım günü.",
                        secenekler=("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")),
    "bakim_saati": Tanim("03:00", "saat", "Depolama", "Haftalık bakım saati (SS:DD)."),
    # --- eklentiler / gözetmen
    "eklenti_nabiz_sn": Tanim(1.0, float, "Gözetmen", "Eklentilerin nabız yazma aralığı.", 0.2, 60),
    "eklenti_yanitsiz_sn": Tanim(60.0, float, "Gözetmen", "Ana döngüsü bu süre ilerlemeyen eklenti takılmış sayılır ve yeniden başlatılır.", 2, 3600),
    "eklenti_baslama_payi_sn": Tanim(20.0, float, "Gözetmen", "Başlayan eklentiye ilk nabız için tanınan süre.", 1, 600),
    "eklenti_bekleme_plani": Tanim("1,2,5,10,30", "plan", "Gözetmen", "Düşen eklenti için yeniden başlatma bekleme planı (sn)."),
    "eklenti_dusme_limiti": Tanim(5, int, "Gözetmen", "Art arda bu kadar düşen eklenti ELLE_MÜDAHALE durumuna geçer.", 1, 100),
    "eklenti_stabil_sn": Tanim(60.0, float, "Gözetmen", "Bu süreden uzun çalışmış eklentinin düşme sayacı sıfırlanır.", 1, 86400),
    # --- loglama
    "log_saklama_gun": Tanim(10, int, "Loglama", "Log dosyalarının saklanma süresi.", 1, 3650),
    # --- sistem izleme (izleme eklentisi); eşik belirtilen süre boyunca aşılırsa alarm, 1 dk normal kalınca kapanır
    "izleme_aralik_sn": Tanim(10.0, float, "İzleme", "Sistem kaynaklarının ölçülme sıklığı (son 24 saat saklanır).", 1, 300),
    "izleme_normale_donus_sn": Tanim(60.0, float, "İzleme", "Değer eşiğin altına indikten bu kadar sn sonra alarm kapanır (dalgalanmada aç-kapa olmasın).", 1, 3600),
    "izleme_sunucu_cpu": Tanim(90.0, float, "İzleme", "Sunucu CPU eşiği (%).", 1, 100),
    "izleme_sunucu_cpu_aktif": Tanim(True, bool, "İzleme", "Sunucu CPU eşiği izlensin."),
    "izleme_sunucu_cpu_dk": Tanim(5.0, float, "İzleme", "Sunucu CPU eşiği bu kadar dakika sürerse alarm.", 0, 1440),
    "izleme_sunucu_ram": Tanim(90.0, float, "İzleme", "Sunucu bellek eşiği (%).", 1, 100),
    "izleme_sunucu_ram_aktif": Tanim(True, bool, "İzleme", "Sunucu bellek eşiği izlensin."),
    "izleme_sunucu_ram_dk": Tanim(5.0, float, "İzleme", "Sunucu bellek eşiği bu kadar dakika sürerse alarm.", 0, 1440),
    "izleme_disk_bos_gb": Tanim(5.0, float, "İzleme", "Veri ve log disklerinde en az boş alan (GB); altına düşünce KRİTİK alarm.", 0.1, 100000),
    "izleme_disk_bos_gb_aktif": Tanim(True, bool, "İzleme", "Disk boş alanı izlensin."),
    "izleme_fwp_cpu": Tanim(25.0, float, "İzleme", "FileWatcherPro bileşenlerinin toplam CPU eşiği (sunucunun %'si).", 1, 100),
    "izleme_fwp_cpu_aktif": Tanim(True, bool, "İzleme", "FileWatcherPro CPU'su izlensin."),
    "izleme_fwp_cpu_dk": Tanim(10.0, float, "İzleme", "FileWatcherPro CPU eşiği bu kadar dakika sürerse alarm.", 0, 1440),
    "izleme_fwp_ram_mb": Tanim(1024.0, float, "İzleme", "FileWatcherPro bileşenlerinin toplam bellek eşiği (MB).", 50, 1000000),
    "izleme_fwp_ram_mb_aktif": Tanim(True, bool, "İzleme", "FileWatcherPro belleği izlensin."),
    "izleme_fwp_ram_mb_dk": Tanim(10.0, float, "İzleme", "FileWatcherPro bellek eşiği bu kadar dakika sürerse alarm.", 0, 1440),
    "izleme_log_mb": Tanim(2048.0, float, "İzleme", "Log klasörü boyut eşiği (MB).", 10, 1000000),
    "izleme_log_mb_aktif": Tanim(True, bool, "İzleme", "Log klasörü boyutu izlensin."),
    "izleme_tarama_sn": Tanim(10.0, float, "İzleme", "Bir dizinin listelenmesi 3 ölçüm üst üste bu süreyi aşarsa alarm (sn).", 0.5, 3600),
    "izleme_tarama_sn_aktif": Tanim(True, bool, "İzleme", "Dizin tarama süresi izlensin."),
    # --- bildirim (mail)
    "bildirim_deneme_plani": Tanim("30,120,300,900,1800", "plan", "Bildirim", "Gönderilemeyen mail için yeniden deneme planı (sn); bitince HATA + alarm."),
    "bildirim_tasma_esigi": Tanim(10, int, "Bildirim", "Bir anında kural 10 dakikada bundan fazla mail üretirse geçici olarak özete geçer (mail yağmuru koruması).", 1, 1000),
    "bildirim_tasma_ozet_dk": Tanim(5.0, float, "Bildirim", "Taşma olduğunda biriken olayların özet maili bu aralıkla gider (dk).", 0.05, 120),
    "log_azami_mb": Tanim(50, int, "Loglama", "Tek log dosyasının azami boyutu.", 1, 10240),
}


def dogrula(anahtar: str, deger):
    """Değeri tanıma göre dönüştürür ve doğrular; geçersizse ValueError (Türkçe mesaj)."""
    t = TANIMLAR.get(anahtar)
    if t is None:
        raise ValueError(f"bilinmeyen ayar: {anahtar}")
    try:
        if t.tur is bool:
            if isinstance(deger, str):
                s = deger.strip().casefold()
                if s in ("1", "true", "evet", "açık", "acik", "on"):
                    v = True
                elif s in ("0", "false", "hayır", "hayir", "kapalı", "kapali", "off"):
                    v = False
                else:
                    raise ValueError
            else:
                v = bool(deger)
        elif t.tur is int:
            v = int(float(deger))
            if float(deger) != v:
                raise ValueError
        elif t.tur is float:
            v = float(deger)
        elif t.tur == "plan":
            return ",".join(f"{x:g}" for x in _plan(deger))
        elif t.tur == "uzantilar":
            return ",".join(_uzanti_listesi(deger))
        elif t.tur == "saat":
            ss, dd = str(deger).strip().split(":")
            ss, dd = int(ss), int(dd)
            if not (0 <= ss < 24 and 0 <= dd < 60):
                raise ValueError
            return f"{ss:02d}:{dd:02d}"
        else:
            v = str(deger).strip()
    except ValueError as e:
        mesaj = str(e) if str(e) else f"'{deger}' değeri {anahtar} için uygun değil"
        raise ValueError(mesaj) from None
    if t.alt is not None and v < t.alt:
        raise ValueError(f"{anahtar} en az {t.alt:g} olmalı")
    if t.ust is not None and v > t.ust:
        raise ValueError(f"{anahtar} en fazla {t.ust:g} olmalı")
    if t.secenekler and v not in t.secenekler:
        raise ValueError(f"{anahtar} şunlardan biri olmalı: {', '.join(t.secenekler)}")
    return v


class Ayarlar:
    """canli.db > ayar tablosu üzerinde önbellekli okuma/yazma."""

    def __init__(self, db):
        self.db = db
        self._surum = None
        self._degerler = {}

    def tazele(self, zorla: bool = False) -> bool:
        """Sürüm değiştiyse (ya da zorla) ayarları yeniden okur. Değişiklik olduysa True."""
        surum = self.db.meta_al("ayar_surumu", "0")
        if not zorla and surum == self._surum:
            return False
        satirlar = self.db.oku("SELECT anahtar, deger FROM ayar")
        degerler = {a: t.varsayilan for a, t in TANIMLAR.items()}
        for s in satirlar:
            if s["anahtar"] in TANIMLAR:
                try:
                    degerler[s["anahtar"]] = dogrula(s["anahtar"], json.loads(s["deger"]))
                except (ValueError, json.JSONDecodeError):
                    pass  # bozuk değer: varsayılan kullanılır
        for a, t in TANIMLAR.items():  # varsayılanları da normalize et
            if a not in {s["anahtar"] for s in satirlar}:
                degerler[a] = dogrula(a, t.varsayilan)
        self._degerler, self._surum = degerler, surum
        return True

    def al(self, anahtar: str):
        if self._surum is None:
            self.tazele(zorla=True)
        return self._degerler[anahtar]

    def plan(self, anahtar: str) -> list:
        return _plan(self.al(anahtar))

    def uzantilar(self, anahtar: str) -> list:
        return _uzanti_listesi(self.al(anahtar))

    def hepsi(self) -> dict:
        if self._surum is None:
            self.tazele(zorla=True)
        return dict(self._degerler)

    def degistir(self, anahtar: str, deger) -> tuple:
        """Doğrular, yazar, sürümü artırır. (eski, yeni) döner; denetim kaydını çağıran yazar."""
        yeni = dogrula(anahtar, deger)
        eski = self.al(anahtar)
        self.db.ayar_yaz(anahtar, yeni)
        self.tazele(zorla=True)
        return eski, yeni
