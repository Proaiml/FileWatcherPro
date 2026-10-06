/* FileWatcherPro önyüzü — hedef pencereleri: tür seçimi → Control-M / Genel API (REST) / Betik (Python, PowerShell).
   Betik: süper yönetici kilidi, kod editörü, gizli değerler, hata sözleşmesi, canlı test (kaydetmeden önce).
   uygulama.js'deki yardımcıları (h, dugme, pencere, API, D…) kullanır; ondan ÖNCE yüklenir, çağrılar sonra olur. */
"use strict";

const HEDEF_TURLERI = {
  CONTROLM: { ad: "Control-M", ikon: "hedef",
    aciklama: "Control-M Automation API: olay (koşul) ekler ya da iş sipariş eder. Kimlik: kullanıcı + şifre ya da API anahtarı." },
  HTTP: { ad: "Genel API (REST)", ikon: "baglanti",
    aciklama: "Herhangi bir HTTP / JSON API. Her kural kendi yöntemini, yolunu ve gövdesini taşır. Kimlik: yok, Bearer, API anahtarı ya da Basic." },
  BETIK: { ad: "Betik (Python / PowerShell)", ikon: "kod",
    aciklama: "Her dosya için yazdığınız betik bu sunucuda çalışır; dosya bilgisi ortam değişkeni ve stdin JSON olarak verilir. curl, PowerShell betiği içinden curl.exe ile kullanılır." },
};
const BETIK_DILLERI = {
  python: { ad: "Python", ref: v => `os.environ["${v}"]` },
  powershell: { ad: "PowerShell", ref: v => `$env:${v}` },
};
const hedefTurMetni = x => x.tur === "BETIK" ? `Betik · ${(BETIK_DILLERI[(x.ayrintilar || {}).dil] || {}).ad || "?"}` : (HEDEF_TURLERI[x.tur] || {}).ad || x.tur;

// Betiğe giden bilgiler: ortam değişkeni → stdin JSON alanı → açıklama
const BETIK_DEGISKENLERI = [
  ["FWP_DOSYA_ADI", "dosya_adi", "Dosya adı"],
  ["FWP_TAM_YOL", "tam_yol", "Tam yol (ağ yolu dahil)"],
  ["FWP_DIZIN", "dizin", "Dizin yolu"],
  ["FWP_BOYUT", "boyut", "Boyut (bayt)"],
  ["FWP_ICERIK_HASH", "icerik_hash", "İçerik hash'i (xxh3-128)"],
  ["FWP_KIMLIK", "kimlik", "Tetik kimliği: yeniden denemede AYNI kalır. Karşı API destekliyorsa Idempotency-Key olarak gönderin"],
  ["FWP_KURAL", "kural", "Kural adı"],
  ["FWP_ZAMAN", "zaman", "Dosyanın hazır olduğu an (YYYY-AA-GG SS:DD:ss)"],
  ["FWP_BUGUN", "bugun", "Bugünün tarihi (YYYYAAGG)"],
  ["FWP_DENEME_SAYISI", "deneme_sayisi", "Kaçıncı deneme (1 = ilk; 2+ = yeniden deneme)"],
  ["FWP_DENEME", "deneme", "Canlı testte 1, gerçek tetikte 0"],
];

const BETIK_ORNEKLERI = [
  { ad: "Python · REST çağrısı (standart kütüphane)", dil: "python", kod: [
    "# Örnek: dosya bilgisini bir REST API'ye gönderir (yalnız standart kütüphane).",
    "# Çıkış: 0 başarılı · 10 kalıcı hata (tekrar denenmez) · diğer: geçici (tekrar denenir)",
    "import json, os, sys, urllib.request, urllib.error",
    "",
    "veri = json.load(sys.stdin)    # aynı bilgiler ortamda da: os.environ[\"FWP_DOSYA_ADI\"]",
    "istek = urllib.request.Request(",
    "    \"https://api.sirket.local/is/baslat\",",
    "    data=json.dumps({\"dosya\": veri[\"dosya_adi\"], \"yol\": veri[\"tam_yol\"]}).encode(\"utf-8\"),",
    "    headers={\"Content-Type\": \"application/json\",",
    "             \"Authorization\": \"Bearer \" + os.environ[\"FWP_SIR_API_ANAHTARI\"],",
    "             \"Idempotency-Key\": veri[\"kimlik\"]},",
    "    method=\"POST\")",
    "try:",
    "    with urllib.request.urlopen(istek, timeout=20) as yanit:",
    "        print(\"HTTP\", yanit.status, yanit.read(500).decode(\"utf-8\", \"replace\"))",
    "except urllib.error.HTTPError as e:    # yalnız kalıcı / geçici ayrımı için",
    "    print(\"HTTP\", e.code, e.read(500).decode(\"utf-8\", \"replace\"), file=sys.stderr)",
    "    sys.exit(10 if 400 <= e.code < 500 and e.code not in (408, 425, 429) else 1)",
    "# Bağlantı hatası, zaman aşımı yakalanmaz: Python 1 ile çıkar → sistem tekrar dener.",
  ].join("\n") },
  { ad: "Python · en sade (yalnız yazdırır)", dil: "python", kod: [
    "# En sade betik: gelen bilgiyi yazdırır. Hata olursa Python kendiliğinden 1 ile çıkar.",
    "import os",
    "",
    "print(\"Dosya:\", os.environ[\"FWP_DOSYA_ADI\"])",
    "print(\"Tam yol:\", os.environ[\"FWP_TAM_YOL\"])",
    "print(\"Tetik kimliği:\", os.environ[\"FWP_KIMLIK\"], \"· canlı test:\", os.environ[\"FWP_DENEME\"])",
  ].join("\n") },
  { ad: "PowerShell · Invoke-RestMethod", dil: "powershell", kod: [
    "# Örnek: Invoke-RestMethod ile REST çağrısı.",
    "# Sistem başa $ErrorActionPreference = 'Stop' ekler: yakalanmayan hata → çıkış 1.",
    "$govde = @{ dosya = $env:FWP_DOSYA_ADI; yol = $env:FWP_TAM_YOL } | ConvertTo-Json",
    "$basliklar = @{ Authorization = \"Bearer $env:FWP_SIR_API_ANAHTARI\"; 'Idempotency-Key' = $env:FWP_KIMLIK }",
    "try {",
    "    $yanit = Invoke-RestMethod -Method Post -Uri 'https://api.sirket.local/is/baslat' `",
    "        -Body ([Text.Encoding]::UTF8.GetBytes($govde)) -ContentType 'application/json; charset=utf-8' `",
    "        -Headers $basliklar -TimeoutSec 20",
    "    Write-Output \"Kabul edildi: $($yanit | ConvertTo-Json -Compress)\"",
    "} catch [System.Net.WebException] {",
    "    $kod = [int]$_.Exception.Response.StatusCode     # bağlantı hatasında 0",
    "    [Console]::Error.WriteLine(\"HTTP $kod $($_.Exception.Message)\")",
    "    if ($kod -ge 400 -and $kod -lt 500 -and $kod -notin 408, 425, 429) { exit 10 }",
    "    exit 1",
    "}",
  ].join("\n") },
  { ad: "PowerShell · curl.exe", dil: "powershell", kod: [
    "# Örnek: curl.exe ile istek. PowerShell 5.1'de \"curl\" Invoke-WebRequest'tir: curl.exe yazın.",
    "# curl HTTP 4xx/5xx'te de 0 ile çıkar: durum kodunu -w ile alıp kendimiz karar veriyoruz.",
    "$govde = @{ dosya = $env:FWP_DOSYA_ADI } | ConvertTo-Json -Compress",
    "$cikti = $govde | curl.exe -sS -X POST 'https://api.sirket.local/is/baslat' `",
    "    -H 'Content-Type: application/json' -H \"Authorization: Bearer $env:FWP_SIR_API_ANAHTARI\" `",
    "    -H \"Idempotency-Key: $env:FWP_KIMLIK\" --data-binary '@-' --max-time 20 -w \"`n%{http_code}\"",
    "if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine(\"curl çıkış kodu $LASTEXITCODE (bağlantı / zaman aşımı)\"); exit 1 }",
    "$kod = [int]($cikti | Select-Object -Last 1)",
    "Write-Output ($cikti -join \"`n\")",
    "if ($kod -ge 200 -and $kod -lt 300) { exit 0 }",
    "if ($kod -ge 400 -and $kod -lt 500 -and $kod -notin 408, 425, 429) { exit 10 }",
    "exit 1",
  ].join("\n") },
];

