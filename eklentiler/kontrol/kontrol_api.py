"""Kontrol eklentisi: önyüzün konuştuğu yerel HTTP arayüzü + önyüz dosyaları.

Çekirdeğin kritik yolunda DEĞİLDİR: düşerse tarama ve teslim son ayarlarla çalışmaya devam eder (U11);
gözetmen bu eklentiyi yeniden başlatır. Tüm değişiklikler cekirdek.yapilandirma üzerinden (doğrulama +
denetim) ya da gözetmen/eklenti komutlarıyla yapılır.

Güvenlik:
  * Giriş zorunlu (config/kullanicilar.json, PBKDF2). Roller: IZLEYICI < OPERATOR < YONETICI.
    Hiç kullanıcı yoksa admin/admin (YÖNETİCİ) oluşturulur; şifre değişene kadar uyarı alarmı açık kalır.
    POST /api/sifre {eski, yeni}: giriş yapmış her kullanıcı kendi şifresini değiştirir.
  * Oturum çerezi HttpOnly + SameSite=Strict; değiştiren isteklerde 'X-FWP: 1' başlığı zorunlu (CSRF).
  * 5 hatalı girişte kullanıcı 60 sn kilitlenir. Varsayılan dinleme adresi 127.0.0.1.
  * Content-Security-Policy: yalnızca kendi kaynakları (CDN yok; önyüz internetsiz çalışır).

Uç noktalar (JSON): bkz. ROTALAR tablosu.
"""
import json
import mimetypes
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from loguru import logger

from cekirdek import betik, betik_sifresi, loglama, lokal_islem
from cekirdek.ayarlar import TANIMLAR, dogrula
from cekirdek.bakim import sonraki_planli_zaman
from cekirdek.eklenti_temel import Eklenti
from cekirdek.kullanicilar import Kullanicilar, rol_yeterli
from cekirdek.istek_sablonu import (SablonHatasi, degiskenler as istek_degiskenleri, olustur as istek_olustur,
                                    parametre_olustur)
from cekirdek.kurallar import RegexHatasi, regex_dene
from cekirdek import eposta
from cekirdek.sirlar import kaynak_metni, sir_oku, sirlari_gizle, sirlari_isle
from cekirdek.olaylar import KATALOG, KODLAR, SEVIYE_SIRA, alarm_turu
from cekirdek.model import AlarmSeviye, TetikDurum
from cekirdek.yapilandirma import Yapilandirma

ONYUZ = Path(__file__).resolve().parent / "onyuz"
OTURUM_OMRU_SN = 12 * 3600
KILIT_ESIGI, KILIT_SN = 5, 60
BETIK_KILIT_SN = 600                      # süper yönetici şifresiyle açılan betik kilidi: 10 dk, yalnız o oturum
BETIK_HATA_ESIGI, BETIK_BEKLEME_SN = 5, 900
CANLI_TEST_UST_SN = 120                   # önyüzde canlı test bir isteği en fazla bu kadar tutar
AZAMI_AKIS = 50
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class ApiHatasi(Exception):
    def __init__(self, kod, mesaj):
        super().__init__(mesaj)
        self.kod = kod


class KontrolApi(Eklenti):
    AD = "kontrol"

    def __init__(self):
        super().__init__()
        self.yap = Yapilandirma(self.db, self.hdb)
        self.kullanicilar = Kullanicilar(self.b.dosya.parent / "kullanicilar.json")
        self.oturumlar = {}                 # jeton → {ad, rol, bitis}
        self.hatali = {}                    # ad → [sayı, kilit_bitis, son_deneme]
        self.betik_hatali = {}              # süper yönetici şifresi: ad → [sayı, bekleme_bitis, son_deneme]
        self.kilit = threading.Lock()
        self.anlik = {}                     # son durum özeti (her 1 sn)
        self.anlik_surum = 0
        self.anlik_kosul = threading.Condition()
        self.akis_sayisi = 0
        self.sunucu = None
        self.port = None

    def bilgi(self) -> dict:
        return {"adres": self.b.kontrol_adres, "port": self.port, "oturum": len(self.oturumlar),
                "akis": self.akis_sayisi}

    # ================================================================ yaşam döngüsü
    def calis(self):
        api = self

        class Isleyici(_Isleyici):
            a = api

        self.sunucu = ThreadingHTTPServer((self.b.kontrol_adres, self.b.kontrol_port), Isleyici)
        self.sunucu.daemon_threads = True
        self.port = self.sunucu.server_address[1]
        self.izinli_adlar = self._izinli_adlar()
        if self.b.kontrol_adres not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(f"kontrol arayüzü ağa açık ({self.b.kontrol_adres}) ve şifrelemesiz (HTTP): giriş bilgileri ağda düz "
                           f"metin gider. Yalnız güvenilir ağda kullanın ya da önüne TLS'li bir ters vekil koyun.")
            loglama.olay("KONTROL_AGA_ACIK", adres=self.b.kontrol_adres, izinli=",".join(sorted(self.izinli_adlar)))
        threading.Thread(target=self.sunucu.serve_forever, name="http", daemon=True).start()
        logger.info(f"kontrol arayüzü: http://{self.b.kontrol_adres}:{self.port}/")
        loglama.olay("KONTROL_BASLADI", adres=self.b.kontrol_adres, port=self.port)
        if self.kullanicilar.ilk_kurulum():
            logger.warning("hiç kullanıcı yoktu: varsayılan 'admin' hesabı oluşturuldu, önyüzden şifresini değiştirin")
            self.hdb.denetim_yaz("KULLANICI_VARSAYILAN", "admin", yeni={"rol": "YONETICI"}, kullanici="sistem",
                                 kaynak="kontrol")
        self.db.alarm_kapat("kontrol:kullanici_yok")
        sonraki_sifre_kontrol = 0.0
        while not self.durmali():
            self.ilerle()
            self.ayar.tazele()
            if time.monotonic() >= sonraki_sifre_kontrol:
                sonraki_sifre_kontrol = time.monotonic() + 5
                self._varsayilan_sifre_alarmi()
            try:
                self._anlik_guncelle()
            except Exception:
                logger.exception("durum özeti hazırlanamadı")
            self._oturum_temizle()
            self.bekle(1.0)
        self.sunucu.shutdown()

    def _varsayilan_sifre_alarmi(self):
        adlar = self.kullanicilar.varsayilan_kullananlar()
        if adlar:
            self.db.alarm_ac("kontrol:varsayilan_sifre", f"Varsayılan şifre kullanılıyor ({', '.join(adlar)}). "
                             "Sağ üstteki kullanıcı adına tıklayıp 'Şifre değiştir' ile değiştirin.",
                             AlarmSeviye.UYARI, "kontrol")
        else:
            self.db.alarm_kapat("kontrol:varsayilan_sifre")

    def _anlik_guncelle(self):
        yeni = self.durum()
        yeni.pop("zaman", None)
        imza = json.dumps(yeni, sort_keys=True, default=str)
        if imza != getattr(self, "_son_imza", None):
            self._son_imza = imza
            yeni["zaman"] = time.time()
            with self.anlik_kosul:
                self.anlik = yeni
                self.anlik_surum += 1
                self.anlik_kosul.notify_all()

    def _izinli_adlar(self) -> set:
        adlar = {"127.0.0.1", "localhost", "::1"} | set(self.b.kontrol_izinli_adlar)
        a = self.b.kontrol_adres.lower()
        if a in ("0.0.0.0", "::", ""):                     # tüm arayüzler: makinenin adları ve adresleri
            ad = socket.gethostname().lower()
            adlar |= {ad, socket.getfqdn().lower()}
            try:
                adlar |= {x[4][0].lower() for x in socket.getaddrinfo(ad, None)}
            except OSError:
                pass
        else:
            adlar.add(a)
        return adlar

    def _oturum_temizle(self):
        simdi = time.time()
        with self.kilit:
            for j in [j for j, o in self.oturumlar.items() if o["bitis"] < simdi]:
                self.oturumlar.pop(j, None)
            for ad in [a for a, (_, bitis, son) in self.hatali.items() if bitis < simdi and son < simdi - 900]:
                self.hatali.pop(ad, None)                   # 15 dk dokunulmamış kayıt: olmayan adlarla tablo şişirilemesin
            for ad in [a for a, (_, bitis, son) in self.betik_hatali.items() if bitis < simdi and son < simdi - 900]:
                self.betik_hatali.pop(ad, None)
            while len(self.hatali) > 10000:
                self.hatali.pop(next(iter(self.hatali)))

    # ================================================================ oturum
    def giris(self, ad, sifre):
        simdi = time.time()
        with self.kilit:
            say, bitis, _ = self.hatali.get(ad, [0, 0, 0])
            if bitis > simdi:
                raise ApiHatasi(429, f"Çok fazla hatalı deneme. {int(bitis - simdi)} sn sonra tekrar deneyin.")
        rol = self.kullanicilar.dogrula(ad, sifre)
        if rol is None:
            with self.kilit:
                say += 1
                self.hatali[ad] = [say, simdi + KILIT_SN if say >= KILIT_ESIGI else 0, simdi]
            self.hdb.denetim_yaz("GIRIS_BASARISIZ", ad, kullanici=str(ad)[:40], kaynak="kontrol")
            time.sleep(0.5)
            raise ApiHatasi(401, "Kullanıcı adı ya da şifre hatalı.")
        jeton = secrets.token_urlsafe(32)
        with self.kilit:
            self.hatali.pop(ad, None)
            self.oturumlar[jeton] = {"ad": ad, "rol": rol, "bitis": simdi + OTURUM_OMRU_SN}
        self.hdb.denetim_yaz("GIRIS", ad, yeni={"rol": rol}, kullanici=ad, kaynak="kontrol")
        return jeton, rol

    def oturum(self, jeton):
        with self.kilit:
            o = self.oturumlar.get(jeton)
            if o and o["bitis"] > time.time():
                return o
        return None

    # ================================================================ durum özeti
    def durum(self) -> dict:
        db = self.db
        simdi = time.time()
        eklentiler = [dict(r) for r in db.oku("SELECT * FROM eklenti ORDER BY ad")]
        for e in eklentiler:
            e["bilgi"] = json.loads(e["bilgi"] or "{}")
        teslim_bilgi = next((e["bilgi"] for e in eklentiler if e["ad"] == "teslim"), {})
        yolda = teslim_bilgi.get("yolda", {})
        sayim = {}
        for r in db.oku("SELECT hedef_id, durum, COUNT(*) n FROM tetik WHERE durum IN (?,?,?,?,?) GROUP BY hedef_id, durum",
                        (TetikDurum.BEKLIYOR, TetikDurum.DENENIYOR, TetikDurum.TEKRAR, TetikDurum.LOKALDE,
                         TetikDurum.ERITILIYOR)):
            sayim.setdefault(r["hedef_id"], {})[r["durum"]] = r["n"]
        hedefler = []
        for h in db.oku("SELECT * FROM hedef ORDER BY ad"):
            h = dict(h)
            h["ayrintilar"] = _ozet_ayrinti(json.loads(h["ayrintilar"] or "{}"))
            s = sayim.get(h["id"], {})
            h.update(bekleyen=s.get("BEKLIYOR", 0) + s.get("TEKRAR", 0), deneniyor=s.get("DENENIYOR", 0),
                     tekrar=s.get("TEKRAR", 0), lokalde=s.get("LOKALDE", 0), eritiliyor=s.get("ERITILIYOR", 0),
                     yolda=yolda.get(str(h["id"]), 0))
            hedefler.append(h)
        dizin_say = {r["dizin_id"]: r["n"] for r in db.oku(
            # kısmi indeks (yalnızca dizinde duranlar, dizin_id sıralı): istatistik (ANALYZE) olmasa da seçilsin
            "SELECT dizin_id, COUNT(*) n FROM dosya INDEXED BY ux_dosya_aktif WHERE kalkma_zamani IS NULL GROUP BY dizin_id")}
        yuk_say = {r["dizin_id"]: (r["n"], r["askida"]) for r in db.oku(
            "SELECT dizin_id, COUNT(*) n, SUM(durum='ASKIDA') askida FROM yukleme GROUP BY dizin_id")}
        kural_say, kural_liste = {}, {}
        for r in db.oku("SELECT k.id, k.dizin_id, k.ad, k.aktif, k.kapatma_modu, h.ad hedef_ad FROM kural k "
                        "LEFT JOIN hedef h ON h.id=k.hedef_id ORDER BY k.sira, k.id"):
            n, kapali = kural_say.get(r["dizin_id"], (0, 0))
            kural_say[r["dizin_id"]] = (n + 1, kapali + (0 if r["aktif"] else 1))
            kural_liste.setdefault(r["dizin_id"], []).append({"id": r["id"], "ad": r["ad"], "aktif": r["aktif"],
                                                              "kapatma_modu": r["kapatma_modu"], "hedef_ad": r["hedef_ad"]})
        dizinler = []
        for d in db.oku("SELECT * FROM dizin ORDER BY id"):
            d = dict(d)
            d.update(aktif_dosya=dizin_say.get(d["id"], 0), yukleniyor=yuk_say.get(d["id"], (0, 0))[0],
                     askida=yuk_say.get(d["id"], (0, 0))[1] or 0, kural_sayisi=kural_say.get(d["id"], (0, 0))[0],
                     kapali_kural=kural_say.get(d["id"], (0, 0))[1] or 0, kurallar=kural_liste.get(d["id"], []))
            dizinler.append(d)
        son = db.oku("SELECT sure_ms, sla_ihlali FROM tetik WHERE durum='ILETILDI' AND sure_ms IS NOT NULL AND eritildi=0 "
                      "ORDER BY iletildi_zamani DESC LIMIT 200")
        sureler = [r[0] for r in son]
        sla = {"n": len(sureler), "ort": sum(sureler) / len(sureler) if sureler else None,
               "azami": max(sureler) if sureler else None, "ihlal": sum(r[1] for r in son)}
        p95 = sorted(sureler)[int(len(sureler) * 0.95) - 1] if len(sureler) >= 20 else (max(sureler) if sureler else None)
        from datetime import datetime
        son_bakim = db.meta_al("son_bakim_sonucu")
        return {
            "zaman": simdi,
            "motor": bool(self.ayar.al("motor_aktif")),
            "eklentiler": eklentiler,
            "hedefler": hedefler,
            "dizinler": dizinler,
            "sayilar": {**db.sayaclar(),
                        "lokalde": sum(h["lokalde"] for h in hedefler),
                        "bekleyen": sum(h["bekleyen"] for h in hedefler),
                        "yukleniyor": sum(d["yukleniyor"] for d in dizinler),
                        "askida": sum(d["askida"] for d in dizinler),
                        "cozulmemis": self.hdb.cozulmemis_sayisi()},
            "sla": {"n": sla["n"], "ort_ms": int(sla["ort"]) if sla["ort"] else None, "p95_ms": p95,
                    "azami_ms": sla["azami"], "ihlal": sla["ihlal"] or 0, "hedef_sn": self.ayar.al("sla_hedef_sn")},
            "alarmlar": [dict(a) for a in db.aktif_alarmlar()],
            "bakim": {"son": json.loads(son_bakim) if son_bakim else None,
                      "suruyor": json.loads(db.meta_al("bakim_suruyor") or "null"),
                      "gun": self.ayar.al("bakim_gunu"), "saat": self.ayar.al("bakim_saati"),
                      "gecmis_limit": self.ayar.al("gecmis_limit"), "hata_limit": self.ayar.al("hata_limit"),
                      "sonraki": sonraki_planli_zaman(datetime.now(), self.ayar.al("bakim_gunu"),
                                                      self.ayar.al("bakim_saati")).timestamp()},
        }


