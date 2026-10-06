"""Olay dizisi modeli (PyTorch, CPU): küçük nedensel transformer. Olaylar arası ilişkiyi self-attention ile öğrenir.

Girdi (her olay): olay türü (sözlük no) + önceki olaydan bu yana geçen süre dilimi + saat + haftanın günü + konum.
Çıktı: sıradaki olayın türü ve sıradaki olaya kadar geçecek süre dilimi.
Ölçüm: kayıp = sıradaki olay türünün negatif log olasılığı (nats; düşük = iyi). Taban çizgileri: Markov (yalnız bir
önceki olaya bakan, düzeltmeli ikili sayım) ve sıklık (yalnız genel sıklık). Model Markov'u geçemiyorsa bir şey
katmıyordur ('anlamlı değil').
Doğrulama: son %20'lik zaman dilimi eğitime hiç girmez (karıştırma yok). Eğitim sırasında doğrulama kaybı en düşük
noktadan sonra art arda yükselirken eğitim kaybı düşüyorsa ezber başlamıştır: eğitim durur, en iyi adıma dönülür.
"""
import bisect
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

SOZLUK = 256                                      # en fazla olay türü (0: diğer / sığmayan)
ARALIK_SINIRLARI = [1, 5, 30, 120, 600, 1800, 3600, 3 * 3600, 8 * 3600, 24 * 3600]
N_ARALIK = len(ARALIK_SINIRLARI) + 1
ARALIK_METNI = ["< 1 sn", "1–5 sn", "5–30 sn", "30 sn–2 dk", "2–10 dk", "10–30 dk", "30 dk–1 sa", "1–3 sa", "3–8 sa", "8–24 sa", "> 1 gün"]


def aralik_dilimi(sn: float) -> int:
    return bisect.bisect_right(ARALIK_SINIRLARI, max(0.0, sn))


class Dizi:
    """Model girdisi: zaman sırasına göre olaylar (numpy dizileri)."""

    def __init__(self, tok, zaman):
        self.tok = np.asarray(tok, dtype=np.int64)
        self.zaman = np.asarray(zaman, dtype=np.float64)
        fark = np.diff(self.zaman, prepend=self.zaman[:1] if len(self.zaman) else [0.0])
        self.ara = np.array([aralik_dilimi(x) for x in fark], dtype=np.int64)
        yerel = [time.localtime(z) for z in self.zaman]
        self.saat = np.array([t.tm_hour for t in yerel], dtype=np.int64)
        self.gun = np.array([t.tm_wday for t in yerel], dtype=np.int64)

    def __len__(self):
        return len(self.tok)

    def pencere(self, bas, uz):
        s = slice(bas, bas + uz)
        return self.tok[s], self.ara[s], self.saat[s], self.gun[s]


# ---------------------------------------------------------------- model
class Blok(nn.Module):
    def __init__(self, boyut, bas, dropout):
        super().__init__()
        self.n1, self.n2 = nn.LayerNorm(boyut), nn.LayerNorm(boyut)
        self.dikkat = nn.MultiheadAttention(boyut, bas, dropout=dropout, batch_first=True)
        self.ileri = nn.Sequential(nn.Linear(boyut, 4 * boyut), nn.GELU(), nn.Linear(4 * boyut, boyut), nn.Dropout(dropout))
        self.drop = nn.Dropout(dropout)

    def forward(self, x, maske, agirlik):
        h = self.n1(x)
        a, w = self.dikkat(h, h, h, attn_mask=maske, need_weights=agirlik, average_attn_weights=False)
        x = x + self.drop(a)
        return x + self.ileri(self.n2(x)), w