const PS_ONSOZ = [
  "$ErrorActionPreference = 'Stop'                    # her hata betiği durdurur",
  "$ProgressPreference = 'SilentlyContinue'",
  "[Console]::OutputEncoding / InputEncoding = UTF-8  # Türkçe çıktı ve stdin JSON doğru okunur",
  "$OutputEncoding = UTF-8                            # curl.exe'ye borulanan metin UTF-8",
  "trap { [Console]::Error.WriteLine($_); exit 1 }     # yakalanmayan hata → çıkış 1 (geçici)",
  ". (Join-Path $PSScriptRoot 'betik.ps1')            # sizin betiğiniz (satır numaraları korunur)",
  "if ($LASTEXITCODE) { exit $LASTEXITCODE }          # exit yazmadan bittiyse: son harici komutun kodu",
  "exit 0",
].join("\n");

const BETIK_SONUC = {
  BASARI: ["Başarılı", "ok", "Gerçek tetikte 'İletildi' sayılırdı."],
  GECICI: ["Geçici hata", "warn", "Gerçek tetikte 5 / 10 / 15 sn sonra yeniden denenir; yine olmazsa lokale yazılıp alarm açılırdı."],
  KALICI: ["Kalıcı hata", "bad", "Gerçek tetikte yeniden denenmez; lokale yazılıp KRİTİK alarm açılırdı."],
  BELIRSIZ: ["Belirsiz (süre doldu)", "warn", "Süreç ağacı sonlandırıldı. Betik işi yapmış olabilir: gerçek tetikte yeniden denenir ve 'olası çift' işaretlenirdi."],
};

