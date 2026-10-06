"""SMTP ile mail gönderimi (bildirim eklentisi ve önyüzdeki 'Test maili' / 'Bağlantıyı dene').

SMTP ayarı (canli.db > meta 'smtp', JSON; düz şifre YOK, yalnızca referans):
  {"sunucu", "port", "guvenlik": "STARTTLS" | "SSL" | "YOK", "kullanici", "sifre_ref": "dpapi:…|wincred:…|env:…",
   "gonderen", "gonderen_ad", "tls_dogrula": true, "aktif": true}
Önyüz şifreyi düz olarak 'sifre' alanında gönderir; ayar_dogrula onu şifreleyip (sirlar.sir_sifrele) referansa çevirir.
"""
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from .sirlar import ref_dogrula, sir_oku, sir_sifrele

GUVENLIK = ("STARTTLS", "SSL", "YOK")
EPOSTA = re.compile(r"^[^@\s;,<>]+@[^@\s;,<>]+\.[^@\s;,<>]+$")


class EpostaHatasi(Exception):
    pass


def eposta_mi(s: str) -> bool:
    return bool(EPOSTA.match(str(s or "").strip()))


def ayar_dogrula(a: dict, eski: dict = None) -> dict:
    """Önyüzden gelen ayar → saklanacak ayar. Şifre: 'sifre' (düz) doluysa şifrelenir; boşsa elle yazılmış
    env:/wincred: referansı; o da boşsa kayıtlı (eski) şifre korunur. Düz şifre dönen sözlükte yoktur."""
    a = dict(a or {})
    sunucu = str(a.get("sunucu") or "").strip()
    if not sunucu:
        raise ValueError("SMTP sunucusu boş olamaz")
    try:
        port = int(a.get("port") or 587)
    except (TypeError, ValueError):
        raise ValueError("port sayı olmalı") from None
    if not 1 <= port <= 65535:
        raise ValueError("port 1–65535 arasında olmalı")
    guvenlik = str(a.get("guvenlik") or "STARTTLS").upper()
    if guvenlik not in GUVENLIK:
        raise ValueError(f"güvenlik şunlardan biri olmalı: {', '.join(GUVENLIK)}")
    gonderen = str(a.get("gonderen") or "").strip()
    if not eposta_mi(gonderen):
        raise ValueError("gönderen adres geçerli bir e-posta adresi olmalı")
    kullanici = str(a.get("kullanici") or "").strip()
    sifre_ref = ""
    if kullanici:
        if a.get("sifre"):
            sifre_ref = sir_sifrele(a["sifre"])
        elif str(a.get("sifre_ref") or "").strip():
            sifre_ref = ref_dogrula(a["sifre_ref"])
        elif (eski or {}).get("sifre_ref"):
            sifre_ref = eski["sifre_ref"]
        else:
            raise ValueError("kullanıcı girildiyse şifre de girilmeli")
    return {"sunucu": sunucu, "port": port, "guvenlik": guvenlik, "kullanici": kullanici, "sifre_ref": sifre_ref,
            "gonderen": gonderen, "gonderen_ad": str(a.get("gonderen_ad") or "FileWatcherPro").strip(),
            "tls_dogrula": bool(a.get("tls_dogrula", True)), "aktif": bool(a.get("aktif", True))}


def _baglan(a: dict, timeout: float) -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    if not a.get("tls_dogrula", True):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        if a["guvenlik"] == "SSL":
            s = smtplib.SMTP_SSL(a["sunucu"], int(a["port"]), timeout=timeout, context=ctx)
        else:
            s = smtplib.SMTP(a["sunucu"], int(a["port"]), timeout=timeout)
            s.ehlo()
            if a["guvenlik"] == "STARTTLS":
                s.starttls(context=ctx)
                s.ehlo()
    except ssl.SSLCertVerificationError as e:
        raise EpostaHatasi(f"TLS sertifikası doğrulanamadı ({e.verify_message}); kurum içi sertifikaysa "
                           f"'TLS sertifikasını doğrula' seçeneğini kapatın") from None
    except (OSError, smtplib.SMTPException) as e:
        raise EpostaHatasi(f"{a['sunucu']}:{a['port']} bağlanılamadı: {e}") from None
    if a.get("kullanici"):
        try:
            sifre = sir_oku(a["sifre_ref"])[1]
        except ValueError as e:
            s.close()
            raise EpostaHatasi(f"şifre okunamadı: {e}") from None
        try:
            s.login(a["kullanici"], sifre)
        except smtplib.SMTPAuthenticationError as e:
            s.close()
            raise EpostaHatasi(f"kimlik doğrulama başarısız ({e.smtp_code}): kullanıcı adını ve şifreyi kontrol edin") from None
        except smtplib.SMTPException as e:
            s.close()
            raise EpostaHatasi(f"oturum açılamadı: {e}") from None
    return s


def dene(a: dict, timeout: float = 10.0, eski: dict = None) -> tuple:
    """Bağlanır, gerekirse TLS + oturum açar; mail GÖNDERMEZ. (başarılı, mesaj). Şifre alanı boşsa kayıtlı şifreyle dener."""
    t0 = time.perf_counter()
    try:
        s = _baglan(ayar_dogrula(a, eski), timeout)
        s.quit()
    except (EpostaHatasi, ValueError) as e:
        return False, str(e)
    return True, (f"{a['sunucu']}:{a['port']} bağlandı, {a.get('guvenlik', 'STARTTLS')}"
                  f"{', oturum açıldı' if a.get('kullanici') else ''} ({int((time.perf_counter() - t0) * 1000)} ms; mail gönderilmedi)")


def gonder(a: dict, alicilar: list, konu: str, govde: str, timeout: float = 20.0) -> list:
    """Tek mail gönderir; hiçbir alıcıya gidemediyse EpostaHatasi (çağıran yeniden dener). Bazı alıcılar reddedildiyse
    diğerlerine gitmiştir: yeniden denemek çift mail üretirdi, reddedilen adresler döndürülür."""
    alicilar = [x.strip() for x in alicilar if eposta_mi(x)]
    if not alicilar:
        raise EpostaHatasi("geçerli alıcı yok")
    m = EmailMessage()
    m["From"] = formataddr((a.get("gonderen_ad") or "FileWatcherPro", a["gonderen"]))
    m["To"] = ", ".join(alicilar)
    m["Subject"] = " ".join(str(konu).split())[:250]        # satır sonu başlık enjeksiyonu / reddi olmasın
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=a["gonderen"].split("@")[-1])
    m.set_content(govde)
    s = _baglan(a, timeout)
    try:
        reddedilen = s.send_message(m)
    except smtplib.SMTPRecipientsRefused as e:
        raise EpostaHatasi(f"alıcılar reddedildi: {', '.join(e.recipients)}") from None
    except (OSError, smtplib.SMTPException) as e:
        raise EpostaHatasi(f"gönderilemedi: {e}") from None
    finally:
        try:
            s.quit()
        except Exception:
            pass
    return sorted(reddedilen or {})