def _duz(v):
    """sqlite3.Row ve iç içe yapıları JSON'a çevrilebilir hâle getirir."""
    import sqlite3
    if isinstance(v, sqlite3.Row):
        return {k: v[k] for k in v.keys()}
    if isinstance(v, (list, tuple)):
        return [_duz(x) for x in v]
    if isinstance(v, dict):
        return {k: _duz(x) for k, x in v.items()}
    return v


def _gizle(ayrinti: dict) -> dict:
    """Önyüze giden hedef ayrıntıları: düz sır hiç yoktur; uygulamada şifreli (dpapi) referans maskelenir, yerine
    '…_kayitli' ve '…_kaynagi' gelir. Beklenmedik düz sır alanı olursa o da maskelenir."""
    return {k: ("••••" if any(x in k.lower() for x in ("sifre", "password", "anahtar", "key")) and
                not k.endswith(("_ref", "_kayitli", "_kaynagi")) and k not in GORUNUR_ALANLAR else v)
            for k, v in sirlari_gizle(ayrinti).items()}


GORUNUR_ALANLAR = {"anahtar_basligi", "anahtar_on_eki"}          # adında 'anahtar' geçen ama sır olmayan alanlar


def _ozet_ayrinti(ayrinti: dict) -> dict:
    """Liste / durum özeti için: betiğin metni (200 KB'a kadar) her saniye gönderilmez; satır sayısı yeter."""
    a = _gizle(ayrinti)
    if "kod" in a:
        a["kod_satir"] = len(str(a.pop("kod") or "").splitlines())
    return a


# ==================================================================== HTTP işleyici
class _Isleyici(BaseHTTPRequestHandler):
    a: KontrolApi = None
    protocol_version = "HTTP/1.1"
    timeout = 60                        # yavaş / boşta bağlantı bir iş parçacığını süresiz tutmasın
    server_version = "FileWatcherPro"
    sys_version = ""

    def log_message(self, *args):
        pass

    # ------------------------------------------------------------ yanıt yardımcıları
    def _baslik_guvenlik(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, kod, veri, cerez=None):
        b = json.dumps(_duz(veri), ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        if cerez is not None:
            self.send_header("Set-Cookie", cerez)
        self._baslik_guvenlik()
        self.end_headers()
        self.wfile.write(b)

    def _govde(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiHatasi(400, "geçersiz Content-Length") from None
        if n < 0:
            raise ApiHatasi(400, "geçersiz Content-Length")
        if n > 1_000_000:
            raise ApiHatasi(413, "istek çok büyük")
        if not n:
            return {}
        try:
            v = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiHatasi(400, "geçersiz JSON") from None
        if not isinstance(v, dict):
            raise ApiHatasi(400, "gövde bir JSON nesnesi olmalı")
        return v

    def _jeton(self):
        for parca in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parca.strip().partition("=")
            if k == "fwp_oturum":
                return v
        return None

    def _yetki(self, gereken: str):
        o = self.a.oturum(self._jeton())
        if o is None:
            raise ApiHatasi(401, "Oturum yok ya da süresi doldu; lütfen giriş yapın.")
        if not rol_yeterli(o["rol"], gereken):
            raise ApiHatasi(403, f"Bu işlem için '{gereken}' yetkisi gerekiyor (sizin rolünüz: {o['rol']}).")
        return o

    # ------------------------------------------------------------ yönlendirme
    def do_GET(self):
        self._isle("GET")

    def do_POST(self):
        self._isle("POST")

    def do_PUT(self):
        self._isle("PUT")

    def do_DELETE(self):
        self._isle("DELETE")

    def _ad_izinli(self, deger: str, port_gerekli: bool) -> bool:
        """'ad:port' ya da '[::1]:port' bu sunucuyu mu gösteriyor? (DNS rebinding: kötü bir site kendi alan adını
        127.0.0.1'e çözdürüp tarayıcıdan bu arayüze aynı kaynakmış gibi istek atamasın.)"""
        deger = (deger or "").strip().lower()
        if deger.startswith("["):
            ad, _, kalan = deger[1:].partition("]")
            port = kalan[1:] if kalan.startswith(":") else ""
        else:
            ad, _, port = deger.rpartition(":") if deger.count(":") == 1 else (deger, "", "")
        if port and port != str(self.a.port):
            return False
        if port_gerekli and not port and self.a.port != 80:
            return False
        return ad in self.a.izinli_adlar

    def _isle(self, yontem):
        u = urlsplit(self.path)
        yol, sorgu = u.path, {k: v[-1] for k, v in parse_qs(u.query).items()}
        try:
            if not self._ad_izinli(self.headers.get("Host"), True):
                raise ApiHatasi(421, "Host başlığı bu sunucuyu göstermiyor (izinli adlar: config\\baslangic.json > kontrol_izinli_adlar).")
            koken = self.headers.get("Origin")
            if yontem != "GET" and koken and not self._ad_izinli(urlsplit(koken).netloc, False):
                raise ApiHatasi(403, "başka bir siteden gelen istek reddedildi")
            if not yol.startswith("/api/"):
                if yontem != "GET":
                    raise ApiHatasi(405, "izin verilmeyen yöntem")
                return self._statik(yol)
            if yontem != "GET" and self.headers.get("X-FWP") != "1":
                raise ApiHatasi(403, "eksik güvenlik başlığı")
            for y, desen, fn, rol in ROTALAR:
                if y != yontem:
                    continue
                m = re.fullmatch(desen, yol)
                if m:
                    oturum = None if rol is None else self._yetki(rol)
                    govde = self._govde() if yontem in ("POST", "PUT") else {}
                    sonuc = fn(self, oturum, govde, sorgu, *m.groups())
                    if sonuc is _AKIS:
                        return
                    if isinstance(sonuc, tuple):
                        return self._json(200, sonuc[0], sonuc[1])
                    return self._json(200, sonuc if sonuc is not None else {"tamam": True})
            raise ApiHatasi(404, "bilinmeyen uç nokta")
        except ApiHatasi as e:
            self._json(e.kod, {"hata": str(e)})
        except ValueError as e:                 # doğrulama hataları (Türkçe mesaj)
            self._json(400, {"hata": str(e)})
        except Exception as e:
            logger.exception(f"API hatası: {yontem} {yol}")             # ayrıntı yalnız logda; yanıtta iç bilgi yok
            self._json(500, {"hata": f"beklenmeyen hata ({type(e).__name__}); ayrıntı kontrol eklentisinin logunda"})

    def _statik(self, yol):
        if yol in ("", "/"):
            yol = "/index.html"
        hedef = (ONYUZ / yol.lstrip("/")).resolve()
        if not hedef.is_relative_to(ONYUZ.resolve()) or not hedef.is_file():
            if not (ONYUZ / "index.html").exists():
                b = "<!doctype html><meta charset=utf-8><title>FileWatcherPro</title><p>Önyüz henüz kurulmadı.".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self._baslik_guvenlik()
                self.end_headers()
                self.wfile.write(b)
                return
            raise ApiHatasi(404, "dosya yok")
        b = hedef.read_bytes()
        tur = mimetypes.guess_type(hedef.name)[0] or "application/octet-stream"
        if tur.startswith("text/") or tur in ("application/javascript", "image/svg+xml"):
            tur += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(b)))
        self._baslik_guvenlik()
        self.end_headers()
        self.wfile.write(b)