class OlayModeli(nn.Module):
    def __init__(self, baglam=64, katman=2, bas=4, boyut=64, dropout=0.1):
        super().__init__()
        self.yapi = {"baglam": baglam, "katman": katman, "bas": bas, "boyut": boyut, "dropout": dropout}
        self.tok = nn.Embedding(SOZLUK, boyut)
        self.ara = nn.Embedding(N_ARALIK, boyut)
        self.saat = nn.Embedding(24, boyut)
        self.gun = nn.Embedding(7, boyut)
        self.konum = nn.Embedding(baglam, boyut)
        self.bloklar = nn.ModuleList(Blok(boyut, bas, dropout) for _ in range(katman))
        self.son = nn.LayerNorm(boyut)
        self.cikis_tok = nn.Linear(boyut, SOZLUK)
        self.cikis_ara = nn.Linear(boyut, N_ARALIK)
        self.sicaklik = 1.0                      # kalibrasyon (doğrulama verisinde bulunur)

    def forward(self, tok, ara, saat, gun, agirlik=False):
        t = tok.shape[1]
        x = self.tok(tok) + self.ara(ara) + self.saat(saat) + self.gun(gun) + self.konum(torch.arange(t))
        maske = torch.triu(torch.ones(t, t, dtype=torch.bool), 1)
        agirliklar = []
        for b in self.bloklar:
            x, w = b(x, maske, agirlik)
            agirliklar.append(w)
        x = self.son(x)
        return self.cikis_tok(x), self.cikis_ara(x), agirliklar

    def parametre(self) -> int:
        return sum(p.numel() for p in self.parameters())


def _tensor(*diziler):
    return [torch.as_tensor(np.stack(d)) for d in diziler]


# ---------------------------------------------------------------- taban çizgileri
class Tabanlar:
    """Markov (bir önceki olaya bakan) ve sıklık tabanı; eğitim diliminden sayılır."""

    def __init__(self, dizi: Dizi, son: int):
        tok = dizi.tok[:son]
        self.uni = Counter(tok.tolist())
        self.n = max(1, len(tok))
        self.v = max(2, len(self.uni) + 1)
        self.ikili = {}
        for a, b in zip(tok[:-1].tolist(), tok[1:].tolist()):
            self.ikili.setdefault(a, Counter())[b] += 1
        ara = dizi.ara[:son]
        self.ara_ikili = {}
        for a, g in zip(tok[:-1].tolist(), ara[1:].tolist()):
            self.ara_ikili.setdefault(a, Counter())[g] += 1

    def p_siklik(self, b):
        return (self.uni.get(b, 0) + 0.5) / (self.n + 0.5 * self.v)

    def p_markov(self, a, b):
        c = self.ikili.get(a)
        if not c:
            return self.p_siklik(b)
        top = sum(c.values())
        return (c.get(b, 0) + self.p_siklik(b)) / (top + 1.0)

    def markov_en_olasi(self, a, k=3):
        c = self.ikili.get(a) or self.uni
        return [x for x, _ in c.most_common(k)]

    def siklik_en_olasi(self, k=3):
        return [x for x, _ in self.uni.most_common(k)]

    def markov_ara(self, a):
        c = self.ara_ikili.get(a)
        return c.most_common(1)[0][0] if c else None


