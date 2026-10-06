# 07 · Güvenlik

## Özet

| Alan | Uygulama |
|---|---|
| İzlenen klasörler | Yalnız okunur. FileWatcherPro izlenen klasörlere yazmaz, dosya taşımaz, silmez, kilitlemez. |
| Arayüz erişimi | Varsayılan yalnız `127.0.0.1`. Ağa açılırsa Host denetimi ve izinli ad listesi; HTTP olduğu için önerilmez. |
| Giriş | Kullanıcı + şifre; roller (İzleyici / Operatör / Yönetici); betik ve lokal silme için ikinci şifre. |
| Şifre saklama | Arayüz şifreleri: PBKDF2-SHA256 (200 000 tur, rastgele tuz). Hedef / SMTP / betik gizli değerleri: Windows DPAPI ile şifreli. |
| Denetim | Her yapılandırma değişikliği kim, ne zaman, eski ve yeni değerle (gizli değerler maskeli). |
| Betik yalıtımı | Ayrı süreç, temiz ortam, veri metne değil ortama / stdin'e, zaman aşımında süreç ağacı sonlandırma. |
| Dış bağlantı | Yalnız tanımladığınız hedefler, SMTP ve izlenen paylaşımlar. Telemetri yok; yapay zekâ asistanı yereldir, dışarı veri göndermez. |

---

## Arayüz

- **Adres:** `config\baslangic.json` → `kontrol_adres: "127.0.0.1"`. Yönetim için sunucuya uzak masaüstüyle
  bağlanılır. Arayüz şifrelemesiz HTTP'dir; ağa açılırsa (`0.0.0.0` ya da sunucu IP'si) giriş bilgileri ağda düz gider.
  Gerekiyorsa önüne TLS sonlandıran bir ters vekil koyun ve `kontrol_izinli_adlar`'a erişilecek adı yazın. Ağa
  açıldığında loga uyarı düşer.
- **DNS rebinding koruması:** `Host` başlığı bu sunucuyu göstermeyen istekler reddedilir (421). Değiştiren isteklerde
  `Origin` başka bir siteyi gösteriyorsa reddedilir.
- **CSRF:** Oturum çerezi `HttpOnly; SameSite=Strict`. GET dışındaki her API isteği `X-FWP: 1` başlığı ister; başka
  bir sitenin formu bu başlığı ekleyemez.
- **İçerik güvenlik ilkesi (CSP):** Arayüz yalnız kendi kaynaklarından betik ve stil yükler; dış kaynak yoktur.
- **Oturum:** 12 saat. Şifre değişince o kullanıcının diğer oturumları düşer.
- **Kaba kuvvet:** Aynı kullanıcıda 5 hatalı girişte 60 sn kilit.
- **İstek sınırları:** Gövde boyutu ve okuma süresi sınırlıdır (yavaş bağlantıyla kaynak tüketme önlenir).

## Kullanıcılar ve roller

| Rol | Kapsam |
|---|---|
| İzleyici | Yalnız görür. |
| Operatör | Operasyon: durdur / aç, erit, devreyi normale al, bileşen ve motor, bakım, alarm onayı, kuru deneme, test maili. |
| Yönetici | Yapılandırma: hedef, dizin, kural, bildirim, ayar; gerçek gönderim denemesi. |
| Süper yönetici kilidi | Rol değil, ikinci şifre: betik hedefi ve lokalde seçerek gönder / sil. 10 dk, yalnız o oturum; 5 hatalı denemede 15 dk bekleme. |

- Varsayılan `admin` / `admin` hesabı yalnız ilk kurulum içindir; şifre değişene kadar uyarı alarmı açık kalır.
- Şifreler en az 10 karakterdir. Kullanıcı ekleme / silme yalnız sunucuda komut satırından yapılır
  (`araclar\kullanici.py`); şifre ekranda gizli sorulur, hiçbir yere düz yazılmaz.
- Süper yönetici şifresi yalnız sunucuda `betik_sifresi.bat` ile belirlenir; arayüz kullanıcılarının şifresiyle aynı
  olamaz. `config\betik_sifresi.json`'a yalnız özeti yazılır.

## Gizli değerler (şifre, token, API anahtarı)

