/* FileWatcherPro önyüzü — kütüphanesiz, internetsiz. Tüm veriler /api/... uç noktalarından gelir.
   Prototip modu (dosyadan açılınca ya da ?prototip): prototip.js örnek verili sahte arka ucu yükler. */
"use strict";

// ====================================================================== yardımcılar
const $ = (s, el = document) => el.querySelector(s);
function h(etiket, oz, ...cocuklar) {
  const el = document.createElement(etiket);
  for (const [k, v] of Object.entries(oz || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  ekle(el, cocuklar);
  return el;
}
function ekle(el, c) {
  if (c === null || c === undefined || c === false) return;
  if (Array.isArray(c)) { c.forEach(x => ekle(el, x)); return; }
  el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
}
const IKONLAR = {
  panel: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  dosya: "M6 3h8l4 4v14H6zM14 3v4h4",
  kutu: "M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10",
  uyari: "M12 3l10 18H2zM12 10v5M12 18h.01",
  klasor: "M3 6h6l2 2h10v11H3z",
  hedef: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
  eklenti: "M9 3h6v4h3a2 2 0 0 1 2 2v3h-4v6h4v3a2 2 0 0 1-2 2h-3v-4H9v4H6a2 2 0 0 1-2-2v-3h4v-6H4V9a2 2 0 0 1 2-2h3z",
  zil: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4",
  liste: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  ayar: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19.4 13a7.6 7.6 0 0 0 0-2l2-1.5-2-3.5-2.4 1a7.4 7.4 0 0 0-1.7-1L15 3h-4l-.3 2.9a7.4 7.4 0 0 0-1.7 1l-2.4-1-2 3.5 2 1.5a7.6 7.6 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7.4 7.4 0 0 0 1.7 1L11 21h4l.3-2.9a7.4 7.4 0 0 0 1.7-1l2.4 1 2-3.5z",
  durdur: "M7 5h4v14H7zM13 5h4v14h-4z",
  oynat: "M7 4l13 8-13 8z",
  kare: "M6 6h12v12H6z",
  yenile: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  arti: "M12 5v14M5 12h14",
  cop: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  ara: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  carpi: "M6 6l12 12M18 6L6 18",
  onay: "M5 12l5 5 9-10",
  kalkan: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  cikis: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11",
  gunes: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  ay: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  kilit: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  kilit_acik: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 7.6-1.8",
  kod: "M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14",
  baglanti: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  bilgi: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 8h.01",
  simsek: "M13 2L4 14h7l-1 8 9-12h-7z",
  saat: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  erit: "M4 6h16M6 12h12M9 18h6",
  motor: "M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8",
  indir: "M12 4v11M7 10l5 5 5-5M5 20h14",
  zarf: "M3 6h18v12H3zM3 7l9 6 9-6",
  nabiz: "M3 12h4l2-5 4 10 2-5h6",
  islemci: "M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  kalem: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  gonder: "M4 12l16-8-6 16-2-6z",
  soru: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01",
  sihir: "M4 20L16 8M14 4v2M20 10h-2M18 6l-1 1M10 4l.5 1.5M4 10l1.5.5",
  goz: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  yz: "M10 3l1.9 5.1L17 10l-5.1 1.9L10 17l-1.9-5.1L3 10l5.1-1.9zM18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z",
};
function ikon(ad, boyut = 16) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", boyut); s.setAttribute("height", boyut);
  s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.9");
  s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", IKONLAR[ad] || ""); s.appendChild(p);
  return s;
}
const nf = new Intl.NumberFormat("tr-TR");
const sayi = n => (n === null || n === undefined) ? "—" : nf.format(n);
function sureMetni(ms) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} sn`;
  return `${Math.floor(ms / 60000)} dk ${Math.round((ms % 60000) / 1000)} sn`;
}
function once(ts) {
  if (!ts) return "—";
  const f = Math.max(0, Date.now() / 1000 - ts);
  if (f < 5) return "az önce";
  if (f < 60) return `${Math.floor(f)} sn önce`;
  if (f < 3600) return `${Math.floor(f / 60)} dk önce`;
  if (f < 86400) return `${Math.floor(f / 3600)} sa önce`;
  return `${Math.floor(f / 86400)} gün önce`;
}
const saat = ts => ts ? new Date(ts * 1000).toLocaleTimeString("tr-TR") : "—";
const tarihSaat = ts => ts ? new Date(ts * 1000).toLocaleString("tr-TR") : "—";
const ondalik = (v, n) => v.toLocaleString("tr-TR", { minimumFractionDigits: n, maximumFractionDigits: n });
const boyutMetni = b => b === null || b === undefined ? "—" : b < 1024 ? `${b} B` : b < 1048576 ? `${ondalik(b / 1024, 1)} KB` : b < 1073741824 ? `${ondalik(b / 1048576, 1)} MB` : `${ondalik(b / 1073741824, 2)} GB`;
const rozet = (metin, sinif, oz = {}) => h("span", { class: `rozet ${sinif || ""}`, ...oz }, metin);

// ====================================================================== durum eşlemleri
const HEDEF_ETIKET = h_ => {
  if (!h_.aktif && h_.kapatma_modu === "KAYITSIZ") return { e: "Kapalı · kayıtsız", s: "bad", i: "bad", a: "Gelen dosyalar hedefe gönderilmiyor ve saklanmıyor." };
  if (!h_.aktif) return { e: "Kapalı · kayıtlı", s: "warn", i: "warn", a: "Gelen dosyalar lokale yazılıyor; açınca kademeli erit ile gönderilir." };
  if (h_.devre_durumu === "KESILDI") return { e: "Devre kesik", s: "bad", i: "bad", a: "Art arda yanıt vermedi; yeni tetikler denenmeden lokale yazılıyor." };
  if (h_.tekrar > 0 || h_.ardisik_hata > 0) return { e: "Hata alıyor", s: "warn", i: "warn", a: "Bazı çağrılar yeniden deneniyor." };
  return { e: "Açık", s: "ok", i: "ok", a: "Tetikler canlı olarak gönderiliyor." };
};
const DIZIN_ETIKET = { ERISILEBILIR: ["Erişilebilir", "ok"], DENENIYOR: ["Yeniden deneniyor", "warn"], ERISILEMEZ: ["Erişilemiyor", "bad"], YANITSIZ: ["Yanıt vermiyor", "bad"], BILINMIYOR: ["Henüz taranmadı", ""] };
const EKLENTI_ETIKET = { CALISIYOR: ["Çalışıyor", "ok"], BASLIYOR: ["Başlıyor", "info"], DURDURULUYOR: ["Durduruluyor", "warn"], DURDURULDU: ["Durduruldu", ""], DUSTU: ["Düştü · yeniden başlatılıyor", "warn"], ELLE_MUDAHALE: ["Elle müdahale bekliyor", "bad"], KAPANDI: ["Kapalı", ""] };
const TETIK_ETIKET = { SILINDI: ["Elle silindi", "bad"], BEKLIYOR: ["Bekliyor", "info"], DENENIYOR: ["Gönderiliyor", "acc"], TEKRAR: ["Yeniden denenecek", "warn"], ILETILDI: ["İletildi", "ok"], LOKALDE: ["Lokalde", "warn"], ERITILIYOR: ["Eritiliyor", "acc"], KAYITSIZ_KAPALI: ["Gönderilmedi (kayıtsız)", "bad"] };
const YUKLEME_ETIKET = { YAZILIYOR: ["Yazılıyor", "info"], KILITLI: ["Yazan süreç tutuyor", "info"], ASKIDA: ["Askıda", "warn"], GECICI_AD: ["Geçici adla yükleniyor", "info"], OKUNAMIYOR: ["Okunamıyor", "warn"] };
const SEBEP_METNI = {
  SLA_SON_DOLDU: "Deneme planı bitti (hedef yanıt vermedi)", KALICI_HATA: "Kalıcı hata (yapılandırma kontrol edilmeli)",
  HEDEF_KAPALI_KAYITLI: "Hedef kayıtlı kapalıydı", HEDEF_KAPALI_KAYITSIZ: "Hedef kayıtsız kapalıydı",
  KURAL_KAPALI_KAYITLI: "Kural kayıtlı kapalıydı", KURAL_KAPALI_KAYITSIZ: "Kural kayıtsız kapalıydı",
  DEVRE_KESIK: "Devre kesikti", ESLESMEDI: "Hiçbir kurala uymadı", LOKAL_KAYIT_BOZUK: "Lokal kayıt dosyası bozuk",
};
const etiketli = (tablo, anahtar) => { const [e, s] = tablo[anahtar] || [anahtar || "—", ""]; return rozet(e, s); };

// ====================================================================== API
class ApiHata extends Error { constructor(kod, mesaj) { super(mesaj); this.kod = kod; } }
const API = {
  async istek(yontem, yol, govde) {
    if (window.PROTOTIP) return window.PROTOTIP.istek(yontem, yol, govde);
    let r;
    try {
      r = await fetch(yol, { method: yontem, credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-FWP": "1" }, body: govde === undefined ? undefined : JSON.stringify(govde) });
    } catch (_) {
      throw new ApiHata(0, "FileWatcherPro'ya ulaşılamıyor. Servis çalışıyor mu? Ağ bağlantısını kontrol edin.");
    }
    let v = null; try { v = await r.json(); } catch (_) { /* boş gövde */ }
    // JSON olmayan 404/405/501: bu adreste FileWatcherPro kontrol arayüzü yok (ör. yalnızca dosya sunucusu)
    if (!v && [404, 405, 501].includes(r.status))
      throw new ApiHata(r.status, "Bu adreste FileWatcherPro çalışmıyor. Doğru adresi açın (varsayılan http://127.0.0.1:8770) ya da tasarımı görmek için adrese ?prototip ekleyin.");
    if (r.status === 401 && yol !== "/api/giris") { D.ben = null; girisCiz(); }
    if (!r.ok) throw new ApiHata(r.status, (v && v.hata) || `Sunucu hatası (HTTP ${r.status})`);
    return v;
  },
  get: y => API.istek("GET", y), post: (y, g) => API.istek("POST", y, g || {}), put: (y, g) => API.istek("PUT", y, g || {}),
  sil: y => API.istek("DELETE", y),
};

// ====================================================================== uygulama durumu
const ROLLER = ["IZLEYICI", "OPERATOR", "YONETICI"];
const ROL_ADI = { IZLEYICI: "İzleyici", OPERATOR: "Operatör", YONETICI: "Yönetici" };
const D = { ben: null, durum: null, sayfa: "genel", akis: null, veri: {}, cekmece: null, filtre: {} };
const yetkili = rol => D.ben && ROLLER.indexOf(D.ben.rol) >= ROLLER.indexOf(rol);

function dugme(metin, { ikon: ik, sinif = "", onclick, rol, ipucu, kucuk, devre_disi } = {}) {
  const izin = !rol || yetkili(rol);
  const b = h("button", { class: `dg ${sinif} ${kucuk ? "kucuk" : ""}`, type: "button", onclick: izin && !devre_disi ? onclick : null,
    title: !izin ? `Bu işlem için ${ROL_ADI[rol]} yetkisi gerekir` : (ipucu || null), disabled: !izin || devre_disi }, ik ? ikon(ik) : null, metin);
  return b;
}
function bildirim(metin, tur = "", sure = null) {
  const b = h("div", { class: `bildirim ${tur}`, role: "status" }, ikon(tur === "bad" ? "uyari" : tur === "ok" ? "onay" : "bilgi"), h("div", {}, metin));
  $("#bildirimler").appendChild(b);
  setTimeout(() => b.remove(), sure || (tur === "bad" ? 8000 : 4500));
}
async function eylem(fn, basari) {
  try { const r = await fn(); if (basari) bildirim(basari, "ok"); await sayfaYenile(); return r; }
  catch (e) { bildirim(e.message, "bad"); throw e; }
}

// ====================================================================== tema
function temaUygula(t) { document.documentElement.dataset.tema = t; try { localStorage.setItem("fwp_tema", t); } catch (_) {} }
function temaBaslat() {
  let t = null; try { t = localStorage.getItem("fwp_tema"); } catch (_) {}
  if (!t) t = matchMedia("(prefers-color-scheme: dark)").matches ? "koyu" : "acik";
  temaUygula(t);
}

// ====================================================================== giriş
function girisCiz(hata) {
  if (D.akis) { D.akis.close && D.akis.close(); D.akis = null; }
  const kok = $("#kok"); kok.innerHTML = "";
  const ad = h("input", { type: "text", id: "g_ad", autocomplete: "username", required: true });
  const sifre = h("input", { type: "password", id: "g_sifre", autocomplete: "current-password", required: true });
  const hataEl = h("div", { class: "alan hata", role: "alert" }, hata || "");
  const form = h("form", { class: "kart ki", style: { padding: "22px" }, onsubmit: async e => {
    e.preventDefault(); hataEl.textContent = "";
    try { D.ben = await API.post("/api/giris", { kullanici: ad.value.trim(), sifre: sifre.value }); sifre.value = ""; basla(); }
    catch (er) { hataEl.textContent = er.message; sifre.select(); }
  } },
    h("div", { class: "alan" }, h("label", { for: "g_ad" }, "Kullanıcı adı"), ad),
    h("div", { class: "alan" }, h("label", { for: "g_sifre" }, "Şifre"), sifre),
    hataEl, h("button", { class: "dg ana", type: "submit", style: { width: "100%", padding: "10px" } }, "Giriş yap"));
  kok.appendChild(h("div", { class: "giris-sayfa" }, h("div", { class: "giris-kutu" },
    h("div", { class: "logo" }, ikon("kalkan", 26), "FileWatcherPro"), form,
    h("p", { class: "sessiz", style: { textAlign: "center", fontSize: "12.5px" } }, "Her işlem kullanıcı adınızla denetim kaydına yazılır."))));
  setTimeout(() => ad.focus(), 0);
}

// ====================================================================== iskelet
const SAYFALAR = [
  { k: "genel", ad: "Genel bakış", ikon: "panel", ciz: sayfaGenel, canli: true },
  { k: "dosyalar", ad: "Dosyalar", ikon: "dosya", ciz: sayfaDosyalar, canli: true },
  { k: "lokal", ad: "Lokal kayıt ve erit", ikon: "kutu", ciz: sayfaLokal, canli: true },
  { k: "gonderilemeyen", ad: "Gönderilemeyenler", ikon: "uyari", ciz: sayfaGonderilemeyen },
  { g: "Yapılandırma" },
  { k: "dizinler", ad: "Dizinler ve kurallar", ikon: "klasor", ciz: sayfaDizinler, canli: true },
  { k: "hedefler", ad: "Hedefler", ikon: "hedef", ciz: sayfaHedefler, canli: true },
  { k: "ayarlar", ad: "Ayarlar", ikon: "ayar", ciz: sayfaAyarlar },
  { g: "Sistem" },
  { k: "eklentiler", ad: "Eklentiler", ikon: "eklenti", ciz: sayfaEklentiler, canli: true },
  { k: "izleme", ad: "Sistem izleme", ikon: "nabiz", ciz: sayfaIzleme, canli: true },
  { k: "asistan", ad: "Yapay zekâ asistanı", ikon: "yz", ciz: sayfaAsistan, canli: true, kosul: asistanVar },   // asistan eklentisi varsa
  { k: "alarmlar", ad: "Alarmlar", ikon: "zil", ciz: sayfaAlarmlar, canli: true },
  { k: "bildirimler", ad: "Bildirimler (mail)", ikon: "zarf", ciz: sayfaBildirimler },
  { k: "denetim", ad: "Denetim kaydı", ikon: "liste", ciz: sayfaDenetim },
];

function iskeletCiz() {
  const kok = $("#kok"); kok.innerHTML = "";
  kok.appendChild(h("div", { class: "uygulama" },
    h("header", { class: "ust" },
      h("div", { class: "logo" }, ikon("kalkan", 22), "FileWatcherPro"),
      h("div", { id: "genel_durum" }),
      h("div", { class: "bosluk" }),
      h("div", { id: "motor_ust" }),
      h("div", { id: "acil_ust" }),
      h("button", { class: "dg hayalet", title: "Tema", "aria-label": "Tema değiştir",
        onclick: () => { temaUygula(document.documentElement.dataset.tema === "koyu" ? "acik" : "koyu"); ustCiz(); } }, ikon(document.documentElement.dataset.tema === "koyu" ? "gunes" : "ay")),
      h("div", { class: "satir", style: { gap: "8px" } },
        h("div", { style: { textAlign: "right", lineHeight: "1.2" } }, h("div", { style: { fontWeight: 600 } }, D.ben.kullanici),
          h("div", { class: "sessiz", style: { fontSize: "12px" } }, ROL_ADI[D.ben.rol])),
        h("button", { class: "dg hayalet", title: "Şifre değiştir", "aria-label": "Şifre değiştir", onclick: () => sifrePenceresi() }, ikon("kilit")),
        h("button", { class: "dg hayalet", title: "Çıkış", "aria-label": "Çıkış", onclick: async () => { await API.post("/api/cikis"); D.ben = null; girisCiz(); } }, ikon("cikis")))),
    h("nav", { class: "yan", id: "yan", "aria-label": "Menü" }),
    h("main", { class: "icerik", id: "icerik" }, h("div", { id: "seritler" }), h("div", { id: "sayfa" }))));
}

function menuCiz() {
  const yan = $("#yan"); if (!yan) return;
  const ogeler = [];
  const du = D.durum || {}; const say = du.sayilar || {};
  const alarmlar = du.alarmlar || [];
  const kritik = alarmlar.filter(a => a.seviye === "KRITIK").length;
  const rozetler = { lokal: say.lokalde ? [say.lokalde, "sari"] : null, alarmlar: alarmlar.length ? [alarmlar.length, kritik ? "kirmizi" : "sari"] : null,
    gonderilemeyen: say.cozulmemis ? [say.cozulmemis, ""] : null, dosyalar: say.yukleniyor ? [say.yukleniyor, ""] : null,
    eklentiler: (du.eklentiler || []).some(e => ["ELLE_MUDAHALE", "DUSTU"].includes(e.durum)) ? ["!", "kirmizi"] : null };
  for (const s of SAYFALAR) {
    if (s.g) { ogeler.push(h("div", { class: "grup" }, s.g)); continue; }
    if (s.kosul && !s.kosul()) continue;
    const r = rozetler[s.k];
    ogeler.push(h("a", { href: `#/${s.k}`, class: D.sayfa === s.k ? "secili" : "" }, ikon(s.ikon), s.ad, r ? h("span", { class: `say ${r[1]}` }, r[0]) : null));
  }
  degistir(yan, ogeler);
}