_AKIS = object()


# ==================================================================== uç noktalar
def _k(o):
    return o["ad"] if o else "sistem"


def _int(v, ad="id"):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiHatasi(400, f"geçersiz {ad}") from None


def u_giris(h, o, g, q):
    jeton, rol = h.a.giris(str(g.get("kullanici", "")), str(g.get("sifre", "")))
    cerez = f"fwp_oturum={jeton}; HttpOnly; SameSite=Strict; Path=/; Max-Age={OTURUM_OMRU_SN}"
    ad = str(g.get("kullanici", ""))
    return {"kullanici": ad, "rol": rol, "varsayilan_sifre": h.a.kullanicilar.varsayilan_mi(ad)}, cerez


def u_cikis(h, o, g, q):
    with h.a.kilit:
        h.a.oturumlar.pop(h._jeton(), None)
    return {"tamam": True}, "fwp_oturum=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"


def u_ben(h, o, g, q):
    return {"kullanici": o["ad"], "rol": o["rol"], "varsayilan_sifre": h.a.kullanicilar.varsayilan_mi(o["ad"])}


def u_oturum(h, o, g, q):
    """Açılış: oturum var mı? 401 üretmez (oturumsuz açılış normaldir; tarayıcı konsolunda hata görünmesin)."""
    o = h.a.oturum(h._jeton())
    return {"oturum": False} if o is None else {"oturum": True, **u_ben(h, o, g, q)}


def u_sifre(h, o, g, q):
    try:
        h.a.kullanicilar.sifre_degistir(o["ad"], str(g.get("eski", "")), str(g.get("yeni", "")))
    except ValueError as e:
        h.a.hdb.denetim_yaz("SIFRE_DEGISTIR_BASARISIZ", o["ad"], kullanici=o["ad"], kaynak="kontrol")
        m = str(e)
        raise ApiHatasi(400, m[:1].upper() + m[1:] + ".") from None
    jeton = h._jeton()
    with h.a.kilit:                                        # şifre değişti: başka yerde açık kalmış oturumlar düşer
        for j in [j for j, x in h.a.oturumlar.items() if x["ad"] == o["ad"] and j != jeton]:
            h.a.oturumlar.pop(j, None)
    h.a.hdb.denetim_yaz("SIFRE_DEGISTIR", o["ad"], kullanici=o["ad"], kaynak="kontrol")
    h.a._varsayilan_sifre_alarmi()
    return {"tamam": True}


def u_durum(h, o, g, q):
    if q.get("taze"):                                   # bir işlemden hemen sonra: 1 sn'lik özeti beklemeden
        return h.a.durum()
    return h.a.anlik or h.a.durum()


def u_akis(h, o, g, q):
    """Server-Sent Events: durum özeti değiştikçe gönderilir (en geç 15 sn'de bir canlılık satırı)."""
    a = h.a
    with a.kilit:
        if a.akis_sayisi >= AZAMI_AKIS:
            raise ApiHatasi(503, "çok fazla açık canlı akış")
        a.akis_sayisi += 1
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h._baslik_guvenlik()
        h.end_headers()
        surum = -1
        while not a.durmali():
            with a.anlik_kosul:
                if a.anlik_surum == surum:
                    a.anlik_kosul.wait(15)
                veri, surum_yeni = a.anlik, a.anlik_surum
            if a.oturum(h._jeton()) is None:
                h.wfile.write(b"event: oturum\ndata: {}\n\n")
                h.wfile.flush()
                break
            if surum_yeni != surum:
                surum = surum_yeni
                h.wfile.write(f"data: {json.dumps(veri, ensure_ascii=False, default=str)}\n\n".encode("utf-8"))
            else:
                h.wfile.write(b": canli\n\n")
            h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        with a.kilit:
            a.akis_sayisi -= 1
    return _AKIS


# ------------------------------------------------------------ listeler
def u_dosyalar(h, o, g, q):
    lim = min(_int(q.get("limit", 200), "limit"), 500)
    kosul, par = ["1=1"], []
    if q.get("dizin"):
        kosul.append("d.dizin_id=?")
        par.append(_int(q["dizin"], "dizin"))
    if q.get("ara"):
        kosul.append("d.dosya_adi LIKE ?")
        par.append(f"%{q['ara']}%")
    return h.a.db.oku(
        "SELECT d.*, t.id tetik_id, t.durum tetik_durum, t.sure_ms, t.sla_ihlali, t.deneme_sayisi, t.belirsiz, "
        "t.son_hata, t.sebep, k.ad kural_ad, h.ad hedef_ad FROM dosya d "
        "LEFT JOIN tetik t ON t.dosya_id=d.id LEFT JOIN kural k ON k.id=t.kural_id LEFT JOIN hedef h ON h.id=t.hedef_id "
        f"WHERE {' AND '.join(kosul)} ORDER BY d.hazir_zamani DESC LIMIT ?", (*par, lim))


def u_yuklemeler(h, o, g, q):
    return h.a.db.oku("SELECT y.*, d.yol dizin_yolu FROM yukleme y JOIN dizin d ON d.id=y.dizin_id "
                      "ORDER BY y.ilk_gorulme")


def u_tetikler(h, o, g, q):
    kosul, par = ["1=1"], []
    if q.get("id"):
        kosul.append("t.id=?")
        par.append(_int(q["id"], "id"))
    if q.get("durum"):
        kosul.append("t.durum=?")
        par.append(q["durum"])
    if q.get("hedef"):
        kosul.append("t.hedef_id=?")
        par.append(_int(q["hedef"], "hedef"))
    lim = min(_int(q.get("limit", 200), "limit"), 1000)
    return h.a.db.oku(f"SELECT t.*, h.ad hedef_ad, k.ad kural_ad FROM tetik t LEFT JOIN hedef h ON h.id=t.hedef_id "
                      f"LEFT JOIN kural k ON k.id=t.kural_id WHERE {' AND '.join(kosul)} ORDER BY t.olusturma DESC LIMIT ?",
                      (*par, lim))


def u_gonderilemeyen(h, o, g, q):
    kosul, par = ["1=1"], []
    if q.get("cozuldu") in ("0", "1"):
        kosul.append("cozuldu=?")
        par.append(int(q["cozuldu"]))
    if q.get("sebep"):
        kosul.append("sebep=?")
        par.append(q["sebep"])
    lim = min(_int(q.get("limit", 1000), "limit"), 1000)
    return h.a.hdb.oku(f"SELECT * FROM gonderilemeyen WHERE {' AND '.join(kosul)} ORDER BY son_zaman DESC LIMIT ?",
                       (*par, lim))


def u_denetim(h, o, g, q):
    lim = min(_int(q.get("limit", 300), "limit"), 2000)
    return h.a.hdb.oku("SELECT * FROM denetim ORDER BY id DESC LIMIT ?", (lim,))


def u_kesintiler(h, o, g, q):
    return h.a.hdb.oku("SELECT * FROM kesinti ORDER BY id DESC LIMIT 200")


def u_alarmlar(h, o, g, q):
    """Alarmlar: olay kataloğundaki türü, ilgili dizin/hedef ve bu alarm için GERÇEKTEN gönderilmiş mail bilgisiyle."""
    db = h.a.db
    dizin = {r[0]: r[1] for r in db.oku("SELECT id, yol FROM dizin")}
    hedef = {r[0]: r[1] for r in db.oku("SELECT id, ad FROM hedef")}
    kural = {r[0]: (r[1], r[2]) for r in db.oku("SELECT id, ad, dizin_id FROM kural")}
    sonuc = []
    for a in db.oku("SELECT * FROM alarm ORDER BY aktif DESC, son_zaman DESC LIMIT 300"):
        a = dict(a)
        kod, ids = alarm_turu(a["anahtar"])
        a["kategori"] = kod
        a["nesne"] = (dizin.get(ids["dizin"]) if "dizin" in ids else hedef.get(ids["hedef"]) if "hedef" in ids
                      else f"kural {kural[ids['kural']][0]}" if ids.get("kural") in kural else None)
        m = db.tek("SELECT m.kural_ad, m.alicilar, m.gonderim_zamani FROM bildirim_olay b JOIN bildirim_mail m ON m.id=b.mail_id "
                   "WHERE b.olay_anahtar=? AND b.zaman >= ? AND m.durum='GONDERILDI' ORDER BY m.id DESC LIMIT 1",
                   (a["anahtar"], a["ilk_zaman"] - 1))
        a["mail"] = (f"{m['kural_ad']} → {', '.join(json.loads(m['alicilar']))} "
                     f"({time.strftime('%H:%M', time.localtime(m['gonderim_zamani']))})") if m else None
        sonuc.append(a)
    return sonuc


