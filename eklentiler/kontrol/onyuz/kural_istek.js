/* FileWatcherPro önyüzü — kural penceresi (dosya adı regex'i + tetiklenecek API isteği ya da betik).
   Kural: dizin + regex → hedef üzerinde tam istek (yöntem, yol, gövde şablonu) ya da betiğe gidecek ek değerler.
   Hedef pencereleri hedef.js'de.
   uygulama.js'deki yardımcıları (h, dugme, pencere, API, D…) kullanır; ondan ÖNCE yüklenir, çağrılar sonra olur. */
"use strict";

// ---------------------------------------------------------------- istek değişkenleri
const ISTEK_DEGISKENLERI = [
  ["dosya_adi", "Dosya adı", "FATURA_20260929.csv"],
  ["tam_yol", "Tam yol (ağ yolu dahil)", "\\\\SUNUCU\\gelen\\FATURA_20260929.csv"],
  ["dizin", "Dizin yolu", "\\\\SUNUCU\\gelen"],
  ["boyut", "Boyut (bayt)", "15342"],
  ["icerik_hash", "İçerik hash'i (xxh3-128)", "9f2c…"],
  ["kimlik", "Tetik kimliği: hedefte olası çifti ayırt etmek için", "a41e…"],
  ["kural", "Kural adı", "fatura"],
  ["zaman", "Dosyanın hazır olduğu an (YYYY-AA-GG SS:DD:ss)", "2026-09-30 14:02:11"],
  ["bugun", "Bugünün tarihi (YYYYAAGG)", "20260930"],
  ["ctm", "Hedefte tanımlı Control-M sunucusu", "ctmprod"],
];
const YERLESIK = new Set(ISTEK_DEGISKENLERI.map(d => d[0]));
// Kural penceresinden bağlanan mail: [olay kodu, açıklama, varsayılan seçili]
const KURAL_MAIL_OLAYLARI = [
  ["DOSYA_GONDERILEMEDI", "Bu kuralın dosyası hedefe gönderilemedi (lokale yazıldı ya da istek reddedildi)", true],
  ["DOSYA_OLASI_CIFT", "Olası çift çağrı (cevap gelmeden koptu, işlem iki kez başlamış olabilir)", true],
  ["DOSYA_KAYITSIZ", "Kural ya da hedef kayıtsız kapalıyken dosya geldi (gönderilmedi)", true],
  ["DOSYA_SLA", "SLA aşıldı (iletim gecikti)", false],
  ["DOSYA_ESLESMEDI", "Bu dizinde hiçbir kuralın regex'ine uymayan dosya geldi", true],
  ["DIZIN_ERISILEMEZ", "Bu dizine erişilemiyor", true],
  ["DIZIN_YANITSIZ", "Bu dizin yanıt vermiyor (ağ takıldı)", true],
  ["YUKLEME_ASKIDA", "Bu dizinde yükleme askıda (çok uzun sürüyor)", false],
  ["DOSYA_ANOMALI", "Bu kuralın dosyalarında anomali: alışılmadık boyut, günlük adet ya da teslim süresi (asistan; 'anomaliyi alarm olarak aç' açıksa)", false],
];

const ISTEK_SABLONLARI = {
  olay: { ad: "Control-M: olay (koşul) ekle", turler: ["CONTROLM"], yontem: "POST", yol: "/run/event/{ctm}/FATURA_GELDI/ODAT", govde: "",
    aciklama: "Control-M'de bu olayı (koşulu) bekleyen iş başlar. Olay adını Control-M tarafındaki işle aynı yazın." },
  siparis: { ad: "Control-M: iş sipariş et (run/order)", turler: ["CONTROLM"], yontem: "POST", yol: "/run/order",
    govde: '{\n  "ctm": "{ctm}",\n  "folder": "KLASOR_ADI",\n  "jobs": "IS_ADI",\n  "variables": [\n    {"FWP_DOSYA": "{dosya_adi}"},\n    {"FWP_YOL": "{tam_yol}"},\n    {"FWP_KIMLIK": "{kimlik}"}\n  ]\n}',
    aciklama: "Klasördeki işi sipariş eder; dosya bilgileri Control-M değişkeni olarak gider." },
  json: { ad: "JSON gövdeyle POST", turler: ["HTTP"], yontem: "POST", yol: "/", govde: '{\n  "dosya": "{dosya_adi}",\n  "yol": "{tam_yol}",\n  "kimlik": "{kimlik}"\n}',
    aciklama: "Dosya bilgisini JSON olarak gönderir; yolu API'nizin uç noktasıyla değiştirin." },
  ozel: { ad: "Özel istek", turler: ["CONTROLM", "HTTP"], yontem: "POST", yol: "/", govde: '{\n  "dosya": "{dosya_adi}"\n}', aciklama: "Yolu ve gövdeyi kendiniz yazın." },
};