// ---------------------------------------------------------------- yardımcılar
function kisaOzet(s) {                       // içerik değişti mi? (FNV-1a; yalnız önyüz karşılaştırması için)
  let x = 0x811c9dc5;
  for (const c of String(s)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619) >>> 0; }
  return x.toString(16).padStart(8, "0");
}
function satirlarAyristir(metin, ayirac, ad) {    // "Ad: değer" / "AD=değer" satırları → nesne
  const o = {};
  for (const s of String(metin || "").split(/\r?\n/)) {
    const t = s.trim(); if (!t) continue;
    const i = t.indexOf(ayirac);
    if (i < 1) throw new Error(`${ad} '${ayirac === ":" ? "Ad: değer" : "AD=değer"}' biçiminde olmalı: ${t}`);
    o[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  }
  return o;
}
const sifreYeri = (kayitli, bos) => kayitli ? "kayıtlı · değiştirmek için yazın" : bos;
function dpapiSeridi() {
  return h("div", { class: "serit bilgi", style: { margin: "0 0 12px" } }, ikon("kilit", 18), h("div", { class: "metin" },
    "Şifre / anahtar bu sunucuda Windows DPAPI ile şifrelenerek saklanır; ekranda, veritabanında ve loglarda düz hâli görünmez. Uygulama başka sunucuya taşınırsa yeniden girilir."));
}
function gelismisRef(ref) {
  return h("details", { class: "yardim" }, h("summary", {}, ikon("ayar", 15), " Gelişmiş: şifreyi dışarıdan oku (Windows Kimlik Bilgisi / ortam değişkeni)"),
    h("div", { class: "yardim-ic" }, h("div", { class: "alan", style: { margin: 0 } }, h("label", {}, "Referans"), ref,
      h("div", { class: "ipucu" }, "Şifre alanı boşsa ve uygulamada kayıtlı şifre yoksa kullanılır. Kurum ilkesi şifrenin uygulamada tutulmamasını istiyorsa: Windows Kimlik Bilgisi Yöneticisi'ne (servisin hesabıyla) ya da ortam değişkenine kaydedip adını yazın."))));
}
function denemeDugmesi(veri, yol) {               // "Bağlantıyı dene" (kaydetmeden, yazılan şifreyle)
  const sonuc = h("div", {});
  return h("div", { class: "satir", style: { marginTop: "12px" } }, dugme("Bağlantıyı dene", { ikon: "yenile", kucuk: true, ipucu: "Kaydetmeden önce erişimi ve kimliği (yazdığınız şifreyle) dener; iş tetiklemez",
    onclick: async () => { sonuc.replaceChildren(h("span", { class: "sessiz" }, "Bağlanılıyor…"));
      try { const r = await API.post(yol, veri()); sonuc.replaceChildren(h("span", { class: `yanit ${r.basarili ? "ok" : "bad"}` }, `${r.basarili ? "✓" : "✗"} ${r.mesaj} (${r.sure_ms} ms)`)); }
      catch (e) { sonuc.replaceChildren(h("span", { class: "alan hata" }, e.message)); } } }), sonuc);
}

// ---------------------------------------------------------------- 1) tür seçimi
async function hedefPenceresi() {
  let bd = null; try { bd = await API.get("/api/betik/durum"); } catch (_) { /* eski sunucu */ }
  let secim = "CONTROLM";
  const kartlar = Object.entries(HEDEF_TURLERI).map(([k, t]) => {
    const kapali = k === "BETIK" && (!bd || !bd.sifre_tanimli);
    return h("label", { class: `secim-kart ${k === secim ? "secili" : ""} ${kapali ? "kapali" : ""}`, "data-tur": k },
      h("input", { type: "radio", name: "hedef_tur", value: k, checked: k === secim ? true : null, disabled: kapali ? true : null,
        onchange: () => { secim = k; kartlar.forEach(el => el.classList.toggle("secili", el.dataset.tur === k)); } }),
      h("div", { class: "tur-ikon" }, ikon(t.ikon, 20)),
      h("div", {}, h("div", { class: "b" }, t.ad, k === "BETIK" ? h("span", { class: "rozet warn duz", style: { marginLeft: "8px" } }, ikon("kilit", 12), "süper yönetici şifresi") : null),
        h("div", { class: "a" }, t.aciklama),
        kapali ? h("div", { class: "a", style: { color: "var(--bad)", marginTop: "6px" } }, !bd
          ? "Bu sürümde henüz yok: betik özelliğinin sunucu tarafı yazılmadı (ekran tasarımı onay bekliyor)."
          : ["Kapalı: süper yönetici şifresi belirlenmemiş. Sunucuda FileWatcherPro klasöründeki ", h("span", { class: "mono" }, "betik_sifresi.bat"), " dosyasına çift tıklayın."]) : null));
  });
  pencere({ baslik: "Hedef ekle", ikon: "hedef", icerik: h("div", {}, h("p", { class: "ikincil", style: { marginTop: 0 } }, "Tetik nereye gidecek? Tür sonradan değiştirilemez."), ...kartlar),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Devam", sinif: "ana", eylem: () => { setTimeout(() => HEDEF_PENCERELERI[secim](null), 0); } }] });
}
const HEDEF_PENCERELERI = { CONTROLM: controlmPenceresi, HTTP: apiPenceresi, BETIK: betikPenceresi };
const hedefDuzenle = async x => {                    // betiğin metni durum özetinde yok: tek hedef sunucudan çekilir
  if (x.tur !== "BETIK") return HEDEF_PENCERELERI[x.tur](x);
  try { betikPenceresi(await API.get(`/api/hedefler/${x.id}`)); } catch (e) { bildirim(e.message, "bad"); }
};
const betikSuresi = x => (x && (x.timeout_sn ?? (x.ayrintilar || {}).zaman_asimi_sn)) || 30;
const betikEszamanli = x => (x && (x.esz_cagri_ust ?? (x.ayrintilar || {}).eszamanli)) || 2;

// ---------------------------------------------------------------- 2a) Control-M
function controlmPenceresi(x) {
  const a = (x && x.ayrintilar) || {};
  const ad = h("input", { type: "text", placeholder: "örn. Control-M Prod", value: x ? x.ad : null });
  const adres = h("input", { type: "text", class: "mono", placeholder: "https://ctm-sunucu:8443/automation-api", value: x ? x.adres : null });
  const ctm = h("input", { type: "text", placeholder: "ctmprod (şablonlarda {ctm})", value: a.ctm || null });
  const kul = h("input", { type: "text", placeholder: "API kullanıcısı", autocomplete: "off", value: a.kullanici || null });
  const sifre = h("input", { type: "password", id: "hedef_sifre", autocomplete: "new-password" });
  const tur = h("select", {}, ...[["token", "Kullanıcı + şifre (oturum token'ı)"], ["apikey", "API anahtarı (x-api-key)"], ["yok", "Kimlik yok (yalnızca deneme / sahte Control-M)"]]
    .map(([v, e]) => h("option", { value: v, selected: (a.kimlik_turu || "token") === v ? true : null }, e)));
  const ref = h("input", { type: "text", class: "mono", placeholder: "wincred:FileWatcherPro/ctm  ya da  env:FWP_CTM_SIFRE" });
  const veri = () => ({ ad: ad.value, adres: adres.value, tur: "CONTROLM", ayrintilar: tur.value === "token"
    ? { ctm: ctm.value, kimlik_turu: "token", kullanici: kul.value, sifre: sifre.value || undefined, sifre_ref: ref.value.trim() || undefined }
    : tur.value === "apikey" ? { ctm: ctm.value, kimlik_turu: "apikey", apikey: sifre.value || undefined, apikey_ref: ref.value.trim() || undefined }
    : { ctm: ctm.value, kimlik_turu: "yok" } });
  const sifreEtiket = h("label", { for: "hedef_sifre" }, "Şifre");
  const kulAlan = h("div", { class: "alan gen" }, h("label", {}, "Kullanıcı"), kul);
  const kimlikAlanlari = h("div", {}, h("div", { class: "satir" }, kulAlan, h("div", { class: "alan gen" }, sifreEtiket, sifre)), dpapiSeridi(), gelismisRef(ref));
  const turDegisti = () => {
    kimlikAlanlari.classList.toggle("gizli", tur.value === "yok");
    kulAlan.classList.toggle("gizli", tur.value === "apikey");
    sifreEtiket.textContent = tur.value === "apikey" ? "API anahtarı" : "Şifre";
    sifre.placeholder = tur.value === "apikey" ? sifreYeri(a.apikey_kayitli, "API anahtarı") : sifreYeri(a.sifre_kayitli, "Şifre");
  };
  tur.addEventListener("change", turDegisti); turDegisti();
  pencere({ baslik: x ? `Hedefi düzenle: ${x.ad}` : "Hedef ekle · Control-M", ikon: "hedef", tur: "acc", icerik: h("div", {},
    h("div", { class: "alan" }, h("label", {}, "Ad"), ad),
    h("div", { class: "alan" }, h("label", {}, "Automation API adresi (temel adres; kurallar bunun üstüne yol ekler)"), adres),
    h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Control-M sunucusu (isteğe bağlı)"), ctm), h("div", { class: "alan gen" }, h("label", {}, "Kimlik türü"), tur)),
    kimlikAlanlari, denemeDugmesi(veri, "/api/hedefler/dene")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: x ? "Değişiklikleri kaydet" : "Hedefi ekle", sinif: "ana", basari: x ? "Hedef güncellendi" : "Hedef eklendi",
      eylem: () => x ? API.put(`/api/hedefler/${x.id}`, veri()) : API.post("/api/hedefler", veri()) }] });
}

// ---------------------------------------------------------------- 2b) Genel API (REST)
function apiPenceresi(x) {
  const a = (x && x.ayrintilar) || {};
  const ad = h("input", { type: "text", placeholder: "örn. Raporlama API", value: x ? x.ad : null });
  const adres = h("input", { type: "text", class: "mono", placeholder: "https://api.sirket.local/v1", value: x ? x.adres : null });
  const tur = h("select", { id: "api_kimlik" }, ...[["yok", "Kimlik yok"], ["bearer", "Bearer token (Authorization: Bearer …)"], ["apikey", "API anahtarı (özel başlık)"], ["basic", "Kullanıcı + şifre (Basic)"]]
    .map(([v, e]) => h("option", { value: v, selected: (a.kimlik_turu || "bearer") === v ? true : null }, e)));
  const baslikAdi = h("input", { type: "text", class: "mono", value: a.anahtar_basligi && a.anahtar_basligi !== "Authorization" ? a.anahtar_basligi : "X-API-Key" });
  const anahtar = h("input", { type: "password", id: "api_anahtar", autocomplete: "new-password" });
  const kul = h("input", { type: "text", autocomplete: "off", placeholder: "Kullanıcı", value: a.kullanici || null });
  const sifre = h("input", { type: "password", id: "api_sifre", autocomplete: "new-password", placeholder: sifreYeri(a.sifre_kayitli, "Şifre") });
  const basliklar = h("textarea", { rows: 3, class: "mono", placeholder: "X-Kaynak: FileWatcherPro\nX-Ortam: prod" },
    Object.entries(a.basliklar || {}).map(([k, v]) => `${k}: ${v}`).join("\n"));
  const tls = h("input", { type: "checkbox", checked: a.tls_dogrula === false ? null : true });
  const tlsUyari = h("div", { class: "alan hata", style: { margin: "4px 0 0" } }, "Sertifika doğrulanmazsa araya giren biri isteği ve anahtarı okuyabilir. Yalnız iç test ortamı için kapatın.");
  const saglik = h("input", { type: "text", class: "mono", placeholder: "/health   (boşsa temel adrese HEAD)", value: a.saglik_yolu || null });
  const ref = h("input", { type: "text", class: "mono", placeholder: "wincred:FileWatcherPro/rapor  ya da  env:FWP_RAPOR_ANAHTAR" });
  const anahtarEtiket = h("label", { for: "api_anahtar" }, "Token");
  const baslikAlan = h("div", { class: "alan", style: { width: "180px" } }, h("label", {}, "Başlık adı"), baslikAdi);
  const anahtarSatir = h("div", { class: "satir" }, baslikAlan, h("div", { class: "alan gen" }, anahtarEtiket, anahtar));
  const basicSatir = h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Kullanıcı"), kul), h("div", { class: "alan gen" }, h("label", { for: "api_sifre" }, "Şifre"), sifre));
  const kimlikAlanlari = h("div", {}, anahtarSatir, basicSatir, dpapiSeridi(), gelismisRef(ref));
  const turDegisti = () => {
    kimlikAlanlari.classList.toggle("gizli", tur.value === "yok");
    anahtarSatir.classList.toggle("gizli", tur.value === "basic"); basicSatir.classList.toggle("gizli", tur.value !== "basic");
    baslikAlan.classList.toggle("gizli", tur.value !== "apikey");
    anahtarEtiket.textContent = tur.value === "apikey" ? "API anahtarı" : "Token";
    anahtar.placeholder = sifreYeri(a.anahtar_kayitli, tur.value === "apikey" ? "API anahtarı" : "Token");
  };
  tur.addEventListener("change", turDegisti); turDegisti();
  tls.addEventListener("change", () => tlsUyari.classList.toggle("gizli", tls.checked)); tlsUyari.classList.toggle("gizli", tls.checked);
  const veri = () => {
    const b = satirlarAyristir(basliklar.value, ":", "Sabit başlık");
    const gizli = Object.keys(b).find(k => /authorization|api-?key|token|secret|cookie|sifre|password/i.test(k));
    if (gizli) throw new Error(`'${gizli}' sabit başlıkta olmamalı: sabit başlıklar düz metin saklanır. Kimlik için 'Kimlik türü' alanını kullanın (DPAPI ile şifrelenir).`);
    const ay = { kimlik_turu: tur.value, basliklar: b, tls_dogrula: tls.checked, saglik_yolu: saglik.value.trim() || undefined };
    if (tur.value === "bearer" || tur.value === "apikey") Object.assign(ay, { anahtar_basligi: tur.value === "bearer" ? "Authorization" : baslikAdi.value.trim(),
      anahtar_on_eki: tur.value === "bearer" ? "Bearer " : "", anahtar: anahtar.value || undefined, anahtar_ref: ref.value.trim() || undefined });
    if (tur.value === "basic") Object.assign(ay, { kullanici: kul.value, sifre: sifre.value || undefined, sifre_ref: ref.value.trim() || undefined });
    return { ad: ad.value, adres: adres.value, tur: "HTTP", ayrintilar: ay };
  };
  const sat = (a_, b_) => h("tr", {}, h("td", {}, a_), h("td", {}, b_));
  pencere({ baslik: x ? `Hedefi düzenle: ${x.ad}` : "Hedef ekle · Genel API (REST)", ikon: "baglanti", tur: "acc", genis: true, icerik: h("div", {},
    h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Ad"), ad), h("div", { class: "alan", style: { flex: 2, minWidth: "260px" } }, h("label", {}, "Temel adres (kurallar bunun üstüne yol ekler)"), adres)),
    h("div", { class: "alan" }, h("label", { for: "api_kimlik" }, "Kimlik türü"), tur), kimlikAlanlari,
    h("div", { class: "satir", style: { alignItems: "flex-start" } },
      h("div", { class: "alan gen" }, h("label", {}, "Sabit başlıklar (isteğe bağlı; satır başına 'Ad: değer')"), basliklar,
        h("div", { class: "ipucu" }, "Şifre / token buraya yazılmaz (düz metin saklanır). Her istekte ayrıca X-Idempotency-Key: <tetik kimliği> gönderilir.")),
      h("div", { class: "alan gen" }, h("label", {}, "Sağlık yoklaması yolu"), saglik,
        h("label", { class: "satir", style: { fontWeight: 500, marginTop: "8px" } }, tls, "TLS sertifikasını doğrula"), tlsUyari)),
    h("details", { class: "yardim" }, h("summary", {}, ikon("soru", 15), " Yanıt nasıl değerlendirilir? (Control-M ile aynı)"),
      h("div", { class: "yardim-ic" }, h("table", { class: "tablo yardim-tablo sozlesme" }, h("tbody", {},
        sat("2xx", "Başarılı → İletildi"),
        sat("408 · 425 · 429 · 5xx · bağlantı hatası", "Geçici → 5 / 10 / 15 sn sonra yeniden denenir; olmazsa lokale yazılır + alarm (429'da Retry-After'a uyulur)"),
        sat("diğer 4xx (400, 401, 403, 404…)", "Kalıcı → yeniden denenmez; lokale yazılır + KRİTİK alarm (kural / kimlik düzeltilip erit edilir)"),
        sat("istek gitti, yanıt gelmeden süre doldu", "Belirsiz → yeniden denenir ve 'olası çift' işaretlenir"))))),
    denemeDugmesi(veri, "/api/hedefler/dene")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: x ? "Değişiklikleri kaydet" : "Hedefi ekle", sinif: "ana", basari: x ? "Hedef güncellendi" : "Hedef eklendi",
      eylem: () => x ? API.put(`/api/hedefler/${x.id}`, veri()) : API.post("/api/hedefler", veri()) }] });
}

// ---------------------------------------------------------------- betik kilidi (süper yönetici şifresi)
/* Betik eklemek / değiştirmek / çalıştırmak ve betik hedefli kural kaydetmek için gerekir. Şifre yalnız sunucuda
   (betik_sifresi.bat → araclar\betik_sifresi.py) belirlenir; önyüzden belirlenemez ve değiştirilemez. Açılan kilit yalnız bu
   oturumda ve sınırlı süre geçerlidir. */
function betikKilidi(degisti) {
  const el = h("div", { class: "kilit-serit" });
  let durum = null, bitis = 0, sayac = null;
  const sifre = h("input", { type: "password", id: "betik_kilit_sifre", placeholder: "Süper yönetici şifresi", autocomplete: "off" });
  const hata = h("div", { class: "alan hata", style: { margin: "6px 0 0" } });
  const al = d => { durum = d; bitis = Date.now() / 1000 + (d.kalan_sn || 0); ciz(); };
  const ac = async () => { hata.textContent = ""; try { al(await API.post("/api/betik/kilit", { sifre: sifre.value })); sifre.value = ""; } catch (e) { hata.textContent = e.message; } };
  sifre.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); ac(); } });
  const sure = () => { const k = Math.max(0, Math.round(bitis - Date.now() / 1000)); return `${Math.floor(k / 60)}:${String(k % 60).padStart(2, "0")}`; };
  function ciz() {
    clearInterval(sayac);
    if (!durum.sifre_tanimli) {
      el.replaceChildren(h("div", { class: "serit kritik", style: { margin: "0 0 14px" } }, ikon("kilit", 18), h("div", { class: "metin" },
        h("b", {}, "Betik özelliği kapalı. "), "Süper yönetici şifresi belirlenmemiş. Sunucuda FileWatcherPro klasöründeki ", h("span", { class: "mono" }, "betik_sifresi.bat"), " dosyasına çift tıklayıp şifreyi iki kez yazın; sonra bu pencereyi yeniden açın.")));
    } else if (!durum.kilit_acik) {
      el.replaceChildren(h("div", { class: "serit uyari", style: { margin: "0 0 14px", flexWrap: "wrap" } }, ikon("kilit", 18),
        h("div", { class: "metin", style: { minWidth: "260px" } }, h("b", {}, "Süper yönetici kilidi kapalı. "),
          "Betik işlemleri ve lokal kayıtları seçerek gönderme / silme süper yönetici şifresi ister (yönetici şifrenizden ayrı; yalnız sunucuda betik_sifresi.bat ile belirlenir). Kilit 10 dakika, yalnız bu oturumda açık kalır."),
        h("div", { class: "satir" }, sifre, dugme("Kilidi aç", { ikon: "kilit_acik", sinif: "ana", kucuk: true, rol: "YONETICI", onclick: ac })), hata));
    } else {
      const kalan = h("b", {}, sure());
      el.replaceChildren(h("div", { class: "serit basari", style: { margin: "0 0 14px" } }, ikon("kilit_acik", 18),
        h("div", { class: "metin" }, "Süper yönetici kilidi açık · ", kalan, " kaldı (yalnız bu oturum). İşlemler denetim kaydına yazılır."),
        dugme("Kilitle", { ikon: "kilit", kucuk: true, onclick: async () => al(await API.sil("/api/betik/kilit")) })));
      sayac = setInterval(() => {
        if (!el.isConnected) return clearInterval(sayac);
        kalan.textContent = sure();
        if (bitis <= Date.now() / 1000) { durum = { ...durum, kilit_acik: false }; ciz(); }
      }, 1000);
    }
    degisti(durum);
  }
  API.get("/api/betik/durum").then(al).catch(e => { el.replaceChildren(h("div", { class: "alan hata" }, e.message)); });
  return { el, acik: () => !!(durum && durum.kilit_acik), durum: () => durum };
}

