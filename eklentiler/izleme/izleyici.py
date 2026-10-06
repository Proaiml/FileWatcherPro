"""İzleme eklentisi (Sistem izleme sayfası; kullanıcı isteği 2026-09-30).

Her `izleme_aralik_sn`'de (varsayılan 10 sn):
  * Sunucu: CPU %, bellek %, veri/log disklerinin boş alanı, açık kalma süresi.
  * FileWatcherPro: çekirdek + her eklentinin CPU'su (SUNUCUNUN yüzdesi; Görev Yöneticisi gibi), belleği, thread ve
    handle sayısı, çalışma süresi, son 1 saatteki tepe CPU.
  * Depolama (60 sn'de bir): canli.db / hata.db (+WAL), lokal kayıt dosyaları, log klasörü.
  * Ölçüm canli.db > olcum tablosuna yazılır (son 24 saat tutulur), anlık özet meta 'izleme_anlik'e.
Eşikler (Ayarlar > İzleme): değer eşiği aşınca önce 'Aşıldı' görünür; belirtilen süre boyunca sürerse alarm açılır
(anlık sıçramalar alarm üretmez); değer 60 sn normal kalınca alarm kendiliğinden kapanır. Dizin tarama süresi 3 ölçüm
üst üste eşiği aşarsa alarm. Alarm anahtarları: kaynak:sunucu_cpu, kaynak:sunucu_ram, kaynak:disk, kaynak:fwp_cpu,
kaynak:fwp_ram, kaynak:log, kaynak:tarama:<dizin_id>.
Bu eklenti düşük öncelikte çalışır ve tetik yoluna hiç dokunmaz; düşerse yalnızca izleme durur.
"""
import json
import os
import time
from collections import deque
from pathlib import Path

import psutil
from loguru import logger

from cekirdek import loglama
from cekirdek.eklenti_temel import Eklenti
from cekirdek.model import AlarmSeviye

SAKLAMA_SN = 24 * 3600 + 300
DEPO_ARALIK_SN = 60.0
TARAMA_ARDISIK = 3


def _yuzde(v):
    return f"%{v:.0f}" if v >= 10 else f"%{v:.1f}".replace(".", ",")


def _sayi(v, n=0):
    s = f"{v:,.{n}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _klasor(yol: Path, desen="*"):
    toplam, adet = 0, 0
    try:
        for f in Path(yol).rglob(desen):
            try:
                if f.is_file():
                    toplam += f.stat().st_size
                    adet += 1
            except OSError:
                pass
    except OSError:
        pass
    return toplam / 1048576, adet