function genelSaglik(du) {
  const kritik = (du.alarmlar || []).filter(a => a.seviye === "KRITIK");
  const uyari = (du.alarmlar || []).filter(a => a.seviye !== "KRITIK");
  if (kritik.length) return { e: `Kritik: ${kritik.length} sorun`, s: "bad" };
  if (uyari.length) return { e: `Dikkat: ${uyari.length} uyarı`, s: "warn" };
  return { e: "Her şey yolunda", s: "ok" };
}

function ustCiz() {
  const du = D.durum; if (!du || !$("#genel_durum")) return;
  bakimTakipEt();
  if ($("#seritler")) degistir($("#seritler"), seritler(du));           // kriz şeritleri: her sayfada, her canlı güncellemede
  const g = genelSaglik(du);
  degistir($("#genel_durum"), rozet(g.e, `${g.s} nabiz`, { style: { fontSize: "12.5px", padding: "4px 11px" } }));
  degistir($("#motor_ust"), h("label", { class: "anahtar", title: du.motor ? "Tarama motoru çalışıyor" : "Tarama motoru durduruldu" },
    h("input", { type: "checkbox", checked: du.motor, disabled: !yetkili("OPERATOR"), onchange: e => { e.preventDefault(); e.target.checked = du.motor; motorPenceresi(); } }),
    h("span", { class: "yol" }), du.motor ? "Motor çalışıyor" : "Motor durdu"));
  const acik = (du.hedefler || []).filter(x => x.aktif);
  degistir($("#acil_ust"), !(du.hedefler || []).length ? h("span") : acik.length
    ? dugme("Gönderimi durdur (tüm hedefler)", { ikon: "durdur", sinif: "tehlike-cizgi", rol: "OPERATOR", onclick: () => kapatPenceresi(null) })
    : dugme("Gönderimi yeniden başlat", { ikon: "oynat", sinif: "ana", rol: "OPERATOR", onclick: () => acPenceresi(null) }));
}

