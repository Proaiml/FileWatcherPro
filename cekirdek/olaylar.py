"""Olay kataloğu: alarm türleri ve maile yönlendirilebilecek olaylar TEK yerden tanımlanır.

Önyüz (Alarmlar sayfasındaki tür / 'Ne yapmalı', Bildirimler > olay seçimi) ve bildirim eklentisi (hangi olay hangi
kurala uyar) bu kataloğu kullanır. Olaylar iki kaynaktan gelir:
  * alarmlar (canli.db > alarm): anahtarın önekinden türe eşlenir (alarm_turu),
  * dosya olayları (hata.db > gonderilemeyen, canli.db > tetik): sebebinden türe eşlenir (sebep_turu).
Kapsam: 'dizin' olayları bildirim kuralındaki dizin seçimiyle süzülür; 'hedef' ve 'sistem' olayları dizinden bağımsızdır.
"""
import re

_K = [
    # kod, grup, ad, seviye, kapsam, önerilen, açıklama, ne yapmalı
    ("HEDEF_DEVRE", "Hedef / teslim", "Devre kesildi", "KRITIK", "hedef", 1,
     "Hedef (Control-M / API / betik) art arda yanıt vermedi; yeni tetikler denenmeden lokale yazılıyor.",
     "Hedefin durumunu kontrol edin; düzelince 'Devreyi normale al', ardından 'Kademeli erit'."),
    ("HEDEF_KALICI", "Hedef / teslim", "Kalıcı hata (istek reddedildi)", "KRITIK", "hedef", 1,
     "Hedef isteği reddetti (4xx: olay / iş adı, klasör, yetki) ya da betik 10 ile çıktı. Tetik lokalde bekler, yeniden denenmez.",
     "Kuralın isteğini 'Kuru deneme' ile kontrol edin, düzeltin, sonra erit edin."),
    ("DOSYA_GONDERILEMEDI", "Hedef / teslim", "Dosya hedefe gönderilemedi", "UYARI", "dizin", 1,
     "Tetik gönderilemedi ve lokal kayda yazıldı (deneme planı bitti, kalıcı hata, devre kesik ya da hedef/kural kayıtlı kapalı).",
     "Hedef düzelince Lokal kayıt sayfasından 'Kademeli erit'."),
    ("DOSYA_OLASI_CIFT", "Hedef / teslim", "Olası çift çağrı", "UYARI", "dizin", 0,
     "Cevap gelmeden bağlantı koptu ya da betiğin süresi doldu; hedef işi iki kez yapmış olabilir.",
     "Hedefte tetik kimliğiyle (FWP_KIMLIK / X-Idempotency-Key) iki çalışma var mı bakın."),
    ("DOSYA_SLA", "Hedef / teslim", "SLA aşıldı", "BILGI", "dizin", 0,
     "Dosya hazır olduktan sonra hedefe iletim SLA süresini aştı.",
     "Sık oluyorsa Sistem izleme ve hedefin yanıt sürelerine bakın."),
    ("DOSYA_KAYITSIZ", "Hedef / teslim", "Kayıtsız kapalıyken dosya geldi", "UYARI", "dizin", 1,
     "Hedef ya da kural kayıtsız kapalıydı; dosya hedefe gönderilmedi ve saklanmadı.",
     "Gerekirse dosyayı elle işleyin; hedefi açın."),
    ("HEDEF_YAVAS", "Hedef / teslim", "Hedef yavaşladı (SLA aşımları arttı)", "UYARI", "hedef", 1,
     "Son pencerede (varsayılan 10 dk) canlı yoldan iletilen tetiklerin en az %20'si SLA hedefini aştı.",
     "Hedefin (Control-M / API / betik) yanıt sürelerine ve Sistem izleme'ye bakın; kalıcıysa eşzamanlı çağrı sayısını ya da SLA hedefini gözden geçirin."),
    ("ERIT_DURDU", "Hedef / teslim", "Kademeli erit durdu", "UYARI", "hedef", 1,
     "Erit sırasında hedef hata verdi; kalanlar lokalde güvende.", "Hedef düzelince eriti yeniden başlatın."),
    ("LOKAL_BIRIKTI", "Hedef / teslim", "Lokalde kayıt birikiyor", "UYARI", "hedef", 0,
     "Gönderilemeyen tetikler lokal kayıtta bekliyor.", "Hedef sağlıklıysa 'Kademeli erit' başlatın."),
    ("HEDEF_KAPALI_UZUN", "Hedef / teslim", "Hedef / kural uzun süredir kapalı", "UYARI", "hedef", 0,
     "Bir hedef ya da kural ayarlanan süreden uzun kapalı.", "Kapatma bilinçliyse onaylayın; değilse açın."),
    ("LOKAL_KAYIT", "Hedef / teslim", "Lokal kayıt yazılamıyor / bozuk", "KRITIK", "sistem", 1,
     "Lokal kayıt klasörüne yazılamıyor ya da okunamayan kayıt karantinaya alındı.",
     "Disk ve klasör izinlerini kontrol edin; tetikler veritabanında güvende."),
    ("DIZIN_ERISILEMEZ", "Dizin / dosya", "Dizine erişilemiyor", "KRITIK", "dizin", 1,
     "Ağ yolu ya da paylaşım erişilemez; 5/10/15 sn denemeleri bitti.",
     "Paylaşımı ve servis hesabının okuma yetkisini kontrol edin; dizin gelince kaçanlar yakalanır."),
    ("DIZIN_YANITSIZ", "Dizin / dosya", "Dizin yanıt vermiyor (ağ takıldı)", "KRITIK", "dizin", 1,
     "Dizin listelemesi zaman aşımına uğradı.", "Dosya sunucusu ve ağ bağlantısını kontrol edin."),
    ("YUKLEME_ASKIDA", "Dizin / dosya", "Yükleme askıda (çok uzun sürüyor)", "UYARI", "dizin", 1,
     "Yazılmakta olan dosya ayarlanan süreyi aştı; tamamlanana kadar tetiklenmez.",
     "FTP tarafında yüklemenin durumuna bakın; yarım kaldıysa dosyayı yeniden isteyin."),
    ("DOSYA_ANOMALI", "Dizin / dosya", "Dosyalarda anomali (boyut / adet / teslim süresi)", "UYARI", "dizin", 0,
     "Yapay zekâ asistanının istatistik takibi: bir kuralın dosyası alışılmadık boyutta geldi, günlük sayısı ya da teslim süresi normalinden saptı. Yalnız asistan ayarlarında 'anomaliyi alarm olarak aç' seçiliyse oluşur.",
     "Dosyayı ve gönderen tarafı kontrol edin (yarım / boş yükleme, yanlış dosya, eksik gönderim). Normalse onaylayın; asistan önerisini 'Faydasız' işaretleyin."),
    ("DOSYA_ESLESMEDI", "Dizin / dosya", "Kurala uymayan dosya geldi", "BILGI", "dizin", 0,
     "Uzantısı uyan ama hiçbir kuralın regex'ine uymayan dosya.",
     "Yeni bir dosya türü mü? Kural ekleyin ya da regex'i genişletin."),
    ("EKLENTI_ELLE", "Sistem", "Bileşen elle müdahale bekliyor", "KRITIK", "sistem", 1,
     "Bir bileşen art arda düştü; otomatik yeniden başlatma durdu.", "Eklentiler sayfasında son hataya bakın, 'Başlat' ile yeniden deneyin."),
    ("EKLENTI_DUSTU", "Sistem", "Bileşen düştü (kendiliğinden kalktı)", "UYARI", "sistem", 0,
     "Bir bileşen beklenmedik biçimde kapandı ve yeniden başlatıldı.", "Tekrarlanıyorsa logları inceleyin."),
    ("CEKIRDEK_YENIDEN", "Sistem", "Çekirdek beklenmedik kapandı", "UYARI", "sistem", 1,
     "Windows servisi çekirdeği yeniden başlattı; kayıp yok.", "Sık tekrarlanıyorsa loglar klasöründeki cekirdek loguna bakın."),
    ("BAKIM_HATA", "Sistem", "Bakım hata verdi", "UYARI", "sistem", 0,
     "Bir bakım adımı hata verdi ve geri alındı (ya da bütünlük kontrolü geçmedi).",
     "Genel bakış → Bakım geçmişi'nde hangi adımın geri alındığına bakın."),
    ("DB_BOYUT", "Sistem", "Veritabanı büyüdü", "UYARI", "sistem", 0,
     "canli.db ya da hata.db beklenenden büyük.", "Saklama sınırlarını ve çözülmemiş kayıtları kontrol edin."),
    ("HATA_DB_SINIR", "Sistem", "Çözülmemiş kayıt sınırı aşıldı", "UYARI", "sistem", 0,
     "Gönderilemeyen çözülmemiş kayıtlar sınırı aştı (silinmezler).", "Gönderilemeyenler sayfasındaki kayıtları çözün."),
    ("VARSAYILAN_SIFRE", "Sistem", "Varsayılan şifre kullanılıyor", "UYARI", "sistem", 0,
     "admin hesabının şifresi hâlâ ilk kurulumdaki gibi.", "Sağ üstteki kilit simgesinden şifreyi değiştirin."),
    ("MAIL_GONDERILEMIYOR", "Sistem", "Mail gönderilemiyor", "UYARI", "sistem", 0,
     "Bildirim maili art arda gönderilemedi (SMTP sunucusu, kimlik ya da ağ).",
     "Bildirimler sayfasında 'Bağlantıyı dene' ve Gönderim geçmişindeki hataya bakın. (Bu olay maille bildirilmez.)"),
    ("KAYNAK_SUNUCU_CPU", "Kaynaklar (sistem izleme)", "Sunucu CPU eşiği aşıldı", "UYARI", "sistem", 1,
     "Sunucunun işlemci kullanımı eşiği belirtilen süre boyunca aştı.", "Sistem izleme sayfasında hangi sürecin yük bindirdiğine bakın."),
    ("KAYNAK_SUNUCU_RAM", "Kaynaklar (sistem izleme)", "Sunucu bellek eşiği aşıldı", "UYARI", "sistem", 1,
     "Sunucunun bellek kullanımı eşiği belirtilen süre boyunca aştı.", "Sunucudaki diğer uygulamaların bellek kullanımını kontrol edin."),
    ("KAYNAK_DISK", "Kaynaklar (sistem izleme)", "Disk boş alanı azaldı", "KRITIK", "sistem", 1,
     "Veri ya da log diskinde boş alan eşiğin altına düştü; veritabanı yazamazsa izleme durur.", "Diskte yer açın; log saklama süresini azaltın."),
    ("KAYNAK_FWP_CPU", "Kaynaklar (sistem izleme)", "FileWatcherPro CPU eşiği aşıldı", "UYARI", "sistem", 1,
     "FileWatcherPro bileşenlerinin toplam işlemci kullanımı eşiği aştı.",
     "Çok büyük dizin ya da kısa tarama aralığı olabilir; Sistem izleme'de bileşenlere bakın."),
    ("KAYNAK_FWP_RAM", "Kaynaklar (sistem izleme)", "FileWatcherPro bellek eşiği aşıldı", "UYARI", "sistem", 1,
     "FileWatcherPro bileşenlerinin toplam belleği eşiği aştı.", "Bileşeni yeniden başlatmak geçici çözüm olur; logları saklayıp bildirin."),
    ("KAYNAK_LOG", "Kaynaklar (sistem izleme)", "Log klasörü büyüdü", "UYARI", "sistem", 0,
     "Log klasörü eşik boyutu aştı.", "Log saklama süresini ve boyut sınırını kontrol edin."),
    ("KAYNAK_TARAMA", "Kaynaklar (sistem izleme)", "Dizin taraması yavaş", "UYARI", "dizin", 0,
     "Bir dizinin listelenmesi art arda eşik süreyi aştı; yeni dosyalar geç fark edilir.",
     "Dosya sunucusu yükünü ve dizindeki dosya sayısını kontrol edin."),
]
KATALOG = [{"kod": k, "grup": g, "ad": a, "seviye": s, "kapsam": kp, "onerilen": bool(o), "aciklama": ac, "oneri": on}
           for k, g, a, s, kp, o, ac, on in _K]