# ---------------------------------------------------------------- değerlendirme
@torch.no_grad()
def degerlendir(model: OlayModeli, dizi: Dizi, bas: int, son: int, tabanlar: Tabanlar = None, dikkat=False, azami=6000, ilerle=None) -> dict:
    """[bas, son) aralığındaki her olayı, ondan önceki olaylara bakarak tahmin eder (hedefin kendisi girdiye girmez).
    Döner: kayıp dizileri, doğruluklar, güven / doğru (kalibrasyon), istenirse dikkat birikimi."""
    model.eval()
    L = model.yapi["baglam"]
    bas = max(1, bas, son - azami)
    parca = {k: [] for k in ("kayip", "dogru1", "dogru3", "guven", "ara_dogru", "logit", "hedef")}
    tb = {k: [] for k in ("markov", "siklik", "markov1", "markov3", "siklik1", "markov_ara")}
    K = len(model.bloklar) * model.yapi["bas"]
    birikim = np.zeros((K, SOZLUK, SOZLUK)) if dikkat else None             # (katman, baş) × tahmin edilen × bakılan
    sayac = np.zeros((SOZLUK, SOZLUK)) if dikkat else None
    j = bas
    while j < son:
        if ilerle:
            ilerle()                                  # eklentinin ana döngüsü takılmış sayılmasın
        uc = min(son, j + L)                          # hedefler [j, uc); girdiler [g0, uc-1)
        g0 = max(0, uc - 1 - L)
        girdi = dizi.pencere(g0, uc - 1 - g0)
        t, a, s_, g = _tensor(*[[x] for x in girdi])
        cikis, cikis_ara, ws = model(t, a, s_, g, agirlik=dikkat)
        i0, i1 = j - 1 - g0, uc - 1 - g0               # bu konumların çıktısı hedefleri tahmin eder
        lg = cikis[0, i0:i1] / model.sicaklik
        lp = F.log_softmax(lg, -1)
        y = torch.as_tensor(dizi.tok[j:uc])
        parca["kayip"].append(-lp.gather(1, y[:, None])[:, 0].numpy())
        en = torch.topk(lp, 3, dim=1).indices
        parca["dogru1"].append((en[:, 0] == y).numpy())
        parca["dogru3"].append((en == y[:, None]).any(1).numpy())
        parca["guven"].append(lp.max(1).values.exp().numpy())
        parca["ara_dogru"].append((cikis_ara[0, i0:i1].argmax(1) - torch.as_tensor(dizi.ara[j:uc])).abs().le(1).numpy())
        parca["logit"].append(lg.numpy())
        parca["hedef"].append(dizi.tok[j:uc])
        if tabanlar is not None:
            for h in range(j, uc):
                onceki, yy = int(dizi.tok[h - 1]), int(dizi.tok[h])
                tb["markov"].append(-math.log(tabanlar.p_markov(onceki, yy)))
                tb["siklik"].append(-math.log(tabanlar.p_siklik(yy)))
                me = tabanlar.markov_en_olasi(onceki)
                tb["markov1"].append(bool(me) and me[0] == yy)
                tb["markov3"].append(yy in me)
                se = tabanlar.siklik_en_olasi(1)
                tb["siklik1"].append(bool(se) and se[0] == yy)
                ma = tabanlar.markov_ara(onceki)
                tb["markov_ara"].append(ma is not None and abs(ma - int(dizi.ara[h])) <= 1)
        if dikkat:
            # Dikkat oranı: bir türün aldığı dikkat payı / bağlamdaki payı. Sık olaylar doğal olarak çok dikkat alır;
            # oran 1 = sıklığı kadar, 3 = sıklığının üç katı bakılıyor (gerçek ipucu). Her katmanın her başı ayrı:
            # ilişkiyi çoğu zaman tek bir baş taşır; ortalama onu seyreltir.
            w = [x[0, b_].numpy() for x in ws for b_ in range(x.shape[1])]
            anahtar = dizi.tok[g0:uc - 1]
            for q in range(i0, i1):
                hedef = int(dizi.tok[g0 + q + 1])
                turler, ters, say = np.unique(anahtar[: q + 1], return_inverse=True, return_counts=True)
                for k_ in range(K):
                    pay = np.bincount(ters, weights=w[k_][q, : q + 1], minlength=len(turler))
                    np.add.at(birikim[k_, hedef], turler, pay * (q + 1) / say)
                np.add.at(sayac[hedef], turler, 1)
        j = uc
    bos = lambda: np.zeros(0)                                                   # noqa: E731
    sonuc = {k: (np.concatenate(v) if v else (np.zeros((0, SOZLUK)) if k == "logit" else bos())) for k, v in parca.items()}
    sonuc["hedef"] = sonuc["hedef"].astype(np.int64)
    sonuc["n"] = len(sonuc["kayip"])
    if tabanlar is not None:
        sonuc.update({k: np.array(v) for k, v in tb.items()})
    if dikkat:
        sonuc.update(birikim=birikim, sayac=sayac)
    return sonuc


def ortalama(x) -> float:
    return float(np.mean(x)) if len(x) else float("nan")