// ---------------------------------------------------------------- regex yardımcıları
/* Örnek dosya adlarından tam eşleşen regex önerir: rakam dizileri \d{n} (8 haneli 20… tarih → (?P<tarih>…)),
   harfler aynen; birden çok örnekte farklılaşan kısımlar genelleştirilir. */
function regexOner(adlar) {
  adlar = adlar.map(a => a.trim()).filter(Boolean);
  if (!adlar.length) return "";
  const parcala = ad => (ad.match(/\d+|[A-Za-zÇĞİÖŞÜçğıöşü]+|./g) || []).map(t => [/^\d/.test(t) ? "r" : /^[A-Za-zÇĞİÖŞÜçğıöşü]/.test(t) ? "h" : "d", t]);
  const kac = t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let listeler = adlar.map(parcala);
  const imza = l => l.map(x => x[0] + (x[0] === "d" ? x[1] : "")).join("");
  if (new Set(listeler.map(imza)).size > 1) listeler = [listeler[0]];            // yapı farklı: ilk örnek esas
  let tarihVar = false;
  return listeler[0].map(([tur, t], i) => {
    const hepsi = listeler.map(l => l[i][1]);
    if (tur === "d") return kac(t);
    if (tur === "h") {
      if (hepsi.every(x => x === t)) return kac(t);
      const uz = new Set(hepsi.map(x => x.length));
      const sinif = hepsi.every(x => x === x.toUpperCase()) ? "[A-Z]" : "[A-Za-z]";
      return uz.size === 1 ? `${sinif}{${t.length}}` : `${sinif}+`;
    }
    const uz = new Set(hepsi.map(x => x.length));
    if (uz.size === 1 && t.length === 8 && hepsi.every(x => /^(19|20)\d{6}$/.test(x)) && !tarihVar) { tarihVar = true; return "(?P<tarih>\\d{8})"; }
    return uz.size === 1 ? `\\d{${t.length}}` : "\\d+";
  }).join("");
}
const regexGruplari = r => [...String(r || "").matchAll(/\(\?P?<([A-Za-z_][A-Za-z0-9_]*)>/g)].map(m => m[1]);

function regexYardimi() {
  const satir = (a, b) => h("tr", {}, h("td", { class: "mono" }, a), h("td", {}, b));
  return h("details", { class: "yardim" },
    h("summary", {}, ikon("soru", 15), " Regex nasıl yazılır? Hangi kurallar geçerli?"),
    h("div", { class: "yardim-ic" },
      h("p", {}, h("b", {}, "Ne yazılır? "), "Dosya adının ", h("b", {}, "tamamına"), " uyan bir kalıp. Başa ", h("span", { class: "mono" }, "^"),
        ", sona ", h("span", { class: "mono" }, "$"), " koymanız gerekmez; klasör yolu yazılmaz, yalnızca dosya adı. Uzantı ön filtresi (dizin ayarı) ayrıca uygulanır."),
      h("p", {}, h("b", {}, "Evrensel mi? "), "Python ", h("span", { class: "mono" }, "re"), " sözdizimi kullanılır. Temel kurallar Java, .NET, JavaScript ve PCRE ile aynıdır; internetteki örneklerin çoğu olduğu gibi çalışır. Tek fark isimli grup: ",
        h("span", { class: "mono" }, "(?P<ad>…)"), " yazın; ", h("span", { class: "mono" }, "(?<ad>…)"), " yazarsanız otomatik çevrilir."),
      h("table", { class: "tablo yardim-tablo" }, h("tbody", {},
        satir("\\.", "Nokta. Tek başına . 'herhangi bir karakter' demektir; uzantıdaki noktayı mutlaka \\. yazın."),
        satir("\\d  \\d{8}  \\d+", "Rakam · tam 8 rakam · bir ya da daha çok rakam"),
        satir("[A-Z]{3}", "3 büyük harf (harf duyarsız seçiliyse küçük harf de uyar)"),
        satir(".*", "Her şey (boş dahil)"),
        satir("(IST|ANK)", "IST ya da ANK"),
        satir("(_v\\d+)?", "Parantez içi isteğe bağlı (olabilir de olmayabilir de)"),
        satir("(?P<tarih>\\d{8})", "Yakalanan kısım {tarih} değişkeni olarak isteğe yerleştirilebilir"))),
      h("p", {}, h("b", {}, "Örnekler")),
      h("table", { class: "tablo yardim-tablo" }, h("tbody", {},
        satir("FATURA_(?P<tarih>\\d{8})\\.csv", "FATURA_20260929.csv"),
        satir("SEVK_(?P<depo>[A-Z]{3})_(?P<tarih>\\d{8})\\.csv", "SEVK_IST_20260929.csv"),
        satir("RAPOR_\\d+\\.xlsx", "RAPOR_1.xlsx, RAPOR_125.xlsx"),
        satir(".*\\.csv", "Tüm .csv dosyaları"))),
      h("p", {}, h("b", {}, "Nereden yazdırırım? "), "1) Aşağıda bir dosya adı seçip ", h("b", {}, "Örnekten öner"), " düğmesine basın; kalıp çıkarılır, gerekirse düzeltirsiniz. ",
        "2) regex101.com'da 'Python' seçerek deneyebilirsiniz (gerçek dosya adlarını dış siteye yazarken gizliliğe dikkat). ",
        "3) Yapay zekâya örnek adları verip 'Python regex, dosya adının tamamı, tarih kısmını tarih adlı grupla yakala' diye isteyin. ",
        "Hangisini seçerseniz seçin, sonucu bu penceredeki canlı denemede görün."),
      h("p", { class: "sessiz" }, "Güvenlik: kaydederken aşırı yavaş desenler (ör. (a+)+) reddedilir; bir kalıp dosya adı başına en fazla birkaç milisaniye sürmelidir.")));
}

// ---------------------------------------------------------------- kural penceresi
async function kuralPenceresi(d, k) {
  const hedefler = D.veri.hedefler || [];
  if (!hedefler.length) { bildirim("Önce Hedefler sayfasından bir hedef ekleyin.", "bad"); return; }
  let gercekAdlar = [], bildirimler = { kurallar: [], smtp: null };
  try { gercekAdlar = await API.get(`/api/dizinler/${d.id}/ornek_adlar`); } catch (_) { /* dizin erişilemiyor olabilir */ }
  try { bildirimler = await API.get("/api/bildirim"); } catch (_) { /* bildirim bilgisi okunamazsa bölüm boş açılır */ }
  const ist = (k && k.istek && k.istek.yol !== undefined) ? k.istek : { ...ISTEK_SABLONLARI.olay };
  const betikParam = h("textarea", { rows: 4, class: "mono", id: "kural_betik_param", placeholder: "OLAY=FATURA_GELDI\nTARIH={tarih}" },
    Object.entries((k && k.istek && k.istek.parametreler) || {}).map(([a, v]) => `${a}=${v}`).join("\n"));
  const ad = h("input", { type: "text", placeholder: "örn. fatura", value: k ? k.ad : "" });
  const sira = h("input", { type: "number", value: k ? k.sira : 100, style: { width: "90px" } });
  const regex = h("input", { type: "text", class: "mono", id: "kural_regex", placeholder: "FATURA_(?P<tarih>\\d{8})\\.csv", value: k ? k.regex : "" });
  const hdKutu = h("input", { type: "checkbox", checked: k ? !!k.harf_duyarsiz : true });
  const ornekler = h("textarea", { rows: 5, class: "mono", placeholder: "Kendi örnek adlarınız (her satıra bir tane)" },
    "FATURA_20260929.csv\nfatura_20260930.CSV\nFATURA_2026.csv\nIADE_1.txt");
  let kaynak = gercekAdlar.length ? "gercek" : "ornek", yalnizEslesen = false, secili = null, sonucSatirlari = [];
  const sonuc = h("div", { class: "canli-sonuc" }), ozet = h("div", { class: "sessiz", style: { fontSize: "12.5px" } });
  const sekmeler = h("div", { class: "sekme kucuk", role: "tablist" });
  const adlar = () => kaynak === "gercek" ? gercekAdlar : ornekler.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const sekmeCiz = () => sekmeler.replaceChildren(
    ...[["gercek", `Dizindeki gerçek adlar (${gercekAdlar.length})`], ["ornek", "Örnek adlarım"]].map(([kk, e]) =>
      h("button", { type: "button", role: "tab", class: kaynak === kk ? "secili" : "", disabled: kk === "gercek" && !gercekAdlar.length ? true : null,
        onclick: () => { kaynak = kk; sekmeCiz(); ornekler.classList.toggle("gizli", kaynak !== "ornek"); dene(); } }, e)));
  let zaman;
  const dene = () => { clearTimeout(zaman); zaman = setTimeout(async () => {
    degiskenCiz();
    if (!regex.value) { sonuc.replaceChildren(h("div", { class: "sessiz" }, "Regex yazın; sonuç burada canlı görünür.")); ozet.textContent = ""; return; }
    try {
      sonucSatirlari = await API.post("/api/regex/dene", { regex: regex.value, harf_duyarsiz: hdKutu.checked, adlar: adlar().slice(0, 200) });
      const n = sonucSatirlari.filter(x => x.eslesti).length;
      ozet.textContent = `${sonucSatirlari.length} addan ${n} tanesi eşleşiyor.`;
      if (!secili || !sonucSatirlari.some(x => x.ad === secili && x.eslesti)) secili = (sonucSatirlari.find(x => x.eslesti) || {}).ad || null;
      const gosterilen = sonucSatirlari.filter(x => !yalnizEslesen || x.eslesti);
      sonuc.replaceChildren(gosterilen.length ? h("table", { class: "tablo eslesme" }, h("tbody", {}, ...gosterilen.map(x =>
        h("tr", { class: `tik ${x.ad === secili ? "secili-satir" : ""}`, title: "Tıklayın: istek denemesinde bu dosya kullanılsın",
          onclick: () => { secili = x.ad; dene(); } },
          h("td", { class: "mono" }, x.ad), h("td", { class: x.eslesti ? "evet" : "hayir" }, x.eslesti ? "✓ eşleşiyor" : "eşleşmiyor"),
          h("td", {}, h("div", { class: "gruplar" }, ...Object.entries(x.gruplar).map(([kk, v]) => h("span", {}, `${kk}=${v}`)))))))) :
        h("div", { class: "sessiz" }, "Gösterilecek ad yok."));
      denemeDosyasi.textContent = secili || "— (eşleşen ad yok)";
    } catch (e) { sonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); ozet.textContent = ""; }
  }, 250); };
  const oner = () => {
    const kaynakAdlar = secili ? [secili] : adlar().slice(0, 1);
    const r = regexOner(kaynakAdlar);
    if (!r) return bildirim("Önce bir örnek ad yazın ya da seçin.", "bad");
    regex.value = r; dene();
  };

  // --- istek tarafı
  const hedef = h("select", {}, ...hedefler.map(x => h("option", { value: x.id, selected: k ? x.id === k.hedef_id : null }, x.ad)));
  const hedefBilgi = h("div", { class: "ipucu mono" });
  const secHedef = () => hedefler.find(y => y.id === +hedef.value) || {};
  const betikMi = () => secHedef().tur === "BETIK";
  let kilit = null;                                   // betik kilidi yalnız betik hedefi seçilince sorulur
  const kilitYeri = h("div", {});
  const KIMLIK_ADI = { apikey: "API anahtarı", yok: "yok", token: "kullanıcı + şifre", bearer: "Bearer token", basic: "kullanıcı + şifre (Basic)" };
  const hedefCiz = () => { const x = secHedef(); const a = x.ayrintilar || {};
    hedefBilgi.textContent = x.tur === "BETIK" ? `${hedefTurMetni(x)} · sürüm ${a.surum || "?"} · zaman aşımı ${betikSuresi(x)} sn`
      : `${hedefTurMetni(x)} · ${x.adres || ""} · kimlik: ${KIMLIK_ADI[a.kimlik_turu || (x.tur === "CONTROLM" ? "token" : "yok")] || a.kimlik_turu}${a.ctm ? ` · {ctm} = ${a.ctm}` : ""}`;
    istekBolumu.classList.toggle("gizli", betikMi()); betikBolumu.classList.toggle("gizli", !betikMi());
    [baglantiDg, gonderDg].forEach(b => b.classList.toggle("gizli", betikMi())); calistirDg.classList.toggle("gizli", !betikMi());
    if (betikMi() && !kilit) { kilit = betikKilidi(() => {}); kilitYeri.replaceChildren(kilit.el); }
    kilitYeri.classList.toggle("gizli", !betikMi());
    if (!k && !istekDokunuldu && x.tur !== "BETIK") {          // yeni kural: hedef türüne uygun başlangıç isteği
      const t = x.tur === "HTTP" ? ISTEK_SABLONLARI.json : ISTEK_SABLONLARI.olay;
      yontem.value = t.yontem; yol.value = t.yol; govde.value = t.govde; sablonAciklama.textContent = t.aciklama;
    }
    sablon.replaceChildren(h("option", { value: "" }, "Hazır şablon seç…"),
      ...Object.entries(ISTEK_SABLONLARI).filter(([, s]) => s.turler.includes(x.tur)).map(([kk, s]) => h("option", { value: kk }, s.ad)));
    denemeSonuc.replaceChildren(); degiskenCiz(); };
  hedef.addEventListener("change", hedefCiz);
  const sablon = h("select", {});
  const yontem = h("select", { style: { width: "96px" } }, ...["POST", "PUT", "GET", "DELETE"].map(y => h("option", { value: y, selected: y === ist.yontem ? true : null }, y)));
  const yol = h("input", { type: "text", class: "mono", value: ist.yol, placeholder: "/run/event/{ctm}/OLAY_ADI/ODAT", style: { width: "100%" } });
  const govde = h("textarea", { rows: 6, class: "mono", placeholder: "Boş bırakılabilir (gövdesiz istek)" }, ist.govde || "");
  const sablonAciklama = h("div", { class: "ipucu" });
  sablon.addEventListener("change", () => { const s = ISTEK_SABLONLARI[sablon.value]; if (!s) return;
    yontem.value = s.yontem; yol.value = s.yol; govde.value = s.govde; sablonAciklama.textContent = s.aciklama; sablon.value = ""; });
  let sonOdak = govde, istekDokunuldu = false;
  [yol, govde, betikParam].forEach(el => el.addEventListener("focus", () => { sonOdak = el; }));
  [yol, govde, yontem].forEach(el => el.addEventListener("input", () => { istekDokunuldu = true; }));
  const betikParametreleri = () => {
    const o = satirlarAyristir(betikParam.value, "=", "Ek değer");
    for (const a of Object.keys(o)) if (!/^[A-Z][A-Z0-9_]*$/.test(a)) throw new Error(`Ek değer adı büyük harf, rakam ve _ olmalı: ${a}`);
    return o;
  };
  const kuralIstegi = () => betikMi() ? { parametreler: betikParametreleri() } : { yontem: yontem.value, yol: yol.value, govde: govde.value };
  const degiskenler = h("div", { class: "degiskenler" });
  const degiskenCiz = () => {
    const gruplar = regexGruplari(regex.value);
    degiskenler.replaceChildren(...[...ISTEK_DEGISKENLERI.filter(x => x[0] !== "ctm" || secHedef().tur === "CONTROLM").map(x => [x[0], x[1]]), ...gruplar.filter(g => !YERLESIK.has(g)).map(g => [g, "Regex grubu"])].map(([kk, a]) =>
      h("button", { type: "button", class: `degisken ${gruplar.includes(kk) ? "grup" : ""}`, title: a, onclick: () => {
        const el = betikMi() ? betikParam : sonOdak === betikParam ? govde : sonOdak, b = el.selectionStart ?? el.value.length;
        el.value = el.value.slice(0, b) + `{${kk}}` + el.value.slice(el.selectionEnd ?? b); el.focus(); el.selectionStart = el.selectionEnd = b + kk.length + 2; } }, `{${kk}}`)),
      ...gruplar.filter(g => YERLESIK.has(g)).map(g => h("span", { class: "alan hata", style: { margin: 0 } }, `Regex grubu '${g}' yerleşik bir değişkenle aynı adı taşıyor; başka ad verin.`)));
  };
  const denemeDosyasi = h("b", { class: "mono" }, "—");
  const denemeSonuc = h("div", { class: "deneme-sonuc" });
  const istekVerisi = gercek => ({ dizin_id: d.id, hedef_id: +hedef.value, regex: regex.value, harf_duyarsiz: hdKutu.checked, ad: ad.value,
    istek: kuralIstegi(), ornek_ad: secili, gonder: !!gercek });
  const denemeGoster = (r, gercek) => {
    const satirlar = [h("div", { class: "istek-satir mono" }, h("b", {}, r.yontem), " ", r.url)];
    satirlar.push(h("div", { class: "mono sessiz" }, ...Object.entries(r.basliklar || {}).map(([kk, v]) => h("div", {}, `${kk}: ${v}`))));
    if (r.govde) satirlar.push(h("pre", { class: "mono" }, r.govde));
    if (gercek && r.yanit) satirlar.push(h("div", { class: `yanit ${r.yanit.basarili ? "ok" : "bad"}` },
      h("b", {}, `HTTP ${r.yanit.kod ?? "—"} · ${r.yanit.sure_ms} ms · ${r.yanit.basarili ? "hedef kabul etti" : "hata"}`), h("pre", { class: "mono" }, r.yanit.govde || "")));
    denemeSonuc.replaceChildren(h("div", { class: "sessiz", style: { fontSize: "12px", marginBottom: "4px" } },
      gercek ? "GÖNDERİLDİ:" : `Kuru deneme (gönderilmedi) · dosya: ${secili || "—"}`), ...satirlar);
  };
  const kuruDeneme = async () => {
    if (!secili) return denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, "Kuru deneme için regex'e uyan bir dosya adı gerekli (soldaki listeden seçin)."));
    try { const r = await API.post("/api/kurallar/dene", istekVerisi(false));
      if (r.tur === "BETIK") denemeSonuc.replaceChildren(h("div", { class: "sessiz", style: { fontSize: "12px" } }, `Kuru deneme (betik çalıştırılmadı) · dosya: ${secili}`), ...ortamTablosu(r));
      else denemeGoster(r, false); }
    catch (e) { denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
  };
  const betikCalistir = () => {
    if (!secili) return kuruDeneme();
    if (!kilit || !kilit.acik()) return denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, "Betiği çalıştırmak için önce süper yönetici kilidini açın."));
    let veri; try { veri = istekVerisi(true); } catch (e) { return denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
    canliOnayi(`'${secHedef().ad}' betiği bu sunucuda GERÇEKTEN çalışacak; '${secili}' dosyası bu kurala uymuş gibi (regex grupları ve ek değerlerle). Dış sistemlerde işlem yapabilir.`, async () => {
      try { const r = await API.post("/api/kurallar/dene", veri);
        denemeSonuc.replaceChildren(h("div", { class: "sessiz", style: { fontSize: "12px", marginBottom: "4px" } }, `ÇALIŞTIRILDI · dosya: ${secili}`), ...betikSonucu(r)); }
      catch (e) { denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
    });
  };
  const baglantiDene = async () => {
    denemeSonuc.replaceChildren(h("div", { class: "sessiz" }, "Bağlanılıyor…"));
    try { const r = await API.post(`/api/hedefler/${+hedef.value}/dene`);
      denemeSonuc.replaceChildren(h("div", { class: `yanit ${r.basarili ? "ok" : "bad"}` }, h("b", {}, r.basarili ? "✓ " : "✗ "), r.mesaj, ` (${r.sure_ms} ms) · iş tetiklenmedi`)); }
    catch (e) { denemeSonuc.replaceChildren(h("div", { class: "alan hata" }, e.message)); }
  };
  const gercektenGonder = () => {
    if (!secili) return kuruDeneme();
    let anladim = false, b_;
    pencere({ baslik: "İsteği gerçekten gönder", ikon: "uyari", tur: "bad", icerik: h("div", {},
      h("p", { style: { marginTop: 0 } }, `Bu istek '${(hedefler.find(y => y.id === +hedef.value) || {}).ad}' hedefine GERÇEKTEN gönderilecek ve orada gerçek bir işlem başlatabilir (iş sipariş eder / olay ekler).`),
      h("p", { class: "ikincil" }, `Deneme dosyası: ${secili}. Denetim kaydına yazılır. Deneme isteği tetik tablosuna girmez.`),
      h("label", { class: "satir", style: { fontWeight: 600, color: "var(--bad)" } }, h("input", { type: "checkbox", onchange: e => { anladim = e.target.checked; b_.disabled = !anladim; } }), "Bunun gerçek bir işlem başlatabileceğini anladım.")),
      dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Gönder", sinif: "tehlike", devre_disi: true, ref: b => { b_ = b; },
        eylem: async () => { const r = await API.post("/api/kurallar/dene", istekVerisi(true)); denemeGoster(r, true); return true; } }] });
  };

  const baglantiDg = dugme("Bağlantıyı dene", { ikon: "yenile", kucuk: true, rol: "OPERATOR", ipucu: "Yalnızca erişim ve kimlik; iş tetiklemez", onclick: baglantiDene });
  const gonderDg = dugme("Gerçekten gönder…", { ikon: "gonder", kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI", onclick: gercektenGonder });
  const calistirDg = dugme("Gerçekten çalıştır…", { ikon: "oynat", kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI", ipucu: "Betik kilidi açık olmalı", onclick: betikCalistir });
  const istekBolumu = h("div", {},
    h("div", { class: "alan" }, h("label", {}, "İstek"), h("div", { class: "satir" }, yontem, h("div", { style: { flex: 1 } }, yol)),
      h("div", { class: "satir", style: { marginTop: "6px" } }, sablon), sablonAciklama),
    h("div", { class: "alan" }, h("label", {}, "Gövde (JSON; değişkenler {…} ile)"), govde));
  const betikBolumu = h("div", {},
    h("div", { class: "alan" }, h("label", { for: "kural_betik_param" }, "Betiğe gidecek ek değerler (isteğe bağlı; satır başına AD=değer)"), betikParam,
      h("div", { class: "ipucu" }, "Her satır betiğe FWP_P_<AD> ortam değişkeni ve stdin'de parametreler.<AD> olarak gider; böylece aynı betik farklı kurallarda farklı işler yapar. Dosya bilgisi ve regex grupları (FWP_G_…) zaten otomatik gider.")));

  // --- 3 · bildirim (mail): bu kurala bağlı alıcılar (Bildirimler'de kural kapsamlı bildirim kuralı olarak tutulur)
  const bagli = k ? (bildirimler.kurallar || []).find(x => x.kurallar && x.kurallar.length === 1 && x.kurallar[0] === k.id) : null;
  const bilinen = [...new Set((bildirimler.kurallar || []).flatMap(x => x.alicilar))];
  const mailAlici = h("textarea", { rows: 2, id: "kural_mail", style: { minHeight: "52px" }, placeholder: "ornek@sirket.local (her satıra bir adres ya da ; ile ayırın)" },
    bagli ? bagli.alicilar.join("\n") : "");
  const mailOlay = new Set(bagli ? bagli.olaylar : KURAL_MAIL_OLAYLARI.filter(x => x[2]).map(x => x[0]));
  const adresEkle = a => { const l = mailAlici.value.split(/[\n;,]+/).map(x => x.trim()).filter(Boolean); if (!l.includes(a)) l.push(a); mailAlici.value = l.join("\n"); };
  const bildirimBolumu = h("div", { class: "kural-bildirim" },
    h("h4", { class: "bolum-baslik" }, "3 · Bildirim (mail)"),
    !(bildirimler.smtp && bildirimler.smtp.sunucu) ? h("div", { class: "serit uyari", style: { margin: "0 0 10px" } }, ikon("uyari", 18),
      h("div", { class: "metin" }, "SMTP ayarlı değil: alıcıları yine kaydedebilirsiniz; mailler Bildirimler sayfasında SMTP ayarlanınca gider.")) : null,
    h("div", { class: "iki-sutun" },
      h("div", {}, h("div", { class: "alan" }, h("label", { for: "kural_mail" }, "Bu kurala bağlı alıcılar (boş = mail yok)"), mailAlici,
        bilinen.length ? h("div", { class: "degiskenler", style: { marginTop: "6px" } }, ...bilinen.map(a => h("button", { type: "button", class: "degisken", title: "Ekle", onclick: () => adresEkle(a) }, a))) : null,
        h("div", { class: "ipucu" }, "Hedef ve sistem olayları (devre kesildi, disk doldu…) için Bildirimler sayfasındaki genel kuralları kullanın."))),
      h("div", {}, h("div", { class: "alan" }, h("label", {}, "Hangi olaylarda mail gitsin?"),
        ...KURAL_MAIL_OLAYLARI.map(([kod, metin]) => h("label", { class: "satir", style: { fontWeight: 500, fontSize: "13px", alignItems: "flex-start" } },
          h("input", { type: "checkbox", value: kod, checked: mailOlay.has(kod) ? true : null, style: { marginTop: "3px" },
            onchange: e => { e.target.checked ? mailOlay.add(kod) : mailOlay.delete(kod); } }), metin))))));
  const bildirimiKaydet = async (kuralId, kuralAdi) => {
    const adresler = mailAlici.value.split(/[\n;,]+/).map(x => x.trim()).filter(Boolean);
    const v = { ad: `Kural: ${kuralAdi} · ${d.yol}`.slice(0, 200), alicilar: adresler, olaylar: [...mailOlay], seviye: "BILGI",
      dizinler: [d.id], kurallar: [kuralId], ozet_dk: 0, tekrar_dk: 60, duzelince: true, aktif: true };
    if (adresler.length) await (bagli ? API.put(`/api/bildirim/kurallar/${bagli.id}`, v) : API.post("/api/bildirim/kurallar", v));
    else if (bagli) await API.sil(`/api/bildirim/kurallar/${bagli.id}`);
  };

  hedefCiz(); sekmeCiz(); ornekler.classList.toggle("gizli", kaynak !== "ornek");
  [regex, ornekler].forEach(el => el.addEventListener("input", dene)); hdKutu.addEventListener("change", dene);
  const yalnizKutu = h("label", { class: "satir", style: { fontWeight: 500, fontSize: "12.5px" } }, h("input", { type: "checkbox", onchange: e => { yalnizEslesen = e.target.checked; dene(); } }), "Yalnız eşleşenler");

  pencere({ baslik: `${k ? "Kuralı düzenle" : "Kural ekle"} · ${d.yol}`, ikon: k ? "kalem" : "arti", tur: "acc", genis: "cok", icerik: h("div", {}, h("div", { class: "iki-sutun" },
    h("div", {},
      h("h4", { class: "bolum-baslik" }, "1 · Dosya adı eşleşmesi"),
      h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Kural adı"), ad), h("div", { class: "alan" }, h("label", {}, "Sıra"), sira)),
      h("div", { class: "alan" }, h("label", { for: "kural_regex" }, "Dosya adı regex'i (tam eşleşme)"), regex,
        h("div", { class: "satir", style: { marginTop: "6px" } }, h("label", { class: "satir", style: { fontWeight: 500 } }, hdKutu, "Harf duyarsız"),
          h("div", { style: { marginLeft: "auto" } }, dugme("Örnekten öner", { ikon: "sihir", kucuk: true, ipucu: "Seçili (ya da ilk) örnek addan kalıp çıkarır", onclick: oner })))),
      regexYardimi(),
      h("div", { class: "alan" }, h("div", { class: "satir" }, h("label", { style: { margin: 0 } }, "Canlı deneme"), h("div", { style: { marginLeft: "auto" } }, yalnizKutu)),
        sekmeler, ornekler, ozet, sonuc)),
    h("div", {},
      h("h4", { class: "bolum-baslik" }, "2 · Tetiklenecek hedef (API ya da betik)"),
      h("div", { class: "alan" }, h("label", {}, "Hedef (adres, kimlik ve betik Hedefler'de)"), hedef, hedefBilgi),
      kilitYeri, istekBolumu, betikBolumu,
      h("div", { class: "alan" }, h("label", {}, "Değişkenler (tıklayınca imlecin olduğu yere eklenir)"), degiskenler),
      h("div", { class: "alan" }, h("label", {}, "Deneme"), h("div", { class: "ipucu", style: { marginTop: 0 } }, "Deneme dosyası: ", denemeDosyasi, " (soldaki listeden değiştirin)"),
        h("div", { class: "satir", style: { marginTop: "8px" } },
          dugme("Kuru deneme", { ikon: "goz", kucuk: true, ipucu: "Gönderilecek isteği / betiğe verilecekleri gösterir; göndermez, çalıştırmaz", onclick: kuruDeneme }),
          baglantiDg, gonderDg, calistirDg),
        denemeSonuc))), bildirimBolumu),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: k ? "Değişiklikleri kaydet" : "Kuralı ekle", sinif: "ana", basari: k ? "Kural güncellendi" : "Kural eklendi",
      eylem: async () => {
        if (betikMi() && (!kilit || !kilit.acik())) throw new Error("Betik hedefli kural kaydetmek için süper yönetici kilidini açın: kural, hangi dosyalarda betiğin çalışacağını belirler.");
        const adresler = mailAlici.value.split(/[\n;,]+/).map(x => x.trim()).filter(Boolean);
        const kotu = adresler.filter(a => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a));
        if (kotu.length) throw new Error(`Geçersiz e-posta adresi: ${kotu.join(", ")}`);
        if (adresler.length && !mailOlay.size) throw new Error("Mail için en az bir olay seçin (ya da alıcıları boşaltın).");
        const v = { dizin_id: d.id, ad: ad.value, regex: regex.value, harf_duyarsiz: hdKutu.checked, hedef_id: +hedef.value,
        sira: parseInt(sira.value, 10) || 100, istek: kuralIstegi(), ornekler: adlar().slice(0, 50) };
        const r = k ? await API.put(`/api/kurallar/${k.id}`, v) : await API.post("/api/kurallar", v);
        try { await bildirimiKaydet(k ? k.id : r.id, ad.value || regex.value); }
        catch (e) { bildirim(`Kural kaydedildi ama mail alıcıları kaydedilemedi: ${e.message}`, "bad"); } } }] });
  degiskenCiz(); dene();
}
