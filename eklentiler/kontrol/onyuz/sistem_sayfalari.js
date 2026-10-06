/* FileWatcherPro önyüzü — Sistem izleme, Bildirimler (mail) ve Alarmlar sayfaları.
   Olay kataloğu (/api/olay_katalogu) alarm türlerini ve maile yönlendirilebilecek olayları tek yerden tanımlar.
   uygulama.js'deki yardımcıları kullanır; ondan ÖNCE yüklenir, fonksiyonlar sonra çağrılır. */
"use strict";

const SEVIYE_ADI = { KRITIK: "Kritik", UYARI: "Uyarı", BILGI: "Bilgi" };
const SEVIYE_SINIF = { KRITIK: "bad", UYARI: "warn", BILGI: "info" };
async function katalog() {
  if (!D.veri_katalog) D.veri_katalog = await API.get("/api/olay_katalogu");
  return D.veri_katalog;
}
const katalogBul = (kat, kod) => (kat || []).find(x => x.kod === kod);

// ---------------------------------------------------------------- küçük çizgi grafik (SVG, kütüphanesiz)
function cizgiGrafik({ seriler, zamanlar, ust, birim = "", esik = null, yukseklik = 170 }) {
  const G = 380, Y = yukseklik, sol = 40, alt = 20, ic = G - sol - 8, icY = Y - alt - 8;   // üç sütunda ~1:1 ölçek
  const ns = "http://www.w3.org/2000/svg";
  const el = (e, oz) => { const x = document.createElementNS(ns, e); for (const [k, v] of Object.entries(oz)) x.setAttribute(k, v); return x; };
  const svg = el("svg", { viewBox: `0 0 ${G} ${Y}`, class: "grafik", role: "img", "aria-label": seriler.map(s => s.ad).join(", ") });
  const n = Math.max(1, (zamanlar || []).length - 1);
  const x = i => sol + (i / n) * ic, y = v => 8 + icY - (Math.min(v, ust) / ust) * icY;
  for (const oran of [0, 0.5, 1]) {
    svg.appendChild(el("line", { x1: sol, x2: G - 8, y1: y(ust * oran), y2: y(ust * oran), class: "izgara-cizgi" }));
    const t = el("text", { x: sol - 6, y: y(ust * oran) + 4, class: "eksen", "text-anchor": "end" }); t.textContent = `${Math.round(ust * oran)}${birim}`; svg.appendChild(t);
  }
  if (esik !== null && esik < ust) {
    svg.appendChild(el("line", { x1: sol, x2: G - 8, y1: y(esik), y2: y(esik), class: "esik-cizgi" }));
    const t = el("text", { x: G - 10, y: y(esik) - 4, class: "eksen esik-yazi", "text-anchor": "end" }); t.textContent = `eşik ${esik}${birim}`; svg.appendChild(t);
  }
  for (const s of seriler) {
    const d = s.degerler.map((v, i) => v === null || v === undefined ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`).filter(Boolean);
    if (d.length > 1) svg.appendChild(el("polyline", { points: d.join(" "), class: `seri ${s.sinif}` }));
  }
  if (zamanlar && zamanlar.length) for (const [i, a] of [[0, "start"], [Math.floor(n / 2), "middle"], [n, "end"]]) {
    const t = el("text", { x: x(i), y: Y - 6, class: "eksen", "text-anchor": a });
    t.textContent = new Date(zamanlar[i] * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }); svg.appendChild(t);
  }
  return h("div", { class: "grafik-kap" }, svg, h("div", { class: "lejant" }, ...seriler.map(s => h("span", {}, h("i", { class: `nokta ${s.sinif}` }), s.ad))));
}
const yuzde = v => v === null || v === undefined ? "—" : `%${ondalik(v, v < 10 ? 1 : 0)}`;
const mb = v => v === null || v === undefined ? "—" : v >= 1024 ? `${ondalik(v / 1024, 1)} GB` : `${ondalik(v, v < 10 ? 1 : 0)} MB`;
function sureUzun(sn) {
  if (!sn && sn !== 0) return "—";
  const g = Math.floor(sn / 86400), s = Math.floor((sn % 86400) / 3600), d = Math.floor((sn % 3600) / 60);
  return g ? `${g} gün ${s} sa` : s ? `${s} sa ${d} dk` : `${d} dk`;
}

// ---------------------------------------------------------------- SİSTEM İZLEME
async function sayfaIzleme(yenileme) {
  const aralik = D.filtre.izleme_aralik || "1s";
  if (!yenileme || !D.veri.izleme || Date.now() - (D.veri.izleme_zaman || 0) > 5000) {
    try { D.veri.izleme = await API.get(`/api/izleme?aralik=${aralik}`); D.veri.izleme_zaman = Date.now(); }
    catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  if (D.sayfa !== "izleme") return;
  const v = D.veri.izleme, s = v.simdi, gc = v.gecmis, es = Object.fromEntries((v.esikler || []).map(x => [x.anahtar, x]));
  const kpi = (ad, deger, alt, sinif, ik) => h("div", { class: `kart kpi ${sinif || ""}` }, h("div", { class: "ad" }, ikon(ik, 14), ad), h("div", { class: "deger" }, deger), h("div", { class: "alt" }, alt));
  const durumSinif = x => !x ? "" : x.durum === "ALARM" ? "bad" : x.durum === "ASILDI" ? "warn" : "";
  const disk = (s.sunucu.diskler || [])[0] || {};
  const sekmeler = h("div", { class: "sekme", role: "tablist" }, ...[["1s", "Son 1 saat"], ["24s", "Son 24 saat"]].map(([kk, e]) =>
    h("button", { class: aralik === kk ? "secili" : "", role: "tab", onclick: () => { D.filtre.izleme_aralik = kk; D.veri.izleme_zaman = 0; sayfaIzleme(false); } }, e)));
  const surecTablo = h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Bileşen", "PID", "CPU", "Tepe CPU", "Bellek", "Thread", "Handle", "Çalışma süresi"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...s.fwp.surecler.map(p => h("tr", {}, h("td", {}, h("b", {}, EKLENTI_ADI[p.ad] || p.ad)), h("td", { class: "sayi mono" }, p.pid || "—"),
      h("td", { class: "sayi" }, yuzde(p.cpu)), h("td", { class: "sayi ikincil" }, yuzde(p.cpu_tepe)), h("td", { class: "sayi" }, mb(p.ram_mb)),
      h("td", { class: "sayi" }, sayi(p.thread)), h("td", { class: "sayi" }, sayi(p.handle)), h("td", { class: "ikincil" }, sureUzun(p.calisma_sn))))),
    h("tfoot", {}, h("tr", {}, h("td", {}, h("b", {}, "Toplam")), h("td", {}), h("td", { class: "sayi" }, h("b", {}, yuzde(s.fwp.cpu))), h("td", {}),
      h("td", { class: "sayi" }, h("b", {}, mb(s.fwp.ram_mb))), h("td", {}), h("td", {}), h("td", {})))));
  const depolama = h("dl", { class: "bilgi-izgara", style: { margin: 0 } },
    ...(s.sunucu.diskler || []).flatMap(dk => [h("dt", {}, `Disk ${dk.surucu}`), h("dd", {}, `${mb(dk.bos_mb)} boş / ${mb(dk.toplam_mb)} (${dk.icerik})`)]),
    h("dt", {}, "canli.db"), h("dd", {}, mb(s.depo.canli_mb)), h("dt", {}, "hata.db"), h("dd", {}, mb(s.depo.hata_mb)),
    h("dt", {}, "Lokal kayıt"), h("dd", {}, `${sayi(s.depo.lokal_adet)} kayıt · ${mb(s.depo.lokal_mb)}`),
    h("dt", {}, "Log klasörü"), h("dd", {}, `${mb(s.depo.log_mb)} · ${sayi(s.depo.log_adet)} dosya`));
  const esikTablo = h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Ölçü", "Şu an", "Eşik", "Süre", "Durum", ""].map(t => h("th", {}, t)))),
    h("tbody", {}, ...(v.esikler || []).map(x => h("tr", {}, h("td", {}, h("b", {}, x.ad), h("div", { class: "sessiz", style: { fontSize: "12px" } }, x.aciklama)),
      h("td", { class: "sayi" }, x.simdi_metin), h("td", { class: "sayi" }, x.aktif ? x.esik_metin : "kapalı"), h("td", { class: "ikincil" }, x.sure_dk ? `${ondalik(x.sure_dk, 0)} dk boyunca` : "anında"),
      h("td", {}, !x.aktif ? rozet("İzlenmiyor", "") : x.durum === "ALARM" ? rozet(`Alarm · ${SEVIYE_ADI[x.seviye]}`, SEVIYE_SINIF[x.seviye]) : x.durum === "ASILDI" ? rozet(`Aşıldı · ${once(x.asilma_zamani)}`, "warn") : rozet("Normal", "ok")),
      h("td", { class: "ikincil", style: { fontSize: "12px" } }, x.mail ? h("span", { title: "Bu alarm için bildirim kuralı var" }, ikon("zarf", 13), " mail") : ""))))));
  const eski = v.olcum_zamani && Date.now() / 1000 - v.olcum_zamani > Math.max(60, 4 * (v.aralik_sn || 10));
  icerikYaz([baslik("Sistem izleme", `FileWatcherPro'nun çalıştığı sunucu (${s.sunucu.ad}) ve kendi kaynak kullanımı. Ölçüm ${v.aralik_sn} sn'de bir alınır, son 24 saat saklanır.`, sekmeler),
    eski ? h("div", { class: "serit uyari" }, ikon("uyari", 20), h("div", { class: "metin" }, h("b", {}, "Ölçümler güncel değil. "),
      `Son ölçüm ${once(v.olcum_zamani)}; izleme eklentisi durmuş olabilir (Eklentiler sayfası).`)) : null,
    h("div", { class: "izgara k6" },
      kpi("Sunucu CPU", yuzde(s.sunucu.cpu), `${s.sunucu.cekirdek} çekirdek`, durumSinif(es.sunucu_cpu), "islemci"),
      kpi("Sunucu bellek", yuzde(s.sunucu.ram_yuzde), `${mb(s.sunucu.ram_kullanilan_mb)} / ${mb(s.sunucu.ram_toplam_mb)}`, durumSinif(es.sunucu_ram), "kutu"),
      kpi("Disk (veri)", mb(disk.bos_mb), `boş · %${ondalik(disk.bos_yuzde || 0, 0)}`, durumSinif(es.disk_bos), "kutu"),
      kpi("FileWatcherPro CPU", yuzde(s.fwp.cpu), "tüm bileşenler, sunucunun yüzdesi", durumSinif(es.fwp_cpu), "nabiz"),
      kpi("FileWatcherPro bellek", mb(s.fwp.ram_mb), `${s.fwp.surecler.length} süreç`, durumSinif(es.fwp_ram), "nabiz"),
      kpi("Çalışma süresi", sureUzun(s.fwp.calisma_sn), `sunucu açık: ${sureUzun(s.sunucu.acik_sn)}`, "", "saat")),
    h("div", { class: "bolum" }, h("div", { class: "izgara k3" },
      kart("İşlemci (%)", cizgiGrafik({ seriler: [{ ad: "Sunucu", sinif: "s1", degerler: gc.sunucu_cpu }, { ad: "FileWatcherPro", sinif: "s2", degerler: gc.fwp_cpu }],
        zamanlar: gc.zaman, ust: 100, birim: "%", esik: es.sunucu_cpu && es.sunucu_cpu.aktif ? es.sunucu_cpu.esik : null })),
      kart("Sunucu belleği (%)", cizgiGrafik({ seriler: [{ ad: "Kullanılan", sinif: "s1", degerler: gc.sunucu_ram }], zamanlar: gc.zaman, ust: 100, birim: "%",
        esik: es.sunucu_ram && es.sunucu_ram.aktif ? es.sunucu_ram.esik : null })),
      kart("FileWatcherPro belleği (MB)", cizgiGrafik({ seriler: [{ ad: "Toplam", sinif: "s2", degerler: gc.fwp_ram }], zamanlar: gc.zaman,
        ust: Math.max(100, Math.ceil(Math.max(...gc.fwp_ram.filter(x => x !== null), es.fwp_ram ? es.fwp_ram.esik : 0) / 100) * 100), birim: "",
        esik: es.fwp_ram && es.fwp_ram.aktif ? es.fwp_ram.esik : null })))),
    h("div", { class: "bolum" }, h("div", { class: "izgara k2" },
      kart("Bileşenler", surecTablo, null, { sifir: true }),
      kart("Depolama", depolama))),
    h("div", { class: "bolum" }, kart("Eşikler ve alarmlar", esikTablo,
      dugme("Eşikleri düzenle", { kucuk: true, ikon: "ayar", rol: "YONETICI", onclick: () => esikPenceresi(v.esikler) }), { sifir: true })),
    h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Eşik aşılınca önce 'Aşıldı' görünür; belirtilen süre boyunca sürerse alarm açılır (anlık sıçramalar alarm üretmez). Değer eşiğin altına inip 1 dk kalınca alarm kendiliğinden kapanır. Maile gönderim Bildirimler sayfasındaki kurallarla yapılır.")]);
}
function esikPenceresi(esikler) {
  const degisen = {};
  const satirlar = esikler.map(x => {
    const acik = h("input", { type: "checkbox", checked: !!x.aktif, onchange: e => { degisen[`${x.ayar}_aktif`] = e.target.checked; } });
    const deger = h("input", { type: "number", value: x.esik, step: "any", style: { width: "100px" }, oninput: e => { degisen[x.ayar] = parseFloat(e.target.value); } });
    const sure = x.sure_ayar ? h("input", { type: "number", value: x.sure_dk, step: "any", style: { width: "80px" }, oninput: e => { degisen[x.sure_ayar] = parseFloat(e.target.value); } }) : h("span", { class: "sessiz" }, "anında");
    return h("tr", {}, h("td", {}, h("label", { class: "satir", style: { fontWeight: 600 } }, acik, x.ad)), h("td", {}, h("div", { class: "satir" }, deger, h("span", { class: "sessiz" }, x.birim))),
      h("td", {}, h("div", { class: "satir" }, sure, x.sure_ayar ? h("span", { class: "sessiz" }, "dk") : null)), h("td", {}, rozet(SEVIYE_ADI[x.seviye], SEVIYE_SINIF[x.seviye])));
  });
  pencere({ baslik: "Kaynak eşiklerini düzenle", ikon: "ayar", tur: "acc", genis: true, icerik: h("div", {},
    h("table", { class: "tablo" }, h("thead", {}, h("tr", {}, ...["Ölçü", "Eşik", "Ne kadar sürerse", "Alarm seviyesi"].map(t => h("th", {}, t)))), h("tbody", {}, ...satirlar)),
    h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Değişiklikler hemen uygulanır ve denetim kaydına yazılır.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Kaydet", sinif: "ana", basari: "Eşikler kaydedildi",
      eylem: () => Object.keys(degisen).length ? API.put("/api/ayarlar", degisen) : true }] });
}

// ---------------------------------------------------------------- BİLDİRİMLER (MAIL)
async function sayfaBildirimler() {
  let b, kat;
  try { [b, kat] = await Promise.all([API.get("/api/bildirim"), katalog()]); } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  if (D.sayfa !== "bildirimler") return;
  D.veri.bildirim = b;
  const sm = b.smtp || {};
  const smtpKart = kart("Mail sunucusu (SMTP)", h("div", {},
    sm.sunucu ? h("dl", { class: "bilgi-izgara", style: { margin: 0 } },
      h("dt", {}, "Sunucu"), h("dd", { class: "mono" }, `${sm.sunucu}:${sm.port} · ${sm.guvenlik}`),
      h("dt", {}, "Kullanıcı"), h("dd", {}, h("span", { class: "mono" }, sm.kullanici || "—"), sm.kullanici ? ` · şifre: ${sm.sifre_kaynagi || "kayıtlı değil"}` : ""),
      h("dt", {}, "Gönderen"), h("dd", {}, `${sm.gonderen_ad || ""} <${sm.gonderen}>`),
      h("dt", {}, "Durum"), h("dd", {}, !sm.aktif ? rozet("Kapalı: mail gönderilmiyor", "warn") : b.son_durum ? (b.son_durum.basarili
        ? rozet(`Son gönderim başarılı · ${once(b.son_durum.zaman)}`, "ok") : rozet(`Son hata · ${once(b.son_durum.zaman)}: ${b.son_durum.mesaj}`, "bad")) : rozet("Henüz gönderim yok", "")))
      : bosDurum("zarf", "Mail sunucusu tanımlı değil. Bildirim göndermek için önce SMTP ayarlarını girin."),
    h("div", { class: "satir", style: { marginTop: "14px" } },
      dugme(sm.sunucu ? "Düzenle" : "SMTP ayarla", { ikon: "ayar", kucuk: true, sinif: sm.sunucu ? "" : "ana", rol: "YONETICI", onclick: () => smtpPenceresi(sm) }),
      dugme("Test maili gönder", { ikon: "gonder", kucuk: true, rol: "OPERATOR", devre_disi: !sm.sunucu, onclick: testMailPenceresi }))));
  const nasil = kart("Nasıl çalışır?", h("ul", { class: "sonuc-listesi", style: { margin: 0 } },
    h("li", {}, "Her kural: hangi olaylar, hangi dizinler, kime. Bir olay birden çok kurala uyabilir; her alıcı o olayı bir kez alır."),
    h("li", {}, h("b", {}, "Anında: "), "olay olunca ayrı mail. ", h("b", {}, "Özet: "), "belirtilen aralıkta birikenler tek mailde."),
    h("li", {}, h("b", {}, "Tekrar sınırı: "), "aynı olay sürüp dururken en fazla bu aralıkla hatırlatılır (mail yağmuru olmaz)."),
    h("li", {}, h("b", {}, "Düzelince bildir: "), "alarm kapanınca 'düzeldi' maili gider."),
    h("li", {}, h("b", {}, "Mail yağmuru koruması: "), "bir anında kural 10 dakikada 10'dan fazla mail üretirse geçici olarak 5 dakikalık özete geçer."),
    h("li", {}, "Mail gönderilemezse FileWatcherPro etkilenmez; gönderim ayrı bileşende yeniden denenir (30 sn, 2, 5, 15, 30 dk), Gönderim geçmişinde görünür.")));
  const olayAdi = kod => (katalogBul(kat, kod) || { ad: kod }).ad;
  const kuralTablo = b.kurallar.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Kural", "Alıcılar", "Olaylar", "Kapsam", "Seviye", "Gönderim", "Durum", ""].map(t => h("th", {}, t)))),
    h("tbody", {}, ...b.kurallar.map(k => h("tr", {},
      h("td", {}, h("b", {}, k.ad)), h("td", { class: "ikincil", style: { maxWidth: "220px" } }, k.alicilar.join(", ")),
      h("td", {}, h("div", { class: "etiketler" }, ...k.olaylar.slice(0, 3).map(o => h("span", {}, olayAdi(o))), k.olaylar.length > 3 ? h("span", {}, `+${k.olaylar.length - 3}`) : null)),
      h("td", { class: "ikincil" }, k.kurallar ? `Kural: ${k.kural_adlari.join(", ")}` : k.dizinler === null ? "Tüm dizinler" : `${k.dizinler.length} dizin`),
      h("td", {}, rozet(k.seviye === "KRITIK" ? "Yalnız kritik" : k.seviye === "UYARI" ? "Uyarı ve üstü" : "Hepsi", "duz")),
      h("td", { class: "ikincil" }, k.ozet_dk ? `Özet · ${k.ozet_dk} dk` : "Anında", k.duzelince ? h("div", { class: "sessiz", style: { fontSize: "12px" } }, "+ düzelince") : null),
      h("td", {}, k.aktif ? rozet("Açık", "ok") : rozet("Kapalı", "")),
      h("td", { style: { textAlign: "right", whiteSpace: "nowrap" } },
        dugme("", { kucuk: true, ikon: "kalem", sinif: "hayalet", rol: "YONETICI", ipucu: "Düzenle", onclick: () => bildirimKuralPenceresi(kat, k) }),
        dugme("", { kucuk: true, ikon: "cop", sinif: "hayalet", rol: "YONETICI", ipucu: "Sil",
          onclick: () => onayla("Bildirim kuralını sil", `'${k.ad}' silinecek; bu alıcılara artık mail gitmeyecek.`, () => API.sil(`/api/bildirim/kurallar/${k.id}`), "bad") })))))))
    : bosDurum("zarf", "Henüz bildirim kuralı yok.");
  const gecmis = b.gecmis.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Zaman", "Kural", "Alıcılar", "Konu", "Olay", "Sonuç"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...b.gecmis.map(g_ => h("tr", {}, h("td", { class: "ikincil", style: { whiteSpace: "nowrap" } }, tarihSaat(g_.zaman)), h("td", {}, g_.kural || "—"),
      h("td", { class: "ikincil" }, g_.alicilar.join(", ")), h("td", {}, g_.konu), h("td", { class: "sayi" }, g_.olay_sayisi),
      h("td", {}, g_.durum === "GONDERILDI" ? rozet("Gönderildi", "ok") : g_.durum === "BEKLIYOR" ? rozet(`Yeniden denenecek (${g_.deneme})`, "warn") : rozet(`Hata: ${g_.hata}`, "bad")))))))
    : bosDurum("liste", "Henüz gönderim yok.");
  icerikYaz([baslik("Bildirimler (mail)", "Hangi olayların hangi dizinler için kime mail olarak gideceğini belirleyin.",
      dugme("Bildirim kuralı ekle", { ikon: "arti", sinif: "ana", rol: "YONETICI", devre_disi: !sm.sunucu, ipucu: !sm.sunucu ? "Önce SMTP ayarlayın" : null, onclick: () => bildirimKuralPenceresi(kat, null) })),
    h("div", { class: "izgara k2" }, smtpKart, nasil),
    h("div", { class: "bolum" }, kart(`Bildirim kuralları (${b.kurallar.length})`, kuralTablo, null, { sifir: true })),
    h("div", { class: "bolum" }, kart("Gönderim geçmişi (son 100)", gecmis, null, { sifir: true }))]);
}
function smtpPenceresi(sm) {
  const g = (ph, v, oz = {}) => h("input", { type: "text", placeholder: ph, value: v ?? "", ...oz });
  const sunucu = g("mail.sirket.local", sm.sunucu), port = g("587", sm.port || 587, { type: "number", style: { width: "100px" } });
  const guv = h("select", {}, ...[["STARTTLS", "STARTTLS (587)"], ["SSL", "SSL/TLS (465)"], ["YOK", "Şifresiz (25, yalnız iç ağ)"]].map(([v, e]) => h("option", { value: v, selected: v === (sm.guvenlik || "STARTTLS") ? true : null }, e)));
  const kul = g("fwp@sirket.local", sm.kullanici, { autocomplete: "off" }), ref = g("wincred:FileWatcherPro/smtp  ya da  env:FWP_SMTP_SIFRE", sm.sifre_ref, { class: "mono" });
  const sifre = h("input", { type: "password", id: "smtp_sifre", autocomplete: "new-password",
    placeholder: sm.sifre_kayitli ? "•••••••• kayıtlı (değiştirmek için yazın)" : "Şifre" });
  const gon = g("fwp@sirket.local", sm.gonderen), gonAd = g("FileWatcherPro", sm.gonderen_ad || "FileWatcherPro");
  const aktif = h("input", { type: "checkbox", checked: sm.aktif !== 0 && sm.aktif !== false });
  const tls = h("input", { type: "checkbox", checked: sm.tls_dogrula !== false });
  const sonuc = h("div", {});
  const veri = () => ({ sunucu: sunucu.value.trim(), port: parseInt(port.value, 10), guvenlik: guv.value, kullanici: kul.value.trim(), sifre: sifre.value || undefined, sifre_ref: ref.value.trim() || undefined,
    gonderen: gon.value.trim(), gonderen_ad: gonAd.value.trim(), aktif: aktif.checked, tls_dogrula: tls.checked });
  pencere({ baslik: "Mail sunucusu (SMTP)", ikon: "zarf", tur: "acc", icerik: h("div", {},
    h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Sunucu"), sunucu), h("div", { class: "alan" }, h("label", {}, "Port"), port), h("div", { class: "alan" }, h("label", {}, "Güvenlik"), guv)),
    h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Kullanıcı"), kul), h("div", { class: "alan gen" }, h("label", { for: "smtp_sifre" }, "Şifre"), sifre)),
    h("div", { class: "satir" }, h("div", { class: "alan gen" }, h("label", {}, "Gönderen adres"), gon), h("div", { class: "alan gen" }, h("label", {}, "Gönderen adı"), gonAd)),
    h("label", { class: "satir", style: { fontWeight: 600 } }, aktif, "Mail gönderimi açık"),
    h("label", { class: "satir", style: { fontWeight: 500, marginTop: "6px" } }, tls, "TLS sertifikasını doğrula (kurum içi, kendinden imzalı sertifikada kapatın)"),
    h("div", { class: "serit bilgi", style: { margin: "12px 0 10px" } }, ikon("kilit", 18), h("div", { class: "metin" },
      "Şifre bu sunucuda Windows DPAPI ile şifrelenerek saklanır; ekranda, veritabanında ve loglarda düz hâli görünmez.", sm.sifre_kayitli ? ` Şu an kayıtlı: ${sm.sifre_kaynagi}. Değiştirmeyecekseniz boş bırakın.` : "")),
    h("details", { class: "yardim", open: sm.sifre_ref ? true : null }, h("summary", {}, ikon("ayar", 15), " Gelişmiş: şifreyi dışarıdan oku (Windows Kimlik Bilgisi / ortam değişkeni)"),
      h("div", { class: "yardim-ic" }, h("div", { class: "alan", style: { margin: 0 } }, h("label", {}, "Referans"), ref,
        h("div", { class: "ipucu" }, "Şifre alanı boşsa kullanılır. Kurum ilkesi şifrenin uygulamada tutulmamasını istiyorsa: şifreyi Windows Kimlik Bilgisi Yöneticisi'ne (servisin çalıştığı hesapla) ya da ortam değişkenine kaydedip adını yazın.")))),
    h("div", { class: "satir", style: { marginTop: "12px" } }, dugme("Bağlantıyı dene", { ikon: "yenile", kucuk: true, ipucu: "Sunucuya bağlanır ve (yazdığınız ya da kayıtlı şifreyle) oturum açar; mail göndermez",
      onclick: async () => { sonuc.replaceChildren(h("span", { class: "sessiz" }, "Bağlanılıyor…"));
        try { const r = await API.post("/api/bildirim/smtp/dene", veri()); sonuc.replaceChildren(h("span", { class: `yanit ${r.basarili ? "ok" : "bad"}` }, `${r.basarili ? "✓" : "✗"} ${r.mesaj}`)); }
        catch (e) { sonuc.replaceChildren(h("span", { class: "alan hata" }, e.message)); } } }), sonuc)),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Kaydet", sinif: "ana", basari: "SMTP ayarları kaydedildi", eylem: () => API.put("/api/bildirim/smtp", veri()) }] });
}
function testMailPenceresi() {
  const alici = h("input", { type: "email", placeholder: "ad.soyad@sirket.local", value: (D.ben && D.ben.eposta) || "" });
  pencere({ baslik: "Test maili gönder", ikon: "gonder", tur: "acc", icerik: h("div", {},
    h("div", { class: "alan" }, h("label", {}, "Alıcı"), alici), h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Kayıtlı SMTP ayarlarıyla kısa bir deneme maili gönderilir; sonuç Gönderim geçmişine yazılır.")),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Gönder", sinif: "ana", basari: "Test maili gönderildi", eylem: () => API.post("/api/bildirim/test", { alici: alici.value.trim() }) }] });
}
function bildirimKuralPenceresi(kat, k) {
  const dizinler = (D.durum || {}).dizinler || [];
  const ad = h("input", { type: "text", placeholder: "örn. Operasyon ekibi · kritikler", value: k ? k.ad : "" });
  const alicilar = h("textarea", { rows: 3, placeholder: "Her satıra bir adres (ya da ; ile ayırın)" }, k ? k.alicilar.join("\n") : "");
  const seviye = h("select", {}, ...[["BILGI", "Hepsi"], ["UYARI", "Uyarı ve üstü"], ["KRITIK", "Yalnız kritik"]].map(([v, e]) => h("option", { value: v, selected: v === (k ? k.seviye : "UYARI") ? true : null }, e)));
  let kapsamHepsi = !k || k.dizinler === null;
  const dizinSecim = h("div", { class: "secim-liste" }, ...dizinler.map(d => h("label", { class: "satir" },
    h("input", { type: "checkbox", value: d.id, checked: k && k.dizinler && k.dizinler.includes(d.id) ? true : null }), h("span", { class: "mono" }, d.yol))));
  const kapsamRadyo = (hepsi, e) => h("label", { class: "satir", style: { fontWeight: 500 } }, h("input", { type: "radio", name: "kapsam", checked: kapsamHepsi === hepsi ? true : null,
    onchange: () => { kapsamHepsi = hepsi; dizinSecim.classList.toggle("gizli", hepsi); } }), e);
  dizinSecim.classList.toggle("gizli", kapsamHepsi);
  let ozetMod = !!(k && k.ozet_dk);
  const ozetDk = h("input", { type: "number", min: 1, value: (k && k.ozet_dk) || 15, style: { width: "80px" } });
  const tekrarDk = h("input", { type: "number", min: 1, value: (k && k.tekrar_dk) || 60, style: { width: "80px" } });
  const duzelince = h("input", { type: "checkbox", checked: k ? !!k.duzelince : true });
  const aktif = h("input", { type: "checkbox", checked: k ? !!k.aktif : true });
  const secili = new Set(k ? k.olaylar : kat.filter(x => x.onerilen).map(x => x.kod));
  const onizleme = h("div", { class: "onizleme" });
  const onizle = () => {
    const ornek = kat.find(x => secili.has(x.kod));
    onizleme.replaceChildren(ornek ? h("div", {}, h("div", { class: "sessiz", style: { fontSize: "12px" } }, "Örnek mail"),
      h("div", {}, h("b", {}, `[FileWatcherPro] ${SEVIYE_ADI[ornek.seviye].toUpperCase()}: ${ornek.ornek_konu || ornek.ad}`)),
      h("div", { class: "ikincil", style: { fontSize: "12.5px", whiteSpace: "pre-line" } }, `${ornek.ornek_govde || ornek.aciklama}\n\nNe yapmalı: ${ornek.oneri || "—"}\nÖnyüz: http://sunucu:8770/#/alarmlar`)) :
      h("div", { class: "sessiz" }, "Olay seçin; örnek mail burada görünür."));
  };
  const gruplar = {};
  for (const o of kat) (gruplar[o.grup] = gruplar[o.grup] || []).push(o);
  const kutular = [];
  const katalogListe = h("div", { class: "katalog" }, ...Object.entries(gruplar).map(([g, liste]) => h("div", { class: "katalog-grup" },
    h("div", { class: "katalog-baslik" }, h("b", {}, g), h("button", { type: "button", class: "dg hayalet kucuk", onclick: () => {
      const hepsi = liste.every(o => secili.has(o.kod)); liste.forEach(o => hepsi ? secili.delete(o.kod) : secili.add(o.kod)); kutular.forEach(f => f()); onizle(); } }, "tümü")),
    ...liste.map(o => { const kutu = h("input", { type: "checkbox", checked: secili.has(o.kod) ? true : null, onchange: e => { e.target.checked ? secili.add(o.kod) : secili.delete(o.kod); onizle(); } });
      kutular.push(() => { kutu.checked = secili.has(o.kod); });
      return h("label", { class: "katalog-oge" }, kutu, h("div", {}, h("div", {}, o.ad, " ", rozet(SEVIYE_ADI[o.seviye], SEVIYE_SINIF[o.seviye]),
        o.kapsam === "dizin" ? h("span", { class: "sessiz", style: { fontSize: "11.5px" } }, " · dizine bağlı") : null), h("div", { class: "sessiz", style: { fontSize: "12px" } }, o.aciklama))); }))));
  const hazir = (e, fn) => h("button", { type: "button", class: "dg hayalet kucuk", onclick: () => { secili.clear(); kat.filter(fn).forEach(o => secili.add(o.kod)); kutular.forEach(f => f()); onizle(); } }, e);
  onizle();
  pencere({ baslik: k ? "Bildirim kuralını düzenle" : "Bildirim kuralı ekle", ikon: "zarf", tur: "acc", genis: "cok", icerik: h("div", { class: "iki-sutun" },
    h("div", {},
      h("div", { class: "alan" }, h("label", {}, "Kural adı"), ad),
      h("div", { class: "alan" }, h("label", {}, "Alıcılar"), alicilar),
      h("div", { class: "alan" }, h("label", {}, "Seviye"), seviye, h("div", { class: "ipucu" }, "Seçilen olaylardan yalnızca bu seviye ve üstündekiler gönderilir.")),
      k && k.kurallar ? h("div", { class: "serit bilgi", style: { margin: "0 0 12px" } }, ikon("bilgi", 18), h("div", { class: "metin" },
        `Bu bildirim kural penceresinden '${k.kural_adlari.join(", ")}' kuralına bağlandı: o kuralın dosya olayları ve dizininin olayları (ör. hiçbir regex'e uymayan dosya) bu alıcılara gider. Kapsamı kural penceresinden değiştirin.`)) : null,
      h("div", { class: `alan ${k && k.kurallar ? "gizli" : ""}` }, h("label", {}, "Dizinler"), kapsamRadyo(true, "Tüm dizinler"), kapsamRadyo(false, "Seçili dizinler"), dizinSecim,
        h("div", { class: "ipucu" }, "Dizin seçimi dizine bağlı olayları (erişim, askı, dosya olayları) süzer. Control-M ve sistem olayları dizinden bağımsızdır.")),
      h("div", { class: "alan" }, h("label", {}, "Gönderim"),
        h("label", { class: "satir", style: { fontWeight: 500 } }, h("input", { type: "radio", name: "gonderim", checked: !ozetMod ? true : null, onchange: () => { ozetMod = false; } }), "Anında (her olay ayrı mail)"),
        h("label", { class: "satir", style: { fontWeight: 500 } }, h("input", { type: "radio", name: "gonderim", checked: ozetMod ? true : null, onchange: () => { ozetMod = true; } }), "Özet: her ", ozetDk, " dakikada bir toplu"),
        h("div", { class: "satir", style: { marginTop: "6px" } }, "Aynı olay sürerse en fazla ", tekrarDk, " dakikada bir hatırlat"),
        h("label", { class: "satir", style: { fontWeight: 500, marginTop: "6px" } }, duzelince, "Olay düzelince de bildir"),
        h("label", { class: "satir", style: { fontWeight: 500, marginTop: "6px" } }, aktif, "Kural açık")),
      onizleme),
    h("div", {},
      h("div", { class: "satir" }, h("label", { style: { fontWeight: 600, margin: 0 } }, "Hangi olaylar mail olsun?"),
        h("div", { class: "satir", style: { marginLeft: "auto", gap: "4px" } }, hazir("Önerilen", o => o.onerilen), hazir("Yalnız kritikler", o => o.seviye === "KRITIK"), hazir("Hiçbiri", () => false))),
      katalogListe)),
    dugmeler: [{ metin: "Vazgeç", sinif: "hayalet" }, { metin: "Kaydet", sinif: "ana", basari: "Bildirim kuralı kaydedildi", eylem: () => {
      const v = { ad: ad.value.trim(), alicilar: alicilar.value.split(/[\n;,]+/).map(x => x.trim()).filter(Boolean), seviye: seviye.value, olaylar: [...secili],
        dizinler: kapsamHepsi ? null : [...dizinSecim.querySelectorAll("input:checked")].map(x => +x.value), ozet_dk: ozetMod ? parseInt(ozetDk.value, 10) : 0,
        kurallar: k && k.kurallar ? k.kurallar : null,
        tekrar_dk: parseInt(tekrarDk.value, 10), duzelince: duzelince.checked, aktif: aktif.checked };
      return k ? API.put(`/api/bildirim/kurallar/${k.id}`, v) : API.post("/api/bildirim/kurallar", v); } }] });
}

