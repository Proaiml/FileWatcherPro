"""Önyüz kullanıcılarını yönetir (şifre ekranda gizli sorulur, hiçbir yere düz yazılmaz).

    py -3.11 araclar\\kullanici.py ekle <ad> <IZLEYICI|OPERATOR|YONETICI>
    py -3.11 araclar\\kullanici.py sil <ad>
    py -3.11 araclar\\kullanici.py liste
    py -3.11 araclar\\kullanici.py varsayilan   (admin / admin hesabını ekler; 'admin' zaten varsa dokunmaz)
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cekirdek.ayarlar import baslangic_oku  # noqa: E402
from cekirdek.kullanicilar import Kullanicilar  # noqa: E402


def main(argv):
    b = baslangic_oku()
    k = Kullanicilar(b.dosya.parent / "kullanicilar.json")
    if not argv or argv[0] == "liste":
        for u in k.liste():
            print(f"{u['ad']:<20} {u['rol']:<10} {'(varsayılan şifre)' if u['varsayilan_sifre'] else ''}")
        return 0
    if argv[0] == "ekle" and len(argv) == 3:
        s1 = getpass.getpass("Şifre (en az 10 karakter): ")
        s2 = getpass.getpass("Şifre (tekrar): ")
        if s1 != s2:
            print("Şifreler aynı değil.")
            return 1
        k.ekle(argv[1], s1, argv[2])
        print(f"'{argv[1]}' eklendi ({argv[2].upper()}).")
        return 0
    if argv[0] == "varsayilan" and len(argv) == 1:
        print("'admin' eklendi (YONETICI, şifre: admin). Önyüzden değiştirin." if k.varsayilan_ekle()
              else "'admin' adlı kullanıcı zaten var; dokunulmadı.")
        return 0
    if argv[0] == "sil" and len(argv) == 2:
        k.sil(argv[1])
        print(f"'{argv[1]}' silindi.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
