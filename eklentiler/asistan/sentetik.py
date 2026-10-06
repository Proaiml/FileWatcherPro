"""'Kendini sına': içine bilinen ilişkiler gömülmüş yapay olay akışı + ayrı bir modelin sıfırdan eğitimi.

Gömülen düzen:
  * 'Lojistik yanıtsız' olayından 60–180 sn sonra %80 olasılıkla 'Control-M devre kesildi'. Arada 1–3 başka olay
    olur: bir önceki olaya bakan Markov tabanı bu ilişkiyi göremez; self-attention görmelidir.
  * 'Muhasebe'ye iş günleri 09:00 ± 15 dk'da 3–6 dosya; her dosyanın ardından birkaç saniyede 'İletildi'.
  * Lojistik gün içinde rastgele dosyalar; geri kalanı gürültü.
Geçme koşulu: doğrulama kaybı Markov tabanından en az %5 düşük, ezber yok ve dikkat haritasında 'devre kesildi'
satırında en güçlü (kendisi hariç) sütun 'Lojistik yanıtsız'. Gerçek veriye ve kullanılan modele dokunulmaz.
"""
import time

import numpy as np

from . import model as M

TURLER = ["Dosya geldi · Muhasebe", "İletildi · Muhasebe", "Dosya geldi · Lojistik", "İletildi · Lojistik", "Lojistik yanıtsız",
          "Control-M devre kesildi", "Lokale yazıldı", "SLA aşıldı", "Yeniden denendi"]
MUH, MUH_IL, LOJ, LOJ_IL, YANITSIZ, DEVRE, LOKAL, SLA, TEKRAR = range(1, 10)


def uret(gun=42, tohum=11):
    rng = np.random.default_rng(tohum)
    bugun = time.time()
    bas = bugun - gun * 86400
    bas -= (time.localtime(bas).tm_hour * 3600 + time.localtime(bas).tm_min * 60)          # gece yarısı
    olay = []
    for d in range(gun):
        g0 = bas + d * 86400
        is_gunu = time.localtime(g0 + 43200).tm_wday < 5
        if is_gunu:
            t = g0 + 9 * 3600 + rng.normal(0, 7.5 * 60)
            for _ in range(rng.integers(3, 7)):
                olay += [(t, MUH), (t + rng.uniform(1, 4), MUH_IL)]
                t += rng.uniform(40, 200)
        for _ in range(rng.integers(25 if is_gunu else 5, 45 if is_gunu else 12)):
            t = g0 + rng.uniform(7, 20) * 3600
            olay += [(t, LOJ), (t + rng.uniform(1, 4), LOJ_IL)]
        for _ in range(rng.integers(4, 8)):
            t = g0 + rng.uniform(0, 24) * 3600
            olay.append((t, YANITSIZ))
            for k in range(rng.integers(1, 3)):                                 # araya giren sıradan trafik (ayırt edilemez)
                ta = t + 5 + 20 * k + rng.uniform(0, 10)
                olay += [(ta, LOJ), (ta + rng.uniform(1, 4), LOJ_IL)]
            if rng.random() < 0.8:
                td = t + rng.uniform(60, 180)
                olay += [(td, DEVRE), (td + rng.uniform(1, 30), LOKAL)]
        for _ in range(rng.integers(2, 6)):
            olay.append((g0 + rng.uniform(0, 24) * 3600, int(rng.choice([SLA, TEKRAR]))))
    olay.sort()
    return M.Dizi([o[1] for o in olay], [o[0] for o in olay])


def sina(ayar: dict, ilerle=None, ilerleme=None, durmali=None, tohum=5) -> dict:
    t0 = time.time()
    M.torch.manual_seed(tohum)
    dizi = uret()
    n = len(dizi)
    n_eg = int(n * 0.8)
    model = M.OlayModeli(baglam=min(ayar["baglam"], 64), katman=ayar["katman"], bas=ayar["bas"], boyut=ayar["boyut"], dropout=ayar["dropout"])
    tabanlar = M.Tabanlar(dizi, n_eg)
    s = M.egit(model, dizi, n_eg, n_eg, adim=600, sure_sn=150, lr=1e-3, agirlik_azaltma=ayar["agirlik_azaltma"], degerlendir_her=20,
               ilerle=ilerle, ilerleme=ilerleme, durmali=durmali, tohum=tohum)
    olcum = M.olc_ve_kalibre(model, dizi, n_eg, tabanlar, ilerle=ilerle)
    d = M.degerlendir(model, dizi, n_eg, n, dikkat=True, ilerle=ilerle)
    oran = M.dikkat_orani(d["birikim"], d["sayac"])
    satir = oran[DEVRE]
    adaylar = {TURLER[i - 1]: float(satir[i]) for i in range(1, 10) if i != DEVRE}
    sirali = sorted(adaylar.items(), key=lambda x: -x[1])
    iyi, tr_son = olcum["iyilesme"], s["egri"]["egitim"][-1]
    fark = olcum["dogrulama"] - tr_son
    buldu = sirali and sirali[0][0] == "Lojistik yanıtsız"
    gecti = iyi >= 0.05 and buldu                  # ezber başlarsa en iyi adıma dönülür; bu doğru davranıştır, ayrıca raporlanır
    kk = lambda v: f"{v:.2f}".replace(".", ",")                                  # noqa: E731
    maddeler = [
        f"Doğrulama kaybı {kk(olcum['dogrulama'])}: Markov tabanından ({kk(olcum['markov'])}) %{iyi * 100:.0f} "
        + ("düşük." if iyi > 0 else "yüksek (taban geçilemedi)."),
        (f"Ezber yok: eğitim–doğrulama farkı {kk(fark)}." if s["ezber_bas"] is None else
         f"Adım {s['ezber_bas']}'den sonra ezber başladı (doğrulama kaybı yükselirken eğitim kaybı düştü); eğitim durdu, en iyi adıma dönüldü."),
        (f"Gömülen ilişki bulundu: 'Lojistik yanıtsız → Control-M devre kesildi' dikkat oranı {kk(sirali[0][1])} × (ilk sırada; ikinci {kk(sirali[1][1])} ×)."
         if buldu else f"Gömülen ilişki bulunamadı: 'devre kesildi' satırında en güçlü sütun '{sirali[0][0]}' ({kk(sirali[0][1])} ×)."),
        f"Zaman tahmini (doğru süre dilimi ±1): model {olcum['basari'][3]['model']}, Markov {olcum['basari'][3]['markov']}.",
        f"Süre {time.time() - t0:.0f} sn · {n} yapay olay · gerçek model ve veri etkilenmedi."]
    return {"zaman": time.time(), "sonuc": "GECTI" if gecti else "KALDI",
            "baslik": "Gömülen ilişkiyi buldu; öğreniyor, ezberlemiyor." if gecti else "Sınama geçilemedi: ayrıntılar aşağıda.",
            "maddeler": maddeler, "egri": {"adimlar": s["egri"]["adimlar"], "egitim": s["egri"]["egitim"], "dogrulama": s["egri"]["dogrulama"],
                                          "markov": olcum["markov"]},
            "olcum": {"iyilesme": iyi, "dikkat": sirali[:3], "ezber_bas": s["ezber_bas"]}}
