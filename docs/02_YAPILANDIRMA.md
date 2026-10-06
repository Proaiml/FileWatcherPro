# 02 · Yapılandırma

Bütün yapılandırma web arayüzünden yapılır ve `veri\canli.db`'de tutulur; dosya düzenlemek gerekmez. Her değişiklik
kim, ne zaman, eski ve yeni değerle **Denetim kaydı**'na yazılır ve çalışan sisteme yeniden başlatmadan uygulanır.

Önerilen sıra: **Hedef → Dizin → Kural → Bildirim.** Kural bir hedefe ve bir dizine bağlıdır, önce onlar olmalıdır.

- [Hedefler](#hedefler)
- [Dizinler](#dizinler)
- [Kurallar](#kurallar)
- [Bildirimler (mail)](#bildirimler-mail)
- [Ayarlar](#ayarlar)
- [Kullanıcılar ve roller](#kullanıcılar-ve-roller)
- [Arayüz dışındaki tek dosya: baslangic.json](#arayüz-dışındaki-tek-dosya-baslangicjson)

---

## Hedefler

Hedef, tetiğin gideceği yerdir. **Hedefler → Hedef ekle** penceresinde önce tür seçilir.

### Control-M

| Alan | Açıklama |
|---|---|
| Ad | Ekranda ve loglarda görünen ad, ör. `Control-M Prod`. |
| Automation API adresi | Temel adres, ör. `https://ctm-sunucu:8443/automation-api`. Kurallar bunun üstüne yol ekler. |
| Control-M sunucusu | İsteklerde `{ctm}` değişkeniyle kullanılır (ör. `/run/event/{ctm}/...`). |
| Kimlik türü | **Kullanıcı + şifre** (oturum açılır, token ~25 dk'da bir yenilenir) · **API anahtarı** (`x-api-key`) · **Yok**. |
| TLS doğrulama | Sertifika doğrulanır. Kendi imzalı sertifikada kapatmak yerine sertifikayı sunucuya güvenilir olarak ekleyin. |

### Genel API (REST)

| Alan | Açıklama |
|---|---|
| Temel adres | ör. `https://api.ornek.local/v1`. Kural kendi yolunu ekler. |
| Kimlik türü | **Yok** · **Bearer** (`Authorization: Bearer <token>`) · **API anahtarı** (başlık adı ve isteğe bağlı ön ek, ör. `X-API-Key`) · **Basic** (kullanıcı + şifre). |
| Sabit başlıklar | Satır başına `Ad: değer`. Buraya şifre ya da token yazılmaz; yazılırsa kayıt reddedilir (gizli değerler kimlik alanında şifreli saklanır). |
| Sağlık yoklaması yolu | İsteğe bağlı, ör. `/health`. "Bağlantıyı dene" bunu çağırır; hedef kapalıyken ya da devresi kesikken de düzenli yoklanır ve hedefin yeniden yanıt verip vermediği ekranda görünür (devreyi normale almak operatörün kararıdır). |

### Betik

Python ya da PowerShell betiği; her tetikte sunucuda ayrı süreçte çalışır. Ekleme, değiştirme ve çalıştırma **süper
yönetici şifresi** ister. Ayrıntılar: [04 · Betik hedefi](04_BETIK_HEDEFI.md).

### Ortak

- **Bağlantıyı dene** kaydetmeden önce hedefe gerçekten bağlanır (Control-M'de oturum açar, API'de sağlık yolunu
  çağırır).
- **Şifreler:** Ekrandan girilen şifre, token ve anahtarlar bu sunucuda Windows DPAPI ile şifreli saklanır; ekranda,
  veritabanında, logda ve denetim kaydında düz hâli yoktur. Düzenlerken şifre alanını boş bırakmak eskisini korur.
- **Silme:** Hedefe bağlı kural ya da gönderilmeyi bekleyen (lokal dahil) tetik varsa hedef silinmez; önce kurallar
  taşınır ve bekleyenler eritilir.

---

## Dizinler

**Dizinler ve kurallar → Dizin ekle**

| Alan | Açıklama |
|---|---|
| Dizin yolu | Tam yol ya da ağ yolu: `D:\ftp\gelen\muhasebe`, `\\dosyasunucu\paylasim\gelen`. Yalnız okuma yetkisi yeterlidir. Alt klasörler izlenmez; her klasör ayrı dizin olarak eklenir. |
| Görünen ad | ör. `Muhasebe gelen`. |
| Uzantılar | Bu dizinde ilgilenilen dosya türleri: `.csv, .txt`. Harf duyarsızdır; son noktadan sonraki kısım karşılaştırılır. **Boş = tüm dosyalar.** |
| Dizinde şu an duran dosyalar | **Temel al:** eklendiği an klasörde duran dosyalar işlenmiş sayılır, yalnız bundan sonra gelenler tetiklenir. **Tetikle:** duranlar da (kurala uyanlar) hedefe gönderilir. Zorunlu seçimdir. |

### Uzantı listesi ne işe yarar?

Uzantısı listede olmayan dosya **hiç izlenmez**: yazımının bitmesi beklenmez, kimliği çıkarılmaz, kayıt açılmaz. Bu
hem yükü azaltır hem de gürültüyü önler. Uzantısı listede olup hiçbir kurala uymayan dosya ise **"kurala uymayan dosya"**
olarak kaydedilir ve isteğe bağlı maillenir (yanlış adla gelmiş bir dosyayı yakalamak için). Liste boşsa `.ok`,
`.done`, `.log` gibi ilgisiz her dosya da "kurala uymayan" olarak düşer.

> **Dikkat:** Kuralın regex'i dosya adının tamamına uygulanır, uzantı dahil (bkz. [03 · Kurallar](03_KURALLAR.md)).
> Regex'te yazdığınız uzantı dizinin uzantı listesinde de olmalıdır. Liste `.csv` iken `\.txt` ile biten bir regex
> hiçbir zaman tetiklenmez.

### Dizin durumları

| Durum | Anlamı |
|---|---|
| Erişilebilir | Normal. |
| Yanıtsız | Listeleme `dizin_tarama_zaman_asimi_sn` (20 sn) içinde bitmedi; ağ takılmış olabilir. KRİTİK alarm. |
| Erişilemez | Bekleme planı (5, 10, 15 sn) bitti, dizin okunamıyor. KRİTİK alarm. 30 sn'de bir yeniden denenir; **Şimdi dene** ile hemen denenir. Erişim gelince arada gelen dosyalar yakalanır. |

---

## Kurallar

**Dizinler ve kurallar → (dizin) → Kural ekle.** Pencere üç bölümdür:

### 1 · Eşleşme

| Alan | Açıklama |
|---|---|
| Kural adı | ör. `fatura`. İstekte `{kural}` değişkeniyle kullanılabilir. |
| Sıra | Küçük sayı önce denenir (varsayılan 100). Bir dosya birden çok kurala uyabiliyorsa sıra belirleyicidir. |
| Dosya adı regex'i (tam eşleşme) | ör. `FATURA_(?P<tarih>\d{8})\.csv`. Yazarken **canlı deneme** çalışır: "Dizindeki gerçek adlar" sekmesi bu dizinde görülmüş son dosya adlarını, "Örnek adlarım" sekmesi kendi yazdığınız adları gösterir; her ad için eşleşip eşleşmediği ve yakalanan gruplar görünür. **Örnekten öner** seçili addan regex üretir. |
| Harf duyarsız | Varsayılan açık: `fatura_x.CSV` de eşleşir. |

### 2 · İstek

| Alan | Açıklama |
|---|---|
| Hedef | Tetiğin gideceği hedef. |
| Şablon | Control-M için **olay (koşul) ekle** ya da **iş sipariş et (run/order)**; API için **JSON gövdeyle POST**; **özel istek**. |
| Yöntem / yol / gövde | Yol hedefin temel adresine eklenir. Gövde JSON'dur; değişkenler `"{dosya_adi}"` gibi tırnak içinde yazılır. Değişken listesine tıklayınca imlecin olduğu yere eklenir. |
| Betiğe gidecek ek değerler | Betik hedefinde istek yerine bu alan vardır: satır başına `AD=değer` (değerde değişken kullanılabilir). |

**Kuru deneme** seçili dosya adıyla oluşacak isteği gönderMEDEN gösterir: tam adres, başlıklar (gizli değerler
maskeli) ve gövde. Gösterilen istek, sahada gönderilenle birebir aynıdır. **Gerçekten gönder** isteği hedefe gerçekten
yollar; yönetici yetkisi ve onay ister. Ayrıntılar ve örnekler: [03 · Kurallar](03_KURALLAR.md).

### 3 · Bildirim (mail)

Bu kurala bağlı alıcılar ve olaylar seçilir (boş = bu kural için mail yok). Seçilen adreslere **bu kuralın** olayları
(gönderilemedi, kalıcı hata, olası çift, anomali…) ve **dizininin kurala bağlı olmayan** olayları (hiçbir regex'e
uymayan dosya, dizine erişilemiyor) gider. Başka kuralın ya da başka dizinin olayı gitmez.

### Kuralı durdurma / silme

Kural satırındaki **Durdur**: *Kayıtlı durdur* (önerilen; gelen dosyalar lokalde bekler, açınca erit ile gider) ya da
onaylı *Kayıtsız durdur* (gelen dosyalar gönderilmez, kaydı tutulur). Dizin kartında **Kuralları durdur / aç** o
dizinin tüm kurallarını, sayfa başındaki **Tüm kuralları durdur / aç** hepsini etkiler. Silinen kuralın bekleyen
tetikleri tetikteki istek kopyasıyla gönderilmeye devam eder.

---

## Bildirimler (mail)

### SMTP

**Bildirimler (mail) → SMTP ayarları**

| Alan | Açıklama |
|---|---|
| Sunucu / Port | ör. `smtp.ornek.local` / `587`. |
| Güvenlik | `STARTTLS` (587) · `SSL` (465) · `YOK` (yalnız iç ağda, önerilmez). Sertifika doğrulanır. |
| Kullanıcı / Şifre | Şifre DPAPI ile şifreli saklanır. Kimliksiz iç röle için boş bırakılabilir. |
| Gönderen adres / ad | ör. `fwp@ornek.local` / `FileWatcherPro`. |

**Bağlantıyı dene** SMTP'ye bağlanıp oturum açar; **Test maili gönder** gerçek bir mail yollar.

### Bildirim kuralları

**Bildirimler → Kural ekle.** Bir olay bir bildirim kuralına şu üçü birlikte sağlanırsa uyar: olay seçilmiş, seviyesi
yeterli, (dizine bağlı olaylarda) dizin kapsamda.

| Alan | Açıklama |
|---|---|
| Alıcılar | Bir ya da birden çok adres. Aynı olay aynı alıcıya birden çok kuraldan gelse bile tek mail gider. |
| Olaylar | 31 olay türünden seçilir; "önerilen" işaretliler iyi bir başlangıçtır. Liste: [Yönetici veri sayfası](YONETICI_VERI_SAYFASI.md#8-olay-ve-alarm-kataloğu). |
| Seviye | En az BİLGİ / UYARI / KRİTİK. |
| Kapsam | Tüm dizinler ya da seçilen dizinler (kural penceresinden bağlananlarda ayrıca kural). |
| Gönderim | **Anında** ya da **özet** (`ozet_dk` içinde biriken olaylar tek mailde). |
| Tekrar | Aynı sorun sürerken en fazla `tekrar_dk`'da bir hatırlatılır. |
| Düzelince bildir | Sorun kapanınca "DÜZELDİ" maili. |

**Mail yağmuru koruması:** Anında bir kural 10 dakikada `bildirim_tasma_esigi` (10) maili aşarsa geçici olarak özete
geçer. Gönderilemeyen mail `bildirim_deneme_plani` (30 sn … 30 dk) ile yeniden denenir; olmazsa arayüzde "mail
gönderilemiyor" alarmı açılır (bu alarm maillenmez).

---

## Ayarlar

**Ayarlar** sayfası çalışma ayarlarını gruplar hâlinde gösterir (Motor, Tamamlanma, Kural, Teslim, Depolama,
Gözetmen, Loglama, İzleme, Bildirim). Her ayarın açıklaması, varsayılanı ve izin verilen aralığı sayfada yazar; değer
kaydedilince bileşenler yeniden başlatılmadan uygular. Sık ayarlananlar:

| Ayar | Varsayılan | Ne zaman değiştirilir |
|---|---|---|
| `sabitlik_W_sn` | 10 sn | Dosya bu süre boyunca boyut ve tarih değiştirmezse (ve başka süreçte açık değilse) tamamlanmış sayılır. Yavaş yüklemelerde artırın (`ftp_gozlem.py` önerisine göre). |
| `tarama_araligi_sn` | 2 sn | Dizin listeleme sıklığı. Çok büyük dizinlerde ağ yükünü azaltmak için artırılabilir. |
| `sla_hedef_sn` | 10 sn | Dosyanın hazır olmasından hedefin kabulüne kadar hedef süre; aşımlar kaydedilir. |
| `deneme_plani` | 5,10,15 | Hedef hatasında bekleme planı (sn); bitince lokal kayıt + alarm. |
| `cagri_timeout_sn` | 4 sn | Tek çağrının azami süresi. Yavaş hedeflerde artırın. |
| `otomatik_devre_esigi` | 5 | Art arda bu kadar hatada devre kesilir (0 = kapalı). |
| `erit_hizi` | 5/sn | Kademeli eritmede saniyede en fazla çağrı. Hedefin kaldırabileceği hıza göre. |
| `coklu_kural` | ilk | Dosya birden çok kurala uyarsa yalnız ilki mi, hepsi mi tetiklensin. |
| `bakim_gunu` / `bakim_saati` | Cumartesi 03:00 | Haftalık bakım zamanı. |

Tam liste: [Yönetici veri sayfası · varsayılan ayarlar](YONETICI_VERI_SAYFASI.md#7-varsayılan-ayarlar).

---

## Kullanıcılar ve roller

| Rol | Yapabilecekleri |
|---|---|
| **İzleyici** | Her sayfayı görür; hiçbir şeyi değiştiremez. |
| **Operatör** | İzleyici + operasyon: hedef / kural / dizin kuralları / tümünü durdurma ve açma, devreyi normale alma, kademeli erit, motoru durdurma / başlatma, bileşen başlat / durdur, bakımı başlatma, alarm onaylama, regex ve istek kuru denemesi, test maili, lokalden seçilenleri gönderme (süper yönetici kilidiyle). |
| **Yönetici** | Operatör + yapılandırma: hedef, dizin, kural, bildirim, SMTP ve ayar ekleme / değiştirme / silme, gerçek gönderim denemesi, lokalden silme (süper yönetici kilidiyle), asistan ayarları. |

**Süper yönetici kilidi** bir rol değil, ikinci bir şifredir: betik hedefiyle ilgili her işlem ve lokal kayıtta seçerek
gönder / sil, pencerede bu şifreyle kilit açılmasını ister. Kilit 10 dk ve yalnız o oturum için açılır; 5 hatalı
denemede 15 dk bekletilir.

Kullanıcılar sunucuda komut satırından yönetilir (şifre ekranda gizli sorulur):

```bat
py -3.11 araclar\kullanici.py ekle <ad> <IZLEYICI|OPERATOR|YONETICI>
py -3.11 araclar\kullanici.py sil <ad>
py -3.11 araclar\kullanici.py liste
```

Herkes kendi şifresini arayüzde sağ üstteki kilit simgesinden değiştirir. Şifreler en az 10 karakterdir ve
PBKDF2-SHA256 özetiyle saklanır. Unutulan şifre için kullanıcıyı silip yeniden ekleyin. Oturum 12 saat sürer; 5 hatalı
girişte hesap 60 sn kilitlenir.

---

## Arayüz dışındaki tek dosya: baslangic.json

`config\baslangic.json` veritabanı açılmadan önce bilinmesi gerekenleri tutar. Değiştirdikten sonra servisi yeniden
başlatın.

```json
{
  "veri_klasoru": "veri",
  "log_klasoru": "loglar",
  "kontrol_adres": "127.0.0.1",
  "kontrol_port": 8770,
  "eklentiler": [
    {"ad": "tarama",   "modul": "eklentiler.tarama.tarayici"},
    {"ad": "teslim",   "modul": "eklentiler.teslim.dagitici"},
    {"ad": "kontrol",  "modul": "eklentiler.kontrol.kontrol_api"},
    {"ad": "izleme",   "modul": "eklentiler.izleme.izleyici"},
    {"ad": "bildirim", "modul": "eklentiler.bildirim.bildirimci"},
    {"ad": "asistan",  "modul": "eklentiler.asistan.asistan"}
  ]
}
```

| Alan | Açıklama |
|---|---|
| `veri_klasoru`, `log_klasoru` | Göreli yollar uygulama klasörüne göredir. Başka bir diske almak için tam yol yazılabilir. |
| `kontrol_adres`, `kontrol_port` | Arayüzün dinlediği adres ve port. 8770 sunucuda başka program tarafından kullanılıyorsa portu değiştirin (`baslat.bat`'taki tarayıcı adresini de güncelleyin). |
| `kontrol_izinli_adlar` | *(isteğe bağlı)* Arayüze hangi ad(lar)la erişileceği, ör. `["fwp.ornek.local"]`. Arayüz ağa açılırsa gerekir; diğer adlarla gelen istekler reddedilir. |
| `eklentiler` | Çalışacak bileşenler. Asistan istenmiyorsa satırı kaldırın. |
