"""Lokal kayıt (spool): Control-M'e gönderilemeyen tetiklerin insan okunur JSON kopyası.

Tetik veritabanında LOKALDE durumuna geçer VE ayrıca buraya yazılır (çift güvence). Veritabanı
kaybolursa teslim eklentisi açılışta bu dosyalardan tetikleri geri yükler (ice_aktar).

Yazım atomiktir: geçici ada yazılır, diske zorlanır (fsync), sonra tek hamlede asıl ada çevrilir
(os.replace). Süreç yazarken ölse bile yarım kayıt dosyası oluşmaz. Okunamayan (bozuk) dosya
karantinaya taşınır.

Yerleşim: veri/lokal_kayit/<hedef>/<YYYYMMDD>/<olusturma_ms>_<idempotency[:16]>.json
"""
import json
import os
import shutil
import time
from pathlib import Path

SURUM = 1


def _guvenli_ad(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))[:60] or "hedef"


class LokalKayit:
    def __init__(self, kok: Path, karantina: Path):
        self.kok = Path(kok)
        self.karantina = Path(karantina)
        self.kok.mkdir(parents=True, exist_ok=True)
        self.karantina.mkdir(parents=True, exist_ok=True)

    def yol(self, hedef_ad: str, olusturma: float, idempotency: str) -> Path:
        gun = time.strftime("%Y%m%d", time.localtime(olusturma))
        return self.kok / _guvenli_ad(hedef_ad) / gun / f"{int(olusturma * 1000)}_{idempotency[:16]}.json"

    def yaz(self, kayit: dict) -> str:
        """Atomik yazım; yazılan dosyanın yolunu döner. Hata olursa OSError (çağıran alarm verir)."""
        hedef = self.yol(kayit["hedef"], kayit["olusturma"], kayit["idempotency"])
        hedef.parent.mkdir(parents=True, exist_ok=True)
        gecici = hedef.with_suffix(".tmp")
        veri = json.dumps({"surum": SURUM, **kayit}, ensure_ascii=False, indent=1).encode("utf-8")
        with open(gecici, "wb") as f:
            f.write(veri)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, hedef)
        return str(hedef)

    def oku(self, yol: str) -> dict:
        with open(yol, "rb") as f:
            d = json.loads(f.read().decode("utf-8"))
        for alan in ("idempotency", "hedef", "dosya_adi", "tam_yol", "parametreler", "olusturma"):
            if alan not in d:
                raise ValueError(f"eksik alan: {alan}")
        return d

    def sil(self, yol: str):
        try:
            os.remove(yol)
        except FileNotFoundError:
            pass
        p = Path(yol).parent
        try:
            if p != self.kok and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass

    def karantinaya_al(self, yol: str) -> str:
        hedef = self.karantina / f"{int(time.time() * 1000)}_{Path(yol).name}"
        shutil.move(yol, hedef)
        return str(hedef)

    def tum_dosyalar(self) -> list:
        return sorted(str(p) for p in self.kok.rglob("*.json"))

    def yarim_kalanlari_temizle(self) -> int:
        """Yazım sırasında ölmüş sürecin bıraktığı .tmp dosyaları (asıl kayıt hiç oluşmamıştır)."""
        n = 0
        for p in self.kok.rglob("*.tmp"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n