KODLAR = {x["kod"]: x for x in KATALOG}
MAILE_GITMEZ = {"MAIL_GONDERILEMIYOR"}          # mail sorunu maille bildirilemez (döngü olmasın)
SEVIYE_SIRA = {"BILGI": 0, "UYARI": 1, "KRITIK": 2}

_ALARM = [
    (r"^dizin:(?P<dizin>\d+):erisilemez", "DIZIN_ERISILEMEZ"), (r"^dizin:(?P<dizin>\d+):yanitsiz", "DIZIN_YANITSIZ"),
    (r"^askida:(?P<dizin>\d+):", "YUKLEME_ASKIDA"), (r"^hedef:(?P<hedef>\d+):devre", "HEDEF_DEVRE"),
    (r"^hedef:(?P<hedef>\d+):kalici", "HEDEF_KALICI"), (r"^hedef:(?P<hedef>\d+):erit", "ERIT_DURDU"),
    (r"^hedef:(?P<hedef>\d+):lokalde", "LOKAL_BIRIKTI"), (r"^hedef:(?P<hedef>\d+):yavas", "HEDEF_YAVAS"), (r"^hedef:(?P<hedef>\d+):kapali", "HEDEF_KAPALI_UZUN"),
    (r"^kural:(?P<kural>\d+):kapali", "HEDEF_KAPALI_UZUN"), (r"^lokal:", "LOKAL_KAYIT"),
    (r"^eklenti:[a-z_]+:elle", "EKLENTI_ELLE"), (r"^eklenti:[a-z_]+:dustu", "EKLENTI_DUSTU"),
    (r"^servis:cekirdek_dustu", "CEKIRDEK_YENIDEN"), (r"^bakim:", "BAKIM_HATA"), (r"^db:", "DB_BOYUT"),
    (r"^hata_db:", "HATA_DB_SINIR"), (r"^kontrol:varsayilan_sifre", "VARSAYILAN_SIFRE"), (r"^bildirim:", "MAIL_GONDERILEMIYOR"),
    (r"^kaynak:sunucu_cpu", "KAYNAK_SUNUCU_CPU"), (r"^kaynak:sunucu_ram", "KAYNAK_SUNUCU_RAM"), (r"^kaynak:disk", "KAYNAK_DISK"),
    (r"^kaynak:fwp_cpu", "KAYNAK_FWP_CPU"), (r"^kaynak:fwp_ram", "KAYNAK_FWP_RAM"), (r"^kaynak:log", "KAYNAK_LOG"),
    (r"^kaynak:tarama:(?P<dizin>\d+)", "KAYNAK_TARAMA"), (r"^anomali:(?P<kural>\d+):", "DOSYA_ANOMALI"),
]
_ALARM = [(re.compile(d), k) for d, k in _ALARM]
_SEBEP = {"SLA_SON_DOLDU": "DOSYA_GONDERILEMEDI", "KALICI_HATA": "DOSYA_GONDERILEMEDI", "DEVRE_KESIK": "DOSYA_GONDERILEMEDI",
          "HEDEF_KAPALI_KAYITLI": "DOSYA_GONDERILEMEDI", "KURAL_KAPALI_KAYITLI": "DOSYA_GONDERILEMEDI",
          "HEDEF_KAPALI_KAYITSIZ": "DOSYA_KAYITSIZ", "KURAL_KAPALI_KAYITSIZ": "DOSYA_KAYITSIZ", "ESLESMEDI": "DOSYA_ESLESMEDI",
          "LOKAL_KAYIT_BOZUK": "LOKAL_KAYIT"}


def alarm_turu(anahtar: str) -> tuple:
    """Alarm anahtarı → (olay kodu, {'dizin': id, 'hedef': id, 'kural': id}). Tanınmazsa ('DIGER', {})."""
    for desen, kod in _ALARM:
        m = desen.match(anahtar or "")
        if m:
            return kod, {k: int(v) for k, v in m.groupdict().items() if v}
    return "DIGER", {}


def sebep_turu(sebep: str) -> str:
    return _SEBEP.get(sebep, "DOSYA_GONDERILEMEDI")