function seritler(du) {
  const s = [];
  if (D.ben && D.ben.varsayilan_sifre)
    s.push(h("div", { class: "serit uyari", role: "alert" }, ikon("kilit", 20), h("div", { class: "metin" },
      h("b", {}, "Varsayılan şifre kullanılıyor. "), "Bu hesabın şifresi hâlâ ilk kurulumdaki şifre; aynı ağdaki herkes tahmin edebilir."),
      dugme("Şifreyi değiştir", { ikon: "kilit", sinif: "ana", onclick: () => sifrePenceresi() })));
  for (const x of du.hedefler || []) {
    if (!x.aktif && x.kapatma_modu === "KAYITSIZ")
      s.push(h("div", { class: "serit kayitsiz", role: "alert" }, ikon("uyari", 20), h("div", { class: "metin" },
        h("b", {}, `${x.ad} kayıtsız kapalı. `), `Bu sürede gelen dosyalar hedefe gönderilmiyor ve saklanmıyor. Kapatan: ${x.kapatan || "?"}, ${once(x.kapatma_zamani)}.`),
        dugme("Gönderimi aç", { ikon: "oynat", sinif: "ana", rol: "OPERATOR", onclick: () => acPenceresi(x) })));
    else if (x.devre_durumu === "KESILDI")
      s.push(h("div", { class: "serit kritik", role: "alert" }, ikon("simsek", 20), h("div", { class: "metin" },
        h("b", {}, `${x.ad}: devre kesik. `), `Art arda yanıt vermedi; yeni dosyalar denenmeden lokale yazılıyor (${sayi(x.lokalde)} kayıt). `,
        x.saglik ? h("span", { class: "sessiz" }, `Son yoklama: ${x.saglik.startsWith("YANIT_VERIYOR") ? "yanıt veriyor ✓" : "yanıt yok"} (${once(x.saglik_zamani)})`) : null),
        dugme("Devreyi normale al", { ikon: "yenile", rol: "OPERATOR", onclick: () => devrePenceresi(x) })));
  }
  for (const d of du.dizinler || []) {
    if (["ERISILEMEZ", "YANITSIZ"].includes(d.erisim_durumu))
      s.push(h("div", { class: "serit kritik", role: "alert" }, ikon("klasor", 20), h("div", { class: "metin" },
        h("b", {}, `Dizine erişilemiyor: ${d.yol}. `), "Durum korunuyor; dizin geri gelince bu sürede gelen dosyalar yakalanacak. ",
        h("span", { class: "sessiz" }, d.son_hata || "")), dugme("Şimdi dene", { ikon: "yenile", rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/dizinler/${d.id}/simdi_dene`), "Yeniden deneniyor") })));
  }
  if (du.motor === false)
    s.push(h("div", { class: "serit uyari" }, ikon("durdur", 20), h("div", { class: "metin" }, h("b", {}, "Tarama motoru durduruldu. "),
      "Yeni dosyalar şu an fark edilmiyor; motor başlayınca bu sürede gelenler yakalanır."), dugme("Motoru başlat", { ikon: "oynat", sinif: "ana", rol: "OPERATOR", onclick: () => motorPenceresi() })));
  return s;
}

// ====================================================================== yönlendirme ve çizim
function sayfaBul() { return SAYFALAR.find(s => s.k === D.sayfa) || SAYFALAR[0]; }
// bir işlemden sonra: veriyi beklemeden yeniden çek (canlı çizimdeki 3 sn sınırı uygulanmaz)
async function sayfaYenile() {
  try { D.durum = await API.get("/api/durum?taze=1"); } catch (_) {}
  const s = sayfaBul(); if (s.ciz) { await s.ciz(false); } menuCiz(); ustCiz();
}
function rotaDegisti() {
  const k = (location.hash.match(/^#\/([a-z_]+)/) || [])[1] || "genel";
  D.sayfa = SAYFALAR.some(s => s.k === k && (!s.kosul || s.kosul())) ? k : "genel";
  D.veri = {}; cekmeceKapat();
  menuCiz(); const icerik = $("#icerik"), sayfa = $("#sayfa"); if (icerik) icerik.scrollTop = 0; if (sayfa) sayfa.innerHTML = "";
  sayfaBul().ciz(false);
}
/* Canlı veri her saniye gelir. Tıklama kaybolmasın diye: (1) fare/dokunma basılıyken yeniden çizim ertelenir,
   (2) yeni içerik eskisiyle aynıysa DOM'a hiç dokunulmaz (düğmeler ve olay dinleyicileri yerinde kalır). */
let basili = false, bekleyenCizim = null;
document.addEventListener("pointerdown", () => { basili = true; }, true);
document.addEventListener("pointerup", () => { basili = false; if (bekleyenCizim) { const f = bekleyenCizim; bekleyenCizim = null; setTimeout(f, 0); } }, true);
document.addEventListener("pointercancel", () => { basili = false; }, true);
function degistir(el, dugumler) {
  const gecici = document.createElement("div"); gecici.append(...[].concat(dugumler).filter(Boolean));
  if (gecici.innerHTML === el.innerHTML) return false;
  el.replaceChildren(...gecici.childNodes);
  return true;
}
function icerikYaz(dugumler) {
  const el = $("#icerik"), sayfa = $("#sayfa"); if (!el || !sayfa) return;
  const odak = document.activeElement && el.contains(document.activeElement) && document.activeElement.id ? document.activeElement : null;
  const secim = odak && "selectionStart" in odak ? [odak.selectionStart, odak.selectionEnd] : null;
  const kaydir = el.scrollTop;
  if (!degistir(sayfa, dugumler)) return;
  el.scrollTop = kaydir;
  if (odak) { const yeni = document.getElementById(odak.id); if (yeni) { yeni.focus(); if (secim) try { yeni.setSelectionRange(...secim); } catch (_) {} } }
}
function baslik(ad, aciklama, sag) {
  return h("div", { class: "sayfa-baslik" }, h("div", {}, h("h1", {}, ad), aciklama ? h("div", { class: "aciklama" }, aciklama) : null), sag ? h("div", { class: "sag" }, sag) : null);
}
const kart = (baslikMetni, icerik, sag, oz = {}) => h("section", { class: "kart", ...oz },
  baslikMetni ? h("div", { class: "kb" }, h("h2", {}, baslikMetni), sag ? h("div", { class: "sag" }, sag) : null) : null,
  h("div", { class: `ki ${oz.sifir ? "sifir" : ""}` }, icerik));
const bosDurum = (ik, metin) => h("div", { class: "bos" }, ikon(ik, 28), metin);

// ====================================================================== GENEL BAKIŞ
function sayfaGenel() {
  const du = D.durum; if (!du) return icerikYaz(bosDurum("saat", "Yükleniyor…"));
  const say = du.sayilar || {}; const sla = du.sla || {};
  const p95 = sla.p95_ms; const hedefMs = (sla.hedef_sn || 10) * 1000;
  const kpi = (ad, deger, alt, sinif, ik) => h("div", { class: `kart kpi ${sinif || ""}` }, h("div", { class: "ad" }, ik ? ikon(ik, 14) : null, ad), h("div", { class: "deger" }, deger), h("div", { class: "alt" }, alt));
  icerikYaz([
    baslik("Genel bakış", `Son güncelleme ${saat(du.zaman)} · canlı`),
    h("div", { class: "izgara k6" },
      kpi("Bugün iletilen", sayi(say.iletildi || 0), `${sayi(say.eritildi || 0)} kademeli eritten`, "ok", "onay"),
      kpi("Gönderim bekleyen", sayi(say.bekleyen || 0), "kuyrukta ya da yeniden denenecek", say.bekleyen ? "warn" : "", "saat"),
      kpi("Lokalde bekleyen", sayi(say.lokalde || 0), say.lokalde ? "erit bekliyor" : "yok", say.lokalde ? "warn" : "", "kutu"),
      kpi("Yükleniyor", sayi(say.yukleniyor || 0), say.askida ? `${say.askida} askıda` : "tamamlanınca tetiklenir", say.askida ? "warn" : "", "dosya"),
      kpi("Tetik süresi (p95)", p95 === null || p95 === undefined ? "—" : sureMetni(p95), `hedef ${sla.hedef_sn} sn · son ${sayi(sla.n || 0)} tetik`, p95 > hedefMs ? "bad" : "", "simsek"),
      kpi("Gönderilemeyen", sayi(say.cozulmemis || 0), "çözülmemiş kayıt", say.cozulmemis ? "warn" : "", "uyari")),
    h("div", { class: "bolum" }, h("div", { class: "izgara k2" },
      kart("Hedefler", (du.hedefler || []).length ? h("div", {}, ...(du.hedefler || []).map(hedefOzet)) : bosDurum("hedef", "Tanımlı hedef yok."),
        dugme("Hepsini gör", { kucuk: true, sinif: "hayalet", onclick: () => { location.hash = "#/hedefler"; } })),
      kart("Aktif alarmlar", alarmListesi((du.alarmlar || []).slice(0, 6)), dugme("Tümü", { kucuk: true, sinif: "hayalet", onclick: () => { location.hash = "#/alarmlar"; } }), { sifir: true }))),
    h("div", { class: "bolum" }, kart("İzlenen dizinler", dizinTablosu(du.dizinler || []), null, { sifir: true })),
    h("div", { class: "bolum" }, h("div", { class: "izgara k2" },
      kart("Bileşenler", eklentiOzet(du.eklentiler || []), dugme("Ayrıntı", { kucuk: true, sinif: "hayalet", onclick: () => { location.hash = "#/eklentiler"; } }), { sifir: true }),
      kart("Bakım ve kayıt", bakimOzet(du))))
  ]);
}
function hedefOzet(x) {
  const e = HEDEF_ETIKET(x);
  return h("div", { style: { padding: "4px 0 14px", borderBottom: "1px solid var(--line)", marginBottom: "12px" } },
    h("div", { class: "satir" }, h("span", { class: `isik ${e.i}`, style: { width: "10px", height: "10px", borderRadius: "50%", display: "inline-block" } }),
      h("b", {}, x.ad), rozet(e.e, e.s), x.erit_durumu === "CALISIYOR" ? rozet("Eritiliyor", "acc nabiz") : null,
      h("span", { style: { marginLeft: "auto" }, class: "sessiz mono" }, x.tur)),
    h("div", { class: "sessiz", style: { margin: "4px 0 0 20px", fontSize: "12.8px" } }, e.a),
    h("div", { class: "olcu-sirasi", style: { marginLeft: "20px" } },
      olcu(x.yolda, "yolda"), olcu(x.bekleyen, "bekleyen"), olcu(x.lokalde, "lokalde"), olcu(x.ardisik_hata, "ardışık hata")));
}
const olcu = (n, e) => h("div", { class: "olcu" }, h("div", { class: "n" }, sayi(n || 0)), h("div", { class: "e" }, e));
function alarmListesi(liste) {
  if (!liste.length) return bosDurum("onay", "Aktif alarm yok.");
  return h("div", {}, ...liste.map(a => h("div", { class: `alarm ${a.seviye}` }, h("div", { class: "sol" }),
    h("div", { class: "m" }, h("div", {}, a.mesaj), h("div", { class: "z" }, `${a.seviye === "KRITIK" ? "Kritik" : a.seviye === "UYARI" ? "Uyarı" : "Bilgi"} · ${a.kaynak} · ${once(a.son_zaman)}${a.tekrar > 1 ? ` · ${a.tekrar} kez` : ""}`)),
    dugme("Onayla", { kucuk: true, rol: "OPERATOR", ipucu: "Alarmı kapatır; sorun sürerse yeniden açılır",
      onclick: () => eylem(() => API.post(`/api/alarmlar/${a.id}/onayla`), "Alarm onaylandı") }))));
}
function dizinTablosu(dizinler) {
  if (!dizinler.length) return bosDurum("klasor", "İzlenen dizin yok. 'Dizinler ve kurallar' sayfasından ekleyin.");
  return h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Dizin", "Erişim", "Son tarama", "Liste süresi", "Aktif dosya", "Yükleniyor", "Kural", ""].map(t => h("th", {}, t)))),
    h("tbody", {}, ...dizinler.map(d => h("tr", {},
      h("td", {}, h("div", { class: "mono" }, d.yol), d.aktif ? null : rozet("İzleme kapalı", ""),
        (d.kurallar || []).length ? h("div", { class: "dizin-kurallari" }, ...d.kurallar.map(k => h("span", { class: "dizin-kurali" },
          h("span", { class: `isik ${k.aktif ? "ok" : k.kapatma_modu === "KAYITSIZ" ? "bad" : "warn"}` }),
          h("b", {}, k.ad), h("span", { class: "sessiz" }, k.aktif ? ` → ${k.hedef_ad || "?"}` : ` · durduruldu (${k.kapatma_modu === "KAYITSIZ" ? "kayıtsız" : "kayıtlı"})`),
          k.aktif ? dugme("Durdur", { kucuk: true, sinif: "hayalet", rol: "OPERATOR", ipucu: "Bu kuralı durdur", onclick: () => kapatPenceresi(null, k) })
            : dugme("Aç", { kucuk: true, sinif: "hayalet", rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/kurallar/${k.id}/ac`), "Kural açıldı") })))) : null),
      h("td", {}, etiketli(DIZIN_ETIKET, d.erisim_durumu)),
      h("td", { class: "ikincil" }, once(d.son_tarama)),
      h("td", { class: "sayi" }, d.son_tarama_ms === null || d.son_tarama_ms === undefined ? "—" : `${d.son_tarama_ms} ms`),
      h("td", { class: "sayi" }, sayi(d.aktif_dosya)),
      h("td", { class: "sayi" }, sayi(d.yukleniyor), d.askida ? h("span", {}, " ", rozet(`${d.askida} askıda`, "warn")) : null),
      h("td", { class: "sayi" }, sayi(d.kural_sayisi), d.kapali_kural ? h("span", { class: "sessiz" }, ` (${d.kapali_kural} kapalı)`) : null),
      h("td", { style: { textAlign: "right" } }, dugme("Şimdi dene", { kucuk: true, sinif: "hayalet", ikon: "yenile", rol: "OPERATOR",
        onclick: () => eylem(() => API.post(`/api/dizinler/${d.id}/simdi_dene`), "Dizin yeniden taranıyor") })))))));
}
function eklentiOzet(ek) {
  return h("div", { class: "tablo-sar" }, h("table", { class: "tablo" }, h("tbody", {}, ...ek.map(e => h("tr", {},
    h("td", {}, h("b", {}, EKLENTI_ADI[e.ad] || e.ad), h("div", { class: "sessiz", style: { fontSize: "12px" } }, e.ad === "cekirdek" ? "gözetmen" : e.modul)),
    h("td", {}, etiketli(EKLENTI_ETIKET, e.durum)),
    h("td", { class: "ikincil" }, e.son_nabiz ? `nabız ${once(e.son_nabiz)}` : "—"),
    h("td", { class: "sayi sessiz" }, e.yeniden_baslatma ? `${e.yeniden_baslatma} yeniden başlatma` : ""))))));
}
const EKLENTI_ADI = { cekirdek: "Çekirdek", tarama: "Tarama", teslim: "Teslim", kontrol: "Kontrol arayüzü", izleme: "Sistem izleme", bildirim: "Bildirim (mail)", asistan: "Yapay zekâ asistanı" };
// ---------------------------------------------------------------------- bakım: sonuç metni, kart, takip, geçmiş
const BUDAMA_ADI = { dosya: "dosya", tetik: "tetik", alarm: "alarm", komut: "komut", gonderilemeyen: "gönderilemeyen", denetim: "denetim", kesinti: "kesinti" };
function bakimMetni(son) {
  const budanan = Object.entries({ ...(son.budama_canli || {}), ...(son.budama_hata || {}) })
    .filter(([k, v]) => BUDAMA_ADI[k] && typeof v === "number" && v > 0).map(([k, v]) => `${sayi(v)} ${BUDAMA_ADI[k]}`);
  const boyut = x => !x ? "—" : x.once_mb !== undefined && Math.abs(x.once_mb - x.boyut_mb) >= 0.05
    ? `${ondalik(x.once_mb, 1)} → ${ondalik(x.boyut_mb, 1)} MB` : `${ondalik(x.boyut_mb, 1)} MB`;
  return { budanan: budanan.length ? budanan.join(", ") : "budanacak eski kayıt yoktu", canli: boyut(son.canli), hata: boyut(son.hata) };
}
const bakimBaslatan = k => !k || k === "zamanlayıcı" ? "zamanlanmış" : k;
/* Başarısız bakımın açıklaması: hangi adım geri alındı, sistem etkilendi mi (eski kayıtlarda yalnız hata metni vardır). */
function bakimHataMetni(son) {
  const hata = son.hata_mesaji || (typeof son.hata === "string" ? son.hata : "") || "bilinmeyen hata";
  if (son.hatali_adim === "on_kontrol") return `Bakım başlamadı: ön bütünlük kontrolü geçmedi (${hata}). Hiçbir değişiklik yapılmadı.`;
  if (son.geri_alinan) return `'${son.geri_alinan}' adımı hata verdi ve geri alındı; kalan adımlar yapılmadı. ${son.sistem_etkilenmedi ? "Veritabanı bakımdan önceki çalışan hâliyle sürüyor, izleme etkilenmedi." : "Son kontrol sorunlu: Alarmlar'a bakın."} Hata: ${hata}`;
  return hata;
}
function bakimOzet(du) {
  const b = du.bakim || {}; const son = b.son; const sur = b.suruyor;
  const m = son ? bakimMetni(son) : null;
  const durumRozet = sur ? rozet(`Sürüyor · ${once(sur.basladi)} başladı`, "acc nabiz") : !son ? null
    : son.durum === "TAMAM" ? rozet("Başarılı", "ok") : rozet("Başarısız", "bad");
  return h("dl", { class: "bilgi-izgara", style: { margin: 0 } },
    h("dt", {}, "Son bakım"), h("dd", {}, son ? `${tarihSaat(son.basladi)} · ${sureMetni(son.sure_ms)} · ${bakimBaslatan(son.kullanici)} ` : "henüz yapılmadı ", durumRozet),
    son && son.durum !== "TAMAM" ? [h("dt", {}, "Hata"), h("dd", { style: { color: "var(--bad)" } }, bakimHataMetni(son))] : null,
    m ? [h("dt", {}, "Budanan"), h("dd", {}, m.budanan)] : null,
    h("dt", {}, "canli.db"), h("dd", {}, m ? m.canli : "—"),
    h("dt", {}, "hata.db"), h("dd", {}, m ? m.hata : "—"),
    h("dt", {}, "Sonraki bakım"), h("dd", {}, tarihSaat(b.sonraki)),
    h("dt", {}, ""), h("dd", {}, h("div", { class: "satir" },
      dugme(sur ? "Bakım sürüyor…" : "Şimdi bakım yap", { kucuk: true, ikon: "yenile", rol: "OPERATOR", devre_disi: !!sur, onclick: bakimBaslat }),
      dugme("Bakım geçmişi", { kucuk: true, sinif: "hayalet", onclick: bakimGecmisi }))));
}
async function bakimBaslat() {
  const onceki = ((D.durum || {}).bakim || {}).son;
  try { await API.post("/api/bakim"); } catch (e) { return bildirim(e.message, "bad"); }
  D.bakimTakip = { baslangic: Date.now(), onceki: onceki ? onceki.basladi : 0 };
  bildirim("Bakım başlatıldı (budama, REINDEX, ANALYZE, WAL checkpoint). Bitince sonucu bildireceğim.");
  await sayfaYenile();
}
/* Her canlı güncellemede çağrılır: başlatılan bakımın sonucu gelince bildirir (hangi sayfada olunursa olunsun). */
function bakimTakipEt() {
  const t = D.bakimTakip; if (!t || !D.durum) return;
  const b = D.durum.bakim || {}; const son = b.son;
  if (son && son.basladi > t.onceki && !b.suruyor) {
    D.bakimTakip = null;
    const m = bakimMetni(son);
    if (son.durum === "TAMAM") bildirim(`Bakım bitti · başarılı · ${sureMetni(son.sure_ms)}. Budanan: ${m.budanan}. canli.db ${m.canli} · hata.db ${m.hata}.`, "ok", 12000);
    else bildirim(`Bakım başarısız · ${bakimHataMetni(son)}`, "bad", 15000);
  } else if (Date.now() - t.baslangic > 180000) {
    D.bakimTakip = null;
    bildirim("Bakım 3 dakikadır bitmedi ya da sonucu gelmedi. Genel bakış → Bakım geçmişi ve Alarmlar sayfasına bakın.", "bad", 15000);
  }
}
async function bakimGecmisi() {
  let liste;
  try { liste = await API.get("/api/bakim/gecmis"); } catch (e) { return bildirim(e.message, "bad"); }
  const b = ((D.durum || {}).bakim) || {};
  pencere({ baslik: "Bakım geçmişi", ikon: "yenile", tur: "acc", genis: true, icerik: h("div", {},
    h("p", { style: { marginTop: 0 } }, "Bakım sırası: ", h("b", {}, "1)"), " bütünlük kontrolü (sorun varsa bakım başlamaz), ", h("b", {}, "2)"),
      " son sağlam kopya (veri\\yedek), ", h("b", {}, "3)"), ` budama (son ${sayi(b.gecmis_limit || 200)} dosya/tetik geçmişi, çözülmüşlerden ${sayi(b.hata_limit || 1000)} gönderilemeyen; aktif ve çözülmemiş kayıtlar asla silinmez), `,
      h("b", {}, "4)"), " REINDEX + ANALYZE, ", h("b", {}, "5)"), " WAL checkpoint ve boş alanı geri verme, ", h("b", {}, "6)"), " son bütünlük kontrolü."),
    h("p", {}, h("b", {}, "Hata olursa: "), "her adım kendi işlemi içinde yapılır; hata veren adım tamamen geri alınır (veritabanı o adımdan önceki çalışan hâlinde kalır), kalan adımlar yapılmaz, uyarı alarmı açılır. Tarama ve teslim bakım boyunca çalışmaya devam eder."),
    h("p", { class: "ikincil" }, `Planlı bakım: her ${b.gun || "hafta"} ${b.saat || ""} · sonraki ${tarihSaat(b.sonraki)}.`),
    liste.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Zaman", "Başlatan", "Sonuç", "Süre", "Budanan", "canli.db", "hata.db"].map(x => h("th", {}, x)))),
      h("tbody", {}, ...liste.map(r => { const s = r.sonuc || {}; const m = bakimMetni(s);
        return h("tr", {}, h("td", { class: "ikincil", style: { whiteSpace: "nowrap" } }, tarihSaat(r.zaman)), h("td", {}, bakimBaslatan(r.kullanici)),
          h("td", { style: { maxWidth: "320px" } }, s.durum === "TAMAM" ? rozet("Başarılı", "ok") : h("span", {}, rozet(s.geri_alinan ? "Adım geri alındı" : "Başarısız", "bad"), h("div", { class: "sessiz", style: { fontSize: "12px" } }, bakimHataMetni(s)))),
          h("td", { class: "sayi" }, sureMetni(s.sure_ms)), h("td", { class: "ikincil" }, m.budanan), h("td", { class: "sayi" }, m.canli), h("td", { class: "sayi" }, m.hata)); })))) :
      bosDurum("yenile", "Henüz bakım yapılmadı.")),
    dugmeler: [{ metin: "Kapat", sinif: "hayalet" }] });
}