# ---------------------------------------------------------------- eğitim
def egit(model: OlayModeli, dizi: Dizi, n_egitim: int, n_dogrulama_bas: int, *, adim: int, sure_sn: float, lr: float,
         agirlik_azaltma: float, degerlendir_her: int = 20, baslangic_adimi: int = 0, ilerle=None, durmali=None,
         ilerleme=None, tohum: int = None) -> dict:
    """Eğitim turu. Eğitim penceresi: [0, n_egitim); doğrulama hedefleri: [n_dogrulama_bas, len(dizi)).
    Ezber: doğrulama kaybı en iyi değerinden sonra 3 değerlendirme üst üste %1'den çok yüksek kalırken eğitim kaybı
    düşüyorsa eğitim durur; her durumda en iyi doğrulama adımındaki ağırlıklar geri yüklenir."""
    if tohum is not None:
        torch.manual_seed(tohum)
        np.random.seed(tohum)
    L = model.yapi["baglam"]
    uz = min(L, n_egitim - 1)
    if uz < 4:
        raise ValueError("eğitim için yeterli olay yok")
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=agirlik_azaltma)
    egri = {"adimlar": [], "egitim": [], "dogrulama": []}
    en_iyi = (float("inf"), None, baslangic_adimi)
    ezber_bas, kotu_seri = None, 0
    t0 = time.time()
    rng = np.random.default_rng(tohum)

    def olc(adim_no):
        tr = degerlendir(model, dizi, max(1, n_egitim - 1500), n_egitim, azami=1500, ilerle=ilerle)
        dv = degerlendir(model, dizi, n_dogrulama_bas, len(dizi), ilerle=ilerle)
        return ortalama(tr["kayip"]), ortalama(dv["kayip"])

    tr0, dv0 = olc(baslangic_adimi)
    egri["adimlar"].append(baslangic_adimi)
    egri["egitim"].append(tr0)
    egri["dogrulama"].append(dv0)
    en_iyi = (dv0, {k: v.clone() for k, v in model.state_dict().items()}, baslangic_adimi)
    yapilan = 0
    for s in range(1, adim + 1):
        model.train()
        baslar = rng.integers(0, n_egitim - uz, size=min(32, max(1, n_egitim - uz)))
        pencereler = [dizi.pencere(int(b), uz + 1) for b in baslar]
        t, a, sa, g = _tensor(*[[p[i][:-1] for p in pencereler] for i in range(4)])
        yt = torch.as_tensor(np.stack([p[0][1:] for p in pencereler]))
        ya = torch.as_tensor(np.stack([p[1][1:] for p in pencereler]))
        cikis, cikis_ara, _ = model(t, a, sa, g)
        kayip = F.cross_entropy(cikis.reshape(-1, SOZLUK), yt.reshape(-1)) + 0.3 * F.cross_entropy(cikis_ara.reshape(-1, N_ARALIK), ya.reshape(-1))
        opt.zero_grad()
        kayip.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        yapilan = s
        if ilerle and s % 5 == 0:
            ilerle()
        if ilerleme:
            ilerleme(s / adim)
        son_mu = s == adim or time.time() - t0 > sure_sn or (durmali and durmali())
        if s % degerlendir_her == 0 or son_mu:
            tr, dv = olc(baslangic_adimi + s)
            egri["adimlar"].append(baslangic_adimi + s)
            egri["egitim"].append(tr)
            egri["dogrulama"].append(dv)
            if dv < en_iyi[0] - 1e-4:
                en_iyi = (dv, {k: v.clone() for k, v in model.state_dict().items()}, baslangic_adimi + s)
                kotu_seri = 0
            elif dv > en_iyi[0] * 1.01 and len(egri["egitim"]) >= 2 and tr < egri["egitim"][-2] + 1e-3:
                kotu_seri += 1
                if kotu_seri >= 3:
                    ezber_bas = en_iyi[2]
                    break
            else:
                kotu_seri = 0
        if son_mu:
            break
    model.load_state_dict(en_iyi[1])
    return {"egri": egri, "en_iyi_kayip": en_iyi[0], "en_iyi_adim": en_iyi[2], "ezber_bas": ezber_bas,
            "son_adim": baslangic_adimi + yapilan, "sure_sn": time.time() - t0}