- Arayüzden girilen hedef, SMTP ve betik gizli değerleri **Windows DPAPI** ile şifrelenip veritabanında saklanır.
  Ekranda, veritabanında, logda, denetim kaydında ve kuru deneme çıktısında düz hâli yoktur; düzenlerken boş bırakılan
  alan eskisini korur.
- Şifreleme **makine kapsamlıdır**: değerler yalnız bu sunucuda çözülebilir; veritabanı başka makineye kopyalanırsa
  çözülemez (yeniden girilmeleri gerekir). Aynı sunucuda çalışan yetkili bir süreç ise çözebilir. Bu yüzden:
  - `FileWatcherPro\veri` klasörüne yalnız servis hesabı ve sunucu yöneticileri erişebilmelidir.
  - Sunucuya oturum açabilenleri sınırlı tutun.
- Gelişmiş seçenek: gizli değer ekrana girilmek yerine referansla verilebilir: `env:DEGISKEN` (servis ortam
  değişkeni) ya da `wincred:Hedef` (Windows Kimlik Bilgisi Yöneticisi; servis hesabıyla kaydedilmiş olmalı).
- Genel API hedefinin "sabit başlıklar" alanına şifre / token yazılırsa kayıt reddedilir; gizli değer kimlik alanına
  girilir.
- Betiğe gizli değerler yalnız `FWP_SIR_<AD>` ortam değişkeni olarak verilir; stdin'e ve loga yazılmaz, betik çıktısında
  `***` ile maskelenir.

## Betik hedefi

- Betik her tetikte ayrı süreçte çalışır; servisin ortam değişkenleri betiğe geçmez (yalnız Windows'un çalışması için
  gerekenler ve `FWP_*`).
- Dosya adı, yol gibi dış kaynaklı veriler betiğin metnine yazılmaz; ortam değişkeni ve stdin JSON ile verilir. Dosya
  adındaki `&`, `|`, `;`, `"` gibi karakterler komut çalıştıramaz. Bu yüzden `cmd` / `.bat` desteklenmez.
- Zaman aşımında betik ve başlattığı tüm alt süreçler (Windows Job Object) sonlandırılır; servis kapanırken de.
- Betik metni ve her değişikliği denetim kaydında saklanır.

## Diğer önlemler

- **Regex:** Aşırı yavaş desenler (felaket geri izleme, ör. `(a+)+`) kaydedilirken reddedilir; canlı deneme ayrı
  süreçte 2 sn sınırla çalışır. Kötü bir desen arayüzü ya da taramayı kilitleyemez.
- **CSV dışa aktarma:** `=`, `+`, `-`, `@` ile başlayan hücreler etkisizleştirilir (elektronik tabloda formül
  çalıştırılamaz).
- **Mail:** Konu ve başlıklara satır sonu enjeksiyonu engellenir. SMTP sertifikası doğrulanır.
- **TLS:** Control-M, API ve SMTP bağlantılarında sertifika doğrulaması varsayılan açıktır.
- **Asistan:** Model dosyaları kod çalıştıramayan bir biçimde (NumPy dizileri) saklanır; zararlı bir model dosyası
  yüklenirken kod çalışmaz.
- **Loglar:** Gizli değer yazılmaz.

## Önerilen sertleştirme

- [ ] Servis LocalSystem değil, en az yetkili ayrı bir hesapla çalışıyor
- [ ] `FileWatcherPro` klasörü: servis hesabı + yöneticiler; `veri` ve `config` başkalarına kapalı
- [ ] Servis hesabının paylaşımlarda yalnız okuma izni var
- [ ] Arayüz yalnız `127.0.0.1`'de; yönetim uzak masaüstüyle
- [ ] `admin` şifresi değişti; herkes kendi hesabıyla, en az yetkili rolle giriyor
- [ ] Süper yönetici şifresi yalnız gereken kişilerde
- [ ] TLS doğrulaması hiçbir hedefte kapatılmadı
- [ ] Denetim kaydı uzun süre saklanacaksa: `denetim_limit` artırıldı ya da `veri\hata.db` yedekleme sistemine alınıyor
  (varsayılan son 2 000 kayıt tutulur)
