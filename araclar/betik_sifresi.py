"""Süper yönetici (betik) şifresini belirler. Şifre ekranda gizli sorulur, hiçbir yere düz yazılmaz.
Kolay yol: FileWatcherPro klasöründeki betik_sifresi.bat'a çift tıklayın.

    py -3.11 araclar\\betik_sifresi.py            şifreyi belirle / değiştir
    py -3.11 araclar\\betik_sifresi.py durum      belirlenmiş mi, ne zaman, kim
    py -3.11 araclar\\betik_sifresi.py kaldir     şifreyi sil (betik özelliği kapanır)
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cekirdek import betik_sifresi as bs  # noqa: E402
from cekirdek.ayarlar import baslangic_oku  # noqa: E402
from cekirdek.kullanicilar import ASGARI_SIFRE, Kullanicilar  # noqa: E402


def main(argv):
    b = baslangic_oku()
    dosya = bs.dosya_yolu(b.dosya.parent)
    islem = argv[0] if argv else "belirle"
    if islem == "durum":
        i = bs.bilgi(dosya)
        print(f"Belirlenmiş: {i['zaman']} · {i['belirleyen']}" if i["tanimli"]
              else "Süper yönetici şifresi belirlenmemiş: betik özelliği kapalı.")
        return 0
    if islem == "kaldir":
        print("Şifre silindi: betik özelliği kapandı." if bs.kaldir(dosya) else "Zaten belirlenmemişti.")
        return 0
    if islem != "belirle":
        print(__doc__)
        return 1
    if bs.tanimli_mi(dosya):
        i = bs.bilgi(dosya)
        print(f"Şu an belirlenmiş bir şifre var ({i['zaman']} · {i['belirleyen']}); yenisi onun yerine geçer.")
    print(f"Süper yönetici şifresi: betik eklemek, değiştirmek ve çalıştırmak için. En az {ASGARI_SIFRE} karakter;"
          " önyüz şifrelerinden farklı olmalı. Yazarken ekranda görünmez.")
    s1 = getpass.getpass("Şifre: ")
    s2 = getpass.getpass("Şifre (tekrar): ")
    if s1 != s2:
        print("Şifreler aynı değil; hiçbir şey değişmedi.")
        return 1
    try:
        bs.belirle(dosya, s1, Kullanicilar(b.dosya.parent / "kullanicilar.json"))
    except ValueError as e:
        print(f"Kaydedilmedi: {e}.")
        return 1
    print(f"Kaydedildi ({dosya}). Dosyada şifrenin kendisi değil, geri çevrilemez özeti var.")
    print("Önyüzde betik penceresindeki kilidi bu şifreyle açın (10 dakika, yalnız o oturum).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
