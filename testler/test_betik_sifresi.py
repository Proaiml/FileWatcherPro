"""Süper yönetici (betik) şifresi: yalnız sunucuda betik_sifresi.bat ile belirlenir, dosyada düz hâli yok."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cekirdek import betik_sifresi as bs
from cekirdek.kullanicilar import Kullanicilar

KOK = Path(__file__).resolve().parent.parent
SIFRE = "ornek-super-sifre-D"


def _cli(tmp_path, monkeypatch, girdiler):
    """araclar\\betik_sifresi.py'yi geçici config klasörüyle, gizli girişi taklit ederek çalıştırır."""
    spec = importlib.util.spec_from_file_location("betik_sifresi_cli", KOK / "araclar" / "betik_sifresi.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "baslangic_oku", lambda: SimpleNamespace(dosya=tmp_path / "config" / "baslangic.json"))
    sira = iter(girdiler)
    monkeypatch.setattr(m.getpass, "getpass", lambda _istem="": next(sira))
    return m


def test_belirle_dogrula_ve_duz_sifre_dosyada_yok(tmp_path):
    d = bs.dosya_yolu(tmp_path)
    assert not bs.tanimli_mi(d) and not bs.dogru_mu(d, SIFRE)          # dosya yok → özellik kapalı
    bs.belirle(d, SIFRE, belirleyen="test")
    assert bs.tanimli_mi(d) and bs.dogru_mu(d, SIFRE)
    assert not bs.dogru_mu(d, SIFRE.lower()) and not bs.dogru_mu(d, "") and not bs.dogru_mu(d, None)
    ham = d.read_bytes()
    for kod in ("utf-8", "utf-16-le"):
        assert SIFRE.encode(kod) not in ham
    v = json.loads(ham)
    assert v["ozet"].startswith("pbkdf2_sha256$200000$") and v["belirleyen"] == "test"
    assert "ozet" not in bs.bilgi(d) and bs.bilgi(d)["tanimli"]          # dışarı yalnız zaman / kim
    bs.belirle(d, "ornek-super-sifre-G", belirleyen="test")             # değiştirme: eskisi geçersiz
    assert not bs.dogru_mu(d, SIFRE) and bs.dogru_mu(d, "ornek-super-sifre-G")
    assert bs.kaldir(d) and not bs.tanimli_mi(d) and not bs.kaldir(d)


def test_kurallar_kisa_varsayilan_ve_onyuz_sifresiyle_ayni_olamaz(tmp_path):
    d = bs.dosya_yolu(tmp_path)
    k = Kullanicilar(tmp_path / "kullanicilar.json")
    k.ekle("deniz", "ornek-arayuz-sifresi-D", "YONETICI")
    for kotu, mesaj in (("kisa", "en az"), ("ADMIN", "en az"), ("ornek-arayuz-sifresi-D", "önyüz kullanıcısının")):
        with pytest.raises(ValueError, match=mesaj):
            bs.belirle(d, kotu, k)
    assert not d.exists()
    bs.belirle(d, SIFRE, k)
    assert bs.dogru_mu(d, SIFRE)


def test_bat_akisi_iki_kez_sorar_uyusmazsa_kaydetmez(tmp_path, monkeypatch, capsys):
    d = bs.dosya_yolu(tmp_path / "config")
    m = _cli(tmp_path, monkeypatch, [SIFRE, SIFRE + "x"])
    assert m.main([]) == 1 and not d.exists()
    assert "aynı değil" in capsys.readouterr().out
    m = _cli(tmp_path, monkeypatch, [SIFRE, SIFRE])
    assert m.main([]) == 0 and bs.dogru_mu(d, SIFRE)
    cikti = capsys.readouterr().out
    assert "Kaydedildi" in cikti and SIFRE not in cikti                  # şifre ekrana da yazılmaz
    assert m.main(["durum"]) == 0 and "Belirlenmiş" in capsys.readouterr().out
    assert m.main(["kaldir"]) == 0 and not d.exists()
    assert m.main(["durum"]) == 0 and "kapalı" in capsys.readouterr().out
