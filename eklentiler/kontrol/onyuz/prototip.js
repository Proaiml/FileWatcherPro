/* PROTOTİP: yalnızca tasarım onayı için. Gerçek sisteme bağlanmaz; örnek veri üreten sahte arka uçtur.
   Dosyadan açıldığında ya da ?prototip ile yüklenir. Alt şeritteki düğmelerle kriz senaryoları canlandırılır. */
"use strict";
(function () {
  let kaydir = 0;                                   // ön-çalıştırma için sanal saat kayması
  const simdi = () => Date.now() / 1000 + kaydir;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const sec = l => l[Math.floor(Math.random() * l.length)];
  let sira = 1000;
  const yeniId = () => ++sira;
  const g = (s) => simdi() - s;

  const P = {
    ben: { kullanici: "deniz", rol: "YONETICI" },
    motor: true, cokuk: false, dizinDustu: false, eklentiCokuk: false,
    sayac: { iletildi: 1284, eritildi: 0, hazir: 1291, eslesmedi: 3, lokale: 0, sla_ihlali: 2 },
    hedefler: [
      { id: 1, ad: "Control-M Prod", tur: "CONTROLM", adres: "https://ctm-prod.sirket.local:8443/automation-api",
        ayrintilar: { ctm: "ctmprod", kimlik_turu: "token", kullanici: "fwp_api", sifre_ref: "dpapi:(şifreli)", sifre_kayitli: true, sifre_kaynagi: "uygulamada şifreli (bu sunucu)" },
        aktif: 1, kapatma_modu: "KAYITLI", kapatma_zamani: null, kapatan: null, devre_durumu: "NORMAL", ardisik_hata: 0,
        erit_durumu: "YOK", erit_hizi: null, saglik: null, saglik_zamani: null },
      { id: 2, ad: "Raporlama API", tur: "HTTP", adres: "https://rapor.sirket.local/api/fwp",
        ayrintilar: { kimlik_turu: "bearer", anahtar_basligi: "Authorization", anahtar_on_eki: "Bearer ", anahtar_ref: "dpapi:(şifreli)", anahtar_kayitli: true,
          anahtar_kaynagi: "uygulamada şifreli (bu sunucu)", basliklar: { "X-Kaynak": "FileWatcherPro" }, tls_dogrula: true }, aktif: 1, kapatma_modu: "KAYITLI", kapatma_zamani: null, kapatan: null,
        devre_durumu: "NORMAL", ardisik_hata: 0, erit_durumu: "YOK", erit_hizi: null, saglik: null, saglik_zamani: null },
      { id: 3, ad: "Fatura aktarım betiği", tur: "BETIK", adres: "",
        ayrintilar: { dil: "python", kod: BETIK_ORNEKLERI[0].kod, zaman_asimi_sn: 30, eszamanli: 2, surum: "a41e9c2", degistiren: "deniz", degisme_zamani: Date.now() / 1000 - 7300,
          sirlar: [{ ad: "API_ANAHTARI", kayitli: true, kaynak: "uygulamada şifreli (bu sunucu)" }], son_calisma: { cikis: 0, sure_ms: 1240, zaman: Date.now() / 1000 - 190 } },
        aktif: 1, kapatma_modu: "KAYITLI", kapatma_zamani: null, kapatan: null, devre_durumu: "NORMAL", ardisik_hata: 0,
        erit_durumu: "YOK", erit_hizi: null, saglik: null, saglik_zamani: null },
    ],
    betik: { sifre_tanimli: new URLSearchParams(location.search).get("betik") !== "yok", bitis: 0, hatali: 0 },
    dizinler: [
      { id: 1, yol: "\\\\ORNEK-SUNUCU\\gelen\\muhasebe", ad: "Muhasebe", uzantilar: ".csv,.txt", ilk_kurulum_modu: "TEMEL_AL", aktif: 1, erisim_durumu: "ERISILEBILIR", son_hata: null, ardisik: 0 },
      { id: 2, yol: "\\\\ORNEK-SUNUCU\\gelen\\lojistik", ad: "Lojistik", uzantilar: ".csv", ilk_kurulum_modu: "TEMEL_AL", aktif: 1, erisim_durumu: "ERISILEBILIR", son_hata: null, ardisik: 0 },
      { id: 3, yol: "\\\\ORNEK-SUNUCU-2\\gelen\\ik", ad: "İK", uzantilar: ".xlsx,.csv", ilk_kurulum_modu: "TETIKLE", aktif: 1, erisim_durumu: "ERISILEBILIR", son_hata: null, ardisik: 0 },
    ],
    kurallar: [
      { id: 1, dizin_id: 1, ad: "fatura", regex: "FATURA_(?P<tarih>\\d{8})\\.csv", harf_duyarsiz: 1, sira: 10, hedef_id: 1, is_bilgisi: { folder: "MUHASEBE", jobs: "FATURA_YUKLE" }, aktif: 1, kapatma_modu: "KAYITLI" },
      { id: 2, dizin_id: 1, ad: "iade", regex: "IADE_(?P<no>\\d+)\\.txt", harf_duyarsiz: 1, sira: 20, hedef_id: 1, is_bilgisi: { folder: "MUHASEBE", jobs: "IADE_ISLE" }, aktif: 1, kapatma_modu: "KAYITLI" },
      { id: 3, dizin_id: 2, ad: "sevkiyat", regex: "SEVK_(?P<depo>[A-Z]{3})_(?P<tarih>\\d{8})\\.csv", harf_duyarsiz: 1, sira: 10, hedef_id: 1, is_bilgisi: { folder: "LOJISTIK", jobs: "SEVK_AKTAR" }, aktif: 1, kapatma_modu: "KAYITLI" },
      { id: 4, dizin_id: 3, ad: "bordro", regex: "BORDRO_(?P<donem>\\d{6})\\.xlsx", harf_duyarsiz: 1, sira: 10, hedef_id: 2, is_bilgisi: { folder: "IK", jobs: "BORDRO_RAPOR" }, aktif: 1, kapatma_modu: "KAYITLI" },
    ],
    dosyalar: [], yuklemeler: [], tetikler: [], gon: [], denetim: [], alarmlar: [],
    eklentiler: [
      { ad: "cekirdek", modul: "cekirdek.gozetmen", durum: "CALISIYOR", pid: 4120, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: {} },
      { ad: "tarama", modul: "eklentiler.tarama.tarayici", durum: "CALISIYOR", pid: 4388, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: { dizinler: [1, 2, 3] } },
      { ad: "teslim", modul: "eklentiler.teslim.dagitici", durum: "CALISIYOR", pid: 4392, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: { sayac: { iletildi: 1284, hata: 0 } } },
      { ad: "kontrol", modul: "eklentiler.kontrol.kontrol_api", durum: "CALISIYOR", pid: 4401, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: { adres: "127.0.0.1", port: 8770, oturum: 1 } },
    ],
    bakim: { son: { basladi: g(3 * 86400 + 3600 * 14), kullanici: "zamanlayıcı", durum: "TAMAM", sure_ms: 184, budama_canli: { dosya: 40, tetik: 118, alarm: 3, komut: 9 },
      budama_hata: { gonderilemeyen: 0, denetim: 0, kesinti: 0 }, canli: { boyut_mb: 1.8, once_mb: 2.4 }, hata: { boyut_mb: 0.9, once_mb: 0.9 } }, suruyor: null, gecmis: [] },
    bekleyenDizin: [],
  };
  const hedef = id => P.hedefler.find(x => x.id === id);
  const kural = id => P.kurallar.find(x => x.id === id);
  const dizin = id => P.dizinler.find(x => x.id === id);
  const denetim = (islem, nesne, yeni, eski) => P.denetim.unshift({ id: yeniId(), zaman: simdi(), kullanici: P.ben.kullanici, kaynak: "kontrol", islem, nesne, eski: eski ? JSON.stringify(eski) : null, yeni: yeni ? JSON.stringify(yeni) : null });
  const alarmAc = (anahtar, mesaj, seviye = "UYARI", kaynak = "teslim") => {
    const a = P.alarmlar.find(x => x.anahtar === anahtar && x.aktif);
    if (a) { a.son_zaman = simdi(); a.mesaj = mesaj; return; }
    P.alarmlar.unshift({ id: yeniId(), anahtar, seviye, kaynak, mesaj, ilk_zaman: simdi(), son_zaman: simdi(), tekrar: 1, aktif: 1, kapanma_zamani: null, onaylayan: null });
  };
  const alarmKapat = (anahtar, onaylayan) => P.alarmlar.filter(x => x.anahtar === anahtar && x.aktif).forEach(x => { x.aktif = 0; x.kapanma_zamani = simdi(); x.onaylayan = onaylayan || null; });

  // ---------------------------------------------------------------- başlangıç verisi
  const ADLAR = {
    1: () => Math.random() < 0.8 ? `FATURA_202609${String(Math.floor(rnd(10, 30))).padStart(2, "0")}.csv` : `IADE_${Math.floor(rnd(1000, 9999))}.txt`,
    2: () => `SEVK_${sec(["IST", "ANK", "IZM", "BRS"])}_202609${String(Math.floor(rnd(10, 30))).padStart(2, "0")}.csv`,
    3: () => `BORDRO_2026${String(Math.floor(rnd(1, 10))).padStart(2, "0")}.xlsx`,
  };
  function eslestir(dizin_id, ad) {
    for (const k of P.kurallar.filter(k => k.dizin_id === dizin_id).sort((a, b) => a.sira - b.sira)) {
      const m = jsRegex(k.regex, k.harf_duyarsiz).exec(ad);
      if (m) return { k, gruplar: { ...(m.groups || {}) } };
    }
    return null;
  }
  function jsRegex(desen, hd) { return new RegExp(`^(?:${desen.replace(/\(\?P</g, "(?<")})$`, hd ? "i" : ""); }
  function hazirEt(y, zaman) {
    const e = eslestir(y.dizin_id, y.dosya_adi);
    const d = { id: yeniId(), dizin_id: y.dizin_id, dosya_adi: y.dosya_adi, tam_yol: y.tam_yol, boyut: y.boyut, icerik_hash: Math.random().toString(16).slice(2).padEnd(32, "a"),
      hash_suresi_ms: Math.floor(y.boyut / 400000) + 2, durum: e ? "HAZIR" : "ESLESMEDI", ilk_gorulme: y.ilk_gorulme, hazir_zamani: zaman, kalkma_zamani: null };
    P.dosyalar.unshift(d);
    if (!e) {
      P.sayac.eslesmedi++;
      P.gon.unshift({ id: yeniId(), anahtar: d.icerik_hash, sebep: "ESLESMEDI", dosya_adi: d.dosya_adi, tam_yol: d.tam_yol, hedef_ad: null, sebep_detay: "uzantı uydu ama hiçbir kuralın regex'i uymadı",
        ilk_zaman: zaman, son_zaman: zaman, deneme_sayisi: 0, cozuldu: 0, cozum: null, lokal_dosya: null });
      return;
    }
    P.sayac.hazir++;
    P.tetikler.unshift({ id: yeniId(), dosya_id: d.id, kural_id: e.k.id, hedef_id: e.k.hedef_id, idempotency: Math.random().toString(16).slice(2, 18) + Math.random().toString(16).slice(2, 18),
      dosya_adi: d.dosya_adi, tam_yol: d.tam_yol, durum: "BEKLIYOR", olusturma: zaman, deneme_sayisi: 0, sonraki: zaman + rnd(0.1, 0.5), deneme_gecmisi: "[]", belirsiz: 0, sure_ms: null, sla_ihlali: 0, sebep: null, lokal_dosya: null });
  }
  // son bir saatin geçmişi
  for (let i = 0; i < 40; i++) {
    const dz = sec([1, 1, 1, 2, 2, 3]); const ad = ADLAR[dz](); const t = g(rnd(60, 3600));
    const y = { dizin_id: dz, dosya_adi: ad, tam_yol: `${dizin(dz).yol}\\${ad}`, boyut: Math.floor(rnd(8e4, 3e6)), ilk_gorulme: t - rnd(3, 20) };
    hazirEt(y, t);
    const tt = P.tetikler[0];
    if (tt && tt.durum === "BEKLIYOR") { const ms = Math.floor(rnd(180, 2400)); tt.durum = "ILETILDI"; tt.sure_ms = ms; tt.deneme_sayisi = 1; tt.iletildi_zamani = t + ms / 1000;
      tt.deneme_gecmisi = JSON.stringify([{ z: t + ms / 1000, tur: "BASARI", kod: 200, mesaj: `runId=${Math.random().toString(16).slice(2, 10)}`, ms: ms - 50, erit: false }]); }
  }
  P.dosyalar.sort((a, b) => b.hazir_zamani - a.hazir_zamani); P.tetikler.sort((a, b) => b.olusturma - a.olusturma);
  P.yuklemeler.push({ dizin_id: 2, ad_anahtar: "sevk_ist_20260929.csv", dosya_adi: "SEVK_IST_20260929.csv", tam_yol: "\\\\ORNEK-SUNUCU\\gelen\\lojistik\\SEVK_IST_20260929.csv",
    durum: "ASKIDA", boyut: 312_400_000, ilk_gorulme: g(34 * 60), son_buyume: g(19 * 60), aciklama: "yazan süreç dosyayı hâlâ açık tutuyor", sabit: true });
  alarmAc("askida:2:sevk_ist_20260929.csv", "SEVK_IST_20260929.csv 34,0 dakikadır tamamlanmadı (\\\\ORNEK-SUNUCU\\gelen\\lojistik). Yükleme yavaş, takılmış ya da yarıda kalmış olabilir; tamamlanana kadar tetiklenmeyecek.", "UYARI", "tarama");
  denetim("GIRIS", "deniz", { rol: "YONETICI" });
  [["KURAL_EKLE", "sevkiyat"], ["DIZIN_EKLE", "\\\\ORNEK-SUNUCU-2\\gelen\\ik"], ["AYAR_DEGISTIR", "sla_hedef_sn"]].forEach(([i, n], k) => P.denetim.push({ id: yeniId(), zaman: g(86400 * (k + 1)), kullanici: "deniz", kaynak: "kontrol", islem: i, nesne: n, eski: null, yeni: null }));

  // ---------------------------------------------------------------- simülasyon adımı (her saniye)
  function adim() {
    const t = simdi();
    for (const e of P.eklentiler) { if (e.durum === "CALISIYOR") { e.son_nabiz = t; e.son_ilerleme = t; } }
    const tarama = P.eklentiler.find(e => e.ad === "tarama");
    const taramaCalisiyor = tarama.durum === "CALISIYOR" && P.motor;
    // yeni dosya gelişi
    if (Math.random() < 0.55) {
      const dz = sec([1, 1, 1, 2, 2, 3]); const ad = Math.random() < 0.04 ? `rapor_${Math.floor(rnd(1, 99))}.csv` : ADLAR[dz]();
      const y = { dizin_id: dz, ad_anahtar: ad.toLowerCase(), dosya_adi: ad, tam_yol: `${dizin(dz).yol}\\${ad}`, durum: "YAZILIYOR", boyut: 0, hedef_boyut: Math.floor(rnd(5e4, 4e6)),
        ilk_gorulme: t, son_buyume: t, aciklama: "", kalan: Math.floor(rnd(2, 5)) };
      if (dz === 2 && P.dizinDustu) P.bekleyenDizin.push(y); else if (taramaCalisiyor) P.yuklemeler.push(y); else P.bekleyenDizin.push(y);
    }
    // yüklemelerin ilerlemesi
    if (taramaCalisiyor) {
      for (const y of [...P.yuklemeler]) {
        if (y.sabit) continue;
        if (y.dizin_id === 2 && P.dizinDustu) continue;
        y.kalan--;
        if (y.kalan > 1) { y.boyut = Math.min(y.hedef_boyut, y.boyut + y.hedef_boyut / 3); y.son_buyume = t; y.durum = "YAZILIYOR"; }
        else if (y.kalan === 1) { y.boyut = y.hedef_boyut; y.durum = "KILITLI"; y.aciklama = "yazan süreç dosyayı hâlâ açık tutuyor"; }
        else { P.yuklemeler.splice(P.yuklemeler.indexOf(y), 1); hazirEt(y, t); }
      }
    }
    // teslim
    const teslim = P.eklentiler.find(e => e.ad === "teslim");
    if (teslim.durum === "CALISIYOR") {
      for (const tt of P.tetikler.filter(x => ["BEKLIYOR", "TEKRAR"].includes(x.durum) && x.sonraki <= t)) {
        const hd = hedef(tt.hedef_id); const kr = kural(tt.kural_id);
        if (!hd.aktif || (kr && !kr.aktif)) {
          const kayitsiz = (!hd.aktif ? hd.kapatma_modu : kr.kapatma_modu) === "KAYITSIZ";
          if (kayitsiz) { tt.durum = "KAYITSIZ_KAPALI"; tt.sebep = "HEDEF_KAPALI_KAYITSIZ"; P.gon.unshift(gonKaydi(tt, "HEDEF_KAPALI_KAYITSIZ", "kayıtsız kapalıydı", 1, "KAYITSIZ_KAPATMA")); }
          else lokale(tt, !hd.aktif ? "HEDEF_KAPALI_KAYITLI" : "KURAL_KAPALI_KAYITLI", "kapalıyken geldi; erit bekliyor");
          continue;
        }
        if (hd.devre_durumu === "KESILDI") { lokale(tt, "DEVRE_KESIK", "devre kesik; denenmeden lokale yazıldı"); continue; }
        const gecmis = JSON.parse(tt.deneme_gecmisi);
        if (P.cokuk && hd.id === 1) {
          gecmis.push({ z: t, tur: "GECICI", kod: 503, mesaj: "HTTP 503: Service Unavailable: Control-M/Server is not available", ms: 120, erit: false });
          tt.deneme_sayisi++; tt.deneme_gecmisi = JSON.stringify(gecmis); hd.ardisik_hata++;
          if (hd.ardisik_hata >= 5 && hd.devre_durumu === "NORMAL") { hd.devre_durumu = "KESILDI"; alarmAc(`hedef:${hd.id}:devre`, `'${hd.ad}' art arda ${hd.ardisik_hata} kez yanıt vermedi; devre kesildi. Yeni tetikler denenmeden lokale yazılıyor. Hedef yanıt vermeye başlayınca 'Devreyi normale al' ve 'Kademeli erit' kullanın.`, "KRITIK"); P.denetim.unshift({ id: yeniId(), zaman: t, kullanici: "sistem", kaynak: "teslim", islem: "DEVRE_KESILDI", nesne: hd.ad, eski: null, yeni: null }); }
          if (tt.deneme_sayisi <= 3 && hd.devre_durumu === "NORMAL") { tt.durum = "TEKRAR"; tt.sonraki = t + [2, 3, 4][tt.deneme_sayisi - 1]; }
          else lokale(tt, hd.devre_durumu === "KESILDI" ? "DEVRE_KESIK" : "SLA_SON_DOLDU", `${tt.deneme_sayisi} deneme başarısız; son hata: HTTP 503`);
          continue;
        }
        iletildi(tt, gecmis, false);
        hd.ardisik_hata = 0;
      }
    }
    // erit
    for (const hd of P.hedefler) {
      if (hd.erit_durumu !== "CALISIYOR" || teslim.durum !== "CALISIYOR") continue;
      if (P.cokuk && hd.id === 1) { hd.erit_durumu = "DURAKLATILDI"; alarmAc(`hedef:${hd.id}:erit`, `'${hd.ad}' için kademeli erit durdu: erit sırasında hata: HTTP 503. Kalan kayıtlar lokalde güvende; hedef düzelince eriti yeniden başlatın.`); continue; }
      const lokal = P.tetikler.filter(x => x.hedef_id === hd.id && x.durum === "LOKALDE").sort((a, b) => a.olusturma - b.olusturma);
      if (!lokal.length) { hd.erit_durumu = "YOK"; alarmKapat(`hedef:${hd.id}:erit`); alarmKapat(`hedef:${hd.id}:lokalde`); continue; }
      for (const tt of lokal.slice(0, Math.max(1, Math.round(hd.erit_hizi || 5)))) iletildi(tt, JSON.parse(tt.deneme_gecmisi), true);
    }
    // lokalde bekleyen alarmı
    for (const hd of P.hedefler) {
      const n = P.tetikler.filter(x => x.hedef_id === hd.id && x.durum === "LOKALDE").length;
      if (n && hd.erit_durumu !== "CALISIYOR") alarmAc(`hedef:${hd.id}:lokalde`, `'${hd.ad}' için ${n} tetik lokalde bekliyor. Hedef erişilebilir olduğunda 'Kademeli erit' ile gönderin.`);
      if (!n) alarmKapat(`hedef:${hd.id}:lokalde`);
      if (hd.devre_durumu === "KESILDI" || !hd.aktif) { hd.saglik = (P.cokuk && hd.id === 1) ? "YANITSIZ: bağlantı kurulamadı: [WinError 10061] hedef makine reddetti" : "YANIT_VERIYOR: oturum açılabiliyor"; hd.saglik_zamani = t - rnd(1, 20); }
    }
    // dizin kesintisi
    const lj = dizin(2);
    if (P.dizinDustu) {
      lj.ardisik++; lj.erisim_durumu = lj.ardisik <= 3 ? "DENENIYOR" : "ERISILEMEZ";
      lj.son_hata = "FileNotFoundError: [WinError 53] Ağ yolu bulunamadı: '\\\\ORNEK-SUNUCU\\gelen\\lojistik'";
      if (lj.erisim_durumu === "ERISILEMEZ") alarmAc("dizin:2:erisilemez", `Dizine erişilemiyor: ${lj.yol} (${lj.son_hata}). Durum korunuyor; bu sürede gelen dosyalar dizin geri gelince yakalanacak.`, "KRITIK", "tarama");
    } else if (lj.erisim_durumu !== "ERISILEBILIR") { lj.erisim_durumu = "ERISILEBILIR"; lj.ardisik = 0; lj.son_hata = null; alarmKapat("dizin:2:erisilemez"); }
    if (!P.dizinDustu && taramaCalisiyor && P.bekleyenDizin.length) { P.yuklemeler.push(...P.bekleyenDizin); P.bekleyenDizin = []; }
    // eklenti çökmesi
    if (P.eklentiCokuk && tarama.durum !== "ELLE_MUDAHALE") {
      tarama.ardisik_dusme++; tarama.yeniden_baslatma++; tarama.son_hata = "RuntimeError: prototip: bilerek çöktü";
      tarama.durum = tarama.ardisik_dusme >= 5 ? "ELLE_MUDAHALE" : "DUSTU"; tarama.pid = null;
      if (tarama.durum === "ELLE_MUDAHALE") { alarmKapat("eklenti:tarama:dustu"); alarmAc("eklenti:tarama:elle", "'tarama' eklentisi art arda 5 kez düştü; otomatik yeniden başlatma durduruldu. Son neden: RuntimeError. Önyüzden 'Başlat' ile yeniden deneyin.", "KRITIK", "gozetmen"); }
      else alarmAc("eklenti:tarama:dustu", `'tarama' eklentisi düştü; otomatik yeniden başlatılıyor (${tarama.ardisik_dusme}/5).`, "UYARI", "gozetmen");
    }
    for (const d of P.dizinler) { if (d.erisim_durumu === "ERISILEBILIR" && taramaCalisiyor) { d.son_tarama = t - rnd(0, 1.5); d.son_tarama_ms = Math.floor(rnd(8, 60)); } }
    // budama (son 200)
    if (P.dosyalar.length > 200) P.dosyalar.length = 200;
    const bitmis = P.tetikler.filter(x => ["ILETILDI", "KAYITSIZ_KAPALI"].includes(x.durum));
    if (bitmis.length > 200) { const sil = new Set(bitmis.slice(200).map(x => x.id)); P.tetikler = P.tetikler.filter(x => !sil.has(x.id)); }
  }
  function iletildi(tt, gecmis, erit) {
    const t = simdi(); const ms = Math.floor(rnd(150, 1900));
    gecmis.push({ z: t, tur: "BASARI", kod: 200, mesaj: `runId=${Math.random().toString(16).slice(2, 10)}`, ms, erit });
    tt.durum = "ILETILDI"; tt.eritildi = erit ? 1 : 0; tt.deneme_sayisi++; tt.deneme_gecmisi = JSON.stringify(gecmis); tt.iletildi_zamani = t;
    tt.sure_ms = Math.floor((t - tt.olusturma) * 1000); tt.sla_ihlali = tt.sure_ms > 10000 && !erit ? 1 : 0;
    P.sayac.iletildi++; if (erit) P.sayac.eritildi++; if (tt.sla_ihlali) P.sayac.sla_ihlali++;
    if (tt.lokal_dosya) { const gk = P.gon.find(x => x.anahtar === tt.idempotency && !x.cozuldu); if (gk) { gk.cozuldu = 1; gk.cozum = erit ? "ERIT" : "TEKRAR"; gk.cozulme_zamani = t; } tt.lokal_dosya = null; }
  }
  function gonKaydi(tt, sebep, detay, cozuldu = 0, cozum = null) {
    return { id: yeniId(), anahtar: tt.idempotency, sebep, dosya_adi: tt.dosya_adi, tam_yol: tt.tam_yol, hedef_ad: hedef(tt.hedef_id).ad, sebep_detay: detay,
      ilk_zaman: simdi(), son_zaman: simdi(), deneme_sayisi: tt.deneme_sayisi, cozuldu, cozum, lokal_dosya: tt.lokal_dosya };
  }
  function lokale(tt, sebep, detay) {
    tt.durum = "LOKALDE"; tt.sebep = sebep; tt.son_hata = detay; P.sayac.lokale++;
    const hd = hedef(tt.hedef_id);
    tt.lokal_dosya = `C:\\FileWatcherPro\\veri\\lokal_kayit\\${hd.ad.replace(/\W+/g, "_")}\\20260929\\${Math.floor(tt.olusturma * 1000)}_${tt.idempotency.slice(0, 16)}.json`;
    P.gon.unshift(gonKaydi(tt, sebep, detay));
  }

  // ---------------------------------------------------------------- durum özeti (gerçek /api/durum biçimi)
  function durum() {
    const t = simdi();
    const hedefler = P.hedefler.map(hd => {
      const tet = P.tetikler.filter(x => x.hedef_id === hd.id);
      const say = d => tet.filter(x => x.durum === d).length;
      return { ...hd, bekleyen: say("BEKLIYOR") + say("TEKRAR"), deneniyor: 0, tekrar: say("TEKRAR"), lokalde: say("LOKALDE"), eritiliyor: 0, yolda: say("BEKLIYOR") ? 1 : 0 };
    });
    const dizinler = P.dizinler.map(d => ({ ...d, aktif_dosya: P.dosyalar.filter(x => x.dizin_id === d.id && !x.kalkma_zamani).length,
      yukleniyor: P.yuklemeler.filter(y => y.dizin_id === d.id).length, askida: P.yuklemeler.filter(y => y.dizin_id === d.id && y.durum === "ASKIDA").length,
      kural_sayisi: P.kurallar.filter(k => k.dizin_id === d.id).length, kapali_kural: P.kurallar.filter(k => k.dizin_id === d.id && !k.aktif).length, dosya_sayisi: 0,
      kurallar: P.kurallar.filter(k => k.dizin_id === d.id).map(k => ({ id: k.id, ad: k.ad, aktif: k.aktif, kapatma_modu: k.kapatma_modu, hedef_ad: (hedef(k.hedef_id) || {}).ad })) }));
    const sureler = P.tetikler.filter(x => x.durum === "ILETILDI" && x.sure_ms !== null && !x.eritildi).slice(0, 200).map(x => x.sure_ms).sort((a, b) => a - b);
    const onc = { KRITIK: 0, UYARI: 1, BILGI: 2 };
    return {
      zaman: t, motor: P.motor, eklentiler: P.eklentiler.map(e => ({ ...e })), hedefler, dizinler,
      sayilar: { ...P.sayac, lokalde: hedefler.reduce((a, x) => a + x.lokalde, 0), bekleyen: hedefler.reduce((a, x) => a + x.bekleyen, 0),
        yukleniyor: P.yuklemeler.length, askida: P.yuklemeler.filter(y => y.durum === "ASKIDA").length, cozulmemis: P.gon.filter(x => !x.cozuldu).length },
      sla: { n: sureler.length, ort_ms: sureler.length ? Math.round(sureler.reduce((a, b) => a + b, 0) / sureler.length) : null,
        p95_ms: sureler.length ? sureler[Math.max(0, Math.floor(sureler.length * 0.95) - 1)] : null, azami_ms: sureler[sureler.length - 1] || null, ihlal: 0, hedef_sn: 10 },
      alarmlar: P.alarmlar.filter(a => a.aktif).sort((a, b) => onc[a.seviye] - onc[b.seviye] || b.son_zaman - a.son_zaman),
      bakim: { son: P.bakim.son, suruyor: P.bakim.suruyor || null, gun: "Cumartesi", saat: "03:00", gecmis_limit: 200, hata_limit: 1000, sonraki: (() => { const d = new Date(); d.setDate(d.getDate() + ((6 - d.getDay() + 7) % 7 || 7)); d.setHours(3, 0, 0, 0); return d.getTime() / 1000; })() },
    };
  }

  // ---------------------------------------------------------------- sahte uç noktalar
  const bekle = ms => new Promise(r => setTimeout(r, ms));
  class Hata extends Error { constructor(kod, m) { super(m); this.kod = kod; } }
  const yetki = rol => { const R = ["IZLEYICI", "OPERATOR", "YONETICI"]; if (R.indexOf(P.ben.rol) < R.indexOf(rol)) throw new Hata(403, `Bu işlem için '${rol}' yetkisi gerekiyor (sizin rolünüz: ${P.ben.rol}).`); };
  const kopya = v => JSON.parse(JSON.stringify(v));
  const ROTALAR = [
    ["GET", /^\/api\/ben$/, () => P.ben],
    ["GET", /^\/api\/oturum$/, () => ({ ...P.ben, oturum: true })],
    ["POST", /^\/api\/giris$/, g_ => { P.ben.kullanici = g_.kullanici || "deniz"; return P.ben; }],
    ["POST", /^\/api\/cikis$/, () => ({ tamam: true })],
    ["GET", /^\/api\/durum$/, durum],
    ["GET", /^\/api\/yuklemeler$/, () => P.yuklemeler.map(y => ({ ...y, dizin_yolu: dizin(y.dizin_id).yol }))],
    ["GET", /^\/api\/dosyalar/, (g_, q) => P.dosyalar.filter(d => !q.get("ara") || d.dosya_adi.toLowerCase().includes(q.get("ara").toLowerCase())).map(d => {
      const tt = P.tetikler.find(x => x.dosya_id === d.id); const k = tt && kural(tt.kural_id);
      return { ...d, tetik_id: tt && tt.id, tetik_durum: tt && tt.durum, sure_ms: tt && tt.sure_ms, sla_ihlali: tt && tt.sla_ihlali, deneme_sayisi: tt ? tt.deneme_sayisi : null,
        belirsiz: tt && tt.belirsiz, son_hata: tt && tt.son_hata, sebep: tt && tt.sebep, kural_ad: k && k.ad, hedef_ad: tt && hedef(tt.hedef_id).ad };
    })],
    ["GET", /^\/api\/tetikler/, (g_, q) => P.tetikler.filter(x => (!q.get("durum") || x.durum === q.get("durum")) && (!q.get("id") || x.id === +q.get("id"))).map(x => ({ ...x, hedef_ad: hedef(x.hedef_id).ad, kural_ad: (kural(x.kural_id) || {}).ad }))],
    ["GET", /^\/api\/gonderilemeyen/, (g_, q) => P.gon.filter(x => (q.get("cozuldu") === null || q.get("cozuldu") === "" || String(x.cozuldu) === q.get("cozuldu")) && (!q.get("sebep") || x.sebep === q.get("sebep")))],
    ["GET", /^\/api\/denetim/, () => P.denetim],
    ["GET", /^\/api\/alarmlar$/, () => P.alarmlar],
    ["GET", /^\/api\/dizinler$/, () => P.dizinler.map(d => ({ ...d, kurallar: P.kurallar.filter(k => k.dizin_id === d.id).map(k => ({ ...k, hedef_ad: hedef(k.hedef_id).ad })) }))],
    ["GET", /^\/api\/hedefler$/, () => P.hedefler],
    ["GET", /^\/api\/ayarlar$/, () => AYARLAR],
    ["POST", /^\/api\/regex\/dene$/, g_ => { let r; try { r = jsRegex(g_.regex, g_.harf_duyarsiz); } catch (e) { throw new Hata(400, `regex geçersiz: ${e.message}`); }
      return (g_.adlar || []).map(ad => { const m = r.exec(ad); return { ad, eslesti: !!m, gruplar: m && m.groups ? { ...m.groups } : {} }; }); }],
    ["POST", /^\/api\/alarmlar\/(\d+)\/onayla$/, (g_, q, id) => { yetki("OPERATOR"); const a = P.alarmlar.find(x => x.id === +id); a.aktif = 0; a.kapanma_zamani = simdi(); a.onaylayan = P.ben.kullanici; denetim("ALARM_ONAYLA", a.anahtar); }],
    ["POST", /^\/api\/hedefler\/(\d+)\/kapat$/, (g_, q, id) => { yetki("OPERATOR"); const hd = hedef(+id); hd.aktif = 0; hd.kapatma_modu = g_.mod; hd.kapatma_zamani = simdi(); hd.kapatan = P.ben.kullanici; denetim("HEDEF_KAPAT", hd.ad, { mod: g_.mod }); }],
    ["POST", /^\/api\/hedefler\/(\d+)\/ac$/, (g_, q, id) => { yetki("OPERATOR"); const hd = hedef(+id); hd.aktif = 1; hd.kapatma_zamani = null; hd.kapatan = null; hd.devre_durumu = "NORMAL"; hd.ardisik_hata = 0; hd.saglik = null; denetim("HEDEF_AC", hd.ad); }],
    ["POST", /^\/api\/toptan_kapat$/, g_ => { yetki("OPERATOR"); const ids = []; P.hedefler.filter(x => x.aktif).forEach(hd => { hd.aktif = 0; hd.kapatma_modu = g_.mod; hd.kapatma_zamani = simdi(); hd.kapatan = P.ben.kullanici; ids.push(hd.id); denetim("HEDEF_KAPAT", hd.ad, { mod: g_.mod }); }); denetim("TOPTAN_KAPAT", "hedefler", { mod: g_.mod }); return { kapatilan: ids }; }],
    ["POST", /^\/api\/toptan_ac$/, () => { yetki("OPERATOR"); const ids = []; P.hedefler.filter(x => !x.aktif).forEach(hd => { hd.aktif = 1; hd.kapatma_zamani = null; hd.kapatan = null; hd.devre_durumu = "NORMAL"; hd.ardisik_hata = 0; ids.push(hd.id); denetim("HEDEF_AC", hd.ad); }); return { acilan: ids }; }],
    ["POST", /^\/api\/hedefler\/(\d+)\/devre_sifirla$/, (g_, q, id) => { yetki("OPERATOR"); const hd = hedef(+id); hd.devre_durumu = "NORMAL"; hd.ardisik_hata = 0; alarmKapat(`hedef:${hd.id}:devre`, P.ben.kullanici); denetim("DEVRE_SIFIRLA", hd.ad); }],
    ["POST", /^\/api\/hedefler\/(\d+)\/erit$/, (g_, q, id) => { yetki("OPERATOR"); const hd = hedef(+id);
      if (g_.islem === "baslat") { if (!hd.aktif) throw new Hata(400, "hedef kapalıyken erit başlatılamaz; önce hedefi açın"); if (hd.devre_durumu !== "NORMAL") throw new Hata(400, "devre kesikken erit başlatılamaz; önce devreyi normale alın"); hd.erit_durumu = "CALISIYOR"; hd.erit_hizi = g_.hiz; alarmKapat(`hedef:${hd.id}:erit`); }
      else hd.erit_durumu = g_.islem === "duraklat" ? "DURAKLATILDI" : "YOK";
      denetim(`ERIT_${g_.islem.toUpperCase()}`, hd.ad, { hiz: g_.hiz }); }],
    ["POST", /^\/api\/kurallar\/(\d+)\/kapat$/, (g_, q, id) => { yetki("OPERATOR"); const k = kural(+id); k.aktif = 0; k.kapatma_modu = g_.mod; denetim("KURAL_KAPAT", k.ad, { mod: g_.mod }); }],
    ["POST", /^\/api\/kurallar\/(\d+)\/ac$/, (g_, q, id) => { yetki("OPERATOR"); const k = kural(+id); k.aktif = 1; denetim("KURAL_AC", k.ad); }],
    ["POST", /^\/api\/motor$/, g_ => { yetki("OPERATOR"); P.motor = !!g_.aktif; denetim(P.motor ? "MOTOR_BASLAT" : "MOTOR_DURDUR", "motor"); return { motor: P.motor }; }],
    ["POST", /^\/api\/dizinler\/(\d+)\/simdi_dene$/, (g_, q, id) => { yetki("OPERATOR"); denetim("SIMDI_DENE", dizin(+id).yol); }],
    ["POST", /^\/api\/eklentiler\/([a-z_]+)\/(baslat|durdur|yeniden_baslat)$/, (g_, q, ad, islem) => { yetki("OPERATOR");
      if (ad === "kontrol" && islem === "durdur") throw new Hata(400, "Kontrol eklentisi önyüzden durdurulamaz (önyüz de kapanırdı); yeniden başlatabilirsiniz.");
      const e = P.eklentiler.find(x => x.ad === ad);
      if (islem === "durdur") { e.durum = "DURDURULDU"; e.pid = null; } else { if (ad === "tarama") P.eklentiCokuk = false; e.durum = "CALISIYOR"; e.ardisik_dusme = 0; e.pid = Math.floor(rnd(4000, 9000)); e.son_hata = null; alarmKapat(`eklenti:${ad}:elle`); alarmKapat(`eklenti:${ad}:dustu`); if (islem === "yeniden_baslat") e.yeniden_baslatma++; }
      denetim(`EKLENTI_${islem.toUpperCase()}`, ad); return { komut_id: yeniId() }; }],
    ["POST", /^\/api\/bakim$/, () => { yetki("OPERATOR"); if (P.bakim.suruyor) throw new Hata(409, "bakım zaten sürüyor");
      P.bakim.suruyor = { basladi: simdi(), kullanici: P.ben.kullanici }; denetim("BAKIM_BASLAT", "veritabanlari");
      setTimeout(() => { const son = { basladi: P.bakim.suruyor.basladi, kullanici: P.bakim.suruyor.kullanici, durum: "TAMAM", sure_ms: 2480,
        budama_canli: { dosya: 12, tetik: 37, alarm: 2, komut: 5 }, budama_hata: { gonderilemeyen: 0, denetim: 0, kesinti: 1, cozulmemis: P.gon.filter(x => !x.cozuldu).length },
        canli: { boyut_mb: 1.7, once_mb: 2.1 }, hata: { boyut_mb: 0.9, once_mb: 0.9 } };
        P.bakim.son = son; P.bakim.suruyor = null; P.bakim.gecmis.unshift({ zaman: son.basladi, kullanici: son.kullanici, sonuc: son }); }, 2500);
      return { komut_id: yeniId() }; }],
    ["GET", /^\/api\/bakim\/gecmis$/, () => P.bakim.gecmis.slice(0, 10)],
    ["POST", /^\/api\/dizinler$/, g_ => { yetki("YONETICI"); if (!g_.ilk_kurulum_modu) throw new Hata(400, "ilk kurulum modu açıkça seçilmeli"); if (!/^(\\\\|[A-Za-z]:\\)/.test(g_.yol || "")) throw new Hata(400, "dizin yolu tam yol olmalı (C:\\... ya da \\\\sunucu\\paylaşım\\...)");
      const d = { id: yeniId(), yol: g_.yol, ad: g_.ad, uzantilar: g_.uzantilar, ilk_kurulum_modu: g_.ilk_kurulum_modu, aktif: 1, erisim_durumu: "BILINMIYOR", ardisik: 0 }; P.dizinler.push(d); denetim("DIZIN_EKLE", d.yol); ADLAR[d.id] = () => `DENEME_${Math.floor(rnd(1, 99))}.csv`; return { id: d.id }; }],
    ["PUT", /^\/api\/dizinler\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); Object.assign(dizin(+id), g_); denetim("DIZIN_GUNCELLE", dizin(+id).yol, g_); }],
    ["DELETE", /^\/api\/dizinler\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const d = dizin(+id); P.dizinler = P.dizinler.filter(x => x.id !== +id); P.kurallar = P.kurallar.filter(k => k.dizin_id !== +id); denetim("DIZIN_SIL", d.yol); }],
    ["POST", /^\/api\/kurallar$/, g_ => { yetki("YONETICI"); if ((hedef(+g_.hedef_id) || {}).tur === "BETIK") kilitGerek(); try { jsRegex(g_.regex || "", true); } catch (e) { throw new Hata(400, `regex geçersiz: ${e.message}`); }
      if (!g_.regex) throw new Hata(400, "regex boş olamaz"); if (/\([^)]*[+*]\)[+*]/.test(g_.regex)) throw new Hata(400, "regex çok yavaş: 3 sn içinde bitmedi (iç içe tekrar, örn. (a+)+). Deseni sadeleştirin.");
      const k = { id: yeniId(), dizin_id: g_.dizin_id, ad: g_.ad || g_.regex, regex: g_.regex, harf_duyarsiz: g_.harf_duyarsiz ? 1 : 0, sira: g_.sira, hedef_id: g_.hedef_id, is_bilgisi: g_.is_bilgisi, aktif: 1, kapatma_modu: "KAYITLI" };
      P.kurallar.push(k); denetim("KURAL_EKLE", k.ad, { regex: k.regex }); return { id: k.id }; }],
    ["DELETE", /^\/api\/kurallar\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const k = kural(+id); P.kurallar = P.kurallar.filter(x => x.id !== +id); denetim("KURAL_SIL", k.ad); }],
    ["POST", /^\/api\/hedefler$/, g_ => { yetki("YONETICI"); const ayr = hedefAyrintisi(g_, null);
      const hd = { id: yeniId(), ad: g_.ad, tur: g_.tur, adres: g_.tur === "BETIK" ? "" : g_.adres, ayrintilar: ayr, aktif: 1, kapatma_modu: "KAYITLI", devre_durumu: "NORMAL", ardisik_hata: 0, erit_durumu: "YOK" };
      P.hedefler.push(hd); denetim(g_.tur === "BETIK" ? "BETIK_EKLE" : "HEDEF_EKLE", hd.ad, g_.tur === "BETIK" ? { surum: ayr.surum } : null); return { id: hd.id }; }],
    ["PUT", /^\/api\/hedefler\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const hd = hedef(+id); if (!hd) throw new Hata(404, "hedef yok");
      if (g_.tur !== hd.tur) throw new Hata(400, "hedef türü değiştirilemez"); const eski = hd.ayrintilar.surum; const ayr = hedefAyrintisi(g_, hd);
      Object.assign(hd, { ad: g_.ad, adres: hd.tur === "BETIK" ? "" : g_.adres, ayrintilar: ayr });
      denetim(hd.tur === "BETIK" ? "BETIK_DEGISTI" : "HEDEF_GUNCELLE", hd.ad, hd.tur === "BETIK" ? { surum: ayr.surum } : null, hd.tur === "BETIK" ? { surum: eski } : null); }],
    ["PUT", /^\/api\/ayarlar$/, g_ => { yetki("YONETICI"); for (const [k, v] of Object.entries(g_)) { const a = AYARLAR.find(x => x.anahtar === k); if (a.alt !== null && v < a.alt) throw new Hata(400, `${k} en az ${a.alt} olmalı`); }
      for (const [k, v] of Object.entries(g_)) { const a = AYARLAR.find(x => x.anahtar === k); denetim("AYAR_DEGISTIR", k, { deger: v }, { deger: a.deger }); a.deger = v; if (k === "motor_aktif") P.motor = !!v; } return g_; }],
  ];
  const AYARLAR = [
    ["motor_aktif", true, "bool", "Motor", "Tarama motoru çalışsın mı (önyüzden durdur/başlat)."],
    ["tarama_araligi_sn", 2, "float", "Motor", "Dizin listeleme sıklığı.", 0.2, 600],
    ["dizin_tarama_zaman_asimi_sn", 20, "float", "Motor", "Tek dizin listelemesi bu süreyi aşarsa dizin YANITSIZ sayılır.", 1, 600],
    ["dizin_deneme_plani", "5,10,15", "plan", "Motor", "Dizine erişilemezse bekleme planı (sn); bitince ERİŞİLEMEZ + alarm."],
    ["dizin_seyrek_deneme_sn", 30, "float", "Motor", "ERİŞİLEMEZ dizin için seyrek deneme aralığı.", 1, 3600],
    ["sabitlik_W_sn", 10, "float", "Tamamlanma", "Boyut ve mtime bu süre değişmezse dosya tamamlanmış sayılabilir (paylaşım testiyle birlikte).", 0, 3600],
    ["aski_T_dk", 30, "float", "Tamamlanma", "Yazılmakta olan dosya bu süreyi aşarsa ASKIDA + önyüze bildirim.", 0.1, 1440],
    ["hash_esik_mb", 500, "float", "Tamamlanma", "Bu boyutun altındaki dosyaların içerik hash'i (xxh3) alınır; kimlik = dizin + ad + hash.", 0, 1000000],
    ["parca_dikkate_al", true, "bool", "Tamamlanma", ".filepart/.part gibi geçici adları 'yükleniyor' olarak izle (asla tetiklenmez)."],
    ["parca_uzantilari", ".filepart,.part", "uzantilar", "Tamamlanma", "Geçici yükleme uzantıları."],
    ["coklu_kural", "ilk", "str", "Kural", "Bir dosya birden çok kurala uyarsa: 'ilk' eşleşen ya da 'hepsi'.", null, null, ["ilk", "hepsi"]],
    ["sla_hedef_sn", 10, "float", "Teslim", "HAZIR → ilk başarılı API çağrısı hedef süresi; aşılırsa SLA ihlali kaydı.", 1, 3600],
    ["deneme_plani", "5,10,15", "plan", "Teslim", "API hatasında bekleme planı (sn); bitince lokal kayıt + alarm."],
    ["cagri_timeout_sn", 4, "float", "Teslim", "Tek API çağrısı için azami süre.", 0.5, 120],
    ["esz_cagri_ust", 4, "int", "Teslim", "Hedef başına aynı anda en fazla çağrı.", 1, 64],
    ["otomatik_devre_esigi", 5, "int", "Teslim", "Hedefte art arda bu kadar hata olursa devre kesilir; yeni tetikler denenmeden lokale yazılır (0 = kapalı).", 0, 1000],
    ["erit_hizi", 5, "float", "Teslim", "Kademeli eritmede saniyede en fazla çağrı.", 0.1, 100],
    ["kapali_hatirlatma_dk", 30, "float", "Teslim", "Hedef/kural bu süreden uzun kapalı kalırsa hatırlatma alarmı.", 1, 10080],
    ["gecmis_limit", 200, "int", "Depolama", "canli.db: dizinden kalkmış dosya ve bitmiş tetik geçmişi (aktif ve bekleyenler hariç).", 10, 100000],
    ["hata_limit", 1000, "int", "Depolama", "hata.db: gönderilemeyen kayıt sınırı (çözülmemişler asla silinmez).", 10, 1000000],
    ["bakim_gunu", "Cumartesi", "str", "Depolama", "Haftalık bakım günü.", null, null, ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]],
    ["bakim_saati", "03:00", "saat", "Depolama", "Haftalık bakım saati (SS:DD)."],
    ["eklenti_dusme_limiti", 5, "int", "Gözetmen", "Art arda bu kadar düşen eklenti ELLE_MÜDAHALE durumuna geçer.", 1, 100],
    ["log_saklama_gun", 10, "int", "Loglama", "Log dosyalarının saklanma süresi.", 1, 3650],
  ].map(([anahtar, deger, tur, grup, aciklama, alt = null, ust = null, secenekler = null]) => ({ anahtar, deger, varsayilan: deger, tur, grup, aciklama, alt, ust, secenekler }));

  // ================================================================ 2026-09-30 tasarımı: kural isteği, izleme, bildirimler
  const KATALOG = [
    ["HEDEF_DEVRE", "Hedef / teslim", "Devre kesildi", "KRITIK", "hedef", 1, "Control-M art arda yanıt vermedi; yeni tetikler denenmeden lokale yazılıyor.", "Control-M'in durumunu kontrol edin; düzelince 'Devreyi normale al', ardından 'Kademeli erit'."],
    ["HEDEF_KALICI", "Hedef / teslim", "Kalıcı hata (istek reddedildi)", "KRITIK", "hedef", 1, "Control-M isteği reddetti (4xx: olay/iş adı, klasör, yetki). Tetik lokalde bekler, yeniden denenmez.", "Kuralın isteğini 'Kuru deneme' ile kontrol edin, düzeltin, sonra erit edin."],
    ["DOSYA_GONDERILEMEDI", "Hedef / teslim", "Dosya hedefe gönderilemedi", "UYARI", "dizin", 1, "Deneme planı bitti; tetik lokal kayda yazıldı.", "Control-M düzelince Lokal kayıt sayfasından 'Kademeli erit'."],
    ["DOSYA_OLASI_CIFT", "Hedef / teslim", "Olası çift çağrı", "UYARI", "dizin", 0, "Cevap gelmeden bağlantı koptu; Control-M işi iki kez başlatmış olabilir.", "Control-M'de FWP_KIMLIK değişkeniyle iki çalışma var mı bakın."],
    ["DOSYA_SLA", "Hedef / teslim", "SLA aşıldı", "BILGI", "dizin", 0, "Dosya hazır olduktan sonra Control-M'e iletim hedef süreyi aştı.", "Sık oluyorsa Sistem izleme ve Control-M yanıt sürelerine bakın."],
    ["DOSYA_KAYITSIZ", "Hedef / teslim", "Kayıtsız kapalıyken dosya geldi", "UYARI", "dizin", 1, "Hedef ya da kural kayıtsız kapalıydı; dosya Control-M'e gönderilmedi ve saklanmadı.", "Gerekirse dosyayı elle işleyin; hedefi açın."],
    ["ERIT_DURDU", "Hedef / teslim", "Kademeli erit durdu", "UYARI", "hedef", 1, "Erit sırasında Control-M hata verdi; kalanlar lokalde güvende.", "Control-M düzelince eriti yeniden başlatın."],
    ["LOKAL_BIRIKTI", "Hedef / teslim", "Lokalde kayıt birikiyor", "UYARI", "hedef", 0, "Gönderilemeyen tetikler lokal kayıtta bekliyor.", "Hedef sağlıklıysa 'Kademeli erit' başlatın."],
    ["HEDEF_KAPALI_UZUN", "Hedef / teslim", "Hedef / kural uzun süredir kapalı", "UYARI", "hedef", 0, "Bir hedef ya da kural ayarlanan süreden uzun kapalı.", "Kapatma bilinçliyse onaylayın; değilse açın."],
    ["LOKAL_KAYIT", "Hedef / teslim", "Lokal kayıt yazılamıyor / bozuk", "KRITIK", "sistem", 1, "Lokal kayıt klasörüne yazılamıyor ya da okunamayan kayıt karantinaya alındı.", "Disk ve klasör izinlerini kontrol edin; tetikler veritabanında güvende."],
    ["DIZIN_ERISILEMEZ", "Dizin / dosya", "Dizine erişilemiyor", "KRITIK", "dizin", 1, "Ağ yolu ya da paylaşım erişilemez; 5/10/15 sn denemeleri bitti.", "Paylaşımı ve servis hesabının okuma yetkisini kontrol edin; dizin gelince kaçanlar yakalanır."],
    ["DIZIN_YANITSIZ", "Dizin / dosya", "Dizin yanıt vermiyor (ağ takıldı)", "KRITIK", "dizin", 1, "Dizin listelemesi zaman aşımına uğradı.", "Dosya sunucusu ve ağ bağlantısını kontrol edin."],
    ["YUKLEME_ASKIDA", "Dizin / dosya", "Yükleme askıda (çok uzun sürüyor)", "UYARI", "dizin", 1, "Yazılmakta olan dosya ayarlanan süreyi aştı; tamamlanana kadar tetiklenmez.", "FTP tarafında yüklemenin durumuna bakın; yarım kaldıysa dosyayı yeniden isteyin."],
    ["DOSYA_OKUNAMIYOR", "Dizin / dosya", "Dosya okunamıyor (izin)", "UYARI", "dizin", 0, "Dosya listede görünüyor ama açılamıyor; bilinmiyor sayılır.", "Servis hesabının dosya üzerindeki okuma iznini kontrol edin."],
    ["DOSYA_ESLESMEDI", "Dizin / dosya", "Kurala uymayan dosya geldi", "BILGI", "dizin", 0, "Uzantısı uyan ama hiçbir kuralın regex'ine uymayan dosya.", "Yeni bir dosya türü mü? Kural ekleyin ya da regex'i genişletin."],
    ["EKLENTI_ELLE", "Sistem", "Bileşen elle müdahale bekliyor", "KRITIK", "sistem", 1, "Bir bileşen art arda düştü; otomatik yeniden başlatma durdu.", "Eklentiler sayfasında son hataya bakın, 'Başlat' ile yeniden deneyin."],
    ["EKLENTI_DUSTU", "Sistem", "Bileşen düştü (kendiliğinden kalktı)", "UYARI", "sistem", 0, "Bir bileşen beklenmedik biçimde kapandı ve yeniden başlatıldı.", "Tekrarlanıyorsa logları inceleyin."],
    ["CEKIRDEK_YENIDEN", "Sistem", "Çekirdek beklenmedik kapandı", "UYARI", "sistem", 1, "Windows servisi çekirdeği yeniden başlattı; kayıp yok.", "Sık tekrarlanıyorsa loglar klasöründeki cekirdek loguna bakın."],
    ["BAKIM_HATA", "Sistem", "Haftalık bakım başarısız", "UYARI", "sistem", 0, "REINDEX/ANALYZE/checkpoint tamamlanamadı.", "Bakım logunu inceleyin; 'Şimdi bakım yap' ile yeniden deneyin."],
    ["DB_BOYUT", "Sistem", "Veritabanı büyüdü", "UYARI", "sistem", 0, "canli.db ya da hata.db beklenenden büyük.", "Saklama sınırlarını ve çözülmemiş kayıtları kontrol edin."],
    ["HATA_DB_SINIR", "Sistem", "Çözülmemiş kayıt sınırı aşıldı", "UYARI", "sistem", 0, "Gönderilemeyen çözülmemiş kayıtlar sınırı aştı (silinmezler).", "Gönderilemeyenler sayfasındaki kayıtları çözün."],
    ["VARSAYILAN_SIFRE", "Sistem", "Varsayılan şifre kullanılıyor", "UYARI", "sistem", 0, "admin hesabının şifresi hâlâ ilk kurulumdaki gibi.", "Sağ üstteki kilit simgesinden şifreyi değiştirin."],
    ["KAYNAK_SUNUCU_CPU", "Kaynaklar (sistem izleme)", "Sunucu CPU eşiği aşıldı", "UYARI", "sistem", 1, "Sunucunun işlemci kullanımı eşiği belirtilen süre boyunca aştı.", "Sistem izleme sayfasında hangi sürecin yük bindirdiğine bakın."],
    ["KAYNAK_SUNUCU_RAM", "Kaynaklar (sistem izleme)", "Sunucu bellek eşiği aşıldı", "UYARI", "sistem", 1, "Sunucunun bellek kullanımı eşiği belirtilen süre boyunca aştı.", "Sunucudaki diğer uygulamaların bellek kullanımını kontrol edin."],
    ["KAYNAK_DISK", "Kaynaklar (sistem izleme)", "Disk boş alanı azaldı", "KRITIK", "sistem", 1, "Veri ya da log diskinde boş alan eşiğin altına düştü; veritabanı yazamazsa izleme durur.", "Diskte yer açın; log saklama süresini azaltın."],
    ["KAYNAK_FWP_CPU", "Kaynaklar (sistem izleme)", "FileWatcherPro CPU eşiği aşıldı", "UYARI", "sistem", 1, "FileWatcherPro bileşenlerinin toplam işlemci kullanımı eşiği aştı.", "Çok büyük dizin ya da kısa tarama aralığı olabilir; Sistem izleme'de bileşenlere bakın."],
    ["KAYNAK_FWP_RAM", "Kaynaklar (sistem izleme)", "FileWatcherPro bellek eşiği aşıldı", "UYARI", "sistem", 1, "FileWatcherPro bileşenlerinin toplam belleği eşiği aştı.", "Bileşeni yeniden başlatmak geçici çözüm olur; logları saklayıp bildirin."],
    ["KAYNAK_LOG", "Kaynaklar (sistem izleme)", "Log klasörü büyüdü", "UYARI", "sistem", 0, "Log klasörü eşik boyutu aştı.", "Log saklama süresini ve boyut sınırını kontrol edin."],
    ["KAYNAK_TARAMA", "Kaynaklar (sistem izleme)", "Dizin taraması yavaş", "UYARI", "dizin", 0, "Bir dizinin listelenmesi art arda eşik süreyi aştı; yeni dosyalar geç fark edilir.", "Dosya sunucusu yükünü ve dizindeki dosya sayısını kontrol edin."],
  ].map(([kod, grup, ad, seviye, kapsam, onerilen, aciklama, oneri]) => ({ kod, grup, ad, seviye, kapsam, onerilen: !!onerilen, aciklama, oneri }));
  const KATEGORI = [[/^dizin:\d+:erisilemez/, "DIZIN_ERISILEMEZ"], [/^dizin:\d+:yanitsiz/, "DIZIN_YANITSIZ"], [/^askida:/, "YUKLEME_ASKIDA"],
    [/^hedef:\d+:devre/, "HEDEF_DEVRE"], [/^hedef:\d+:kalici/, "HEDEF_KALICI"], [/^hedef:\d+:erit/, "ERIT_DURDU"], [/^hedef:\d+:lokalde/, "LOKAL_BIRIKTI"],
    [/^(hedef|kural):\d+:kapali/, "HEDEF_KAPALI_UZUN"], [/^lokal:/, "LOKAL_KAYIT"], [/^eklenti:[a-z_]+:elle/, "EKLENTI_ELLE"], [/^eklenti:[a-z_]+:dustu/, "EKLENTI_DUSTU"],
    [/^servis:cekirdek_dustu/, "CEKIRDEK_YENIDEN"], [/^bakim:/, "BAKIM_HATA"], [/^db:/, "DB_BOYUT"], [/^hata_db:/, "HATA_DB_SINIR"], [/^kontrol:varsayilan_sifre/, "VARSAYILAN_SIFRE"],
    [/^kaynak:sunucu_cpu/, "KAYNAK_SUNUCU_CPU"], [/^kaynak:sunucu_ram/, "KAYNAK_SUNUCU_RAM"], [/^kaynak:disk/, "KAYNAK_DISK"], [/^kaynak:fwp_cpu/, "KAYNAK_FWP_CPU"],
    [/^kaynak:fwp_ram/, "KAYNAK_FWP_RAM"], [/^kaynak:log/, "KAYNAK_LOG"], [/^kaynak:tarama/, "KAYNAK_TARAMA"]];
  P.bakim.gecmis.push({ zaman: P.bakim.son.basladi, kullanici: "zamanlayıcı", sonuc: P.bakim.son },
    { zaman: P.bakim.son.basladi - 7 * 86400, kullanici: "zamanlayıcı", sonuc: { ...P.bakim.son, basladi: P.bakim.son.basladi - 7 * 86400, sure_ms: 201 } },
    { zaman: P.bakim.son.basladi - 9 * 86400, kullanici: "deniz", sonuc: { durum: "HATA", sure_ms: 612, geri_alinan: "REINDEX + ANALYZE: canli.db", hatali_adim: "reindex_canli", sistem_etkilenmedi: true, hata_mesaji: "database is locked (başka süreç uzun yazma yapıyordu)", budama_canli: { dosya: 3, tetik: 11 }, canli: { boyut_mb: 1.9, once_mb: 1.9 }, hata: { boyut_mb: 0.9, once_mb: 0.9 } } });
  P.bildirim = {
    smtp: { sunucu: "mail.sirket.local", port: 587, guvenlik: "STARTTLS", kullanici: "fwp@sirket.local", sifre_ref: "", sifre_kayitli: true, sifre_kaynagi: "uygulamada şifreli (bu sunucu)", gonderen: "fwp@sirket.local", gonderen_ad: "FileWatcherPro", aktif: 1 },
    kurallar: [
      { id: 501, ad: "Operasyon · kritikler", alicilar: ["operasyon@sirket.local"], olaylar: ["HEDEF_DEVRE", "HEDEF_KALICI", "DIZIN_ERISILEMEZ", "DIZIN_YANITSIZ", "EKLENTI_ELLE", "LOKAL_KAYIT", "KAYNAK_DISK"],
        seviye: "KRITIK", dizinler: null, ozet_dk: 0, tekrar_dk: 60, duzelince: 1, aktif: 1 },
      { id: 502, ad: "Muhasebe · dosya sorunları", alicilar: ["muhasebe.it@sirket.local", "deniz@sirket.local"], olaylar: ["DOSYA_GONDERILEMEDI", "DOSYA_ESLESMEDI", "YUKLEME_ASKIDA", "DOSYA_KAYITSIZ"],
        seviye: "BILGI", dizinler: [1], ozet_dk: 30, tekrar_dk: 120, duzelince: 0, aktif: 1 },
    ],
    gecmis: [], son_durum: { zaman: g(2 * 3600), basarili: true, mesaj: "" },
  };
  P.bildirim.gecmis.push(
    { id: yeniId(), zaman: g(2 * 3600), kural: "Muhasebe · dosya sorunları", alicilar: ["muhasebe.it@sirket.local", "deniz@sirket.local"], konu: "[FileWatcherPro] Özet: 3 olay (Muhasebe)", olay_sayisi: 3, durum: "GONDERILDI" },
    { id: yeniId(), zaman: g(26 * 3600), kural: "Operasyon · kritikler", alicilar: ["operasyon@sirket.local"], konu: "[FileWatcherPro] KRİTİK: Dizine erişilemiyor (\\\\ORNEK-SUNUCU\\gelen\\lojistik)", olay_sayisi: 1, durum: "GONDERILDI" },
    { id: yeniId(), zaman: g(26 * 3600 - 600), kural: "Operasyon · kritikler", alicilar: ["operasyon@sirket.local"], konu: "[FileWatcherPro] DÜZELDİ: Dizine erişilemiyor (\\\\ORNEK-SUNUCU\\gelen\\lojistik)", olay_sayisi: 1, durum: "GONDERILDI" },
    { id: yeniId(), zaman: g(3 * 86400), kural: "(test)", alicilar: ["deniz@sirket.local"], konu: "[FileWatcherPro] Test maili", olay_sayisi: 0, durum: "HATA", hata: "535 Kimlik doğrulama başarısız (şifre referansı yanlış)" });
  function alarmZengin(a) {
    const kat = (KATEGORI.find(([r]) => r.test(a.anahtar)) || [null, "DIGER"])[1];
    const m = a.anahtar.match(/^(dizin|hedef|askida):(\d+)/);
    const nesne = !m ? (a.anahtar.match(/^eklenti:([a-z_]+)/) || [])[1] || null : m[1] === "hedef" ? (hedef(+m[2]) || {}).ad : (dizin(+m[2]) || {}).yol;
    const kurallar = P.bildirim.kurallar.filter(k => k.aktif && k.olaylar.includes(kat) && (!k.dizinler || !m || m[1] === "hedef" || k.dizinler.includes(+m[2])));
    return { ...a, kategori: kat, nesne, mail: kurallar.length ? kurallar.map(k => `${k.ad} → ${k.alicilar.join(", ")}`).join(" · ") : null };
  }
  const ORNEK_EK = { 1: ["fatura_20260930.CSV", "IADE_2211.txt", "rapor_aylik.csv", "FATURA_2026.csv", "FATURA_20260931_v2.csv"],
    2: ["SEVK_IST_20260930.csv", "sevk_ank_20260930.csv", "SEVK_IZMIR_20260930.csv", "stok_sayim.csv"], 3: ["BORDRO_202609.xlsx", "bordro_202610.XLSX", "izin_listesi.xlsx"] };
  const deneMetni = gun => gun.toISOString().slice(0, 10).replace(/-/g, "");
  function istekOlustur(g_) {
    const hd = hedef(+g_.hedef_id); if (!hd) throw new Hata(400, "hedef bulunamadı");
    if (!g_.ornek_ad) throw new Hata(400, "deneme için regex'e uyan bir dosya adı seçin");
    let m; try { m = jsRegex(g_.regex || "", g_.harf_duyarsiz).exec(g_.ornek_ad); } catch (e) { throw new Hata(400, `regex geçersiz: ${e.message}`); }
    if (!m) throw new Hata(400, `'${g_.ornek_ad}' regex'e uymuyor`);
    const d = dizin(+g_.dizin_id) || { yol: "\\\\SUNUCU\\gelen" }; const now = new Date(simdi() * 1000);
    const deg = { dosya_adi: g_.ornek_ad, tam_yol: `${d.yol}\\${g_.ornek_ad}`, dizin: d.yol, boyut: "15342", icerik_hash: "9f2c4e1ab07d5c3e8f61a2b4c9d0e7f1",
      kimlik: "deneme-" + Math.random().toString(16).slice(2, 18), kural: g_.ad || "kural", zaman: now.toISOString().slice(0, 19).replace("T", " "),
      bugun: deneMetni(now), ctm: (hd.ayrintilar || {}).ctm || "", ...(m.groups || {}) };
    const yerlestir = (metin, kac) => String(metin || "").replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, a) => {
      if (!(a in deg)) throw new Hata(400, `bilinmeyen değişken {${a}}: yerleşik değişkenlerden ya da regex grubu olmalı`); return kac(String(deg[a] ?? "")); });
    const yol = yerlestir(g_.istek.yol || "/", encodeURIComponent);
    const govde = (g_.istek.govde || "").trim() ? yerlestir(g_.istek.govde, v => JSON.stringify(v).slice(1, -1)) : "";
    let govdeJson = null;
    if (govde) { try { govdeJson = JSON.parse(govde); } catch (e) { throw new Hata(400, `gövde geçerli JSON değil: ${e.message}`); } }
    const basliklar = { "Content-Type": "application/json", "X-Idempotency-Key": deg.kimlik };
    const a = hd.ayrintilar || {};
    if (a.kimlik_turu === "token") basliklar.Authorization = "Bearer •••••• (oturum token'ı; gönderimde alınır)"; else if (a.kimlik_turu === "apikey") basliklar["x-api-key"] = "••••••";
    return { yontem: g_.istek.yontem, url: hd.adres.replace(/\/$/, "") + (yol.startsWith("/") ? yol : "/" + yol), basliklar, govde: govdeJson ? JSON.stringify(govdeJson, null, 2) : "" };
  }
  // tutarlı (her yenilemede aynı) izleme verisi: zaman dilimine bağlı sözde rastgele
  const prng = i => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
  function izleme(aralik) {
    const adimSn = aralik === "24s" ? 240 : 10, n = 360, t = simdi(), son = Math.floor(t / adimSn);
    const zaman = [], scpu = [], fcpu = [], sram = [], fram = [];
    for (let i = n - 1; i >= 0; i--) {
      const k = son - i; zaman.push(k * adimSn);
      const gun = Math.sin((k * adimSn) / 86400 * 2 * Math.PI - 1.2);
      scpu.push(Math.max(2, 22 + 14 * gun + 18 * prng(k) ** 3 + (P.cokuk && i < 30 ? 35 : 0)));
      fcpu.push(Math.max(0.2, 1.2 + 0.8 * prng(k + 7) + (i < 3 ? 1.5 : 0)));
      sram.push(58 + 6 * gun + 3 * prng(k + 3));
      fram.push(142 + 6 * prng(k + 11) + (aralik === "24s" ? (n - i) * 0.02 : 0));
    }
    const s = { sunucu: { ad: "ORNEK-FWP01", cekirdek: 8, cpu: scpu[n - 1], ram_yuzde: sram[n - 1], ram_toplam_mb: 16384, ram_kullanilan_mb: 16384 * sram[n - 1] / 100, acik_sn: 38 * 86400 + 5 * 3600,
        diskler: [{ surucu: "C:", icerik: "veri, lokal kayıt", bos_mb: P.cokuk ? 3800 : 61234, toplam_mb: 255000, bos_yuzde: (P.cokuk ? 3800 : 61234) / 2550 }, { surucu: "D:", icerik: "loglar", bos_mb: 412000, toplam_mb: 512000, bos_yuzde: 80.5 }] },
      fwp: { cpu: fcpu[n - 1], ram_mb: fram[n - 1], calisma_sn: 5 * 86400 + 3 * 3600 + 12 * 60, surecler: P.eklentiler.map((e, i) => ({ ad: e.ad, pid: e.pid,
        cpu: [0.1, fcpu[n - 1] * 0.62, fcpu[n - 1] * 0.2, fcpu[n - 1] * 0.15, 0.3, 0.05, 0.9][i], cpu_tepe: [0.4, 9.8, 3.1, 2.2, 1.1, 0.4, 24.5][i],
        ram_mb: [30.1, 44.8, 31.5, 34.2, 27.3, 25.9, 212.4][i], thread: [4, 9, 11, 7, 5, 4, 6][i], handle: [212, 388, 301, 265, 190, 172, 240][i],
        calisma_sn: e.pid ? 5 * 86400 - i * 40 : null })) },
      depo: { canli_mb: 6.3, hata_mb: 1.1, lokal_adet: P.tetikler.filter(x => x.durum === "LOKALDE").length, lokal_mb: 0.01 * P.tetikler.filter(x => x.durum === "LOKALDE").length, log_mb: 184.2, log_adet: 42 } };
    const ay = k => (AYARLAR.find(x => x.anahtar === k) || {}).deger;
    const tanim = [
      ["sunucu_cpu", "Sunucu CPU", "Sunucunun toplam işlemci kullanımı", "izleme_sunucu_cpu", "%", ">", s.sunucu.cpu, "UYARI"],
      ["sunucu_ram", "Sunucu bellek", "Sunucunun bellek kullanımı", "izleme_sunucu_ram", "%", ">", s.sunucu.ram_yuzde, "UYARI"],
      ["disk_bos", "Disk boş alan", "Veri ve log disklerinin en azı", "izleme_disk_bos_gb", "GB", "<", Math.min(...s.sunucu.diskler.map(dk => dk.bos_mb)) / 1024, "KRITIK"],
      ["fwp_cpu", "FileWatcherPro CPU", "Tüm bileşenlerin toplamı (sunucunun yüzdesi)", "izleme_fwp_cpu", "%", ">", s.fwp.cpu, "UYARI"],
      ["fwp_ram", "FileWatcherPro bellek", "Tüm bileşenlerin toplamı", "izleme_fwp_ram_mb", "MB", ">", s.fwp.ram_mb, "UYARI"],
      ["log_boyut", "Log klasörü", "Log klasörünün toplam boyutu", "izleme_log_mb", "MB", ">", s.depo.log_mb, "UYARI"],
      ["tarama_suresi", "Dizin tarama süresi", "Bir dizinin listelenmesi (3 tur üst üste)", "izleme_tarama_sn", "sn", ">", 0.06, "UYARI"],
    ];
    const esikler = tanim.map(([anahtar, ad, aciklama, ayar, birim, yon, deger, seviye]) => {
      const esik = ay(ayar), aktif = ay(`${ayar}_aktif`) !== false, sure = ay(`${ayar}_dk`);
      const asti = aktif && (yon === ">" ? deger > esik : deger < esik);
      const alarm = asti && (anahtar === "disk_bos" || anahtar === "sunucu_cpu");
      const fmt = v => birim === "%" ? `%${ondalik(v, 0)}` : `${ondalik(v, birim === "sn" ? 2 : v < 10 ? 1 : 0)} ${birim}`;
      if (alarm) alarmAc(`kaynak:${anahtar}`, `${ad} ${yon === ">" ? "eşiği aştı" : "eşiğin altına düştü"}: ${fmt(deger)} (eşik ${yon} ${fmt(esik)}).`, seviye, "izleme");
      else alarmKapat(`kaynak:${anahtar}`);
      return { anahtar, ad, aciklama, ayar, sure_ayar: sure !== undefined ? `${ayar}_dk` : null, esik, sure_dk: sure, birim, seviye, aktif,
        simdi_metin: fmt(deger), esik_metin: `${yon} ${fmt(esik)}`, durum: alarm ? "ALARM" : asti ? "ASILDI" : "NORMAL", asilma_zamani: asti ? t - 90 : null,
        mail: P.bildirim.kurallar.some(k => k.aktif && k.olaylar.includes(KATEGORI.find(([r]) => r.test(`kaynak:${anahtar}`))[1])) };
    });
    return { aralik_sn: 10, olcum_zamani: t, simdi: s, gecmis: { zaman, sunucu_cpu: scpu, fwp_cpu: fcpu, sunucu_ram: sram, fwp_ram: fram }, esikler };
  }
  const epostaMi = x => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x);
  function bildirimKuraliDogrula(g_) {
    if (!(g_.ad || "").trim()) throw new Hata(400, "kural adı boş olamaz");
    if (!g_.alicilar || !g_.alicilar.length) throw new Hata(400, "en az bir alıcı girin");
    const kotu = g_.alicilar.filter(x => !epostaMi(x)); if (kotu.length) throw new Hata(400, `geçersiz e-posta adresi: ${kotu.join(", ")}`);
    if (!g_.olaylar || !g_.olaylar.length) throw new Hata(400, "en az bir olay seçin");
    if (g_.dizinler && !g_.dizinler.length) throw new Hata(400, "'Seçili dizinler' için en az bir dizin işaretleyin");
  }
  // ---------------------------------------------------------------- betik hedefi (2026-10-01 tasarım prototipi)
  const DILLER = {
    python: { surum: "Python 3.11.9 (servisle aynı yorumlayıcı)", komut: "python.exe -X utf8 -I betik.py", yol: "C:\\Program Files\\Python311\\python.exe" },
    powershell: { surum: "Windows PowerShell 5.1", komut: "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File calistir.ps1", yol: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" },
  };
  const betikDurum = () => ({ sifre_tanimli: P.betik.sifre_tanimli, kilit_acik: P.betik.bitis > simdi(), kalan_sn: Math.max(0, Math.round(P.betik.bitis - simdi())), diller: DILLER });
  const kilitGerek = () => { if (!(P.betik.bitis > simdi())) throw new Hata(403, "betik kilidi kapalı: süper yönetici şifresiyle açın"); };
  const ozet7 = t => { let x = 0x811c9dc5; for (const c of String(t)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619) >>> 0; } return x.toString(16).padStart(8, "0").slice(0, 7); };
  function hedefAyrintisi(g_, eski) {              // gerçek sistemde şifre / anahtar / gizli değer DPAPI ile şifrelenip saklanır
    const ea = (eski && eski.ayrintilar) || {};
    if (!(g_.ad || "").trim()) throw new Hata(400, "ad boş olamaz");
    if (g_.tur === "BETIK") {
      kilitGerek();
      const a = g_.ayrintilar || {};
      if (!(a.kod || "").trim()) throw new Hata(400, "betik boş olamaz");
      if (!DILLER[a.dil]) throw new Hata(400, "dil python ya da powershell olmalı");
      const ad_ = (a.sirlar || []).map(z => z.ad); const cift = ad_.find((z, i) => ad_.indexOf(z) !== i); if (cift) throw new Hata(400, `gizli değer adı iki kez: ${cift}`);
      const sirlar = (a.sirlar || []).map(z => { const o = (ea.sirlar || []).find(y => y.ad === z.ad);
        if (!z.deger && !o) throw new Hata(400, `'${z.ad}' gizli değeri için değer girin`); return { ad: z.ad, kayitli: true, kaynak: "uygulamada şifreli (bu sunucu)" }; });
      return { dil: a.dil, kod: a.kod, zaman_asimi_sn: Math.min(600, Math.max(1, +a.zaman_asimi_sn || 30)), eszamanli: Math.min(8, Math.max(1, +a.eszamanli || 1)), sirlar,
        surum: ozet7(a.dil + a.kod), degistiren: P.ben.kullanici, degisme_zamani: simdi(), son_calisma: ea.son_calisma };
    }
    if (!/^https?:\/\//.test(g_.adres || "")) throw new Hata(400, "hedef adresi http:// ya da https:// ile başlamalı");
    const { sifre, apikey, anahtar, ...ayr } = g_.ayrintilar || {};
    for (const k of ["sifre", "apikey", "anahtar"]) if (ea[`${k}_kayitli`] && !g_.ayrintilar[k]) Object.assign(ayr, { [`${k}_ref`]: ea[`${k}_ref`], [`${k}_kayitli`]: true, [`${k}_kaynagi`]: ea[`${k}_kaynagi`] });
    if (sifre) Object.assign(ayr, { sifre_ref: "dpapi:(şifreli)", sifre_kayitli: true, sifre_kaynagi: "uygulamada şifreli (bu sunucu)" });
    if (apikey) Object.assign(ayr, { apikey_ref: "dpapi:(şifreli)", apikey_kayitli: true, apikey_kaynagi: "uygulamada şifreli (bu sunucu)" });
    if (anahtar) Object.assign(ayr, { anahtar_ref: "dpapi:(şifreli)", anahtar_kayitli: true, anahtar_kaynagi: "uygulamada şifreli (bu sunucu)" });
    return ayr;
  }
  function betikOrtami(g_, deg, gruplar, parametreler, sirAdlari, deneme) {
    const ortam = {};
    for (const [v, k] of BETIK_DEGISKENLERI) ortam[v] = k === "deneme" ? (deneme ? "1" : "0") : k === "deneme_sayisi" ? "1" : String(deg[k] ?? "");
    for (const [k, v] of Object.entries(gruplar)) ortam[`FWP_G_${k.toUpperCase()}`] = v;
    for (const [k, v] of Object.entries(parametreler)) ortam[`FWP_P_${k}`] = v;
    for (const k of sirAdlari) ortam[`FWP_SIR_${k}`] = "*** (gizli)";
    const stdin = {}; for (const [, k] of BETIK_DEGISKENLERI) stdin[k] = k === "deneme" ? !!deneme : k === "deneme_sayisi" ? 1 : k === "boyut" ? +deg.boyut : deg[k];
    return { komut: DILLER[g_.dil].komut, ortam, stdin: { ...stdin, gruplar, parametreler } };
  }
  function betikKos(dil, kod, ortam, zaman, sirAdlari) {     // sahte çalıştırma: gerçek sistemde ayrı süreç + iş nesnesi
    const sure = Math.floor(rnd(280, 1400));
    const eksik = [...kod.matchAll(/FWP_SIR_([A-Z0-9_]+)/g)].map(m => m[1]).find(a => !sirAdlari.includes(a));
    if (/time\.sleep\(\s*\d{3,}|Start-Sleep\s+(-Seconds\s+)?\d{3,}/.test(kod)) return { cikis_kodu: null, sonuc: "BELIRSIZ", sure_ms: zaman * 1000, stdout: "", stderr: "", mesaj: `süre doldu (${zaman} sn): süreç ağacı sonlandırıldı` };
    if (eksik) return dil === "python"
      ? { cikis_kodu: 1, sonuc: "GECICI", sure_ms: 61, stdout: "", stderr: `Traceback (most recent call last):\n  File "betik.py", line 10, in <module>\n    "Authorization": "Bearer " + os.environ["FWP_SIR_${eksik}"],\nKeyError: 'FWP_SIR_${eksik}'`, mesaj: "" }
      : { cikis_kodu: 1, sonuc: "GECICI", sure_ms: 412, stdout: "", stderr: `FWP_SIR_${eksik} tanımlı değil`, mesaj: "" };
    if (/exit 10|sys\.exit\(10\)/.test(kod) && /HATA_DENE/.test(kod)) return { cikis_kodu: 10, sonuc: "KALICI", sure_ms: sure, stdout: "", stderr: "HTTP 404 {\"hata\": \"iş bulunamadı: FATURA_YUKLE\"}", mesaj: "" };
    const api = /urlopen|Invoke-RestMethod|curl\.exe/.test(kod);
    const stdout = api ? (dil === "python" ? `HTTP 200 {"runId": "7f3a91c2", "durum": "kabul", "dosya": "${ortam.FWP_DOSYA_ADI}"}` : `Kabul edildi: {"runId":"7f3a91c2","durum":"kabul"}`)
      : `Dosya: ${ortam.FWP_DOSYA_ADI}\nTam yol: ${ortam.FWP_TAM_YOL}\nTetik kimliği: ${ortam.FWP_KIMLIK} · canlı test: 1`;
    return { cikis_kodu: 0, sonuc: "BASARI", sure_ms: sure, stdout, stderr: "", mesaj: "" };
  }
  function ornekDegerler(dosya_adi, dizinYol) {
    const now = new Date(simdi() * 1000);
    return { dosya_adi, tam_yol: `${dizinYol}\\${dosya_adi}`, dizin: dizinYol, boyut: "15342", icerik_hash: "9f2c4e1ab07d5c3e8f61a2b4c9d0e7f1",
      kimlik: "deneme-" + Math.random().toString(16).slice(2, 18), zaman: now.toISOString().slice(0, 19).replace("T", " "), bugun: deneMetni(now) };
  }
  ROTALAR.push(
    ["GET", /^\/api\/betik\/durum$/, () => betikDurum()],
    ["POST", /^\/api\/kurallar\/toptan_kapat$/, g_ => { yetki("OPERATOR"); const l = P.kurallar.filter(k => k.aktif && (g_.dizin_id == null || k.dizin_id === g_.dizin_id));
      l.forEach(k => { k.aktif = 0; k.kapatma_modu = g_.mod; }); denetim("KURAL_TOPTAN_KAPAT", g_.dizin_id == null ? "tüm kurallar" : `dizin ${g_.dizin_id}`, { mod: g_.mod }); return { kapatilan: l.map(k => k.id) }; }],
    ["POST", /^\/api\/kurallar\/toptan_ac$/, g_ => { yetki("OPERATOR"); const l = P.kurallar.filter(k => !k.aktif && (g_.dizin_id == null || k.dizin_id === g_.dizin_id));
      l.forEach(k => { k.aktif = 1; }); denetim("KURAL_TOPTAN_AC", g_.dizin_id == null ? "tüm kurallar" : `dizin ${g_.dizin_id}`); return { acilan: l.map(k => k.id) }; }],
    ["GET", /^\/api\/hedefler\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const hd = hedef(+id); if (!hd) throw new Hata(404, "hedef bulunamadı"); return hd; }],
    ["POST", /^\/api\/betik\/kilit$/, g_ => { yetki("YONETICI"); if (!P.betik.sifre_tanimli) throw new Hata(400, "süper yönetici şifresi belirlenmemiş (sunucuda betik_sifresi.bat ile belirleyin)");
      if (P.betik.hatali >= 5) throw new Hata(429, "çok fazla hatalı deneme: 15 dakika bekleyin");
      if (!g_.sifre) throw new Hata(400, "şifre boş");
      if (g_.sifre === "yanlis") { P.betik.hatali++; denetim("BETIK_KILIDI_HATALI", P.ben.kullanici); throw new Hata(403, `süper yönetici şifresi yanlış (kalan deneme: ${5 - P.betik.hatali})`); }
      P.betik.hatali = 0; P.betik.bitis = simdi() + 600; denetim("BETIK_KILIDI_ACILDI", P.ben.kullanici); return betikDurum(); }],
    ["DELETE", /^\/api\/betik\/kilit$/, () => { P.betik.bitis = 0; denetim("BETIK_KILITLENDI", P.ben.kullanici); return betikDurum(); }],
    ["POST", /^\/api\/betik\/denetle$/, g_ => { yetki("YONETICI");
      const satirlar = String(g_.kod || "").split("\n"); let derinlik = 0, ilk = 0;
      for (let i = 0; i < satirlar.length; i++) for (const c of satirlar[i].replace(/(["'])(?:\\.|(?!\1).)*\1/g, "").replace(/#.*$/, "")) {
        if ("([{".includes(c)) { if (!derinlik) ilk = i + 1; derinlik++; } else if (")]}".includes(c)) { derinlik--; if (derinlik < 0) return { gecerli: false, satir: i + 1, mesaj: `satır ${i + 1}: fazladan kapanan parantez` }; } }
      if (derinlik) return { gecerli: false, satir: ilk, mesaj: `satır ${ilk}: açılan parantez kapanmamış` };
      return { gecerli: true, mesaj: g_.dil === "python" ? "Sözdizimi geçerli (Python derleyicisi; çalıştırılmadı)" : "Sözdizimi geçerli (PowerShell ayrıştırıcısı; çalıştırılmadı)" }; }],
    ["POST", /^\/api\/betik\/dene$/, g_ => { yetki("YONETICI"); if (!DILLER[g_.dil]) throw new Hata(400, "dil python ya da powershell olmalı");
      if (!(g_.ornek || {}).dosya_adi) throw new Hata(400, "deneme dosya adı boş olamaz");
      const gruplar = {}, parametreler = {}; for (const [k, v] of Object.entries(g_.ornek.ek || {})) (k.startsWith("G_") ? gruplar : parametreler)[k.slice(2)] = v;
      const sirAdlari = (g_.sirlar || []).map(z => z.ad);
      const deg = { ...ornekDegerler(g_.ornek.dosya_adi, "\\\\ORNEK-SUNUCU\\gelen\\muhasebe"), kural: "(canlı test)" };
      const r = betikOrtami(g_, deg, Object.fromEntries(Object.entries(gruplar).map(([k, v]) => [k.toLowerCase(), v])), parametreler, sirAdlari, true);
      if (!g_.calistir) return r;
      kilitGerek(); const s_ = betikKos(g_.dil, g_.kod, r.ortam, g_.zaman_asimi_sn || 30, sirAdlari);
      const hd = g_.hedef_id && hedef(+g_.hedef_id); if (hd) hd.ayrintilar.son_calisma = { cikis: s_.cikis_kodu, sure_ms: s_.sure_ms, zaman: simdi() };
      denetim("BETIK_CANLI_TEST", hd ? hd.ad : "(kaydedilmemiş betik)", { dosya: g_.ornek.dosya_adi, cikis: s_.cikis_kodu, surum: ozet7(g_.dil + g_.kod) }); return { ...r, ...s_ }; }],
    ["GET", /^\/api\/olay_katalogu$/, () => KATALOG],
    ["GET", /^\/api\/dizinler\/(\d+)\/ornek_adlar$/, (g_, q, id) => [...new Set([...P.dosyalar.filter(x => x.dizin_id === +id).map(x => x.dosya_adi), ...(ORNEK_EK[+id] || [])])].slice(0, 60)],
    ["POST", /^\/api\/kurallar\/dene$/, g_ => { const hb = hedef(+g_.hedef_id);
      if (hb && hb.tur === "BETIK") {
        if (!g_.ornek_ad) throw new Hata(400, "deneme için regex'e uyan bir dosya adı seçin");
        let m; try { m = jsRegex(g_.regex || "", g_.harf_duyarsiz).exec(g_.ornek_ad); } catch (e) { throw new Hata(400, `regex geçersiz: ${e.message}`); }
        if (!m) throw new Hata(400, `'${g_.ornek_ad}' regex'e uymuyor`);
        const d = dizin(+g_.dizin_id) || { yol: "\\\\SUNUCU\\gelen" }; const deg = { ...ornekDegerler(g_.ornek_ad, d.yol), kural: g_.ad || "kural" };
        const parametreler = {}; for (const [k, v] of Object.entries((g_.istek || {}).parametreler || {}))
          parametreler[k] = String(v).replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, a) => { const t = { ...deg, ...(m.groups || {}) }; if (!(a in t)) throw new Hata(400, `bilinmeyen değişken {${a}}`); return t[a]; });
        const r = { tur: "BETIK", ...betikOrtami(hb.ayrintilar, deg, m.groups || {}, parametreler, (hb.ayrintilar.sirlar || []).map(z => z.ad), !!g_.gonder) };
        if (!g_.gonder) return r;
        yetki("YONETICI"); kilitGerek(); const s_ = betikKos(hb.ayrintilar.dil, hb.ayrintilar.kod, r.ortam, hb.ayrintilar.zaman_asimi_sn, (hb.ayrintilar.sirlar || []).map(z => z.ad));
        hb.ayrintilar.son_calisma = { cikis: s_.cikis_kodu, sure_ms: s_.sure_ms, zaman: simdi() }; denetim("BETIK_CANLI_TEST", hb.ad, { dosya: g_.ornek_ad, cikis: s_.cikis_kodu, kural: g_.ad });
        return { ...r, ...s_ };
      }
      const r = istekOlustur(g_); if (!g_.gonder) return r; yetki("YONETICI");
      const runId = Math.random().toString(16).slice(2, 10); denetim("KURAL_ISTEK_GONDER", g_.ad || "kural", { url: r.url, dosya: g_.ornek_ad });
      return { ...r, yanit: { basarili: true, kod: 200, sure_ms: Math.floor(rnd(120, 480)), govde: JSON.stringify({ runId, statusURI: `${hedef(+g_.hedef_id).adres}/run/status/${runId}` }, null, 2) } }; }],
    ["PUT", /^\/api\/kurallar\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const k = kural(+id); if ([g_.hedef_id, k.hedef_id].some(i => (hedef(+i) || {}).tur === "BETIK")) kilitGerek(); try { jsRegex(g_.regex || "", true); } catch (e) { throw new Hata(400, `regex geçersiz: ${e.message}`); }
      const eski = { regex: k.regex, istek: k.istek }; Object.assign(k, { ad: g_.ad || g_.regex, regex: g_.regex, harf_duyarsiz: g_.harf_duyarsiz ? 1 : 0, sira: g_.sira, hedef_id: g_.hedef_id, istek: g_.istek });
      denetim("KURAL_GUNCELLE", k.ad, { regex: k.regex, istek: k.istek }, eski); }],
    ["POST", /^\/api\/hedefler\/(\d+)\/dene$/, (g_, q, id) => { yetki("OPERATOR"); const hd = hedef(+id);
      return P.cokuk && hd.id === 1 ? { basarili: false, sure_ms: 4003, mesaj: "bağlantı kurulamadı: [WinError 10061] hedef makine reddetti" }
        : { basarili: true, sure_ms: Math.floor(rnd(90, 350)), mesaj: hd.tur === "CONTROLM" ? "Control-M yanıt veriyor; oturum açıldı (config/servers: ctmprod UP)" : "Adres yanıt veriyor (HTTP 200)" }; }],
    ["POST", /^\/api\/hedefler\/dene$/, g_ => { if (!/^https?:\/\//.test(g_.adres || "")) throw new Hata(400, "adres http:// ya da https:// ile başlamalı");
      return { basarili: true, sure_ms: Math.floor(rnd(90, 350)), mesaj: g_.tur === "HTTP" ? `Adres yanıt veriyor (HEAD ${((g_.ayrintilar || {}).saglik_yolu) || "/"} → HTTP 200; kimlik kabul edildi)` : "Control-M yanıt veriyor; oturum açıldı" }; }],
    ["GET", /^\/api\/izleme/, (g_, q) => izleme(q.get("aralik") || "1s")],
    ["GET", /^\/api\/bildirim$/, () => ({ smtp: P.bildirim.smtp, kurallar: P.bildirim.kurallar, gecmis: P.bildirim.gecmis.slice(0, 100), son_durum: P.bildirim.son_durum })],
    ["PUT", /^\/api\/bildirim\/smtp$/, g_ => { yetki("YONETICI"); if (!g_.sunucu) throw new Hata(400, "sunucu boş olamaz"); if (!epostaMi(g_.gonderen || "")) throw new Hata(400, "gönderen adres geçersiz");
      if (g_.kullanici && !g_.sifre && !g_.sifre_ref && !P.bildirim.smtp.sifre_kayitli) throw new Hata(400, "kullanıcı girildiyse şifre de girilmeli");
      const ref = (g_.sifre_ref || "").trim(); if (ref && !/^(env|wincred):/.test(ref)) throw new Hata(400, "şifre referansı env:… ya da wincred:… biçiminde olmalı; şifrenin kendisini 'Şifre' alanına yazın");
      const kaynak = g_.sifre ? "uygulamada şifreli (bu sunucu)" : ref ? (ref.startsWith("env:") ? `ortam değişkeni ${ref.slice(4)}` : `Windows Kimlik Bilgisi ${ref.slice(8)}`) : P.bildirim.smtp.sifre_kaynagi;
      const { sifre, ...kalan } = g_;
      P.bildirim.smtp = { ...kalan, sifre_ref: ref, sifre_kayitli: !!g_.kullanici, sifre_kaynagi: g_.kullanici ? kaynak : "", aktif: g_.aktif ? 1 : 0 };
      denetim("SMTP_AYARLA", g_.sunucu, { port: g_.port, guvenlik: g_.guvenlik, sifre_degisti: !!sifre }); }],
    ["POST", /^\/api\/bildirim\/smtp\/dene$/, g_ => ({ basarili: !!g_.sunucu, mesaj: g_.sunucu ? `${g_.sunucu}:${g_.port} bağlandı, ${g_.guvenlik}, oturum açıldı (mail gönderilmedi)` : "sunucu boş" })],
    ["POST", /^\/api\/bildirim\/test$/, g_ => { yetki("OPERATOR"); if (!epostaMi(g_.alici || "")) throw new Hata(400, "geçerli bir alıcı adresi girin");
      P.bildirim.gecmis.unshift({ id: yeniId(), zaman: simdi(), kural: "(test)", alicilar: [g_.alici], konu: "[FileWatcherPro] Test maili", olay_sayisi: 0, durum: "GONDERILDI" });
      P.bildirim.son_durum = { zaman: simdi(), basarili: true, mesaj: "" }; denetim("TEST_MAILI", g_.alici); }],
    ["POST", /^\/api\/bildirim\/kurallar$/, g_ => { yetki("YONETICI"); bildirimKuraliDogrula(g_); const k = { id: yeniId(), ...g_, aktif: g_.aktif ? 1 : 0, duzelince: g_.duzelince ? 1 : 0 };
      P.bildirim.kurallar.push(k); denetim("BILDIRIM_KURAL_EKLE", k.ad, { olaylar: k.olaylar.length, alicilar: k.alicilar }); return { id: k.id }; }],
    ["PUT", /^\/api\/bildirim\/kurallar\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); bildirimKuraliDogrula(g_); const k = P.bildirim.kurallar.find(x => x.id === +id);
      Object.assign(k, g_, { aktif: g_.aktif ? 1 : 0, duzelince: g_.duzelince ? 1 : 0 }); denetim("BILDIRIM_KURAL_GUNCELLE", k.ad); }],
    ["DELETE", /^\/api\/bildirim\/kurallar\/(\d+)$/, (g_, q, id) => { yetki("YONETICI"); const k = P.bildirim.kurallar.find(x => x.id === +id);
      P.bildirim.kurallar = P.bildirim.kurallar.filter(x => x.id !== +id); denetim("BILDIRIM_KURAL_SIL", k.ad); }],
  );
  // alarm listesi ve durum özeti: tür / nesne / mail bilgisiyle
  const alarmRotasi = ROTALAR.find(r => r[0] === "GET" && String(r[1]) === String(/^\/api\/alarmlar$/));
  alarmRotasi[2] = () => P.alarmlar.map(alarmZengin);
  // kurallar: istek alanıyla
  const ISTEKLER = { 1: { yontem: "POST", yol: "/run/event/{ctm}/FATURA_GELDI/ODAT", govde: "" },
    2: { yontem: "POST", yol: "/run/order", govde: '{\n  "ctm": "{ctm}",\n  "folder": "MUHASEBE",\n  "jobs": "IADE_ISLE",\n  "variables": [{"FWP_DOSYA": "{dosya_adi}"}, {"IADE_NO": "{no}"}]\n}' },
    3: { yontem: "POST", yol: "/run/event/{ctm}/SEVK_{depo}_GELDI/ODAT", govde: "" },
    4: { yontem: "POST", yol: "/", govde: '{\n  "dosya": "{dosya_adi}",\n  "donem": "{donem}"\n}' } };
  for (const k of P.kurallar) k.istek = ISTEKLER[k.id];
  const kuralEkleRotasi = ROTALAR.find(r => r[0] === "POST" && String(r[1]) === String(/^\/api\/kurallar$/));
  const eskiKuralEkle = kuralEkleRotasi[2];
  kuralEkleRotasi[2] = g_ => { const r = eskiKuralEkle(g_); kural(r.id).istek = g_.istek; return r; };
  AYARLAR.push(...[
    ["kapanis_teslim_bekleme_sn", 15, "float", "Teslim", "Kapanırken bekleyen tetiklerin gönderilmesi için verilen süre; bitmeyenler veritabanında kalır, açılışta gönderilir.", 0, 60],
    ["izleme_aralik_sn", 10, "float", "İzleme", "Sistem kaynaklarının ölçülme sıklığı.", 5, 300],
    ["izleme_sunucu_cpu", 90, "float", "İzleme", "Sunucu CPU eşiği (%).", 1, 100], ["izleme_sunucu_cpu_aktif", true, "bool", "İzleme", "Sunucu CPU eşiği izlensin."], ["izleme_sunucu_cpu_dk", 5, "float", "İzleme", "Sunucu CPU eşiği bu süre aşılırsa alarm (dk).", 0, 1440],
    ["izleme_sunucu_ram", 90, "float", "İzleme", "Sunucu bellek eşiği (%).", 1, 100], ["izleme_sunucu_ram_aktif", true, "bool", "İzleme", "Sunucu bellek eşiği izlensin."], ["izleme_sunucu_ram_dk", 5, "float", "İzleme", "Sunucu bellek eşiği süresi (dk).", 0, 1440],
    ["izleme_disk_bos_gb", 5, "float", "İzleme", "Veri/log diskinde en az boş alan (GB).", 0.1, 100000], ["izleme_disk_bos_gb_aktif", true, "bool", "İzleme", "Disk boş alanı izlensin."],
    ["izleme_fwp_cpu", 25, "float", "İzleme", "FileWatcherPro toplam CPU eşiği (sunucunun %'si).", 1, 100], ["izleme_fwp_cpu_aktif", true, "bool", "İzleme", "FileWatcherPro CPU izlensin."], ["izleme_fwp_cpu_dk", 10, "float", "İzleme", "FileWatcherPro CPU eşiği süresi (dk).", 0, 1440],
    ["izleme_fwp_ram_mb", 1024, "float", "İzleme", "FileWatcherPro toplam bellek eşiği (MB).", 50, 1000000], ["izleme_fwp_ram_mb_aktif", true, "bool", "İzleme", "FileWatcherPro belleği izlensin."], ["izleme_fwp_ram_mb_dk", 10, "float", "İzleme", "Bellek eşiği süresi (dk).", 0, 1440],
    ["izleme_log_mb", 2048, "float", "İzleme", "Log klasörü boyut eşiği (MB).", 10, 1000000], ["izleme_log_mb_aktif", true, "bool", "İzleme", "Log klasörü boyutu izlensin."],
    ["izleme_tarama_sn", 10, "float", "İzleme", "Dizin tarama süresi eşiği (sn; 3 tur üst üste).", 0.5, 3600], ["izleme_tarama_sn_aktif", true, "bool", "İzleme", "Dizin tarama süresi izlensin."],
  ].map(([anahtar, deger, tur, grup, aciklama, alt = null, ust = null]) => ({ anahtar, deger, varsayilan: deger, tur, grup, aciklama, alt, ust, secenekler: null })));

  // ================================================================ 2026-09-30 tasarımı (2): yapay zekâ asistanı (yerel model)
  //  ?asistan=bos (ilk kurulum: veri toplanıyor) | ezber (son sürüm ezberledi) | varsayılan: öğreniyor
  P.eklentiler.push(
    { ad: "izleme", modul: "eklentiler.izleme.izleyici", durum: "CALISIYOR", pid: 4415, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: {} },
    { ad: "bildirim", modul: "eklentiler.bildirim.bildirimci", durum: "CALISIYOR", pid: 4422, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: {} },
    { ad: "asistan", modul: "eklentiler.asistan.asistan", durum: "CALISIYOR", pid: 4430, yeniden_baslatma: 0, ardisik_dusme: 0, son_hata: null, bilgi: { surum: 14 } });
  const AS = (() => {
    const senaryo = new URLSearchParams(location.search).get("asistan") || "ogreniyor";
    const t = simdi(), gun = 86400;
    const adimlar = Array.from({ length: 31 }, (_, i) => i * 100);
    const gr = (i, k) => (prng(i * 7 + k) - 0.5) * 0.05;
    const ezber = senaryo === "ezber";
    const egitim = adimlar.map((a, i) => ezber ? 0.35 + 2.55 * Math.exp(-a / 700) + gr(i, 1) : 1.08 + 1.82 * Math.exp(-a / 520) + gr(i, 1));
    const dogrulama = adimlar.map((a, i) => ezber ? 1.30 + 1.65 * Math.exp(-a / 450) + (a > 1400 ? ((a - 1400) / 1600) ** 1.4 * 0.45 : 0) + gr(i, 2)
      : 1.24 + 1.72 * Math.exp(-a / 600) + gr(i, 2) * 0.8);
    const enIyiI = dogrulama.indexOf(Math.min(...dogrulama));
    const k2 = v => ondalik(v, 2);
    const turler = ["Dosya geldi · Muhasebe", "Dosya geldi · Lojistik", "Dosya geldi · İK", "İletildi", "Yeniden denendi", "Lokale yazıldı",
      "Eşleşmedi · Lojistik", "Yükleme askıda · Lojistik", "Lojistik yanıtsız", "Control-M devre kesildi"];
    const matris = turler.map((_, i) => turler.map((__, j) => 0.3 + prng(i * 31 + j) * 1.1));     // dikkat oranı (1 = sıklığı kadar)
    const koy = (s, st, v) => { matris[turler.indexOf(s)][turler.indexOf(st)] = v * 10; };
    koy("Control-M devre kesildi", "Lojistik yanıtsız", 0.62); koy("Control-M devre kesildi", "Yeniden denendi", 0.41);
    koy("Lokale yazıldı", "Control-M devre kesildi", 0.55); koy("Dosya geldi · Lojistik", "Yükleme askıda · Lojistik", 0.33);
    koy("Eşleşmedi · Lojistik", "Eşleşmedi · Lojistik", 0.44); koy("İletildi", "Dosya geldi · Muhasebe", 0.36);
    koy("İletildi", "Dosya geldi · Lojistik", 0.31); koy("İletildi", "Dosya geldi · İK", 0.22); koy("Dosya geldi · İK", "Dosya geldi · Muhasebe", 0.27);
    koy("Yeniden denendi", "Lojistik yanıtsız", 0.24);
    const oneriler = [
      { id: 1, tur: "BEKLENEN_GELMEDI", nesne: "\\\\ORNEK-SUNUCU\\gelen\\muhasebe", baslik: "Muhasebe: bugünkü FATURA dosyası henüz gelmedi",
        metin: "Son 14 iş gününün 13'ünde FATURA_*.csv 08:45–09:20 arasında geldi. Şu an 09:52 ve bugün henüz yok.",
        kanit: ["13 / 14 iş günü, ortalama 09:02 (sapma 9 dk)", "Model bu saate kadar gelmiş olma olasılığını %93 buluyordu", "Dizin erişilebilir, tarama normal: sorun gönderen tarafta görünüyor"],
        oneri: "Gönderen tarafa (EFT / muhasebe) sorun. Dosya gelince öneri kendiliğinden kapanır.", guven: 0.87, kaynak: "model", surum: 14, zaman: t - 240, durum: "ACIK" },
      { id: 2, tur: "ILISKI", nesne: "Lojistik → Control-M Prod", baslik: "Lojistik dizini yanıt vermeyince Control-M devresi kesiliyor",
        metin: "Son 30 günde 'Lojistik yanıtsız' olayından sonraki 1–3 dk içinde 7 kez Control-M devresi kesildi. Bu yakınlıkta birlikte görülmeleri tesadüfe göre 9,4 kat sık.",
        kanit: ["Dikkat oranı 6,2×: model devre kesilmesini beklerken 'Lojistik yanıtsız' olayına sıklığının 6,2 katı bakıyor", "7 olayın 7'sinde aynı sıra; ters sıra hiç yok", "İki kaynağa da aynı ağ bölümünden erişiliyor"],
        oneri: "Ortak bir neden olabilir (ağ, DNS). Bu saatleri ağ ekibiyle paylaşın; ayrıntı İlişkiler sekmesinde.", guven: 0.74, kaynak: "model", surum: 14, zaman: t - 3600 * 2, durum: "ACIK" },
      { id: 3, tur: "OLAGANDISI", nesne: "\\\\ORNEK-SUNUCU-2\\gelen\\ik", baslik: "İK dizinine gece 03:12'de 46 dosya geldi",
        metin: "Bu dizine bu saatte daha önce hiç dosya gelmemişti; 46 dosya da aynı dakikada geldi.",
        kanit: ["Modelin bu olaya verdiği olasılık %0,3 (şaşırma puanı 8,1; olağanı 4'ün altı)", "Hepsi kurala uydu ve Control-M'e iletildi"],
        oneri: "Toplu yeniden gönderim olabilir; beklenmiyorsa gönderen tarafa sorun.", guven: 0.68, kaynak: "model", surum: 14, zaman: t - 3600 * 7, durum: "ACIK" },
      { id: 4, tur: "KURAL", nesne: "\\\\ORNEK-SUNUCU\\gelen\\lojistik", baslik: "Lojistik: 'SEVK_IZMIR_…' adları hiçbir kurala uymuyor",
        metin: "Son 3 günde 12 dosya 'kurala uymadı' olarak kaldı. Mevcut kural depo kodunu 3 harf bekliyor (SEVK_[A-Z]{3}_…).",
        kanit: ["Örnek: SEVK_IZMIR_20260929.csv, SEVK_IZMIR_20260930.csv", "Eşleşmeyenlerin hepsi aynı kalıpta"],
        oneri: "Regex: SEVK_(?P<depo>[A-Z]{3,5})_(?P<tarih>\\d{8})\\.csv (kural penceresinde canlı deneyin)", guven: null, kaynak: "kural", surum: null, zaman: t - 3600 * 20, durum: "ACIK" },
      { id: 5, tur: "BEKLENEN_GELMEDI", nesne: "\\\\ORNEK-SUNUCU\\gelen\\lojistik", baslik: "Lojistik: cuma SEVK_ANK dosyası gelmedi", metin: "Son 6 cumanın 6'sında 17:00'ye kadar gelmişti.",
        kanit: [], oneri: null, guven: 0.81, kaynak: "model", surum: 13, zaman: t - 3 * gun, durum: "FAYDALI", isaretleyen: "deniz" },
      { id: 6, tur: "OLAGANDISI", nesne: "\\\\ORNEK-SUNUCU\\gelen\\muhasebe", baslik: "Muhasebe: 09:00'da 3 kat fazla dosya", metin: "Ay sonu yoğunluğu.",
        kanit: [], oneri: null, guven: 0.55, kaynak: "model", surum: 12, zaman: t - 5 * gun, durum: "FAYDASIZ", isaretleyen: "operator1" },
    ];
    const gunluk = Array.from({ length: 14 }, (_, i) => { const d = new Date((t - (13 - i) * gun) * 1000); const hs = [0, 6].includes(d.getDay());
      return { gun: d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" }), sayi: Math.round((hs ? 520 : 2750) + prng(i + 40) * 600) }; });
    const A = {
      durum: { model_durumu: ezber ? "EZBERLIYOR" : "OGRENIYOR", egitiliyor: false, son_egitim: t - 720, surum: 14, sonraki_egitim_olay: 312, parametre: 98304,
        cihaz: "CPU · 1 iş parçacığı · düşük öncelik", son_tur_sn: 38, torch: true,
        dogrulama_aciklama: "Son %20'lik zaman dilimi eğitime hiç girmez (zamana göre ayrım, karıştırma yok)" },
      veri: { olay_sayisi: ezber ? 9120 : 38412, gun_sayisi: ezber ? 6 : 14, ilk_zaman: t - (ezber ? 6 : 14) * gun, son_zaman: t - 5, boyut_mb: ezber ? 2.3 : 9.6, model_mb: 4.2, saklama_gun: 90,
        asgari_olay: 2000, asgari_gun: 3, gunluk: ezber ? gunluk.slice(8) : gunluk,
        turler: [["Dosya geldi", 15210], ["İletildi", 15188], ["Yükleme başladı / bitti", 3120], ["Alarm açıldı / kapandı", 412], ["Yeniden denendi", 318], ["Lokale yazıldı", 97],
          ["Eşleşmedi", 41], ["Kaynak eşiği", 22], ["Dizin erişimi değişti", 18]].map(([ad, sayi]) => ({ ad, sayi: ezber ? Math.round(sayi * 0.24) : sayi })) },
      egitim: { adimlar, egitim_kaybi: egitim, dogrulama_kaybi: dogrulama, taban_markov: 1.62, taban_siklik: 2.31, en_iyi_adim: adimlar[enIyiI], en_iyi_surum: 14,
        ezber_baslangic: ezber ? 1500 : null,
        karar: ezber ? { baslik: "Sürüm 15 ezberledi: kullanılmadı, sürüm 14'e dönüldü.", maddeler: [
            `Adım 1 500'den sonra eğitim kaybı ${k2(egitim[15])} → ${k2(egitim[30])} düşerken doğrulama kaybı ${k2(dogrulama[enIyiI])} → ${k2(dogrulama[30])} yükseldi (kırmızı bölge).`,
            "Olası neden: yalnızca 6 günlük veri var; model gördüğü günleri tekrar ediyor, yeni günü tahmin edemiyor.",
            "Otomatik önlem: en iyi adımdaki sürüm korundu; sonraki turda dropout 0,1 → 0,2 ve erken durdurma 300 adım.",
            "Öneriler en iyi sürümle (14) sürüyor; güven puanı düşürüldü."] }
          : { baslik: "Model öğreniyor; ezber yok.", maddeler: [
            `Doğrulama kaybı ${k2(dogrulama[enIyiI])}: Markov tabanından (1,62) %23 düşük (%95 güven aralığı %18–%27).`,
            `Eğitim ile doğrulama arasındaki fark ${k2(dogrulama[30] - egitim[30])} ve son 10 değerlendirmede büyümüyor: ezber işareti yok.`,
            "Son 600 adımda doğrulama kaybı %0,4 iyileşti: öğrenme yavaşladı, yeni veriyle sürecek.",
            "Öneriler açık (gölge modu)."] },
        surumler: ezber ? [
            { surum: 15, zaman: t - 600, olay: 9120, egitim: egitim[30], dogrulama: dogrulama[30], markova_gore: dogrulama[30] / 1.62 - 1, durum: "EZBER" },
            { surum: 14, zaman: t - 3 * 3600, olay: 8610, egitim: egitim[enIyiI], dogrulama: dogrulama[enIyiI], markova_gore: dogrulama[enIyiI] / 1.62 - 1, durum: "KULLANIMDA" },
            { surum: 13, zaman: t - gun, olay: 7002, egitim: 1.12, dogrulama: 1.49, markova_gore: 1.49 / 1.62 - 1, durum: "ESKI" },
            { surum: 12, zaman: t - 2 * gun, olay: 4811, egitim: 1.31, dogrulama: 1.66, markova_gore: 1.66 / 1.62 - 1, durum: "ANLAMSIZ" }]
          : [{ surum: 14, zaman: t - 720, olay: 38412, egitim: egitim[30], dogrulama: dogrulama[enIyiI], markova_gore: dogrulama[enIyiI] / 1.62 - 1, durum: "KULLANIMDA" },
            { surum: 13, zaman: t - 5 * 3600, olay: 37910, egitim: 1.12, dogrulama: 1.27, markova_gore: 1.27 / 1.62 - 1, durum: "ESKI" },
            { surum: 12, zaman: t - gun, olay: 35200, egitim: 1.15, dogrulama: 1.29, markova_gore: 1.29 / 1.62 - 1, durum: "ESKI" },
            { surum: 11, zaman: t - 2.2 * gun, olay: 31022, egitim: 1.30, dogrulama: 1.52, markova_gore: 1.52 / 1.62 - 1, durum: "ESKI" },
            { surum: 10, zaman: t - 3 * gun, olay: 27411, egitim: 1.20, dogrulama: 1.66, markova_gore: 1.66 / 1.62 - 1, durum: "ANLAMSIZ" }] },
      guven: {
        karne: ezber ? { puan: 0.41, derece: "Düşük", ozet: "Model şu an güvenilir değil; önerileri yalnızca ipucu sayın.", olcutler: [
            { ad: "Tabanı geçiyor", aciklama: "En iyi sürüm Markov tabanından %15 iyi; son sürüm tabanın gerisinde", deger: "%15", durum: "orta", agirlik: 0.3 },
            { ad: "Ezber yok", aciklama: "Son sürüm ezberledi (fark 1,38 ve büyüyor)", deger: "1,38", durum: "kotu", agirlik: 0.2 },
            { ad: "Kalibrasyon", aciklama: "Söylediği güven ile gerçek isabet arasındaki ortalama fark", deger: "ECE %11,8", durum: "kotu", agirlik: 0.2 },
            { ad: "Veri yeterliliği", aciklama: "6 gün, 9 120 olay; haftalık düzen için 4 hafta önerilir", deger: "%21", durum: "kotu", agirlik: 0.15 },
            { ad: "Geri bildirim isabeti", aciklama: "Henüz yeterli geri bildirim yok", deger: "—", durum: "orta", agirlik: 0.15 }] }
          : { puan: 0.73, derece: "Orta-iyi", ozet: "Önerileri dikkate alın; önemli bir karardan önce kanıtına bakın.", olcutler: [
            { ad: "Tabanı geçiyor", aciklama: "Doğrulama kaybı Markov tabanından %23 düşük (güven aralığı %18–%27)", deger: "%23", durum: "iyi", agirlik: 0.3 },
            { ad: "Ezber yok", aciklama: "Eğitim–doğrulama farkı küçük ve büyümüyor", deger: k2(dogrulama[30] - egitim[30]), durum: "iyi", agirlik: 0.2 },
            { ad: "Kalibrasyon", aciklama: "Söylediği güven ile gerçek isabet arasındaki ortalama fark (iyi: %5 altı)", deger: "ECE %6,1", durum: "orta", agirlik: 0.2 },
            { ad: "Veri yeterliliği", aciklama: "14 gün, 38 412 olay; haftalık düzen için 4 hafta önerilir", deger: "%50", durum: "orta", agirlik: 0.15 },
            { ad: "Geri bildirim isabeti", aciklama: "9 öneriden 6'sı faydalı bulundu (az örnek)", deger: "%67", durum: "orta", agirlik: 0.15 }] },
        ece: ezber ? 0.118 : 0.061,
        guvenilirlik: [[0.06, 0.05, 410], [0.15, 0.13, 620], [0.25, 0.22, 700], [0.35, 0.31, 540], [0.45, 0.43, 460], [0.55, 0.49, 390], [0.65, 0.60, 350], [0.75, 0.70, 420], [0.85, 0.79, 510], [0.95, 0.90, 880]]
          .map(([tahmin, gercek, sayi], i) => ({ alt: i / 10, ust: (i + 1) / 10, tahmin, gercek: ezber ? gercek * 0.82 : gercek, sayi })),
        ornek_cumle: ezber ? "Model %90 emin olduğunda gerçekte %74 doğru çıkıyor: fazla kendinden emin (ezberin tipik işareti)."
          : "Model %80–90 emin olduğunda gerçekte %79 doğru çıkıyor: biraz fazla kendinden emin; öneri güvenleri buna göre düzeltilerek gösterilir.",
        basari: [{ ad: "İlk tahmin doğru (top-1)", aciklama: "sıradaki olayı ilk tahminde bilme", model: ezber ? "%44" : "%61", markov: "%48", siklik: "%22" },
          { ad: "İlk 3 tahminde (top-3)", aciklama: null, model: ezber ? "%70" : "%86", markov: "%74", siklik: "%51" },
          { ad: "Kayıp", aciklama: "düşük = daha iyi", model: k2(dogrulama[enIyiI]), markov: "1,62", siklik: "2,31" },
          { ad: "Zaman tahmini", aciklama: "sıradaki olayın ne zaman geleceği (±%25 içinde)", model: ezber ? "%39" : "%58", markov: "%41", siklik: "—" }],
        onceden: { gunler: Array.from({ length: 14 }, (_, i) => i + 1), model: Array.from({ length: 14 }, (_, i) => 0.33 + 0.28 * (1 - Math.exp(-i / 4)) + (prng(i + 90) - 0.5) * 0.04),
          markov: Array.from({ length: 14 }, (_, i) => 0.44 + 0.04 * (1 - Math.exp(-i / 3)) + (prng(i + 70) - 0.5) * 0.03) },
        geri_bildirim: { toplam: 9, oran: 6 / 9, turler: [{ tur: "BEKLENEN_GELMEDI", faydali: 4, faydasiz: 1 }, { tur: "ILISKI", faydali: 1, faydasiz: 1 },
          { tur: "OLAGANDISI", faydali: 0, faydasiz: 1 }, { tur: "KURAL", faydali: 1, faydasiz: 0 }] } },
      iliskiler: { turler, matris, liste: [
        { once: "Lojistik yanıtsız", sonra: "Control-M devre kesildi", aralik: "1–3 dk", dikkat: 6.2, lift: 9.4, birlikte: 7, uyumlu: true, sistem: false },
        { once: "Control-M devre kesildi", sonra: "Lokale yazıldı", aralik: "hemen (sistem kuralı)", sistem: true, dikkat: 5.5, lift: 31.0, birlikte: 23, uyumlu: true },
        { once: "Eşleşmedi · Lojistik", sonra: "Eşleşmedi · Lojistik", aralik: "aynı gün", dikkat: 4.4, lift: 6.8, birlikte: 12, uyumlu: true },
        { once: "Yükleme askıda · Lojistik", sonra: "Dosya geldi · Lojistik", aralik: "4–12 dk", dikkat: 3.3, lift: 5.2, birlikte: 18, uyumlu: true },
        { once: "Dosya geldi · Muhasebe", sonra: "Dosya geldi · İK", aralik: "25–40 dk", dikkat: 2.7, lift: 2.1, birlikte: 11, uyumlu: true },
        { once: "Lojistik yanıtsız", sonra: "Yeniden denendi", aralik: "< 1 dk", dikkat: 2.4, lift: 1.3, birlikte: 4, uyumlu: false }] },
      oneriler: ezber ? oneriler.filter(o => o.id !== 3) : [{ id: 90, zaman: t - 900, anahtar: "anomali:1:boyut:1", tur: "ANOMALI", nesne: "kural:1", durum: "ACIK", kaynak: "istatistik", guven: null, surum: null,
          baslik: "'fatura' kuralında alışılmadık küçük dosya", metin: "FATURA_20261001.csv 3,1 KB geldi; bu kuralın dosyaları genelde 1,2 MB – 1,8 MB arasında (medyan 1,5 MB). Yaklaşık 495,5 kat daha küçük.",
          kanit: ["Geçmiş: son 420 dosya (en çok 60 gün)", "Normal aralık (%5–%95): 1,2 MB – 1,8 MB", "Sağlam z = -38.2 (eşik ±4; log ölçeği, medyan / MAD)", "Dizin: \\\\ORNEK-SUNUCU\\gelen\\muhasebe"],
          oneri: "Dosyayı açıp kontrol edin: yarım / boş yükleme ya da yanlış dosya olabilir. Normalse 'Faydasız' işaretleyin." }, ...oneriler], guven_var: true,
      anomali: [
        { kural_id: 1, kural: "fatura", dizin: "\\\\ORNEK-SUNUCU\\gelen\\muhasebe", n: 420, yeterli: true, boyut_p5: 1.24e6, boyut_p95: 1.83e6, boyut_medyan: 1.52e6, son_boyut: 3170,
          sure_medyan: 640, sure_son: 710, gunluk_medyan: 31, dun: 30, bugun: 12, anomali: { boyut: true, sure: false, adet: false } },
        { kural_id: 3, kural: "sevkiyat", dizin: "\\\\ORNEK-SUNUCU\\gelen\\lojistik", n: 188, yeterli: true, boyut_p5: 42000, boyut_p95: 61000, boyut_medyan: 50500, son_boyut: 51800,
          sure_medyan: 820, sure_son: 4300, gunluk_medyan: 14, dun: 13, bugun: 6, anomali: { boyut: false, sure: true, adet: false } },
        { kural_id: 2, kural: "iade", dizin: "\\\\ORNEK-SUNUCU\\gelen\\muhasebe", n: 96, yeterli: true, boyut_p5: 2100, boyut_p95: 9800, boyut_medyan: 4200, son_boyut: 3900,
          sure_medyan: 590, sure_son: 610, gunluk_medyan: 7, dun: 2, bugun: 3, anomali: { boyut: false, sure: false, adet: true } },
        { kural_id: 4, kural: "bordro", dizin: "\\\\ORNEK-SUNUCU-2\\gelen\\ik", n: 6, yeterli: false, boyut_p5: 880000, boyut_p95: 910000, boyut_medyan: 900000, son_boyut: 902000,
          sure_medyan: 700, sure_son: 700, gunluk_medyan: null, dun: 0, bugun: 0, anomali: { boyut: false, sure: false, adet: false } }],
      ayarlar: { surekli: true, egitim_sikligi: 500, egitim_adimi: 200, baglam: 64, katman: 2, bas: 4, boyut: 64, ogrenme_orani: 0.001, dropout: 0.1, agirlik_azaltma: 0.01, is_parcacigi: 1,
        anomali: true, anomali_alarm: false, anomali_asgari: 20 },
      kendini_sina: { son: { zaman: t - gun, sonuc: "GECTI" } },
    };
    if (senaryo === "bos") Object.assign(A, {
      durum: { model_durumu: "VERI_TOPLANIYOR", egitiliyor: false, son_egitim: null, surum: null, sonraki_egitim_olay: null, parametre: 98304, cihaz: "CPU · 1 iş parçacığı · düşük öncelik", son_tur_sn: null },
      veri: { ...A.veri, olay_sayisi: 312, gun_sayisi: 0.4, ilk_zaman: t - 0.4 * gun, boyut_mb: 0.1, model_mb: 0, gunluk: gunluk.slice(13), turler: A.veri.turler.map(x => ({ ...x, sayi: Math.round(x.sayi / 123) })) },
      egitim: null, guven: null, guven_var: false, iliskiler: null, oneriler: [], kendini_sina: { son: null } });
    return A;
  })();
  const kendiniSinaSonucu = () => {
    const adimlar = Array.from({ length: 21 }, (_, i) => i * 50);
    return { sonuc: "GECTI", baslik: "Gömülen ilişkileri buldu; öğreniyor, ezberlemiyor.", maddeler: [
      "Doğrulama kaybı 0,94: Markov tabanından (1,31) %28 düşük.", "Ezber yok: eğitim–doğrulama farkı 0,06.",
      "Gömülen ilişki bulundu: 'Lojistik yanıtsız → Control-M devre kesildi' dikkat 0,71 (ilk sırada); ters yönde 0,04.",
      "Zaman düzeni bulundu: Muhasebe 09:00 gelişlerinde zaman tahmini hatası ±11 dk.", "Süre 52 sn · CPU 1 iş parçacığı · gerçek model ve veri etkilenmedi."],
      egri: { adimlar, egitim: adimlar.map((a, i) => 0.88 + 1.9 * Math.exp(-a / 180) + (prng(i + 300) - 0.5) * 0.04), dogrulama: adimlar.map((a, i) => 0.94 + 1.86 * Math.exp(-a / 200) + (prng(i + 330) - 0.5) * 0.04), markov: 1.31 } };
  };
  ROTALAR.push(
    ["GET", /^\/api\/asistan$/, () => AS],
    ["POST", /^\/api\/asistan\/egit$/, () => { yetki("YONETICI"); AS.durum.egitiliyor = true; denetim("ASISTAN_EGIT", "asistan");
      setTimeout(() => { AS.durum.egitiliyor = false; AS.durum.son_egitim = simdi(); }, 4000); }],
    ["POST", /^\/api\/asistan\/oneriler\/(\d+)\/geri_bildirim$/, (g_, q, id) => { yetki("OPERATOR"); const o = AS.oneriler.find(x => x.id === +id);
      o.durum = g_.faydali ? "FAYDALI" : "FAYDASIZ"; o.isaretleyen = P.ben.kullanici;
      const gb = AS.guven.geri_bildirim, tr = gb.turler.find(x => x.tur === o.tur) || (gb.turler.push({ tur: o.tur, faydali: 0, faydasiz: 0 }), gb.turler[gb.turler.length - 1]);
      tr[g_.faydali ? "faydali" : "faydasiz"]++; gb.toplam++; gb.oran = gb.turler.reduce((s, x) => s + x.faydali, 0) / gb.toplam; }],
    ["PUT", /^\/api\/asistan\/ayarlar$/, g_ => { yetki("YONETICI"); Object.assign(AS.ayarlar, g_); denetim("ASISTAN_AYAR", "asistan", g_); }],
    ["POST", /^\/api\/asistan\/surum\/(\d+)\/kullan$/, (g_, q, s) => { yetki("YONETICI"); for (const x of AS.egitim.surumler) x.durum = x.surum === +s ? "KULLANIMDA" : x.durum === "KULLANIMDA" ? "ESKI" : x.durum;
      AS.durum.surum = +s; denetim("ASISTAN_SURUM", `sürüm ${s}`); }],
    ["POST", /^\/api\/asistan\/sifirla$/, () => { yetki("YONETICI"); denetim("ASISTAN_SIFIRLA", "asistan"); }],
    ["POST", /^\/api\/asistan\/veri_sil$/, () => { yetki("YONETICI"); denetim("ASISTAN_VERI_SIL", "asistan"); }],
    ["POST", /^\/api\/asistan\/kendini_sina$/, () => { yetki("OPERATOR"); AS.kendini_sina.son = { zaman: simdi(), sonuc: "GECTI" }; return kendiniSinaSonucu(); }],
  );

  window.PROTOTIP = {
    async istek(yontem, yol, govde) {
      await bekle(rnd(60, 220));
      const [p, qs] = yol.split("?"); const q = new URLSearchParams(qs || "");
      for (const [y, desen, fn] of ROTALAR) {
        if (y !== yontem) continue;
        const m = p.match(desen);
        if (m) { try { const r = fn(govde || {}, q, ...m.slice(1)); return kopya(r === undefined ? { tamam: true } : r); } catch (e) { throw new ApiHata(e.kod || 500, e.message); } }
      }
      throw new ApiHata(404, `prototipte tanımsız: ${yontem} ${yol}`);
    },
    akis(cb) { const z = setInterval(() => { adim(); cb(kopya(durum())); }, 1000); return { close: () => clearInterval(z) }; },
  };


  // ---------------------------------------------------------------- ekran görüntüsü parametreleri (yalnız prototip)
  //  ?prototip&tema=koyu&senaryo=kriz&pencere=durdur|erit|kural|dosya|kayitsiz#/sayfa
  const Q = new URLSearchParams(location.search);
  if (Q.get("tema")) { try { localStorage.setItem("fwp_tema", Q.get("tema")); } catch (_) {} temaUygula(Q.get("tema")); }
  if (Q.get("senaryo") === "kriz") {
    P.cokuk = true; P.dizinDustu = true;
    for (kaydir = -30; kaydir < 0; kaydir += 1) adim();
    kaydir = 0;
  }
  if (Q.get("pencere")) {
    const ac = async () => {
      if (typeof D === "undefined" || !D.durum || !document.querySelector("#icerik")) return setTimeout(ac, 200);
      await new Promise(r => setTimeout(r, 1200));
      const hedefler = D.durum.hedefler;
      const p = Q.get("pencere");
      if (p === "durdur" || p === "kayitsiz") {
        kapatPenceresi(null);
        if (p === "kayitsiz") setTimeout(() => document.querySelectorAll(".perde .secim-kart")[1].click(), 100);
      }
      if (p === "erit") { await API.post("/api/toptan_ac"); await new Promise(r => setTimeout(r, 1100)); eritPenceresi(D.durum.hedefler[0]); }
      if (p === "kural" || p === "kural_deneme") {
        location.hash = "#/dizinler"; await new Promise(r => setTimeout(r, 700));
        await kuralPenceresi(P.dizinler[0], p === "kural_deneme" ? kural(1) : null);
        if (p === "kural") { const r = document.getElementById("kural_regex"); r.value = "FATURA_(?P<tarih>\\d{8})\\.csv"; r.dispatchEvent(new Event("input"));
          document.querySelector(".perde input[placeholder='örn. fatura']").value = "fatura"; document.querySelector(".perde details.yardim").open = true; }
        else { await new Promise(r => setTimeout(r, 900)); [...document.querySelectorAll(".perde button")].find(b => b.textContent.includes("Kuru deneme")).click(); }
      }
      if (p === "bildirim") { location.hash = "#/bildirimler"; await new Promise(r => setTimeout(r, 900)); bildirimKuralPenceresi(await API.get("/api/olay_katalogu"), P.bildirim.kurallar[1]); }
      if (p === "smtp") { location.hash = "#/bildirimler"; await new Promise(r => setTimeout(r, 900)); smtpPenceresi(P.bildirim.smtp); }
      if (p === "hedef_tur") { location.hash = "#/hedefler"; await new Promise(r => setTimeout(r, 700)); await hedefPenceresi(); }
      if (p === "hedef_api") { location.hash = "#/hedefler"; await new Promise(r => setTimeout(r, 700)); apiPenceresi(null);
        await new Promise(r => setTimeout(r, 300)); const pi = document.querySelector(".perde .pi"); pi.querySelector("input[placeholder='örn. Raporlama API']").value = "Raporlama API";
        pi.querySelector("input[placeholder='https://api.sirket.local/v1']").value = "https://rapor.sirket.local/api/v1"; }
      if (p === "betik_kilitli") { location.hash = "#/hedefler"; await new Promise(r => setTimeout(r, 700)); betikPenceresi(null); }
      if (p === "betik" || p === "betik_test" || p === "betik_ps") {
        P.betik.bitis = simdi() + 600; location.hash = "#/hedefler"; await new Promise(r => setTimeout(r, 700));
        betikPenceresi(p === "betik_ps" ? null : hedef(3)); await new Promise(r => setTimeout(r, 500));
        if (p === "betik_ps") { const o = BETIK_ORNEKLERI[3]; const ta = document.getElementById("betik_kod"); document.getElementById("betik_dil").value = o.dil;
          ta.value = o.kod.replace("curl.exe -sS", "curl -sS").replace(' -w "`n%{http_code}"', ""); ta.dispatchEvent(new Event("input")); document.querySelector(".perde details.yardim").open = true; }
        if (p === "betik_test") { const b = [...document.querySelectorAll(".perde button")].find(x => x.textContent.includes("Canlı çalıştır")); b.click();
          await new Promise(r => setTimeout(r, 300)); const ps = [...document.querySelectorAll(".perde")].pop(); ps.querySelector("input[type=checkbox]").click();
          [...ps.querySelectorAll("button")].find(x => x.textContent === "Çalıştır").click(); await new Promise(r => setTimeout(r, 900));
          document.querySelector(".perde .pi").scrollTop = 99999; }
      }
      if (p === "kural_betik") {
        P.betik.bitis = simdi() + 600; location.hash = "#/dizinler"; await new Promise(r => setTimeout(r, 700));
        await kuralPenceresi(P.dizinler[0], null); await new Promise(r => setTimeout(r, 300));
        const r = document.getElementById("kural_regex"); r.value = "FATURA_(?P<tarih>\\d{8})\\.csv"; r.dispatchEvent(new Event("input"));
        document.querySelector(".perde input[placeholder='örn. fatura']").value = "fatura_betik";
        const sec = [...document.querySelectorAll(".perde select")].find(x => [...x.options].some(o => o.textContent === "Fatura aktarım betiği"));
        sec.value = "3"; sec.dispatchEvent(new Event("change")); document.getElementById("kural_betik_param").value = "OLAY=FATURA_GELDI\nDONEM={tarih}";
        await new Promise(r => setTimeout(r, 900)); [...document.querySelectorAll(".perde button")].find(b => b.textContent.includes("Kuru deneme")).click();
        await new Promise(r => setTimeout(r, 600)); document.querySelector(".perde .pi").scrollTop = 99999;
      }
      if (p === "dosya") { const r = (await API.get("/api/dosyalar")).find(x => x.tetik_durum === "ILETILDI"); dosyaCekmecesi(r); }
    };
    ac();
  }
  // ---------------------------------------------------------------- senaryo şeridi
  function serit() {
    const el = document.createElement("div"); el.className = "prototip-serit";
    const dugme = (metin, fn) => { const b = document.createElement("button"); b.textContent = metin; b.onclick = () => { fn(); ciz(); }; return b; };
    function ciz() {
      el.replaceChildren();
      el.append("PROTOTİP · ÖRNEK VERİ (gerçek klasör ya da dosya yok, hiçbir şey diske yazılmıyor) ·");
      el.append(dugme(P.cokuk ? "Control-M'i düzelt" : "Control-M'i çökert", () => { P.cokuk = !P.cokuk; }));
      el.append(dugme(P.dizinDustu ? "Lojistik dizinini geri getir" : "Lojistik dizinini düşür", () => { P.dizinDustu = !P.dizinDustu; }));
      el.append(dugme("Tarama eklentisini çökert", () => { P.eklentiCokuk = true; }));
      const s = document.createElement("select"); s.style.cssText = "border:0;border-radius:99px;padding:3px 8px;font-weight:600;color:#3b0764;background:#fff";
      for (const r of ["IZLEYICI", "OPERATOR", "YONETICI"]) { const o = document.createElement("option"); o.value = r; o.textContent = `Rol: ${{ IZLEYICI: "İzleyici", OPERATOR: "Operatör", YONETICI: "Yönetici" }[r]}`; o.selected = P.ben.rol === r; s.appendChild(o); }
      s.onchange = () => { P.ben.rol = s.value; D.ben.rol = s.value; iskeletCiz(); rotaDegisti(); ustCiz(); document.body.appendChild(el); };
      el.append(s);
    }
    ciz(); document.body.appendChild(el);
  }
  if (Q.get("serit") !== "0") { if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", serit); else serit(); }
})();
