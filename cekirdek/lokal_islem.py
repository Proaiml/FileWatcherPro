"""Lokal kayıttaki tetikler üzerinde elle işlem: seçerek gönderme ve silme (süper yönetici kilidiyle, önyüzden).

Seçerek gönder: seçilen LOKALDE tetikler normal kuyruğa döner (BEKLIYOR) ve 'elle' işaretlenir. Teslim onları hemen
dener; başarılıysa lokal dosyası silinir, gönderilemeyen kaydı 'ELLE' çözümüyle kapanır; SLA istatistiğine girmez
(erit gibi). Hedef kapalıysa / devre kesikse / yine hata verirse lokale geri döner: kayıp yok.

Sil: yalnız LOKALDE olanlar (o an eritilene dokunulmaz). Neden zorunludur. Sırasıyla:
  1. Tutanak dosyası (veri/lokal_silinen/tutanak_*.json): kim, ne zaman, neden, her tetiğin veritabanı satırı ve lokal
     kayıt içeriği — işlemden ÖNCE, diske zorlanarak (fsync) yazılır; denetim kaydı budansa da durur.
  2. Lokal JSON dosyası lokal_kayit'tan veri/lokal_silinen/<gün>/ altına taşınır (yerinde kalsaydı, tetik satırı ileride
     budanınca açılıştaki geri yükleme onu diriltirdi). Taşınamayan tetik silinmez, nedeniyle raporlanır.
  3. Tetik SILINDI durumuna geçer (bitmiş sayılır), gönderilemeyen kaydı 'ELLE_SILINDI' çözümüyle kapanır,
     denetime tek özet satırı yazılır (tutanak yolu, neden, tetik listesi).
"""
import json
import os
import shutil
import time
from pathlib import Path

from . import loglama
from .model import TetikDurum

AZAMI_SECIM = 5000


def _idler(idler) -> list:
    try:
        l = sorted({int(x) for x in (idler or [])})
    except (TypeError, ValueError):
        raise ValueError("geçersiz tetik kimliği") from None
    if not l:
        raise ValueError("en az bir kayıt seçin")
    if len(l) > AZAMI_SECIM:
        raise ValueError(f"tek seferde en fazla {AZAMI_SECIM} kayıt")
    return l


def _yer(n):
    return ",".join("?" * n)


def secilenleri_gonder(db, hdb, idler, kullanici: str) -> dict:
    idler = _idler(idler)
    simdi = time.time()
    with db.yaz() as con:
        satirlar = [dict(r) for r in con.execute(
            f"SELECT id, dosya_adi, idempotency, hedef_id, kural_id FROM tetik WHERE durum=? AND id IN ({_yer(len(idler))})",
            (TetikDurum.LOKALDE, *idler))]
        if satirlar:
            con.execute(f"UPDATE tetik SET durum=?, sonraki_deneme=?, elle=1, sahip=NULL WHERE durum=? AND id IN "
                        f"({_yer(len(satirlar))})", (TetikDurum.BEKLIYOR, simdi, TetikDurum.LOKALDE, *[r["id"] for r in satirlar]))
    gonderilen = [r["id"] for r in satirlar]
    atlanan = [i for i in idler if i not in set(gonderilen)]
    hdb.denetim_yaz("LOKAL_SECILI_GONDER", f"{len(gonderilen)} tetik", yeni={
        "tetikler": [{"id": r["id"], "dosya": r["dosya_adi"], "idempotency": r["idempotency"], "hedef_id": r["hedef_id"],
                      "kural_id": r["kural_id"]} for r in satirlar],
        "atlanan (artık lokalde değil)": atlanan}, kullanici=kullanici, kaynak="kontrol")
    loglama.olay("LOKAL_SECILI_GONDER", adet=len(gonderilen), atlanan=len(atlanan), kullanici=kullanici)
    return {"gonderilen": gonderilen, "atlanan": atlanan}


def _atomik_yaz(yol: Path, veri: dict):
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    with open(gecici, "wb") as f:
        f.write(json.dumps(veri, ensure_ascii=False, indent=1).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, yol)


