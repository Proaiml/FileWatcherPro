"""Yapılandırma işlemleri: dizin, kural, hedef ekleme / değiştirme / silme, aç / kapa.

Önyüz (kontrol eklentisi) ve testler yapılandırmayı YALNIZCA bu modül üzerinden değiştirir:
  * her girdi doğrulanır (Türkçe hata mesajı ile ValueError),
  * değişiklik tek işlemde yazılır ve 'yapilandirma_surumu' artırılır (eklentiler yeniden okur),
  * her değişiklik denetim kaydına (hata.db > denetim) eski/yeni değerleriyle düşer.

Kullanıcının biçimi:  "dizin": [["regex", "hedef"], ...]  →  dizin → kural → hedef
"""
import json
import os
import time

from .db_temel import js
from . import betik
from .istek_sablonu import SablonHatasi, dogrula as istek_dogrula, parametre_dogrula
from .kurallar import RegexHatasi, python_bicimi, regex_derle, regex_guvenlik_testi, uzanti_kumesi
from .model import KapatmaModu, TetikDurum
from .sirlar import GIZLI, ref_dogrula, sir_sifrele, sirlari_gizle, sirlari_isle

HEDEF_TURLERI = ("CONTROLM", "HTTP", "BETIK")
AZAMI_DENETIM_KODU = 65_536


