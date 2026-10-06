/* FileWatcherPro önyüzü — Yapay zekâ asistanı (tasarım onaylandı 2026-09-30; arka uç: eklentiler/asistan).
   Yerel model, dış API yok: olay dizilerinden öğrenen küçük bir transformer; olaylar arası ilişkiyi self-attention ile yakalar.
   Gölge modunda çalışır: yalnızca öneri verir; tetik, kural, ayar değiştirmez, alarm açmaz.
   Sekmeler: Öneriler · Eğitim (loss eğrileri: öğreniyor mu, ezberliyor mu) · Güven (kalibrasyon, karne) · İlişkiler (dikkat haritası) · Veri.
   Menüde yalnızca asistan eklentisi kuruluysa (ya da prototipte) görünür. uygulama.js'deki yardımcıları kullanır; ondan ÖNCE yüklenir. */
"use strict";

const MODEL_DURUMU = {
  VERI_TOPLANIYOR: ["Veri toplanıyor", "info", "Yeterli veri olunca ilk eğitim kendiliğinden başlar."],
  HAZIR: ["Eğitime hazır", "info", "Yeterli veri var; ilk eğitim bekleniyor (sürekli öğrenme açıksa kendiliğinden başlar)."],
  OGRENIYOR: ["Öğreniyor", "ok", "Görmediği veride de iyileşiyor ve basit tahmincileri geçiyor."],
  DURAGAN: ["Öğrenmesi durdu", "ok", "Doğrulama kaybı artık iyileşmiyor; en iyi sürüm kullanımda."],
  EZBERLIYOR: ["Ezberliyor", "bad", "Gördüğü veride iyileşirken görmediği veride kötüleşiyor; en iyi sürüme dönüldü."],
  ANLAMSIZ: ["Anlamlı değil", "warn", "Basit tahmincileri (Markov) geçemiyor; öneriler kapalı."],
};
const ONERI_TURU = { ANOMALI: ["Anomali", "warn"], BEKLENEN_GELMEDI: ["Beklenen dosya gelmedi", "warn"], OLAGANDISI: ["Olağandışı", "warn"], ILISKI: ["İlişki", "acc"],
  KURAL: ["Kural önerisi", "info"], ESIK: ["Ayar önerisi", "info"] };
const asistanVar = () => !!window.PROTOTIP || ((D.durum || {}).eklentiler || []).some(e => e.ad === "asistan");
const yuzdeT = (v, n = 0) => v === null || v === undefined ? "—" : `%${ondalik(v * 100, n)}`;
const kayip = v => v === null || v === undefined ? "—" : ondalik(v, 2);

// ---------------------------------------------------------------- grafikler (SVG, kütüphanesiz)
const svgEl = (e, oz) => { const x = document.createElementNS("http://www.w3.org/2000/svg", e); for (const [k, v] of Object.entries(oz)) x.setAttribute(k, v); return x; };
const svgYazi = (metin, oz) => { const t = svgEl("text", oz); t.textContent = metin; return t; };
/* Eğitim eğrisi: x = eğitim adımı. seriler: [{ad, sinif, degerler}] (sinif: egitim | dogrulama | taban | taban2 | s1 | s2);
   dikey: {i, metin} (en iyi sürüm), bolge: [i1, i2] (ezber bölgesi, kırmızı taralı). */
