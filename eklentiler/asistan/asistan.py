"""Yapay zekâ asistanı eklentisi (kullanıcı isteği 2026-09-30: yerel model, dış API yok, kendi penceresinden çevrimiçi
eğitim; loss eğrisiyle öğreniyor mu / ezberliyor mu ve kendine güveni ekranda; olaylar arası ilişki self-attention ile).

Döngü (5 sn): olayları topla → komutları işle → yeterli yeni olay biriktiyse eğitim turu → öneriler → durum yaz.
  * Olay toplama PyTorch gerektirmez; PyTorch yoksa (ya da yüklenemezse) asistan veri toplamayı sürdürür, eğitim yapmaz.
  * PyTorch arka planda yüklenir (ilk açılışta 30 sn sürebilir); ana döngü bu sırada takılmış sayılmaz.
  * Eğitim turu: önce yeni olaylar görmeden tahmin edilir ('önce tahmin et, sonra öğren'), sonra model eğitilir. Son
    %20'lik zaman dilimi doğrulamadır, eğitime girmez. Ezber başlarsa eğitim durur, en iyi adıma dönülür. Yeni sürüm
    kullanılan sürümden kötüyse kullanılmaz.
  * Düşük öncelikli, tek iş parçacıklı (ayar) ayrı süreç: durursa ya da çökerse izleme ve teslim etkilenmez.
Gölge modu: yalnızca öneri yazar; hiçbir tetiği, kuralı, ayarı değiştirmez, alarm açmaz.
Komutlar (alıcı 'asistan'): EGIT, KENDINI_SINA, SURUM_KULLAN {surum}, SIFIRLA, VERI_SIL, AYAR.
"""
import copy
import json
import os
import threading
import time
from pathlib import Path

import psutil
from loguru import logger

from cekirdek import loglama
from cekirdek.eklenti_temel import Eklenti

from . import depo, oneriler
from .depo import AsistanDB, adlar_oku, ayarlar_oku, etiket
from .anomali import Anomali
from .toplayici import Toplayici

DONGU_SN = 5.0
ONERI_SN = 60.0


