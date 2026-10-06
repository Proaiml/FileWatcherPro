# FileWatcherPro · Yönetici veri sayfası

Kurulumdan kaldırmaya kadar yönetici için tek başvuru belgesi: teknik özellikler, bileşenler, dosya ve ağ haritası,
izinler, roller, tüm varsayılan ayarlar, olay kataloğu, saklama ve yedek, ölçülen performans, işletim komutları ve
kontrol listeleri. Ayrıntılı anlatım için [docs](../README.md#belgeler) klasörüne bakın.

---

## 1. Bir bakışta

| Özellik | Değer |
|---|---|
| Görev | Klasörlere (yerel ya da ağ paylaşımı) gelen dosyaları izler; kurala uyan her yeni dosya için hedefi tetikler |
| Hedef türleri | Control-M Automation API · REST API (Bearer / API anahtarı / Basic) · Python ya da PowerShell betiği |
| Platform | Windows; Python 3.11 (64 bit). Windows servisi (NSSM ya da yerleşik pywin32 sarmalayıcı) |
| Bağımlılıklar | `loguru`, `xxhash`, `pywin32`, `psutil`. İsteğe bağlı: `torch`, `numpy` (asistan modeli) |
| Arayüz | Tarayıcı; varsayılan `http://127.0.0.1:8770`; internet gerektirmez |
| İzleme yöntemi | Dizin listeleme (varsayılan 2 sn); dosya açılmadan ad / boyut / tarih okunur. FTP sunucusuyla entegrasyon gerekmez |
| Tamamlanma tespiti | Boyut ve tarih `sabitlik_W_sn` (10 sn) sabit + başka süreçte açık değil + geçici ad değil (`.filepart`, `.part`) |
| Dosya kimliği | Dizin + ad + içerik özeti (xxh3-128, 500 MB altı); üstünde boyut + tarih |
| Teslim hedefi (SLA) | Dosya hazır → hedef kabul: 10 sn (ayarlanabilir); aşımlar kaydedilir |
| Hata yönetimi | 5 / 10 / 15 sn yeniden deneme → lokal kayıt (JSON) + alarm → kademeli erit; art arda 5 hatada devre kesici |
| Çift koruması | Tetik başına benzersiz kimlik (yeniden denemede aynı); yanıtsız kalan istek "olası çift" işaretli |
| Depolama | SQLite (WAL): `canli.db` (çalışma), `hata.db` (gönderilemeyen + denetim), `asistan.db` (asistan) |
| Saklama | Bitmiş geçmiş 200 kayıt · gönderilemeyen 1 000 (çözülmemiş asla silinmez) · denetim 2 000 · log 10 gün |
| Bakım | Haftalık (Cumartesi 03:00): bütünlük, yedek, budama, indeks, WAL, boş alan |
| Kimlik doğrulama | Yerel kullanıcılar (PBKDF2-SHA256); 3 rol + betik / lokal silme için ikinci şifre |
| Gizli değer saklama | Windows DPAPI (makine kapsamı) |
| Kaynak (ölçülen) | Bileşen başına 30–55 MB bellek; asistan PyTorch ile ~400 MB. 20 000 dosyalık ağ dizininde tarama tek çekirdeğin ~%6'sı |

---

## 2. Bileşenler ve süreçler

Her bileşen ayrı bir Windows sürecidir ve çekirdeğe Job Object ile bağlıdır: çekirdek kapanınca hepsi kapanır,
sahipsiz süreç kalmaz.

| Süreç | Görev | Düşerse |
|---|---|---|
| **Servis (bekçi)** | Çekirdeği başlatır, çökerse 1 / 2 / 5 / 10 / 30 sn beklemeyle yeniden başlatır; durdurma isteğini düzgün kapanışa çevirir | Windows kurtarma / NSSM yeniden başlatır |
| **Çekirdek (gözetmen)** | Bileşenleri başlatır, nabız ve ilerlemeyi izler, takılanı / düşeni yeniden başlatır; bakımı zamanlar | Bekçi yeniden başlatır; arayüzde uyarı |
| **tarama** | Dizinleri listeler, yazımın bitmesini bekler, kimlik çıkarır, kuralları uygular, tetik üretir | Gözetmen yeniden başlatır; açılışta arada gelenler yakalanır |
| **teslim** | Tetikleri hedeflere gönderir; yeniden deneme, lokal kayıt, devre kesici, erit, betik çalıştırma | Gözetmen yeniden başlatır; yarım çağrılar "olası çift" işaretlenip yeniden denenir |
| **kontrol** | Web arayüzü ve API | Gözetmen yeniden başlatır; teslim ve tarama etkilenmez |
| **izleme** | Sunucu ve uygulama CPU / bellek / disk, dizin tarama süresi | Gözetmen yeniden başlatır |
| **bildirim** | Alarm ve olayları kurallara göre maillemek | Gözetmen yeniden başlatır; kuyruktaki mailler kaybolmaz |
| **asistan** *(isteğe bağlı)* | Olay toplama, anomali takibi, öneriler, yerel model eğitimi (düşük öncelik) | Gözetmen yeniden başlatır; tetik yolunu etkilemez |
| **betik** *(geçici)* | Betik hedefinde her tetik için kısa ömürlü süreç | Zaman aşımında süreç ağacıyla sonlandırılır |

Art arda 5 kez düşen bileşen "elle müdahale" durumuna geçer (KRİTİK alarm). 60 sn ilerlemeyen bileşen takılmış
sayılır.

---

## 3. Klasör ve dosya haritası

```
FileWatcherPro\
├─ calistir.py                giriş noktası
├─ baslat.bat                 konsolda çalıştırma
├─ betik_sifresi.bat          süper yönetici şifresi
├─ servis_kur.bat / servis_kaldir.bat   yerleşik servis (alternatif)
├─ config\
│   ├─ baslangic.json         veri / log klasörü, arayüz adresi ve portu, bileşen listesi
│   ├─ kullanicilar.json      arayüz kullanıcıları (PBKDF2 özetleri) · ilk açılışta oluşur
│   └─ betik_sifresi.json     süper yönetici şifresinin özeti · betik_sifresi.bat ile oluşur
├─ veri\
│   ├─ canli.db               dizinler, hedefler, kurallar, ayarlar, dosyalar, tetikler, alarmlar, bildirimler
│   ├─ hata.db                gönderilemeyenler, denetim kaydı
│   ├─ asistan.db, asistan\   asistan verisi ve model dosyaları
│   ├─ lokal_kayit\<hedef>\<gün>\*.json    gönderilemeyen tetiklerin diskteki kopyası
│   ├─ lokal_silinen\         elle silinenlerin tutanakları ve arşivlenen lokal kayıtları
│   ├─ karantina\             okunamayan (bozuk) lokal kayıtlar
│   ├─ betik\<hedef>\<sürüm>\ betik hedeflerinin dosyaları
│   └─ yedek\                 bakımın son sağlam kopyası (canli.db, hata.db + .onceki)
├─ loglar\                    <bileşen>_<YYYY-AA-GG>.log · 10 gün
├─ cekirdek\, eklentiler\, servis\   uygulama kodu
├─ araclar\                   yönetim ve tanı araçları
├─ testler\                   otomatik testler, sahte Control-M ve SMTP
└─ docs\                      belgeler
```

`veri_klasoru` ve `log_klasoru` `config\baslangic.json`'da başka bir diske alınabilir.

---

## 4. Ağ ve bağlantılar

| Yön | Hedef | Port / protokol | Not |
|---|---|---|---|
| Gelen | Arayüz | TCP 8770, `127.0.0.1` | Varsayılan yalnız yerel; dışarıdan gelen bağlantı gerekmez |
| Giden | İzlenen paylaşımlar | SMB, TCP 445 | Yalnız okuma |
| Giden | Control-M Automation API | HTTPS (genelde 8443) | Hedefte tanımlı adres |
| Giden | REST API hedefleri | HTTP / HTTPS | Hedefte tanımlı adres |
| Giden | SMTP | 587 (STARTTLS) · 465 (SSL) · 25 | Bildirim için |
| — | İnternet | — | Gerekmez. Telemetri yoktur; asistan dışarı veri göndermez |

Vekil sunucu gerekiyorsa standart `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` ortam değişkenleri kullanılır.

---

## 5. Hesaplar ve izinler

| Hesap | İzin | Kapsam |
|---|---|---|
| Servis hesabı (LocalSystem değil) | Okuma | İzlenen paylaşımlar (paylaşım + NTFS) |
| | Değiştirme | `veri\`, `loglar\`, `config\` |
| | Okuma + yürütme | Uygulama klasörü, Python kurulumu |
| | Hizmet olarak oturum aç | Yerel güvenlik ilkesi / grup ilkesi |
| Sunucu yöneticisi | Yönetici | Servis kurulumu (NSSM), `servis_dogrula.py`, kullanıcı ve süper yönetici şifresi araçları |

Yönetici hakkı gerekmez. Paylaşım başka sunucudaysa alan hesabı gerekir.

---

## 6. Roller ve yetkiler

| İşlem | İzleyici | Operatör | Yönetici | Ek koşul |
|---|:-:|:-:|:-:|---|
| Tüm sayfaları görmek | ✓ | ✓ | ✓ | |
| Kendi şifresini değiştirmek | ✓ | ✓ | ✓ | |
| Hedef / kural / dizin kuralları / tümünü durdur – aç | | ✓ | ✓ | |
| Devreyi normale al, kademeli erit | | ✓ | ✓ | |
| Motoru, bileşenleri durdur – başlat; bakımı başlat | | ✓ | ✓ | |
| Alarm onaylama | | ✓ | ✓ | |
| Regex canlı deneme, istek kuru deneme | | ✓ | ✓ | |
| Test maili | | ✓ | ✓ | |
| Lokalden seçilenleri gönder | | ✓ | ✓ | Süper yönetici kilidi |
| Lokalden seçilenleri sil | | | ✓ | Süper yönetici kilidi + gerekçe |
| Hedef, dizin, kural, bildirim, SMTP, ayar ekle / değiştir / sil | | | ✓ | Betik hedefi: süper yönetici kilidi |
| Gerçek gönderim denemesi | | | ✓ | Onay |
| Asistan ayarları, eğitim, sürüm seçimi | | | ✓ | |
| Kullanıcı ekle / sil | | | | Yalnız sunucuda: `araclar\kullanici.py` |
| Süper yönetici şifresi belirle | | | | Yalnız sunucuda: `betik_sifresi.bat` |

Oturum 12 saat. 5 hatalı girişte 60 sn kilit. Süper yönetici kilidi 10 dk / oturum; 5 hatalı denemede 15 dk bekleme.

---

## 7. Varsayılan ayarlar

Tümü arayüzde **Ayarlar** sayfasından değiştirilir; değişiklik yeniden başlatma gerektirmeden uygulanır ve denetim
kaydına yazılır.

| Grup | Ayar | Varsayılan | Aralık / seçenekler | Açıklama |
|---|---|---|---|---|
| Motor | `motor_aktif` | açık |  | Tarama motoru çalışsın mı (önyüzden durdur/başlat). |
| Motor | `tarama_araligi_sn` | 2 | 0,2 – 600 | Dizin listeleme sıklığı. |
| Motor | `dizin_tarama_zaman_asimi_sn` | 20 | 1 – 600 | Tek dizin listelemesi bu süreyi aşarsa dizin YANITSIZ sayılır. |
| Motor | `dizin_deneme_plani` | 5,10,15 | sn listesi, en çok 10 adım | Dizine erişilemezse bekleme planı (sn); bitince ERİŞİLEMEZ + alarm. |
| Motor | `dizin_seyrek_deneme_sn` | 30 | 1 – 3 600 | ERİŞİLEMEZ dizin için seyrek deneme aralığı. |
| Tamamlanma | `sabitlik_W_sn` | 10 | 0 – 3 600 | Boyut ve mtime bu süre değişmezse dosya tamamlanmış sayılabilir (paylaşım testiyle birlikte). |
| Tamamlanma | `aski_T_dk` | 30 | 0,1 – 1 440 | Yazılmakta olan dosya bu süreyi aşarsa ASKIDA + önyüze bildirim. |
| Tamamlanma | `hash_esik_mb` | 500 | 0 – 1 000 000 | Bu boyutun altındaki dosyaların içerik hash'i (xxh3) alınır; kimlik = dizin + ad + hash. |
| Tamamlanma | `parca_dikkate_al` | açık |  | .filepart/.part gibi geçici adları 'yükleniyor' olarak izle (asla tetiklenmez). |
| Tamamlanma | `parca_uzantilari` | .filepart,.part |  | Geçici yükleme uzantıları. |
| Kural | `coklu_kural` | ilk | ilk · hepsi | Bir dosya birden çok kurala uyarsa: 'ilk' eşleşen ya da 'hepsi'. |
| Teslim | `sla_hedef_sn` | 10 | 1 – 3 600 | HAZIR → ilk başarılı API çağrısı hedef süresi; aşılırsa SLA ihlali kaydı. |
| Teslim | `deneme_plani` | 5,10,15 | sn listesi, en çok 10 adım | API hatasında bekleme planı (sn); bitince lokal kayıt + alarm. |
| Teslim | `cagri_timeout_sn` | 4 | 0,5 – 120 | Tek API çağrısı için azami süre. |
| Teslim | `esz_cagri_ust` | 4 | 1 – 64 | Hedef başına aynı anda en fazla çağrı. |
| Teslim | `otomatik_devre_esigi` | 5 | 0 – 1 000 | Hedefte art arda bu kadar hata olursa devre kesilir; yeni tetikler denenmeden lokale yazılır (0 = kapalı). |
| Teslim | `erit_hizi` | 5 | 0,1 – 100 | Kademeli eritmede saniyede en fazla çağrı. |
| Teslim | `kapanis_teslim_bekleme_sn` | 15 | 0 – 60 | Kapanırken (servis durdurma, Windows kapanışı, teslim eklentisini durdurma) bekleyen tetiklerin gönderilmesi için verilen süre. Bitmeyenler kaybolmaz: veritabanında kalır, açılışta kendiliğinden gönderilir. |
| Teslim | `hedef_yavas_pencere_dk` | 10 | 0,1 – 1 440 | Hedef yavaşlama alarmı: son bu kadar dakikada canlı yoldan iletilen en az 5 tetiğin %20'si SLA hedefini aşarsa uyarı açılır; %5'in altına inince kapanır. |
| Teslim | `kapali_hatirlatma_dk` | 30 | 1 – 10 080 | Hedef/kural bu süreden uzun kapalı kalırsa hatırlatma alarmı. |
| Depolama | `gecmis_limit` | 200 | 10 – 100 000 | canli.db: dizinden kalkmış dosya ve bitmiş tetik geçmişi (aktif ve bekleyenler hariç). |
| Depolama | `hata_limit` | 1 000 | 10 – 1 000 000 | hata.db: gönderilemeyen kayıt sınırı (çözülmemişler asla silinmez). |
| Depolama | `denetim_limit` | 2 000 | 100 – 1 000 000 | hata.db: denetim kaydı sınırı. |
| Depolama | `bakim_gunu` | Cumartesi | Pazartesi · Salı · Çarşamba · Perşembe · Cuma · Cumartesi · Pazar | Haftalık bakım günü. |
| Depolama | `bakim_saati` | 03:00 | SS:DD | Haftalık bakım saati (SS:DD). |
| Gözetmen | `eklenti_nabiz_sn` | 1 | 0,2 – 60 | Eklentilerin nabız yazma aralığı. |
| Gözetmen | `eklenti_yanitsiz_sn` | 60 | 2 – 3 600 | Ana döngüsü bu süre ilerlemeyen eklenti takılmış sayılır ve yeniden başlatılır. |
| Gözetmen | `eklenti_baslama_payi_sn` | 20 | 1 – 600 | Başlayan eklentiye ilk nabız için tanınan süre. |
| Gözetmen | `eklenti_bekleme_plani` | 1,2,5,10,30 | sn listesi, en çok 10 adım | Düşen eklenti için yeniden başlatma bekleme planı (sn). |
| Gözetmen | `eklenti_dusme_limiti` | 5 | 1 – 100 | Art arda bu kadar düşen eklenti ELLE_MÜDAHALE durumuna geçer. |
| Gözetmen | `eklenti_stabil_sn` | 60 | 1 – 86 400 | Bu süreden uzun çalışmış eklentinin düşme sayacı sıfırlanır. |
| Loglama | `log_saklama_gun` | 10 | 1 – 3 650 | Log dosyalarının saklanma süresi. |
| Loglama | `log_azami_mb` | 50 | 1 – 10 240 | Tek log dosyasının azami boyutu. |
| İzleme | `izleme_aralik_sn` | 10 | 1 – 300 | Sistem kaynaklarının ölçülme sıklığı (son 24 saat saklanır). |
| İzleme | `izleme_normale_donus_sn` | 60 | 1 – 3 600 | Değer eşiğin altına indikten bu kadar sn sonra alarm kapanır (dalgalanmada aç-kapa olmasın). |
| İzleme | `izleme_sunucu_cpu` | 90 | 1 – 100 | Sunucu CPU eşiği (%). |
| İzleme | `izleme_sunucu_cpu_aktif` | açık |  | Sunucu CPU eşiği izlensin. |
| İzleme | `izleme_sunucu_cpu_dk` | 5 | 0 – 1 440 | Sunucu CPU eşiği bu kadar dakika sürerse alarm. |
| İzleme | `izleme_sunucu_ram` | 90 | 1 – 100 | Sunucu bellek eşiği (%). |
| İzleme | `izleme_sunucu_ram_aktif` | açık |  | Sunucu bellek eşiği izlensin. |
| İzleme | `izleme_sunucu_ram_dk` | 5 | 0 – 1 440 | Sunucu bellek eşiği bu kadar dakika sürerse alarm. |
| İzleme | `izleme_disk_bos_gb` | 5 | 0,1 – 100 000 | Veri ve log disklerinde en az boş alan (GB); altına düşünce KRİTİK alarm. |
| İzleme | `izleme_disk_bos_gb_aktif` | açık |  | Disk boş alanı izlensin. |
| İzleme | `izleme_fwp_cpu` | 25 | 1 – 100 | FileWatcherPro bileşenlerinin toplam CPU eşiği (sunucunun %'si). |
| İzleme | `izleme_fwp_cpu_aktif` | açık |  | FileWatcherPro CPU'su izlensin. |
| İzleme | `izleme_fwp_cpu_dk` | 10 | 0 – 1 440 | FileWatcherPro CPU eşiği bu kadar dakika sürerse alarm. |
| İzleme | `izleme_fwp_ram_mb` | 1 024 | 50 – 1 000 000 | FileWatcherPro bileşenlerinin toplam bellek eşiği (MB). |
| İzleme | `izleme_fwp_ram_mb_aktif` | açık |  | FileWatcherPro belleği izlensin. |
| İzleme | `izleme_fwp_ram_mb_dk` | 10 | 0 – 1 440 | FileWatcherPro bellek eşiği bu kadar dakika sürerse alarm. |
| İzleme | `izleme_log_mb` | 2 048 | 10 – 1 000 000 | Log klasörü boyut eşiği (MB). |
| İzleme | `izleme_log_mb_aktif` | açık |  | Log klasörü boyutu izlensin. |
| İzleme | `izleme_tarama_sn` | 10 | 0,5 – 3 600 | Bir dizinin listelenmesi 3 ölçüm üst üste bu süreyi aşarsa alarm (sn). |
| İzleme | `izleme_tarama_sn_aktif` | açık |  | Dizin tarama süresi izlensin. |
| Bildirim | `bildirim_deneme_plani` | 30,120,300,900,1800 | sn listesi, en çok 10 adım | Gönderilemeyen mail için yeniden deneme planı (sn); bitince HATA + alarm. |
| Bildirim | `bildirim_tasma_esigi` | 10 | 1 – 1 000 | Bir anında kural 10 dakikada bundan fazla mail üretirse geçici olarak özete geçer (mail yağmuru koruması). |
| Bildirim | `bildirim_tasma_ozet_dk` | 5 | 0,05 – 120 | Taşma olduğunda biriken olayların özet maili bu aralıkla gider (dk). |

Toplam 56 ayar.

Arayüz dışında `config\baslangic.json`: `kontrol_adres` `127.0.0.1` · `kontrol_port` `8770` · `veri_klasoru` `veri` ·
`log_klasoru` `loglar` · `kontrol_izinli_adlar` (isteğe bağlı) · `eklentiler` (bileşen listesi).

Bileşene gömülü sabitler: oturum 12 sa · giriş kilidi 5 deneme / 60 sn · süper yönetici kilidi 10 dk, 5 deneme / 15 dk ·
betik zaman aşımı 1–600 sn (varsayılan 30), eşzamanlı 1–8 (varsayılan 2), çıktı 64 KB, en çok 20 gizli değer · regex
en çok 1 000 karakter · istek gövdesi en çok 20 000 karakter · lokalde tek seferde en çok 5 000 kayıt seçimi.

---

## 8. Olay ve alarm kataloğu

"Önerilen" olaylar bildirim kuralı için iyi bir başlangıçtır. "Mail gönderilemiyor" olayı maillenmez (döngü olmasın).

| Grup | Kod | Olay | Seviye | Önerilen | Açıklama | Ne yapmalı |
|---|---|---|---|:-:|---|---|
| Hedef / teslim | `HEDEF_DEVRE` | Devre kesildi | KRİTİK | ✓ | Hedef (Control-M / API / betik) art arda yanıt vermedi; yeni tetikler denenmeden lokale yazılıyor. | Hedefin durumunu kontrol edin; düzelince 'Devreyi normale al', ardından 'Kademeli erit'. |
| Hedef / teslim | `HEDEF_KALICI` | Kalıcı hata (istek reddedildi) | KRİTİK | ✓ | Hedef isteği reddetti (4xx: olay / iş adı, klasör, yetki) ya da betik 10 ile çıktı. Tetik lokalde bekler, yeniden denenmez. | Kuralın isteğini 'Kuru deneme' ile kontrol edin, düzeltin, sonra erit edin. |
| Hedef / teslim | `DOSYA_GONDERILEMEDI` | Dosya hedefe gönderilemedi | UYARI | ✓ | Tetik gönderilemedi ve lokal kayda yazıldı (deneme planı bitti, kalıcı hata, devre kesik ya da hedef/kural kayıtlı kapalı). | Hedef düzelince Lokal kayıt sayfasından 'Kademeli erit'. |
| Hedef / teslim | `DOSYA_OLASI_CIFT` | Olası çift çağrı | UYARI |  | Cevap gelmeden bağlantı koptu ya da betiğin süresi doldu; hedef işi iki kez yapmış olabilir. | Hedefte tetik kimliğiyle (FWP_KIMLIK / X-Idempotency-Key) iki çalışma var mı bakın. |
| Hedef / teslim | `DOSYA_SLA` | SLA aşıldı | BİLGİ |  | Dosya hazır olduktan sonra hedefe iletim SLA süresini aştı. | Sık oluyorsa Sistem izleme ve hedefin yanıt sürelerine bakın. |
| Hedef / teslim | `DOSYA_KAYITSIZ` | Kayıtsız kapalıyken dosya geldi | UYARI | ✓ | Hedef ya da kural kayıtsız kapalıydı; dosya hedefe gönderilmedi ve saklanmadı. | Gerekirse dosyayı elle işleyin; hedefi açın. |
| Hedef / teslim | `HEDEF_YAVAS` | Hedef yavaşladı (SLA aşımları arttı) | UYARI | ✓ | Son pencerede (varsayılan 10 dk) canlı yoldan iletilen tetiklerin en az %20'si SLA hedefini aştı. | Hedefin (Control-M / API / betik) yanıt sürelerine ve Sistem izleme'ye bakın; kalıcıysa eşzamanlı çağrı sayısını ya da SLA hedefini gözden geçirin. |
| Hedef / teslim | `ERIT_DURDU` | Kademeli erit durdu | UYARI | ✓ | Erit sırasında hedef hata verdi; kalanlar lokalde güvende. | Hedef düzelince eriti yeniden başlatın. |
| Hedef / teslim | `LOKAL_BIRIKTI` | Lokalde kayıt birikiyor | UYARI |  | Gönderilemeyen tetikler lokal kayıtta bekliyor. | Hedef sağlıklıysa 'Kademeli erit' başlatın. |
| Hedef / teslim | `HEDEF_KAPALI_UZUN` | Hedef / kural uzun süredir kapalı | UYARI |  | Bir hedef ya da kural ayarlanan süreden uzun kapalı. | Kapatma bilinçliyse onaylayın; değilse açın. |
| Hedef / teslim | `LOKAL_KAYIT` | Lokal kayıt yazılamıyor / bozuk | KRİTİK | ✓ | Lokal kayıt klasörüne yazılamıyor ya da okunamayan kayıt karantinaya alındı. | Disk ve klasör izinlerini kontrol edin; tetikler veritabanında güvende. |
| Dizin / dosya | `DIZIN_ERISILEMEZ` | Dizine erişilemiyor | KRİTİK | ✓ | Ağ yolu ya da paylaşım erişilemez; 5/10/15 sn denemeleri bitti. | Paylaşımı ve servis hesabının okuma yetkisini kontrol edin; dizin gelince kaçanlar yakalanır. |
| Dizin / dosya | `DIZIN_YANITSIZ` | Dizin yanıt vermiyor (ağ takıldı) | KRİTİK | ✓ | Dizin listelemesi zaman aşımına uğradı. | Dosya sunucusu ve ağ bağlantısını kontrol edin. |
| Dizin / dosya | `YUKLEME_ASKIDA` | Yükleme askıda (çok uzun sürüyor) | UYARI | ✓ | Yazılmakta olan dosya ayarlanan süreyi aştı; tamamlanana kadar tetiklenmez. | FTP tarafında yüklemenin durumuna bakın; yarım kaldıysa dosyayı yeniden isteyin. |
| Dizin / dosya | `DOSYA_ANOMALI` | Dosyalarda anomali (boyut / adet / teslim süresi) | UYARI |  | Yapay zekâ asistanının istatistik takibi: bir kuralın dosyası alışılmadık boyutta geldi, günlük sayısı ya da teslim süresi normalinden saptı. Yalnız asistan ayarlarında 'anomaliyi alarm olarak aç' seçiliyse oluşur. | Dosyayı ve gönderen tarafı kontrol edin (yarım / boş yükleme, yanlış dosya, eksik gönderim). Normalse onaylayın; asistan önerisini 'Faydasız' işaretleyin. |
| Dizin / dosya | `DOSYA_ESLESMEDI` | Kurala uymayan dosya geldi | BİLGİ |  | Uzantısı uyan ama hiçbir kuralın regex'ine uymayan dosya. | Yeni bir dosya türü mü? Kural ekleyin ya da regex'i genişletin. |
| Sistem | `EKLENTI_ELLE` | Bileşen elle müdahale bekliyor | KRİTİK | ✓ | Bir bileşen art arda düştü; otomatik yeniden başlatma durdu. | Eklentiler sayfasında son hataya bakın, 'Başlat' ile yeniden deneyin. |
| Sistem | `EKLENTI_DUSTU` | Bileşen düştü (kendiliğinden kalktı) | UYARI |  | Bir bileşen beklenmedik biçimde kapandı ve yeniden başlatıldı. | Tekrarlanıyorsa logları inceleyin. |
| Sistem | `CEKIRDEK_YENIDEN` | Çekirdek beklenmedik kapandı | UYARI | ✓ | Windows servisi çekirdeği yeniden başlattı; kayıp yok. | Sık tekrarlanıyorsa loglar klasöründeki cekirdek loguna bakın. |
| Sistem | `BAKIM_HATA` | Bakım hata verdi | UYARI |  | Bir bakım adımı hata verdi ve geri alındı (ya da bütünlük kontrolü geçmedi). | Genel bakış → Bakım geçmişi'nde hangi adımın geri alındığına bakın. |
| Sistem | `DB_BOYUT` | Veritabanı büyüdü | UYARI |  | canli.db ya da hata.db beklenenden büyük. | Saklama sınırlarını ve çözülmemiş kayıtları kontrol edin. |
| Sistem | `HATA_DB_SINIR` | Çözülmemiş kayıt sınırı aşıldı | UYARI |  | Gönderilemeyen çözülmemiş kayıtlar sınırı aştı (silinmezler). | Gönderilemeyenler sayfasındaki kayıtları çözün. |
| Sistem | `VARSAYILAN_SIFRE` | Varsayılan şifre kullanılıyor | UYARI |  | admin hesabının şifresi hâlâ ilk kurulumdaki gibi. | Sağ üstteki kilit simgesinden şifreyi değiştirin. |
| Sistem | `MAIL_GONDERILEMIYOR` | Mail gönderilemiyor (maillenmez) | UYARI |  | Bildirim maili art arda gönderilemedi (SMTP sunucusu, kimlik ya da ağ). | Bildirimler sayfasında 'Bağlantıyı dene' ve Gönderim geçmişindeki hataya bakın. (Bu olay maille bildirilmez.) |
| Kaynaklar (sistem izleme) | `KAYNAK_SUNUCU_CPU` | Sunucu CPU eşiği aşıldı | UYARI | ✓ | Sunucunun işlemci kullanımı eşiği belirtilen süre boyunca aştı. | Sistem izleme sayfasında hangi sürecin yük bindirdiğine bakın. |
| Kaynaklar (sistem izleme) | `KAYNAK_SUNUCU_RAM` | Sunucu bellek eşiği aşıldı | UYARI | ✓ | Sunucunun bellek kullanımı eşiği belirtilen süre boyunca aştı. | Sunucudaki diğer uygulamaların bellek kullanımını kontrol edin. |
| Kaynaklar (sistem izleme) | `KAYNAK_DISK` | Disk boş alanı azaldı | KRİTİK | ✓ | Veri ya da log diskinde boş alan eşiğin altına düştü; veritabanı yazamazsa izleme durur. | Diskte yer açın; log saklama süresini azaltın. |
| Kaynaklar (sistem izleme) | `KAYNAK_FWP_CPU` | FileWatcherPro CPU eşiği aşıldı | UYARI | ✓ | FileWatcherPro bileşenlerinin toplam işlemci kullanımı eşiği aştı. | Çok büyük dizin ya da kısa tarama aralığı olabilir; Sistem izleme'de bileşenlere bakın. |
| Kaynaklar (sistem izleme) | `KAYNAK_FWP_RAM` | FileWatcherPro bellek eşiği aşıldı | UYARI | ✓ | FileWatcherPro bileşenlerinin toplam belleği eşiği aştı. | Bileşeni yeniden başlatmak geçici çözüm olur; logları saklayıp bildirin. |
| Kaynaklar (sistem izleme) | `KAYNAK_LOG` | Log klasörü büyüdü | UYARI |  | Log klasörü eşik boyutu aştı. | Log saklama süresini ve boyut sınırını kontrol edin. |
| Kaynaklar (sistem izleme) | `KAYNAK_TARAMA` | Dizin taraması yavaş | UYARI |  | Bir dizinin listelenmesi art arda eşik süreyi aştı; yeni dosyalar geç fark edilir. | Dosya sunucusu yükünü ve dizindeki dosya sayısını kontrol edin. |

Toplam 31 olay türü.

---

## 9. Veri saklama ve budama

| Veri | Nerede | Saklama |
|---|---|---|
| Aktif dosyalar, bekleyen / lokaldeki tetikler | `canli.db` | Bitene kadar; asla budanmaz |
| Bitmiş dosya ve tetik geçmişi | `canli.db` | Son `gecmis_limit` (200) |
| Kapanmış alarmlar, işlenmiş komutlar | `canli.db` | Son 200 |
| Günlük sayaçlar | `canli.db` | 90 gün |
| Gönderilemeyen kayıtları | `hata.db` | Son `hata_limit` (1 000); **çözülmemişler asla silinmez** |
| Denetim kaydı | `hata.db` | Son `denetim_limit` (2 000) |
| Lokal kayıt dosyaları | `veri\lokal_kayit\` | Tetik iletilince silinir |
| Silme tutanakları ve arşiv | `veri\lokal_silinen\` | Uygulama silmez |
| Loglar | `loglar\` | `log_saklama_gun` (10 gün); dosya başına `log_azami_mb` (50 MB) |
| Sistem izleme ölçümleri | `canli.db` | Son 24 saat |
| Asistan verisi | `asistan.db` | Asistan ayarındaki saklama süresi |

Budama haftalık bakımda yapılır. Uzun süreli denetim saklama gerekiyorsa `denetim_limit`'i artırın ya da `veri\yedek\`
kopyalarını yedekleme sisteminize alın.

---

## 10. Yedek ve geri yükleme

**Otomatik:** Haftalık bakım `canli.db` ve `hata.db`'nin çalışan sistemi durdurmadan tutarlı bir kopyasını
`veri\yedek\` altına yazar; bir önceki kopya `.onceki` olarak tutulur.

**Önerilen yedekleme kapsamı:** `veri\yedek\`, `veri\lokal_kayit\`, `veri\lokal_silinen\`, `config\`
(`baslangic.json`, `kullanicilar.json`, `betik_sifresi.json`). Gizli değerler DPAPI ile **bu makineye** bağlıdır: başka
bir makineye geri yüklenen veritabanında hedef ve SMTP şifreleri yeniden girilmelidir.

**Geri yükleme otomatik yapılmaz.** Yalnız veritabanı kullanılamaz hâle geldiyse, elle:

1. Servisi durdurun: `nssm stop FileWatcherPro`.
2. Bozuk dosyaları kenara alın: `veri\canli.db*` ve `veri\hata.db*` (inceleme için saklayın).
3. `veri\yedek\canli.db` ve `veri\yedek\hata.db`'yi `veri\` altına kopyalayın.
4. Yedekten sonra işlenmiş ve hâlâ klasörde duran dosyalar yeniden "yeni" görünebilir. Yeniden gönderilmesinler diye
   ilk açılışı teslimsiz yapın: `config\baslangic.json`'daki `eklentiler` listesinden `teslim` satırını geçici olarak
   çıkarın, servisi başlatın, arayüzde her hedef için **Gönderimi durdur → Kayıtlı durdur** deyin, `teslim`'i listeye
   geri ekleyip servisi yeniden başlatın.
5. Yeniden görülen tetikler **Lokal kayıt** sayfasında birikir. Hedef tarafında zaten işlenmiş olanları seçerek
   silin (gerekçeli, tutanaklı), kalanları gönderin; sonra hedefleri açın.

Lokalde bekleyen tetikler ayrıca `veri\lokal_kayit\` dosyalarından açılışta kendiliğinden geri yüklenir.

---

## 11. Ölçülen performans

Geliştirme makinesinde ölçülmüştür; ağ paylaşımı ölçümleri aynı makinedeki SMB paylaşımı üzerindendir. Gerçek ağda
`araclar\ftp_gozlem.py` ve `araclar\performans_olcum.py` ile doğrulayın.

| Ölçüm | Koşul | Sonuç |
|---|---|---|
| Boşta yük | 20 000 dosyalık ağ dizini, 60 sn | Tarama tek çekirdeğin %6,3'ü; teslim %0,7; arayüz %1,3; çekirdek %0,3 |
| Bellek | Boşta, bileşen başına | 30–55 MB (asistan PyTorch ile ~400 MB) |
| Tarama turu | 20 000 dosya, ağ paylaşımı | 159 ms |
| Ani yük | 300 dosya aynı anda | Tümü 2,4 sn'de iletildi; en uzun tetik 0,27 sn |
| Arayüz durum özeti | 50 000 dosya, 10 000 lokalde | 6,5 ms (saniyede bir) |
| Büyük dizinde ilk kurulum | 8 000 dosya temel alınırken | Yeni gelen dosya 3,4 sn'de tetiklendi |
| Anomali takibi | 5 000 dosyalık patlama, 300 kural | Dosya başına ~0,9 ms (ayrı, düşük öncelikli süreç) |
| Haftalık budama | 5 000 bitmiş tetik | 12 ms |
| Saha provası | Normal gün, ani yük, kesinti + erit, betik hataları, süreç öldürme, bakım, kapanış, lokal seçerek işlem, anomali | 278 dosyada kayıp ve çift yok |

---

## 12. İşletim komutları

| İş | Komut |
|---|---|
| Servisi başlat / durdur / durum | `nssm start FileWatcherPro` · `nssm stop FileWatcherPro` · `nssm status FileWatcherPro` |
| Servisi yeniden başlat | `nssm restart FileWatcherPro` |
| Konsolda çalıştır (deneme) | `baslat.bat` (Ctrl+C ile düzgün kapanır) |
| Kurulumu doğrula | `py -3.11 araclar\servis_dogrula.py [--oldurme-yok]` |
| Kullanıcı ekle / sil / listele | `py -3.11 araclar\kullanici.py ekle <ad> <IZLEYICI\|OPERATOR\|YONETICI>` · `sil <ad>` · `liste` |
| Varsayılan admin'i geri ekle | `py -3.11 araclar\kullanici.py varsayilan` |
| Süper yönetici şifresi | `betik_sifresi.bat` · `py -3.11 araclar\betik_sifresi.py durum` · `... kaldir` |
| Temiz kurulum paketi | `py -3.11 araclar\prod_paketi.py` |
| Kopyayı doğrula | `py -3.11 araclar\prod_paketi.py --dogrula C:\FileWatcherPro` |
| Klasör ölçümü (salt okunur) | `py -3.11 araclar\ftp_gozlem.py "<klasör>" --dk 30` |
| Uçtan uca prova (geçici klasörde) | `py -3.11 araclar\saha_provasi.py` |
| Servisi kaldır | `nssm stop FileWatcherPro` · `nssm remove FileWatcherPro confirm` |

Arayüzden: motor durdur / başlat, bileşen başlat / durdur / yeniden başlat, şimdi bakım yap, gönderimi durdur
(tek hedef / tüm hedefler), kuralları durdur (tek / dizin / tümü), devreyi normale al, kademeli erit.

---

## 13. Kontrol listeleri

### Devreye alma

- [ ] Python 3.11 (tüm kullanıcılar), `pip install -r requirements.txt`
- [ ] Servis hesabı: paylaşımlara okuma; `veri`, `loglar`, `config`'e yazma; "hizmet olarak oturum aç"
- [ ] `ftp_gozlem.py` ile klasör ölçüldü, `sabitlik_W_sn` ayarlandı
- [ ] `admin` şifresi değişti; kullanıcılar uygun rollerle eklendi
- [ ] Süper yönetici şifresi belirlendi (gerekiyorsa)
- [ ] Hedefler: "Bağlantıyı dene" başarılı
- [ ] Dizinler erişilebilir; uzantı listesi ve ilk kurulum seçimi bilinçli
- [ ] Kurallar: canlı deneme gerçek adlarla doğru; kuru deneme isteği doğru
- [ ] SMTP + test maili; KRİTİK olaylar için bildirim kuralı
- [ ] NSSM servisi; `servis_dogrula.py` GEÇTİ
- [ ] Deneme dosyası hedefe ulaştı

### Günlük

- [ ] Genel durum "Her şey yolunda"; açık KRİTİK alarm yok
- [ ] Lokal kayıtta beklenmeyen birikme yok
- [ ] Gönderilemeyenler'de çözülmemiş kayıt incelendi

### Haftalık

- [ ] Bakım sonucu TAMAM (Eklentiler → bakım geçmişi)
- [ ] Sistem izleme: disk, bellek, tarama süresi eğilimi
- [ ] Asistan önerileri ve anomaliler gözden geçirildi

### Aylık

- [ ] Kullanıcılar ve roller güncel (`kullanici.py liste`)
- [ ] Denetim kaydında beklenmeyen değişiklik yok
- [ ] `veri\yedek\` ve `config\` yedekleme sistemine alınıyor

### Sürüm yükseltme

- [ ] Servis durduruldu (bekleyenlere süre tanındı)
- [ ] `veri\` ve `config\` yedeklendi
- [ ] Yeni dosyalar kopyalandı; `veri\`, `loglar\`, `config\kullanicilar.json`, `config\betik_sifresi.json` korundu
- [ ] `pip install -r requirements.txt`
- [ ] Servis başlatıldı, `servis_dogrula.py` GEÇTİ, bir deneme dosyası iletildi

### Hedef kesintisinden sonra

- [ ] Hedef yanıt veriyor (Hedefler kartında sağlık)
- [ ] Devre normale alındı
- [ ] Kademeli erit tamamlandı; lokal kayıt boş
- [ ] "Olası çift" işaretli tetikler hedef tarafında kontrol edildi

---

## 14. Bilinen sınırlar

| Konu | Açıklama |
|---|---|
| Kesik yükleme | Bağlantısı kopan yüklemenin yarım dosyası tamamlanmış dosyadan ayırt edilemez. FTP sunucusunda geçici adla yükleme önerilir. |
| Çok kısa ömürlü dosya | Tarama aralığından kısa sürede gelip silinen dosya görülemez. |
| Alt klasörler | İzlenmez; her klasör ayrı dizin olarak eklenir. |
| Saat sıçraması | Süre ölçümlerini etkileyebilir, tetiklemeyi etkilemez. |
| PowerShell ve grup ilkesi | İmzasız betik engelleniyorsa PowerShell betik hedefi çalışmaz. |
| Arayüz HTTP | TLS yok; yalnız yerel kullanım önerilir. |
| Tek kopya | Aynı veri klasörü için tek süreç; etkin-etkin küme yok. |

---

## 15. Arayüz API'si (izleme entegrasyonu için)

Arayüzün kullandığı API, izleme araçlarından da okunabilir. Oturum çerezi ile çalışır:

1. `POST /api/giris` gövde `{"kullanici": "...", "sifre": "..."}` → `fwp_oturum` çerezi. İzleme için **İzleyici**
   rolünde ayrı bir kullanıcı açın.
2. GET dışındaki her istekte `X-FWP: 1` başlığı zorunludur.
3. Okuma uçları (İzleyici): `GET /api/durum` (genel durum, sayılar, bileşenler, hedefler) · `GET /api/alarmlar` ·
   `GET /api/izleme` · `GET /api/gonderilemeyen` · `GET /api/tetikler`.

API yalnız `127.0.0.1`'den (ya da `kontrol_izinli_adlar`'daki adlarla) erişilebilir.