class Yapilandirma:
    def __init__(self, db, hdb):
        self.db = db
        self.hdb = hdb

    # ------------------------------------------------------------ yardımcılar
    def _denetim(self, islem, nesne, eski, yeni, kullanici):
        self.hdb.denetim_yaz(islem, nesne, eski=eski, yeni=yeni, kullanici=kullanici, kaynak="yapilandirma")

    @staticmethod
    def _satir(row) -> dict:
        return dict(row) if row is not None else None

    @staticmethod
    def _yol_dogrula(yol: str) -> str:
        yol = str(yol or "").strip().strip('"')
        if not yol:
            raise ValueError("dizin yolu boş olamaz")
        if not (yol.startswith("\\\\") or (len(yol) > 2 and yol[1] == ":" and yol[2] in "\\/")):
            raise ValueError("dizin yolu tam yol olmalı (C:\\... ya da \\\\sunucu\\paylaşım\\...)")
        return os.path.normpath(yol)

    @staticmethod
    def _mod(m: str) -> str:
        m = str(m or KapatmaModu.KAYITLI).upper()
        if m not in (KapatmaModu.KAYITLI, KapatmaModu.KAYITSIZ):
            raise ValueError("kapatma modu KAYITLI ya da KAYITSIZ olmalı")
        return m

    # ------------------------------------------------------------ dizin
    def dizin_ekle(self, yol: str, ilk_kurulum_modu: str, uzantilar: str = "", ad: str = "",
                   aktif: bool = True, kullanici: str = "sistem") -> int:
        yol = self._yol_dogrula(yol)
        mod = str(ilk_kurulum_modu or "").upper()
        if mod not in ("TEMEL_AL", "TETIKLE"):
            raise ValueError("ilk kurulum modu açıkça seçilmeli: TEMEL_AL (mevcut dosyalar tetiklenmez) "
                             "ya da TETIKLE (mevcut dosyalar da tetiklenir)")
        uz = ",".join(sorted(uzanti_kumesi(uzantilar)))
        simdi = time.time()
        with self.db.yaz() as con:
            if con.execute("SELECT 1 FROM dizin WHERE yol=?", (yol,)).fetchone():
                raise ValueError(f"bu dizin zaten tanımlı: {yol}")
            dizin_id = con.execute(
                "INSERT INTO dizin(yol, ad, aktif, uzantilar, ilk_kurulum_modu, olusturma, guncelleme) "
                "VALUES(?,?,?,?,?,?,?)", (yol, ad or os.path.basename(yol), int(bool(aktif)), uz, mod, simdi, simdi)
            ).lastrowid
            self.db.yapilandirma_degisti(con)
        self._denetim("DIZIN_EKLE", yol, None, {"id": dizin_id, "uzantilar": uz, "ilk_kurulum_modu": mod}, kullanici)
        return dizin_id

    def dizin_guncelle(self, dizin_id: int, kullanici: str = "sistem", **alanlar) -> dict:
        izinli = {"ad", "aktif", "uzantilar"}
        bilinmeyen = set(alanlar) - izinli
        if bilinmeyen:
            raise ValueError(f"değiştirilemeyen alan: {', '.join(sorted(bilinmeyen))}")
        eski = self._satir(self.db.tek("SELECT * FROM dizin WHERE id=?", (dizin_id,)))
        if eski is None:
            raise ValueError("dizin bulunamadı")
        if "uzantilar" in alanlar:
            alanlar["uzantilar"] = ",".join(sorted(uzanti_kumesi(alanlar["uzantilar"])))
        if "aktif" in alanlar:
            alanlar["aktif"] = int(bool(alanlar["aktif"]))
        alanlar["guncelleme"] = time.time()
        with self.db.yaz() as con:
            con.execute(f"UPDATE dizin SET {', '.join(f'{k}=?' for k in alanlar)} WHERE id=?",
                        (*alanlar.values(), dizin_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("DIZIN_GUNCELLE", eski["yol"], {k: eski[k] for k in alanlar if k in eski}, alanlar, kullanici)
        return alanlar

    def dizin_sil(self, dizin_id: int, kullanici: str = "sistem"):
        eski = self._satir(self.db.tek("SELECT * FROM dizin WHERE id=?", (dizin_id,)))
        if eski is None:
            raise ValueError("dizin bulunamadı")
        with self.db.yaz() as con:
            silinen = [r[0] for r in con.execute("SELECT id FROM kural WHERE dizin_id=?", (dizin_id,))]
            con.execute("DELETE FROM kural WHERE dizin_id=?", (dizin_id,))
            con.execute("DELETE FROM yukleme WHERE dizin_id=?", (dizin_id,))
            con.execute("DELETE FROM dizin WHERE id=?", (dizin_id,))
            self._bildirim_temizle(con, set(silinen), {dizin_id})
            self.db.yapilandirma_degisti(con)
        self._denetim("DIZIN_SIL", eski["yol"], eski, None, kullanici)

    # ------------------------------------------------------------ hedef
    def hedef_ekle(self, ad: str, adres: str, tur: str = "CONTROLM", ayrintilar: dict = None,
                   timeout_sn: float = None, deneme_plani: str = None, esz_cagri_ust: int = None,
                   kullanici: str = "sistem") -> int:
        ad = str(ad or "").strip()
        if not ad:
            raise ValueError("hedef adı boş olamaz")
        tur = str(tur or "CONTROLM").upper()
        if tur not in HEDEF_TURLERI:
            raise ValueError(f"hedef türü şunlardan biri olmalı: {', '.join(HEDEF_TURLERI)}")
        from .ayarlar import dogrula
        if deneme_plani is not None:
            deneme_plani = dogrula("deneme_plani", deneme_plani)
        if tur == "BETIK":
            adres = ""
            ayrintilar, timeout_sn, esz_cagri_ust = self._betik_ayrinti(ayrintilar, None, kullanici)
        else:
            adres = self._adres(adres)
            if timeout_sn is not None:
                timeout_sn = dogrula("cagri_timeout_sn", timeout_sn)
            if esz_cagri_ust is not None:
                esz_cagri_ust = dogrula("esz_cagri_ust", esz_cagri_ust)
            ayrintilar = self._http_ayrinti(tur, ayrintilar, None)
        simdi = time.time()
        with self.db.yaz() as con:
            if con.execute("SELECT 1 FROM hedef WHERE ad=?", (ad,)).fetchone():
                raise ValueError(f"bu adla hedef zaten var: {ad}")
            hedef_id = con.execute(
                "INSERT INTO hedef(ad, tur, adres, ayrintilar, timeout_sn, deneme_plani, esz_cagri_ust, "
                "olusturma, guncelleme) VALUES(?,?,?,?,?,?,?,?,?)",
                (ad, tur, adres, js(ayrintilar or {}), timeout_sn, deneme_plani, esz_cagri_ust, simdi, simdi)
            ).lastrowid
            self.db.yapilandirma_degisti(con)
        if tur == "BETIK":
            self._denetim("BETIK_EKLE", ad, None, self._betik_denetimi(hedef_id, ayrintilar, timeout_sn, esz_cagri_ust),
                          kullanici)
        else:
            self._denetim("HEDEF_EKLE", ad, None, {"id": hedef_id, "adres": adres, "tur": tur,
                                                    "ayrintilar": sirlari_gizle(ayrintilar)}, kullanici)
        return hedef_id

    def hedef_guncelle(self, hedef_id: int, ad: str, adres: str = "", ayrintilar: dict = None, tur: str = None,
                       timeout_sn: float = None, esz_cagri_ust: int = None, kullanici: str = "sistem"):
        """Hedefin adı, adresi ve ayrıntıları değişir (tür değişmez). Boş bırakılan şifre / gizli değer eskisini korur.
        Bekleyen ve lokaldeki tetikler yeni tanımla gönderilir (yanlış adres düzeltilip erit edilebilir)."""
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        if tur and str(tur).upper() != eski["tur"]:
            raise ValueError("hedef türü değiştirilemez; yeni tür için yeni hedef ekleyin")
        ad = str(ad or "").strip()
        if not ad:
            raise ValueError("hedef adı boş olamaz")
        eski_ayr = json.loads(eski["ayrintilar"] or "{}")
        if eski["tur"] == "BETIK":
            adres = ""
            ayrintilar, timeout_sn, esz_cagri_ust = self._betik_ayrinti(ayrintilar, eski_ayr, kullanici)
        else:
            from .ayarlar import dogrula
            adres = self._adres(adres)
            timeout_sn = dogrula("cagri_timeout_sn", timeout_sn) if timeout_sn is not None else eski["timeout_sn"]
            esz_cagri_ust = dogrula("esz_cagri_ust", esz_cagri_ust) if esz_cagri_ust is not None else eski["esz_cagri_ust"]
            ayrintilar = self._http_ayrinti(eski["tur"], ayrintilar, eski_ayr)
        with self.db.yaz() as con:
            if con.execute("SELECT 1 FROM hedef WHERE ad=? AND id<>?", (ad, hedef_id)).fetchone():
                raise ValueError(f"bu adla hedef zaten var: {ad}")
            con.execute("UPDATE hedef SET ad=?, adres=?, ayrintilar=?, timeout_sn=?, esz_cagri_ust=?, guncelleme=? "
                        "WHERE id=?", (ad, adres, js(ayrintilar), timeout_sn, esz_cagri_ust, time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        if eski["tur"] == "BETIK":
            self._denetim("BETIK_DEGISTI", ad, {"surum": eski_ayr.get("surum"), "ad": eski["ad"]},
                          self._betik_denetimi(hedef_id, ayrintilar, timeout_sn, esz_cagri_ust), kullanici)
        else:
            self._denetim("HEDEF_GUNCELLE", ad, {"ad": eski["ad"], "adres": eski["adres"], "ayrintilar": sirlari_gizle(eski_ayr)},
                          {"ad": ad, "adres": adres, "ayrintilar": sirlari_gizle(ayrintilar)}, kullanici)

    def hedef_sil(self, hedef_id: int, kullanici: str = "sistem") -> dict:
        """Hedef silinir. Bağlı kural ya da gönderilmeyi bekleyen tetik (lokal dahil) varsa silinmez: kayıp olmasın.
        Geçmiş (iletilmiş) tetikler kalır; hedefin açık alarmları kapanır."""
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        n = self.db.tek("SELECT COUNT(*) FROM kural WHERE hedef_id=?", (hedef_id,))[0]
        if n:
            raise ValueError(f"bu hedefe bağlı {n} kural var: önce kuralları silin ya da başka hedefe bağlayın")
        n = self.db.tek("SELECT COUNT(*) FROM tetik WHERE hedef_id=? AND durum IN (?,?,?,?,?)",
                        (hedef_id, TetikDurum.BEKLIYOR, TetikDurum.DENENIYOR, TetikDurum.TEKRAR, TetikDurum.LOKALDE,
                         TetikDurum.ERITILIYOR))[0]
        if n:
            raise ValueError(f"bu hedefte gönderilmeyi bekleyen {n} tetik var (lokaldekiler dahil): önce kademeli erit ile "
                             f"gönderin; silinirse kaybolurlar")
        with self.db.yaz() as con:
            con.execute("DELETE FROM hedef WHERE id=?", (hedef_id,))
            con.execute("UPDATE alarm SET aktif=0, kapanma_zamani=?, onaylayan=? WHERE anahtar LIKE ? AND aktif=1",
                        (time.time(), f"{kullanici} (hedef silindi)", f"hedef:{hedef_id}:%"))
            self.db.yapilandirma_degisti(con)
        ayr = json.loads(eski["ayrintilar"] or "{}")
        self._denetim("BETIK_SIL" if eski["tur"] == "BETIK" else "HEDEF_SIL", eski["ad"],
                      {"tur": eski["tur"], "adres": eski["adres"], "ayrintilar": sirlari_gizle(ayr)}, None, kullanici)
        return eski

    # --- hedef yardımcıları
    @staticmethod
    def _adres(adres) -> str:
        adres = str(adres or "").strip()
        if not adres.lower().startswith(("http://", "https://")):
            raise ValueError("hedef adresi http:// ya da https:// ile başlamalı")
        return adres

    @staticmethod
    def _http_ayrinti(tur: str, ayrintilar: dict, eski: dict) -> dict:
        d = dict(ayrintilar or {})
        if tur == "HTTP":
            kt = d.get("kimlik_turu")
            if kt in (None, "", "token"):          # belirtilmemiş (ya da Control-M biçimi): anahtar varsa Bearer
                kt = "bearer" if d.get("anahtar") or d.get("anahtar_ref") else "yok"
            if kt not in ("yok", "bearer", "apikey", "basic"):
                raise ValueError("kimlik türü yok, bearer, apikey ya da basic olmalı")
            d["kimlik_turu"] = kt
            b = d.get("basliklar") or {}
            if not isinstance(b, dict):
                raise ValueError("sabit başlıklar ad → değer biçiminde olmalı")
            for k in b:
                if any(x in str(k).lower() for x in ("authorization", "api-key", "apikey", "token", "secret", "cookie",
                                                     "password", "sifre")):
                    raise ValueError(f"'{k}' sabit başlıkta olamaz (düz metin saklanır); kimlik için 'Kimlik türü'nü kullanın")
            if kt == "apikey" and not str(d.get("anahtar_basligi") or "").strip():
                raise ValueError("API anahtarı için başlık adı gerekli (ör. X-API-Key)")
            yol = str(d.get("saglik_yolu") or "").strip()
            if yol and not yol.startswith("/"):
                raise ValueError("sağlık yolu '/' ile başlamalı")
            d["saglik_yolu"] = yol or None
        d = sirlari_isle(d, eski)                # önyüzden gelen düz şifre → bu makineye bağlı şifreli referans
        if tur == "HTTP" and d.get("kimlik_turu") == "basic" and not d.get("sifre_ref"):
            raise ValueError("Basic kimlik için şifre girin")
        if tur == "HTTP" and d.get("kimlik_turu") in ("bearer", "apikey") and not d.get("anahtar_ref"):
            raise ValueError("token / API anahtarı girin")
        return d

    @staticmethod
    def _betik_ayrinti(ayrintilar: dict, eski: dict, kullanici: str) -> tuple:
        """(saklanacak ayrıntı, zaman aşımı, eşzamanlılık). Gizli değerler DPAPI ile şifrelenir; değeri boş bırakılan
        gizli değer (düzenlemede) eski şifreli değerini korur."""
        a = dict(ayrintilar or {})
        sirlar_g = a.get("sirlar") or []
        if not isinstance(sirlar_g, list):
            raise ValueError("gizli değerler liste olmalı")
        adlar = [str((x or {}).get("ad") or "").strip().upper() for x in sirlar_g]
        dil, kod, z, e = betik.tanim_dogrula(a.get("dil"), a.get("kod"), a.get("zaman_asimi_sn"), a.get("eszamanli"), adlar)
        eski_ref = {x["ad"]: x["ref"] for x in (eski or {}).get("sirlar") or [] if x.get("ref")}
        sirlar = []
        for ad_, x in zip(adlar, sirlar_g):
            deger, ref = (x or {}).get("deger"), (x or {}).get("ref")
            if deger:
                ref = sir_sifrele(str(deger))
            elif ref and ref != GIZLI and not str(ref).startswith("dpapi:"):
                ref = ref_dogrula(ref, f"'{ad_}' gizli değeri")
            elif ad_ in eski_ref:
                ref = eski_ref[ad_]
            else:
                raise ValueError(f"'{ad_}' gizli değeri için değer girin")
            sirlar.append({"ad": ad_, "ref": ref})
        degisti = not eski or eski.get("kod") != kod or eski.get("dil") != dil
        saklanan = {"dil": dil, "kod": kod, "sirlar": sirlar, "surum": betik.surum(dil, kod),
                    "degistiren": kullanici if degisti else (eski or {}).get("degistiren", kullanici),
                    "degisme_zamani": time.time() if degisti else (eski or {}).get("degisme_zamani", time.time())}
        return saklanan, z, e

    @staticmethod
    def _betik_denetimi(hedef_id, ayr: dict, z, e) -> dict:
        """Denetim kaydı: betiğin kendisi (çalışan neydi sorusu için, 64 KB'a kadar), sürüm ve gizli değer ADLARI."""
        return {"id": hedef_id, "dil": ayr["dil"], "surum": ayr["surum"], "zaman_asimi_sn": z, "eszamanli": e,
                "sirlar": [x["ad"] for x in ayr["sirlar"]], "kod": ayr["kod"][:AZAMI_DENETIM_KODU]}

    def hedef_kapat(self, hedef_id: int, mod: str, kullanici: str = "sistem"):
        """Control-M'e yeni çağrı gitmez. KAYITLI: gelenler lokale yazılır. KAYITSIZ: yalnızca denetim."""
        mod = self._mod(mod)
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE hedef SET aktif=0, kapatma_modu=?, kapatma_zamani=?, kapatan=?, guncelleme=? "
                        "WHERE id=?", (mod, time.time(), kullanici, time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("HEDEF_KAPAT", eski["ad"], {"aktif": eski["aktif"]}, {"aktif": 0, "mod": mod}, kullanici)

    def hedef_ac(self, hedef_id: int, kullanici: str = "sistem"):
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE hedef SET aktif=1, kapatma_zamani=NULL, kapatan=NULL, devre_durumu='NORMAL', "
                        "ardisik_hata=0, guncelleme=? WHERE id=?", (time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("HEDEF_AC", eski["ad"], {"aktif": eski["aktif"]}, {"aktif": 1}, kullanici)

    def devre_sifirla(self, hedef_id: int, kullanici: str = "sistem"):
        """Otomatik kesilen devreyi normale alır (H6: yeniden açma elle)."""
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE hedef SET devre_durumu='NORMAL', devre_degisim=?, ardisik_hata=0, guncelleme=? "
                        "WHERE id=?", (time.time(), time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        self.db.alarm_kapat(f"hedef:{hedef_id}:devre", kullanici)
        self._denetim("DEVRE_SIFIRLA", eski["ad"], {"devre": eski["devre_durumu"]}, {"devre": "NORMAL"}, kullanici)

    # ------------------------------------------------------------ kademeli erit
    def erit_baslat(self, hedef_id: int, hiz: float = None, kullanici: str = "sistem"):
        """Lokaldeki tetikleri geliş sırasıyla, hız sınırıyla Control-M'e gönderir. Canlı tetikler önceliklidir."""
        from .ayarlar import dogrula
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        if not eski["aktif"]:
            raise ValueError("hedef kapalıyken erit başlatılamaz; önce hedefi açın")
        if eski["devre_durumu"] != "NORMAL":
            raise ValueError("devre kesikken erit başlatılamaz; önce devreyi normale alın")
        hiz = dogrula("erit_hizi", hiz) if hiz is not None else None
        with self.db.yaz() as con:
            con.execute("UPDATE hedef SET erit_durumu='CALISIYOR', erit_hizi=?, erit_degisim=?, guncelleme=? WHERE id=?",
                        (hiz, time.time(), time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("ERIT_BASLAT", eski["ad"], {"erit": eski["erit_durumu"]}, {"erit": "CALISIYOR", "hiz": hiz},
                      kullanici)

    def erit_duraklat(self, hedef_id: int, kullanici: str = "sistem", neden: str = None):
        self._erit_durumu(hedef_id, "DURAKLATILDI", "ERIT_DURAKLAT", kullanici, neden)

    def erit_durdur(self, hedef_id: int, kullanici: str = "sistem"):
        self._erit_durumu(hedef_id, "YOK", "ERIT_DURDUR", kullanici, None)

    def _erit_durumu(self, hedef_id, durum, islem, kullanici, neden):
        eski = self._satir(self.db.tek("SELECT * FROM hedef WHERE id=?", (hedef_id,)))
        if eski is None:
            raise ValueError("hedef bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE hedef SET erit_durumu=?, erit_degisim=?, guncelleme=? WHERE id=?",
                        (durum, time.time(), time.time(), hedef_id))
            self.db.yapilandirma_degisti(con)
        self._denetim(islem, eski["ad"], {"erit": eski["erit_durumu"]}, {"erit": durum, "neden": neden}, kullanici)

    # ------------------------------------------------------------ kural
    def _hedef_turu(self, hedef_id) -> str:
        r = self.db.tek("SELECT tur FROM hedef WHERE id=?", (hedef_id,))
        if r is None:
            raise ValueError("hedef bulunamadı")
        return r["tur"]

    @staticmethod
    def _kural_dogrula(regex, harf_duyarsiz, istek, ornekler, guvenlik_testi, hedef_turu="CONTROLM"):
        """Regex (sözdizimi + yavaşlık) ve istek şablonu (değişkenler, JSON) doğrulanır; Python biçimi döner.
        Betik hedefinde istek = betiğe gidecek ek değerler ({"parametreler": {AD: şablon}})."""
        regex = python_bicimi(regex)
        try:
            desen = regex_derle(regex, harf_duyarsiz)
            if guvenlik_testi:
                regex_guvenlik_testi(regex, harf_duyarsiz, ornekler)
        except RegexHatasi as e:
            raise ValueError(str(e)) from None
        try:
            if hedef_turu == "BETIK":
                ist = parametre_dogrula(istek or {}, desen.groupindex.keys())
            else:
                if istek and "parametreler" in istek and "yol" not in istek:
                    raise SablonHatasi("bu hedef bir API; istek yöntem, yol ve gövde ile tanımlanır")
                ist = istek_dogrula(istek, desen.groupindex.keys()) if istek else None
        except SablonHatasi as e:
            raise ValueError(f"{'ek değerler' if hedef_turu == 'BETIK' else 'istek'}: {e}") from None
        return regex, ist

    def kural_ekle(self, dizin_id: int, ad: str, regex: str, hedef_id: int, harf_duyarsiz: bool = True,
                   sira: int = 100, is_bilgisi: dict = None, ornekler=(), guvenlik_testi: bool = True,
                   kullanici: str = "sistem", istek: dict = None) -> int:
        ad = str(ad or "").strip() or regex
        regex, istek = self._kural_dogrula(regex, harf_duyarsiz, istek, ornekler, guvenlik_testi,
                                           self._hedef_turu(hedef_id))
        with self.db.yaz() as con:
            if not con.execute("SELECT 1 FROM dizin WHERE id=?", (dizin_id,)).fetchone():
                raise ValueError("dizin bulunamadı")
            if not con.execute("SELECT 1 FROM hedef WHERE id=?", (hedef_id,)).fetchone():
                raise ValueError("hedef bulunamadı")
            simdi = time.time()
            kural_id = con.execute(
                "INSERT INTO kural(dizin_id, ad, regex, harf_duyarsiz, sira, hedef_id, is_bilgisi, istek, olusturma, "
                "guncelleme) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (dizin_id, ad, regex, int(bool(harf_duyarsiz)), int(sira), hedef_id, js(is_bilgisi or {}),
                 js(istek) if istek else None, simdi, simdi)).lastrowid
            self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_EKLE", ad, None, {"id": kural_id, "dizin_id": dizin_id, "regex": regex,
                                                "hedef_id": hedef_id, "istek": istek}, kullanici)
        return kural_id

    def kural_guncelle(self, kural_id: int, ad: str, regex: str, hedef_id: int, harf_duyarsiz: bool = True,
                       sira: int = 100, istek: dict = None, ornekler=(), guvenlik_testi: bool = True,
                       kullanici: str = "sistem"):
        """Kuralın adı, regex'i, hedefi, sırası ve isteği değişir. Yalnızca yeni gelişlere etki eder; bekleyen ve
        lokaldeki tetikler gönderilirken kuralın GÜNCEL isteği kullanılır (yanlış istek düzeltilip erit edilebilir)."""
        eski = self._satir(self.db.tek("SELECT * FROM kural WHERE id=?", (kural_id,)))
        if eski is None:
            raise ValueError("kural bulunamadı")
        ad = str(ad or "").strip() or regex
        regex, istek = self._kural_dogrula(regex, harf_duyarsiz, istek, ornekler, guvenlik_testi,
                                           self._hedef_turu(hedef_id))
        with self.db.yaz() as con:
            if not con.execute("SELECT 1 FROM hedef WHERE id=?", (hedef_id,)).fetchone():
                raise ValueError("hedef bulunamadı")
            con.execute("UPDATE kural SET ad=?, regex=?, harf_duyarsiz=?, sira=?, hedef_id=?, istek=?, guncelleme=? "
                        "WHERE id=?", (ad, regex, int(bool(harf_duyarsiz)), int(sira), hedef_id,
                                       js(istek) if istek else None, time.time(), kural_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_GUNCELLE", ad, {k: eski.get(k) for k in ("ad", "regex", "hedef_id", "sira", "istek")},
                      {"ad": ad, "regex": regex, "hedef_id": hedef_id, "sira": sira, "istek": istek}, kullanici)

    def kural_kapat(self, kural_id: int, mod: str, kullanici: str = "sistem"):
        mod = self._mod(mod)
        eski = self._satir(self.db.tek("SELECT * FROM kural WHERE id=?", (kural_id,)))
        if eski is None:
            raise ValueError("kural bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE kural SET aktif=0, kapatma_modu=?, kapatma_zamani=?, kapatan=?, guncelleme=? "
                        "WHERE id=?", (mod, time.time(), kullanici, time.time(), kural_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_KAPAT", eski["ad"], {"aktif": eski["aktif"]}, {"aktif": 0, "mod": mod}, kullanici)

    def kural_ac(self, kural_id: int, kullanici: str = "sistem"):
        eski = self._satir(self.db.tek("SELECT * FROM kural WHERE id=?", (kural_id,)))
        if eski is None:
            raise ValueError("kural bulunamadı")
        with self.db.yaz() as con:
            con.execute("UPDATE kural SET aktif=1, kapatma_zamani=NULL, kapatan=NULL, guncelleme=? WHERE id=?",
                        (time.time(), kural_id))
            self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_AC", eski["ad"], {"aktif": eski["aktif"]}, {"aktif": 1}, kullanici)

    def kurallari_kapat(self, mod: str, dizin_id: int = None, kullanici: str = "sistem") -> list:
        """Toplu durdurma: açık kuralların hepsi (dizin verilirse yalnız o dizindekiler) tek işlemde kapanır.
        KAYITLI: uyan dosyalar lokale yazılır, açınca erit; KAYITSIZ: gönderilmez, saklanmaz (denetime yazılır)."""
        mod = self._mod(mod)
        kosul, arg = ("aktif=1 AND dizin_id=?", (dizin_id,)) if dizin_id is not None else ("aktif=1", ())
        simdi = time.time()
        with self.db.yaz() as con:
            idler = [r[0] for r in con.execute(f"SELECT id FROM kural WHERE {kosul}", arg)]
            if idler:
                con.execute(f"UPDATE kural SET aktif=0, kapatma_modu=?, kapatma_zamani=?, kapatan=?, guncelleme=? "
                            f"WHERE {kosul}", (mod, simdi, kullanici, simdi, *arg))
                self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_TOPTAN_KAPAT", "tüm kurallar" if dizin_id is None else f"dizin {dizin_id}", None,
                      {"mod": mod, "kurallar": idler}, kullanici)
        return idler

    def kurallari_ac(self, dizin_id: int = None, kullanici: str = "sistem") -> list:
        kosul, arg = ("aktif=0 AND dizin_id=?", (dizin_id,)) if dizin_id is not None else ("aktif=0", ())
        with self.db.yaz() as con:
            idler = [r[0] for r in con.execute(f"SELECT id FROM kural WHERE {kosul}", arg)]
            if idler:
                con.execute(f"UPDATE kural SET aktif=1, kapatma_zamani=NULL, kapatan=NULL, guncelleme=? WHERE {kosul}",
                            (time.time(), *arg))
                self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_TOPTAN_AC", "tüm kurallar" if dizin_id is None else f"dizin {dizin_id}", None,
                      {"kurallar": idler}, kullanici)
        return idler

    def kural_sil(self, kural_id: int, kullanici: str = "sistem"):
        eski = self._satir(self.db.tek("SELECT * FROM kural WHERE id=?", (kural_id,)))
        if eski is None:
            raise ValueError("kural bulunamadı")
        with self.db.yaz() as con:
            con.execute("DELETE FROM kural WHERE id=?", (kural_id,))
            self._bildirim_temizle(con, {kural_id}, set())
            self.db.yapilandirma_degisti(con)
        self._denetim("KURAL_SIL", eski["ad"], eski, None, kullanici)

    @staticmethod
    def _bildirim_temizle(con, kurallar: set, dizinler: set):
        """Silinen kural / dizin, bildirim kurallarının kapsamından çıkarılır. Yalnız silinen kurallara bağlı
        (kural penceresinden kurulmuş) bildirim kuralı da silinir; kapsamı boşalan dizin seçimi silinmez, kapatılır."""
        for r in con.execute("SELECT id, kurallar, dizinler FROM bildirim_kural").fetchall():
            kr = None if r[1] is None else [x for x in json.loads(r[1]) if x not in kurallar]
            dz = None if r[2] is None else [x for x in json.loads(r[2]) if x not in dizinler]
            if r[1] is not None and not kr:
                con.execute("DELETE FROM bildirim_kural WHERE id=?", (r[0],))
            elif (r[1] is not None and len(kr) != len(json.loads(r[1]))) or (r[2] is not None and len(dz) != len(json.loads(r[2]))):
                con.execute("UPDATE bildirim_kural SET kurallar=?, dizinler=?, aktif=CASE WHEN ? THEN aktif ELSE 0 END, "
                            "guncelleme=? WHERE id=?", (None if kr is None else json.dumps(kr),
                                                        None if dz is None else json.dumps(dz),
                                                        int(dz is None or bool(dz)), time.time(), r[0]))

    # ------------------------------------------------------------ toplu içe aktarma
    def kullanici_bicimi_yukle(self, bicim: dict, hedefler: dict, ilk_kurulum_modu: str,
                               kullanici: str = "sistem") -> list:
        """{"dizin": [["regex", "hedef_adı"], ...]} biçimini içe aktarır. hedefler: {ad: id}."""
        eklenen = []
        for yol, kurallar in bicim.items():
            satir = self.db.tek("SELECT id FROM dizin WHERE yol=?", (self._yol_dogrula(yol),))
            dizin_id = satir["id"] if satir else self.dizin_ekle(yol, ilk_kurulum_modu, kullanici=kullanici)
            for sira, (regex, hedef_ad) in enumerate(kurallar, 1):
                if hedef_ad not in hedefler:
                    raise ValueError(f"tanımsız hedef: {hedef_ad}")
                eklenen.append(self.kural_ekle(dizin_id, regex, regex, hedefler[hedef_ad], sira=sira * 10,
                                               kullanici=kullanici))
        return eklenen


def dizin_kurallari_oku(db, ayar) -> dict:
    """Aktif dizinler için DizinKurallari nesneleri (tarayıcı her yapılandırma değişiminde çağırır)."""
    from .kurallar import DizinKurallari, Kural
    parca = frozenset(ayar.uzantilar("parca_uzantilari"))
    parca_dikkate = bool(ayar.al("parca_dikkate_al"))
    coklu = ayar.al("coklu_kural")
    sonuc = {}
    for d in db.oku("SELECT * FROM dizin WHERE aktif=1 ORDER BY id"):
        kurallar = []
        for k in db.oku("SELECT * FROM kural WHERE dizin_id=? ORDER BY sira, id", (d["id"],)):
            try:
                desen = regex_derle(k["regex"], bool(k["harf_duyarsiz"]))
            except RegexHatasi:
                continue  # doğrulamadan geçmiş olmalı; bozuksa atlanır (alarmı tarayıcı verir)
            kurallar.append(Kural(k["id"], k["ad"], desen, k["hedef_id"], k["sira"], bool(k["aktif"]),
                                  k["kapatma_modu"], json.loads(k["is_bilgisi"] or "{}"),
                                  json.loads(k["istek"]) if k["istek"] else None))
        sonuc[d["id"]] = (dict(d), DizinKurallari(d["id"], d["yol"], uzanti_kumesi(d["uzantilar"]), tuple(kurallar),
                                                   parca, parca_dikkate, coklu))
    return sonuc