class Izleyici(Eklenti):
    AD = "izleme"

    def __init__(self):
        super().__init__()
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)     # asıl işi (tarama/teslim) yavaşlatmasın
        except Exception:
            pass
        self.cekirdek_sayisi = psutil.cpu_count() or 1
        self.surecler = {}              # pid → psutil.Process (cpu_percent ölçümü aradaki farka dayanır)
        self.tepe = {}                  # ad → deque[(zaman, cpu)]
        self.durum = {}                 # eşik anahtarı → {"asilma": t, "normal": t, "alarm": bool}
        self.tarama_ardisik = {}        # dizin_id → art arda eşik üstü ölçüm
        self.depo = {}
        self.son_depo = 0.0
        self.son_budama = 0.0
        psutil.cpu_percent(None)
        for a in self.db.oku("SELECT anahtar FROM alarm WHERE aktif=1 AND anahtar LIKE 'kaynak:%'"):
            self.durum[a[0]] = {"asilma": time.time() - 1e6, "normal": None, "alarm": True}   # yeniden başlatmadan önce açılmış

    def bilgi(self) -> dict:
        return {"surec": len(self.surecler), "alarm": sum(1 for d in self.durum.values() if d.get("alarm"))}

    def calis(self):
        while not self.durmali():
            self.ilerle()
            self.ayar.tazele()
            try:
                self._olc()
            except Exception:
                logger.exception("izleme ölçümünde hata (sonraki turda yeniden denenir)")
            self.bekle(float(self.ayar.al("izleme_aralik_sn")))

    # ------------------------------------------------------------ ölçüm
    def _surec(self, pid):
        p = self.surecler.get(pid)
        if p is None:
            p = psutil.Process(pid)
            p.cpu_percent(None)
            self.surecler[pid] = p
        return p

    def _olc(self):
        simdi = time.time()
        vm = psutil.virtual_memory()
        sunucu_cpu = psutil.cpu_percent(None)
        satirlar = [dict(r) for r in self.db.oku("SELECT ad, pid, durum, baslama FROM eklenti ORDER BY ad")]
        surecler, canli_pidler = [], set()
        for r in satirlar:
            kayit = {"ad": r["ad"], "pid": r["pid"], "cpu": None, "cpu_tepe": None, "ram_mb": None, "thread": None,
                     "handle": None, "calisma_sn": None}
            if r["pid"]:
                try:
                    p = self._surec(r["pid"])
                    with p.oneshot():
                        cpu = p.cpu_percent(None) / self.cekirdek_sayisi
                        kayit.update(cpu=round(cpu, 2), ram_mb=round(p.memory_info().rss / 1048576, 1),
                                     thread=p.num_threads(), handle=p.num_handles(),
                                     calisma_sn=round(simdi - p.create_time()))
                    canli_pidler.add(r["pid"])
                    q = self.tepe.setdefault(r["ad"], deque())
                    q.append((simdi, cpu))
                    while q and q[0][0] < simdi - 3600:
                        q.popleft()
                    kayit["cpu_tepe"] = round(max(x[1] for x in q), 2)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    self.surecler.pop(r["pid"], None)
            surecler.append(kayit)
        for pid in [x for x in self.surecler if x not in canli_pidler]:
            self.surecler.pop(pid, None)
        fwp_cpu = sum(x["cpu"] or 0 for x in surecler)
        fwp_ram = sum(x["ram_mb"] or 0 for x in surecler)
        diskler = self._diskler()
        if simdi - self.son_depo >= DEPO_ARALIK_SN or not self.depo:
            self.son_depo = simdi
            self.depo = self._depolama()
        cekirdek = next((x for x in surecler if x["ad"] == "cekirdek"), {})
        anlik = {
            "zaman": simdi,
            "sunucu": {"ad": os.environ.get("COMPUTERNAME", ""), "cekirdek": self.cekirdek_sayisi, "cpu": round(sunucu_cpu, 1),
                       "ram_yuzde": round(vm.percent, 1), "ram_toplam_mb": round(vm.total / 1048576),
                       "ram_kullanilan_mb": round((vm.total - vm.available) / 1048576), "acik_sn": round(simdi - psutil.boot_time()),
                       "diskler": diskler},
            "fwp": {"cpu": round(fwp_cpu, 2), "ram_mb": round(fwp_ram, 1), "calisma_sn": cekirdek.get("calisma_sn"),
                    "surecler": surecler},
            "depo": self.depo,
        }
        disk_bos = min((d["bos_mb"] for d in diskler), default=None)
        anlik["esikler"] = self._esikler(simdi, anlik, disk_bos)
        with self.db.yaz() as con:
            con.execute("INSERT OR REPLACE INTO olcum(zaman, sunucu_cpu, sunucu_ram, fwp_cpu, fwp_ram_mb, disk_bos_mb) "
                        "VALUES(?,?,?,?,?,?)", (simdi, sunucu_cpu, vm.percent, fwp_cpu, fwp_ram, disk_bos))
            self.db.meta_yaz("izleme_anlik", json.dumps(anlik, ensure_ascii=False), con)
            if simdi - self.son_budama > 300:
                self.son_budama = simdi
                con.execute("DELETE FROM olcum WHERE zaman < ?", (simdi - SAKLAMA_SN,))

    def _diskler(self) -> list:
        yollar = [(self.b.veri, "veri, lokal kayıt"), (self.b.loglar, "loglar")]
        sonuc = {}
        for yol, icerik in yollar:
            try:
                u = psutil.disk_usage(str(yol))
            except OSError:
                continue
            surucu = os.path.splitdrive(os.path.abspath(str(yol)))[0] or str(yol)
            if surucu in sonuc:
                sonuc[surucu]["icerik"] += f", {icerik}"
                continue
            sonuc[surucu] = {"surucu": surucu, "icerik": icerik, "bos_mb": round(u.free / 1048576),
                             "toplam_mb": round(u.total / 1048576), "bos_yuzde": round(100 - u.percent, 1)}
        return list(sonuc.values())

    def _depolama(self) -> dict:
        def db_mb(yol):
            return sum(Path(str(yol) + ek).stat().st_size for ek in ("", "-wal") if Path(str(yol) + ek).exists()) / 1048576
        lokal_mb, lokal_adet = _klasor(self.b.lokal_kayit, "*.json")
        log_mb, log_adet = _klasor(self.b.loglar)
        return {"canli_mb": round(db_mb(self.b.canli_db), 2), "hata_mb": round(db_mb(self.b.hata_db), 2),
                "lokal_adet": lokal_adet, "lokal_mb": round(lokal_mb, 2), "log_mb": round(log_mb, 1), "log_adet": log_adet}

    # ------------------------------------------------------------ eşikler (histerezisli)
    def _esikler(self, simdi, anlik, disk_bos_mb) -> list:
        a = self.ayar.al
        s, f, dp = anlik["sunucu"], anlik["fwp"], anlik["depo"]
        tanim = [
            ("sunucu_cpu", "Sunucu CPU", "Sunucunun toplam işlemci kullanımı", "izleme_sunucu_cpu", "%", ">", s["cpu"], AlarmSeviye.UYARI),
            ("sunucu_ram", "Sunucu bellek", "Sunucunun bellek kullanımı", "izleme_sunucu_ram", "%", ">", s["ram_yuzde"], AlarmSeviye.UYARI),
            ("disk", "Disk boş alan", "Veri ve log disklerinin en azı", "izleme_disk_bos_gb", "GB", "<",
             None if disk_bos_mb is None else disk_bos_mb / 1024, AlarmSeviye.KRITIK),
            ("fwp_cpu", "FileWatcherPro CPU", "Tüm bileşenlerin toplamı (sunucunun yüzdesi)", "izleme_fwp_cpu", "%", ">", f["cpu"], AlarmSeviye.UYARI),
            ("fwp_ram", "FileWatcherPro bellek", "Tüm bileşenlerin toplamı", "izleme_fwp_ram_mb", "MB", ">", f["ram_mb"], AlarmSeviye.UYARI),
            ("log", "Log klasörü", "Log klasörünün toplam boyutu", "izleme_log_mb", "MB", ">", dp.get("log_mb"), AlarmSeviye.UYARI),
        ]
        sonuc = []
        for anahtar, ad, aciklama, ayar, birim, yon, deger, seviye in tanim:
            esik, aktif = float(a(ayar)), bool(a(f"{ayar}_aktif"))
            sure_ayar = f"{ayar}_dk" if f"{ayar}_dk" in _TANIMLI else None
            sure_dk = float(a(sure_ayar)) if sure_ayar else 0.0
            asti = aktif and deger is not None and (deger > esik if yon == ">" else deger < esik)
            fmt = (lambda v: _yuzde(v)) if birim == "%" else (lambda v, b=birim: f"{_sayi(v, 1 if v < 10 else 0)} {b}")
            mesaj = (f"{ad} {'eşiği aştı' if yon == '>' else 'eşiğin altına düştü'}: {fmt(deger) if deger is not None else '—'} "
                     f"(eşik {yon} {fmt(esik)}{f', {sure_dk:g} dk boyunca' if sure_dk else ''}).")
            d = self._esik_durumu(f"kaynak:{anahtar}", asti, sure_dk * 60, simdi, mesaj, seviye)
            sonuc.append({"anahtar": anahtar, "ad": ad, "aciklama": aciklama, "ayar": ayar, "sure_ayar": sure_ayar,
                          "esik": esik, "sure_dk": sure_dk, "birim": birim, "seviye": seviye, "aktif": aktif,
                          "simdi_metin": fmt(deger) if deger is not None else "—", "esik_metin": f"{yon} {fmt(esik)}",
                          "durum": "ALARM" if d["alarm"] else "ASILDI" if asti else "NORMAL",
                          "asilma_zamani": d["asilma"] if asti else None})
        sonuc.append(self._tarama_esigi(simdi))
        return sonuc

    def _esik_durumu(self, anahtar, asti, sure_sn, simdi, mesaj, seviye) -> dict:
        d = self.durum.setdefault(anahtar, {"asilma": None, "normal": None, "alarm": False})
        if asti:
            d["normal"] = None
            d["asilma"] = d["asilma"] or simdi
            if not d["alarm"] and simdi - d["asilma"] >= sure_sn:
                d["alarm"] = True
                self.db.alarm_ac(anahtar, mesaj, seviye, "izleme")
                loglama.olay("KAYNAK_ESIGI", anahtar=anahtar, mesaj=mesaj)
            elif d["alarm"]:
                self.db.alarm_ac(anahtar, mesaj, seviye, "izleme")        # mesaj güncel kalsın (tekrar sayısı artar)
        else:
            d["asilma"] = None
            if d["alarm"]:
                d["normal"] = d["normal"] or simdi
                if simdi - d["normal"] >= float(self.ayar.al("izleme_normale_donus_sn")):
                    d["alarm"] = False
                    d["normal"] = None
                    self.db.alarm_kapat(anahtar)
                    loglama.olay("KAYNAK_NORMAL", anahtar=anahtar)
        return d

    def _tarama_esigi(self, simdi) -> dict:
        esik = float(self.ayar.al("izleme_tarama_sn"))
        aktif = bool(self.ayar.al("izleme_tarama_sn_aktif"))
        en_yavas, en_yavas_yol = 0.0, None
        for dz in self.db.oku("SELECT id, yol, son_tarama_ms FROM dizin WHERE aktif=1"):
            sn = (dz["son_tarama_ms"] or 0) / 1000
            if sn >= en_yavas:
                en_yavas, en_yavas_yol = sn, dz["yol"]
            asti = aktif and sn > esik
            n = self.tarama_ardisik[dz["id"]] = (self.tarama_ardisik.get(dz["id"], 0) + 1) if asti else 0
            mesaj = (f"Dizin taraması yavaş: {dz['yol']} listelemesi {_sayi(sn, 1)} sn sürdü ({TARAMA_ARDISIK} ölçüm üst "
                     f"üste eşik {_sayi(esik, 1)} sn üstü). Yeni dosyalar geç fark edilir.")
            self._esik_durumu(f"kaynak:tarama:{dz['id']}", n >= TARAMA_ARDISIK, 0, simdi, mesaj, AlarmSeviye.UYARI)
        alarm = any(d.get("alarm") for k, d in self.durum.items() if k.startswith("kaynak:tarama:"))
        return {"anahtar": "tarama_suresi", "ad": "Dizin tarama süresi", "aciklama": f"En yavaş dizin: {en_yavas_yol or '—'} ({TARAMA_ARDISIK} ölçüm üst üste)",
                "ayar": "izleme_tarama_sn", "sure_ayar": None, "esik": esik, "sure_dk": 0, "birim": "sn", "seviye": AlarmSeviye.UYARI,
                "aktif": aktif, "simdi_metin": f"{_sayi(en_yavas, 2)} sn", "esik_metin": f"> {_sayi(esik, 1)} sn",
                "durum": "ALARM" if alarm else "ASILDI" if aktif and en_yavas > esik else "NORMAL", "asilma_zamani": None}


from cekirdek.ayarlar import TANIMLAR as _TANIMLI  # noqa: E402

if __name__ == "__main__":
    Izleyici.baslat()
