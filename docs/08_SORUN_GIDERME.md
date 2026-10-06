# 08 · Sorun giderme

## Önce nereye bakılır

1. **Genel bakış** üst çubuğu ve **Alarmlar**: sorun çoğu zaman burada adıyla yazar.
2. **Dosyalar** → dosyanın satırı → zaman çizelgesi: dosya görüldü mü, tamamlandı mı, hangi kurala uydu, hedef ne
   yanıt verdi.
3. **Gönderilemeyenler**: gönderilemeyen ya da kurala uymayan dosyanın sebebi.
4. **Eklentiler**: bileşenler çalışıyor mu, nabızlar taze mi.
5. **Loglar** (`loglar\`).

## Loglar

| Dosya | İçerik |
|---|---|
| `loglar\<bileşen>_<YYYY-AA-GG>.log` | Bileşen başına günlük log: `cekirdek`, `tarama`, `teslim`, `kontrol`, `izleme`, `bildirim`, `asistan`, `servis`. Gün değişince ya da 50 MB'ta yeni dosya; 10 gün saklanır. |
| `loglar\<bileşen>_konsol.log` | Bileşenin standart çıktısı (normalde boş; beklenmedik çökme izi burada olur). |

Olay satırları `EVENT | TÜR | alan=değer …` biçimindedir ve aranabilir:

```
2026-10-01 09:15:42.118 | INFO     | teslim   | ... - EVENT | ILETILDI | ad=FATURA_20261001.csv hedef=Control-M Prod sure_ms=180 deneme=1
```

```bat
findstr /C:"EVENT | ILETILDI" loglar\teslim_2026-10-01.log
findstr /C:"FATURA_20261001.csv" loglar\*.log
findstr /C:"| ERROR" /C:"| CRITICAL" loglar\*.log
```

Sık olay türleri: `ILETILDI`, `TEKRAR`, `LOKALE_YAZILDI`, `DEVRE_KESILDI`, `ESLESMEDI`, `KAYITSIZ_KAPALI`,
`LOKALDEN_GERI_YUKLENDI`, `LOKAL_SILINDI`, `EKLENTI_BASLADI`, `KURTARMA`, `BAKIM`.

---

## Belirti → neden → çözüm

### Dosya geldi ama hiç görünmüyor (Dosyalar listesinde yok)

| Neden | Nasıl anlaşılır | Çözüm |
|---|---|---|
| Uzantısı dizinin uzantı listesinde yok | Dizin kartında "uzantılar" | Uzantıyı ekleyin |
| Dizine erişilemiyor | Dizin durumu "Erişilemez / Yanıtsız", alarm | Servis hesabının paylaşım iznini, ağı kontrol edin; **Şimdi dene** |
| Motor durdurulmuş | Üst çubukta motor anahtarı kapalı | Motoru başlatın; arada gelenler yakalanır |
| Dosya bir alt klasörde | — | Alt klasörler izlenmez; alt klasörü ayrı dizin olarak ekleyin |
| Dosya dizin eklenirken zaten vardı ve "Temel al" seçildi | Dosyalar'da "ilk kurulumda vardı" etiketi | Bilinçli bir seçimdir; gerekiyorsa dosyayı kaldırıp yeniden bırakın |
| Dosya 2 sn'den kısa sürede gelip silindi | — | Listeleme tabanlı izlemenin sınırı (bkz. [06](06_ARIZA_DAVRANISI.md#bilinen-sınırlar)) |

### Dosya "yükleniyor"da kalıyor

| Neden | Çözüm |
|---|---|
| Dosya hâlâ yazılıyor ya da başka bir süreç dosyayı açık tutuyor | Normaldir; yazım bitince ilerler. Açık tutan süreci bulun (FTP sunucusu, virüs tarayıcı, yedekleme). |
| Boyut / tarih düzenli aralıkla değişiyor (ör. yavaş yükleme) | `sabitlik_W_sn` dolmadan değişiklik oluyordur; yükleme bitince ilerler. |
| 30 dk'yı aştı | "Yükleme askıda" uyarısı açılır. Yükleme gerçekten kopmuşsa gönderen taraf dosyayı yeniden göndermelidir. |

### Dosya "kurala uymayan" görünüyor

Regex dosya adına uymuyor. **Kuralı düzenle** → canlı denemede "Dizindeki gerçek adlar" sekmesinde o adı seçin; neden
uymadığı görünür. En sık sebep regex'te uzantının olmaması (`FATURA_\d{8}` yerine `FATURA_\d{8}\.csv`). Bkz.
[03 · Kurallar](03_KURALLAR.md#sık-yapılan-hatalar).

### Tetiklendi ama hedefte iş başlamadı

1. Zaman çizelgesinde hedefin yanıtına bakın. 2xx döndüyse istek hedefe ulaşmıştır; sorun hedef tarafındadır.
2. Kuralda **Kuru deneme** ile giden isteği görün: Control-M koşul / klasör / iş adı, API yolu doğru mu?
3. Control-M'de koşul (olay) ekleme kullanılıyorsa işin beklediği koşul adı ve tarih (`ODAT`) eşleşiyor mu?

### Hedef 401 / 403 veriyor

| Neden | Çözüm |
|---|---|
| Kullanıcı / şifre / token yanlış ya da süresi dolmuş | Hedefi düzenleyip yeniden girin; **Bağlantıyı dene** |
| Veritabanı başka makineden taşındı | DPAPI ile şifrelenmiş değerler yeni makinede çözülemez; tüm hedef ve SMTP şifrelerini yeniden girin |
| Hesabın yetkisi yok | Hedef sistemde yetkiyi verin, sonra lokaldekileri eritin |

### Lokal kayıtta tetik birikiyor

| Neden | Çözüm |
|---|---|
| Hedefin devresi kesik | Hedef düzeldiyse **Devreyi normale al**, ardından **Kademeli erit** |
| Hedef ya da kural "kayıtlı durdur"da | Açın; birikenleri eritin |
| Kalıcı hata (4xx) | Kuralı / hedefi düzeltin, sonra erit |
| Bazıları hiç gitmemeli | Seçerek silin (süper yönetici, gerekçeli, tutanaklı) |

### Erit durdu

Erit sırasında bir kayıt yine hata verince erit durur ve "kademeli erit durdu" alarmı açılır. Hatanın sebebini
giderip eriti yeniden başlatın.

### Mail gelmiyor

| Kontrol | Nasıl |
|---|---|
| SMTP çalışıyor mu | Bildirimler → **Bağlantıyı dene**, **Test maili gönder** |
| Olay bir kurala uyuyor mu | Kuralda olay seçili mi, seviye yeterli mi, dizin kapsamda mı |
| Tekrar sınırı | Aynı sorun sürerken en fazla `tekrar_dk`'da bir hatırlatılır |
| Mail yağmuru koruması | Kural 10 dk'da 10 maili aştıysa geçici olarak özete geçmiştir |
| Gönderim geçmişi | Bildirimler → "Gönderim geçmişi (son 100)"; Alarmlar'da "mail gitti" bilgisi |
| Spam / alıcı sunucusu | Gönderen adresin alıcı sistemde engellenmediğini kontrol edin |

### Arayüz açılmıyor

| Belirti | Neden / çözüm |
|---|---|
| Bağlantı reddedildi | Servis çalışmıyor (`nssm status FileWatcherPro`, `services.msc`) ya da port farklı (`config\baslangic.json`) |
| "Bu adreste FileWatcherPro çalışmıyor" | Port başka bir programa ait; `kontrol_port`'u değiştirin |
| HTTP 421 | Arayüze izinli olmayan bir adla erişiliyor; `kontrol_izinli_adlar`'a ekleyin |
| `baslat.bat` "zaten çalışıyor" diyor | Servis açık; aynı veri klasörü için ikinci kopya açılmaz (çıkış kodu 3). Servisi kullanın. |

### Bileşen "elle müdahale bekliyor"

Bileşen art arda 5 kez düştü. `loglar\<bileşen>_*.log` ve `loglar\<bileşen>_konsol.log`'da son hatayı bulun, sebebi
giderin (eksik paket, izin, disk), **Eklentiler → Başlat**.

### Betik çalışmıyor

| Belirti | Çözüm |
|---|---|
| "running scripts is disabled" / "not digitally signed" | Grup ilkesi imzasız PowerShell betiklerini engelliyor; betiği imzalayın ya da Python kullanın |
| Hep "belirsiz" sonuç | Betik zaman aşımına uğruyor; uzun beklemeyi betikten çıkarın ya da zaman aşımını artırın |
| Hata olduğu hâlde "başarılı" | Betik hatayı yutuyor (`except: pass`); bkz. [04 · Betik hedefi](04_BETIK_HEDEFI.md#yazarken-dikkat) |
| "Süper yönetici kilidi kapalı" | Pencerede kilidi açın; şifre tanımlı değilse sunucuda `betik_sifresi.bat` |

### Şifre sorunları

| Durum | Çözüm |
|---|---|
| Kullanıcı şifresini unuttu | Sunucuda `py -3.11 araclar\kullanici.py sil <ad>` ve `... ekle <ad> <ROL>` |
| Hiç yönetici kalmadı | `py -3.11 araclar\kullanici.py ekle <ad> YONETICI` (sunucuda) |
| 5 hatalı giriş | 60 sn bekleyin |
| Süper yönetici şifresi unutuldu | Sunucuda `betik_sifresi.bat` ile yeniden belirleyin |

### Alarm: veritabanı büyüdü / çözülmemiş kayıt sınırı

Çözülmemiş gönderilemeyen kayıtlar asla silinmez; çok birikirse sınır alarmı açılır. Gönderilemeyenler'i inceleyip
çözün (erit, seçerek sil). Geçmiş sınırları **Ayarlar → Depolama** altındadır.

---

## Tanı araçları

| Araç | Ne yapar |
|---|---|
| `py -3.11 araclar\servis_dogrula.py` | Servis, bileşenler, arayüz, dizin erişimi; çekirdeği öldürüp geri gelişi (yönetici olarak) |
| `py -3.11 araclar\ftp_gozlem.py "<klasör>" --dk 30` | Klasördeki yazım davranışını yalnız okuyarak ölçer; sabitlik süresi ve geçici ad önerisi |
| `py -3.11 araclar\saha_provasi.py` | Geçici klasörde, sahte Control-M / API / mail ile uçtan uca prova (~2 dk). Canlı kuruluma dokunmaz. Rapor: `testler\_sonuc\saha_provasi.json` |
| `py -3.11 araclar\performans_olcum.py` | Veritabanı sorguları, listeleme ve boşta kaynak kullanımı ölçümü |
| `py -3.11 araclar\prod_paketi.py --dogrula <klasör>` | Kurulum dosyalarının paketteki özetlerle aynı olduğunu denetler |

## Yardım isterken eklenecekler

- Sorunun saati ve ilgili dosya adı
- `loglar\` altındaki o günün logları (gizli değer içermez)
- Alarmlar ve ilgili dosyanın zaman çizelgesinin ekran görüntüsü
- Son yapılandırma değişiklikleri (Denetim kaydı)