def u_olay_katalogu(h, o, g, q):
    return KATALOG


def _smtp(h) -> dict:
    return json.loads(h.a.db.meta_al("smtp") or "null") or {}


def _smtp_goster(a: dict) -> dict:
    """Önyüze / denetime giden SMTP ayarı: uygulamada şifreli referans gösterilmez; şifrenin kaydı ve kaynağı söylenir."""
    if not a:
        return {}
    d = dict(a)
    ref = d.pop("sifre_ref", "") or ""
    d.update(sifre_kayitli=bool(ref), sifre_kaynagi=kaynak_metni(ref), sifre_ref=ref if ref.startswith(("env:", "wincred:")) else "")
    return d


def u_bildirim(h, o, g, q):
    kural_adi = {r["id"]: f"{r['ad']} ({r['yol']})" for r in
                 h.a.db.oku("SELECT k.id, k.ad, d.yol FROM kural k JOIN dizin d ON d.id=k.dizin_id")}
    kurallar = []
    for r in h.a.db.oku("SELECT * FROM bildirim_kural ORDER BY id"):
        k = dict(r)
        k.update(alicilar=json.loads(k["alicilar"]), olaylar=json.loads(k["olaylar"]),
                 dizinler=None if k["dizinler"] is None else json.loads(k["dizinler"]),
                 kurallar=None if k.get("kurallar") is None else json.loads(k["kurallar"]))
        k["kural_adlari"] = [kural_adi.get(x, f"#{x}") for x in k["kurallar"] or []]
        kurallar.append(k)
    gecmis = [dict(m, kural=m["kural_ad"], alicilar=json.loads(m["alicilar"])) for m in
              h.a.db.oku("SELECT id, zaman, kural_ad, alicilar, konu, olay_sayisi, durum, deneme, hata, gonderim_zamani "
                         "FROM bildirim_mail ORDER BY id DESC LIMIT 100")]
    return {"smtp": _smtp_goster(_smtp(h)), "kurallar": kurallar, "gecmis": gecmis,
            "son_durum": json.loads(h.a.db.meta_al("bildirim_son_durum") or "null")}


def u_smtp_kaydet(h, o, g, q):
    eski = _smtp(h)
    try:
        a = eposta.ayar_dogrula(g, eski)
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None
    h.a.db.meta_yaz("smtp", json.dumps(a, ensure_ascii=False))
    h.a.hdb.denetim_yaz("SMTP_AYARLA", a["sunucu"], eski=_smtp_goster(eski) or None,
                        yeni={**_smtp_goster(a), "sifre_degisti": bool(g.get("sifre"))}, kullanici=_k(o), kaynak="kontrol")
    return _smtp_goster(a)


def u_smtp_dene(h, o, g, q):
    ok, mesaj = eposta.dene(g, eski=_smtp(h))                # şifre alanı boşsa kayıtlı şifreyle dener
    return {"basarili": ok, "mesaj": mesaj}


def u_test_maili(h, o, g, q):
    """Kayıtlı SMTP ayarıyla deneme maili (hemen, bu istekte); sonuç Gönderim geçmişine yazılır."""
    alici = str(g.get("alici") or "").strip()
    if not eposta.eposta_mi(alici):
        raise ApiHatasi(400, "Geçerli bir alıcı adresi girin.")
    a = _smtp(h)
    if not a.get("sunucu"):
        raise ApiHatasi(400, "Önce SMTP ayarlarını kaydedin.")
    konu = "[FileWatcherPro] Test maili"
    govde = (f"Bu bir deneme mailidir. FileWatcherPro bildirimleri bu adrese ulaşabiliyor.\n\nGönderen: {_k(o)} · "
             f"{time.strftime('%d.%m.%Y %H:%M:%S')}\nSunucu: {a['sunucu']}:{a['port']} ({a['guvenlik']})")
    hata = None
    try:
        eposta.gonder(a, [alici], konu, govde)
    except eposta.EpostaHatasi as e:
        hata = str(e)
    simdi = time.time()
    h.a.db.calistir("INSERT INTO bildirim_mail(zaman, kural_ad, alicilar, konu, govde, olay_sayisi, durum, deneme, "
                    "gonderim_zamani, hata) VALUES(?,?,?,?,?,0,?,1,?,?)",
                    (simdi, "(test)", json.dumps([alici]), konu, govde, "HATA" if hata else "GONDERILDI",
                     None if hata else simdi, hata))
    h.a.db.meta_yaz("bildirim_son_durum", json.dumps({"zaman": simdi, "basarili": hata is None, "mesaj": hata or ""}))
    h.a.hdb.denetim_yaz("TEST_MAILI", alici, yeni={"sonuc": hata or "gönderildi"}, kullanici=_k(o), kaynak="kontrol")
    if hata:
        raise ApiHatasi(502, f"Test maili gönderilemedi: {hata}")
    return {"tamam": True}


def _bildirim_kurali(h, g) -> dict:
    ad = str(g.get("ad") or "").strip()
    if not ad:
        raise ApiHatasi(400, "Kural adı boş olamaz.")
    alicilar = [str(x).strip() for x in (g.get("alicilar") or []) if str(x).strip()]
    if not alicilar:
        raise ApiHatasi(400, "En az bir alıcı girin.")
    kotu = [x for x in alicilar if not eposta.eposta_mi(x)]
    if kotu:
        raise ApiHatasi(400, f"Geçersiz e-posta adresi: {', '.join(kotu)}")
    olaylar = list(dict.fromkeys(g.get("olaylar") or []))
    if not olaylar:
        raise ApiHatasi(400, "En az bir olay seçin.")
    bilinmeyen = [x for x in olaylar if x not in KODLAR]
    if bilinmeyen:
        raise ApiHatasi(400, f"Bilinmeyen olay: {', '.join(bilinmeyen)}")
    seviye = str(g.get("seviye") or "UYARI").upper()
    if seviye not in SEVIYE_SIRA:
        raise ApiHatasi(400, "Seviye BILGI, UYARI ya da KRITIK olmalı.")
    dizinler = g.get("dizinler")
    if dizinler is not None:
        dizinler = [_int(x, "dizin") for x in dizinler]
        if not dizinler:
            raise ApiHatasi(400, "'Seçili dizinler' için en az bir dizin işaretleyin.")
        var = {r[0] for r in h.a.db.oku("SELECT id FROM dizin")}
        if set(dizinler) - var:
            raise ApiHatasi(400, "Seçilen dizinlerden biri bulunamadı.")
    kurallar = g.get("kurallar")
    if kurallar is not None:
        kurallar = [_int(x, "kural") for x in kurallar]
        if not kurallar:
            raise ApiHatasi(400, "Kural kapsamı boş olamaz.")
        var = {r[0]: r[1] for r in h.a.db.oku("SELECT id, dizin_id FROM kural")}
        if set(kurallar) - set(var):
            raise ApiHatasi(400, "Bağlanan kural bulunamadı.")
        dizinler = sorted({var[x] for x in kurallar} | set(dizinler or []))   # kuralın dizin olayları da gelsin
    ozet, tekrar = _int(g.get("ozet_dk", 0), "özet süresi"), _int(g.get("tekrar_dk", 60), "tekrar süresi")
    if not 0 <= ozet <= 1440 or not 1 <= tekrar <= 10080:
        raise ApiHatasi(400, "Özet 0–1440 dk, tekrar 1–10080 dk olmalı.")
    return {"ad": ad, "alicilar": json.dumps(alicilar), "olaylar": json.dumps(olaylar), "seviye": seviye,
            "dizinler": None if dizinler is None else json.dumps(dizinler), "ozet_dk": ozet, "tekrar_dk": tekrar,
            "kurallar": None if kurallar is None else json.dumps(kurallar),
            "duzelince": int(bool(g.get("duzelince", True))), "aktif": int(bool(g.get("aktif", True)))}


def u_bildirim_kural_ekle(h, o, g, q):
    k = _bildirim_kurali(h, g)
    simdi = time.time()
    with h.a.db.yaz() as con:
        kid = con.execute(f"INSERT INTO bildirim_kural({', '.join(k)}, olusturma, guncelleme) VALUES({', '.join('?' * len(k))}, ?, ?)",
                          (*k.values(), simdi, simdi)).lastrowid
    h.a.hdb.denetim_yaz("BILDIRIM_KURAL_EKLE", k["ad"], yeni=k, kullanici=_k(o), kaynak="kontrol")
    return {"id": kid}


def u_bildirim_kural_guncelle(h, o, g, q, kural_id):
    eski = h.a.db.tek("SELECT * FROM bildirim_kural WHERE id=?", (_int(kural_id),))
    if eski is None:
        raise ApiHatasi(404, "bildirim kuralı yok")
    k = _bildirim_kurali(h, g)
    with h.a.db.yaz() as con:
        con.execute(f"UPDATE bildirim_kural SET {', '.join(f'{x}=?' for x in k)}, guncelleme=? WHERE id=?",
                    (*k.values(), time.time(), _int(kural_id)))
    h.a.hdb.denetim_yaz("BILDIRIM_KURAL_GUNCELLE", k["ad"], eski=dict(eski), yeni=k, kullanici=_k(o), kaynak="kontrol")


def u_bildirim_kural_sil(h, o, g, q, kural_id):
    eski = h.a.db.tek("SELECT * FROM bildirim_kural WHERE id=?", (_int(kural_id),))
    if eski is None:
        raise ApiHatasi(404, "bildirim kuralı yok")
    h.a.db.calistir("DELETE FROM bildirim_kural WHERE id=?", (_int(kural_id),))
    h.a.hdb.denetim_yaz("BILDIRIM_KURAL_SIL", eski["ad"], eski=dict(eski), kullanici=_k(o), kaynak="kontrol")


