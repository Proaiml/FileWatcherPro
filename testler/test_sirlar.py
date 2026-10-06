"""Sır saklama testleri (kullanıcı isteği 2026-09-30: şifre ekrandan girilsin, uygulama kendisi saklasın).

Önyüzden gelen düz şifre Windows DPAPI ile bu makineye bağlı şifrelenir ('dpapi:<base64>'); düz hâli saklanmaz.
Başka süreçte (teslim, bildirim) çözülebilmeli; bozulmuş / başka makineden gelen kayıt anlaşılır hata vermeli.
"""
import subprocess
import sys

import pytest

from cekirdek import sirlar


def test_dpapi_gidis_donus_ve_duz_hal_yok():
    ref = sirlar.sir_sifrele("Çok-Gizli şifre 42")
    assert ref.startswith("dpapi:") and "Gizli" not in ref and "42" not in ref.split(":", 1)[0]
    assert sirlar.sir_oku(ref) == (None, "Çok-Gizli şifre 42")
    assert sirlar.sir_sifrele("Çok-Gizli şifre 42") != ref                   # her şifrelemede farklı (tuzlu)


def test_baska_surec_cozebilir():
    """Teslim ve bildirim eklentileri ayrı süreçtir: kontrol sürecinin sakladığı şifreyi çözebilmeliler."""
    ref = sirlar.sir_sifrele("surecler-arasi-7")
    r = subprocess.run([sys.executable, "-c", f"from cekirdek.sirlar import sir_oku; print(sir_oku({ref!r})[1])"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "surecler-arasi-7", r.stderr


def test_bozuk_kayit_anlasilir_hata():
    with pytest.raises(ValueError, match="yeniden girin"):
        sirlar.sir_oku("dpapi:QUJDREVG")
    with pytest.raises(ValueError, match="yeniden girin"):
        sirlar.sir_oku("dpapi:bu-base64-degil!")


def test_ayrinti_isleme_koruma_ve_gizleme():
    d = sirlar.sirlari_isle({"kimlik_turu": "token", "kullanici": "u", "sifre": "s1"})
    assert "sifre" not in d and d["sifre_ref"].startswith("dpapi:") and sirlar.sir_oku(d["sifre_ref"])[1] == "s1"
    # şifre alanı boş: eski referans korunur; maskeli referans geri gelirse de eski korunur
    assert sirlar.sirlari_isle({"kullanici": "u"}, eski=d)["sifre_ref"] == d["sifre_ref"]
    assert sirlar.sirlari_isle({"kullanici": "u", "sifre_ref": sirlar.GIZLI}, eski=d)["sifre_ref"] == d["sifre_ref"]
    # gelişmiş alan: yalnız env:/wincred:; düz şifre reddedilir
    assert sirlar.sirlari_isle({"apikey_ref": "env:X"})["apikey_ref"] == "env:X"
    with pytest.raises(ValueError, match="'Şifre' alanına"):
        sirlar.sirlari_isle({"sifre_ref": "duz-sifre"})
    g = sirlar.sirlari_gizle(d)
    assert g["sifre_ref"] == sirlar.GIZLI and g["sifre_kayitli"] is True and g["sifre_kaynagi"] == "uygulamada şifreli (bu sunucu)"
    assert d["sifre_ref"] not in str(g)
    assert sirlar.sirlari_gizle({"sifre_ref": "env:A"})["sifre_kaynagi"] == "ortam değişkeni A"
