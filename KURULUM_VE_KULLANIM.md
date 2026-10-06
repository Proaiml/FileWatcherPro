# FileWatcherPro — Kurulum ve kullanım

FTP sunucusuna (Globalscape EFT) düşen dosyaları izler; her yeni dosya için kuralın hedefini tetikler: Control-M,
genel bir REST API ya da bu sunucuda çalışan bir betik (Python / PowerShell). EFT'ye dokunmaz, izlenen klasörleri
yalnızca okur.

Bu dosya kısa kılavuzdur. Ayrıntılı belgeler `docs\` klasöründedir: devreye alma, yapılandırma, kural yazma rehberi,
betik hedefi, günlük işletim, arıza davranışı, güvenlik, sorun giderme ve yönetici veri sayfası (bkz. `README.md`).

## 1. Gereksinimler

- Windows Server, Python 3.11 (64 bit). Paketler: `py -3.11 -m pip install -r requirements.txt`
- İsteğe bağlı yapay zekâ asistanı: `py -3.11 -m pip install -r requirements_asistan.txt` (PyTorch, ~1 GB disk;
  asistan süreci PyTorch yüklüyken ~400 MB bellek kullanır). PyTorch yoksa anomali takibi ve istatistik önerileri
  yine çalışır, yalnız model eğitilmez.
- Servis hesabı: izlenen paylaşımları OKUYABİLMELİ; `FileWatcherPro\veri`, `loglar`, `config` klasörlerine
  YAZABİLMELİ; "Hizmet olarak oturum aç" hakkı olmalı. LocalSystem kullanmayın.

## 2. Önce elle deneyin

1. `baslat.bat` → tarayıcıda `http://127.0.0.1:8770` açılır.
2. İlk giriş: `admin` / `admin`. Sağ üstteki kilit simgesinden şifreyi hemen değiştirin (değişene kadar uyarı alarmı
   açık kalır). Başka kullanıcılar: `py -3.11 araclar\kullanici.py ekle <ad> <IZLEYICI|OPERATOR|YONETICI>`
3. Ctrl+C ile kapatın (bekleyen tetikler 15 sn içinde gönderilir, kalanlar açılışta gider).

Gerçek Control-M olmadan akışı görmek için: `sahte_controlm_baslat.bat` (adres ekranda yazar).

## 3. Sunucuya servis olarak kurulum (NSSM)