def u_alarm_onayla(h, o, g, q, alarm_id):
    a = h.a.db.tek("SELECT * FROM alarm WHERE id=?", (_int(alarm_id),))
    if a is None:
        raise ApiHatasi(404, "alarm yok")
    h.a.db.calistir("UPDATE alarm SET aktif=0, kapanma_zamani=?, onaylayan=? WHERE id=? AND aktif=1",
                    (time.time(), _k(o), a["id"]))
    h.a.hdb.denetim_yaz("ALARM_ONAYLA", a["anahtar"], eski={"mesaj": a["mesaj"]}, kullanici=_k(o), kaynak="kontrol")


# ------------------------------------------------------------ yapılandırma okuma
def u_dizinler(h, o, g, q):
    dizinler = [dict(d) for d in h.a.db.oku("SELECT * FROM dizin ORDER BY id")]
    kurallar = h.a.db.oku("SELECT k.*, h.ad hedef_ad, h.tur hedef_tur FROM kural k LEFT JOIN hedef h ON h.id=k.hedef_id "
                          "ORDER BY sira, id")
    mail = {}                                            # kural id → kurala bağlı (kural penceresinden) alıcılar
    for b in h.a.db.oku("SELECT alicilar, kurallar FROM bildirim_kural WHERE kurallar IS NOT NULL AND aktif=1"):
        for kid in json.loads(b["kurallar"]):
            mail.setdefault(kid, []).extend(x for x in json.loads(b["alicilar"]) if x not in mail.get(kid, []))
    for d in dizinler:
        d["kurallar"] = [dict(k, is_bilgisi=json.loads(k["is_bilgisi"] or "{}"), mail=mail.get(k["id"], []),
                              istek=json.loads(k["istek"]) if k["istek"] else None) for k in kurallar
                         if k["dizin_id"] == d["id"]]
    return dizinler


def u_hedefler(h, o, g, q):
    return [dict(x, ayrintilar=_ozet_ayrinti(json.loads(x["ayrintilar"] or "{}")))
            for x in h.a.db.oku("SELECT * FROM hedef ORDER BY ad")]


def u_hedef_getir(h, o, g, q, hedef_id):
    """Tek hedef, betiğin metni dahil (sırlar maskeli). Betik penceresi bunu açar."""
    x = _hedef_satiri(h, hedef_id)
    return dict(x, ayrintilar=_gizle(x["ayrintilar"]))


def u_ayarlar(h, o, g, q):
    degerler = h.a.ayar.hepsi()
    return [{"anahtar": k, "deger": degerler[k], "varsayilan": t.varsayilan, "grup": t.grup, "aciklama": t.aciklama,
             "tur": t.tur if isinstance(t.tur, str) else t.tur.__name__, "alt": t.alt, "ust": t.ust,
             "secenekler": t.secenekler} for k, t in TANIMLAR.items()]


def u_kullanicilar(h, o, g, q):
    return h.a.kullanicilar.liste()


# ------------------------------------------------------------ yapılandırma değiştirme (YONETICI)
def u_dizin_ekle(h, o, g, q):
    return {"id": h.a.yap.dizin_ekle(g.get("yol"), g.get("ilk_kurulum_modu"), g.get("uzantilar", ""), g.get("ad", ""),
                                     g.get("aktif", True), kullanici=_k(o))}


def u_dizin_guncelle(h, o, g, q, dizin_id):
    return h.a.yap.dizin_guncelle(_int(dizin_id), kullanici=_k(o), **g)


def u_dizin_sil(h, o, g, q, dizin_id):
    h.a.yap.dizin_sil(_int(dizin_id), kullanici=_k(o))


def _betik_hedefi_mi(h, hedef_id) -> bool:
    r = h.a.db.tek("SELECT tur FROM hedef WHERE id=?", (hedef_id,)) if hedef_id is not None else None
    return bool(r) and r["tur"] == "BETIK"


def u_kural_ekle(h, o, g, q):
    if _betik_hedefi_mi(h, _int(g.get("hedef_id"), "hedef_id")):
        _betik_kilidi(o)                         # kural, betiğin hangi dosyalarda çalışacağını belirler
    return {"id": h.a.yap.kural_ekle(_int(g.get("dizin_id"), "dizin_id"), g.get("ad", ""), g.get("regex"),
                                     _int(g.get("hedef_id"), "hedef_id"), bool(g.get("harf_duyarsiz", True)),
                                     _int(g.get("sira", 100), "sira"), g.get("is_bilgisi") or {},
                                     g.get("ornekler") or [], kullanici=_k(o), istek=g.get("istek"))}


def u_kural_guncelle(h, o, g, q, kural_id):
    eski = h.a.db.tek("SELECT hedef_id FROM kural WHERE id=?", (_int(kural_id),))
    if _betik_hedefi_mi(h, _int(g.get("hedef_id"), "hedef_id")) or (eski and _betik_hedefi_mi(h, eski["hedef_id"])):
        _betik_kilidi(o)
    h.a.yap.kural_guncelle(_int(kural_id), g.get("ad", ""), g.get("regex"), _int(g.get("hedef_id"), "hedef_id"),
                           bool(g.get("harf_duyarsiz", True)), _int(g.get("sira", 100), "sira"), g.get("istek"),
                           g.get("ornekler") or [], kullanici=_k(o))


def _hedef_satiri(h, hedef_id):
    x = h.a.db.tek("SELECT * FROM hedef WHERE id=?", (_int(hedef_id, "hedef_id"),))
    if x is None:
        raise ApiHatasi(404, "hedef bulunamadı")
    return dict(x, ayrintilar=json.loads(x["ayrintilar"] or "{}"))


def _maskeli_basliklar(hedef, idem) -> dict:
    a = hedef["ayrintilar"] or {}
    b = {"Content-Type": "application/json", "X-Idempotency-Key": idem}
    tur = a.get("kimlik_turu", "token")
    if hedef["tur"] == "CONTROLM":
        if tur == "token":
            b["Authorization"] = "Bearer •••••• (oturum token'ı; gönderimde alınır)"
        elif tur == "apikey":
            b["x-api-key"] = "••••••"
        return b
    b.update(a.get("basliklar") or {})
    if tur == "basic":
        b["Authorization"] = "Basic ••••••"
    elif tur != "yok" and a.get("anahtar_ref"):
        b[a.get("anahtar_basligi") or "Authorization"] = (a.get("anahtar_on_eki") if a.get("anahtar_on_eki") is not None
                                                          else "Bearer ") + "••••••"
    return b


def u_kurallar_dene(h, o, g, q):
    """Kural penceresi: kuru deneme (isteği oluşturup gösterir, GÖNDERMEZ) ya da onaylı gerçek gönderim (YÖNETİCİ).
    İstek teslimle aynı şablon koduyla oluşturulur; deneme isteği tetik tablosuna girmez, denetime yazılır."""
    gonder = bool(g.get("gonder"))
    if gonder and not rol_yeterli(o["rol"], "YONETICI"):
        raise ApiHatasi(403, "Gerçek gönderim için YONETICI yetkisi gerekir.")
    hedef = _hedef_satiri(h, g.get("hedef_id"))
    dizin = h.a.db.tek("SELECT yol FROM dizin WHERE id=?", (_int(g.get("dizin_id"), "dizin_id"),))
    if dizin is None:
        raise ApiHatasi(404, "dizin bulunamadı")
    ad = str(g.get("ornek_ad") or "").strip()
    if not ad:
        raise ApiHatasi(400, "Deneme için regex'e uyan bir dosya adı seçin.")
    try:
        m = regex_dene(g.get("regex"), bool(g.get("harf_duyarsiz", True)), [ad])[0]          # ayrı süreçte, süre sınırıyla
    except RegexHatasi as e:
        raise ApiHatasi(400, str(e)) from None
    if not m["eslesti"]:
        raise ApiHatasi(400, f"'{ad}' regex'e uymuyor.")
    kayit = h.a.db.tek("SELECT boyut, icerik_hash FROM dosya WHERE dizin_id=? AND dosya_adi=? ORDER BY id DESC LIMIT 1",
                       (_int(g.get("dizin_id")), ad))
    p = {"dosya_adi": ad, "tam_yol": dizin["yol"].rstrip("\\") + "\\" + ad, "dizin": dizin["yol"],
         "boyut": kayit["boyut"] if kayit else 0, "icerik_hash": kayit["icerik_hash"] if kayit else "",
         "kural": str(g.get("ad") or "kural"), "gruplar": m["gruplar"]}
    idem = "deneme-" + secrets.token_hex(8)
    if hedef["tur"] == "BETIK":
        return _kural_betik_denemesi(h, o, g, hedef, p, idem, m["gruplar"], ad, gonder)
    try:
        yontem, yol, govde = istek_olustur(g.get("istek") or {}, istek_degiskenleri(p, idem, hedef["ayrintilar"]))
    except SablonHatasi as e:
        raise ApiHatasi(400, f"istek: {e}") from None
    sonuc = {"yontem": yontem, "url": str(hedef["adres"]).rstrip("/") + yol, "basliklar": _maskeli_basliklar(hedef, idem),
             "govde": json.dumps(govde, ensure_ascii=False, indent=2) if govde is not None else ""}
    if not gonder:
        return sonuc
    from eklentiler.teslim.adaptorler import adaptor_kur
    tetik = {"parametreler": p, "idempotency": idem, "istek": g.get("istek"), "olusturma": time.time()}
    s = adaptor_kur(dict(hedef, ayrintilar=json.dumps(hedef["ayrintilar"]))).gonder(
        tetik, float(hedef.get("timeout_sn") or h.a.ayar.al("cagri_timeout_sn")))
    sonuc["yanit"] = {"basarili": s.tur == "BASARI", "kod": s.http_kodu, "sure_ms": s.sure_ms, "tur": s.tur,
                      "govde": json.dumps(s.cevap, ensure_ascii=False, indent=2)[:4000] if s.cevap else s.mesaj}
    h.a.hdb.denetim_yaz("KURAL_ISTEK_GONDER", str(g.get("ad") or "kural"),
                        yeni={"url": sonuc["url"], "dosya": ad, "sonuc": s.tur, "kod": s.http_kodu}, kullanici=_k(o),
                        kaynak="kontrol")
    return sonuc