// ---------------------------------------------------------------- kod editörü (satır numaralı, Tab = 4 boşluk)
function kodEditoru(deger) {
  const no = h("div", { class: "satirno", "aria-hidden": "true" });
  const ta = h("textarea", { class: "mono", id: "betik_kod", spellcheck: "false", wrap: "off", autocomplete: "off", "aria-label": "Betik" }, deger || "");
  let hatali = new Set();
  const numara = () => {
    const n = ta.value.split("\n").length;
    no.replaceChildren(...Array.from({ length: n }, (_, i) => h("div", { class: hatali.has(i + 1) ? "hatali" : null }, String(i + 1))));
    no.scrollTop = ta.scrollTop;
  };
  ta.addEventListener("input", numara);
  ta.addEventListener("scroll", () => { no.scrollTop = ta.scrollTop; });
  ta.addEventListener("keydown", e => {            // Tab girinti ekler; Shift+Tab ile editörden çıkılır
    if (e.key !== "Tab" || e.shiftKey || e.ctrlKey || e.altKey || ta.readOnly) return;
    e.preventDefault(); ta.setRangeText("    ", ta.selectionStart, ta.selectionEnd, "end"); ta.dispatchEvent(new Event("input"));
  });
  numara();
  const el = h("div", { class: "kod-editor" }, no, ta);
  return { el, ta,
    isaretle: satirlar => { hatali = new Set(satirlar); numara(); },
    ekle: metin => { if (ta.readOnly) return; ta.focus(); ta.setRangeText(metin, ta.selectionStart, ta.selectionEnd, "end"); ta.dispatchEvent(new Event("input")); },
    kilitle: k => { ta.readOnly = k; el.classList.toggle("kilitli", k); } };
}