class Asistan(Eklenti):
    AD = "asistan"

    def __init__(self):
        super().__init__()
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)          # asıl işi (tarama/teslim) yavaşlatmasın
        except Exception:
            pass
        self.adb = AsistanDB(depo.depo_yolu(self.b.canli_db)).sema_kur()
        self.mdir = depo.model_klasoru(self.b.canli_db)
        self.mdir.mkdir(parents=True, exist_ok=True)
        self.toplayici = Toplayici(self.db, self.hdb, self.adb)
        self.anomali = Anomali(self.adb, self.db)
        self.M = None
        self.torch_hata = None
        self.torch_hazir = threading.Event()
        threading.Thread(target=self._torch_yukle, name="torch", daemon=True).start()
        self.model = None
        self.model_yapi_surumu = None
        kayitli = json.loads(self.adb.meta_al("durum") or "{}")
        self.durum = {"model_durumu": kayitli.get("model_durumu", "VERI_TOPLANIYOR"), "surum": kayitli.get("surum"),
                      "son_egitim": kayitli.get("son_egitim"), "son_tur_sn": kayitli.get("son_tur_sn"), "egitiliyor": False,
                      "egitim_ilerleme": None, "torch": None, "hata": None}
        self.son_n = int(self.adb.meta_al("son_egitim_olay") or 0)
        self.son_oneri = 0.0
        self.son_buda = 0.0

    def bilgi(self) -> dict:
        return {"model_durumu": self.durum.get("model_durumu"), "surum": self.durum.get("surum"), "egitiliyor": self.durum.get("egitiliyor")}

    # ------------------------------------------------------------ PyTorch
    def _torch_yukle(self):
        try:
            if os.environ.get("FWP_ASISTAN_TORCHSUZ"):
                raise ImportError("PyTorch kullanımı kapatıldı (FWP_ASISTAN_TORCHSUZ)")
            import torch
            torch.set_num_threads(int(ayarlar_oku(self.adb)["is_parcacigi"]))
            from . import model as M
            self.M = M
            logger.info(f"PyTorch hazır: {torch.__version__}")
        except Exception as e:                                               # eğitim yapılamaz; toplama sürer
            self.torch_hata = f"PyTorch yüklenemedi ({e}). Olaylar toplanıyor ama model eğitilemiyor. Kurulum: py -3.11 -m pip install torch"
            logger.warning(self.torch_hata)
        finally:
            self.torch_hazir.set()

    # ------------------------------------------------------------ ana döngü
    def calis(self):
        while not self.durmali():
            self.ilerle()
            try:
                self._tur()
            except Exception:
                logger.exception("asistan turunda hata (sonraki turda yeniden denenir)")
            son = time.time() + DONGU_SN                     # beklerken de ilerleme bildir: bekleyen döngü takılmış sayılmasın
            while not self.durmali() and time.time() < son:
                self.ilerle()
                self.bekle(min(0.5, son - time.time()))

    def _tur(self):
        ay = ayarlar_oku(self.adb)
        yeni = self.toplayici.topla()
        if yeni:
            loglama.olay("ASISTAN_TOPLADI", adet=yeni)
        if ay["anomali"]:                                  # istatistik: model / PyTorch gerekmez
            n_anomali = self.anomali.tur(ay)
            if n_anomali:
                loglama.olay("ASISTAN_ANOMALI", adet=n_anomali)
        for k in self.db.komutlari_al("asistan"):
            try:
                sonuc = self._komut(k, ay)
                self.db.komut_bitir(k["id"], sonuc)
            except Exception as e:
                logger.exception(f"asistan komutu hata verdi: {k['komut']}")
                self.db.komut_bitir(k["id"], str(e)[:300], durum="HATA")
            ay = ayarlar_oku(self.adb)
        n, gun = self._veri_boyu()
        yeterli = n >= ay["asgari_olay"] and gun >= ay["asgari_gun"]
        if self.torch_hazir.is_set() and self.M is not None:
            self._model_yukle(ay)
            if yeterli and ay["surekli"] and self._egitilebilir(n, ay) and (self.model is None or n - self.son_n >= ay["egitim_sikligi"]):
                self._egit(ay)
        if time.time() - self.son_oneri >= ONERI_SN:
            self.son_oneri = time.time()
            self._oneriler(ay)
        if self.model is None:                             # model yokken: veri yeterliyse ilk eğitime hazır
            self.durum["model_durumu"] = "HAZIR" if yeterli else "VERI_TOPLANIYOR"
        if time.time() - self.son_buda > 3600:
            self.son_buda = time.time()
            self.toplayici.buda(ay["saklama_gun"])
        self._durum_yaz(ay, n)

    @staticmethod
    def _egitilebilir(n, ay) -> bool:
        n_eg = int(n * (1 - ay["dogrulama_orani"]))
        return n_eg >= ay["baglam"] // 2 + 10 and n - n_eg >= 10

    def _veri_boyu(self):
        ilk, son, n = self.adb.tek("SELECT MIN(zaman), MAX(zaman), COUNT(*) FROM olay")
        return n, ((son - ilk) / 86400 if n else 0.0)

    def _durum_yaz(self, ay, n=None):
        if n is None:
            n = self._veri_boyu()[0]
        d = dict(self.durum)
        d.update(torch=None if not self.torch_hazir.is_set() else self.M is not None, hata=self.torch_hata or d.get("hata"),
                 sonraki_egitim_olay=max(0, ay["egitim_sikligi"] - (n - self.son_n)) if self.model is not None else None,
                 parametre=self.model.parametre() if self.model is not None else None,
                 cihaz=f"CPU · {ay['is_parcacigi']} iş parçacığı · düşük öncelik",
                 dogrulama_aciklama=f"Son %{ay['dogrulama_orani'] * 100:.0f}'lik zaman dilimi eğitime hiç girmez (zamana göre ayrım, karıştırma yok)")
        self.adb.meta_yaz("durum", json.dumps(d, ensure_ascii=False))

    # ------------------------------------------------------------ komutlar
    def _komut(self, k, ay) -> str:
        p = json.loads(k["parametre"] or "{}")
        if k["komut"] == "EGIT":
            if not self._torch_bekle():
                raise RuntimeError(self.torch_hata)
            n, _ = self._veri_boyu()
            if n < max(50, ay["baglam"] + 20):
                raise RuntimeError(f"eğitim için olay çok az ({n})")
            self._model_yukle(ay)
            return self._egit(ay)
        if k["komut"] == "KENDINI_SINA":
            if not self._torch_bekle():
                raise RuntimeError(self.torch_hata)
            return self._kendini_sina(ay)
        if k["komut"] == "SURUM_KULLAN":
            s = self.adb.tek("SELECT * FROM surum WHERE surum=?", (int(p.get("surum", 0)),))
            if s is None or not s["dosya"] or not self._torch_bekle():
                raise RuntimeError("sürüm bulunamadı")
            try:
                self.model = self.M.yukle(self._model_yolu(s["dosya"]))
            except self.M.ModelDosyasiHatasi as e:
                raise RuntimeError(f"sürüm {s['surum']} yüklenemedi: {e}") from None
            with self.adb.yaz() as con:
                con.execute("UPDATE surum SET durum='ESKI' WHERE durum='KULLANIMDA'")
                con.execute("UPDATE surum SET durum='KULLANIMDA' WHERE surum=?", (s["surum"],))
            self.durum["surum"] = s["surum"]
            return f"sürüm {s['surum']} kullanımda"
        if k["komut"] in ("SIFIRLA", "VERI_SIL"):
            self.model = None
            for f in self.mdir.glob("model_*"):
                f.unlink(missing_ok=True)
            with self.adb.yaz() as con:
                con.execute("DELETE FROM surum")
                for a in ("egri", "karar", "guven", "iliskiler", "son_egitim_olay"):
                    con.execute("DELETE FROM meta WHERE anahtar=?", (a,))
                con.execute("DELETE FROM onceden")
                if k["komut"] == "VERI_SIL":
                    con.execute("DELETE FROM olcum")
                    for a in ("anomali_iz", "anomali_ozet"):
                        con.execute("DELETE FROM meta WHERE anahtar=?", (a,))
                    con.execute("DELETE FROM olay")
                    con.execute("DELETE FROM sozluk")
                    con.execute("DELETE FROM oneri")
            self.son_n = 0
            if k["komut"] == "VERI_SIL":
                self.anomali = Anomali(self.adb, self.db)
            self.durum.update(model_durumu="VERI_TOPLANIYOR", surum=None, son_egitim=None)
            return "model sıfırlandı" + ("; toplanan veri silindi" if k["komut"] == "VERI_SIL" else "")
        if k["komut"] == "AYAR":
            return "ayarlar yeniden okundu"
        raise RuntimeError(f"bilinmeyen komut: {k['komut']}")

    def _model_yolu(self, kayitli):
        """Model dosyası yalnızca kendi klasöründen okunur (veritabanındaki yol başka yeri gösterse bile)."""
        return self.mdir / Path(str(kayitli)).name

    def _torch_bekle(self) -> bool:
        while not self.torch_hazir.wait(1.0):
            self.ilerle()
            if self.durmali():
                return False
        return self.M is not None

    # ------------------------------------------------------------ veri → model girdisi
    def _dizi(self):
        satirlar = self.adb.oku("SELECT zaman, kod, nesne FROM olay ORDER BY zaman, id")
        sozluk = {r["token"]: r["no"] for r in self.adb.oku("SELECT token, no FROM sozluk")}
        yeni = []
        for r in satirlar:
            t = f"{r['kod']}|{r['nesne']}"
            if t not in sozluk and len(sozluk) < self.M.SOZLUK - 1:
                sozluk[t] = len(sozluk) + 1
                yeni.append((t, sozluk[t]))
        if yeni:
            with self.adb.yaz() as con:
                con.executemany("INSERT OR IGNORE INTO sozluk(token, no) VALUES(?,?)", yeni)
        toklar = [sozluk.get(f"{r['kod']}|{r['nesne']}", 0) for r in satirlar]
        return self.M.Dizi(toklar, [r["zaman"] for r in satirlar]), {v: k for k, v in sozluk.items()}

    def _model_yukle(self, ay):
        yapi_s = self.adb.meta_al("yapi_surumu") or "0"
        if self.model is not None and self.model_yapi_surumu == yapi_s:
            return
        s = self.adb.tek("SELECT * FROM surum WHERE durum='KULLANIMDA' ORDER BY surum DESC LIMIT 1")
        yol = self._model_yolu(s["dosya"]) if s is not None and s["dosya"] else None
        if self.model is None and yol is not None and yol.exists():
            try:
                m = self.M.yukle(yol)
            except self.M.ModelDosyasiHatasi as e:              # eski biçim / bozuk / değiştirilmiş dosya: yüklenmez
                logger.warning(f"kullanımdaki model yüklenmedi, yeniden eğitilecek: {e}")
                m = None
            if m is not None and all(m.yapi[k] == ay[k] for k in depo.YAPI):
                self.model, self.model_yapi_surumu = m, yapi_s
                self.durum["surum"] = s["surum"]
                return
        if self.model is not None and self.model_yapi_surumu != yapi_s:
            logger.info("model yapısı değişti: model sıfırdan eğitilecek")
            self.model = None
            self.adb.calistir("DELETE FROM meta WHERE anahtar='egri'")
        self.model_yapi_surumu = yapi_s

    # ------------------------------------------------------------ eğitim turu
    def _ilerleme(self, x):
        self.durum["egitim_ilerleme"] = round(x, 3)
        if int(x * 100) % 10 == 0:
            try:
                self._durum_yaz(ayarlar_oku(self.adb))
            except Exception:
                pass

    def _egit(self, ay) -> str:
        M = self.M
        dizi, tokenler = self._dizi()
        n = len(dizi)
        n_eg = int(n * (1 - ay["dogrulama_orani"]))
        if not self._egitilebilir(n, ay):
            raise RuntimeError(f"eğitim için olay çok az ({n})")
        self.durum.update(egitiliyor=True, egitim_ilerleme=0.0)
        self._durum_yaz(ay, n)
        t0 = time.time()
        try:
            yeni_model = self.model is None
            if yeni_model:
                self.model = M.OlayModeli(baglam=ay["baglam"], katman=ay["katman"], bas=ay["bas"], boyut=ay["boyut"], dropout=ay["dropout"])
            else:
                self._onceden(dizi)
                for m_ in self.model.modules():                           # dropout ayarı mevcut modele de uygulanır
                    if isinstance(m_, M.nn.Dropout):
                        m_.p = ay["dropout"]
                    elif isinstance(m_, M.nn.MultiheadAttention):
                        m_.dropout = ay["dropout"]
            onceki = self.adb.tek("SELECT * FROM surum WHERE durum='KULLANIMDA' ORDER BY surum DESC LIMIT 1")
            onceki_agirlik = None if yeni_model else copy.deepcopy(self.model.state_dict())
            onceki_sicaklik = self.model.sicaklik
            onceki_ham = None
            if not yeni_model:
                self.model.sicaklik = 1.0
                onceki_ham = M.ortalama(M.degerlendir(self.model, dizi, n_eg, n, ilerle=self.ilerle)["kayip"])
            egri = json.loads(self.adb.meta_al("egri") or "null") if not yeni_model else None
            bas_adim = egri["adimlar"][-1] if egri and egri.get("adimlar") else 0
            tabanlar = M.Tabanlar(dizi, n_eg)
            r = M.egit(self.model, dizi, n_eg, n_eg, adim=ay["egitim_adimi"], sure_sn=ay["egitim_sure_sn"], lr=ay["ogrenme_orani"],
                       agirlik_azaltma=ay["agirlik_azaltma"], baslangic_adimi=bas_adim, ilerle=self.ilerle, durmali=self.durmali,
                       ilerleme=self._ilerleme)
            self.model.sicaklik = 1.0
            yeni_ham = M.ortalama(M.degerlendir(self.model, dizi, n_eg, n, ilerle=self.ilerle)["kayip"])
            olcum = M.olc_ve_kalibre(self.model, dizi, n_eg, tabanlar, ilerle=self.ilerle)
            yeni_dogrulama = olcum["dogrulama"]
            ezber = r["ezber_bas"] is not None
            anlamsiz = olcum["dogrulama"] >= olcum["markov"] * 0.98
            daha_kotu = onceki_ham is not None and yeni_ham > onceki_ham * 1.005
            surum = (self.adb.tek("SELECT MAX(surum) FROM surum")[0] or 0) + 1
            dosya = str(self.mdir / f"model_{surum}.npz")
            if daha_kotu:
                durum_s = "EZBER" if ezber else "ANLAMSIZ" if anlamsiz else "GERILEDI"
                M.kaydet(self.model, dosya)
                self.model.load_state_dict(onceki_agirlik)                        # kullanılan sürüm yerinde kalır
                self.model.sicaklik = onceki_sicaklik
                olcum = M.olc_ve_kalibre(self.model, dizi, n_eg, tabanlar, ilerle=self.ilerle)
            else:
                durum_s = "KULLANIMDA"
                M.kaydet(self.model, dosya)
            with self.adb.yaz() as con:
                if durum_s == "KULLANIMDA":
                    con.execute("UPDATE surum SET durum='ESKI' WHERE durum='KULLANIMDA'")
                con.execute("INSERT INTO surum(surum, zaman, olay, egitim, dogrulama, markov, siklik, durum, yapi, dosya) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (surum, time.time(), n, r["egri"]["egitim"][-1], yeni_dogrulama, olcum["markov"],
                             olcum["siklik"], durum_s, json.dumps(self.model.yapi), dosya))
            kullanilan = surum if durum_s == "KULLANIMDA" else (onceki["surum"] if onceki else None)
            model_durumu = ("ANLAMSIZ" if olcum["dogrulama"] >= olcum["markov"] * 0.98 else "EZBERLIYOR" if ezber
                            else "OGRENIYOR" if onceki_ham is None or yeni_ham < onceki_ham * 0.995 else "DURAGAN")
            # eğri (birikimli), karar, güven ölçümleri, ilişkiler
            e2 = r["egri"]
            if egri and egri.get("adimlar"):
                for k_ in ("adimlar", "egitim", "dogrulama"):
                    egri[k_] = (egri[k_] + e2[k_])[-300:]
            else:
                egri = {k_: e2[k_] for k_ in ("adimlar", "egitim", "dogrulama")}
            egri.update(taban_markov=olcum["markov"], taban_siklik=olcum["siklik"], en_iyi_adim=r["en_iyi_adim"], en_iyi_surum=kullanilan,
                        ezber_baslangic=r["ezber_bas"])
            adlar = adlar_oku(self.db)
            etiketler = {no: etiket(tokenler[no], adlar) for no in set(dizi.tok.tolist()) if no in tokenler}
            d = M.degerlendir(self.model, dizi, n_eg, n, dikkat=True, ilerle=self.ilerle)
            il = M.iliskiler(d["birikim"], d["sayac"], dizi, etiketler,
                             sistem=lambda b, a: oneriler.sistem_kurali(tokenler.get(b, ""), tokenler.get(a, "")))
            fark = olcum["dogrulama"] - (e2["egitim"][-1] if e2["egitim"] else 0.0)
            karar = self._karar(model_durumu, durum_s, surum, kullanilan, r, olcum, fark, onceki_ham, yeni_ham)
            with self.adb.yaz() as con:
                self.adb.meta_yaz("egri", json.dumps(egri), con)
                self.adb.meta_yaz("karar", json.dumps(karar, ensure_ascii=False), con)
                self.adb.meta_yaz("guven", json.dumps({k_: olcum[k_] for k_ in ("iyilesme", "ga_alt", "ga_ust", "ece", "guvenilirlik", "basari",
                                                                              "ornek_cumle", "surpriz_esik", "dogrulama", "markov")} | {"fark": fark},
                                                      ensure_ascii=False), con)
                self.adb.meta_yaz("iliskiler", json.dumps(il, ensure_ascii=False), con)
                self.adb.meta_yaz("son_egitim_olay", str(n), con)
            self.son_n = n
            if model_durumu != "ANLAMSIZ":
                _, gun = self._veri_boyu()
                oneriler.iliski_onerileri(self.adb, il["liste"], {**tokenler}, gun, kullanilan)
            sure = time.time() - t0
            self.durum.update(model_durumu=model_durumu, surum=kullanilan, son_egitim=time.time(), son_tur_sn=round(sure))
            loglama.olay("ASISTAN_EGITIM", surum=surum, durum=durum_s, model=model_durumu, dogrulama=round(olcum["dogrulama"], 3),
                         markov=round(olcum["markov"], 3), adim=r["son_adim"] - bas_adim, sure_sn=round(sure))
            return f"sürüm {surum}: {durum_s} ({model_durumu})"
        finally:
            self.durum.update(egitiliyor=False, egitim_ilerleme=None)
            self._durum_yaz(ay)

    @staticmethod
    def _karar(model_durumu, durum_s, surum, kullanilan, r, olcum, fark, onceki_ham, yeni_ham) -> dict:
        kk = lambda v: f"{v:.2f}".replace(".", ",")                           # noqa: E731
        yz = lambda v: f"%{v * 100:.0f}"                                        # noqa: E731
        m = []
        if model_durumu == "ANLAMSIZ":
            baslik = "Model Markov tabanını geçemiyor: öneri üretmiyor."
            m.append(f"Doğrulama kaybı {kk(olcum['dogrulama'])}, Markov tabanı {kk(olcum['markov'])}: model 'bir önceki olaya bakmaktan' fazlasını öğrenemedi.")
            m.append("Olası neden: veri az ya da olaylarda düzen yok. Veri biriktikçe yeniden denenecek.")
        elif model_durumu == "EZBERLIYOR":
            baslik = (f"Sürüm {surum} ezberledi: kullanılmadı, sürüm {kullanilan}'e dönüldü." if durum_s != "KULLANIMDA"
                      else f"Ezber başladı; eğitim durduruldu, en iyi adıma (sürüm {surum}) dönüldü.")
            e = r["egri"]
            i = e["adimlar"].index(r["ezber_bas"]) if r["ezber_bas"] in e["adimlar"] else 0
            m.append(f"Adım {r['ezber_bas']}'den sonra eğitim kaybı {kk(e['egitim'][i])} → {kk(e['egitim'][-1])} düşerken doğrulama kaybı "
                     f"{kk(e['dogrulama'][i])} → {kk(e['dogrulama'][-1])} yükseldi (kırmızı bölge).")
            m.append("Olası neden: veri az; model gördüğü günleri tekrar ediyor. Veri biriktikçe azalır; gerekirse Gelişmiş ayarlarda dropout'u artırın.")
            m.append(f"Kullanılan modelin doğrulama kaybı {kk(olcum['dogrulama'])}; Markov tabanı {kk(olcum['markov'])}.")
        else:
            baslik = "Model öğreniyor; ezber yok." if model_durumu == "OGRENIYOR" else "Model kararlı; bu turda belirgin iyileşme yok."
            m.append(f"Doğrulama kaybı {kk(olcum['dogrulama'])}: Markov tabanından ({kk(olcum['markov'])}) {yz(olcum['iyilesme'])} düşük "
                     f"(%95 güven aralığı {yz(olcum['ga_alt'])}–{yz(olcum['ga_ust'])}).")
            m.append(f"Eğitim ile doğrulama arasındaki fark {kk(fark)}: " + ("ezber işareti yok." if fark < 0.3 else "büyük; ezber riski izleniyor."))
            if onceki_ham is not None:
                m.append(f"Önceki sürüm aynı doğrulama verisinde {kk(onceki_ham)}, yeni sürüm {kk(yeni_ham)}"
                         + (" → yeni sürüm kullanımda." if durum_s == "KULLANIMDA" else " → yeni sürüm kullanılmadı."))
            m.append("Öneriler açık (gölge modu).")
        return {"baslik": baslik, "maddeler": m}

    def _onceden(self, dizi):
        """Yeni olaylar, model onları hiç görmeden tahmin edilir (önce tahmin et, sonra öğren); günlük başarı yazılır."""
        n = len(dizi)
        bas = max(1, min(self.son_n, n))
        if bas >= n:
            return
        M = self.M
        tb = M.Tabanlar(dizi, bas)
        d = M.degerlendir(self.model, dizi, bas, n, tabanlar=tb, azami=20000, ilerle=self.ilerle)
        gunler = {}
        for z, dm, mm in zip(dizi.zaman[n - d["n"]:], d["dogru1"], d["markov1"]):
            g = time.strftime("%Y-%m-%d", time.localtime(z))
            x = gunler.setdefault(g, [0, 0, 0])
            x[0] += 1
            x[1] += int(dm)
            x[2] += int(mm)
        with self.adb.yaz() as con:
            for g, (say, md, mk) in gunler.items():
                con.execute("INSERT INTO onceden(gun, n, model, markov) VALUES(?,?,?,?) ON CONFLICT(gun) DO UPDATE SET "
                            "n=n+excluded.n, model=model+excluded.model, markov=markov+excluded.markov", (g, say, md, mk))

    # ------------------------------------------------------------ öneriler
    def _oneriler(self, ay):
        adlar = adlar_oku(self.db)
        oneriler.beklenen_gelmedi(self.adb, self.db, adlar)
        oneriler.kural_onerileri(self.adb, self.db, self.hdb)
        if self.model is not None and self.durum.get("model_durumu") not in ("ANLAMSIZ", "VERI_TOPLANIYOR"):
            self._olagandisi(adlar)

    def _olagandisi(self, adlar):
        son_id = int(self.adb.meta_al("olagandisi_iz") or 0)
        en_son = self.adb.tek("SELECT MAX(id) FROM olay")[0] or 0
        if en_son <= son_id:
            return
        g = json.loads(self.adb.meta_al("guven") or "null")
        if not g:
            return
        M = self.M
        dizi, tokenler = self._dizi()
        idler = [r[0] for r in self.adb.oku("SELECT id FROM olay ORDER BY zaman, id")]
        bas = next((i for i, x in enumerate(idler) if x > son_id), len(idler))
        self.adb.meta_yaz("olagandisi_iz", str(en_son))
        if bas >= len(dizi) or bas < 10:
            return
        p = M.olasiliklar(self.model, dizi, bas, len(dizi))
        esik = max(0.005, float(M.np.exp(-g.get("surpriz_esik", 10.0))))
        egitim_sayisi = M.Counter(dizi.tok[: int(self.son_n * 0.8)].tolist())
        from .depo import karne
        k = karne(g, {"faydali": 0, "faydasiz": 0}, self.durum.get("model_durumu"), {"gun_sayisi": self._veri_boyu()[1], "olay_sayisi": len(dizi)})
        gruplar = {}
        for i, olas in zip(range(len(dizi) - len(p), len(dizi)), p):
            no = int(dizi.tok[i])
            if olas >= esik or egitim_sayisi.get(no, 0) < 5 or no not in tokenler:
                continue                                                    # yeni olay türüne model görüş bildirmez
            anahtar = (no, int(dizi.zaman[i] // 3600))
            x = gruplar.setdefault(anahtar, [dizi.zaman[i], olas, 0])
            x[1] = min(x[1], olas)
            x[2] += 1
        for (no, _), (zaman, olas, adet) in gruplar.items():
            oneriler.olagandisi_onerisi(self.adb, token=tokenler[no], adlar=adlar, zaman=float(zaman), olasilik=float(olas), esik=esik,
                                        adet=adet, guven=k["puan"], surum=self.durum.get("surum"))

    # ------------------------------------------------------------ kendini sına
    def _kendini_sina(self, ay) -> str:
        from . import sentetik
        self.adb.meta_yaz("kendini_sina", json.dumps({"son": json.loads(self.adb.meta_al("kendini_sina") or "{}").get("son"),
                                                      "suruyor": True, "baslangic": time.time()}))
        try:
            s = sentetik.sina(ay, ilerle=self.ilerle, durmali=self.durmali)
        except Exception as e:
            s = {"zaman": time.time(), "sonuc": "KALDI", "baslik": f"Sınama çalıştırılamadı: {e}", "maddeler": [], "egri": None}
        s.pop("olcum", None)
        self.adb.meta_yaz("kendini_sina", json.dumps({"son": s, "suruyor": False}, ensure_ascii=False))
        loglama.olay("ASISTAN_KENDINI_SINA", sonuc=s["sonuc"])
        return f"kendini sına: {s['sonuc']}"


if __name__ == "__main__":
    Asistan.baslat()