def _kural_betik_denemesi(h, o, g, hedef, p, idem, gruplar, ad, gonder):
    """Kural penceresi, betik hedefi: kuru deneme betiğe verilecekleri gösterir; gerçek çalıştırma kilit ister."""
    from eklentiler.teslim.adaptorler.betik import sir_degerleri
    a = hedef["ayrintilar"]
    deg = istek_degiskenleri(p, idem, a)
    try:
        parametreler = parametre_olustur(g.get("istek") or {}, deg)
    except SablonHatasi as e:
        raise ApiHatasi(400, f"ek değerler: {e}") from None
    if not gonder:
        ortam, stdin = betik.ortam_ve_stdin(deg, gruplar, parametreler, {s["ad"]: "" for s in a.get("sirlar") or []},
                                            deneme=False)
        return {"tur": "BETIK", "komut": betik.komut_metni(a.get("dil")), "ortam": betik.gorunur_ortam(ortam),
                "stdin": stdin}
    _betik_kilidi(o)
    try:
        sirlar = sir_degerleri(a)
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None
    ortam, stdin = betik.ortam_ve_stdin(deg, gruplar, parametreler, sirlar, deneme=True)
    sure = min(float(hedef.get("timeout_sn") or 30), CANLI_TEST_UST_SN)
    s = betik.calistir(h.a.b.veri / "betik" / "deneme", a.get("dil"), a.get("kod") or "", ortam, stdin, sure,
                       sirlar.values())
    h.a.hdb.denetim_yaz("BETIK_CANLI_TEST", hedef["ad"], yeni={"dosya": ad, "kural": str(g.get("ad") or ""),
                                                               "sonuc": s.tur, "cikis": s.cikis_kodu, "surum": a.get("surum")},
                        kullanici=_k(o), kaynak="kontrol")
    return {"tur": "BETIK", "komut": betik.komut_metni(a.get("dil")), "ortam": betik.gorunur_ortam(ortam),
            "stdin": stdin, **s.sozluk()}


def u_dizin_ornek_adlar(h, o, g, q, dizin_id):
    """Kural penceresindeki canlı deneme için bu dizinde görülmüş gerçek dosya adları (en yeni 80)."""
    i = _int(dizin_id)
    adlar = [r[0] for r in h.a.db.oku("SELECT dosya_adi FROM yukleme WHERE dizin_id=? ORDER BY ilk_gorulme DESC", (i,))]
    adlar += [r[0] for r in h.a.db.oku("SELECT dosya_adi FROM dosya WHERE dizin_id=? ORDER BY hazir_zamani DESC LIMIT 200", (i,))]
    return list(dict.fromkeys(adlar))[:80]


def _saglik(hedef: dict, timeout: float) -> dict:
    from eklentiler.teslim.adaptorler import adaptor_kur
    t0 = time.perf_counter()
    try:
        ok, mesaj = adaptor_kur(dict(hedef, ayrintilar=json.dumps(hedef["ayrintilar"]))).saglik(timeout)
    except Exception as e:
        ok, mesaj = False, str(e)
    return {"basarili": bool(ok), "mesaj": (("yanıt veriyor · " + mesaj) if ok else mesaj) + " · iş tetiklenmedi",
            "sure_ms": int((time.perf_counter() - t0) * 1000)}


def u_hedef_dene(h, o, g, q, hedef_id):
    return _saglik(_hedef_satiri(h, hedef_id), float(h.a.ayar.al("cagri_timeout_sn")))


def u_hedef_dene_yeni(h, o, g, q):
    """Hedef penceresi: kaydetmeden önce adres ve kimlik denenir (iş tetiklenmez)."""
    adres = str(g.get("adres") or "")
    if not adres.startswith(("http://", "https://")):
        raise ApiHatasi(400, "hedef adresi http:// ya da https:// ile başlamalı")
    return _saglik({"adres": adres, "tur": g.get("tur", "CONTROLM"), "ayrintilar": sirlari_isle(g.get("ayrintilar") or {})},
                   float(h.a.ayar.al("cagri_timeout_sn")))                # yazılan şifre yalnızca bu deneme için


def u_kural_sil(h, o, g, q, kural_id):
    h.a.yap.kural_sil(_int(kural_id), kullanici=_k(o))


def u_hedef_ekle(h, o, g, q):
    if str(g.get("tur") or "").upper() == "BETIK":
        _betik_kilidi(o)
    return {"id": h.a.yap.hedef_ekle(g.get("ad"), g.get("adres"), g.get("tur", "CONTROLM"), g.get("ayrintilar") or {},
                                     g.get("timeout_sn"), g.get("deneme_plani"), g.get("esz_cagri_ust"),
                                     kullanici=_k(o))}


def u_hedef_guncelle(h, o, g, q, hedef_id):
    x = _hedef_satiri(h, hedef_id)
    if x["tur"] == "BETIK":
        _betik_kilidi(o)
    h.a.yap.hedef_guncelle(x["id"], g.get("ad"), g.get("adres"), g.get("ayrintilar") or {}, g.get("tur"),
                           g.get("timeout_sn"), g.get("esz_cagri_ust"), kullanici=_k(o))


def u_hedef_sil(h, o, g, q, hedef_id):
    x = _hedef_satiri(h, hedef_id)
    if x["tur"] == "BETIK":
        _betik_kilidi(o)
    h.a.yap.hedef_sil(x["id"], kullanici=_k(o))
    if x["tur"] == "BETIK":                               # betiğin çalışma klasörü (sürüm klasörleri)
        import shutil
        shutil.rmtree(h.a.b.veri / "betik" / str(x["id"]), ignore_errors=True)


# ------------------------------------------------------------ betik: süper yönetici kilidi, denetim, deneme
def _betik_kilidi(o):
    if (o or {}).get("betik_bitis", 0) <= time.time():
        raise ApiHatasi(403, "Süper yönetici kilidi kapalı: penceredeki kilidi süper yönetici şifresiyle açın.")


def u_lokal_gonder(h, o, g, q):
    """Lokaldeki seçilen tetikleri şimdi gönder (süper yönetici kilidi)."""
    _betik_kilidi(o)
    try:
        return lokal_islem.secilenleri_gonder(h.a.db, h.a.hdb, g.get("idler"), _k(o))
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None


def u_lokal_sil(h, o, g, q):
    """Lokaldeki seçilen tetikleri sil: tutanaklı, arşivli, nedenli (süper yönetici kilidi, yönetici)."""
    _betik_kilidi(o)
    try:
        return lokal_islem.secilenleri_sil(h.a.db, h.a.hdb, g.get("idler"), g.get("neden"), _k(o), h.a.b.veri,
                                           h.a.b.lokal_kayit)
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None


def _betik_durumu(h, o) -> dict:
    kalan = max(0, int((o or {}).get("betik_bitis", 0) - time.time()))
    return {"sifre_tanimli": betik_sifresi.tanimli_mi(betik_sifresi.dosya_yolu(h.a.b.dosya.parent)),
            "kilit_acik": kalan > 0, "kalan_sn": kalan, "diller": betik.diller()}


def u_betik_durum(h, o, g, q):
    return _betik_durumu(h, o)


def u_betik_kilit_ac(h, o, g, q):
    a, ad, simdi = h.a, o["ad"], time.time()
    dosya = betik_sifresi.dosya_yolu(a.b.dosya.parent)
    if not betik_sifresi.tanimli_mi(dosya):
        raise ApiHatasi(400, "Süper yönetici şifresi belirlenmemiş: sunucuda betik_sifresi.bat ile belirleyin.")
    with a.kilit:
        say, bitis, _ = a.betik_hatali.get(ad, [0, 0, 0])
        if bitis > simdi:
            raise ApiHatasi(429, f"Çok fazla hatalı deneme: {int(bitis - simdi) // 60 + 1} dk sonra tekrar deneyin.")
    if not betik_sifresi.dogru_mu(dosya, str(g.get("sifre") or "")):
        with a.kilit:
            say += 1
            a.betik_hatali[ad] = [say, simdi + BETIK_BEKLEME_SN if say >= BETIK_HATA_ESIGI else 0, simdi]
        a.hdb.denetim_yaz("BETIK_KILIDI_HATALI", ad, kullanici=ad, kaynak="kontrol")
        time.sleep(0.5)
        kalan = BETIK_HATA_ESIGI - say
        raise ApiHatasi(403, "Süper yönetici şifresi yanlış. " + (f"Kalan deneme: {kalan}." if kalan > 0
                                                                  else "15 dakika beklemeniz gerekiyor."))
    with a.kilit:
        a.betik_hatali.pop(ad, None)
        o["betik_bitis"] = simdi + BETIK_KILIT_SN
    a.hdb.denetim_yaz("BETIK_KILIDI_ACILDI", ad, kullanici=ad, kaynak="kontrol")
    return _betik_durumu(h, o)


def u_betik_kilitle(h, o, g, q):
    if o.pop("betik_bitis", None):
        h.a.hdb.denetim_yaz("BETIK_KILITLENDI", o["ad"], kullanici=o["ad"], kaynak="kontrol")
    return _betik_durumu(h, o)


def u_betik_denetle(h, o, g, q):
    kod = str(g.get("kod") or "")
    if len(kod) > betik.AZAMI_KOD:
        raise ApiHatasi(400, f"betik en fazla {betik.AZAMI_KOD} karakter olabilir")
    try:
        return betik.sozdizimi_denetle(g.get("dil"), kod)
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None