def secilenleri_sil(db, hdb, idler, neden: str, kullanici: str, veri: Path, lokal_kok: Path) -> dict:
    idler = _idler(idler)
    neden = " ".join(str(neden or "").split())
    if len(neden) < 5:
        raise ValueError("silme nedeni en az 5 karakter olmalı (tutanağa ve denetime yazılır)")
    simdi = time.time()
    arsiv = Path(veri) / "lokal_silinen"
    gun = arsiv / time.strftime("%Y%m%d", time.localtime(simdi))
    lokal_kok = Path(lokal_kok).resolve()
    silinen, atlanan, kayitlar = [], [], []
    tutanak = arsiv / (f"tutanak_{time.strftime('%Y%m%d_%H%M%S', time.localtime(simdi))}_{int(simdi * 1000) % 1000:03d}_"
                       f"{''.join(c if c.isalnum() else '_' for c in kullanici)[:40]}.json")
    with db.yaz() as con:                              # tek yazma işlemi: teslim bu sırada bu satırları sahiplenemez
        satirlar = [dict(r) for r in con.execute(f"SELECT * FROM tetik WHERE durum=? AND id IN ({_yer(len(idler))})",
                                                  (TetikDurum.LOKALDE, *idler))]
        for r in satirlar:
            icerik, hata = None, None
            if r["lokal_dosya"]:
                try:
                    icerik = json.loads(Path(r["lokal_dosya"]).read_text(encoding="utf-8"))
                except FileNotFoundError:
                    icerik = None
                except (OSError, ValueError) as e:
                    hata = f"lokal kayıt okunamadı: {e}"
            kayitlar.append({"tetik": r, "lokal_kayit": icerik, "okuma_hatasi": hata})
        _atomik_yaz(tutanak, {"zaman": simdi, "zaman_metin": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(simdi)),
                              "kullanici": kullanici, "neden": neden, "istenen": idler, "adet": len(kayitlar),
                              "durum": "BASLADI", "kayitlar": kayitlar})
        for k in kayitlar:
            r = k["tetik"]
            yeni_yol = None
            if r["lokal_dosya"] and Path(r["lokal_dosya"]).exists():
                kaynak = Path(r["lokal_dosya"]).resolve()
                if lokal_kok not in kaynak.parents:
                    atlanan.append({"id": r["id"], "neden": "lokal dosya beklenen klasörde değil"})
                    continue
                try:
                    gun.mkdir(parents=True, exist_ok=True)
                    yeni_yol = gun / kaynak.name
                    shutil.move(str(kaynak), str(yeni_yol))
                except OSError as e:
                    atlanan.append({"id": r["id"], "neden": f"lokal dosya arşive taşınamadı: {e}"})
                    continue
            con.execute("UPDATE tetik SET durum=?, kapanis=?, sahip=NULL, lokal_dosya=?, son_hata=? WHERE id=? AND durum=?",
                        (TetikDurum.SILINDI, simdi, str(yeni_yol) if yeni_yol else None,
                         f"elle silindi ({kullanici}): {neden}"[:500], r["id"], TetikDurum.LOKALDE))
            k["arsiv_yolu"] = str(yeni_yol) if yeni_yol else None
            silinen.append(r)
    for r in silinen:
        hdb.cozuldu_isaretle(r["idempotency"], f"ELLE_SILINDI ({kullanici}): {neden}"[:300])
    secilmeyen = [i for i in idler if i not in {r["id"] for r in satirlar}]
    _atomik_yaz(tutanak, {"zaman": simdi, "zaman_metin": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(simdi)),
                          "kullanici": kullanici, "neden": neden, "istenen": idler, "adet": len(silinen), "durum": "TAMAMLANDI",
                          "silinen": [r["id"] for r in silinen], "atlanan": atlanan,
                          "lokalde_degildi": secilmeyen, "kayitlar": kayitlar})
    hdb.denetim_yaz("LOKAL_SIL", f"{len(silinen)} tetik", yeni={
        "neden": neden, "tutanak": str(tutanak), "atlanan": atlanan, "lokalde_degildi": secilmeyen,
        "tetikler": [{"id": r["id"], "dosya": r["dosya_adi"], "tam_yol": r["tam_yol"], "idempotency": r["idempotency"],
                      "hedef_id": r["hedef_id"], "kural_id": r["kural_id"]} for r in silinen]},
        kullanici=kullanici, kaynak="kontrol")
    loglama.olay("LOKAL_SILINDI", adet=len(silinen), atlanan=len(atlanan), kullanici=kullanici, tutanak=tutanak.name)
    return {"silinen": [r["id"] for r in silinen], "atlanan": atlanan, "lokalde_degildi": secilmeyen,
            "tutanak": str(tutanak)}
