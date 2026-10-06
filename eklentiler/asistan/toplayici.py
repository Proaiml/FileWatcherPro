"""Olay toplama (PyTorch gerektirmez): canli.db ve hata.db'deki durum değişikliklerini asistan.db > olay'a yazar.

canli.db geçmişi 200 kayıtla budandığı için asistan olayları sürekli (her turda) toplar. Her olayın bir 'kaynak'
anahtarı vardır (ör. tetik:12:iletildi); aynı olay iki kez yazılmaz, bu yüzden okuma pencereleri biraz geriden
(güvenlik payıyla) başlar. Toplananlar: dosya geldi (tetik oluştu), iletildi / eritildi, yeniden denendi,
gönderilemeyen (lokale yazıldı, eşleşmedi, kayıtsız kapalı), alarm açıldı / kapandı (olay kataloğundaki türüyle).
Dosya içerikleri ve dosya adları toplanmaz; yalnızca olay türü, dizin / hedef kimliği, zaman, seviye.
"""
import json
import time

from cekirdek.olaylar import alarm_turu

PAY_SN = 120.0            # zaman damgalı okumalarda güvenlik payı (aynı saniyedeki yazımlar kaçmasın)


class Toplayici:
    def __init__(self, db, hdb, adb):
        self.db, self.hdb, self.adb = db, hdb, adb
        self.iz = json.loads(adb.meta_al("toplama_iz") or "{}")

    def _dizin_yolu_haritasi(self) -> dict:
        return {str(r["yol"]).lower(): r["id"] for r in self.db.oku("SELECT id, yol FROM dizin")}

    def topla(self) -> int:
        """Yeni olayları yazar; yazılan olay sayısını döner."""
        iz = self.iz
        olaylar = []                                   # (zaman, kod, nesne, seviye, kaynak)
        son_tetik = iz.get("tetik_id", 0)
        for r in self.db.oku("SELECT t.id, t.olusturma, t.hedef_id, k.dizin_id FROM tetik t LEFT JOIN kural k ON k.id=t.kural_id "
                             "WHERE t.id > ? ORDER BY t.id LIMIT 20000", (son_tetik,)):
            olaylar.append((r["olusturma"], "DOSYA_GELDI", f"dizin:{r['dizin_id']}" if r["dizin_id"] else "", None, f"tetik:{r['id']}:geldi"))
            son_tetik = max(son_tetik, r["id"])
        iz["tetik_id"] = son_tetik
        esik = iz.get("iletildi_zaman", 0.0) - PAY_SN
        en = iz.get("iletildi_zaman", 0.0)
        for r in self.db.oku("SELECT id, iletildi_zamani, hedef_id, eritildi FROM tetik WHERE iletildi_zamani > ? ORDER BY iletildi_zamani",
                             (esik,)):
            olaylar.append((r["iletildi_zamani"], "ERITILDI" if r["eritildi"] else "ILETILDI", f"hedef:{r['hedef_id']}", None, f"tetik:{r['id']}:iletildi"))
            en = max(en, r["iletildi_zamani"])
        iz["iletildi_zaman"] = en
        esik = iz.get("deneme_zaman", 0.0) - PAY_SN
        en = iz.get("deneme_zaman", 0.0)
        for r in self.db.oku("SELECT id, son_deneme, deneme_sayisi, hedef_id FROM tetik WHERE son_deneme > ? AND deneme_sayisi > 1",
                             (esik,)):
            olaylar.append((r["son_deneme"], "YENIDEN_DENENDI", f"hedef:{r['hedef_id']}", None, f"tetik:{r['id']}:deneme:{r['deneme_sayisi']}"))
            en = max(en, r["son_deneme"])
        iz["deneme_zaman"] = en
        yollar = None
        son_gon = iz.get("gon_id", 0)
        for r in self.hdb.oku("SELECT id, sebep, ilk_zaman, dizin_yolu FROM gonderilemeyen WHERE id > ? ORDER BY id LIMIT 20000", (son_gon,)):
            if yollar is None:
                yollar = self._dizin_yolu_haritasi()
            dz = yollar.get(str(r["dizin_yolu"] or "").lower())
            kod = "ESLESMEDI" if r["sebep"] == "ESLESMEDI" else "KAYITSIZ_KAPALI" if "KAYITSIZ" in (r["sebep"] or "") else "LOKALE_YAZILDI"
            olaylar.append((r["ilk_zaman"], kod, f"dizin:{dz}" if dz else "", None, f"gon:{r['id']}"))
            son_gon = max(son_gon, r["id"])
        iz["gon_id"] = son_gon
        son_alarm = iz.get("alarm_id", 0)
        for r in self.db.oku("SELECT id, anahtar, seviye, ilk_zaman FROM alarm WHERE id > ? ORDER BY id", (son_alarm,)):
            olaylar.append((r["ilk_zaman"], "ALARM_" + alarm_turu(r["anahtar"])[0], self._nesne(r["anahtar"]), r["seviye"], f"alarm:{r['id']}:acildi"))
            son_alarm = max(son_alarm, r["id"])
        iz["alarm_id"] = son_alarm
        esik = iz.get("kapanma_zaman", 0.0) - PAY_SN
        en = iz.get("kapanma_zaman", 0.0)
        for r in self.db.oku("SELECT id, anahtar, seviye, kapanma_zamani FROM alarm WHERE kapanma_zamani > ?", (esik,)):
            olaylar.append((r["kapanma_zamani"], "DUZELDI_" + alarm_turu(r["anahtar"])[0], self._nesne(r["anahtar"]), r["seviye"], f"alarm:{r['id']}:kapandi"))
            en = max(en, r["kapanma_zamani"])
        iz["kapanma_zaman"] = en
        # anomali takibi için sayısal ölçümler (dosya adı yok): boyut (tetik oluşunca), teslim süresi (canlı iletim)
        olcumler = []
        son_o = iz.get("olcum_tetik_id", 0)
        for r in self.db.oku("SELECT t.id, t.olusturma, t.kural_id, t.hedef_id, d.boyut FROM tetik t LEFT JOIN dosya d ON d.id=t.dosya_id "
                             "WHERE t.id > ? ORDER BY t.id LIMIT 20000", (son_o,)):
            if r["boyut"] is not None:
                olcumler.append((r["olusturma"], r["kural_id"], r["hedef_id"], "boyut", float(r["boyut"]), f"olcum:{r['id']}:boyut"))
            son_o = max(son_o, r["id"])
        iz["olcum_tetik_id"] = son_o
        esik = iz.get("olcum_iletildi", 0.0) - PAY_SN
        en = iz.get("olcum_iletildi", 0.0)
        for r in self.db.oku("SELECT id, iletildi_zamani, kural_id, hedef_id, sure_ms FROM tetik WHERE iletildi_zamani > ? "
                             "AND eritildi=0 AND sure_ms IS NOT NULL", (esik,)):
            olcumler.append((r["iletildi_zamani"], r["kural_id"], r["hedef_id"], "sure", float(r["sure_ms"]), f"olcum:{r['id']}:sure"))
            en = max(en, r["iletildi_zamani"])
        iz["olcum_iletildi"] = en
        yazilan = 0
        with self.adb.yaz() as con:
            for o in olcumler:
                con.execute("INSERT OR IGNORE INTO olcum(zaman, kural_id, hedef_id, tur, deger, kaynak) VALUES(?,?,?,?,?,?)", o)
            for o in olaylar:
                if o[0] is None:
                    continue
                yazilan += con.execute("INSERT OR IGNORE INTO olay(zaman, kod, nesne, seviye, kaynak) VALUES(?,?,?,?,?)", o).rowcount
            self.adb.meta_yaz("toplama_iz", json.dumps(iz), con)
        return yazilan

    @staticmethod
    def _nesne(anahtar: str) -> str:
        _, ids = alarm_turu(anahtar)
        for k in ("dizin", "hedef", "kural"):
            if k in ids:
                return f"{k}:{ids[k]}"
        return ""

    def buda(self, saklama_gun: int) -> int:
        sinir = time.time() - saklama_gun * 86400
        self.adb.calistir("DELETE FROM olcum WHERE zaman < ?", (sinir,))
        return self.adb.calistir("DELETE FROM olay WHERE zaman < ?", (sinir,))