def u_betik_dene(h, o, g, q):
    """Betik penceresi (kaydetmeden): kuru deneme betiğe verilecekleri gösterir; canlı çalıştırma kilit ister,
    editördeki (kaydedilmemiş) betiği FWP_DENEME=1 ile gerçekten çalıştırır ve denetime yazar."""
    calistir = bool(g.get("calistir"))
    sirlar_g = g.get("sirlar") or []
    if not isinstance(sirlar_g, list):
        raise ApiHatasi(400, "gizli değerler liste olmalı")
    adlar = [str((x or {}).get("ad") or "").strip().upper() for x in sirlar_g]
    try:
        dil, kod, z, _ = betik.tanim_dogrula(g.get("dil"), g.get("kod"), g.get("zaman_asimi_sn"), 1, adlar)
    except ValueError as e:
        raise ApiHatasi(400, str(e)) from None
    ornek = g.get("ornek") or {}
    ad = str(ornek.get("dosya_adi") or "").strip()
    if not ad or any(c in ad for c in '\\/:*?"<>|'):
        raise ApiHatasi(400, "Deneme dosya adı boş olamaz ve yol / geçersiz karakter içeremez.")
    gruplar, parametreler = {}, {}
    for k, v in (ornek.get("ek") or {}).items():
        k = str(k).strip().upper()
        if k.startswith("G_") and len(k) > 2:
            gruplar[k[2:].lower()] = str(v)
        elif k.startswith("P_") and len(k) > 2:
            parametreler[k[2:]] = str(v)
        else:
            raise ApiHatasi(400, f"Ek değer adı G_ (regex grubu) ya da P_ (kural değeri) ile başlamalı: {k}")
    kayitli = {}
    if g.get("hedef_id"):
        x = _hedef_satiri(h, g.get("hedef_id"))
        if x["tur"] == "BETIK":
            kayitli = {s_["ad"]: s_["ref"] for s_ in x["ayrintilar"].get("sirlar") or []}
    sirlar = {}
    for a_, x in zip(adlar, sirlar_g):
        if (x or {}).get("deger"):
            sirlar[a_] = str(x["deger"])
        elif a_ in kayitli and calistir:
            try:
                sirlar[a_] = sir_oku(kayitli[a_])[1]
            except Exception as e:  # noqa: BLE001
                raise ApiHatasi(400, f"'{a_}' gizli değeri okunamadı: {e}") from None
        elif calistir:
            raise ApiHatasi(400, f"'{a_}' gizli değeri için değer girin.")
        else:
            sirlar[a_] = ""
    dizin = "\\\\DENEME\\gelen"
    deg = istek_degiskenleri({"dosya_adi": ad, "tam_yol": f"{dizin}\\{ad}", "dizin": dizin, "boyut": 0,
                              "icerik_hash": "", "kural": "(canlı test)", "gruplar": gruplar},
                             "deneme-" + secrets.token_hex(8), {})
    ortam, stdin = betik.ortam_ve_stdin(deg, gruplar, parametreler, sirlar, deneme=True)
    sonuc = {"komut": betik.komut_metni(dil), "ortam": betik.gorunur_ortam(ortam), "stdin": stdin}
    if not calistir:
        return sonuc
    _betik_kilidi(o)
    s = betik.calistir(h.a.b.veri / "betik" / "deneme", dil, kod, ortam, stdin, min(z, CANLI_TEST_UST_SN),
                       sirlar.values())
    h.a.hdb.denetim_yaz("BETIK_CANLI_TEST", str(g.get("ad") or "(kaydedilmemiş betik)"),
                        yeni={"dosya": ad, "sonuc": s.tur, "cikis": s.cikis_kodu, "surum": betik.surum(dil, kod)},
                        kullanici=_k(o), kaynak="kontrol")
    return {**sonuc, **s.sozluk()}


def u_ayar_degistir(h, o, g, q):
    degisen = {}
    for k, v in g.items():
        dogrula(k, v)                                # önce hepsini doğrula (yarım uygulama olmasın)
    for k, v in g.items():
        eski, yeni = h.a.ayar.degistir(k, v)
        if eski != yeni:
            h.a.hdb.denetim_yaz("AYAR_DEGISTIR", k, eski=eski, yeni=yeni, kullanici=_k(o), kaynak="kontrol")
            degisen[k] = yeni
    return degisen


# ------------------------------------------------------------ operatör eylemleri
def u_hedef_kapat(h, o, g, q, hedef_id):
    h.a.yap.hedef_kapat(_int(hedef_id), g.get("mod", "KAYITLI"), kullanici=_k(o))


def u_hedef_ac(h, o, g, q, hedef_id):
    h.a.yap.hedef_ac(_int(hedef_id), kullanici=_k(o))


def u_toptan_kapat(h, o, g, q):
    ids = [r["id"] for r in h.a.db.oku("SELECT id FROM hedef WHERE aktif=1")]
    for i in ids:
        h.a.yap.hedef_kapat(i, g.get("mod", "KAYITLI"), kullanici=_k(o))
    h.a.hdb.denetim_yaz("TOPTAN_KAPAT", "hedefler", yeni={"mod": g.get("mod", "KAYITLI"), "hedefler": ids},
                        kullanici=_k(o), kaynak="kontrol")
    return {"kapatilan": ids}


def u_toptan_ac(h, o, g, q):
    ids = [r["id"] for r in h.a.db.oku("SELECT id FROM hedef WHERE aktif=0")]
    for i in ids:
        h.a.yap.hedef_ac(i, kullanici=_k(o))
    return {"acilan": ids}


def u_devre_sifirla(h, o, g, q, hedef_id):
    h.a.yap.devre_sifirla(_int(hedef_id), kullanici=_k(o))


def u_erit(h, o, g, q, hedef_id):
    islem = g.get("islem")
    hid = _int(hedef_id)
    if islem == "baslat":
        h.a.yap.erit_baslat(hid, g.get("hiz"), kullanici=_k(o))
    elif islem == "duraklat":
        h.a.yap.erit_duraklat(hid, kullanici=_k(o), neden="kullanıcı duraklattı")
    elif islem == "durdur":
        h.a.yap.erit_durdur(hid, kullanici=_k(o))
    else:
        raise ApiHatasi(400, "islem: baslat | duraklat | durdur")


def u_kural_kapat(h, o, g, q, kural_id):
    h.a.yap.kural_kapat(_int(kural_id), g.get("mod", "KAYITLI"), kullanici=_k(o))


def u_kurallar_toptan_kapat(h, o, g, q):
    dizin = g.get("dizin_id")
    return {"kapatilan": h.a.yap.kurallari_kapat(g.get("mod", "KAYITLI"), None if dizin is None else _int(dizin, "dizin_id"),
                                                 kullanici=_k(o))}


def u_kurallar_toptan_ac(h, o, g, q):
    dizin = g.get("dizin_id")
    return {"acilan": h.a.yap.kurallari_ac(None if dizin is None else _int(dizin, "dizin_id"), kullanici=_k(o))}


def u_kural_ac(h, o, g, q, kural_id):
    h.a.yap.kural_ac(_int(kural_id), kullanici=_k(o))


def u_motor(h, o, g, q):
    if "aktif" not in g:
        raise ApiHatasi(400, "aktif alanı gerekli")
    eski, yeni = h.a.ayar.degistir("motor_aktif", bool(g["aktif"]))
    h.a.hdb.denetim_yaz("MOTOR_" + ("BASLAT" if yeni else "DURDUR"), "motor", eski=eski, yeni=yeni, kullanici=_k(o),
                        kaynak="kontrol")
    return {"motor": yeni}


def u_simdi_dene(h, o, g, q, dizin_id):
    h.a.db.komut_gonder("tarama", "SIMDI_DENE", {"dizin_id": _int(dizin_id)}, kullanici=_k(o))


def u_eklenti(h, o, g, q, ad, islem):
    komut = {"baslat": "BASLAT", "durdur": "DURDUR", "yeniden_baslat": "YENIDEN_BASLAT"}.get(islem)
    if komut is None:
        raise ApiHatasi(400, "islem: baslat | durdur | yeniden_baslat")
    if ad == "kontrol" and komut == "DURDUR":
        raise ApiHatasi(400, "Kontrol eklentisi önyüzden durdurulamaz (önyüz de kapanırdı); yeniden başlatabilirsiniz.")
    if h.a.db.eklenti(ad) is None or ad == "cekirdek":
        raise ApiHatasi(404, "bilinmeyen eklenti")
    return {"komut_id": h.a.db.komut_gonder("gozetmen", komut, {"ad": ad}, kullanici=_k(o))}


def u_komut(h, o, g, q, komut_id):
    k = h.a.db.tek("SELECT * FROM komut WHERE id=?", (_int(komut_id),))
    if k is None:
        raise ApiHatasi(404, "komut yok")
    return dict(k)


def u_bakim(h, o, g, q):
    return {"komut_id": h.a.db.komut_gonder("cekirdek", "BAKIM_YAP", kullanici=_k(o))}


# ==================================================================== yapay zekâ asistanı
_ADB = {}


def _asistan(h):
    """Asistanın deposu (veri\\asistan.db). Eklenti kurulu değilse 404."""
    if h.a.db.eklenti("asistan") is None:
        raise ApiHatasi(404, "Yapay zekâ asistanı eklentisi kurulu değil (config\\baslangic.json).")
    from eklentiler.asistan.depo import AsistanDB, depo_yolu
    yol = depo_yolu(h.a.db.yol)
    if yol not in _ADB:
        _ADB[yol] = AsistanDB(yol).sema_kur()
    return _ADB[yol]


def u_asistan(h, o, g, q):
    from eklentiler.asistan.depo import ozet
    return ozet(_asistan(h), h.a.db)


def _asistan_komut(h, o, komut, parametre=None, islem=None, nesne="asistan"):
    _asistan(h)
    kid = h.a.db.komut_gonder("asistan", komut, parametre, kullanici=_k(o))
    h.a.hdb.denetim_yaz(islem or f"ASISTAN_{komut}", nesne, yeni=parametre or None, kullanici=_k(o), kaynak="kontrol")
    return {"komut_id": kid}


def u_asistan_egit(h, o, g, q):
    return _asistan_komut(h, o, "EGIT")


def u_asistan_kendini_sina(h, o, g, q):
    return _asistan_komut(h, o, "KENDINI_SINA")


def u_asistan_sifirla(h, o, g, q):
    return _asistan_komut(h, o, "SIFIRLA")


def u_asistan_veri_sil(h, o, g, q):
    return _asistan_komut(h, o, "VERI_SIL")


def u_asistan_surum(h, o, g, q, surum):
    return _asistan_komut(h, o, "SURUM_KULLAN", {"surum": _int(surum, "surum")}, nesne=f"sürüm {surum}")


def u_asistan_ayarlar(h, o, g, q):
    from eklentiler.asistan.depo import ayar_yaz, ayarlar_oku
    adb = _asistan(h)
    eski = ayarlar_oku(adb)
    yeni = ayar_yaz(adb, g)                              # ValueError → 400 (Türkçe mesaj)
    degisen = {k: v for k, v in yeni.items() if eski.get(k) != v}
    h.a.db.komut_gonder("asistan", "AYAR", degisen, kullanici=_k(o))
    h.a.hdb.denetim_yaz("ASISTAN_AYAR", "asistan", eski={k: eski[k] for k in degisen} or None, yeni=degisen or None,
                        kullanici=_k(o), kaynak="kontrol")
    return yeni