// ====================================================================== DOSYALAR
async function sayfaDosyalar(yenileme) {
  const sekme = D.filtre.dosya_sekme || "yukleniyor";
  if (!yenileme || sekme === "yukleniyor" || Date.now() - (D.veri.dosya_zaman || 0) > 3000) {
    try {
      D.veri.yuklemeler = await API.get("/api/yuklemeler");
      const q = new URLSearchParams(); if (D.filtre.ara) q.set("ara", D.filtre.ara);
      D.veri.dosyalar = await API.get(`/api/dosyalar?${q}`); D.veri.dosya_zaman = Date.now();
    } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  if (D.sayfa !== "dosyalar") return;
  const y = D.veri.yuklemeler || [], f = D.veri.dosyalar || [];
  const ara = h("div", { class: "arama" }, ikon("ara"), h("input", { type: "text", id: "ara_dosya", placeholder: "Dosya adında ara…", value: D.filtre.ara || "",
    oninput: e => { D.filtre.ara = e.target.value; clearTimeout(D._araZ); D._araZ = setTimeout(() => { D.veri.dosya_zaman = 0; sayfaDosyalar(true); }, 300); } }));
  const sekmeler = h("div", { class: "sekme", role: "tablist" },
    ...[["yukleniyor", `Yükleniyor (${y.length})`], ["son", `Son dosyalar (${f.length})`]].map(([k, e]) =>
      h("button", { class: sekme === k ? "secili" : "", role: "tab", onclick: () => { D.filtre.dosya_sekme = k; sayfaDosyalar(true); } }, e)));
  let govde;
  if (sekme === "yukleniyor") {
    govde = y.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Dosya", "Dizin", "Durum", "Boyut", "İlk görülme", "Son büyüme", "Açıklama"].map(t => h("th", {}, t)))),
      h("tbody", {}, ...y.map(r => h("tr", {}, h("td", { class: "mono" }, r.dosya_adi), h("td", { class: "mono sessiz" }, r.dizin_yolu),
        h("td", {}, etiketli(YUKLEME_ETIKET, r.durum)), h("td", { class: "sayi" }, boyutMetni(r.boyut)),
        h("td", { class: "ikincil" }, once(r.ilk_gorulme)), h("td", { class: "ikincil" }, once(r.son_buyume)), h("td", { class: "ikincil" }, r.aciklama || "")))))) :
      bosDurum("dosya", "Şu an yüklenmekte olan dosya yok.");
    govde = [h("p", { class: "ikincil", style: { marginTop: 0 } }, "Buradaki dosyalar henüz yeni dosya sayılmaz ve tetiklenmez. Yazılması bittiğinde (boyut sabit, yazan süreç dosyayı bırakmış, hash alınmış) tek bir tetik üretilir. Çok uzun süren yüklemeler 'Askıda' olarak işaretlenir ve alarm verir."), kart(null, govde, null, { sifir: true })];
  } else {
    govde = f.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Dosya", "Kural → hedef", "Tetik", "Süre", "Deneme", "Boyut", "Hazır"].map(t => h("th", {}, t)))),
      h("tbody", {}, ...f.map(r => h("tr", { class: "tik", onclick: () => dosyaCekmecesi(r) },
        h("td", { class: "mono" }, r.dosya_adi, r.durum === "ESLESMEDI" ? h("span", {}, " ", rozet("kurala uymadı", "")) : null, r.durum === "TEMEL" ? h("span", {}, " ", rozet("ilk kurulumda vardı", "")) : null),
        h("td", { class: "ikincil" }, r.kural_ad ? `${r.kural_ad} → ${r.hedef_ad}` : "—"),
        h("td", {}, r.tetik_durum ? etiketli(TETIK_ETIKET, r.tetik_durum) : "—", r.belirsiz ? h("span", { title: "Cevap gelmeden bağlantı koptu; hedef işi iki kez yapmış olabilir" }, " ", rozet("olası çift", "warn")) : null),
        h("td", { class: "sayi" }, r.sure_ms !== null && r.sure_ms !== undefined ? h("span", { style: { color: r.sla_ihlali ? "var(--bad)" : null } }, sureMetni(r.sure_ms)) : "—"),
        h("td", { class: "sayi" }, r.deneme_sayisi ?? "—"),
        h("td", { class: "sayi" }, boyutMetni(r.boyut)),
        h("td", { class: "ikincil" }, once(r.hazir_zamani))))))) : bosDurum("dosya", "Kayıt yok.");
    govde = [kart(null, govde, null, { sifir: true }), h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Dizinde duran dosyalar ve son 200 geçmiş kayıt gösterilir. Satıra tıklayınca dosyanın zaman çizelgesi açılır.")];
  }
  icerikYaz([baslik("Dosyalar", "Yüklenmekte olan ve son işlenen dosyalar", ara), sekmeler, ...[].concat(govde)]);
}
async function dosyaCekmecesi(r) {
  let t = null;
  if (r.tetik_id) { try { t = (await API.get(`/api/tetikler?id=${r.tetik_id}`))[0] || null; } catch (_) {} }
  const gecmis = t ? JSON.parse(t.deneme_gecmisi || "[]") : [];
  const olaylar = [
    { s: "", z: r.ilk_gorulme, m: "Dizinde görüldü (yükleniyor)" },
    { s: "acc", z: r.hazir_zamani, m: `Tamamlandı · kimlik belirlendi${r.icerik_hash ? " (xxh3 hash)" : " (eşik üstü: ad+boyut+tarih)"}${r.hash_suresi_ms ? ` · hash ${sureMetni(r.hash_suresi_ms)}` : ""}` },
    ...gecmis.map(g => ({ s: g.tur === "BASARI" ? "ok" : g.tur === "KALICI" ? "bad" : "warn", z: g.z, m: `${g.erit ? "Erit: " : ""}${g.tur === "BASARI" ? "Hedef kabul etti" : g.tur === "GECICI" ? "Geçici hata" : g.tur === "BELIRSIZ" ? "Sonuç belirsiz (cevap gelmedi)" : "Kalıcı hata"} · ${g.mesaj || ""} · ${sureMetni(g.ms)}` })),
    t && t.durum === "LOKALDE" ? { s: "warn", z: null, m: `Lokalde bekliyor: ${SEBEP_METNI[t.sebep] || t.sebep || ""}` } : null,
    r.icerik_degisim ? { s: "", z: r.son_icerik_degisimi, m: `İçerik değişti${r.icerik_degisim > 1 ? ` (${r.icerik_degisim} kez)` : ""} · yeni geliş sayılmaz, tetik yok; güncel hâli esas alındı` } : null,
    r.kalkma_zamani ? { s: "", z: r.kalkma_zamani, m: "Dizinden kalktı" } : null,
  ].filter(Boolean);
  const c = h("aside", { class: "cekmece", role: "dialog", "aria-label": "Dosya ayrıntısı" },
    h("div", { class: "cb" }, ikon("dosya", 18), h("h3", { class: "mono" }, r.dosya_adi), h("div", { style: { marginLeft: "auto" } }, h("button", { class: "dg hayalet", "aria-label": "Kapat", onclick: cekmeceKapat }, ikon("carpi")))),
    h("div", { class: "ci" },
      h("dl", { class: "bilgi-izgara" },
        h("dt", {}, "Tam yol"), h("dd", { class: "mono" }, r.tam_yol),
        h("dt", {}, "Boyut"), h("dd", {}, boyutMetni(r.boyut)),
        h("dt", {}, "Kural → hedef"), h("dd", {}, r.kural_ad ? `${r.kural_ad} → ${r.hedef_ad}` : (r.durum === "ESLESMEDI" ? "Hiçbir kurala uymadı" : "—")),
        h("dt", {}, "Tetik durumu"), h("dd", {}, t ? etiketli(TETIK_ETIKET, t.durum) : "—"),
        h("dt", {}, "Hazır → iletim"), h("dd", {}, t && t.sure_ms !== null ? `${sureMetni(t.sure_ms)}${t.sla_ihlali ? " (SLA hedefi aşıldı)" : ""}` : "—"),
        h("dt", {}, "İçerik hash'i"), h("dd", { class: "mono" }, r.icerik_hash || "—"),
        h("dt", {}, "Idempotency"), h("dd", { class: "mono" }, t ? t.idempotency : "—"),
        t && t.lokal_dosya ? [h("dt", {}, "Lokal kayıt"), h("dd", { class: "mono" }, t.lokal_dosya)] : null,
        t && t.belirsiz ? [h("dt", {}, "Uyarı"), h("dd", {}, rozet("Olası çift", "warn"), " Cevap gelmeden bağlantı koptu ya da süre doldu; hedef bu işi iki kez yapmış olabilir. FWP_KIMLIK değişkeniyle ayırt edilebilir.")] : null),
      h("h4", { style: { margin: "6px 0 10px" } }, "Zaman çizelgesi"),
      h("ul", { class: "cizelge" }, ...olaylar.map(o => h("li", { class: o.s }, h("span", { class: "n" }), h("div", {}, o.m), h("div", { class: "z" }, o.z ? `${tarihSaat(o.z)}` : ""))))));
  cekmeceKapat(); D.cekmece = c; document.body.appendChild(c);
}
function cekmeceKapat() { if (D.cekmece) { D.cekmece.remove(); D.cekmece = null; } }

