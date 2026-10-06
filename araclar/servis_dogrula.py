"""Kurulu FileWatcherPro servisini hedef makinede doğrular (servis_kur.bat sonunda çağrılır; YÖNETİCİ olarak).

Denetlenenler:
  1. Servis kayıtlı ve çalışıyor (RUNNING), başlangıç türü ve servis hesabı
  2. Çekirdek ve eklentiler 'Çalışıyor', nabızlar taze
  3. Önyüz (kontrol arayüzü) yanıt veriyor
  4. İzlenen dizinlerin erişim durumu (servis hesabı paylaşımı okuyabiliyor mu)
  5. G4/M6: çekirdek süreci bir kez öldürülür → servis yeniden başlatır, eklentiler yeniden kalkar
Sonuç ekrana 'GEÇTİ / KALDI' olarak yazılır; hiçbir ayar ya da dosya değiştirilmez (yalnızca 5. adımdaki
öldürme ve servisin açtığı 'çekirdek yeniden başlatıldı' uyarı alarmı; onu önyüzden onaylayabilirsiniz).

    py -3.11 araclar\\servis_dogrula.py [--oldurme-yok]
"""
import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cekirdek import win  # noqa: E402
from cekirdek.ayarlar import baslangic_oku  # noqa: E402
from cekirdek.db_canli import CanliDB  # noqa: E402

sonuclar = []


def sonuc(ad, gecti, ayrinti=""):
    sonuclar.append(gecti)
    print(f"  [{'GEÇTİ' if gecti else 'KALDI'}] {ad}" + (f" — {ayrinti}" if ayrinti else ""))


def bekle(kosul, sn):
    son = time.time() + sn
    while time.time() < son:
        try:
            v = kosul()
        except Exception:
            v = None
        if v:
            return v
        time.sleep(0.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oldurme-yok", action="store_true", help="5. adımı (çekirdeği öldürme) atla")
    a = ap.parse_args()
    b = baslangic_oku()
    print("FileWatcherPro servis doğrulaması\n")

    # 1. servis
    try:
        import win32service
        import win32serviceutil
        durum = win32serviceutil.QueryServiceStatus("FileWatcherPro")[1]
        sonuc("Servis çalışıyor", durum == win32service.SERVICE_RUNNING, f"durum kodu {durum}")
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        hs = win32service.OpenService(scm, "FileWatcherPro", win32service.SERVICE_QUERY_CONFIG)
        cfg = win32service.QueryServiceConfig(hs)
        tur = {2: "otomatik", 3: "elle", 4: "devre dışı"}.get(cfg[1], str(cfg[1]))
        print(f"         başlangıç: {tur} · hesap: {cfg[7]} · komut: {cfg[3]}")
        if os.sep + "Users" + os.sep in cfg[3] and cfg[7].lower() not in ("localsystem", ".\\localsystem"):
            print("         UYARI: Python ya da proje bir kullanıcı profilinde; servis hesabı bu klasörü okuyamayabilir.")
    except Exception as e:
        sonuc("Servis kayıtlı", False, str(e))
        return 1

    db = CanliDB(b.canli_db)
    # 2. çekirdek ve eklentiler
    def hepsi_calisiyor():
        rows = {r["ad"]: r for r in db.oku("SELECT * FROM eklenti")}
        ok = rows.get("cekirdek") and rows["cekirdek"]["durum"] == "CALISIYOR" and rows["cekirdek"]["pid"] \
            and win.surec_canli(rows["cekirdek"]["pid"])
        ok = ok and all(r["durum"] in ("CALISIYOR", "DURDURULDU") for k, r in rows.items() if k != "cekirdek")
        taze = ok and all(time.time() - (r["son_nabiz"] or 0) < 15 for r in rows.values() if r["durum"] == "CALISIYOR")
        return rows if taze else None
    rows = bekle(hepsi_calisiyor, 60)
    sonuc("Çekirdek ve eklentiler çalışıyor, nabızlar taze", bool(rows),
          ", ".join(f"{k}: {r['durum']}" for k, r in (rows or {r['ad']: r for r in db.oku('SELECT * FROM eklenti')}).items()))
    if not rows:
        print("         Çekirdek açılmadıysa: loglar klasöründeki servis_*.log ve cekirdek_*.log dosyalarına bakın.")
        return 1

    # 3. önyüz
    url = f"http://{b.kontrol_adres}:{b.kontrol_port}/"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            sonuc("Önyüz yanıt veriyor", r.status == 200, url)
    except Exception as e:
        sonuc("Önyüz yanıt veriyor", False, f"{url}: {e}")

    # 4. dizinler
    dizinler = db.oku("SELECT yol, aktif, erisim_durumu, son_hata FROM dizin")
    if not dizinler:
        print("  [ BİLGİ ] Henüz izlenen dizin tanımlı değil (önyüz → Dizinler ve kurallar).")
    for d in dizinler:
        if d["aktif"]:
            r = bekle(lambda: db.tek("SELECT erisim_durumu, son_hata FROM dizin WHERE yol=?", (d["yol"],))
                      if db.tek("SELECT erisim_durumu FROM dizin WHERE yol=?", (d["yol"],))[0] != "BILINMIYOR" else None, 30)
            ok = r is not None and r[0] == "ERISILEBILIR"
            sonuc(f"Dizin erişilebilir: {d['yol']}", ok, "" if ok else f"{r[0] if r else 'taranmadı'} {r[1] if r else ''} "
                  "(servis hesabının paylaşımı okuma yetkisi var mı?)")

    # 5. çekirdek öldürülür → servis geri getirir
    if not a.oldurme_yok:
        eski = rows["cekirdek"]["pid"]
        print(f"\n  Çekirdek (pid {eski}) öldürülüyor; servisin yeniden başlatması bekleniyor...")
        try:
            os.kill(eski, 9)
        except OSError as e:
            sonuc("Çekirdek öldürülebildi", False, f"{e} (yönetici olarak çalıştırın)")
            return 1
        t0 = time.time()
        yeni = bekle(lambda: (r := db.tek("SELECT pid, durum FROM eklenti WHERE ad='cekirdek'")) and r["pid"] != eski
                     and r["durum"] == "CALISIYOR" and win.surec_canli(r["pid"]) and r["pid"], 60)
        sonuc("Servis çekirdeği yeniden başlattı (G4/M6)", bool(yeni), f"{time.time() - t0:.1f} sn · yeni pid {yeni}")
        sonuc("Eklentiler yeniden kalktı", bool(bekle(hepsi_calisiyor, 60)))
        sonuc("Önyüzde 'çekirdek yeniden başlatıldı' uyarısı açıldı",
              bool(bekle(lambda: db.tek("SELECT 1 FROM alarm WHERE anahtar='servis:cekirdek_dustu' AND aktif=1"), 10)),
              "önyüz → Alarmlar → Onayla ile kapatabilirsiniz")

    print(f"\nSONUÇ: {'HEPSİ GEÇTİ' if all(sonuclar) else 'SORUN VAR (yukarıdaki KALDI satırları)'}")
    return 0 if all(sonuclar) else 1


if __name__ == "__main__":
    sys.exit(main())