function egriGrafik({ seriler, x, ust, alt = 0, yukseklik = 230, genislik = 620, xAd = "eğitim adımı", dikey = null, bolge = null, yBirim = "", ondalikY = 1 }) {
  const G = genislik, Y = yukseklik, sol = 46, sag = 12, tep = 10, taban = 34, ic = G - sol - sag, icY = Y - tep - taban;
  const svg = svgEl("svg", { viewBox: `0 0 ${G} ${Y}`, class: "grafik", role: "img", "aria-label": seriler.map(s => s.ad).join(", ") });
  const n = Math.max(1, x.length - 1), X = i => sol + (i / n) * ic, Yv = v => tep + icY - ((Math.min(Math.max(v, alt), ust) - alt) / (ust - alt)) * icY;
  if (bolge) svg.appendChild(svgEl("rect", { x: X(bolge[0]), y: tep, width: X(bolge[1]) - X(bolge[0]), height: icY, class: "bolge-bad" }));
  for (const oran of [0, 0.25, 0.5, 0.75, 1]) {
    const v = alt + (ust - alt) * oran;
    svg.appendChild(svgEl("line", { x1: sol, x2: G - sag, y1: Yv(v), y2: Yv(v), class: "izgara-cizgi" }));
    svg.appendChild(svgYazi(`${ondalik(v, ondalikY)}${yBirim}`, { x: sol - 6, y: Yv(v) + 4, class: "eksen", "text-anchor": "end" }));
  }
  for (const s of seriler) {
    const d = s.degerler.map((v, i) => v === null || v === undefined ? null : `${X(i).toFixed(1)},${Yv(v).toFixed(1)}`).filter(Boolean);
    if (d.length > 1) svg.appendChild(svgEl("polyline", { points: d.join(" "), class: `seri ${s.sinif}` }));
  }
  if (dikey) {
    svg.appendChild(svgEl("line", { x1: X(dikey.i), x2: X(dikey.i), y1: tep, y2: tep + icY, class: "dikey" }));
    svg.appendChild(svgYazi(dikey.metin, { x: X(dikey.i) + (dikey.i > n * 0.75 ? -5 : 5), y: tep + 12, class: "eksen dikey-yazi", "text-anchor": dikey.i > n * 0.75 ? "end" : "start" }));
  }
  for (const [i, a] of [[0, "start"], [Math.floor(n / 2), "middle"], [n, "end"]])
    svg.appendChild(svgYazi(typeof x[i] === "number" ? sayi(x[i]) : String(x[i]), { x: X(i), y: Y - 16, class: "eksen", "text-anchor": a }));
  svg.appendChild(svgYazi(xAd, { x: sol + ic / 2, y: Y - 2, class: "eksen", "text-anchor": "middle" }));
  return h("div", { class: "grafik-kap" }, svg, h("div", { class: "lejant" }, ...seriler.map(s => h("span", {}, h("i", { class: `nokta ${s.sinif}` }), s.ad))));
}
/* Güvenilirlik (kalibrasyon) diyagramı: model %p emin olduğunda gerçekte ne kadar doğru çıkıyor. Köşegen = mükemmel kalibrasyon. */
function guvenilirlikGrafik(kutular) {
  const G = 400, Y = 270, sol = 44, sag = 10, tep = 10, taban = 36, ic = G - sol - sag, icY = Y - tep - taban;
  const X = v => sol + v * ic, Yv = v => tep + icY - v * icY;
  const svg = svgEl("svg", { viewBox: `0 0 ${G} ${Y}`, class: "grafik", role: "img", "aria-label": "Güvenilirlik diyagramı" });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    svg.appendChild(svgEl("line", { x1: sol, x2: G - sag, y1: Yv(v), y2: Yv(v), class: "izgara-cizgi" }));
    svg.appendChild(svgYazi(`%${v * 100}`, { x: sol - 6, y: Yv(v) + 4, class: "eksen", "text-anchor": "end" }));
    svg.appendChild(svgYazi(`%${v * 100}`, { x: X(v), y: Y - 20, class: "eksen", "text-anchor": v === 0 ? "start" : v === 1 ? "end" : "middle" }));
  }
  for (const k of kutular) {
    if (!k.sayi) continue;
    const w = X(k.ust) - X(k.alt) - 3;
    svg.appendChild(svgEl("rect", { x: X(k.alt) + 1.5, y: Yv(k.gercek), width: w, height: Yv(0) - Yv(k.gercek), class: "cubuk", rx: 2 }));
    svg.appendChild(svgEl("line", { x1: X(k.alt) + 1.5, x2: X(k.alt) + 1.5 + w, y1: Yv(k.tahmin), y2: Yv(k.tahmin), class: "tahmin-cizgi" }));
  }
  svg.appendChild(svgEl("line", { x1: X(0), y1: Yv(0), x2: X(1), y2: Yv(1), class: "kosegen" }));
  svg.appendChild(svgYazi("modelin kendine güveni", { x: sol + ic / 2, y: Y - 3, class: "eksen", "text-anchor": "middle" }));
  return h("div", { class: "grafik-kap" }, svg, h("div", { class: "lejant" },
    h("span", {}, h("i", { class: "nokta cubuk" }), "Gerçekte doğru çıkma oranı"), h("span", {}, h("i", { class: "nokta tahmin-cizgi" }), "Ortalama güven"),
    h("span", {}, h("i", { class: "nokta kosegen" }), "Mükemmel kalibrasyon")));
}
/* Dikkat haritası: satır = tahmin edilen olay, sütun = modelin baktığı önceki olay; koyuluk = ortalama dikkat ağırlığı. */
function dikkatHaritasi(turler, matris) {
  const en = Math.max(...matris.flat());
  return h("div", { class: "tablo-sar" }, h("table", { class: "isi" },
    h("thead", {}, h("tr", {}, h("th", { class: "kose" }, h("div", {}, "baktığı önceki olay →"), h("div", {}, "tahmin edilen ↓")), ...turler.map(t => h("th", { class: "dik" }, h("span", {}, t))))),
    h("tbody", {}, ...turler.map((t, i) => h("tr", {}, h("th", {}, t), ...matris[i].map((v, j) => {
      const p = Math.round((v / en) * 100);
      return h("td", { style: { background: `color-mix(in srgb, var(--acc) ${p}%, var(--bg2))`, color: p > 55 ? "#fff" : "var(--tx2)" },
        title: `${t} beklenirken '${turler[j]}' olayına sıklığının ${ondalik(v, 1)} katı bakılıyor` }, v >= Math.max(1.5, en * 0.35) ? ondalik(v, 1) : "");
    }))))));
}

// ---------------------------------------------------------------- sayfa
async function sayfaAsistan(yenileme) {
  if (!yenileme || !D.veri.asistan || Date.now() - (D.veri.asistan_zaman || 0) > 5000) {
    try { D.veri.asistan = await API.get("/api/asistan"); D.veri.asistan_zaman = Date.now(); }
    catch (e) { return icerikYaz(bosDurum("uyari", e.message)); }
  }
  if (D.sayfa !== "asistan") return;
  const v = D.veri.asistan, du = v.durum, sekme = D.filtre.asistan_sekme || "oneriler";
  const md = MODEL_DURUMU[du.model_durumu] || [du.model_durumu, "", ""];
  const yetersiz = du.model_durumu === "VERI_TOPLANIYOR";
  const acik = v.oneriler.filter(o => o.durum === "ACIK"), gb = (v.guven || {}).geri_bildirim || {};
  const guvenVar = v.guven_var ?? !!(v.guven && v.guven.karne), torchYok = du.torch === false;
  const kpi = (ad, deger, alt, sinif, ik) => h("div", { class: `kart kpi ${sinif || ""}` }, h("div", { class: "ad" }, ikon(ik, 14), ad), h("div", { class: "deger" }, deger), h("div", { class: "alt" }, alt));
  const sekmeler = h("div", { class: "sekme", role: "tablist" }, ...[["oneriler", `Öneriler${acik.length ? ` (${acik.length})` : ""}`], ["anomali", `Anomaliler${(v.anomali || []).some(x => Object.values(x.anomali).some(Boolean)) ? " •" : ""}`], ["egitim", "Eğitim"], ["guven", "Güven"], ["iliskiler", "İlişkiler"], ["veri", "Veri"]].map(([k, e]) =>
    h("button", { role: "tab", class: sekme === k ? "secili" : "", onclick: () => { D.filtre.asistan_sekme = k; sayfaAsistan(true); } }, e)));
  const govde = { oneriler: asistanOneriler, anomali: asistanAnomali, egitim: asistanEgitim, guven: asistanGuven, iliskiler: asistanIliskiler, veri: asistanVeri }[sekme](v);
  icerikYaz([baslik("Yapay zekâ asistanı", "Bu sunucuda çalışan, olaylardan kendi kendine öğrenen yerel model. Veri dışarı gitmez; tetik akışına karışmaz.",
      h("div", { class: "satir" },
        dugme("Kendini sına", { ikon: "sihir", rol: "OPERATOR", ipucu: "İçine bilinen bir ilişki gömülmüş yapay veriyle ayrı bir modeli eğitip ilişkiyi bulup bulmadığına bakar", onclick: () => kendiniSinaPenceresi() }),
        dugme(du.egitiliyor ? "Eğitiliyor…" : "Şimdi eğit", { ikon: "oynat", sinif: "ana", rol: "YONETICI", devre_disi: yetersiz || du.egitiliyor || torchYok,
          ipucu: torchYok ? "PyTorch kurulu değil" : yetersiz ? "Önce yeterli veri toplanmalı (Veri sekmesi)" : "Yeni olaylarla bir eğitim turu",
          onclick: () => eylem(() => API.post("/api/asistan/egit"), "Eğitim başladı; ilerleme 'Son eğitim' kutusunda") }))),
    torchYok ? h("div", { class: "serit uyari" }, ikon("uyari", 20), h("div", { class: "metin" }, h("b", {}, "PyTorch kurulu değil. "),
      du.hata || "Olaylar toplanıyor ama model eğitilemiyor.")) : null,
    h("div", { class: "serit bilgi" }, ikon("kalkan", 20), h("div", { class: "metin" }, h("b", {}, "Gölge modu. "),
      v.ayarlar.anomali_alarm ? "Asistan hiçbir tetiği, kuralı ya da ayarı değiştirmez. Anomali alarmı açık: anomaliler uyarı alarmı olarak da açılır (mail kurallarına gidebilir); diğer öneriler yalnız öneridir."
        : "Asistan yalnızca öneri verir: hiçbir tetiği, kuralı ya da ayarı değiştirmez, alarm açmaz. Her önerideki güven, modelin geçmişte o güvenle ne kadar isabet ettiğine göre ayarlanmıştır.")),
    h("div", { class: "izgara k4" },
      kpi("Model", md[0], md[2], md[1] === "bad" ? "bad" : md[1] === "warn" ? "warn" : "", "sihir"),
      kpi("Güven", guvenVar ? yuzdeT(v.guven.karne.puan) : "—", guvenVar ? `${v.guven.karne.derece} · nasıl hesaplandığı Güven sekmesinde` : "henüz eğitilmedi", "", "kalkan"),
      kpi("Açık öneri", sayi(acik.length), gb.toplam ? `geri bildirimlerin ${yuzdeT(gb.oran)}'i 'faydalı'` : "henüz geri bildirim yok", "", "bilgi"),
      kpi("Son eğitim", du.egitiliyor ? `%${Math.round((du.egitim_ilerleme || 0) * 100)}` : du.son_egitim ? once(du.son_egitim) : "henüz yok",
        du.egitiliyor ? "eğitiliyor (düşük öncelik; izleme etkilenmez)" : du.son_egitim ? `sürüm ${du.surum ?? "—"} · sonraki: ${sayi(du.sonraki_egitim_olay)} yeni olayda`
          : `${sayi(v.veri.olay_sayisi)} / ${sayi(v.veri.asgari_olay)} olay toplandı`, "", "saat")),
    h("div", { class: "bolum" }, sekmeler, govde)]);
}