def u_asistan_geri_bildirim(h, o, g, q, oneri_id):
    adb = _asistan(h)
    durum = "FAYDALI" if g.get("faydali") else "FAYDASIZ"
    n = adb.calistir("UPDATE oneri SET durum=?, isaretleyen=?, kapanma=? WHERE id=? AND durum='ACIK'",
                     (durum, _k(o), time.time(), _int(oneri_id, "oneri_id")))
    if not n:
        raise ApiHatasi(404, "öneri bulunamadı ya da zaten kapanmış")
    r = adb.tek("SELECT tur, baslik FROM oneri WHERE id=?", (_int(oneri_id),))
    h.a.hdb.denetim_yaz("ASISTAN_GERI_BILDIRIM", r["baslik"][:120], yeni={"tur": r["tur"], "durum": durum}, kullanici=_k(o), kaynak="kontrol")
    return {"durum": durum}


def u_izleme(h, o, g, q):
    """Sistem izleme sayfası: izleme eklentisinin son ölçümü + geçmiş (1 saat ham, 24 saat 4 dk ortalama) + eşikler."""
    anlik = json.loads(h.a.db.meta_al("izleme_anlik") or "null")
    if not anlik:
        raise ApiHatasi(503, "Sistem izleme henüz ölçüm yapmadı. İzleme eklentisi çalışıyor mu? (Eklentiler sayfası)")
    simdi = time.time()
    if q.get("aralik") == "24s":
        satirlar = h.a.db.oku("SELECT CAST(zaman/240 AS INTEGER)*240 z, AVG(sunucu_cpu), AVG(sunucu_ram), AVG(fwp_cpu), "
                              "AVG(fwp_ram_mb) FROM olcum WHERE zaman>=? GROUP BY 1 ORDER BY 1", (simdi - 86400,))
    else:
        satirlar = h.a.db.oku("SELECT zaman, sunucu_cpu, sunucu_ram, fwp_cpu, fwp_ram_mb FROM olcum WHERE zaman>=? "
                              "ORDER BY zaman", (simdi - 3600,))
    yuvarla = lambda v, n=1: None if v is None else round(v, n)                      # noqa: E731
    gecmis = {"zaman": [r[0] for r in satirlar], "sunucu_cpu": [yuvarla(r[1]) for r in satirlar],
              "sunucu_ram": [yuvarla(r[2]) for r in satirlar], "fwp_cpu": [yuvarla(r[3], 2) for r in satirlar],
              "fwp_ram": [yuvarla(r[4]) for r in satirlar]}
    esikler = anlik.pop("esikler", [])
    for e in esikler:
        e["mail"] = _mail_kurali_var(h, "KAYNAK_TARAMA" if e["anahtar"] == "tarama_suresi" else
                                     {"sunucu_cpu": "KAYNAK_SUNUCU_CPU", "sunucu_ram": "KAYNAK_SUNUCU_RAM", "disk": "KAYNAK_DISK",
                                      "fwp_cpu": "KAYNAK_FWP_CPU", "fwp_ram": "KAYNAK_FWP_RAM", "log": "KAYNAK_LOG"}.get(e["anahtar"], ""))
    return {"aralik_sn": h.a.ayar.al("izleme_aralik_sn"), "olcum_zamani": anlik.get("zaman"), "simdi": anlik,
            "gecmis": gecmis, "esikler": esikler}


def _mail_kurali_var(h, kategori: str) -> bool:
    """Bu olay türü için açık bir bildirim (mail) kuralı var mı? (bildirim tablosu yoksa False)"""
    try:
        for r in h.a.db.oku("SELECT olaylar FROM bildirim_kural WHERE aktif=1"):
            if kategori in json.loads(r[0] or "[]"):
                return True
    except Exception:
        pass
    return False


def u_bakim_gecmis(h, o, g, q):
    """Son 10 bakımın sonucu (denetim kaydından): zaman, başlatan, sonuç ayrıntısı."""
    satirlar = h.a.hdb.oku("SELECT zaman, kullanici, yeni FROM denetim WHERE islem='BAKIM' ORDER BY id DESC LIMIT 10")
    return [{"zaman": r["zaman"], "kullanici": r["kullanici"], "sonuc": json.loads(r["yeni"] or "null")} for r in satirlar]


def u_regex_dene(h, o, g, q):
    try:
        return regex_dene(g.get("regex"), bool(g.get("harf_duyarsiz", True)), [str(x) for x in (g.get("adlar") or [])][:200])
    except RegexHatasi as e:
        raise ApiHatasi(400, str(e)) from None


I, OP, Y = "IZLEYICI", "OPERATOR", "YONETICI"
ROTALAR = [
    ("POST", r"/api/giris", u_giris, None),
    ("POST", r"/api/cikis", u_cikis, None),
    ("GET", r"/api/oturum", u_oturum, None),
    ("GET", r"/api/ben", u_ben, I),
    ("POST", r"/api/sifre", u_sifre, I),
    ("GET", r"/api/durum", u_durum, I),
    ("GET", r"/api/akis", u_akis, I),
    ("GET", r"/api/dosyalar", u_dosyalar, I),
    ("GET", r"/api/yuklemeler", u_yuklemeler, I),
    ("GET", r"/api/tetikler", u_tetikler, I),
    ("GET", r"/api/gonderilemeyen", u_gonderilemeyen, I),
    ("GET", r"/api/denetim", u_denetim, I),
    ("GET", r"/api/kesintiler", u_kesintiler, I),
    ("GET", r"/api/alarmlar", u_alarmlar, I),
    ("GET", r"/api/dizinler", u_dizinler, I),
    ("GET", r"/api/hedefler", u_hedefler, I),
    ("GET", r"/api/ayarlar", u_ayarlar, I),
    ("GET", r"/api/komut/(\d+)", u_komut, I),
    ("POST", r"/api/regex/dene", u_regex_dene, OP),
    ("POST", r"/api/alarmlar/(\d+)/onayla", u_alarm_onayla, OP),
    ("POST", r"/api/hedefler/(\d+)/kapat", u_hedef_kapat, OP),
    ("POST", r"/api/hedefler/(\d+)/ac", u_hedef_ac, OP),
    ("POST", r"/api/hedefler/(\d+)/devre_sifirla", u_devre_sifirla, OP),
    ("POST", r"/api/hedefler/(\d+)/erit", u_erit, OP),
    ("POST", r"/api/toptan_kapat", u_toptan_kapat, OP),
    ("POST", r"/api/toptan_ac", u_toptan_ac, OP),
    ("POST", r"/api/kurallar/(\d+)/kapat", u_kural_kapat, OP),
    ("POST", r"/api/kurallar/toptan_kapat", u_kurallar_toptan_kapat, OP),
    ("POST", r"/api/lokal/gonder", u_lokal_gonder, OP),
    ("POST", r"/api/lokal/sil", u_lokal_sil, Y),
    ("POST", r"/api/kurallar/toptan_ac", u_kurallar_toptan_ac, OP),
    ("POST", r"/api/kurallar/(\d+)/ac", u_kural_ac, OP),
    ("POST", r"/api/motor", u_motor, OP),
    ("POST", r"/api/dizinler/(\d+)/simdi_dene", u_simdi_dene, OP),
    ("POST", r"/api/eklentiler/([a-z_]+)/(baslat|durdur|yeniden_baslat)", u_eklenti, OP),
    ("POST", r"/api/bakim", u_bakim, OP),
    ("GET", r"/api/bakim/gecmis", u_bakim_gecmis, I),
    ("GET", r"/api/izleme", u_izleme, I),
    ("GET", r"/api/asistan", u_asistan, I),
    ("POST", r"/api/asistan/egit", u_asistan_egit, Y),
    ("POST", r"/api/asistan/kendini_sina", u_asistan_kendini_sina, OP),
    ("POST", r"/api/asistan/sifirla", u_asistan_sifirla, Y),
    ("POST", r"/api/asistan/veri_sil", u_asistan_veri_sil, Y),
    ("POST", r"/api/asistan/surum/(\d+)/kullan", u_asistan_surum, Y),
    ("PUT", r"/api/asistan/ayarlar", u_asistan_ayarlar, Y),
    ("POST", r"/api/asistan/oneriler/(\d+)/geri_bildirim", u_asistan_geri_bildirim, OP),
    ("GET", r"/api/olay_katalogu", u_olay_katalogu, I),
    ("GET", r"/api/bildirim", u_bildirim, I),
    ("PUT", r"/api/bildirim/smtp", u_smtp_kaydet, Y),
    ("POST", r"/api/bildirim/smtp/dene", u_smtp_dene, Y),
    ("POST", r"/api/bildirim/test", u_test_maili, OP),
    ("POST", r"/api/bildirim/kurallar", u_bildirim_kural_ekle, Y),
    ("PUT", r"/api/bildirim/kurallar/(\d+)", u_bildirim_kural_guncelle, Y),
    ("DELETE", r"/api/bildirim/kurallar/(\d+)", u_bildirim_kural_sil, Y),
    ("POST", r"/api/dizinler", u_dizin_ekle, Y),
    ("PUT", r"/api/dizinler/(\d+)", u_dizin_guncelle, Y),
    ("DELETE", r"/api/dizinler/(\d+)", u_dizin_sil, Y),
    ("POST", r"/api/kurallar", u_kural_ekle, Y),
    ("PUT", r"/api/kurallar/(\d+)", u_kural_guncelle, Y),
    ("POST", r"/api/kurallar/dene", u_kurallar_dene, OP),
    ("GET", r"/api/dizinler/(\d+)/ornek_adlar", u_dizin_ornek_adlar, I),
    ("POST", r"/api/hedefler/(\d+)/dene", u_hedef_dene, OP),
    ("POST", r"/api/hedefler/dene", u_hedef_dene_yeni, Y),
    ("DELETE", r"/api/kurallar/(\d+)", u_kural_sil, Y),
    ("POST", r"/api/hedefler", u_hedef_ekle, Y),
    ("GET", r"/api/hedefler/(\d+)", u_hedef_getir, Y),
    ("PUT", r"/api/hedefler/(\d+)", u_hedef_guncelle, Y),
    ("DELETE", r"/api/hedefler/(\d+)", u_hedef_sil, Y),
    ("GET", r"/api/betik/durum", u_betik_durum, OP),
    ("POST", r"/api/betik/kilit", u_betik_kilit_ac, OP),
    ("DELETE", r"/api/betik/kilit", u_betik_kilitle, OP),
    ("POST", r"/api/betik/denetle", u_betik_denetle, Y),
    ("POST", r"/api/betik/dene", u_betik_dene, Y),
    ("PUT", r"/api/ayarlar", u_ayar_degistir, Y),
    ("GET", r"/api/kullanicilar", u_kullanicilar, Y),
]


if __name__ == "__main__":
    KontrolApi.baslat()