# ---------------------------------------------------------------- kalibrasyon ve ölçümler
def sicaklik_bul(logit: np.ndarray, hedef: np.ndarray) -> float:
    """Doğrulama verisinde NLL'i en küçük yapan sıcaklık (T>1: model fazla kendinden emin)."""
    if len(hedef) < 20:
        return 1.0
    lt = torch.as_tensor(logit, dtype=torch.float32)
    ht = torch.as_tensor(hedef, dtype=torch.long)                # Windows'ta numpy tamsayısı 32 bit olabilir
    en = (float("inf"), 1.0)
    for T in np.arange(0.5, 3.01, 0.05):
        nll = float(F.cross_entropy(lt / float(T), ht))
        if nll < en[0]:
            en = (nll, float(T))
    return en[1]


def guvenilirlik(guven: np.ndarray, dogru: np.ndarray, kutu=10):
    kutular, ece = [], 0.0
    n = max(1, len(guven))
    for i in range(kutu):
        alt, ust = i / kutu, (i + 1) / kutu
        m = (guven >= alt) & ((guven < ust) if i < kutu - 1 else (guven <= ust))
        say = int(m.sum())
        if say:
            tah, ger = float(guven[m].mean()), float(dogru[m].mean())
            ece += say / n * abs(tah - ger)
        else:
            tah, ger = (alt + ust) / 2, 0.0
        kutular.append({"alt": alt, "ust": ust, "tahmin": tah, "gercek": ger, "sayi": say})
    return kutular, float(ece)