// ---------------------------------------------------------------- ALARMLAR (olay kataloğuyla)
function alarmKarti(a, kat) {
  const o = katalogBul(kat, a.kategori) || {};
  return h("div", { class: `alarm ${a.seviye}` }, h("div", { class: "sol" }),
    h("div", { class: "m" },
      h("div", { class: "satir", style: { gap: "8px" } }, rozet(o.ad || "Diğer", SEVIYE_SINIF[a.seviye]), a.nesne ? h("span", { class: "mono ikincil", style: { fontSize: "12px" } }, a.nesne) : null,
        a.mail ? h("span", { class: "sessiz", style: { fontSize: "12px" }, title: a.mail }, ikon("zarf", 13), " mail gitti") : null),
      h("div", { style: { marginTop: "4px" } }, a.mesaj),
      o.oneri ? h("div", { class: "oneri" }, h("b", {}, "Ne yapmalı: "), o.oneri) : null,
      h("div", { class: "z" }, `${SEVIYE_ADI[a.seviye]} · ${a.kaynak} · ilk ${once(a.ilk_zaman)} · son ${once(a.son_zaman)}${a.tekrar > 1 ? ` · ${a.tekrar} kez` : ""}`)),
    dugme("Onayla", { kucuk: true, rol: "OPERATOR", ipucu: "Alarmı kapatır; sorun sürerse yeniden açılır",
      onclick: () => eylem(() => API.post(`/api/alarmlar/${a.id}/onayla`), "Alarm onaylandı") }));
}
async function sayfaAlarmlar() {
  let liste, kat;
  try { [liste, kat] = await Promise.all([API.get("/api/alarmlar"), katalog()]); } catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  if (D.sayfa !== "alarmlar") return;
  const f = D.filtre.alarm || { seviye: "", grup: "", ara: "" };
  const uygun = a => (!f.seviye || a.seviye === f.seviye) && (!f.grup || (katalogBul(kat, a.kategori) || {}).grup === f.grup)
    && (!f.ara || `${a.mesaj} ${a.nesne || ""}`.toLocaleLowerCase("tr").includes(f.ara.toLocaleLowerCase("tr")));
  const sira = { KRITIK: 0, UYARI: 1, BILGI: 2 };
  const aktif = liste.filter(a => a.aktif && uygun(a)).sort((a, b) => sira[a.seviye] - sira[b.seviye] || b.son_zaman - a.son_zaman);
  const eski = liste.filter(a => !a.aktif && uygun(a));
  const secim = (ad, deger, secenekler, alan) => h("select", { "aria-label": ad, onchange: e => { D.filtre.alarm = { ...f, [alan]: e.target.value }; sayfaAlarmlar(); } },
    ...secenekler.map(([v, e]) => h("option", { value: v, selected: v === deger ? true : null }, e)));
  const filtre = h("div", { class: "satir" },
    secim("Seviye", f.seviye, [["", "Tüm seviyeler"], ["KRITIK", "Kritik"], ["UYARI", "Uyarı"], ["BILGI", "Bilgi"]], "seviye"),
    secim("Tür", f.grup, [["", "Tüm türler"], ...[...new Set(kat.map(x => x.grup))].map(g => [g, g])], "grup"),
    h("div", { class: "arama" }, ikon("ara"), h("input", { type: "text", id: "ara_alarm", placeholder: "Mesaj, dizin, hedef…", value: f.ara || "",
      oninput: e => { D.filtre.alarm = { ...f, ara: e.target.value }; clearTimeout(D._az); D._az = setTimeout(sayfaAlarmlar, 250); } })));
  icerikYaz([baslik("Alarmlar", "Sorun sürerse onaylanan alarm yeniden açılır. Mail bildirimleri Bildirimler sayfasından ayarlanır.", filtre),
    kart(`Aktif (${aktif.length})`, aktif.length ? h("div", {}, ...aktif.map(a => alarmKarti(a, kat))) : bosDurum("onay", "Aktif alarm yok."), null, { sifir: true }),
    h("div", { class: "bolum" }, kart(`Kapanmış (son ${eski.length})`, eski.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
      h("thead", {}, h("tr", {}, ...["Seviye", "Tür", "Mesaj", "Açıldı", "Kapandı", "Kapatan"].map(t => h("th", {}, t)))),
      h("tbody", {}, ...eski.map(a => h("tr", {}, h("td", {}, rozet(SEVIYE_ADI[a.seviye], SEVIYE_SINIF[a.seviye])), h("td", { class: "ikincil" }, (katalogBul(kat, a.kategori) || { ad: "Diğer" }).ad),
        h("td", {}, a.mesaj), h("td", { class: "ikincil" }, tarihSaat(a.ilk_zaman)), h("td", { class: "ikincil" }, tarihSaat(a.kapanma_zamani)),
        h("td", {}, a.onaylayan || "kendiliğinden")))))) : bosDurum("onay", "Kayıt yok."), null, { sifir: true }))]);
}