**Kopyalama.** Geliştirme klasörünü olduğu gibi kopyalamayın: `veri\` içindeki şifreler DPAPI ile o makineye bağlı
şifrelidir (başka sunucuda çözülemez), deneme hedefleri / dizinleri ve kullanıcılar da taşınmamalı. Temiz paket:

```
py -3.11 araclar\prod_paketi.py
```

`dagitim\FileWatcherPro_<zaman>.zip` oluşur (kod + belgeler; veri, log, kullanıcı ve süper yönetici şifresi yok;
paketlemeden önce kodu derler, .bat satır sonlarını ve başlangıç ayarını denetler). Sunucuda:

1. Zip'i `C:\` altına açın (`C:\FileWatcherPro`), kopyanın sağlamlığını denetleyin:
   `py -3.11 C:\FileWatcherPro\araclar\prod_paketi.py --dogrula C:\FileWatcherPro`
2. Paketler: `py -3.11 -m pip install -r requirements.txt` (asistan için ayrıca `requirements_asistan.txt`; sunucuda
   PyTorch'un CPU sürümü yeterli, CUDA sürümü gereksiz yere birkaç GB'tır).
3. `betik_sifresi.bat` ile süper yönetici şifresini belirleyin (betik hedefi ve lokal kayıtta seçerek gönder / sil için).
4. Servis hesabına klasör izinlerini verin (bölüm 1), sonra aşağıdaki NSSM adımları. İlk girişte `admin` / `admin`
   şifresini hemen değiştirin; hedef, dizin, kural ve mail ayarları önyüzden yeniden girilir.

Yönetici komut isteminde (yollar kendi kurulumunuza göre):

```
nssm install FileWatcherPro "C:\Program Files\Python311\python.exe" servis\windows_servisi.py konsol
nssm set FileWatcherPro AppDirectory "C:\FileWatcherPro"
nssm set FileWatcherPro AppStopMethodConsole 60000
nssm set FileWatcherPro Start SERVICE_DELAYED_AUTO_START
nssm set FileWatcherPro ObjectName "ALAN\fwp_servis" "<servis hesabının şifresi>"
nssm set FileWatcherPro AppEnvironmentExtra PYTHONIOENCODING=utf-8
nssm set FileWatcherPro AppExit Default Restart
nssm start FileWatcherPro
```

- `python.exe`'yi doğrudan verin (`py` başlatıcısını değil). `AppStopMethodConsole` en az 60000 ms olmalı: kapanışta
  bekleyen tetiklere süre tanınır; kısa olursa NSSM süreci öldürür (kayıp olmaz ama açılışta yeniden denenir).
- `konsol` kipi bekçiyi de çalıştırır: çekirdek çökerse artan beklemeyle yeniden başlatır ve önyüzde uyarı açar.
- Kurulumdan sonra doğrulama (yönetici olarak): `py -3.11 araclar\servis_dogrula.py`
  (servis çalışıyor mu, eklentiler, önyüz, paylaşım erişimi; çekirdeği bir kez öldürüp geri geldiğini denetler).
- Önyüz yalnızca bu sunucudan açılır (127.0.0.1). Ağa açmak gerekirse `config\baslangic.json`'da `kontrol_adres`
  değiştirilir; arayüz HTTP'dir (TLS yok), giriş bilgileri ağda düz gider — önerilmez.

## 4. Canlıya geçmeden: test FTP ölçümü

Gerçek paylaşımda dosyaların nasıl göründüğünü ölçün (yalnızca okur, hiçbir şeye dokunmaz):

```
py -3.11 araclar\ftp_gozlem.py "\\sunucu\paylasim\gelen" --dk 30
```

Sonuç, sabitlik süresi (W) ve EFT'nin geçici adla yükleyip yüklemediği hakkında öneri verir. EFT'de "geçici adla
yükle, bitince yeniden adlandır" ayarı varsa açılması önerilir: kopan bir yüklemenin yarım dosyası dosya
sisteminden tamamlanmış dosyadan ayırt edilemez (EFT'ye dokunulmadığı için bilinen sınır).

## 5. Yapılandırma (önyüzden)

1. **Hedefler → Hedef ekle**: tür seçin.
   - *Control-M*: Automation API adresi, kullanıcı + şifre ya da API anahtarı. "Bağlantıyı dene" kaydetmeden dener.
   - *Genel API*: temel adres, kimlik (Bearer / API anahtarı / Basic), sabit başlıklar (şifre buraya yazılmaz).
   - *Betik*: bkz. bölüm 6. Şifreler bu sunucuda DPAPI ile şifreli saklanır; ekranda, veritabanında, logda düz yoktur.
2. **Dizinler ve kurallar → Dizin ekle**: yol (`\\sunucu\paylasim\...`), uzantılar, ilk kurulum (mevcut dosyalar
   temel alınsın mı, tetiklensin mi).
3. **Kural ekle**: dosya adı regex'i (canlı deneme ve "Örnekten öner" var), hedef, istek (ya da betiğe ek değerler).
   "Kuru deneme" göndermeden gösterir; "Gerçekten gönder" onay ister. **3 · Bildirim (mail)** bölümünde bu kurala
   bağlı alıcıları seçin: o kuralın hataları ve dizininin olayları (ör. hiçbir regex'e uymayan dosya) onlara gider.
4. **Bildirimler (mail)**: SMTP ayarı, test maili; genel bildirim kuralları (devre kesildi, disk doldu…).

## 6. Betik hedefi

- Önce süper yönetici şifresini sunucuda belirleyin: `betik_sifresi.bat` (çift tıklayın, şifreyi iki kez yazın).
  Önyüzden belirlenemez. Betik eklemek, değiştirmek, çalıştırmak, betik hedefli kural kaydetmek ve lokal kayıtları
  seçerek göndermek / silmek için penceredeki kilit bu şifreyle açılır (10 dk, yalnız o oturum; 5 hatalı denemede
  15 dk bekleme).
- Dosya bilgisi betiğe ortam değişkeni (`FWP_DOSYA_ADI`, `FWP_TAM_YOL`, `FWP_KIMLIK`, `FWP_G_<regex grubu>`,
  `FWP_P_<kuralın ek değeri>`, `FWP_SIR_<gizli değer>`) ve stdin JSON olarak gelir; betik metnine yazılmaz.
- **Hata sözleşmesi** — betik sade yazılır, hatayı yutmaz:

  | Çıkış | Sonuç | Sistem ne yapar |
  |---|---|---|
  | 0 | Başarılı | İletildi |
  | 10 | Kalıcı hata | Yeniden denenmez; lokale yazılır, KRİTİK alarm; düzeltip "Kademeli erit" |
  | diğer | Geçici hata | 5 / 10 / 15 sn sonra yeniden; olmazsa lokale + alarm |
  | süre doldu | Belirsiz | Betik ve alt süreçleri sonlandırılır; yeniden denenir, "olası çift" işaretlenir |

- Yeniden deneme, zaman aşımı, kayıt ve alarm sistemin işidir; betik içinde döngüyle yeniden denemeyin. Aynı tetik
  yeniden çalışabilir: karşı API destekliyorsa `FWP_KIMLIK`'i Idempotency-Key olarak gönderin.
- PowerShell'e sistem `$ErrorActionPreference='Stop'` ekler; `curl` yerine `curl.exe` yazın ve durum kodunu
  denetleyin (curl HTTP 500'de bile 0 ile çıkar). cmd / bat desteklenmez (dosya adındaki `&` komut çalıştırabilir).
- Penceredeki "Canlı çalıştır" betiği gerçekten çalıştırır (`FWP_DENEME=1`); kaydetmeden önce deneyin.

## 7. Gündelik işletim

- **Genel bakış**: sayılar, hedefler, alarmlar; her dizinin altında kuralları ve durumları (tek tık Durdur / Aç).
- **Durdurma**: hedef bazında ("Gönderimi durdur"), tüm hedefler (üst çubuk), tek kural, bir dizinin kuralları ya da
  tüm kurallar (Dizinler sayfası). *Kayıtlı* durdurmada gelen dosyalar lokalde bekler (kaybolmaz); *kayıtsız*
  onaylıdır ve dosyalar gönderilmez.
- **Hedef çöktüğünde**: yeniden deneme → lokal kayıt + alarm; art arda 5 hatada devre kesilir. Hedef düzelince
  "Devreyi normale al" → Lokal kayıt sayfasından "Kademeli erit" (geliş sırasıyla, hız sınırlı).
- **Lokalde bekleyenlerden yalnız bazılarını göndermek / silmek**: Lokal kayıt sayfasında kayıtları tek tek, "tümü"
  ya da filtreyle seçin. Her ikisi de süper yönetici şifresi ister (pencerede kilidi açın, 10 dk o oturuma).
  - *Seçilenleri gönder* (operatör): seçilenler hemen sıraya girer, seçilmeyenler beklemeye devam eder.
  - *Seçilenleri sil* (yönetici): gerekçe (en az 5 karakter) ve "gönderilmeyeceğini anladım" onayı gerekir. Önce
    `veri\lokal_silinen\tutanak_*.json` yazılır (kim, ne zaman, neden, her kaydın tam dökümü), lokal kayıt dosyası
    aynı klasöre arşivlenir, tetik "Elle silindi" olur; Gönderilemeyenler ve Denetim kaydında görünür. Silinen
    kayıt erit ya da yeniden başlatmayla gönderilmez; geri alınamaz (tutanak ve arşiv elle inceleme içindir).
- **Anomali takibi** (Yapay zekâ asistanı → Anomaliler): her kural için dosya boyutunun normal aralığı, teslim
  süresi ve günlük adet. Örn. hep 1–2 MB gelen fatura 3 KB gelirse ya da dün yarısı kadar dosya geldiyse kanıtlı
  öneri yazılır. Varsayılan yalnız öneridir; "Anomaliyi alarm olarak da aç" seçilirse UYARI alarmı açılır ve kuralın
  bağlı mail alıcılarına gider ("Dosyalarda anomali" olayı seçiliyse), normal dosya gelince kendiliğinden kapanır.
  Bir kuralın normali en az 20 dosyadan çıkar; günlük adet için en az 7 gün geçmiş gerekir. Tetik akışına karışmaz.
- **Dosya nerede takıldı?** Dosyalar sayfasında satıra tıklayın: zaman çizelgesi, denemeler, sonuç.
- **Bakım**: her Cumartesi 03:00 kendiliğinden (budama, indeks); hata olursa adım geri alınır, izleme durmaz.

## 8. Sorun giderme

- Loglar: `loglar\<bileşen>_<tarih>.log` (gün ya da 50 MB'ta döner, 10 gün saklanır). Olay satırları
  `EVENT | TÜR | ...` biçimindedir.
- Bileşen düşerse gözetmen yeniden başlatır; sürekli düşerse "elle müdahale" alarmı: Eklentiler sayfasından başlatın.
- PowerShell betiği "running scripts is disabled" / "not digitally signed" hatası verirse grup ilkesi (GPO)
  imzasız betiği engelliyordur (`-ExecutionPolicy Bypass` grup ilkesini aşmaz): betiği imzalatın ya da Python kullanın.
  Hata, betik penceresindeki "Canlı çalıştır" sonucunda ve dosyanın deneme geçmişinde görünür.
- Uçtan uca prova (geçici klasörde, canlıya dokunmaz; ~2 dk): `py -3.11 araclar\saha_provasi.py`
  Sonuç: `testler\_sonuc\saha_provasi.json` (kayıp / çift, log hataları, kaynak kullanımı, önyüz taraması).
- Otomatik testler: `py -3.11 -m pytest testler -q`
