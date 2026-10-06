# 04 · Betik hedefi

Hedef bir Control-M ya da hazır bir REST API değilse, dosya geldiğinde sunucuda bir **Python** ya da **PowerShell**
betiği çalıştırılabilir: bir uygulamanın kendine özgü API'sini çağırmak, `curl.exe` ile istek atmak, bir kuyruğa
mesaj bırakmak gibi.

Betik içeriğinden betiği yazan sorumludur. FileWatcherPro betiği yalıtılmış bir süreçte çalıştırır, sonucunu çıkış
koduna göre yorumlar ve yeniden deneme, zaman aşımı, kayıt ve alarm işlerini kendisi yapar.

- [Güvenlik: süper yönetici kilidi](#güvenlik-süper-yönetici-kilidi)
- [Betik nasıl çalıştırılır](#betik-nasıl-çalıştırılır)
- [Betiğe gelen veri](#betiğe-gelen-veri)
- [Çıkış kodu sözleşmesi](#çıkış-kodu-sözleşmesi)
- [Örnekler](#örnekler)
- [Yazarken dikkat](#yazarken-dikkat)

---

## Güvenlik: süper yönetici kilidi

Betik sunucuda kod çalıştırmak demektir; bu yüzden yönetici rolüne ek olarak ikinci bir şifre ister.

1. Şifre sunucuda belirlenir: `betik_sifresi.bat` (ya da `py -3.11 araclar\betik_sifresi.py`). En az 10 karakter;
   arayüz kullanıcılarının şifresiyle aynı olamaz. Dosyaya yalnız özeti yazılır. Şifre belirlenmeden betik türü
   seçilemez.
2. Betik penceresinde **Kilidi aç** ile şifre girilir. Kilit **10 dakika** ve **yalnız o oturum** için açılır;
   5 hatalı denemede 15 dakika bekletilir. Kilidin açılması ve hatalı denemeler denetim kaydına yazılır.
3. Kilit kapalıyken betik salt okunurdur: görülebilir ama değiştirilemez, çalıştırılamaz, betik hedefli kural
   kaydedilemez.

Durum ve kaldırma: `py -3.11 araclar\betik_sifresi.py durum` · `... kaldir` (betik özelliği kapanır).

---

## Betik nasıl çalıştırılır

| | Python | PowerShell |
|---|---|---|
| Yorumlayıcı | Servisle **aynı** Python (`python.exe -X utf8 -I -B`) | Windows PowerShell 5.1 (`powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass`) |
| Sistemin eklediği | — | Başa: `$ErrorActionPreference = 'Stop'` (her hata betiği durdurur), UTF-8 giriş / çıkış, `trap` (yakalanmayan hata → çıkış 1) |
| Kodlama | UTF-8 | UTF-8 |

- Her tetik **ayrı bir süreçte** çalışır. Çalışma klasörü `veri\betik\<hedef>\<sürüm>` klasörüdür (betik her değiştiğinde yeni sürüm klasörü).
- **Temiz ortam:** Betiğe yalnız Windows'un çalışması için gerekenler (`SYSTEMROOT`, `PATH`, `TEMP` …), vekil sunucu
  değişkenleri (`HTTP_PROXY` …) ve `FWP_*` değişkenleri geçer. Servisin diğer ortam değişkenleri geçmez.
- **Zaman aşımı:** 1–600 sn (varsayılan 30). Süre dolunca betik **ve başlattığı tüm alt süreçler** sonlandırılır.
- **Eşzamanlılık:** Hedef başına aynı anda en fazla N betik (varsayılan 2, en çok 8).
- **Çıktı:** stdout ve stderr'in son 64 KB'ı tetiğin deneme geçmişine yazılır; gizli değerler `***` ile maskelenir.
- **cmd / .bat desteklenmez:** cmd, `%DEGISKEN%`'i yeniden yorumlar; dosya adındaki `&` komut çalıştırabilir.
  `curl` gerekiyorsa PowerShell içinden `curl.exe` kullanın.

### Penceredeki araçlar

| Düğme | Ne yapar |
|---|---|
| **Örnek yükle** | Hazır şablonlar: Python REST çağrısı, en sade Python, PowerShell `Invoke-RestMethod`, PowerShell `curl.exe`. |
| **Sözdizimini denetle** | Betiği çalıştırmadan derler; hatalı satırı işaretler. Hatayı yutan `try/except: pass` gibi kalıplar için uyarı gösterir. |
| **Canlı çalıştır** | Betiği seçtiğiniz deneme dosya adıyla **gerçekten** çalıştırır (`FWP_DENEME=1`); çıkış kodunu, sonucu (başarılı / kalıcı / geçici / belirsiz), süreyi ve çıktıyı gösterir. Kaydetmeden önce kullanın. |

---

## Betiğe gelen veri

Dosya bilgisi betiğin **metnine yazılmaz** (dosya adındaki özel karakterler komut çalıştıramaz). İki yoldan gelir:
ortam değişkenleri ve **stdin**'den JSON.

| Ortam değişkeni | stdin JSON alanı | Değer |
|---|---|---|
| `FWP_DOSYA_ADI` | `dosya_adi` | Dosya adı |
| `FWP_TAM_YOL` | `tam_yol` | Tam yol (ağ yolu dahil) |
| `FWP_DIZIN` | `dizin` | Dizin yolu |
| `FWP_BOYUT` | `boyut` | Boyut (bayt) |
| `FWP_ICERIK_HASH` | `icerik_hash` | İçerik özeti (xxh3-128) |
| `FWP_KIMLIK` | `kimlik` | Tetiğin benzersiz kimliği (yeniden denemede aynı) |
| `FWP_KURAL` | `kural` | Kural adı |
| `FWP_ZAMAN` | `zaman` | Dosyanın hazır olduğu an |
| `FWP_BUGUN` | `bugun` | Bugün (`YYYYAAGG`) |
| `FWP_DENEME_SAYISI` | `deneme_sayisi` | Bu kaçıncı deneme (1'den başlar) |
| `FWP_DENEME` | `deneme` | `1` = penceredeki canlı test, `0` = gerçek tetik (JSON'da true / false) |
| `FWP_G_<GRUP>` | `gruplar` | Regex'in isimli grupları (`(?P<tarih>…)` → `FWP_G_TARIH`) |
| `FWP_P_<AD>` | `parametreler` | Kuraldaki ek değerler (`TARIH={tarih}` → `FWP_P_TARIH`) |
| `FWP_SIR_<AD>` | *(yok)* | Hedefte tanımlı **gizli değerler** (token, şifre). Yalnız ortamda bulunur; stdin'e ve loga yazılmaz. |

**Gizli değerler** betik penceresinde ad + değer olarak girilir (en fazla 20; ad büyük harf, rakam ve `_`). Değer
DPAPI ile şifreli saklanır; betiğe yalnız ortam değişkeni olarak verilir ve çıktıda maskelenir.

---

## Çıkış kodu sözleşmesi

Sonucu **yalnız çıkış kodu** belirler. Betik sade yazılır ve hatayı yutmaz.

| Durum | Sonuç | Sistem ne yapar |
|---|---|---|
| Çıkış `0` | Başarılı | İletildi. |
| Çıkış `10` | Kalıcı hata | Yeniden denenmez; tetik lokale yazılır, KRİTİK alarm. Betik ya da veri düzeltilince **kademeli erit**. |
| Diğer çıkış kodları | Geçici hata | Deneme planına göre (5, 10, 15 sn) yeniden; olmazsa lokale + alarm. |
| Süre doldu / servis kapanırken sonlandırıldı | Belirsiz | Betik ve alt süreçleri sonlandırılır; tetik yeniden denenir, "olası çift" işaretlenir. |
| Betik başlatılamadı | Kalıcı hata | Lokale + alarm. |

PowerShell'de betik `exit` yazmadan biterse son harici komutun çıkış kodu (hiç yoksa 0) kullanılır.

> **Yeniden deneme sistemin işidir.** Betik içinde döngüyle tekrar denemeyin; geçici hatada 0 dışında bir kodla
> çıkmanız yeterlidir. Aynı tetik yeniden çalışabileceği için karşı sistem destekliyorsa `FWP_KIMLIK`'i
> `Idempotency-Key` olarak gönderin.

---

## Örnekler

### Python — REST çağrısı (yalnız standart kütüphane)

```python
import json, os, sys, urllib.request, urllib.error

veri = json.load(sys.stdin)
istek = urllib.request.Request(
    "https://api.ornek.local/is/baslat",
    data=json.dumps({"dosya": veri["dosya_adi"], "yol": veri["tam_yol"]}).encode("utf-8"),
    headers={"Content-Type": "application/json",
             "Authorization": "Bearer " + os.environ["FWP_SIR_API_ANAHTARI"],
             "Idempotency-Key": veri["kimlik"]},
    method="POST")
try:
    with urllib.request.urlopen(istek, timeout=20) as yanit:
        print("HTTP", yanit.status, yanit.read(500).decode("utf-8", "replace"))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read(500).decode("utf-8", "replace"), file=sys.stderr)
    sys.exit(10 if 400 <= e.code < 500 and e.code not in (408, 425, 429) else 1)
# Bağlantı hatası ve zaman aşımı yakalanmaz: Python 1 ile çıkar → sistem yeniden dener.
```

### PowerShell — Invoke-RestMethod

```powershell
$govde = @{ dosya = $env:FWP_DOSYA_ADI; yol = $env:FWP_TAM_YOL } | ConvertTo-Json
$basliklar = @{ Authorization = "Bearer $env:FWP_SIR_API_ANAHTARI"; 'Idempotency-Key' = $env:FWP_KIMLIK }
try {
    $yanit = Invoke-RestMethod -Method Post -Uri 'https://api.ornek.local/is/baslat' `
        -Body ([Text.Encoding]::UTF8.GetBytes($govde)) -ContentType 'application/json; charset=utf-8' `
        -Headers $basliklar -TimeoutSec 20
    Write-Output "Kabul edildi: $($yanit | ConvertTo-Json -Compress)"
} catch [System.Net.WebException] {
    $kod = [int]$_.Exception.Response.StatusCode     # bağlantı hatasında 0
    [Console]::Error.WriteLine("HTTP $kod $($_.Exception.Message)")
    if ($kod -ge 400 -and $kod -lt 500 -and $kod -notin 408, 425, 429) { exit 10 }
    exit 1
}
```

### PowerShell — curl.exe

PowerShell 5.1'de `curl` aslında `Invoke-WebRequest`'tir; `curl.exe` yazın. curl HTTP 4xx / 5xx'te de 0 ile çıkar,
durum kodunu kendiniz değerlendirin:

```powershell
$govde = @{ dosya = $env:FWP_DOSYA_ADI } | ConvertTo-Json -Compress
$cikti = $govde | curl.exe -sS -X POST 'https://api.ornek.local/is/baslat' `
    -H 'Content-Type: application/json' -H "Authorization: Bearer $env:FWP_SIR_API_ANAHTARI" `
    -H "Idempotency-Key: $env:FWP_KIMLIK" --data-binary '@-' --max-time 20 -w "`n%{http_code}"
if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("curl çıkış kodu $LASTEXITCODE"); exit 1 }
$kod = [int]($cikti | Select-Object -Last 1)
Write-Output ($cikti -join "`n")
if ($kod -ge 200 -and $kod -lt 300) { exit 0 }
if ($kod -ge 400 -and $kod -lt 500 -and $kod -notin 408, 425, 429) { exit 10 }
exit 1
```

### Kuraldan gelen değerleri kullanmak

Kuralın ek değerleri `OLAY=FATURA_GELDI` ve `TARIH={tarih}` ise:

```python
import os
olay = os.environ["FWP_P_OLAY"]      # FATURA_GELDI
tarih = os.environ["FWP_P_TARIH"]    # regex'teki (?P<tarih>…) grubunun değeri
```

---

## Yazarken dikkat

- **Hatayı yutmayın.** `except: pass` ya da `try { } catch { }` hatayı başarıya çevirir; dosya iletildi sayılır ama
  iş yapılmamıştır.
- **Kalıcı ile geçiciyi ayırın.** Tekrar denemekle düzelmeyecek hatalarda (yanlış veri, yetki, bulunamadı) `exit 10`;
  ağ ve sunucu hatalarında başka bir kod.
- **Süreyi aşmayın.** Uzun işleri betikte beklemeyin; karşı sisteme işi bırakıp çıkın. Zaman aşımı "belirsiz" sonuç
  ve olası çift demektir.
- **Dosyayı taşımayın, silmeyin.** İzlenen klasör üzerindeki işlem, akışın sahibi olan uygulamaya bırakılmalıdır.
- **Grup ilkesi:** Sunucudaki grup ilkesi (GPO) imzasız PowerShell betiklerini engelliyorsa ("running scripts is disabled",
  "not digitally signed") `-ExecutionPolicy Bypass` bunu aşmaz. Betiği imzalatın ya da Python kullanın. Hata canlı
  testte ve tetiğin deneme geçmişinde görünür.
- **Önce canlı test.** Her değişiklikten sonra penceredeki "Canlı çalıştır" ile bir kez deneyin; çıkış kodunu ve
  çıktıyı görün.
