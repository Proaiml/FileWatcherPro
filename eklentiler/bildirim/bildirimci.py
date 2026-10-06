"""Bildirim eklentisi (Bildirimler sayfası; kullanıcı isteği 2026-09-30).

Olay kaynakları (kaldığı yerden okunur; ilk açılışta geçmiş maillenmez):
  * alarm açıldı / düzeldi (canli.db > alarm)          → tür: cekirdek/olaylar.alarm_turu
  * gönderilemeyen dosya (hata.db > gonderilemeyen)     → tür: cekirdek/olaylar.sebep_turu
  * SLA aşımı ve olası çift çağrı (canli.db > tetik)
Bir olay, bildirim kuralında seçilmişse, seviyesi yeterliyse ve (dizine bağlı olaylarda) dizin kapsamdaysa kurala uyar.
  * Anında kurallar: olay başına tek mail; aynı olaya uyan anında kuralların alıcıları birleşir (her alıcı bir kez alır).
  * Özet kurallar: 'ozet_dk' içinde biriken olaylar tek mailde.
  * Tekrar sınırı: aynı olay (alarm) sürerken en fazla 'tekrar_dk'da bir hatırlatılır.
  * Düzelince: alarm kapanınca, daha önce maillenmişse 'DÜZELDİ' maili.
  * Mail yağmuru koruması: bir anında kural 10 dk'da 10'dan çok mail ürettiyse geçici olarak 5 dk'lık özete geçer.
  * Kural eklendiğinde zaten açık olan alarmlar da (bir kez) bildirilir.
Gönderim: SMTP ayarı yoksa ya da kapalıysa mail üretilmez. Başarısız mail 30 sn, 2, 5, 15, 30 dk sonra yeniden denenir;
sonra HATA + 'Mail gönderilemiyor' alarmı (bu alarm maille bildirilmez). Bu eklenti düşerse izleme ve teslim etkilenmez.
"""
import json
import time

from loguru import logger

from cekirdek import eposta, loglama
from cekirdek.eklenti_temel import Eklenti
from cekirdek.model import AlarmSeviye
from cekirdek.olaylar import KODLAR, MAILE_GITMEZ, SEVIYE_SIRA, alarm_turu, sebep_turu

TASMA_PENCERE_SN = 600          # taşma: bu pencerede 'bildirim_tasma_esigi'nden çok mail → geçici özet
HATIRLAT_ARALIK_SN = 30
SEVIYE_ADI = {"KRITIK": "KRİTİK", "UYARI": "UYARI", "BILGI": "BİLGİ"}
SEBEP_METNI = {"SLA_SON_DOLDU": "deneme planı bitti (Control-M yanıt vermedi)", "KALICI_HATA": "kalıcı hata (istek reddedildi)",
               "DEVRE_KESIK": "devre kesikti", "HEDEF_KAPALI_KAYITLI": "hedef kayıtlı kapalıydı",
               "KURAL_KAPALI_KAYITLI": "kural kayıtlı kapalıydı", "HEDEF_KAPALI_KAYITSIZ": "hedef kayıtsız kapalıydı",
               "KURAL_KAPALI_KAYITSIZ": "kural kayıtsız kapalıydı", "ESLESMEDI": "hiçbir kurala uymadı",
               "LOKAL_KAYIT_BOZUK": "lokal kayıt bozuk"}


def _saat(z):
    return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(z))