// Statik ipuçları: engellemez, yalnız sık yapılan ve hatayı başarı gibi gösteren kalıpları işaret eder.
function betikUyarilari(dil, kod, sirAdlari) {
  const u = [], k = String(kod || "");
  if (dil === "powershell") {
    if (/(^|[\s;|(=])curl(?!\.exe)\s/im.test(k)) u.push("PowerShell 5.1'de 'curl', Invoke-WebRequest'in takma adıdır; gerçek curl için curl.exe yazın.");
    if (/curl\.exe/i.test(k) && !/--fail|http_code/i.test(k)) u.push("curl HTTP 4xx/5xx yanıtında da 0 ile çıkar: --fail-with-body ya da -w \"%{http_code}\" ile kontrol edin; yoksa hata başarılı sayılır.");
    if (/-(ErrorAction|ea)\s+(SilentlyContinue|Ignore|0)\b/i.test(k)) u.push("-ErrorAction SilentlyContinue hatayı yutar: başarısız adım başarılı sayılabilir.");
    if (/catch\s*(\[[^\]]*\]\s*)?\{\s*\}/i.test(k)) u.push("Boş catch bloğu hatayı yutar: betik 0 ile çıkar, tetik başarılı sayılır.");
    if (/\bcmd(\.exe)?\s+\/c\b/i.test(k)) u.push("cmd /c içinde %FWP_…% kullanılırsa dosya adındaki & | ^ karakterleri komut çalıştırabilir; değerleri $env: ile kullanın.");
  } else {
    if (/except[^\n:]*:[^\n]*\n\s*pass\b/.test(k)) u.push("except … pass hatayı yutar: betik 0 ile çıkar, tetik başarılı sayılır.");
    if (/verify\s*=\s*False/.test(k)) u.push("TLS doğrulaması kapalı (verify=False).");
    if (/shell\s*=\s*True|os\.system\(/.test(k)) u.push("Komut satırı kabukta çalışıyor (shell=True / os.system): dosya adındaki özel karakterler komut çalıştırabilir; subprocess.run([...]) liste biçimini kullanın.");
  }
  if (/(sifre|şifre|password|passwd|token|api_?key|secret)["']?\s*[:=]\s*["'][^"'$\s]{4,}["']/i.test(k)) u.push("Betikte düz metin şifre / anahtar var gibi görünüyor: 'Gizli değerler'e taşıyın ve FWP_SIR_… ile okuyun.");
  for (const m of k.matchAll(/FWP_SIR_([A-Z0-9_]+)/g)) if (!sirAdlari.includes(m[1])) u.push(`FWP_SIR_${m[1]} kullanılıyor ama 'Gizli değerler'de ${m[1]} yok.`);
  return [...new Set(u)];
}

function ortamTablosu(r) {                         // kuru deneme: komut + ortam değişkenleri + stdin
  return [
    h("div", { class: "cikti-baslik" }, "Komut"), h("div", { class: "mono istek-satir" }, r.komut),
    h("div", { class: "cikti-baslik" }, "Ortam değişkenleri"),
    h("table", { class: "tablo ortam-tablo" }, h("tbody", {}, ...Object.entries(r.ortam).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", { class: "mono" }, v))))),
    h("div", { class: "cikti-baslik" }, "stdin (JSON; gizli değerler stdin'e konmaz)"), h("pre", { class: "mono" }, JSON.stringify(r.stdin, null, 2)),
  ].filter(Boolean);
}
function betikSonucu(r) {                          // canlı çalıştırma sonucu
  const [e, s, aciklama] = BETIK_SONUC[r.sonuc] || [r.sonuc, "", ""];
  return [
    h("div", { class: "satir" }, h("span", { class: `rozet ${s}` }, e), h("span", { class: "mono" }, `çıkış ${r.cikis_kodu ?? "—"} · ${r.sure_ms} ms`), r.mesaj ? h("span", { class: "sessiz" }, r.mesaj) : null),
    h("div", { class: "ipucu", style: { marginTop: "4px" } }, aciklama),
    h("div", { class: "cikti-baslik" }, r.stdout ? "stdout" : "stdout (boş)"), r.stdout ? h("pre", { class: "mono" }, r.stdout) : null,
    h("div", { class: "cikti-baslik" }, r.stderr ? "stderr" : "stderr (boş)"), r.stderr ? h("pre", { class: "mono", style: { color: "var(--bad)" } }, r.stderr) : null,
    h("div", { class: "ipucu" }, `Çıktı ${r.kesildi ? "64 KB'ta kesildi; " : ""}gizli değerler *** ile maskelenir. Sonucu yalnız çıkış kodu belirler.`),
  ].filter(Boolean);
}
function canliOnayi(metin, calistir) {           // gerçek çalıştırma öncesi onay kutulu pencere
  let b_;
  pencere({ baslik: "Betiği gerçekten çalıştır", ikon: "uyari", tur: "bad", icerik: h("div", {},
    h("p", { style: { marginTop: 0 } }, metin),
    h("p", { class: "ikincil" }, "FWP_DENEME=1 verilir. Denetim kaydına yazılır; tetik tablosuna girmez."),
    h("label", { class: "satir", style: { fontWeight: 600, color: "var(--bad)" } }, h("input", { type: "checkbox", onchange: e => { b_.disabled = !e.target.checked; } }),
      "Bunun dış sistemlerde gerçek bir işlem yapabileceğini anladım.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Çalıştır", sinif: "tehlike", devre_disi: true, ref: b => { b_ = b; }, eylem: async () => { await calistir(); return true; } }] });
}

// ---------------------------------------------------------------- 2c) Betik
function betikPenceresi(x) {
  const a = (x && x.ayrintilar) || {};
  let kilitAcik = false, sonTest = null, kaydetDg = null, diller = {};
  const ad = h("input", { type: "text", id: "betik_ad", placeholder: "örn. Fatura aktarım betiği", value: x ? x.ad : null });
  const ilkOrnek = BETIK_ORNEKLERI[0];
  const dilSec = h("select", { id: "betik_dil" }, ...Object.entries(BETIK_DILLERI).map(([k, d]) => h("option", { value: k, selected: k === (a.dil || ilkOrnek.dil) ? true : null }, d.ad)));
  const ornekSec = h("select", { "aria-label": "Örnek yükle" }, h("option", { value: "" }, "Örnek yükle…"), ...BETIK_ORNEKLERI.map((o, i) => h("option", { value: String(i) }, o.ad)));
  const ed = kodEditoru(x ? a.kod : ilkOrnek.kod);
  const yorumlayici = h("div", { class: "ipucu mono" });
  const uyariEl = h("div", { class: "betik-uyarilar" });
  const denetimEl = h("span", { class: "betik-denetim" });
  const onsoz = h("details", { class: "yardim" }, h("summary", {}, ikon("bilgi", 15), " Sistemin PowerShell betiğine eklediği satırlar (değiştirilemez)"),
    h("div", { class: "yardim-ic" }, h("pre", { class: "mono kod-pre" }, PS_ONSOZ),
      h("p", { class: "sessiz" }, "Neden: PowerShell varsayılan olarak hatada devam eder ve 0 ile çıkar; bu, başarısız bir çağrının 'iletildi' sayılması (sessiz kayıp) demektir. Son satırlar: betik exit yazmadan biterse son harici komutun (ör. curl.exe) çıkış kodu kullanılır; bilerek başarı için 'exit 0' yazın.")));

  // gizli değerler → FWP_SIR_<AD>; değer DPAPI ile saklanır, bir daha gösterilmez
  const sirlar = (a.sirlar || []).map(s => ({ ad: s.ad, kayitli: !!s.kayitli, kaynak: s.kaynak, deger: "" }));
  const sirListe = h("div", { class: "sir-liste" });
  const sirCiz = () => {
    sirListe.replaceChildren(...sirlar.map((s, i) => h("div", { class: "satir sir-satir" },
      h("input", { type: "text", class: "mono", value: s.ad || null, placeholder: "AD", "aria-label": "Gizli değer adı", style: { width: "150px" },
        oninput: e => { s.ad = e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"); e.target.value = s.ad; uyar(); } }),
      h("input", { type: "password", autocomplete: "new-password", "aria-label": "Gizli değer", placeholder: sifreYeri(s.kayitli, "Değer"), style: { flex: 1, minWidth: "120px" },
        oninput: e => { s.deger = e.target.value; } }),
      dugme("", { ikon: "cop", kucuk: true, ipucu: "Gizli değeri kaldır", onclick: () => { sirlar.splice(i, 1); sirCiz(); uyar(); } }))),
      ...(sirlar.length ? [] : [h("div", { class: "sessiz", style: { fontSize: "12.5px" } }, "Gizli değer yok.")]));
    guncelle();
  };
  const zamanAsimi = h("input", { type: "number", min: 1, max: 600, value: betikSuresi(x), style: { width: "90px" } });
  const eszamanli = h("input", { type: "number", min: 1, max: 8, value: betikEszamanli(x), style: { width: "90px" } });

  // değişken listesi: tıklayınca dile uygun okuma kodu imlece eklenir
  const degiskenler = h("div", { class: "degiskenler" }, ...BETIK_DEGISKENLERI.map(([v, , acik]) =>
    h("button", { type: "button", class: "degisken", title: acik, onclick: () => ed.ekle(BETIK_DILLERI[dilSec.value].ref(v)) }, v)));

  // canlı test
  const denemeAd = h("input", { type: "text", class: "mono", id: "betik_deneme_ad", value: "FATURA_20260930.csv" });
  const ekDegerler = h("textarea", { rows: 2, class: "mono", style: { minHeight: "52px" }, placeholder: "G_TARIH=20260930\nP_OLAY=FATURA_GELDI" });
  const testSonuc = h("div", { class: "deneme-sonuc" });
  const testDurum = h("div", { class: "test-durum" });
  const icerikOzeti = () => kisaOzet(`${dilSec.value}\n${ed.ta.value}`);
  const betikVerisi = () => ({ hedef_id: x ? x.id : undefined, dil: dilSec.value, kod: ed.ta.value, zaman_asimi_sn: +zamanAsimi.value || 30,
    sirlar: sirlar.filter(s => s.ad).map(s => ({ ad: s.ad, deger: s.deger || undefined })) });
  const ornekVerisi = () => {
    const ek = satirlarAyristir(ekDegerler.value, "=", "Ek değer");
    for (const k of Object.keys(ek)) if (!/^[GP]_[A-Z0-9_]+$/.test(k)) throw new Error(`Ek değer adı G_… (regex grubu) ya da P_… (kural değeri) ile başlamalı, büyük harf: ${k}`);
    return { dosya_adi: denemeAd.value.trim(), ek };
  };
  const kuruDeneme = async () => {
    try { const r = await API.post("/api/betik/dene", { ...betikVerisi(), ornek: ornekVerisi(), calistir: false });
      testSonuc.replaceChildren(h("div", { class: "sessiz", style: { fontSize: "12px" } }, "Kuru deneme (betik çalıştırılmadı): betiğe verilecekler"), ...ortamTablosu(r)); }
    catch (e) { testSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
  };
  const canliCalistir = () => {
    let veri; try { veri = { ...betikVerisi(), ornek: ornekVerisi(), calistir: true }; } catch (e) { return testSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
    canliOnayi(`Editördeki ${BETIK_DILLERI[veri.dil].ad} betiği (kaydedilmemiş hâliyle) bu sunucuda, servisin hesabıyla GERÇEKTEN çalışacak; '${veri.ornek.dosya_adi}' dosyası gelmiş gibi. Dış sistemlerde işlem yapabilir (API çağrısı, dosya yazma…).`, async () => {
      testSonuc.replaceChildren(h("div", { class: "satir sessiz" }, h("div", { class: "ilerleme belirsiz", style: { width: "120px", marginTop: 0 } }, h("i", {})), "Çalışıyor…"));
      const ozet = icerikOzeti();
      try { const r = await API.post("/api/betik/dene", veri); sonTest = { ozet, sonuc: r.sonuc, cikis: r.cikis_kodu };
        testSonuc.replaceChildren(h("div", { class: "sessiz", style: { fontSize: "12px", marginBottom: "4px" } }, `ÇALIŞTIRILDI · dosya: ${veri.ornek.dosya_adi}`), ...betikSonucu(r)); }
      catch (e) { testSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
      guncelle();
    });
  };
  const sozdizimi = async () => {
    denetimEl.replaceChildren(h("span", { class: "sessiz" }, "Denetleniyor…"));
    try { const r = await API.post("/api/betik/denetle", { dil: dilSec.value, kod: ed.ta.value });
      ed.isaretle(r.gecerli ? [] : [r.satir]);
      denetimEl.replaceChildren(h("span", { class: `yanit ${r.gecerli ? "ok" : "bad"}` }, `${r.gecerli ? "✓" : "✗"} ${r.mesaj}`)); }
    catch (e) { denetimEl.replaceChildren(h("span", { class: "alan hata" }, e.message)); }
  };
  const calistirDg = dugme("Canlı çalıştır…", { ikon: "oynat", kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI", ipucu: "Betiği bu sunucuda gerçekten çalıştırır (kilit açık olmalı)", onclick: canliCalistir });

  function uyar() {
    const u = betikUyarilari(dilSec.value, ed.ta.value, sirlar.map(s => s.ad).filter(Boolean));
    uyariEl.replaceChildren(...u.map(m => h("div", {}, ikon("uyari", 14), h("span", {}, m))));
  }
  function guncelle() {
    const kilitli = !kilitAcik;
    ed.kilitle(kilitli);
    [ad, dilSec, ornekSec, zamanAsimi, eszamanli, ...sirListe.querySelectorAll("input, button")].forEach(el => { el.disabled = kilitli; });
    sirEkleDg.disabled = kilitli; calistirDg.disabled = kilitli || !yetkili("YONETICI");
    if (kaydetDg) kaydetDg.disabled = kilitli;
    const d = diller[dilSec.value];
    yorumlayici.textContent = d ? `${d.surum} · ${d.komut}` : "";
    onsoz.classList.toggle("gizli", dilSec.value !== "powershell");
    const ayni = sonTest && sonTest.ozet === icerikOzeti();
    testDurum.className = `test-durum ${ayni ? (sonTest.sonuc === "BASARI" ? "ok" : "bad") : "warn"}`;
    testDurum.textContent = ayni ? `Bu içerik canlı denendi: ${(BETIK_SONUC[sonTest.sonuc] || [sonTest.sonuc])[0]} (çıkış ${sonTest.cikis ?? "—"})`
      : sonTest ? "Betik son canlı testten sonra değişti: yeniden denemeniz önerilir." : "Bu içerik henüz canlı denenmedi.";
  }
  const sirEkleDg = dugme("Gizli değer ekle", { ikon: "arti", kucuk: true, onclick: () => { sirlar.push({ ad: "", kayitli: false, deger: "" }); sirCiz(); sirListe.querySelector(".sir-satir:last-child input").focus(); } });
  dilSec.addEventListener("change", () => { uyar(); guncelle(); });
  ornekSec.addEventListener("change", () => { const o = BETIK_ORNEKLERI[+ornekSec.value]; ornekSec.value = ""; if (!o) return;
    if (ed.ta.value.trim() && !confirm("Editördeki betik örnekle değiştirilsin mi?")) return;
    dilSec.value = o.dil; ed.ta.value = o.kod; ed.ta.dispatchEvent(new Event("input")); });
  ed.ta.addEventListener("input", () => { uyar(); guncelle(); ed.isaretle([]); denetimEl.replaceChildren(); });
  const kilit = betikKilidi(d => { kilitAcik = !!d.kilit_acik; diller = d.diller || {}; guncelle(); });

  const bolum = (baslik, ...icerik) => h("div", { class: "betik-bolum" }, h("h4", { class: "bolum-baslik" }, baslik), ...icerik);
  const sat = (a_, b_, c_) => h("tr", {}, h("td", {}, a_), h("td", {}, b_), h("td", {}, c_));
  sirCiz(); uyar();
  pencere({ baslik: x ? `Betik hedefi: ${x.ad}` : "Hedef ekle · Betik", ikon: "kod", tur: "acc", genis: "cok", icerik: h("div", {},
    kilit.el,
    h("div", { class: "iki-sutun betik-izgara" },
      h("div", {},
        h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", { for: "betik_ad" }, "Ad"), ad),
          h("div", { class: "alan" }, h("label", { for: "betik_dil" }, "Dil"), dilSec)),
        h("div", { class: "alan" }, h("div", { class: "satir" }, h("label", { for: "betik_kod", style: { margin: 0, fontWeight: 600, fontSize: "12.8px" } }, "Betik"),
          h("div", { style: { marginLeft: "auto" } }, ornekSec)), ed.el, yorumlayici, uyariEl,
          h("div", { class: "satir", style: { marginTop: "8px" } }, dugme("Sözdizimini denetle", { ikon: "onay", kucuk: true, rol: "YONETICI", ipucu: "Betiği çalıştırmadan derler / ayrıştırır", onclick: sozdizimi }), denetimEl)),
        onsoz,
        bolum("Betiğe giden veriler",
          h("div", { class: "ipucu", style: { marginBottom: "6px" } }, "Tıklayınca okuma kodu imlecin olduğu yere eklenir. Aynı bilgiler stdin'den JSON olarak da gelir. Dosya adı betik metnine asla yazılmaz (komut enjeksiyonu olmaz)."),
          degiskenler,
          h("table", { class: "tablo ortam-tablo", style: { marginTop: "8px" } }, h("tbody", {},
            h("tr", {}, h("td", {}, "FWP_G_<GRUP>"), h("td", {}, "Kuralın regex grupları (büyük harf), ör. (?P<tarih>…) → FWP_G_TARIH")),
            h("tr", {}, h("td", {}, "FWP_P_<AD>"), h("td", {}, "Kuralda tanımlanan ek değerler; aynı betiği farklı kurallar farklı değerlerle kullanır")),
            h("tr", {}, h("td", {}, "FWP_SIR_<AD>"), h("td", {}, "Gizli değerler (yalnız ortam değişkeni; stdin'de yok)")))))),
      h("div", {},
        bolum("Gizli değerler", h("div", { class: "ipucu", style: { marginBottom: "6px" } }, "Şifre / token betiğe yazılmaz: buraya girilir, DPAPI ile şifrelenir, FWP_SIR_<AD> olarak verilir, çıktıda *** ile maskelenir."),
          sirListe, h("div", { style: { marginTop: "6px" } }, sirEkleDg)),
        bolum("Çalıştırma", h("div", { class: "satir" },
          h("div", { class: "alan" }, h("label", {}, "Zaman aşımı (sn)"), zamanAsimi), h("div", { class: "alan" }, h("label", {}, "Aynı anda en fazla"), eszamanli),
          h("div", { class: "ipucu", style: { flex: 1, minWidth: "180px" } }, "Süre dolunca betik ve başlattığı tüm süreçler sonlandırılır. Her dosya ayrı süreçte çalışır."))),
        h("details", { class: "yardim", open: x ? null : true }, h("summary", {}, ikon("soru", 15), " Hata sözleşmesi: betik nasıl yazılmalı?"),
          h("div", { class: "yardim-ic" },
            h("table", { class: "tablo yardim-tablo sozlesme" }, h("tbody", {},
              sat("0", "Başarılı", "İletildi"),
              sat("10", "Kalıcı hata", "Yeniden denenmez; lokale yazılır + KRİTİK alarm"),
              sat("diğer (1, 2…)", "Geçici hata", "5 / 10 / 15 sn sonra yeniden denenir; olmazsa lokale + alarm"),
              sat("süre doldu", "Belirsiz", "Süreç ağacı sonlandırılır; yeniden denenir, 'olası çift' işaretlenir"),
              sat("başlatılamadı", "Kalıcı hata", "Yorumlayıcı bulunamadı"))),
            h("ul", { class: "sonuc-listesi" },
              h("li", {}, h("b", {}, "Sade yazın. "), "Yeniden deneme, zaman aşımı, kayıt, lokale yazma ve alarm sistemin işi; betik içinde döngüyle yeniden denemeyin (çift tetik ve süre aşımı riski)."),
              h("li", {}, h("b", {}, "Tek kural: hatayı yutmayın. "), "Python'da yakalanmayan hata zaten 1 ile çıkar. PowerShell'e sistem 'Stop' ekler. curl'de durum kodunu kendiniz denetleyin (örneklerde var)."),
              h("li", {}, h("b", {}, "İsterseniz: "), "kalıcı hatayı (ör. HTTP 400/404: yanlış iş adı) exit 10 ile bildirin; boşuna yeniden denenmez."),
              h("li", {}, h("b", {}, "Aynı tetik yeniden çalışabilir "), "(özellikle süre dolunca): karşı API destekliyorsa FWP_KIMLIK'i Idempotency-Key olarak gönderin."),
              h("li", {}, "stdout / stderr kaydedilir (son 64 KB); sonucu etkilemez, yalnız çıkış kodu belirler.")))),
        bolum("Canlı test",
          h("div", { class: "satir", style: { alignItems: "flex-start" } },
            h("div", { class: "alan gen" }, h("label", { for: "betik_deneme_ad" }, "Deneme dosya adı"), denemeAd),
            h("div", { class: "alan gen" }, h("label", {}, "Ek değerler (isteğe bağlı)"), ekDegerler)),
          h("div", { class: "satir" },
            dugme("Kuru deneme", { ikon: "goz", kucuk: true, rol: "YONETICI", ipucu: "Betiğe verilecek ortam değişkenlerini ve stdin'i gösterir; çalıştırmaz", onclick: kuruDeneme }), calistirDg),
          testSonuc)))),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: x ? "Değişiklikleri kaydet" : "Hedefi ekle", sinif: "ana", basari: x ? "Betik güncellendi" : "Betik hedefi eklendi", ref: b => { kaydetDg = b; b.disabled = true; },
      eylem: () => { const v = { ad: ad.value, tur: "BETIK", adres: "", ayrintilar: { ...betikVerisi(), eszamanli: +eszamanli.value || 1 } }; delete v.ayrintilar.hedef_id;
        return x ? API.put(`/api/hedefler/${x.id}`, v) : API.post("/api/hedefler", v); } }] });
  // kaydet düğmesinin yanında test durumu
  if (kaydetDg) kaydetDg.parentNode.insertBefore(testDurum, kaydetDg.parentNode.firstChild);
  guncelle();
}
