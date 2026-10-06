"""Sahte Control-M Automation API sunucusu (testler ve önyüz denemeleri için).

Gerçek API'den taklit edilenler (BMC belgeleri):
  POST /automation-api/session/login   {"username","password"} → {"username","token","version"}
  POST /automation-api/session/logout
  POST /automation-api/run/order       {"ctm","folder","jobs","variables":[{"AD":"değer"}]} → {"runId","statusURI"}
  GET  /automation-api/run/status/<runId>
  GET  /automation-api/config/servers
  Kimlik: "Authorization: Bearer <token>" ya da "x-api-key: <anahtar>"; hata gövdesi {"errors":[{"message","id"}]}
  Bilinen tuhaflık: süresi dolmuş token bazı durumlarda 500 + "Session token is invalid or expired" döner.

Hata modları (yalnızca run/order'a uygulanır; 'adet' verilirse o kadar istekten sonra normale döner):
  normal · yavas (gecikme sn bekle, sonra başarı) · kopma (bağlantıyı cevapsız kapat, işlenmez)
  hata500 · hata503 · hata400 (klasör yok) · hata404 · hata401 (her zaman yetkisiz)
  token_dolu (token geçersiz sayılır → 401; yeniden oturum açınca düzelir)
  token_500 (aynısı ama bilinen tuhaflıkla 500 döner) · hiz_siniri (429 + Retry-After)
  belirsiz (sipariş İŞLENİR ve kaydedilir ama cevap 'gecikme' sn geç gelir → istemci zaman aşımı)
  Sunucunun tamamen kapanması için durdur() / yeniden_baslat().

Yönetim: POST /_sahte/mod {"mod","adet","gecikme"} · GET /_sahte/siparisler · POST /_sahte/sifirla

Tek başına:  py -3.11 -m testler.sahte_controlm --port 9870
"""
import argparse
import json
import random
import socket
import threading
import time
import uuid
from urllib.parse import unquote
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TABAN = "/automation-api"


class SahteControlM:
    def __init__(self, port: int = 0, kullanici="fwp", sifre="gizli", apikey="anahtar-123", kimliksiz=False):
        self.istenen_port = port
        self.kimliksiz = kimliksiz          # yalnızca elle deneme: kimlik doğrulaması yok
        self.kullanici, self.sifre, self.apikey = kullanici, sifre, apikey
        self.kilit = threading.Lock()
        self.siparisler = []          # başarıyla işlenen siparişler
        self.istekler = []            # run/order'a gelen tüm istekler (mod bilgisiyle)
        self.girisler = 0
        self.tokenlar = set()
        self.webhook = []
        self.olaylar = []             # run/event ile eklenen olaylar
        self.mod, self.adet, self.gecikme = "normal", None, 0.0
        self.sunucu = None
        self.port = None

    # ------------------------------------------------------------ yönetim
    def baslat(self):
        sahte = self

        class Isleyici(_Isleyici):
            s = sahte

        self.sunucu = ThreadingHTTPServer(("127.0.0.1", self.port or self.istenen_port), Isleyici)
        self.sunucu.daemon_threads = True
        self.port = self.sunucu.server_address[1]
        threading.Thread(target=self.sunucu.serve_forever, name="sahte-controlm", daemon=True).start()
        return self

    def durdur(self):
        """Control-M tamamen kapandı: bağlantı reddedilir."""
        if self.sunucu:
            self.sunucu.shutdown()
            self.sunucu.server_close()
            self.sunucu = None

    def yeniden_baslat(self):
        self.durdur()
        return self.baslat()

    @property
    def adres(self):
        return f"http://127.0.0.1:{self.port}{TABAN}"

    def mod_ayarla(self, mod="normal", adet=None, gecikme=0.0):
        with self.kilit:
            self.mod, self.adet, self.gecikme = mod, adet, float(gecikme)

    def sifirla(self):
        with self.kilit:
            self.siparisler.clear()
            self.istekler.clear()
            self.webhook.clear()
            self.olaylar.clear()
            self.girisler = 0
            self.mod, self.adet, self.gecikme = "normal", None, 0.0

    def tokenlari_gecersiz_kil(self):
        with self.kilit:
            self.tokenlar.clear()

    def idempotency_sayilari(self) -> Counter:
        with self.kilit:
            return Counter(s["idempotency"] for s in self.siparisler)

    def _mod_al(self):
        with self.kilit:
            mod, gecikme = self.mod, self.gecikme
            if self.adet is not None:
                self.adet -= 1
                if self.adet <= 0:
                    self.mod, self.adet, self.gecikme = "normal", None, 0.0
            return mod, gecikme


