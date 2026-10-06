"""Yalnızca testlerde kullanılan eklenti: davranışı veri klasöründeki bir dosyayla değiştirilir.

    davranis_<ad>.txt içeriği:
      normal  → düzgün çalışır
      coker   → istisna fırlatıp düşer
      takil   → ana döngü takılır (nabız thread'i yaşamaya devam eder)
      cik     → os._exit(3) ile aniden çıkar
"""
import os
import time

from cekirdek.eklenti_temel import Eklenti


class Yardimci(Eklenti):
    AD = "yardimci"

    def davranis(self) -> str:
        p = self.b.veri / f"davranis_{self.ad}.txt"
        try:
            return p.read_text(encoding="utf-8").strip() or "normal"
        except OSError:
            return "normal"

    def bilgi(self):
        return {"davranis": self.davranis()}

    def calis(self):
        while not self.durmali():
            d = self.davranis()
            if d == "coker":
                raise RuntimeError("test: bilerek çöktü")
            if d == "takil":
                time.sleep(3600)
            if d == "cik":
                os._exit(3)
            self.ilerle()
            self.bekle(0.1)


if __name__ == "__main__":
    Yardimci.baslat()
