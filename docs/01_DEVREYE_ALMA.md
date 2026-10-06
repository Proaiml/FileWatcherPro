# 01 · Devreye alma

Bu belge FileWatcherPro'yu bir sunucuya kurup canlıya almayı adım adım anlatır. Sıra önemlidir: önce planlama ve
ölçüm, sonra kurulum, en son yapılandırma ve doğrulama.

- [1. Planlama](#1-planlama)
- [2. Canlıdan önce: klasörü ölçün](#2-canlıdan-önce-klasörü-ölçün)
- [3. Kurulum dosyalarını hazırlama](#3-kurulum-dosyalarını-hazırlama)
- [4. Sunucuya kurulum](#4-sunucuya-kurulum)
- [5. Windows servisi olarak çalıştırma](#5-windows-servisi-olarak-çalıştırma)
- [6. Doğrulama](#6-doğrulama)
- [7. Canlıya geçiş kontrol listesi](#7-canlıya-geçiş-kontrol-listesi)
- [8. Sürüm yükseltme](#8-sürüm-yükseltme)
- [9. Kaldırma](#9-kaldırma)

---

## 1. Planlama

### Sunucu

| Gereksinim | Açıklama |
|---|---|
| İşletim sistemi | Windows (Server ya da masaüstü). Python 3.11'in desteklediği bir sürüm olmalı. |
| Python | **3.11, 64 bit**, "tüm kullanıcılar için" kurulmuş (servis hesabı da çalıştırabilsin). `py` başlatıcısı kurulumla gelir. |
| Bellek | Asistansız: tüm bileşenler toplam ~200–250 MB (bileşen başına 30–55 MB). Asistan PyTorch ile çalışırsa +~400 MB. |
| Disk | Uygulama ~2 MB. Veritabanları küçük kalır (geçmiş ve hata kayıtları sınırlıdır); lokal kayıt yalnız hedef çalışmazken büyür. Log klasörü 10 gün tutulur. Veri ve log diskinde en az 5 GB boş alan önerilir (altına düşünce alarm). |
| Ağ | İzlenen paylaşımlara (SMB, 445) ve hedeflere (Control-M / API, genelde HTTPS) erişim; mail için SMTP. Gelen bağlantı gerekmez. |

Aynı sunucuda FTP sunucusunun kendisi de çalışabilir; FileWatcherPro FTP sunucusuyla entegre olmaz, yalnız onun yazdığı
klasörleri okur.

### Servis hesabı

FileWatcherPro'yu **LocalSystem ile değil**, ayrı bir hesapla çalıştırın (yerel ya da alan hesabı, ör.
`ALAN\fwp_servis`). Bu hesabın ihtiyaçları:

| İzin | Nerede | Neden |
|---|---|---|
| **Okuma** (Listele + Oku) | İzlenen her paylaşım / klasör (paylaşım izni ve NTFS izni) | Dosyaları görmek ve kimliklerini çıkarmak. Yazma **gerekmez**; FileWatcherPro izlenen klasörlere hiçbir şey yazmaz, dosya taşımaz, silmez. |
| **Değiştirme** | `FileWatcherPro\veri`, `FileWatcherPro\loglar`, `FileWatcherPro\config` | Veritabanları, lokal kayıt, loglar; arayüzden şifre değişince kullanıcı dosyası. |
| **Okuma + Yürütme** | `FileWatcherPro` klasörünün geri kalanı ve Python kurulum klasörü | Kodu çalıştırmak. |
| **Hizmet olarak oturum aç** | Yerel güvenlik ilkesi ya da grup ilkesi | Servis olarak başlayabilmek. |

Yönetici hakkı gerekmez. Paylaşım başka sunucudaysa alan hesabı kullanın; yerel hesap ağ paylaşımına erişemez.

### Arayüz erişimi

Web arayüzü varsayılan olarak yalnız sunucunun kendisinden açılır: `http://127.0.0.1:8770`. Yönetim için sunucuya uzak
masaüstüyle bağlanılır. Arayüzü ağa açmak mümkündür ama önerilmez (bkz. [07 · Güvenlik](07_GUVENLIK.md)).

### Yapay zekâ asistanı (isteğe bağlı)

Asistan yerelde çalışır ve dışarı veri göndermez. Anomali takibi ve istatistik önerileri ek paket gerektirmez. Kendi
modelini eğitmesi için PyTorch gerekir (CPU sürümü yeterli). İstemiyorsanız `config\baslangic.json`'daki
`eklentiler` listesinden `asistan` satırını kaldırın.

---

## 2. Canlıdan önce: klasörü ölçün

Dosyaların gerçek paylaşımda nasıl göründüğünü ölçün. Araç yalnız okur, hiçbir şeye dokunmaz:

```bat
py -3.11 araclar\ftp_gozlem.py "\\dosyasunucu\paylasim\gelen" --dk 30
```

Gözlem bitince şunları raporlar:

- Dosyaların yazımı ne kadar sürüyor, yazılırken boyut ve tarih nasıl değişiyor → **sabitlik süresi** (`sabitlik_W_sn`)
  önerisi.
- FTP sunucusu dosyayı geçici adla (`.filepart`, `.part` …) yükleyip sonra yeniden adlandırıyor mu?

> **Öneri:** FTP sunucunuzda "geçici adla yükle, bitince yeniden adlandır" seçeneği varsa açın. Bağlantısı kopan bir
> yüklemenin yarım dosyası, dosya sisteminden bakıldığında tamamlanmış dosyadan ayırt edilemez. Geçici adla yüklemede
> bu sorun hiç yaşanmaz; FileWatcherPro bu yöntemi tam destekler.

---

## 3. Kurulum dosyalarını hazırlama

Depoyu indirin (`git clone` ya da GitHub'dan ZIP). Çalışan bir kurulumu başka sunucuya taşıyorsanız **klasörü olduğu
gibi kopyalamayın**: `veri\` içindeki şifreler o makineye bağlı şifrelidir (başka sunucuda çözülemez) ve deneme
hedefleri / dizinleri canlıya taşınmamalıdır. Temiz paket üretin:

```bat
py -3.11 araclar\prod_paketi.py
```

`dagitim\FileWatcherPro_<zaman>.zip` oluşur. İçinde kod ve belgeler vardır; veri, log, kullanıcı dosyası ve süper
yönetici şifresi **yoktur**. Araç paketlemeden önce kodun derlendiğini, `.bat` dosyalarının satır sonlarını ve başlangıç
ayarını denetler; her dosyanın SHA-256 özetini `MANIFEST_SHA256.txt`'e yazar.

### İnternetsiz sunucu

Paketleri internete çıkan bir makinede indirip taşıyın:

```bat
py -3.11 -m pip download -r requirements.txt -d paketler
```

Sunucuda:

```bat
py -3.11 -m pip install --no-index --find-links paketler -r requirements.txt
```

PyTorch için CPU sürümünü indirin (CUDA sürümü gereksiz yere birkaç GB'tır):

```bat
py -3.11 -m pip download torch numpy --index-url https://download.pytorch.org/whl/cpu -d paketler_asistan
```

---

## 4. Sunucuya kurulum

1. Dosyaları kalıcı bir yere açın, ör. `C:\FileWatcherPro`. Paketten açtıysanız kopyanın sağlamlığını denetleyin:

   ```bat
   py -3.11 C:\FileWatcherPro\araclar\prod_paketi.py --dogrula C:\FileWatcherPro
   ```

2. Paketleri kurun:

   ```bat
   cd /d C:\FileWatcherPro
   py -3.11 -m pip install -r requirements.txt
   ```

   Asistanın model eğitimi isteniyorsa ayrıca: `py -3.11 -m pip install -r requirements_asistan.txt` (CPU sürümü için
   yukarıdaki `--index-url` seçeneğini kullanın).

3. Servis hesabına klasör izinlerini verin ([bölüm 1](#servis-hesabı)).

4. **İlk açılış (elle):** `baslat.bat`'a çift tıklayın. Tarayıcıda `http://127.0.0.1:8770` açılır.
   - İlk giriş `admin` / `admin`. Sağ üstteki kilit simgesinden şifreyi hemen değiştirin; değişene kadar
     "varsayılan şifre" uyarısı açık kalır. Şifre en az 10 karakter olmalıdır.
   - Diğer kullanıcıları ekleyin (şifre ekranda gizli sorulur):

     ```bat
     py -3.11 araclar\kullanici.py ekle ayse OPERATOR
     py -3.11 araclar\kullanici.py ekle izleme IZLEYICI
     py -3.11 araclar\kullanici.py liste
     ```

   - Pencerede Ctrl+C ile kapatın (bekleyen tetiklere 15 sn verilir, kalanlar açılışta gider).

5. **Süper yönetici şifresi:** `betik_sifresi.bat`'a çift tıklayın, şifreyi iki kez yazın. Bu şifre betik hedefi
   eklemek / değiştirmek / çalıştırmak ve lokalde bekleyen kayıtları seçerek göndermek / silmek için arayüzde ayrıca
   sorulur. Arayüzden belirlenemez; yalnız sunucuda bu araçla belirlenir. Dosyaya şifrenin kendisi değil özeti yazılır.

6. Yapılandırmayı arayüzden yapın: hedefler, dizinler, kurallar, mail (bkz. [02 · Yapılandırma](02_YAPILANDIRMA.md)).
   Elle açılmış kopya açıkken yapılandırabilir, sonra kapatıp servise geçebilirsiniz; ayarlar `veri\` içinde kalır.

---

## 5. Windows servisi olarak çalıştırma

Önerilen yol **NSSM**'dir (Non-Sucking Service Manager; resmi sitesinden indirin). Yönetici komut isteminde, yolları
kendi kurulumunuza göre düzenleyerek:

```bat
nssm install FileWatcherPro "C:\Program Files\Python311\python.exe" servis\windows_servisi.py konsol
nssm set FileWatcherPro AppDirectory "C:\FileWatcherPro"
nssm set FileWatcherPro DisplayName "FileWatcherPro"
nssm set FileWatcherPro Description "Klasörlere gelen dosyalar için Control-M / API / betik tetikler"
nssm set FileWatcherPro Start SERVICE_DELAYED_AUTO_START
nssm set FileWatcherPro ObjectName "ALAN\fwp_servis" "<servis hesabının şifresi>"
nssm set FileWatcherPro AppEnvironmentExtra PYTHONIOENCODING=utf-8
nssm set FileWatcherPro AppStopMethodConsole 60000
nssm set FileWatcherPro AppExit Default Restart
nssm start FileWatcherPro
```

| Ayar | Neden |
|---|---|
| `python.exe` doğrudan | `py` başlatıcısı servis olarak araya bir süreç daha ekler; durdurma sinyali doğru iletilmez. |
| `servis\windows_servisi.py konsol` | Bekçi kipi: çekirdek çökerse artan beklemeyle (1, 2, 5, 10, 30 sn) yeniden başlatır, arayüzde "çekirdek beklenmedik kapandı" uyarısı açar. |
| `AppStopMethodConsole 60000` | Servis durdurulurken bekleyen tetiklere süre tanınır (varsayılan 15 sn + çağrı süresi). Kısa olursa NSSM süreci öldürür; tetik kaybolmaz ama açılışta yeniden denenir. |
| `SERVICE_DELAYED_AUTO_START` | Açılışta ağ ve paylaşımlar hazır olduktan sonra başlasın. |
| `AppExit Default Restart` | Servis sürecinin kendisi düşerse ikinci katman. |

> **Alternatif:** `servis_kur.bat` (yönetici olarak) pywin32 ile yerleşik servis kurar ve Windows kurtarma ayarını
> yapar. Bu yolla kurulan servis LocalSystem ile başlar; hesabı `services.msc`'den servis hesabıyla değiştirin.
> Kaldırma: `servis_kaldir.bat`.

Aynı veri klasörü için ikinci bir kopya çalışmaz: servis açıkken `baslat.bat` "zaten çalışıyor" der ve kapanır (çıkış
kodu 3). Bu çökme sayılmaz.

---

## 6. Doğrulama

Servisi kurduktan sonra yönetici komut isteminde:

```bat
py -3.11 araclar\servis_dogrula.py
```

Denetlenenler: servis kayıtlı ve çalışıyor (başlangıç türü, hesap) · çekirdek ve bileşenler çalışıyor, nabızlar taze ·
arayüz yanıt veriyor · izlenen dizinlere servis hesabıyla erişilebiliyor · çekirdek bir kez öldürülür ve servisin onu
geri getirdiği denetlenir (bu adımı atlamak için `--oldurme-yok`). Sonuç `GEÇTİ / KALDI` olarak yazılır; ayar
değiştirilmez. Öldürme adımının açtığı "çekirdek yeniden başlatıldı" uyarısını arayüzden onaylayın.

Ardından bir deneme dosyasıyla uçtan uca deneyin: kurala uyan bir dosya bırakın, **Dosyalar** sayfasında satıra
tıklayıp zaman çizelgesinde "görüldü → tamamlandı → hedef kabul etti" adımlarını görün.

---

## 7. Canlıya geçiş kontrol listesi

- [ ] Python 3.11 tüm kullanıcılar için kurulu, `pip install -r requirements.txt` tamam
- [ ] Servis hesabı LocalSystem değil; paylaşımlara okuma, `veri` / `loglar` / `config`'e yazma izni var
- [ ] `ftp_gozlem.py` ile klasör ölçüldü; `sabitlik_W_sn` sonuca göre ayarlandı
- [ ] `admin` şifresi değiştirildi; gereken kullanıcılar uygun rollerle eklendi
- [ ] Süper yönetici şifresi `betik_sifresi.bat` ile belirlendi (betik ya da lokal seçerek işlem kullanılacaksa)
- [ ] Her hedef için "Bağlantıyı dene" başarılı
- [ ] Her dizin "Erişilebilir"; uzantı listesi girildi; ilk kurulum seçimi (temel al / tetikle) bilinçli yapıldı
- [ ] Her kural canlı denemede gerçek adlarla doğru eşleşiyor; "Kuru deneme" isteği beklenen gibi
- [ ] SMTP ayarı yapıldı, test maili alındı; en az bir bildirim kuralı (devre kesildi, dizine erişilemiyor, disk) var
- [ ] Servis NSSM ile kuruldu, `servis_dogrula.py` GEÇTİ
- [ ] Bir deneme dosyası hedefe ulaştı; Control-M / API tarafında iş başladı
- [ ] Hedef geçici olarak kapatıldığında dosyanın lokale düştüğü ve erit ile gittiği bir kez görüldü (isteğe bağlı ama önerilir)

---

## 8. Sürüm yükseltme

1. Arayüzden ya da `nssm stop FileWatcherPro` ile durdurun. Bekleyen tetiklere süre tanınır; bitmeyenler
   veritabanında kalır.
2. Yedek alın: `veri\` ve `config\` klasörlerini kopyalayın.
3. Yeni sürümün dosyalarını üzerine kopyalayın. **Dokunulmayacaklar:** `veri\`, `loglar\`,
   `config\kullanicilar.json`, `config\betik_sifresi.json`; `config\baslangic.json`'ı değiştirdiyseniz kendi
   kopyanızı koruyun.
4. `py -3.11 -m pip install -r requirements.txt`
5. `nssm start FileWatcherPro`, ardından `py -3.11 araclar\servis_dogrula.py`.

Veritabanında yeni sürümün ihtiyaç duyduğu sütunlar açılışta kendiliğinden eklenir. Sürüm notunda ayrıca bir adım
yazıyorsa onu da uygulayın.

---

## 9. Kaldırma

```bat
nssm stop FileWatcherPro
nssm remove FileWatcherPro confirm
```

Ardından klasörü silin. Kayıtları saklamak istiyorsanız önce `veri\` (veritabanları, lokal kayıt, silme tutanakları) ve
`loglar\` klasörlerini arşivleyin. Lokalde bekleyen tetik varsa kaldırmadan önce eritin ya da kaydını alın.