def iyilesme_araligi(model_k: np.ndarray, markov_k: np.ndarray, tekrar=300, blok=50, tohum=7):
    """1 − kayıp_model / kayıp_markov ve blok bootstrap %95 aralığı (ardışık olaylar bağımlı olduğu için bloklarla)."""
    n = len(model_k)
    if n == 0:
        return 0.0, 0.0, 0.0
    iyi = 1 - model_k.mean() / markov_k.mean()
    rng = np.random.default_rng(tohum)
    bloklar = max(1, n // blok)
    ornekler = []
    for _ in range(tekrar):
        sec = rng.integers(0, bloklar, size=bloklar)
        idx = np.concatenate([np.arange(b * blok, min(n, (b + 1) * blok)) for b in sec])
        ornekler.append(1 - model_k[idx].mean() / markov_k[idx].mean())
    return float(iyi), float(np.percentile(ornekler, 2.5)), float(np.percentile(ornekler, 97.5))


def dikkat_orani(birikim, sayac, asgari=8):
    """Her (katman, baş) için ortalama dikkat oranı; ilişkiyi hangi baş taşıyorsa o görünsün diye başların en güçlüsü.
    Bağlamda asgari kezden az birlikte görülen çiftler gürültülü olduğu için 0 sayılır."""
    oran = (birikim / np.maximum(1.0, sayac)[None]).max(0)
    oran[sayac < asgari] = 0.0
    return oran


def iliskiler(birikim, sayac, dizi: Dizi, etiketler: dict, azami_tur=10, pencere_sn=900.0, sistem=None):
    """Dikkat birikiminden ısı haritası (en sık türler) ve istatistikle denetlenen ilişki listesi."""
    oran = dikkat_orani(birikim, sayac)
    sik = [t for t, _ in Counter(dizi.tok.tolist()).most_common() if t in etiketler][:azami_tur]
    matris = []
    for a in sik:
        matris.append([round(float(x), 2) for x in oran[a, sik]])
    zamanlar = {t: dizi.zaman[dizi.tok == t] for t in sik}
    tum = dizi.zaman
    liste = []
    for i, a in enumerate(sik):
        sira = sorted(range(len(sik)), key=lambda j: -matris[i][j])[:2]
        for j in sira:
            b = sik[j]
            if matris[i][j] <= 1.0:                      # sıklığından fazla bakılmıyorsa ipucu değil
                continue
            tb, ta = zamanlar[b], zamanlar[a]
            if len(tb) < 3 or len(ta) < 3:
                continue
            k = np.searchsorted(ta, tb, side="right")                       # b'den sonraki ilk a
            gecerli = k < len(ta)
            gecikme = np.where(gecerli, ta[np.minimum(k, len(ta) - 1)] - tb, np.inf)
            isabet = gecikme <= pencere_sn
            k2 = np.searchsorted(ta, tum, side="right")
            g2 = np.where(k2 < len(ta), ta[np.minimum(k2, len(ta) - 1)] - tum, np.inf)
            taban = max(1e-6, float((g2 <= pencere_sn).mean()))
            p = float(isabet.mean())
            lift = p / taban
            birlikte = int(isabet.sum())
            if birlikte == 0:
                continue
            med = float(np.median(gecikme[isabet]))
            aralik = ARALIK_METNI[aralik_dilimi(med)]
            sis = bool(sistem and sistem(b, a))
            liste.append({"once": etiketler[b], "sonra": etiketler[a], "once_tok": int(b), "sonra_tok": int(a), "dikkat": round(matris[i][j], 3),
                          "lift": round(lift, 2), "birlikte": birlikte, "olasilik": round((birlikte + 1) / (len(tb) + 2), 3),
                          "aralik": aralik + (" (sistem kuralı)" if sis else ""), "sistem": sis, "uyumlu": lift >= 2 and birlikte >= 3})
    liste.sort(key=lambda x: -x["dikkat"])
    return {"turler": [etiketler[t] for t in sik], "matris": matris, "liste": liste[:10]}


def olc_ve_kalibre(model: OlayModeli, dizi: Dizi, n_egitim: int, tabanlar: Tabanlar, ilerle=None) -> dict:
    """Doğrulama diliminde: sıcaklık (kalibrasyon), ECE ve güvenilirlik kutuları, başarı tablosu, iyileşme aralığı."""
    model.sicaklik = 1.0
    ham = degerlendir(model, dizi, n_egitim, len(dizi), ilerle=ilerle)
    model.sicaklik = sicaklik_bul(ham["logit"], ham["hedef"])
    d = degerlendir(model, dizi, n_egitim, len(dizi), tabanlar=tabanlar, ilerle=ilerle)
    kutular, ece = guvenilirlik(d["guven"], d["dogru1"].astype(float))
    iyi, alt, ust = iyilesme_araligi(d["kayip"], d["markov"])
    yz = lambda v: f"%{v * 100:.0f}"                                          # noqa: E731
    kk = lambda v: f"{v:.2f}".replace(".", ",")                               # noqa: E731
    return {
        "dogrulama": ortalama(d["kayip"]), "markov": ortalama(d["markov"]), "siklik": ortalama(d["siklik"]), "n": d["n"],
        "sicaklik": model.sicaklik, "ece": ece, "guvenilirlik": kutular, "iyilesme": iyi, "ga_alt": alt, "ga_ust": ust,
        "surpriz_esik": float(np.percentile(d["kayip"], 99.5)) if d["n"] else 10.0,
        "basari": [
            {"ad": "İlk tahmin doğru (top-1)", "aciklama": "sıradaki olayı ilk tahminde bilme", "model": yz(d["dogru1"].mean()),
             "markov": yz(d["markov1"].mean()), "siklik": yz(d["siklik1"].mean())},
            {"ad": "İlk 3 tahminde (top-3)", "aciklama": None, "model": yz(d["dogru3"].mean()), "markov": yz(d["markov3"].mean()), "siklik": "—"},
            {"ad": "Kayıp", "aciklama": "düşük = daha iyi", "model": kk(ortalama(d["kayip"])), "markov": kk(ortalama(d["markov"])),
             "siklik": kk(ortalama(d["siklik"]))},
            {"ad": "Zaman tahmini", "aciklama": "sıradaki olayın ne zaman geleceği (doğru süre dilimi ±1)", "model": yz(d["ara_dogru"].mean()),
             "markov": yz(d["markov_ara"].mean()), "siklik": "—"}],
        "ornek_cumle": _kalibrasyon_cumlesi(kutular),
    }


def _kalibrasyon_cumlesi(kutular) -> str:
    dolu = [k for k in kutular if k["sayi"] >= 20 and k["alt"] >= 0.6]
    if not dolu:
        return "Yüksek güvenli tahmin henüz az; kalibrasyon veri biriktikçe netleşir."
    k = max(dolu, key=lambda x: x["sayi"])
    fark = k["tahmin"] - k["gercek"]
    durum = "biraz fazla kendinden emin" if fark > 0.03 else "biraz fazla temkinli" if fark < -0.03 else "söylediği güven gerçeğe yakın"
    return (f"Model %{k['alt'] * 100:.0f}–{k['ust'] * 100:.0f} emin olduğunda gerçekte %{k['gercek'] * 100:.0f} doğru çıkıyor: {durum}; "
            f"öneri güvenleri buna göre düzeltilerek gösterilir.")


@torch.no_grad()
def olasiliklar(model: OlayModeli, dizi: Dizi, bas: int, son: int):
    """[bas, son) hedefleri için gerçekleşen olayın (kalibre) olasılığı."""
    d = degerlendir(model, dizi, bas, son)
    return np.exp(-d["kayip"]) if d["n"] else np.zeros(0)


# ---------------------------------------------------------------- model dosyası (pickle YOK)
# torch.save / torch.load Python pickle kullanır: model dosyasını değiştirebilen biri yükleme anında servisin hesabıyla kod
# çalıştırabilir. Bu yüzden ağırlıklar düz sayı dizileri olarak .npz'ye (np.load allow_pickle=False), üst bilgi JSON
# olarak yazılır; yüklerken yapı değerleri sınırları içinde mi diye denetlenir.
YAPI_SINIR = {"baglam": (8, 256), "katman": (1, 6), "bas": (1, 8), "boyut": (16, 256)}


class ModelDosyasiHatasi(ValueError):
    pass


def kaydet(model: OlayModeli, yol):
    yol = Path(yol)
    ust = {"bicim": 1, "yapi": model.yapi, "sicaklik": float(model.sicaklik)}
    agirlik = {k: v.detach().cpu().numpy() for k, v in model.state_dict().items()}
    gecici = yol.with_name(yol.name + ".tmp")
    with open(gecici, "wb") as f:
        np.savez(f, __ust__=np.frombuffer(json.dumps(ust).encode("utf-8"), dtype=np.uint8), **agirlik)
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, yol)                                  # yarım yazılmış model dosyası kalmasın


def yukle(yol) -> OlayModeli:
    try:
        with np.load(str(yol), allow_pickle=False) as z:
            if "__ust__" not in z.files:
                raise ModelDosyasiHatasi("tanınmayan model dosyası (eski biçim ya da başka bir dosya)")
            ust = json.loads(bytes(z["__ust__"]).decode("utf-8"))
            yapi = ust["yapi"]
            for k, (alt, ust_) in YAPI_SINIR.items():
                if not isinstance(yapi.get(k), int) or not alt <= yapi[k] <= ust_:
                    raise ModelDosyasiHatasi(f"model dosyasında geçersiz yapı değeri: {k}")
            m = OlayModeli(baglam=yapi["baglam"], katman=yapi["katman"], bas=yapi["bas"], boyut=yapi["boyut"],
                           dropout=float(yapi.get("dropout", 0.1)))
            durum = {k: torch.from_numpy(z[k].copy()) for k in z.files if k != "__ust__"}
    except ModelDosyasiHatasi:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ModelDosyasiHatasi(f"model dosyası okunamadı: {e}") from None
    m.load_state_dict(durum, strict=True)
    m.sicaklik = float(ust.get("sicaklik", 1.0))
    m.eval()
    return m