// ---------------------------------------------------------------- Öneriler
function asistanOneriler(v) {
  if ((v.durum.model_durumu === "VERI_TOPLANIYOR" || v.durum.model_durumu === "HAZIR") && !v.oneriler.length) return veriToplaniyor(v);   // istatistik önerileri (anomali, beklenen gelmedi) model beklemeden görünür
  const f = D.filtre.asistan_oneri || "ACIK";
  const liste = v.oneriler.filter(o => f === "ACIK" ? o.durum === "ACIK" : o.durum !== "ACIK");
  const secim = h("div", { class: "sekme kucuk", role: "tablist" }, ...[["ACIK", "Açık"], ["KAPALI", "Geri bildirim verilen / kapanan"]].map(([k, e]) =>
    h("button", { role: "tab", class: f === k ? "secili" : "", onclick: () => { D.filtre.asistan_oneri = k; sayfaAsistan(true); } }, e)));
  const kartlar = liste.map(o => {
    const [tAd, tSinif] = ONERI_TURU[o.tur] || [o.tur, ""];
    return h("div", { class: `oneri-kart ${tSinif}` },
      h("div", { class: "ok-ust" }, rozet(tAd, tSinif), o.nesne ? h("span", { class: "mono ikincil", style: { fontSize: "12px" } }, o.nesne) : null,
        h("span", { class: "sessiz", style: { fontSize: "12px", marginLeft: "auto" } }, `${o.kaynak === "kural" ? "kurala dayalı (model değil)" : o.kaynak === "istatistik" ? "istatistik (geçmiş günler)" : `model · sürüm ${o.surum ?? "—"}`} · ${once(o.zaman)}`)),
      h("div", { class: "ok-govde" },
        h("div", {}, h("div", { class: "ok-baslik" }, o.baslik), h("div", { class: "ikincil" }, o.metin),
          o.kanit && o.kanit.length ? h("ul", { class: "kanit" }, ...o.kanit.map(k => h("li", {}, k))) : null,
          o.oneri ? h("div", { class: "oneri" }, h("b", {}, "Önerilen: "), o.oneri) : null),
        o.guven !== null ? h("div", { class: "guven-kutu", title: "Kalibre edilmiş güven: bu güvenle verilen önerilerin geçmişte doğru çıkma oranı" },
          h("div", { class: "sessiz", style: { fontSize: "11.5px" } }, "güven"), h("div", { class: "guven-deger" }, yuzdeT(o.guven)),
          h("div", { class: "ilerleme" }, h("i", { style: { width: `${o.guven * 100}%` } }))) : h("div", { class: "guven-kutu" }, h("div", { class: "sessiz", style: { fontSize: "11.5px" } }, "kurala dayalı"))),
      o.durum === "ACIK" ? h("div", { class: "ok-alt" },
        dugme("Faydalı", { ikon: "onay", kucuk: true, rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/asistan/oneriler/${o.id}/geri_bildirim`, { faydali: true }), "Kaydedildi: faydalı (öneri isabetine girer)") }),
        dugme("Faydasız", { ikon: "carpi", kucuk: true, rol: "OPERATOR", onclick: () => eylem(() => API.post(`/api/asistan/oneriler/${o.id}/geri_bildirim`, { faydali: false }), "Kaydedildi: faydasız (öneri isabetine girer)") }),
        h("span", { class: "sessiz", style: { fontSize: "12px" } }, "Geri bildirim güven ölçümüne girer; öneri kapanır."))
        : h("div", { class: "ok-alt sessiz", style: { fontSize: "12px" } }, o.durum === "FAYDALI" ? `✓ Faydalı · ${o.isaretleyen}` : o.durum === "FAYDASIZ" ? `✗ Faydasız · ${o.isaretleyen}` : "Kendiliğinden kapandı (durum düzeldi)"));
  });
  return h("div", {}, secim, kartlar.length ? h("div", { class: "oneri-liste" }, ...kartlar) : kart(null, bosDurum("onay", f === "ACIK" ? "Şu an öneri yok." : "Kayıt yok.")));
}
// ---------------------------------------------------------------- Anomaliler (istatistik; model gerekmez)
function asistanAnomali(v) {
  const l = v.anomali || [], a = v.ayarlar;
  const ayarKutu = (anahtar, metin, basari) => h("label", { class: "satir", style: { fontWeight: 500 } },
    h("input", { type: "checkbox", checked: a[anahtar] ? true : null, disabled: yetkili("YONETICI") ? null : true,
      onchange: ev => eylem(() => API.put("/api/asistan/ayarlar", { [anahtar]: ev.target.checked }), basari(ev.target.checked)) }), metin);
  const ayarlar = h("div", { class: "satir", style: { margin: "0 0 12px", gap: "22px" } },
    ayarKutu("anomali", "Anomali takibi", x => x ? "Anomali takibi açıldı" : "Anomali takibi kapatıldı"),
    ayarKutu("anomali_alarm", "Anomaliyi alarm olarak da aç (Bildirimler ve kurala bağlı mail kurallarına gider)", x => x ? "Anomali alarmı açıldı" : "Anomali alarmı kapatıldı"),
    h("span", { class: "sessiz", style: { fontSize: "12.5px" } }, `Bir kuralın normali en az ${a.anomali_asgari} dosyadan çıkarılır.`));
  const aciklama = h("div", { class: "serit bilgi" }, ikon("bilgi", 20), h("div", { class: "metin" }, h("b", {}, "İstatistik, model değil. "),
    "Her kural (dosya türü) için dosya boyutu, teslim süresi ve günlük adet geçmişinden normal aralık çıkarılır (medyan / MAD, %5–%95 dilimi). Yeni değer bunun dışına düşerse Öneriler'e kanıtıyla yazılır. Dosya adı ve içerik toplanmaz."));
  const hucre = (deger, kotu) => h("td", { class: kotu ? "anomali-kotu" : null }, deger);
  const tablo = l.length ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Kural (dosya türü)", "Geçmiş", "Boyut: normal aralık", "Son dosya", "Teslim süresi: genelde / son 10", "Günlük adet: genelde / dün / bugün", "Durum"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...l.map(x => { const an = x.anomali, anomali = Object.entries(an).filter(([, b]) => b).map(([t]) => ({ boyut: "boyut", sure: "teslim süresi", adet: "günlük adet" }[t]));
      return h("tr", {},
        h("td", { class: "anomali-kural" }, h("b", {}, x.kural), h("div", { class: "sessiz mono kisalt", title: x.dizin }, h("span", { dir: "ltr" }, x.dizin))),
        h("td", { class: "sayi" }, sayi(x.n), " dosya"),
        h("td", { class: "mono tasma-yok" }, x.boyut_p5 === null ? "—" : `${boyutMetni(Math.round(x.boyut_p5))} – ${boyutMetni(Math.round(x.boyut_p95))}`,
          x.boyut_medyan === null ? null : h("div", { class: "sessiz", style: { fontSize: "11.5px" } }, `medyan ${boyutMetni(Math.round(x.boyut_medyan))}`)),
        hucre(h("span", { class: "mono tasma-yok" }, x.son_boyut === null ? "—" : boyutMetni(Math.round(x.son_boyut))), an.boyut),
        hucre(x.sure_medyan === null ? "—" : `${sureMetni(x.sure_medyan)} / ${sureMetni(x.sure_son)}`, an.sure),
        hucre(x.gunluk_medyan === null ? "—" : `${x.gunluk_medyan} / ${x.dun} / ${x.bugun}`, an.adet),
        h("td", {}, !x.yeterli ? rozet(`Veri toplanıyor (${x.n}/${a.anomali_asgari})`, "") : anomali.length ? rozet(`Anomali: ${anomali.join(", ")}`, "warn") : rozet("Normal", "ok")));
    })))) : bosDurum("nabiz", a.anomali ? "Henüz ölçüm yok: kurallara uyan dosyalar geldikçe her kuralın normali çıkarılır." : "Anomali takibi kapalı.");
  return h("div", {}, ayarlar, aciklama, kart(null, tablo, null, { sifir: true }));
}
function veriToplaniyor(v) {
  const x = v.veri;
  const cubuk = (ad, deger, hedef, birim) => h("div", { class: "alan" }, h("div", { class: "satir" }, h("b", {}, ad), h("span", { class: "sessiz", style: { marginLeft: "auto" } }, `${sayi(deger)} / ${sayi(hedef)} ${birim}`)),
    h("div", { class: "ilerleme" }, h("i", { style: { width: `${Math.min(100, (deger / hedef) * 100)}%` } })));
  return h("div", { class: "izgara k2" },
    kart(v.durum.model_durumu === "HAZIR" ? "Eğitime hazır" : "Veri toplanıyor", h("div", {},
      h("p", { style: { marginTop: 0 } }, v.durum.model_durumu === "HAZIR"
        ? `Yeterli veri toplandı. İlk eğitim ${v.ayarlar.surekli ? "kendiliğinden başlayacak" : "'Şimdi eğit' ile başlatılabilir (sürekli öğrenme kapalı)"}.`
        : "Asistan henüz eğitilmedi. Çalıştıkça olayları topluyor (dosya gelişleri, teslim sonuçları, alarmlar, kaynak eşikleri). İlk eğitim iki koşul birlikte sağlanınca kendiliğinden başlar:"),
      cubuk("Olay", x.olay_sayisi, x.asgari_olay, "olay"), cubuk("Süre", x.gun_sayisi, x.asgari_gun, "gün"),
      h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Neden bekliyor? Az veriyle eğitilen model ezberler: gördüğü birkaç günü tekrar eder, yeni günde yanılır. Günlük ve haftalık düzeni görebilmesi için en az birkaç günlük veri gerekir."))),
    kart("Beklerken", h("div", {},
      h("p", { style: { marginTop: 0 } }, h("b", {}, "Kendini sına: "), "asistan, içine bilinen bir ilişki gömülmüş yapay bir olay akışı üretir, ayrı bir modeli yalnızca bununla eğitir ve ilişkiyi bulup bulmadığını gösterir. Gerçek veriye ve gerçek modele dokunmaz."),
      dugme("Kendini sına", { ikon: "sihir", sinif: "ana", rol: "OPERATOR", onclick: () => kendiniSinaPenceresi() }),
      v.kendini_sina && v.kendini_sina.son ? h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, `Son sınama: ${tarihSaat(v.kendini_sina.son.zaman)} · ${v.kendini_sina.son.sonuc === "GECTI" ? "geçti ✓" : "kaldı ✗"}`) : null)));
}

// ---------------------------------------------------------------- Eğitim
function asistanEgitim(v) {
  const e = v.egitim, du = v.durum, md = MODEL_DURUMU[du.model_durumu] || ["", "", ""];
  const a = v.ayarlar;
  const alan = (etiket, anahtar, ipucu, oz = {}) => h("div", { class: "alan" }, h("label", {}, etiket), h("input", { type: "number", value: a[anahtar], step: "any", "data-anahtar": anahtar, ...oz }), ipucu ? h("div", { class: "ipucu" }, ipucu) : null);
  const gelismis = h("details", { class: "yardim" }, h("summary", {}, ikon("ayar", 15), " Gelişmiş ayarlar (model yapısı ve eğitim)"),
    h("div", { class: "yardim-ic" },
      h("div", { class: "izgara k4", style: { gap: "10px" } },
        alan("Bağlam (olay)", "baglam", "Model tahmin ederken geriye doğru kaç olaya bakar."), alan("Katman", "katman", "Transformer katmanı."),
        alan("Dikkat başı", "bas", "Her katmandaki self-attention başı."), alan("Boyut", "boyut", "Olay gösteriminin boyutu."),
        alan("Öğrenme oranı", "ogrenme_orani", null), alan("Dropout", "dropout", "Ezberlemeyi azaltır."), alan("Ağırlık azaltma", "agirlik_azaltma", "Ezberlemeyi azaltır."),
        alan("CPU iş parçacığı", "is_parcacigi", "İzlemeyi yavaşlatmasın diye 1 önerilir.")),
      h("p", { class: "sessiz", style: { fontSize: "12.5px" } }, "Yapı değişince model sıfırdan eğitilir; eski sürümler saklanır. Değişiklikler denetim kaydına yazılır."),
      dugme("Ayarları kaydet", { sinif: "ana", kucuk: true, rol: "YONETICI", onclick: ev => {
        const yeni = {}; ev.target.closest(".yardim-ic").querySelectorAll("input[data-anahtar]").forEach(i => { yeni[i.dataset.anahtar] = parseFloat(i.value); });
        eylem(() => API.put("/api/asistan/ayarlar", yeni), "Asistan ayarları kaydedildi"); } })));
  const kontrol = kart("Eğitim", h("div", {},
    h("label", { class: "satir", style: { fontWeight: 600 } }, h("input", { type: "checkbox", checked: a.surekli, disabled: !yetkili("YONETICI"),
      onchange: ev => eylem(() => API.put("/api/asistan/ayarlar", { surekli: ev.target.checked }), ev.target.checked ? "Sürekli öğrenme açıldı" : "Sürekli öğrenme kapatıldı") }), "Sürekli öğrenme (çevrimiçi)"),
    h("div", { class: "ipucu" }, `Her ${sayi(a.egitim_sikligi)} yeni olayda bir tur: önce yeni olaylar tahmin edilir (görmeden ölçüm), sonra onlarla en fazla ${sayi(a.egitim_adimi)} adım eğitilir. Doğrulama kaybı kötüleşen sürüm kullanılmaz.`),
    h("dl", { class: "bilgi-izgara dar", style: { marginTop: "12px" } },
      h("dt", {}, "Model"), h("dd", {}, `Transformer (nedensel) · ${a.katman} katman · ${a.bas} dikkat başı · ${a.boyut} boyut · bağlam ${a.baglam} olay`),
      h("dt", {}, "Parametre"), h("dd", {}, `${sayi(du.parametre)} (küçük: az veriyle ezberlemesin)`),
      h("dt", {}, "Çalıştığı yer"), h("dd", {}, `${du.cihaz || "CPU"}${du.son_tur_sn ? ` · son tur ${du.son_tur_sn} sn` : ""}`),
      h("dt", {}, "Doğrulama"), h("dd", {}, du.dogrulama_aciklama || "Son %20'lik zaman dilimi eğitime hiç girmez (zamana göre ayrım, karıştırma yok)")),
    h("div", { class: "satir", style: { marginTop: "10px" } },
      e && e.en_iyi_surum ? dugme("En iyi sürüme dön", { kucuk: true, rol: "YONETICI", onclick: () => onayla("En iyi sürüme dön", `Doğrulama kaybı en düşük sürüm (${e.en_iyi_surum}) kullanılacak.`, () => API.post(`/api/asistan/surum/${e.en_iyi_surum}/kullan`), "acc") }) : null,
      dugme("Modeli sıfırla", { kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI", onclick: () => onayla("Modeli sıfırla", "Öğrenilen her şey silinir, model toplanan veriyle sıfırdan eğitilir. Toplanan veri silinmez.", () => API.post("/api/asistan/sifirla"), "bad") }))));
  if (!e) return h("div", {}, h("div", { class: "izgara k3" }, h("div", { class: "genis2" }, kart("Kayıp eğrisi (loss)", bosDurum("liste",
      du.model_durumu === "HAZIR" ? "Yeterli veri var; ilk eğitimden sonra burada eğitim ve doğrulama kaybı eğrileri görünür." : "İlk eğitimden sonra burada eğitim ve doğrulama kaybı eğrileri görünür."))), kontrol),
    h("div", { class: "bolum" }, gelismis));
  const enIyi = e.adimlar.indexOf(e.en_iyi_adim), ezberI = e.ezber_baslangic !== null && e.ezber_baslangic !== undefined ? e.adimlar.indexOf(e.ezber_baslangic) : -1;
  const ust = Math.ceil(Math.max(...e.egitim_kaybi, ...e.dogrulama_kaybi, e.taban_markov, e.taban_siklik) * 2) / 2;
  const grafik = egriGrafik({ x: e.adimlar, ust, alt: 0, ondalikY: 2, dikey: enIyi >= 0 ? { i: enIyi, metin: `en iyi · sürüm ${e.en_iyi_surum ?? "—"}` } : null, bolge: ezberI >= 0 ? [ezberI, e.adimlar.length - 1] : null,
    seriler: [{ ad: "Eğitim kaybı (gördüğü veri)", sinif: "egitim", degerler: e.egitim_kaybi }, { ad: "Doğrulama kaybı (hiç görmediği son günler)", sinif: "dogrulama", degerler: e.dogrulama_kaybi },
      { ad: `Markov tabanı (${kayip(e.taban_markov)})`, sinif: "taban", degerler: e.adimlar.map(() => e.taban_markov) }, { ad: `Sıklık tabanı (${kayip(e.taban_siklik)})`, sinif: "taban2", degerler: e.adimlar.map(() => e.taban_siklik) }] });
  const fark = e.dogrulama_kaybi.map((d, i) => d - e.egitim_kaybi[i]);
  const farkGrafik = egriGrafik({ x: e.adimlar, ust: Math.max(0.6, Math.ceil(Math.max(...fark) * 10) / 10), alt: Math.min(0, Math.floor(Math.min(...fark) * 10) / 10), yukseklik: 170, genislik: 380, ondalikY: 2,
    seriler: [{ ad: "Doğrulama − eğitim (genelleme farkı)", sinif: "dogrulama", degerler: fark }], bolge: ezberI >= 0 ? [ezberI, e.adimlar.length - 1] : null });
  const karar = h("div", { class: `karar ${md[1]}` }, h("div", { class: "satir" }, rozet(md[0], md[1], { style: { fontSize: "13px", padding: "4px 12px" } }), h("b", {}, e.karar.baslik)),
    h("ul", {}, ...e.karar.maddeler.map(m => h("li", {}, m))));
  const surumler = h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Sürüm", "Zaman", "Veri", "Eğitim kaybı", "Doğrulama kaybı", "Markov'a göre", "Durum", ""].map(t => h("th", {}, t)))),
    h("tbody", {}, ...e.surumler.map(s => h("tr", {}, h("td", { class: "sayi" }, h("b", {}, s.surum)), h("td", { class: "ikincil" }, tarihSaat(s.zaman)), h("td", { class: "sayi" }, `${sayi(s.olay)} olay`),
      h("td", { class: "sayi" }, kayip(s.egitim)), h("td", { class: "sayi" }, kayip(s.dogrulama)),
      h("td", { class: "sayi", style: { color: s.markova_gore < 0 ? "var(--ok)" : "var(--bad)" } }, `${s.markova_gore < 0 ? "" : "+"}${ondalik(s.markova_gore * 100, 0)}%`),
      h("td", {}, s.durum === "KULLANIMDA" ? rozet("Kullanımda", "ok") : s.durum === "EZBER" ? rozet("Ezberledi · kullanılmadı", "bad") : s.durum === "ANLAMSIZ" ? rozet("Tabanı geçemedi", "warn") : s.durum === "GERILEDI" ? rozet("Geriledi · kullanılmadı", "warn") : rozet("Eski", "")),
      h("td", { style: { textAlign: "right" } }, s.durum === "ESKI" ? dugme("Kullan", { kucuk: true, rol: "YONETICI", ipucu: "Bu sürüme dön", onclick: () => onayla("Model sürümüne dön", `Sürüm ${s.surum} yeniden kullanılacak.`, () => API.post(`/api/asistan/surum/${s.surum}/kullan`), "acc") }) : null))))));
  return h("div", {},
    h("div", { class: "izgara k3" }, h("div", { class: "genis2" }, kart("Kayıp eğrisi (loss)", h("div", {}, grafik, karar))),
      h("div", {}, kart("Nasıl okunur?", h("ul", { class: "sonuc-listesi", style: { margin: 0 } },
        h("li", {}, h("b", {}, "Eğitim kaybı "), "modelin gördüğü veride, ", h("b", {}, "doğrulama kaybı "), "hiç görmediği son günlerde ölçülür. Düşük = daha iyi tahmin."),
        h("li", {}, h("b", {}, "Öğreniyor: "), "ikisi birlikte düşüyor ve doğrulama kaybı taban çizgilerinin altında."),
        h("li", {}, h("b", {}, "Ezberliyor: "), "eğitim kaybı düşerken doğrulama kaybı yükseliyor (kırmızı bölge). O sürüm kullanılmaz, en iyi sürüme dönülür."),
        h("li", {}, h("b", {}, "Anlamlı değil: "), "doğrulama kaybı Markov tabanının (yalnızca 'bir önceki olaya bakan' basit tahminci) altına inemiyor: model bir şey katmıyor, öneriler kapanır."))),
        h("div", { class: "bolum" }, kart("Genelleme farkı", farkGrafik)))),
    h("div", { class: "bolum" }, h("div", { class: "izgara k3" }, kontrol, h("div", { class: "genis2" }, kart("Sürümler", surumler, null, { sifir: true })))),
    h("div", { class: "bolum" }, gelismis));
}

// ---------------------------------------------------------------- Güven
function asistanGuven(v) {
  if (!(v.guven_var ?? !!(v.guven && v.guven.karne))) return kart("Güven", bosDurum("kalkan", "İlk eğitimden sonra modelin ne kadar güvenilir olduğu burada ölçülür."));
  const g = v.guven, k = g.karne;
  const isaret = d => d === "iyi" ? h("span", { class: "isaret ok" }, "✓") : d === "orta" ? h("span", { class: "isaret warn" }, "!") : h("span", { class: "isaret bad" }, "✗");
  const karne = kart("Güven karnesi", h("div", {},
    h("div", { class: "karne-ust" }, h("div", { class: "karne-puan" }, yuzdeT(k.puan)), h("div", {}, h("b", {}, k.derece), h("div", { class: "ikincil" }, k.ozet))),
    h("table", { class: "tablo" }, h("tbody", {}, ...k.olcutler.map(o => h("tr", {}, h("td", { style: { width: "26px" } }, isaret(o.durum)), h("td", {}, h("b", {}, o.ad), h("div", { class: "sessiz", style: { fontSize: "12px" } }, o.aciklama)),
      h("td", { class: "sayi" }, o.deger), h("td", { class: "sayi sessiz" }, `ağırlık ${yuzdeT(o.agirlik)}`))))),
    h("p", { class: "sessiz", style: { fontSize: "12.5px", marginBottom: 0 } }, "Güven puanı bu ölçütlerin ağırlıklı ortalamasıdır. Tek bir önerinin güveni ayrıca kalibre edilir: model o önerideki kadar emin olduğunda geçmişte ne sıklıkla haklı çıktıysa o gösterilir.")));
  const kalibrasyon = kart("Kalibrasyon: söylediği güven gerçek mi?", h("div", {}, guvenilirlikGrafik(g.guvenilirlik),
    h("p", { class: "ikincil", style: { fontSize: "12.8px", marginBottom: 0 } }, `Beklenen kalibrasyon hatası (ECE): ${yuzdeT(g.ece, 1)} (iyi: %5'in altı). `, g.ornek_cumle)));
  const basari = kart("Tahmin başarısı (hiç görmediği veride)", h("div", {},
    h("div", { class: "tablo-sar" }, h("table", { class: "tablo" }, h("thead", {}, h("tr", {}, ...["", "Model", "Markov tabanı", "Sıklık tabanı"].map(t => h("th", {}, t)))),
      h("tbody", {}, ...g.basari.map(r => h("tr", {}, h("td", {}, h("b", {}, r.ad), r.aciklama ? h("div", { class: "sessiz", style: { fontSize: "12px" } }, r.aciklama) : null),
        h("td", { class: "sayi", style: { fontWeight: 650 } }, r.model), h("td", { class: "sayi" }, r.markov), h("td", { class: "sayi" }, r.siklik)))))),
    h("div", { style: { marginTop: "10px" } }, egriGrafik({ x: g.onceden.gunler, ust: 1, alt: 0, yukseklik: 170, genislik: 520, xAd: "gün", yBirim: "", ondalikY: 2,
      seriler: [{ ad: "Model: ilk tahmin doğru", sinif: "dogrulama", degerler: g.onceden.model }, { ad: "Markov tabanı", sinif: "taban", degerler: g.onceden.markov }] })),
    h("p", { class: "sessiz", style: { fontSize: "12.5px", marginBottom: 0 } }, "'Önce tahmin et, sonra öğren': her yeni olay, model onu görmeden önce tahmin edilir; eğitim ondan sonra yapılır. Bu yüzden bu grafik ezberden etkilenmez.")));
  const gb = g.geri_bildirim;
  const geriBildirim = kart("Önerilerin isabeti (sizin geri bildiriminizle)", gb.toplam ? h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
    h("thead", {}, h("tr", {}, ...["Öneri türü", "Faydalı", "Faydasız", "İsabet"].map(t => h("th", {}, t)))),
    h("tbody", {}, ...gb.turler.map(t => h("tr", {}, h("td", {}, (ONERI_TURU[t.tur] || [t.tur])[0]), h("td", { class: "sayi" }, t.faydali), h("td", { class: "sayi" }, t.faydasiz),
      h("td", { class: "sayi" }, t.faydali + t.faydasiz >= 5 ? yuzdeT(t.faydali / (t.faydali + t.faydasiz)) : h("span", { class: "sessiz" }, "az örnek"))))))) : bosDurum("liste", "Henüz geri bildirim yok."));
  return h("div", {}, h("div", { class: "izgara k2" }, karne, kalibrasyon), h("div", { class: "bolum" }, h("div", { class: "izgara k2" }, basari, geriBildirim)));
}

// ---------------------------------------------------------------- İlişkiler
function asistanIliskiler(v) {
  if (!v.iliskiler || !v.iliskiler.turler.length) return kart("İlişkiler", bosDurum("nabiz", "İlk eğitimden sonra olaylar arası ilişkiler (dikkat haritası) burada görünür."));
  const r = v.iliskiler;
  return h("div", {},
    h("div", { class: "izgara k3" },
      h("div", { class: "genis2" }, kart("Dikkat haritası (self-attention)", dikkatHaritasi(r.turler, r.matris))),
      kart("Nasıl okunur?", h("ul", { class: "sonuc-listesi", style: { margin: 0 } },
        h("li", {}, "Model bir olayı tahmin ederken önceki olaylardan hangisine ne kadar 'baktığını' kendisi öğrenir (self-attention)."),
        h("li", {}, h("b", {}, "Satır: "), "tahmin edilen olay. ", h("b", {}, "Sütun: "), "o sırada bakılan önceki olay."),
        h("li", {}, h("b", {}, "Değer: "), "dikkat oranı: model o olaya bağlamdaki sıklığının kaç katı bakıyor (1 = sıklığı kadar, 5 = beş katı). Sık olaylar doğal olarak çok dikkat alır; oran bunu düzeltir."),
        h("li", {}, h("b", {}, "Koyu hücre: "), "satırdaki olay beklenirken sütundaki olay güçlü bir ipucu. Her katmanın her dikkat başı ayrı ölçülür, en güçlüsü gösterilir; değerler doğrulama verisindeki tahminlerin ortalamasıdır."),
        h("li", {}, "Örnek: 'Control-M devre kesildi' satırında 'Lojistik yanıtsız' sütunu koyu: model, devre kesilmesini bu olaydan önceden seziyor.")))),
    h("div", { class: "bolum" },
      kart("Bulunan ilişkiler", h("div", {}, h("div", { class: "tablo-sar" }, h("table", { class: "tablo" },
        h("thead", {}, h("tr", {}, ...["Önce", "Sonra", "Tipik aralık", "Dikkat", "İstatistik (lift)", ""].map(t => h("th", {}, t)))),
        h("tbody", {}, ...r.liste.map(x => h("tr", {}, h("td", {}, x.once), h("td", {}, x.sonra), h("td", { class: "ikincil" }, x.aralik),
          h("td", { class: "sayi" }, `${ondalik(x.dikkat, 1)} ×`), h("td", { class: "sayi" }, `${ondalik(x.lift, 1)} × · ${sayi(x.birlikte)} kez`),
          h("td", {}, x.sistem ? rozet("Sistem kuralı", "info") : x.uyumlu ? rozet("İstatistik doğruluyor", "ok") : rozet("İstatistik zayıf", "warn"))))))),
        h("p", { class: "sessiz", style: { fontSize: "12.5px", marginBottom: 0 } }, "Her ilişki iki yoldan denetlenir: modelin dikkati ve düz sayım (lift: 'önce' olayından sonra 'sonra' olayının görülme olasılığı, genel olasılığının kaç katı). İkisi uyuşmuyorsa ilişki öneriye dönüşmez. İlişki neden-sonuç demek değildir; ortak bir nedeni gösterebilir.")))));
}

// ---------------------------------------------------------------- Veri
function asistanVeri(v) {
  const x = v.veri, en = Math.max(1, ...x.turler.map(t => t.sayi)), gunluk = x.gunluk || [];
  return h("div", {},
    h("div", { class: "izgara k2" },
      kart("Toplanan olaylar", h("div", {},
        h("dl", { class: "bilgi-izgara", style: { marginTop: 0 } },
          h("dt", {}, "Olay"), h("dd", {}, `${sayi(x.olay_sayisi)} (${x.gun_sayisi ? `${ondalik(x.gun_sayisi, 1)} gün` : "—"})`),
          h("dt", {}, "Aralık"), h("dd", {}, x.ilk_zaman ? `${tarihSaat(x.ilk_zaman)} → ${tarihSaat(x.son_zaman)}` : "—"),
          h("dt", {}, "Depolama"), h("dd", {}, `veri\\asistan.db · ${ondalik(x.boyut_mb, 1)} MB · model sürümleri ${ondalik(x.model_mb, 1)} MB`),
          h("dt", {}, "Saklama"), h("dd", {}, `son ${x.saklama_gun} gün (eskisi özetlenip silinir)`)),
        h("div", { class: "cubuk-liste" }, ...x.turler.map(t => h("div", { class: "cubuk-satir" }, h("span", { class: "ad" }, t.ad),
          h("span", { class: "cubuk" }, h("i", { style: { width: `${(t.sayi / en) * 100}%` } })), h("span", { class: "sayi" }, sayi(t.sayi))))))),
      kart("Ne toplanır, ne toplanmaz?", h("ul", { class: "sonuc-listesi", style: { margin: 0 } },
        h("li", {}, h("b", {}, "Toplanır: "), "olay türü (dosya geldi, iletildi, lokale yazıldı, eşleşmedi, askıda, alarm açıldı/kapandı, kaynak eşiği…), ilgili dizin ve hedefin kimliği, zaman, seviye."),
        h("li", {}, h("b", {}, "Toplanmaz: "), "dosya içerikleri hiçbir zaman okunmaz; dosya adları modele verilmez (yalnızca 'Kural önerisi' eşleşmeyen adları kurala dayalı inceler), şifre ve adresler alınmaz."),
        h("li", {}, h("b", {}, "Nerede: "), "yalnızca bu sunucuda (veri\\asistan.db). Dış servise, internete hiçbir şey gönderilmez; model de burada eğitilir."),
        h("li", {}, h("b", {}, "Etkisi: "), "asistan ayrı ve düşük öncelikli bir süreçtir; durursa ya da çökerse izleme ve teslim etkilenmez (Sistem izleme sayfasında belleği ve işlemcisi görünür)."),
        h("li", {}, h("b", {}, "Veriyi sil: "), "toplanan olaylar ve model sürümleri silinir, toplama baştan başlar."),
        h("div", { style: { marginTop: "10px" } }, dugme("Toplanan veriyi sil…", { kucuk: true, sinif: "tehlike-cizgi", rol: "YONETICI",
          onclick: () => onayla("Asistan verisini sil", "Toplanan olaylar ve bütün model sürümleri silinecek. FileWatcherPro'nun kendi kayıtları etkilenmez.", () => API.post("/api/asistan/veri_sil"), "bad") }))))),
    h("div", { class: "bolum" }, kart("Günlük olay sayısı", gunluk.length < 2 ? bosDurum("liste", "Günlük grafik için en az iki günlük veri gerekir.")
      : egriGrafik({ x: gunluk.map(g => g.gun), ust: Math.max(10, Math.ceil(Math.max(...gunluk.map(g => g.sayi)) / 10) * 10), yukseklik: 170, genislik: 900, xAd: "gün", ondalikY: 0,
        seriler: [{ ad: "Olay / gün", sinif: "egitim", degerler: gunluk.map(g => g.sayi) }] }))));
}

// ---------------------------------------------------------------- Kendini sına
function kendiniSinaPenceresi() {
  const sonuc = h("div", {});
  const ciz = r => {
    const e = r.egri;
    if (!e) return sonuc.replaceChildren(h("div", { class: "karar bad" }, h("b", {}, r.baslik)));
    sonuc.replaceChildren(
      h("div", { class: `karar ${r.sonuc === "GECTI" ? "ok" : "bad"}` }, h("div", { class: "satir" }, rozet(r.sonuc === "GECTI" ? "Geçti" : "Kaldı", r.sonuc === "GECTI" ? "ok" : "bad"), h("b", {}, r.baslik)),
        h("ul", {}, ...r.maddeler.map(m => h("li", {}, m)))),
      egriGrafik({ x: e.adimlar, ust: Math.ceil(Math.max(...e.egitim, ...e.dogrulama, e.markov) * 2) / 2, yukseklik: 190, genislik: 560, ondalikY: 2,
        seriler: [{ ad: "Eğitim", sinif: "egitim", degerler: e.egitim }, { ad: "Doğrulama", sinif: "dogrulama", degerler: e.dogrulama }, { ad: "Markov tabanı", sinif: "taban", degerler: e.adimlar.map(() => e.markov) }] }));
  };
  pencere({ baslik: "Kendini sına", ikon: "sihir", tur: "acc", genis: true, icerik: h("div", {},
    h("p", { style: { marginTop: 0 } }, "Asistan, içine bilinen ilişkiler gömülmüş yapay bir olay akışı üretir ve ayrı bir modeli yalnızca bu veriyle sıfırdan eğitir:"),
    h("ul", { class: "sonuc-listesi" },
      h("li", {}, "'Lojistik dizini yanıt vermiyor' olayından 1–3 dk sonra %80 olasılıkla 'Control-M devre kesildi'; arada sıradan trafik olur, bu yüzden yalnız bir önceki olaya bakan Markov tabanı ilişkiyi göremez"),
      h("li", {}, "'Muhasebe' dizinine iş günleri 09:00 ± 15 dk'da dosya"),
      h("li", {}, "geri kalanı rastgele gürültü")),
    h("p", { class: "ikincil" }, "Geçmek için: doğrulama kaybı Markov tabanından en az %5 düşük olmalı ve dikkat haritası gömülen ilişkiyi bulmalı (ezber başlarsa en iyi adıma dönülür ve raporlanır). Gerçek veriye ve kullanılan modele dokunulmaz; ~1 dk sürer (düşük öncelikli)."),
    sonuc),
    dugmeler: [{ metin: "Kapat", sinif: "hayalet" }, { metin: "Sınamayı başlat", sinif: "ana", eylem: async () => {
      const bas = Date.now() / 1000, yazi = h("div", { class: "sessiz" }, "Yapay veri üretiliyor, model eğitiliyor…");
      sonuc.replaceChildren(yazi, h("div", { class: "ilerleme belirsiz", style: { marginTop: "8px" } }, h("i", { style: { width: "35%" } })));
      const r = await API.post("/api/asistan/kendini_sina");
      if (r && r.sonuc) { ciz(r); return false; }                        // prototip: sonuç hemen döner
      for (let i = 0; i < 150; i++) {                                    // gerçek: asistan eklentisi arka planda sınar (~1 dk)
        await new Promise(z => setTimeout(z, 2000));
        const ks = (await API.get("/api/asistan")).kendini_sina || {};
        if (ks.son && ks.son.zaman >= bas && !ks.suruyor) { ciz(ks.son); return false; }
        yazi.textContent = `Yapay veri üretiliyor, model eğitiliyor… (${Math.round(Date.now() / 1000 - bas)} sn)`;
      }
      throw new ApiHata(0, "Sınama 5 dakikada bitmedi; Eklentiler sayfasında asistanın durumuna bakın.");
    } }] });
}