class _Isleyici(BaseHTTPRequestHandler):
    s: SahteControlM = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _govde(self):
        n = int(self.headers.get("Content-Length") or 0)
        ham = self.rfile.read(n) if n else b""
        try:
            return json.loads(ham or b"{}")
        except ValueError:
            return None

    def _cevap(self, kod, veri, basliklar=None):
        b = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        for k, v in (basliklar or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _hata(self, kod, mesaj, basliklar=None):
        self._cevap(kod, {"errors": [{"message": mesaj, "id": str(uuid.uuid4())[:8]}]}, basliklar)

    def _yetkili(self) -> bool:
        if self.s.kimliksiz:
            return True
        if self.headers.get("x-api-key") == self.s.apikey:
            return True
        a = self.headers.get("Authorization", "")
        return a.startswith("Bearer ") and a[7:] in self.s.tokenlar

    # ------------------------------------------------------------ yönlendirme
    def do_POST(self):
        g = self._govde()
        s = self.s
        if self.path == "/_sahte/mod":
            s.mod_ayarla(g.get("mod", "normal"), g.get("adet"), g.get("gecikme", 0))
            return self._cevap(200, {"mod": s.mod})
        if self.path == "/_sahte/sifirla":
            s.sifirla()
            return self._cevap(200, {"tamam": True})
        if self.path == "/webhook":
            with s.kilit:
                s.webhook.append({"zaman": time.time(), "govde": g, "yol": self.path,
                                  "idempotency": self.headers.get("X-Idempotency-Key"),
                                  "basliklar": {k.lower(): v for k, v in self.headers.items()}})
            return self._cevap(200, {"alindi": True})
        if self.path == f"{TABAN}/session/login":
            if not g or g.get("username") != s.kullanici or g.get("password") != s.sifre:
                return self._hata(401, "Login failed: wrong username or password")
            token = uuid.uuid4().hex
            with s.kilit:
                s.tokenlar.add(token)
                s.girisler += 1
            return self._cevap(200, {"username": g["username"], "token": token, "version": "9.21.300"})
        if self.path == f"{TABAN}/session/logout":
            return self._cevap(200, {"message": "Successfully logged out"})
        if self.path == f"{TABAN}/run/order":
            return self._siparis(g)
        if self.path.startswith(f"{TABAN}/run/event/"):
            return self._olay(g)
        return self._hata(404, f"Unknown path {self.path}")

    def do_GET(self):
        s = self.s
        if self.path == "/_sahte/siparisler":
            with s.kilit:
                return self._cevap(200, {"siparisler": s.siparisler, "istekler": len(s.istekler)})
        if self.path == f"{TABAN}/config/servers":
            if not self._yetkili():
                return self._hata(401, "Session token is invalid or expired")
            return self._cevap(200, [{"name": "ctmsunucu", "state": "Up"}])
        if self.path.startswith(f"{TABAN}/run/status/"):
            return self._cevap(200, {"statuses": [{"status": "Executing"}]})
        return self._hata(404, f"Unknown path {self.path}")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _olay(self, g):
        """POST /run/event/{server}/{name}/{date}: Control-M'e olay (koşul) ekler; o olayı bekleyen iş başlar."""
        s = self.s
        mod, gecikme = s._mod_al()
        idem = self.headers.get("X-Idempotency-Key")
        parcalar = [unquote(x) for x in self.path[len(f"{TABAN}/run/event/"):].split("/")]
        with s.kilit:
            s.istekler.append({"zaman": time.time(), "mod": mod, "idempotency": idem, "yol": self.path})
        if mod == "kopma":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if not self._yetkili() or mod == "hata401":
            return self._hata(401, "Session token is invalid or expired")
        if len(parcalar) != 3 or not all(parcalar):
            return self._hata(400, "Expected /run/event/{server}/{name}/{date}")
        ctm, ad, tarih = parcalar
        if ctm != "ctmsunucu":
            return self._hata(404, f"Control-M/Server '{ctm}' not found")
        if mod == "hata500":
            return self._hata(500, "Internal Server Error")
        if mod == "hata503":
            return self._hata(503, "Service Unavailable: Control-M/Server is not available")
        if mod == "hiz_siniri":
            return self._hata(429, "Too Many Requests", {"Retry-After": "1"})
        kayit = {"zaman": time.time(), "olay": ad, "tarih": tarih, "ctm": ctm, "govde": g, "idempotency": idem,
                 "yol": self.path}
        with s.kilit:
            s.olaylar.append(kayit)
            s.siparisler.append(kayit)             # çift/kayıp sayımı tek listeden yapılsın
        if mod in ("yavas", "belirsiz"):
            time.sleep(gecikme)
        try:
            self._cevap(200, {"message": f"Event '{ad}' with date '{tarih}' was added"})
        except OSError:
            pass

    def _siparis(self, g):
        s = self.s
        mod, gecikme = s._mod_al()
        idem = self.headers.get("X-Idempotency-Key")
        with s.kilit:
            s.istekler.append({"zaman": time.time(), "mod": mod, "idempotency": idem})
        if mod == "kopma":
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            return
        if mod == "token_dolu" or mod == "token_500":
            s.tokenlari_gecersiz_kil()
        if not self._yetkili() or mod == "hata401":
            if mod == "token_500":
                return self._hata(500, "Session token is invalid or expired")
            return self._hata(401, "Session token is invalid or expired")
        if g is None or not isinstance(g, dict) or not g.get("ctm") or not g.get("folder"):
            return self._hata(400, "Missing mandatory parameters: ctm, folder")
        if mod == "hata500":
            return self._hata(500, "Internal Server Error")
        if mod == "hata503":
            return self._hata(503, "Service Unavailable: Control-M/Server is not available")
        if mod == "hata400":
            return self._hata(400, f"Folder '{g.get('folder')}' does not exist in Control-M/Server '{g.get('ctm')}'")
        if mod == "hata404":
            return self._hata(404, f"Job '{g.get('jobs')}' not found")
        if mod == "hiz_siniri":
            return self._hata(429, "Too Many Requests", {"Retry-After": "1"})
        if mod == "titrek":                                         # ağ/sunucu gecikmesi dalgalı: varış sırası
            time.sleep(random.uniform(0, gecikme))                  # gönderim sırasından sapabilir
        run_id = str(uuid.uuid4())
        with s.kilit:
            s.siparisler.append({"zaman": time.time(), "runId": run_id, "govde": g, "idempotency": idem})
        if mod in ("yavas", "belirsiz"):
            time.sleep(gecikme)
        try:
            self._cevap(200, {"runId": run_id, "statusURI": f"{s.adres}/run/status/{run_id}"})
        except OSError:
            pass                                                   # istemci zaman aşımıyla gitmiş olabilir


def main():
    ap = argparse.ArgumentParser(description="Sahte Control-M Automation API")
    ap.add_argument("--port", type=int, default=9870)
    ap.add_argument("--kimliksiz", action="store_true", help="kimlik doğrulaması isteme (yalnızca elle deneme)")
    a = ap.parse_args()
    s = SahteControlM(a.port, kimliksiz=a.kimliksiz).baslat()
    print(f"Sahte Control-M çalışıyor: {s.adres}")
    print("Kimlik: YOK (önyüzde hedef eklerken 'Kimlik yok (yalnızca deneme)' seçin)" if a.kimliksiz
          else "Kimlik: kullanıcı fwp / şifre gizli, x-api-key anahtar-123 (test değerleri)")
    print("Mod değiştirmek için: POST http://127.0.0.1:%d/_sahte/mod {\"mod\": \"hata503\", \"adet\": 3}" % a.port)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        s.durdur()


if __name__ == "__main__":
    main()