// ====================================================================== LOKAL KAYIT VE ERİT
async function sayfaLokal(yenileme) {
  if (!yenileme || Date.now() - (D.veri.lokal_zaman || 0) > 1500) {
    try { D.veri.lokal = await API.get("/api/tetikler?durum=LOKALDE&limit=1000"); D.veri.lokal_zaman = Date.now(); }
    catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  if (D.sayfa !== "lokal") return;
  const du = D.durum || {}; const liste = D.veri.lokal || [];
  const kartlar = (du.hedefler || []).map(x => {
    const e = HEDEF_ETIKET(x); const toplam = x.lokalde + x.eritiliyor;
    const hiz = x.erit_hizi || 5;
    const erit = x.erit_durumu;
    const eritDugmeleri = erit === "CALISIYOR"
      ? [dugme("Duraklat", { ikon: "durdur", rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/hedefler/${x.id}/erit`, { islem: "duraklat" }), "Erit duraklatıldı") }),
         dugme("Durdur", { ikon: "kare", sinif: "hayalet", rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/hedefler/${x.id}/erit`, { islem: "durdur" }), "Erit durduruldu") })]
      : [dugme(erit === "DURAKLATILDI" ? "Eriti sürdür" : "Kademeli erit başlat", { ikon: "erit", sinif: "ana", rol: "OPERATOR", devre_disi: !toplam || !x.aktif || x.devre_durumu !== "NORMAL",
          ipucu: !x.aktif ? "Önce hedefi açın" : x.devre_durumu !== "NORMAL" ? "Önce devreyi normale alın" : !toplam ? "Lokalde kayıt yok" : null, onclick: () => eritPenceresi(x) })];
    return kart(x.ad, h("div", {},
      h("div", { class: "satir" }, rozet(e.e, e.s), erit === "CALISIYOR" ? rozet(`Eritiliyor · ${hiz}/sn`, "acc nabiz") : erit === "DURAKLATILDI" ? rozet("Erit duraklatıldı", "warn") : null),
      h("div", { class: "olcu-sirasi" }, olcu(x.lokalde, "lokalde"), olcu(x.eritiliyor, "şu an gönderiliyor"), olcu(x.bekleyen, "canlı bekleyen")),
      erit === "CALISIYOR" && toplam ? h("div", { class: "sessiz", style: { marginTop: "10px", fontSize: "12.8px" } }, `Tahmini bitiş: ~${sureMetni(Math.ceil(toplam / hiz) * 1000)} · canlı tetikler önce gönderilir`) : null,
      h("div", { class: "satir", style: { marginTop: "14px" } }, ...eritDugmeleri)));
  });
  // seçim (sayfa canlı yenilense de korunur); hedef süzgeci
  const secim = D.lokalSecim = D.lokalSecim || new Set();
  const varolan = new Set(liste.map(t => t.id));
  [...secim].forEach(i => { if (!varolan.has(i)) secim.delete(i); });
  const filtre = D.lokalFiltre || "";
  const gorunen = liste.filter(t => !filtre || String(t.hedef_id) === filtre);
  const yeniden = () => sayfaLokal(true);
  const hepsiKutu = h("input", { type: "checkbox", "aria-label": "Görünenlerin hepsini seç", checked: gorunen.length && gorunen.every(t => secim.has(t.id)) ? true : null,
    onchange: e => { gorunen.forEach(t => e.target.checked ? secim.add(t.id) : secim.delete(t.id)); yeniden(); } });
  const hedefSuzgec = h("select", { "aria-label": "Hedefe göre süz", onchange: e => { D.lokalFiltre = e.target.value; yeniden(); } },
    h("option", { value: "" }, "Tüm hedefler"), ...[...new Map(liste.map(t => [String(t.hedef_id), t.hedef_ad])).entries()].map(([i, a]) =>
      h("option", { value: i, selected: i === filtre ? true : null }, a)));
  const arac = h("div", { class: "satir lokal-arac" }, hedefSuzgec, h("span", { class: "sessiz", id: "lokal_secili" }, `${secim.size} seçili`),
    dugme("Seçilenleri gönder", { ikon: "gonder", kucuk: true, rol: "OPERATOR", devre_disi: !secim.size, ipucu: "Seçilen kayıtları şimdi hedefine gönder (süper yönetici kilidi)",
      onclick: () => lokalGonderPenceresi([...secim]) }),
    dugme("Seçilenleri sil", { ikon: "cop", kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI", devre_disi: !secim.size, ipucu: "Seçilen kayıtları sil: hedefe hiç gönderilmez (tutanaklı, süper yönetici kilidi)",
      onclick: () => lokalSilPenceresi([...secim]) }),
    secim.size ? dugme("Seçimi temizle", { kucuk: true, sinif: "hayalet", onclick: () => { secim.clear(); yeniden(); } }) : null);
  const tablo = gorunen.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, h("th", { style: { width: "34px" } }, hepsiKutu), ...["Sıra", "Dosya", "Hedef", "Sebep", "Deneme", "Lokale yazılma", "Lokal dosya"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...gorunen.slice().reverse().map((t, i) => h("tr", { class: secim.has(t.id) ? "secili-satir" : null },
      h("td", {}, h("input", { type: "checkbox", "aria-label": `${t.dosya_adi} seç`, checked: secim.has(t.id) ? true : null,
        onchange: e => { e.target.checked ? secim.add(t.id) : secim.delete(t.id); yeniden(); } })),
      h("td", { class: "sayi sessiz" }, i + 1), h("td", { class: "mono" }, t.dosya_adi), h("td", {}, t.hedef_ad),
      h("td", {}, SEBEP_METNI[t.sebep] || t.sebep || "—"), h("td", { class: "sayi" }, t.deneme_sayisi),
      h("td", { class: "ikincil" }, once(t.olusturma)), h("td", { class: "mono sessiz" }, t.lokal_dosya ? "✓ yazıldı" : h("span", { style: { color: "var(--bad)" } }, "yazılamadı (veritabanında güvende)"))))))) :
    bosDurum("kutu", "Lokalde bekleyen kayıt yok.");
  icerikYaz([baslik("Lokal kayıt ve kademeli erit", "Hedefe gönderilemeyen ya da kapalıyken gelen tetikler burada güvende bekler. Eritme geliş sırasıyla ve hız sınırıyla yapılır."),
    h("div", { class: "izgara k2" }, ...kartlar), h("div", { class: "bolum" }, kart(`Bekleyen kayıtlar (${liste.length}) · geliş sırasıyla`, h("div", {}, liste.length ? arac : null, tablo), null, { sifir: true }))]);
}
function lokalSecimOzeti(idler) {
  const l = (D.veri.lokal || []).filter(t => idler.includes(t.id));
  const say = {};
  l.forEach(t => { say[t.hedef_ad] = (say[t.hedef_ad] || 0) + 1; });
  return [l, h("div", {}, h("div", { class: "ikincil" }, Object.entries(say).map(([a, n]) => `${a}: ${n}`).join(" · ")),
    h("ul", { class: "sonuc-listesi" }, ...l.slice(0, 8).map(t => h("li", { class: "mono" }, t.dosya_adi)),
      l.length > 8 ? h("li", { class: "sessiz" }, `… ve ${l.length - 8} kayıt daha`) : null))];
}
function lokalGonderPenceresi(idler) {
  let b_;
  const kilit = betikKilidi(d => { if (b_) b_.disabled = !d.kilit_acik; });
  const [l, ozet] = lokalSecimOzeti(idler);
  pencere({ baslik: `Seçilenleri gönder (${l.length})`, ikon: "gonder", tur: "acc", genis: true, icerik: h("div", {}, kilit.el,
    h("p", { style: { marginTop: 0 } }, `${l.length} lokal kayıt şimdi hedefine gönderilecek (erit gibi, SLA istatistiğine girmez).`), ozet,
    h("div", { class: "ipucu" }, "Hedef kapalıysa, devre kesikse ya da yine hata verirse kayıt lokale geri döner; kaybolmaz. İşlem, gönderilen her kayıtla birlikte denetim kaydına yazılır.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Gönder", sinif: "ana", devre_disi: true, ref: b => { b_ = b; },
      eylem: async () => { const r = await API.post("/api/lokal/gonder", { idler });
        r.gonderilen.forEach(i => D.lokalSecim.delete(i));
        bildirim(`${r.gonderilen.length} kayıt gönderime alındı${r.atlanan.length ? ` · ${r.atlanan.length} kayıt artık lokalde değildi` : ""}`, "ok"); } }] });
}
function lokalSilPenceresi(idler) {
  let b_, kilitAcik = false, anladim = false;
  const neden = h("textarea", { rows: 2, id: "lokal_sil_neden", style: { minHeight: "56px" }, placeholder: "Örn. yanlış kuralla tetiklenmiş deneme dosyaları; muhasebe ekibi onayladı (talep no …)" });
  const guncelle = () => { if (b_) b_.disabled = !(kilitAcik && anladim && neden.value.trim().length >= 5); };
  neden.addEventListener("input", guncelle);
  const kilit = betikKilidi(d => { kilitAcik = !!d.kilit_acik; guncelle(); });
  const [l, ozet] = lokalSecimOzeti(idler);
  pencere({ baslik: `Seçilenleri sil (${l.length})`, ikon: "cop", tur: "bad", genis: true, icerik: h("div", {}, kilit.el,
    h("p", { style: { marginTop: 0 } }, h("b", {}, `${l.length} lokal kayıt silinecek: bu dosyalar hedefe HİÇ gönderilmeyecek.`)), ozet,
    h("div", { class: "alan" }, h("label", { for: "lokal_sil_neden" }, "Neden (zorunlu; tutanağa ve denetime yazılır)"), neden),
    h("div", { class: "serit bilgi", style: { margin: "0 0 10px" } }, ikon("kilit", 18), h("div", { class: "metin" },
      "Kayıtlar izsiz kaybolmaz: silmeden önce tutanak (kim, ne zaman, neden, her kaydın tam içeriği) veri\\lokal_silinen klasörüne yazılır, lokal dosyalar oraya taşınır, işlem denetim kaydına işlenir.")),
    h("label", { class: "satir", style: { fontWeight: 600, color: "var(--bad)" } }, h("input", { type: "checkbox", onchange: e => { anladim = e.target.checked; guncelle(); } }),
      "Bu dosyaların hedefe hiç gönderilmeyeceğini anladım.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Kalıcı olarak sil", sinif: "tehlike", devre_disi: true, ref: b => { b_ = b; },
      eylem: async () => { const r = await API.post("/api/lokal/sil", { idler, neden: neden.value });
        r.silinen.forEach(i => D.lokalSecim.delete(i));
        bildirim(`${r.silinen.length} kayıt silindi · tutanak: ${r.tutanak.split(/[\\/]/).pop()}${r.atlanan.length ? ` · ${r.atlanan.length} kayıt atlandı` : ""}`, r.atlanan.length ? "bad" : "ok"); } }] });
}

// ====================================================================== GÖNDERİLEMEYENLER
async function sayfaGonderilemeyen(yenileme) {
  const f = D.filtre.gon || { cozuldu: "0", sebep: "" };
  if (!yenileme || !D.veri.gon) {
    const q = new URLSearchParams(); if (f.cozuldu !== "") q.set("cozuldu", f.cozuldu); if (f.sebep) q.set("sebep", f.sebep);
    try { D.veri.gon = await API.get(`/api/gonderilemeyen?${q}`); } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  const liste = D.veri.gon;
  const secim = (ad, deger, secenekler, degis) => h("select", { "aria-label": ad, onchange: e => { degis(e.target.value); D.veri.gon = null; sayfaGonderilemeyen(false); } },
    ...secenekler.map(([v, e]) => h("option", { value: v, selected: v === deger }, e)));
  const filtre = h("div", { class: "satir" },
    secim("Durum", f.cozuldu, [["0", "Çözülmemiş"], ["1", "Çözülmüş"], ["", "Hepsi"]], v => { D.filtre.gon = { ...f, cozuldu: v }; }),
    secim("Sebep", f.sebep, [["", "Tüm sebepler"], ...Object.entries(SEBEP_METNI)], v => { D.filtre.gon = { ...f, sebep: v }; }),
    dugme("CSV indir", { ikon: "indir", onclick: () => csvIndir(liste) }));
  const tablo = liste.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Dosya", "Sebep", "Ayrıntı", "Hedef", "Deneme", "İlk", "Son", "Durum"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...liste.map(g => h("tr", {}, h("td", { class: "mono" }, g.dosya_adi), h("td", {}, SEBEP_METNI[g.sebep] || g.sebep),
      h("td", { class: "ikincil", style: { maxWidth: "380px" } }, g.sebep_detay || ""), h("td", {}, g.hedef_ad || "—"), h("td", { class: "sayi" }, g.deneme_sayisi),
      h("td", { class: "ikincil" }, once(g.ilk_zaman)), h("td", { class: "ikincil" }, once(g.son_zaman)),
      h("td", {}, g.cozuldu ? rozet(g.cozum === "ERIT" ? "Eritildi" : g.cozum === "KAYITSIZ_KAPATMA" ? "Bilerek gönderilmedi" : "Çözüldü", g.cozum === "KAYITSIZ_KAPATMA" ? "bad" : "ok") : rozet("Bekliyor", "warn"))))))) :
    bosDurum("onay", "Bu filtreye uyan kayıt yok.");
  icerikYaz([baslik("Gönderilemeyenler", "Hedefe gitmeme sebebi olan dosyalar (son 1000; çözülmemişler asla silinmez)", filtre), kart(null, tablo, null, { sifir: true })]);
}
/* CSV hücresi: = + - @ ile başlayan metin Excel'de formül olarak çalışmasın diye başına ' eklenir (dosya adı ve sunucu
   yanıtı dışarıdan gelir). */
