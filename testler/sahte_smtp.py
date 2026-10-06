"""YALNIZCA TESTLER: küçük bir sahte SMTP sunucusu (bildirim eklentisi ve önyüzdeki test maili için).

Destekler: EHLO/HELO, AUTH PLAIN / AUTH LOGIN (kullanıcı/şifre tanımlıysa zorunlu, yanlışsa 535), MAIL FROM, RCPT TO
('red@' içeren adres 550 ile reddedilir), DATA, RSET, NOOP, QUIT. STARTTLS yok (testlerde güvenlik 'YOK').
Modlar: 'normal' | 'gecici' (MAIL FROM'a 451: geçici hata) — mod_ayarla ile değişir. durdur() ile bağlantı reddedilir.
Alınan mailler: .mailler (from, to, konu, govde).
"""
import base64
import socketserver
import threading
from email import message_from_bytes, policy


class SahteSMTP:
    def __init__(self, kullanici=None, sifre=None):
        self.kullanici, self.sifre = kullanici, sifre
        self.mailler = []
        self.mod = "normal"
        self.kilit = threading.Lock()
        self.sunucu = None
        self.port = None

    def baslat(self, port=0):
        sahte = self

        class Isleyici(_Isleyici):
            s = sahte

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.sunucu = socketserver.ThreadingTCPServer(("127.0.0.1", port or self.port or 0), Isleyici)
        self.sunucu.daemon_threads = True
        self.port = self.sunucu.server_address[1]
        threading.Thread(target=self.sunucu.serve_forever, daemon=True).start()
        return self

    def durdur(self):
        if self.sunucu:
            self.sunucu.shutdown()
            self.sunucu.server_close()
            self.sunucu = None

    def mod_ayarla(self, mod):
        self.mod = mod

    def ayar(self, **ek) -> dict:
        a = {"sunucu": "127.0.0.1", "port": self.port, "guvenlik": "YOK", "gonderen": "fwp@test.local",
             "gonderen_ad": "FileWatcherPro", "aktif": True}
        if self.kullanici:
            a.update(kullanici=self.kullanici, sifre_ref="env:FWP_TEST_SMTP_SIFRE")
        return {**a, **ek}


class _Isleyici(socketserver.StreamRequestHandler):
    s: SahteSMTP = None

    def yaz(self, satir):
        self.wfile.write((satir + "\r\n").encode())

    def handle(self):
        s = self.s
        self.yaz("220 sahte.smtp ESMTP hazir")
        kimlik = s.kullanici is None
        gonderen, alicilar = None, []
        while True:
            ham = self.rfile.readline()
            if not ham:
                return
            satir = ham.decode("utf-8", "replace").rstrip("\r\n")
            komut = satir[:4].upper()
            if komut in ("EHLO", "HELO"):
                self.wfile.write(b"250-sahte.smtp\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
            elif satir.upper().startswith("AUTH PLAIN"):
                parca = satir.split(" ", 2)
                veri = parca[2] if len(parca) > 2 else (self.yaz("334 ") or self.rfile.readline().decode().strip())
                _, k, p = base64.b64decode(veri).decode().split("\0")
                kimlik = (k, p) == (s.kullanici, s.sifre)
                self.yaz("235 Authentication successful" if kimlik else "535 5.7.8 Authentication credentials invalid")
            elif satir.upper().startswith("AUTH LOGIN"):
                self.yaz("334 VXNlcm5hbWU6")
                k = base64.b64decode(self.rfile.readline().strip()).decode()
                self.yaz("334 UGFzc3dvcmQ6")
                p = base64.b64decode(self.rfile.readline().strip()).decode()
                kimlik = (k, p) == (s.kullanici, s.sifre)
                self.yaz("235 Authentication successful" if kimlik else "535 5.7.8 Authentication credentials invalid")
            elif komut == "MAIL":
                if not kimlik:
                    self.yaz("530 5.7.0 Authentication required")
                elif s.mod == "gecici":
                    self.yaz("451 4.3.0 Gecici hata, sonra deneyin")
                else:
                    gonderen, alicilar = satir.split(":", 1)[1].strip(" <>"), []
                    self.yaz("250 OK")
            elif komut == "RCPT":
                adres = satir.split(":", 1)[1].strip(" <>")
                if "red@" in adres:
                    self.yaz("550 5.1.1 Kullanici yok")
                else:
                    alicilar.append(adres)
                    self.yaz("250 OK")
            elif komut == "DATA":
                self.yaz("354 Veriyi gonderin; . ile bitirin")
                veri = bytearray()
                while True:
                    s_ = self.rfile.readline()
                    if s_ in (b".\r\n", b".\n", b""):
                        break
                    veri += s_[1:] if s_.startswith(b"..") else s_
                m = message_from_bytes(bytes(veri), policy=policy.default)
                with s.kilit:
                    s.mailler.append({"from": gonderen, "to": list(alicilar), "konu": str(m["Subject"]),
                                      "govde": m.get_body(preferencelist=("plain",)).get_content()})
                self.yaz("250 OK kuyruga alindi")
            elif komut == "RSET":
                gonderen, alicilar = None, []
                self.yaz("250 OK")
            elif komut == "NOOP":
                self.yaz("250 OK")
            elif komut == "QUIT":
                self.yaz("221 Hoscakalin")
                return
            else:
                self.yaz("502 Komut bilinmiyor")
