"""Loguru kurulumu.

Her süreç (çekirdek ve her eklenti) kendi log dosyasına yazar; birden çok sürecin aynı dosyaya
yazması Windows'ta dönüşüm (rotation) sırasında sorun çıkarır.

Dosya adı: <süreç>_<YYYY-MM-DD>.log. Dönüşüm gün değişince YA DA dosya boyut sınırını aşınca olur
(demo koddaki "her günün logu" niyeti burada gerçekten uygulanır). Eski dosyalar zip'lenir ve
saklama süresinden eskiler silinir.

Olay satırları makinece okunabilir tek biçimdedir:
    EVENT | TÜR | anahtar=değer anahtar=değer ...
"""
import sys
from datetime import date
from pathlib import Path

from loguru import logger

BICIM = ("{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[surec]: <8} | "
         "{name}:{function}:{line} - {message}")


class _GunlukVeBoyutDonusu:
    """Gün değişince ya da dosya `azami_bayt`'ı aşacaksa yeni dosyaya geç."""

    def __init__(self, azami_bayt: int):
        self.azami = azami_bayt
        self.gun = date.today()

    def __call__(self, mesaj, dosya) -> bool:
        gun = mesaj.record["time"].date()
        if gun != self.gun:
            self.gun = gun
            return True
        dosya.seek(0, 2)
        return dosya.tell() + len(mesaj) > self.azami


def kur(surec: str, log_klasoru: Path, saklama_gun: int = 10, azami_mb: int = 50,
        konsol: bool = True, seviye: str = "DEBUG") -> None:
    """Bu sürecin loglamasını kurar. Süreç başında bir kez çağrılır."""
    log_klasoru = Path(log_klasoru)
    log_klasoru.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(extra={"surec": surec})
    if konsol and sys.stderr is not None:
        logger.add(sys.stderr, level="INFO", format=BICIM, colorize=False, enqueue=True)
    logger.add(
        str(log_klasoru / f"{surec}_{{time:YYYY-MM-DD}}.log"),
        level=seviye,
        format=BICIM,
        rotation=_GunlukVeBoyutDonusu(azami_mb * 1024 * 1024),
        retention=f"{int(saklama_gun)} days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,  # hata anında değişken içerikleri loga yazılmasın (gizlilik)
    )


def olay(olay_turu: str, /, **alanlar) -> None:
    """Makinece okunabilir olay satırı: EVENT | TÜR | k=v ... (ilk parametre yalnız konumsal: 'tur' alan adı da
    olabilir; 2026-10-01 saha provası: 'tur=' alanı TypeError verip TEKRAR ve KAYITSIZ_KAPALI olaylarını yutuyordu)."""
    govde = " ".join(f"{k}={_temiz(v)}" for k, v in alanlar.items())
    logger.opt(depth=1).info(f"EVENT | {olay_turu} | {govde}")


def _temiz(v) -> str:
    # satır sonları kaçırılır: dışarıdan gelen metin (ör. sunucu yanıtı, hata mesajı) sahte bir log satırı uyduramasın
    s = str(v).replace("\r", "\\r").replace("\n", "\\n")
    return f'"{s}"' if (" " in s or not s) else s