function csvHucre(v) {
  let s = String(v ?? "");
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return `"${s.replace(/"/g, '""')}"`;
}
function csvIndir(liste) {
  const alanlar = ["dosya_adi", "tam_yol", "sebep", "sebep_detay", "hedef_ad", "deneme_sayisi", "ilk_zaman", "son_zaman", "cozuldu", "cozum", "lokal_dosya"];
  const kac = csvHucre;
  const metin = "﻿" + [alanlar.join(";"), ...liste.map(g => alanlar.map(a => kac(a.endsWith("zaman") ? tarihSaat(g[a]) : g[a])).join(";"))].join("\r\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([metin], { type: "text/csv;charset=utf-8" })), download: `gonderilemeyenler_${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.appendChild(a); a.click(); a.remove();
}

// ====================================================================== DİZİNLER VE KURALLAR
async function sayfaDizinler(yenileme) {
  if (!yenileme || !D.veri.dizinler || Date.now() - (D.veri.dizin_zaman || 0) > 3000) {
    try { D.veri.dizinler = await API.get("/api/dizinler"); D.veri.hedefler = await API.get("/api/hedefler"); D.veri.dizin_zaman = Date.now(); }
    catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  if (D.sayfa !== "dizinler") return;
  const liste = D.veri.dizinler;
  const kartlar = liste.map(d => kart(null, h("div", {},
    h("div", { class: "satir" }, ikon("klasor", 18), h("b", { class: "mono" }, d.yol), etiketli(DIZIN_ETIKET, d.erisim_durumu),
      d.aktif ? null : rozet("İzleme kapalı", ""), h("span", { class: "sessiz" }, `uzantılar: ${d.uzantilar || "hepsi"} · ilk kurulum: ${d.ilk_kurulum_modu === "TETIKLE" ? "mevcutlar tetiklendi" : "mevcutlar temel alındı"}`),
      h("div", { style: { marginLeft: "auto" }, class: "satir" },
        dugme(d.aktif ? "İzlemeyi kapat" : "İzlemeyi aç", { kucuk: true, rol: "YONETICI", onclick: () => onayla(d.aktif ? "İzlemeyi kapat" : "İzlemeyi aç",
          d.aktif ? `${d.yol} artık taranmayacak. Kapalıyken gelen dosyalar, izleme açılınca yakalanır.` : `${d.yol} yeniden taranacak.`,
          () => API.put(`/api/dizinler/${d.id}`, { aktif: !d.aktif }), d.aktif ? "warn" : "acc") }),
        d.kurallar.some(k => k.aktif) ? dugme("Kuralları durdur", { kucuk: true, ikon: "durdur", sinif: "tehlike-cizgi", rol: "OPERATOR", ipucu: "Bu dizindeki açık kuralların hepsini durdur",
          onclick: () => kapatPenceresi(null, null, { dizin: d, kurallar: d.kurallar }) }) : null,
        d.kurallar.some(k => !k.aktif) ? dugme("Kuralları aç", { kucuk: true, ikon: "oynat", rol: "OPERATOR", ipucu: "Bu dizindeki durdurulmuş kuralların hepsini aç",
          onclick: () => kurallariAc(d, d.kurallar) }) : null,
        dugme("Kural ekle", { kucuk: true, ikon: "arti", rol: "YONETICI", onclick: () => kuralPenceresi(d) }),
        dugme("Sil", { kucuk: true, ikon: "cop", sinif: "tehlike-cizgi", rol: "YONETICI", onclick: () => dizinSilPenceresi(d) }))),
    d.kurallar.length ? h("div", { class: "tablo-sar", style: { marginTop: "12px" } }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Sıra", "Kural", "Regex (dosya adına tam eşleşme)", "Tetiklenecek istek", "Durum", ""].map(t => h("th", {}, t)))),
      h("tbody", {}, ...d.kurallar.map(k => h("tr", {}, h("td", { class: "sayi sessiz" }, k.sira), h("td", {}, h("b", {}, k.ad)),
        h("td", { class: "mono" }, k.regex, k.harf_duyarsiz ? h("span", { class: "sessiz" }, "  (harf duyarsız)") : null),
        h("td", {}, h("div", { class: "mono", style: { fontSize: "12px" } }, k.hedef_tur === "BETIK"
            ? `betik · ${Object.entries((k.istek || {}).parametreler || {}).map(([a, v]) => `${a}=${v}`).join(", ") || "ek değer yok"}`
            : k.istek ? `${k.istek.yontem} ${k.istek.yol}` : `run/order ${(k.is_bilgisi || {}).folder || ""}/${(k.is_bilgisi || {}).jobs || ""}`),
          h("div", { class: "sessiz", style: { fontSize: "12px" } }, `→ ${k.hedef_ad}`),
          (k.mail || []).length ? h("div", { class: "sessiz", style: { fontSize: "12px" }, title: "Bu kurala bağlı mail alıcıları" }, ikon("zarf", 12), " ", k.mail.join(", ")) : null),
        h("td", {}, k.aktif ? rozet("Açık", "ok") : rozet(`Kapalı · ${k.kapatma_modu === "KAYITSIZ" ? "kayıtsız" : "kayıtlı"}`, k.kapatma_modu === "KAYITSIZ" ? "bad" : "warn")),
        h("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
          dugme("", { kucuk: true, ikon: "kalem", sinif: "hayalet", rol: "YONETICI", ipucu: "Kuralı düzenle", onclick: () => kuralPenceresi(d, k) }), " ",
          k.aktif ? dugme("Durdur", { kucuk: true, rol: "OPERATOR", ipucu: "Bu kuralı durdur (kayıtlı / kayıtsız)", onclick: () => kapatPenceresi(null, k) }) : dugme("Aç", { kucuk: true, sinif: "ana", rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/kurallar/${k.id}/ac`), "Kural açıldı") }),
          " ", dugme("", { kucuk: true, ikon: "cop", sinif: "hayalet", rol: "YONETICI", ipucu: "Kuralı sil",
            onclick: () => onayla("Kuralı sil", `'${k.ad}' kuralı silinecek. Bu kurala uyan yeni dosyalar artık tetiklenmez.`, () => API.sil(`/api/kurallar/${k.id}`), "bad") })))))))
      : h("div", { class: "sessiz", style: { marginTop: "10px" } }, "Bu dizinde kural yok: uzantısı uyan dosyalar 'kurala uymadı' olarak kaydedilir, tetiklenmez."))));
  const tumKurallar = liste.flatMap(d => d.kurallar);
  icerikYaz([baslik("Dizinler ve kurallar", "Kural: dizin + dosya adı regex'i → hedefe gidecek istek (ya da çalışacak betik). Uzantı ön filtresi son noktadan sonrasına bakar (harf duyarsız).",
    [tumKurallar.some(k => !k.aktif) ? dugme("Tüm kuralları aç", { ikon: "oynat", rol: "OPERATOR", onclick: () => kurallariAc(null, tumKurallar) }) : null,
     dugme("Tüm kuralları durdur", { ikon: "durdur", sinif: "tehlike-cizgi", rol: "OPERATOR", devre_disi: !tumKurallar.some(k => k.aktif),
      onclick: () => kapatPenceresi(null, null, { dizin: null, kurallar: tumKurallar }) }),
     dugme("Dizin ekle", { ikon: "arti", sinif: "ana", rol: "YONETICI", onclick: dizinPenceresi })]),
    liste.length ? h("div", { class: "izgara" }, ...kartlar) : kart(null, bosDurum("klasor", "Henüz dizin yok."))]);
}

// ====================================================================== HEDEFLER
async function sayfaHedefler() {
  const du = D.durum || {}; const liste = du.hedefler || [];
  const kartlar = liste.map(x => {
    const e = HEDEF_ETIKET(x); const a = x.ayrintilar || {};
    const kontrol = x.aktif
      ? [dugme("Gönderimi durdur", { ikon: "durdur", sinif: "tehlike-cizgi", rol: "OPERATOR", onclick: () => kapatPenceresi(x) })]
      : [dugme("Gönderimi aç", { ikon: "oynat", sinif: "ana", rol: "OPERATOR", onclick: () => acPenceresi(x) })];
    if (x.devre_durumu === "KESILDI") kontrol.push(dugme("Devreyi normale al", { ikon: "yenile", rol: "OPERATOR", onclick: () => devrePenceresi(x) }));
    if (x.lokalde) kontrol.push(dugme(`Lokaldekiler (${x.lokalde})`, { ikon: "kutu", onclick: () => { location.hash = "#/lokal"; } }));
    kontrol.push(dugme(x.tur === "BETIK" ? "Betiği aç" : "Düzenle", { ikon: x.tur === "BETIK" ? "kod" : "kalem", rol: "YONETICI",
      ipucu: x.tur === "BETIK" ? "Betiği görüntüler; değiştirmek ve çalıştırmak için betik kilidi gerekir" : null, onclick: () => hedefDuzenle(x) }));
    kontrol.push(dugme("Sil", { ikon: "cop", sinif: "hayalet", rol: "YONETICI", ipucu: "Bağlı kural ya da bekleyen tetik yoksa silinir",
      onclick: () => onayla("Hedefi sil", `'${x.ad}' hedefi silinecek. Bağlı kural ya da gönderilmeyi bekleyen (lokal dahil) tetik varsa silinmez.${x.tur === "BETIK" ? " Betik hedefi için betik kilidi açık olmalı." : ""}`,
        () => API.sil(`/api/hedefler/${x.id}`), "bad", "Hedef silindi") }));
    return kart(null, h("div", { class: "hedef" },
      h("div", {},
        h("div", { class: "durum-buyuk" }, h("span", { class: `isik ${e.i}` }), x.ad, rozet(e.e, e.s)),
        h("div", { class: "ikincil", style: { marginTop: "6px" } }, e.a),
        h("dl", { class: "bilgi-izgara", style: { marginTop: "12px" } },
          h("dt", {}, x.tur === "BETIK" ? "Tür" : "Tür / adres"), h("dd", { class: "mono" }, x.tur === "BETIK" ? hedefTurMetni(x) : `${hedefTurMetni(x)} · ${x.adres}`),
          x.tur === "CONTROLM" ? [h("dt", {}, "Control-M sunucusu"), h("dd", { class: "mono" }, a.ctm || "—")] : null,
          x.tur === "BETIK" ? [
            h("dt", {}, "Betik sürümü"), h("dd", { class: "mono" }, `${a.surum || "?"} · ${a.degistiren || "?"} · ${a.degisme_zamani ? once(a.degisme_zamani) : "—"}`),
            h("dt", {}, "Çalıştırma"), h("dd", {}, `zaman aşımı ${betikSuresi(x)} sn · aynı anda en fazla ${betikEszamanli(x)}`),
            h("dt", {}, "Gizli değerler"), h("dd", { class: "mono" }, (a.sirlar || []).length ? a.sirlar.map(z => `${z.ad} (${z.kayitli ? "şifreli" : "boş"})`).join(", ") : "yok"),
            a.son_calisma ? [h("dt", {}, "Son çalıştırma"), h("dd", {}, `çıkış ${a.son_calisma.cikis ?? "—"} · ${a.son_calisma.sure_ms} ms · ${once(a.son_calisma.zaman)}`)] : null]
          : [h("dt", {}, "Kimlik"), h("dd", { class: "mono" }, x.tur === "CONTROLM"
            ? (a.kimlik_turu === "yok" ? "yok" : a.kimlik_turu === "apikey" ? `API anahtarı · ${a.apikey_kaynagi || "kayıtlı değil"}`
              : `${a.kullanici || "?"} · şifre: ${a.sifre_kaynagi || "kayıtlı değil"}`)
            : a.kimlik_turu === "basic" ? `${a.kullanici || "?"} · Basic · şifre: ${a.sifre_kaynagi || "kayıtlı değil"}`
            : a.kimlik_turu === "yok" || !(a.anahtar_kayitli || a.anahtar_ref) ? "kimlik yok"
            : `${a.kimlik_turu === "apikey" ? `API anahtarı (${a.anahtar_basligi})` : "Bearer token"} · ${a.anahtar_kaynagi || "kayıtlı"}`)],
          !x.aktif ? [h("dt", {}, "Kapatan"), h("dd", {}, `${x.kapatan || "?"} · ${tarihSaat(x.kapatma_zamani)}`)] : null,
          x.saglik ? [h("dt", {}, "Son yoklama"), h("dd", {}, `${x.saglik.replace("YANIT_VERIYOR: ", "✓ yanıt veriyor · ").replace("YANITSIZ: ", "✗ yanıt yok · ")} (${once(x.saglik_zamani)})`)] : null),
        h("div", { class: "olcu-sirasi" }, olcu(x.yolda, "yolda"), olcu(x.bekleyen, "bekleyen"), olcu(x.tekrar, "yeniden denenecek"), olcu(x.lokalde, "lokalde"), olcu(x.ardisik_hata, "ardışık hata"))),
      h("div", { class: "dugmeler" }, ...kontrol)));
  });
  icerikYaz([baslik("Hedefler", "Tetiklerin gittiği yer: Control-M, genel bir API ya da bu sunucuda çalışan betik. Durdurma kayıtlı (lokale yazar) ya da kayıtsız (hiç göndermez) yapılabilir.",
    [dugme("Hepsini durdur", { ikon: "durdur", sinif: "tehlike-cizgi", rol: "OPERATOR", devre_disi: !liste.some(x => x.aktif), onclick: () => kapatPenceresi(null) }),
     dugme("Hedef ekle", { ikon: "arti", sinif: "ana", rol: "YONETICI", onclick: hedefPenceresi })]),
    liste.length ? h("div", { class: "izgara" }, ...kartlar) : kart(null, bosDurum("hedef", "Henüz hedef yok."))]);
}

// ====================================================================== EKLENTİLER
function sayfaEklentiler() {
  const ek = (D.durum || {}).eklentiler || [];
  icerikYaz([baslik("Eklentiler", "Çekirdek (gözetmen) her zaman ayaktadır; eklentiler ayrı süreçtir. Düşen eklenti otomatik yeniden başlatılır; art arda düşerse elle müdahale bekler."),
    h("div", { class: "izgara k2" }, ...ek.map(e => {
      const bilgi = e.bilgi || {};
      const ekstra = e.ad === "tarama" && bilgi.dizinler ? `${bilgi.dizinler.length} dizin izleniyor` : e.ad === "teslim" && bilgi.sayac ? `iletildi ${bilgi.sayac.iletildi || 0} · hata ${bilgi.sayac.hata || 0}` : e.ad === "kontrol" && bilgi.port ? `http://${bilgi.adres}:${bilgi.port} · ${bilgi.oturum || 0} oturum` : "";
      const dgm = e.ad === "cekirdek" ? [] : [
        e.durum === "DURDURULDU" || e.durum === "ELLE_MUDAHALE" ? dugme("Başlat", { ikon: "oynat", sinif: "ana", rol: "OPERATOR", onclick: () => eklentiKomutu(e, "baslat") }) : null,
        !["DURDURULDU", "ELLE_MUDAHALE"].includes(e.durum) ? dugme("Yeniden başlat", { ikon: "yenile", rol: "OPERATOR", onclick: () => eklentiKomutu(e, "yeniden_baslat") }) : null,
        e.ad !== "kontrol" && !["DURDURULDU"].includes(e.durum) ? dugme("Durdur", { ikon: "kare", sinif: "tehlike-cizgi", rol: "OPERATOR", onclick: () => eklentiKomutu(e, "durdur") }) : null];
      return kart(null, h("div", {},
        h("div", { class: "satir" }, h("b", { style: { fontSize: "15px" } }, EKLENTI_ADI[e.ad] || e.ad), etiketli(EKLENTI_ETIKET, e.durum), h("span", { class: "sessiz mono", style: { marginLeft: "auto" } }, e.pid ? `PID ${e.pid}` : "")),
        h("dl", { class: "bilgi-izgara", style: { marginTop: "12px" } },
          h("dt", {}, "Son nabız"), h("dd", {}, once(e.son_nabiz)),
          h("dt", {}, "Ana döngü"), h("dd", {}, e.son_ilerleme ? `ilerliyor (${once(e.son_ilerleme)})` : "—"),
          h("dt", {}, "Yeniden başlatma"), h("dd", {}, `${e.yeniden_baslatma || 0} kez${e.ardisik_dusme ? ` · art arda ${e.ardisik_dusme}` : ""}`),
          e.son_hata ? [h("dt", {}, "Son hata"), h("dd", { style: { color: "var(--bad)" } }, e.son_hata)] : null,
          ekstra ? [h("dt", {}, "Bilgi"), h("dd", {}, ekstra)] : null),
        dgm.some(Boolean) ? h("div", { class: "satir" }, ...dgm) : h("div", { class: "sessiz" }, "Çekirdek önyüzden durdurulamaz; Windows servisi yönetir.")));
    }))]);
}
function eklentiKomutu(e, islem) {
  const ad = EKLENTI_ADI[e.ad] || e.ad;
  const metin = { baslat: `${ad} eklentisi başlatılacak.`, yeniden_baslat: `${ad} eklentisi kapatılıp yeniden açılacak. Yarım kalan işler kaldığı yerden devam eder.`,
    durdur: e.ad === "tarama" ? "Tarama durdurulacak: yeni dosyalar fark edilmez (başlayınca yakalanır). Motoru durdurmak da aynı işi görür." : e.ad === "teslim" ? "Teslim durdurulacak: bekleyen tetikler için 'kapanış teslim bekleme' süresi kadar (Ayarlar) gönderime devam edilir; bitmeyenler veritabanında bekler (kayıp olmaz). Başlatınca kaldığı yerden devam eder." : `${ad} durdurulacak.` }[islem];
  onayla({ baslat: "Eklentiyi başlat", yeniden_baslat: "Eklentiyi yeniden başlat", durdur: "Eklentiyi durdur" }[islem], metin,
    () => API.post(`/api/eklentiler/${e.ad}/${islem}`), islem === "durdur" ? "bad" : "acc");
}

// ====================================================================== ALARMLAR ve DENETİM
async function sayfaDenetim() {
  try { D.veri.denetim = await API.get("/api/denetim?limit=500"); } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  if (D.sayfa !== "denetim") return;
  const f = (D.filtre.denetim || "").toLocaleLowerCase("tr");
  const liste = D.veri.denetim.filter(r => !f || `${r.kullanici} ${r.islem} ${r.nesne}`.toLocaleLowerCase("tr").includes(f));
  const ozet = v => { if (!v) return ""; try { const o = JSON.parse(v); return typeof o === "object" ? Object.entries(o).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join(" · ") : String(o); } catch (_) { return v; } };
  icerikYaz([baslik("Denetim kaydı", "Kim, ne zaman, ne yaptı. Değişikliklerin eski ve yeni değerleriyle.",
    h("div", { class: "arama" }, ikon("ara"), h("input", { type: "text", id: "ara_denetim", placeholder: "Kullanıcı, işlem ya da nesne…", value: D.filtre.denetim || "",
      oninput: e => { D.filtre.denetim = e.target.value; clearTimeout(D._dz); D._dz = setTimeout(sayfaDenetim, 250); } }))),
    kart(null, liste.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Zaman", "Kullanıcı", "İşlem", "Nesne", "Eski", "Yeni"].map(t => h("th", {}, t)))),
      h("tbody", {}, ...liste.map(r => h("tr", {}, h("td", { class: "ikincil", style: { whiteSpace: "nowrap" } }, tarihSaat(r.zaman)), h("td", {}, h("b", {}, r.kullanici)),
        h("td", {}, rozet(r.islem.replaceAll("_", " ").toLocaleLowerCase("tr"), r.islem.includes("KAPAT") || r.islem.includes("SIL") || r.islem.includes("BASARISIZ") ? "warn" : "duz")),
        h("td", { class: "mono" }, r.nesne || ""), h("td", { class: "ikincil", style: { maxWidth: "260px" } }, ozet(r.eski)), h("td", { class: "ikincil", style: { maxWidth: "320px" } }, ozet(r.yeni))))))) : bosDurum("liste", "Kayıt yok."), null, { sifir: true })]);
}

// ====================================================================== AYARLAR
async function sayfaAyarlar() {
  try { D.veri.ayarlar = await API.get("/api/ayarlar"); } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  const degisen = {};
  const kaydet = dugme("Değişiklikleri kaydet", { ikon: "onay", sinif: "ana", rol: "YONETICI", devre_disi: true });
  const gruplar = {};
  for (const a of D.veri.ayarlar) (gruplar[a.grup] = gruplar[a.grup] || []).push(a);
  const alanlar = Object.entries(gruplar).map(([g, liste]) => kart(g, h("div", {}, ...liste.map(a => {
    const id = `ay_${a.anahtar}`;
    const degis = v => { if (String(v) !== String(a.deger)) degisen[a.anahtar] = v; else delete degisen[a.anahtar]; kaydet.disabled = !Object.keys(degisen).length || !yetkili("YONETICI"); kaydet.textContent = Object.keys(degisen).length ? `${Object.keys(degisen).length} değişikliği kaydet` : "Değişiklikleri kaydet"; };
    let girdi;
    if (a.tur === "bool") girdi = h("label", { class: "anahtar" }, h("input", { type: "checkbox", id, checked: a.deger, disabled: !yetkili("YONETICI"), onchange: e => degis(e.target.checked) }), h("span", { class: "yol" }), "");
    else if (a.secenekler) girdi = h("select", { id, disabled: !yetkili("YONETICI"), onchange: e => degis(e.target.value) }, ...a.secenekler.map(s => h("option", { value: s, selected: s === a.deger }, s)));
    else girdi = h("input", { type: ["int", "float"].includes(a.tur) ? "number" : "text", step: a.tur === "float" ? "any" : null, id, value: a.deger, min: a.alt ?? null, max: a.ust ?? null,
      disabled: !yetkili("YONETICI"), style: { width: ["int", "float"].includes(a.tur) ? "140px" : "260px" }, oninput: e => degis(a.tur === "int" ? parseInt(e.target.value, 10) : a.tur === "float" ? parseFloat(e.target.value) : e.target.value) });
    return h("div", { class: "alan", style: { display: "grid", gridTemplateColumns: "minmax(200px, 300px) 1fr", gap: "4px 16px", alignItems: "start" } },
      h("label", { for: id }, a.anahtar.replaceAll("_", " ")), h("div", {}, girdi, h("div", { class: "ipucu" }, a.aciklama,
        a.alt !== null && a.alt !== undefined ? ` (${a.alt}–${a.ust})` : "", String(a.deger) !== String(a.varsayilan) ? ` · varsayılan: ${a.varsayilan}` : "")));
  }))));
  kaydet.onclick = () => onayla("Ayarları kaydet", h("div", {}, "Şu değişiklikler hemen uygulanacak:",
    h("ul", { class: "sonuc-listesi" }, ...Object.entries(degisen).map(([k, v]) => h("li", {}, h("b", {}, k), ` → ${v}`)))),
    () => API.put("/api/ayarlar", degisen), "acc", "Ayarlar kaydedildi");
  icerikYaz([baslik("Ayarlar", "Tüm değişiklikler doğrulanır, eklentilere canlı yansır ve denetim kaydına yazılır.", kaydet), h("div", { class: "izgara" }, ...alanlar)]);
}

// ====================================================================== PENCERELER
function pencere({ baslik: b, ikon: ik = "bilgi", tur = "acc", icerik, dugmeler, genis }) {
  const onceki = document.activeElement;
  const perde = h("div", { class: "perde", onmousedown: e => { if (e.target === perde) kapat(); } });
  const kapat = () => { perde.remove(); document.removeEventListener("keydown", tus); if (onceki && onceki.focus) onceki.focus(); };
  const tus = e => { if (e.key === "Escape" && perde === [...document.querySelectorAll(".perde")].pop()) kapat(); };
  document.addEventListener("keydown", tus);
  const hataEl = h("div", { class: "alan hata", role: "alert", style: { margin: "0 20px" } });
  const ps = h("div", { class: "ps" }, ...(dugmeler || []).map(d => {
    const b_ = h("button", { class: `dg ${d.sinif || ""}`, type: "button", disabled: d.devre_disi || null }, d.metin);
    b_.onclick = async () => {
      if (!d.eylem) return kapat();
      b_.disabled = true; hataEl.textContent = "";
      try { const r = await d.eylem(); if (r !== false) { kapat(); if (d.basari) bildirim(d.basari, "ok"); await sayfaYenile(); } }
      catch (e) { hataEl.textContent = e.message; } finally { b_.disabled = false; }
    };
    if (d.ref) d.ref(b_);
    return b_;
  }));
  const p = h("div", { class: `pencere ${genis === "cok" ? "cok-genis" : genis ? "genis" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": b },
    h("div", { class: "pb" }, h("div", { class: `ikon ${tur}` }, ikon(ik, 20)), h("h3", { style: { paddingTop: "8px" } }, b)),
    h("div", { class: "pi" }, icerik), hataEl, ps);
  perde.appendChild(p); document.body.appendChild(perde);
  setTimeout(() => { const f = p.querySelector("input, select, textarea") || ps.lastChild; f && f.focus(); }, 0);
  return { kapat, perde };
}
function onayla(b, metin, fn, tur = "acc", basari = "Tamamlandı") {
  pencere({ baslik: b, ikon: tur === "bad" ? "uyari" : tur === "warn" ? "uyari" : "bilgi", tur, icerik: typeof metin === "string" ? h("p", { style: { margin: 0 } }, metin) : metin,
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: b, sinif: tur === "bad" ? "tehlike" : "ana", eylem: fn, basari }] });
}

function sifrePenceresi() {
  const alan = (id, etiket, oto) => { const i = h("input", { type: "password", id, autocomplete: oto }); return [i, h("div", { class: "alan" }, h("label", { for: id }, etiket), i)]; };
  const [eski, eskiA] = alan("s_eski", "Mevcut şifre", "current-password");
  const [yeni, yeniA] = alan("s_yeni", "Yeni şifre (en az 10 karakter)", "new-password");
  const [tekrar, tekrarA] = alan("s_tekrar", "Yeni şifre (tekrar)", "new-password");
  pencere({ baslik: `Şifre değiştir: ${D.ben.kullanici}`, ikon: "kilit",
    icerik: h("div", {}, eskiA, yeniA, tekrarA, h("p", { class: "sessiz", style: { margin: 0, fontSize: "12.5px" } }, "Şifre sunucuda geri çevrilemez biçimde (PBKDF2) saklanır. Açık oturumlar kapanmaz.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Şifreyi değiştir", sinif: "ana", basari: "Şifre değiştirildi",
      eylem: async () => {
        if (yeni.value.length < 10) throw new Error("Yeni şifre en az 10 karakter olmalı.");
        if (yeni.value !== tekrar.value) throw new Error("Yeni şifreler aynı değil.");
        await API.post("/api/sifre", { eski: eski.value, yeni: yeni.value });
        D.ben.varsayilan_sifre = false;
      } }] });
}
function kapatPenceresi(hedef, kural, kume) {        // kume: { dizin: d | null, kurallar: [...] } → kuralları toplu durdur
  const du = D.durum || {};
  const hedefler = hedef ? [hedef] : (du.hedefler || []).filter(x => x.aktif);
  const hepsi = !hedef && !kural && !kume;
  let mod = "KAYITLI", anladim = false, onayDugmesi;
  const yolda = hedefler.reduce((t, x) => t + (x.yolda || 0), 0), bekleyen = hedefler.reduce((t, x) => t + (x.bekleyen || 0), 0);
  const secenek = (m, b, a, tehlikeli) => {
    const k = h("label", { class: `secim-kart ${m === mod ? "secili" : ""} ${tehlikeli ? "tehlikeli" : ""}` },
      h("input", { type: "radio", name: "mod", value: m, checked: m === mod, onchange: () => { mod = m; guncelle(); } }), h("div", {}, h("div", { class: "b" }, b), h("div", { class: "a" }, a)));
    return k;
  };
  const kayitli = secenek("KAYITLI", "Kayıtlı durdur (önerilen)", "Gelen dosyalar lokale yazılır. Hedef düzelince 'Kademeli erit' ile sırayla gönderilir. Hiçbir dosya kaybolmaz.");
  const kayitsiz = secenek("KAYITSIZ", "Kayıtsız durdur", "Gelen dosyalar hedefe HİÇ gönderilmez ve saklanmaz; yalnızca denetim kaydına yazılır. Sonradan geri alınamaz.", true);
  const anladimKutu = h("label", { class: "satir gizli", style: { marginTop: "4px", fontWeight: 600, color: "var(--bad)" } },
    h("input", { type: "checkbox", onchange: e => { anladim = e.target.checked; guncelle(); } }), "Bu sürede gelen dosyaların hedefe hiç gitmeyeceğini anladım.");
  function guncelle() {
    kayitli.classList.toggle("secili", mod === "KAYITLI"); kayitsiz.classList.toggle("secili", mod === "KAYITSIZ");
    anladimKutu.classList.toggle("gizli", mod !== "KAYITSIZ");
    if (onayDugmesi) { onayDugmesi.disabled = mod === "KAYITSIZ" && !anladim; onayDugmesi.className = `dg ${mod === "KAYITSIZ" ? "tehlike" : "ana"}`; }
  }
  const kumeAcik = kume ? kume.kurallar.filter(x => x.aktif) : [];
  const neYapacak = kural ? `'${kural.ad}' kuralına uyan dosyalar hedefe gönderilmeyecek.` :
    kume ? `${kume.dizin ? `'${kume.dizin.yol}' dizinindeki` : "Tüm dizinlerdeki"} ${kumeAcik.length} açık kuralın hepsi durdurulacak (${kumeAcik.map(x => x.ad).join(", ")}); uyan dosyalar hedefe gönderilmeyecek.` :
    hepsi ? `${hedefler.length} hedefin tamamına (${hedefler.map(x => x.ad).join(", ")}) yeni çağrı gönderilmeyecek.` : `'${hedef.ad}' hedefine yeni çağrı gönderilmeyecek.`;
  pencere({ baslik: kural ? "Kuralı durdur" : kume ? (kume.dizin ? `Kuralları durdur: ${kume.dizin.yol}` : "Tüm kuralları durdur") : hepsi ? "Gönderimi durdur (tüm hedefler)" : `${hedef.ad}: gönderimi durdur`, ikon: "durdur", tur: "bad",
    icerik: h("div", {}, h("p", { style: { marginTop: 0 } }, neYapacak, " Tarama devam eder; dosyalar yine fark edilir."),
      kural || kume ? h("p", { class: "ikincil", style: { marginTop: 0 } }, "Hedefler açık kalır; diğer kurallar etkilenmez. Açınca kayıtlı durdurulanlar 'Kademeli erit' ile gönderilir.")
        : h("ul", { class: "sonuc-listesi" }, h("li", {}, `Şu an yolda olan ${yolda} çağrı yarıda kesilmez; sonucu kaydedilir.`),
        h("li", {}, `Gönderim bekleyen ${bekleyen} tetik seçtiğiniz moda göre işlenir.`)),
      kayitli, kayitsiz, anladimKutu),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" },
      { metin: "Durdur", sinif: "ana", ref: b => { onayDugmesi = b; }, basari: kural || kume ? "Kural(lar) durduruldu" : "Gönderim durduruldu",
        eylem: () => kural ? API.post(`/api/kurallar/${kural.id}/kapat`, { mod })
          : kume ? API.post("/api/kurallar/toptan_kapat", { mod, dizin_id: kume.dizin ? kume.dizin.id : null })
          : hepsi ? API.post("/api/toptan_kapat", { mod }) : API.post(`/api/hedefler/${hedef.id}/kapat`, { mod }) }] });
}
function kurallariAc(dizin, kurallar) {                // durdurulmuş kuralların hepsi (dizin ya da tümü)
  const kapali = kurallar.filter(k => !k.aktif);
  const kayitli = kapali.filter(k => k.kapatma_modu !== "KAYITSIZ").length;
  onayla(dizin ? `Kuralları aç: ${dizin.yol}` : "Tüm kuralları aç",
    `${kapali.length} durdurulmuş kural açılacak (${kapali.map(k => k.ad).join(", ")}). Yeni gelen dosyalar canlı gönderilir.` +
      (kayitli ? " Kayıtlı durdurulmuşken gelenler lokalde bekler: Lokal kayıt sayfasından 'Kademeli erit' ile gönderin." : ""),
    () => API.post("/api/kurallar/toptan_ac", { dizin_id: dizin ? dizin.id : null }), "acc", "Kurallar açıldı");
}
function acPenceresi(hedef) {
  const du = D.durum || {};
  const kapali = hedef ? [hedef] : (du.hedefler || []).filter(x => !x.aktif);
  const lokalde = kapali.reduce((t, x) => t + (x.lokalde || 0), 0);
  pencere({ baslik: hedef ? `${hedef.ad}: gönderimi aç` : "Gönderimi yeniden başlat", ikon: "oynat", tur: "acc",
    icerik: h("div", {}, h("p", { style: { marginTop: 0 } }, "Yeni gelen dosyalar yeniden canlı olarak hedefe gönderilecek."),
      lokalde ? h("div", { class: "serit uyari", style: { margin: 0 } }, ikon("kutu", 18), h("div", { class: "metin" }, `Lokalde ${lokalde} kayıt bekliyor. Bunlar kendiliğinden gitmez; Hedefin sağlıklı olduğundan emin olunca 'Kademeli erit' ile gönderin.`)) : null),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Gönderimi aç", sinif: "ana", basari: "Gönderim açıldı",
      eylem: () => hedef ? API.post(`/api/hedefler/${hedef.id}/ac`) : API.post("/api/toptan_ac") }] });
}
function devrePenceresi(x) {
  const yanit = x.saglik && x.saglik.startsWith("YANIT_VERIYOR");
  onayla("Devreyi normale al", h("div", {}, h("p", { style: { marginTop: 0 } }, `'${x.ad}' için yeni dosyalar yeniden canlı gönderilecek.`),
    h("p", {}, yanit ? h("span", { style: { color: "var(--ok)", fontWeight: 600 } }, "✓ Son yoklamada hedef yanıt veriyor.") : h("span", { style: { color: "var(--warn)", fontWeight: 600 } }, "Son yoklamada hedef yanıt vermedi; devre yeniden kesilebilir.")),
    x.lokalde ? h("p", { class: "ikincil" }, `Lokaldeki ${x.lokalde} kayıt için ardından 'Kademeli erit' başlatın.`) : null),
    () => API.post(`/api/hedefler/${x.id}/devre_sifirla`), "acc", "Devre normale alındı");
}
function eritPenceresi(x) {
  let hiz = x.erit_hizi || 5;
  const toplam = x.lokalde + x.eritiliyor;
  const tahmin = h("div", { class: "ipucu" });
  const yaz_ = () => { tahmin.textContent = `${toplam} kayıt · saniyede ${hiz} çağrı · tahmini ~${sureMetni(Math.ceil(toplam / Math.max(hiz, 0.1)) * 1000)}`; };
  yaz_();
  const girdi = h("input", { type: "number", min: 0.1, max: 100, step: 0.5, value: hiz, style: { width: "120px" }, oninput: e => { hiz = parseFloat(e.target.value) || 1; yaz_(); } });
  pencere({ baslik: `${x.ad}: kademeli erit`, ikon: "erit", tur: "acc", icerik: h("div", {},
    h("p", { style: { marginTop: 0 } }, "Lokaldeki kayıtlar geliş sırasıyla, hız sınırıyla hedefe gönderilir. Yeni gelen (canlı) dosyalar her zaman önce gider."),
    h("ul", { class: "sonuc-listesi" }, h("li", {}, "Başarılı olan kayıt lokalden silinir, 'Gönderilemeyenler'de çözüldü olarak işaretlenir."),
      h("li", {}, "Hedef yine hata verirse erit kendiliğinden duraklar; kalanlar lokalde güvende kalır.")),
    h("div", { class: "alan" }, h("label", {}, "Hız (saniyede çağrı)"), girdi, tahmin)),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Eriti başlat", sinif: "ana", basari: "Kademeli erit başladı",
      eylem: () => API.post(`/api/hedefler/${x.id}/erit`, { islem: "baslat", hiz }) }] });
}
function motorPenceresi() {
  const calisiyor = (D.durum || {}).motor;
  onayla(calisiyor ? "Motoru durdur" : "Motoru başlat", calisiyor
    ? h("div", {}, h("p", { style: { marginTop: 0 } }, "Tarama durur: yeni dosyalar fark edilmez. Kuyruktaki tetiklerin teslimi sürer."), h("p", { class: "ikincil" }, "Motor başlayınca durduğu sürede gelen dosyalar yakalanır ve tetiklenir (telafi taraması)."))
    : "Tarama yeniden başlayacak; durduğu sürede gelen dosyalar yakalanıp tetiklenecek.",
  () => API.post("/api/motor", { aktif: !calisiyor }), calisiyor ? "warn" : "acc", calisiyor ? "Motor durduruldu" : "Motor başlatıldı");
}
function dizinPenceresi() {
  let mod = null;
  const yol = h("input", { type: "text", placeholder: "\\\\sunucu\\paylasim\\gelen", class: "mono" });
  const uz = h("input", { type: "text", placeholder: ".csv, .txt (boş = hepsi)" });
  const ad = h("input", { type: "text", placeholder: "örn. Muhasebe gelen" });
  const secenek = (m, b, a) => h("label", { class: "secim-kart" }, h("input", { type: "radio", name: "ilk", value: m, onchange: e => { mod = m; e.target.closest(".pi").querySelectorAll(".secim-kart").forEach(k => k.classList.toggle("secili", k.contains(e.target))); } }), h("div", {}, h("div", { class: "b" }, b), h("div", { class: "a" }, a)));
  pencere({ baslik: "Dizin ekle", ikon: "klasor", tur: "acc", icerik: h("div", {},
    h("div", { class: "alan" }, h("label", {}, "Dizin yolu"), yol, h("div", { class: "ipucu" }, "Tam yol ya da ağ yolu. Yalnızca okuma yetkisi yeterlidir.")),
    h("div", { class: "alan" }, h("label", {}, "Görünen ad"), ad),
    h("div", { class: "alan" }, h("label", {}, "Uzantılar"), uz, h("div", { class: "ipucu" }, "Son noktadan sonraki kısım, harf duyarsız karşılaştırılır.")),
    h("div", { class: "alan" }, h("label", {}, "Dizinde şu an duran dosyalar ne olsun? (zorunlu)"),
      secenek("TEMEL_AL", "Temel al (tetikleme)", "Şu an duran dosyalar işlenmiş sayılır. Bundan sonra gelenler tetiklenir."),
      secenek("TETIKLE", "Tetikle", "Şu an duran (kurala uyan) dosyalar da hedefe gönderilir."))),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Dizini ekle", sinif: "ana", basari: "Dizin eklendi",
      eylem: () => { if (!mod) throw new Error("Dizinde duran dosyalar için bir seçim yapın."); return API.post("/api/dizinler", { yol: yol.value.trim(), uzantilar: uz.value, ad: ad.value, ilk_kurulum_modu: mod }); } }] });
}
function dizinSilPenceresi(d) {
  let yazilan = "", b_;
  const girdi = h("input", { type: "text", class: "mono", oninput: e => { yazilan = e.target.value; b_.disabled = yazilan.trim() !== d.yol; } });
  pencere({ baslik: "Dizini sil", ikon: "cop", tur: "bad", icerik: h("div", {},
    h("p", { style: { marginTop: 0 } }, "Dizin ve kuralları silinecek; bu dizine gelen dosyalar artık fark edilmeyecek. Geçmiş kayıtlar silinmez."),
    h("div", { class: "alan" }, h("label", {}, "Onaylamak için yolu yazın:"), h("div", { class: "mono ikincil" }, d.yol), girdi)),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Sil", sinif: "tehlike", devre_disi: true, ref: b => { b_ = b; }, basari: "Dizin silindi", eylem: () => API.sil(`/api/dizinler/${d.id}`) }] });
}

// ====================================================================== başlatma ve canlı akış
function akisBaslat() {
  const uygula = du => {
    D.durum = du;
    if (basili) { bekleyenCizim = () => uygula(D.durum); return; }
    const s = sayfaBul(); menuCiz(); ustCiz(); if (s.canli && !document.querySelector(".perde")) s.ciz(true);
  };
  if (window.PROTOTIP) { D.akis = window.PROTOTIP.akis(uygula); return; }
  const es = new EventSource("/api/akis");
  es.onmessage = e => { try { uygula(JSON.parse(e.data)); } catch (_) {} };
  es.addEventListener("oturum", () => { es.close(); D.ben = null; girisCiz("Oturumun süresi doldu; yeniden giriş yapın."); });
  es.onerror = () => {
    const g = $("#genel_durum"); if (g) g.replaceChildren(rozet("Bağlantı koptu · yeniden deneniyor", "bad nabiz"));
    if (es.readyState === EventSource.CLOSED) akisYenidenDene(es);   // tarayıcı artık kendisi denemez (ör. 401)
  };
  D.akis = es;
}
/* Kontrol arayüzü yeniden başlarsa oturumlar düşer; tarayıcı 401 alınca canlı akışı bir daha denemez.
   Burada elle denenir: sunucu hâlâ kapalıysa 2 sn'de bir tekrar, açıldı ve oturum yoksa giriş ekranı. */
function akisYenidenDene(es) {
  clearTimeout(D._yeniden);
  D._yeniden = setTimeout(async () => {
    if (D.akis !== es || !D.ben) return;
    try { await API.get("/api/ben"); }
    catch (e) {
      if (e.kod === 401) return girisCiz("Bağlantı yeniden kuruldu; oturum sona erdiği için yeniden giriş yapın.");
      return akisYenidenDene(es);
    }
    es.close(); akisBaslat();
  }, 2000);
}
async function basla() {
  iskeletCiz();
  try { D.durum = await API.get("/api/durum"); } catch (_) { return; }
  akisBaslat();
  window.onhashchange = rotaDegisti;
  rotaDegisti(); ustCiz();
}
async function acilis() {
  temaBaslat();
  const prototip = location.protocol === "file:" || new URLSearchParams(location.search).has("prototip");
  if (prototip && !window.PROTOTIP) {
    await new Promise((ok, hata) => { const s = document.createElement("script"); s.src = "prototip.js"; s.onload = ok; s.onerror = hata; document.body.appendChild(s); });
  }
  try { const r = await API.get("/api/oturum"); if (!r.oturum) return girisCiz(null); D.ben = r; basla(); }   // oturum yok: giriş (401 üretmez)
  catch (e) { girisCiz(e.kod === 401 ? null : e.message); }         // diğerleri: nedenini göster
}
acilis();