class Bildirimci(Eklenti):
    AD = "bildirim"

    def __init__(self):
        super().__init__()
        self.son_hatirlatma = 0.0
        self.son_budama = 0.0
        self.gonderilen = 0

    def bilgi(self) -> dict:
        return {"gonderilen": self.gonderilen}

    def calis(self):
        self.iz = self._izleri_yukle()
        while not self.durmali():
            self.ilerle()
            self.ayar.tazele()
            try:
                self._tur()
            except Exception:
                logger.exception("bildirim turunda hata (sonraki turda devam)")
            self.bekle(2.0)

    # ------------------------------------------------------------ tur
    def _tur(self):
        smtp = json.loads(self.db.meta_al("smtp") or "null")
        etkin = bool(smtp and smtp.get("aktif") and smtp.get("sunucu"))
        kurallar = [self._kural(r) for r in self.db.oku("SELECT * FROM bildirim_kural WHERE aktif=1")]
        self._sozlukler()
        olaylar = self._yeni_olaylar()                       # izler her durumda ilerler (geçmiş birikmesin)
        if etkin and kurallar:
            for ev in olaylar:
                self._dagit(ev, kurallar)
            if time.time() - self.son_hatirlatma >= HATIRLAT_ARALIK_SN:
                self.son_hatirlatma = time.time()
                self._hatirlat(kurallar)
            self._ozetleri_hazirla(kurallar)
        if etkin:
            self._gonder(smtp)
        if time.time() - self.son_budama > 600:
            self.son_budama = time.time()
            self._buda()

    @staticmethod
    def _kural(r) -> dict:
        k = dict(r)
        k["alicilar"] = json.loads(k["alicilar"] or "[]")
        k["olaylar"] = set(json.loads(k["olaylar"] or "[]"))
        k["dizinler"] = None if k["dizinler"] is None else set(json.loads(k["dizinler"]))
        k["kurallar"] = None if k.get("kurallar") is None else set(json.loads(k["kurallar"]))
        return k

    def _sozlukler(self):
        self.dizin_yol = {r["id"]: r["yol"] for r in self.db.oku("SELECT id, yol FROM dizin")}
        self.yol_dizin = {v.casefold(): k for k, v in self.dizin_yol.items()}
        self.hedef_ad = {r["id"]: r["ad"] for r in self.db.oku("SELECT id, ad FROM hedef")}
        self.kural_dizin = {r["id"]: (r["dizin_id"], r["ad"]) for r in self.db.oku("SELECT id, dizin_id, ad FROM kural")}

    # ------------------------------------------------------------ olay toplama
    def _izleri_yukle(self) -> dict:
        iz = json.loads(self.db.meta_al("bildirim_iz") or "null")
        if iz:
            return iz
        iz = {"alarm_id": self.db.tek("SELECT COALESCE(MAX(id),0) FROM alarm")[0],
              "kapanma": self.db.tek("SELECT COALESCE(MAX(kapanma_zamani),0) FROM alarm")[0] or time.time(),
              "gon_id": self.hdb.tek("SELECT COALESCE(MAX(id),0) FROM gonderilemeyen")[0],
              "tetik_zaman": time.time()}
        self.db.meta_yaz("bildirim_iz", json.dumps(iz))
        return iz

    def _alarm_olayi(self, a, tur) -> dict:
        kod, ids = alarm_turu(a["anahtar"])
        dizin = ids.get("dizin")
        if "kural" in ids and ids["kural"] in self.kural_dizin:
            dizin = self.kural_dizin[ids["kural"]][0]
        kural = ids.get("kural")
        nesne = self.dizin_yol.get(dizin) if dizin else self.hedef_ad.get(ids.get("hedef")) if ids.get("hedef") else None
        onaylayan = f" (onaylayan: {a['onaylayan']})" if a["onaylayan"] else ""
        return {"anahtar": a["anahtar"], "kod": kod, "seviye": a["seviye"], "tur": tur, "dizin": dizin, "nesne": nesne,
                "kural": kural,
                "metin": a["mesaj"] if tur != "DUZELDI" else f"Düzeldi{onaylayan}. Önceki durum: {a['mesaj']}",
                "zaman": (a["kapanma_zamani"] if tur == "DUZELDI" else a["son_zaman"]) or time.time()}

    def _yeni_olaylar(self) -> list:
        iz, olaylar = self.iz, []
        for a in self.db.oku("SELECT * FROM alarm WHERE id > ? ORDER BY id", (iz["alarm_id"],)):
            olaylar.append(self._alarm_olayi(a, "ACILDI"))
            iz["alarm_id"] = a["id"]
        for a in self.db.oku("SELECT * FROM alarm WHERE aktif=0 AND kapanma_zamani > ? ORDER BY kapanma_zamani",
                             (iz["kapanma"],)):
            olaylar.append(self._alarm_olayi(a, "DUZELDI"))
            iz["kapanma"] = a["kapanma_zamani"]
        for g in self.hdb.oku("SELECT * FROM gonderilemeyen WHERE id > ? ORDER BY id", (iz["gon_id"],)):
            kod = sebep_turu(g["sebep"])
            dizin = self.yol_dizin.get(str(g["dizin_yolu"] or "").casefold())
            t = self.db.tek("SELECT kural_id FROM tetik WHERE id=?", (g["tetik_id"],)) if g["tetik_id"] else None
            kural = t[0] if t else None
            kural_ad = g["kural_ad"] or (self.kural_dizin.get(kural) or (None, None))[1]
            olaylar.append({"anahtar": f"gon:{g['id']}", "kod": kod, "seviye": KODLAR[kod]["seviye"], "tur": "ACILDI",
                            "dizin": dizin, "nesne": g["dizin_yolu"] or g["hedef_ad"], "kural": kural,
                            "metin": f"{g['dosya_adi']}: {SEBEP_METNI.get(g['sebep'], g['sebep'])}"
                                     f"{' · ' + g['sebep_detay'] if g['sebep_detay'] else ''}"
                                     f"{' · kural: ' + kural_ad if kural_ad else ''}"
                                     f"{' · hedef: ' + g['hedef_ad'] if g['hedef_ad'] else ''}", "zaman": g["ilk_zaman"]})
            iz["gon_id"] = g["id"]
        for t in self.db.oku("SELECT t.*, d.dizin_id FROM tetik t LEFT JOIN dosya d ON d.id=t.dosya_id "
                             "WHERE t.iletildi_zamani > ? AND (t.sla_ihlali=1 OR t.belirsiz=1) ORDER BY t.iletildi_zamani",
                             (iz["tetik_zaman"],)):
            if t["sla_ihlali"]:
                olaylar.append({"anahtar": f"sla:{t['id']}", "kod": "DOSYA_SLA", "seviye": "BILGI", "tur": "ACILDI",
                                "dizin": t["dizin_id"], "kural": t["kural_id"], "nesne": self.dizin_yol.get(t["dizin_id"]), "zaman": t["iletildi_zamani"],
                                "metin": f"{t['dosya_adi']}: hazır olduktan {t['sure_ms'] / 1000:.1f} sn sonra iletildi (SLA hedefi aşıldı)."})
            if t["belirsiz"]:
                olaylar.append({"anahtar": f"cift:{t['id']}", "kod": "DOSYA_OLASI_CIFT", "seviye": "UYARI", "tur": "ACILDI",
                                "dizin": t["dizin_id"], "kural": t["kural_id"], "nesne": self.dizin_yol.get(t["dizin_id"]), "zaman": t["iletildi_zamani"],
                                "metin": f"{t['dosya_adi']}: cevap gelmeden bağlantı koptu; Control-M işi iki kez başlatmış olabilir "
                                         f"(kimlik: {t['idempotency']})."})
            iz["tetik_zaman"] = t["iletildi_zamani"]
        self.db.meta_yaz("bildirim_iz", json.dumps(iz))
        return olaylar

    # ------------------------------------------------------------ kurallar
    @staticmethod
    def _uyar(k, ev) -> bool:
        if not (ev["kod"] in k["olaylar"] and ev["kod"] not in MAILE_GITMEZ
                and SEVIYE_SIRA.get(ev["seviye"], 1) >= SEVIYE_SIRA.get(k["seviye"], 1)):
            return False
        if k.get("kurallar") is not None:
            # kural penceresinden bağlanan alıcılar: o kuralın olayları + kuralın dizinindeki kurala bağlı olmayan
            # dizin olayları (ör. hiçbir regex'e uymayan dosya, dizine erişilemiyor); sistem / hedef olayları gelmez
            if ev.get("kural") is not None:
                return ev["kural"] in k["kurallar"]
            return ev["dizin"] is not None and bool(k["dizinler"]) and ev["dizin"] in k["dizinler"]
        return k["dizinler"] is None or ev["dizin"] is None or ev["dizin"] in k["dizinler"]

    def _son_bildirim(self, kural_id, anahtar):
        """Bu kural bu olayı en son ne zaman bildirdi (açıldı/sürüyor) ve son bildirimin türü (DUZELDI ise sorun kapanmıştı)."""
        r = self.db.tek("SELECT zaman, tur FROM bildirim_olay WHERE kural_id=? AND olay_anahtar=? ORDER BY id DESC LIMIT 1",
                        (kural_id, anahtar))
        if r is None:
            return None, None
        acik = self.db.tek("SELECT MAX(zaman) FROM bildirim_olay WHERE kural_id=? AND olay_anahtar=? AND tur IN ('ACILDI','SURUYOR')",
                           (kural_id, anahtar))[0]
        return acik, r["tur"]

    def _tasiyor(self, kural_id) -> bool:
        return self.db.tek("SELECT COUNT(DISTINCT mail_id) FROM bildirim_olay WHERE kural_id=? AND mail_id IS NOT NULL "
                           "AND zaman > ?", (kural_id, time.time() - TASMA_PENCERE_SN))[0] >= int(self.ayar.al("bildirim_tasma_esigi"))

    def _dagit(self, ev, kurallar):
        simdi = time.time()
        anlik = []
        for k in kurallar:
            if not self._uyar(k, ev):
                continue
            son, son_tur = self._son_bildirim(k["id"], ev["anahtar"])
            if ev["tur"] == "DUZELDI":
                if not k["duzelince"] or son is None or son_tur == "DUZELDI":
                    continue                                        # açılışı bildirilmemiş olay için 'düzeldi' yok
            elif son is not None and son_tur != "DUZELDI" and simdi - son < k["tekrar_dk"] * 60:
                continue                                            # tekrar sınırı (düzelip yeniden açılan her zaman gider)
            baslik = self._baslik(ev)
            with self.db.yaz() as con:
                olay_id = con.execute("INSERT INTO bildirim_olay(zaman, kural_id, olay_anahtar, kod, seviye, tur, baslik, metin) "
                                      "VALUES(?,?,?,?,?,?,?,?)", (simdi, k["id"], ev["anahtar"], ev["kod"], ev["seviye"],
                                                                  ev["tur"], baslik, self._metin(ev))).lastrowid
            if not k["ozet_dk"] and not self._tasiyor(k["id"]):
                anlik.append((k, olay_id))
        if anlik:
            alicilar = list(dict.fromkeys(a for k, _ in anlik for a in k["alicilar"]))
            adlar = ", ".join(k["ad"] for k, _ in anlik)
            govde = self._metin(ev) + f"\n\nBu mail şu bildirim kuralıyla gönderildi: {adlar}."
            self._kuyruga(adlar, alicilar, self._baslik(ev), govde, [i for _, i in anlik], 1)

    def _hatirlat(self, kurallar):
        """Açık alarmlar: kural eklendiğinde zaten açık olanlar bir kez; sürenler 'tekrar_dk'da bir hatırlatılır."""
        simdi = time.time()
        for a in self.db.oku("SELECT * FROM alarm WHERE aktif=1"):
            ev = self._alarm_olayi(a, "SURUYOR")
            for k in kurallar:
                if not self._uyar(k, ev):
                    continue
                son, son_tur = self._son_bildirim(k["id"], ev["anahtar"])
                if son is None or son_tur == "DUZELDI":
                    if a["ilk_zaman"] > (son or 0):
                        self._dagit({**ev, "tur": "ACILDI"}, [k])
                elif simdi - son >= k["tekrar_dk"] * 60:
                    self._dagit({**ev, "metin": f"Sürüyor (ilk: {_saat(a['ilk_zaman'])}, {a['tekrar']} kez). {a['mesaj']}"}, [k])

    def _ozetleri_hazirla(self, kurallar):
        simdi = time.time()
        for k in kurallar:
            bekleyen = self.db.oku("SELECT * FROM bildirim_olay WHERE kural_id=? AND mail_id IS NULL ORDER BY zaman", (k["id"],))
            if not bekleyen:
                continue
            aralik = k["ozet_dk"] * 60 if k["ozet_dk"] else float(self.ayar.al("bildirim_tasma_ozet_dk")) * 60
            if simdi - bekleyen[0]["zaman"] < aralik:
                continue
            satirlar = [f"• {time.strftime('%H:%M:%S', time.localtime(o['zaman']))}  {SEVIYE_ADI.get(o['seviye'], o['seviye'])}  "
                        f"{o['baslik'].replace('[FileWatcherPro] ', '')}\n  {o['metin'].splitlines()[0]}" for o in bekleyen]
            neden = "" if k["ozet_dk"] else " Kısa sürede çok olay olduğu için anında mailler geçici olarak özetlendi."
            govde = (f"{len(bekleyen)} olay ({_saat(bekleyen[0]['zaman'])} – {_saat(bekleyen[-1]['zaman'])}):\n\n" +
                     "\n".join(satirlar) + f"\n\n{self._onyuz()}\nBu mail '{k['ad']}' bildirim kuralıyla gönderildi.{neden}")
            self._kuyruga(k["ad"], k["alicilar"], f"[FileWatcherPro] Özet: {len(bekleyen)} olay ({k['ad']})", govde,
                          [o["id"] for o in bekleyen], len(bekleyen))

    def _kuyruga(self, kural_ad, alicilar, konu, govde, olay_idleri, olay_sayisi):
        with self.db.yaz() as con:
            mid = con.execute("INSERT INTO bildirim_mail(zaman, kural_ad, alicilar, konu, govde, olay_sayisi, sonraki_deneme) "
                              "VALUES(?,?,?,?,?,?,?)", (time.time(), kural_ad, json.dumps(alicilar), konu, govde, olay_sayisi,
                                                        time.time())).lastrowid
            con.executemany("UPDATE bildirim_olay SET mail_id=? WHERE id=?", [(mid, i) for i in olay_idleri])

    # ------------------------------------------------------------ metin
    @staticmethod
    def _baslik(ev) -> str:
        k = KODLAR.get(ev["kod"], {"ad": ev["kod"]})
        on = "DÜZELDİ" if ev["tur"] == "DUZELDI" else SEVIYE_ADI.get(ev["seviye"], ev["seviye"])
        return f"[FileWatcherPro] {on}: {k['ad']}" + (f" ({ev['nesne']})" if ev.get("nesne") else "")

    def _onyuz(self) -> str:
        return f"Önyüz (sunucuda): http://{self.b.kontrol_adres}:{self.b.kontrol_port}/#/alarmlar"

    def _metin(self, ev) -> str:
        k = KODLAR.get(ev["kod"], {"ad": ev["kod"], "oneri": ""})
        satirlar = [ev["metin"], "", f"Tür: {k['ad']} · Seviye: {SEVIYE_ADI.get(ev['seviye'], ev['seviye'])} · "
                                     f"Zaman: {_saat(ev['zaman'])}"]
        if ev.get("nesne"):
            satirlar.append(f"İlgili: {ev['nesne']}")
        if ev["tur"] != "DUZELDI" and k.get("oneri"):
            satirlar.append(f"Ne yapmalı: {k['oneri']}")
        satirlar += ["", self._onyuz()]
        return "\n".join(satirlar)

    # ------------------------------------------------------------ gönderim
    def _gonder(self, smtp):
        simdi = time.time()
        for m in self.db.oku("SELECT * FROM bildirim_mail WHERE durum='BEKLIYOR' AND sonraki_deneme <= ? ORDER BY id LIMIT 20",
                             (simdi,)):
            try:
                reddedilen = eposta.gonder(smtp, json.loads(m["alicilar"]), m["konu"], m["govde"])
            except eposta.EpostaHatasi as e:
                plan = self.ayar.plan("bildirim_deneme_plani")
                deneme = m["deneme"] + 1
                son = deneme > len(plan)
                self.db.calistir("UPDATE bildirim_mail SET deneme=?, durum=?, sonraki_deneme=?, hata=? WHERE id=?",
                                 (deneme, "HATA" if son else "BEKLIYOR",
                                  None if son else time.time() + plan[deneme - 1], str(e)[:500], m["id"]))
                self.db.meta_yaz("bildirim_son_durum", json.dumps({"zaman": time.time(), "basarili": False, "mesaj": str(e)[:300]}))
                if son:
                    self.db.alarm_ac("bildirim:gonderilemiyor", f"Bildirim maili {deneme} denemede gönderilemedi "
                                     f"('{m['konu']}'): {e}. Bildirimler sayfasında SMTP ayarını deneyin.",
                                     AlarmSeviye.UYARI, "bildirim")
                logger.warning(f"mail gönderilemedi (deneme {deneme}): {e}")
                break                                            # sunucu sorunluysa kuyruğu bu turda zorlamayalım
            self.gonderilen += 1
            self.db.calistir("UPDATE bildirim_mail SET durum='GONDERILDI', gonderim_zamani=?, deneme=deneme+1, hata=? WHERE id=?",
                             (time.time(), f"reddedilen alıcı: {', '.join(reddedilen)}" if reddedilen else None, m["id"]))
            self.db.meta_yaz("bildirim_son_durum", json.dumps({"zaman": time.time(), "basarili": True, "mesaj": ""}))
            self.db.alarm_kapat("bildirim:gonderilemiyor")
            loglama.olay("MAIL_GONDERILDI", konu=m["konu"], alici=len(json.loads(m["alicilar"])))

    def _buda(self):
        with self.db.yaz() as con:
            con.execute("DELETE FROM bildirim_mail WHERE durum<>'BEKLIYOR' AND id NOT IN (SELECT id FROM bildirim_mail "
                        "WHERE durum<>'BEKLIYOR' ORDER BY id DESC LIMIT 500)")
            con.execute("DELETE FROM bildirim_olay WHERE mail_id IS NOT NULL AND zaman < ?", (time.time() - 30 * 86400,))


if __name__ == "__main__":
    Bildirimci.baslat()
