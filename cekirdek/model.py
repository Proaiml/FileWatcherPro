"""Durum adları ve sabitler — yaşam döngüsü tek yerde tanımlıdır.

Dosya yaşam döngüsü (bkz. docs\03_KURALLAR.md):

    yukleme tablosu (henüz "yeni dosya" değil, tetiklenmez):
        YAZILIYOR ─ boyut/mtime değişiyor ya da W süresi dolmadı
        KILITLI   ─ yazan süreç dosyayı hâlâ açık tutuyor (paylaşım testi)
        ASKIDA    ─ T_askı süresinden uzun sürdü → önyüze bildirilir, beklemeye devam
        GECICI_AD ─ .filepart / .part gibi geçici adla yükleniyor (asla tetiklenmez)

    dosya tablosu (tamamlanmış, kimliği belli):
        HAZIR     ─ kurala uydu, tetik(ler) oluşturuldu
        ESLESMEDI ─ uzantı uydu ama hiçbir kuralın regex'i uymadı

    tetik tablosu (Control-M'e gidecek çağrı):
        BEKLIYOR → DENENIYOR → ILETILDI
                            ↘ TEKRAR (5/10/15) → ... → LOKALDE → (kademeli erit) → ERITILIYOR → ILETILDI
        KAYITSIZ_KAPALI ─ kural/hedef kayıtsız kapalıyken geldi; yalnızca denetim kaydı
"""


class YuklemeDurum:
    YAZILIYOR = "YAZILIYOR"
    KILITLI = "KILITLI"
    ASKIDA = "ASKIDA"
    GECICI_AD = "GECICI_AD"
    OKUNAMIYOR = "OKUNAMIYOR"   # erişim reddedildi / ağ hatası; önceki durum korunur (F2)


class DosyaDurum:
    HAZIR = "HAZIR"
    ESLESMEDI = "ESLESMEDI"
    TEMEL = "TEMEL"             # dizin eklenirken zaten vardı (ilk kurulum modu TEMEL_AL); tetiklenmez


class TetikDurum:
    BEKLIYOR = "BEKLIYOR"
    DENENIYOR = "DENENIYOR"
    TEKRAR = "TEKRAR"
    ILETILDI = "ILETILDI"
    LOKALDE = "LOKALDE"
    ERITILIYOR = "ERITILIYOR"
    KAYITSIZ_KAPALI = "KAYITSIZ_KAPALI"
    SILINDI = "SILINDI"                 # lokaldeyken süper yönetici kilidiyle elle silindi (tutanaklı)

    BITMIS = (ILETILDI, KAYITSIZ_KAPALI, SILINDI)
    BEKLEYEN = (BEKLIYOR, DENENIYOR, TEKRAR, LOKALDE, ERITILIYOR)


class KapatmaModu:
    KAYITLI = "KAYITLI"      # kapalıyken gelen tetikler lokale yazılır, sonra eritilir
    KAYITSIZ = "KAYITSIZ"    # kapalıyken gelen tetikler yalnızca denetim kaydına düşer


class DevreDurum:
    NORMAL = "NORMAL"
    KESILDI = "KESILDI"      # art arda hata: yeni tetikler denenmeden lokale yazılır


class EritDurum:
    YOK = "YOK"
    CALISIYOR = "CALISIYOR"
    DURAKLATILDI = "DURAKLATILDI"


class DizinErisim:
    BILINMIYOR = "BILINMIYOR"      # henüz taranmadı
    ERISILEBILIR = "ERISILEBILIR"
    DENENIYOR = "DENENIYOR"        # 5/10/15 tekrar sürüyor
    ERISILEMEZ = "ERISILEMEZ"      # tekrarlar bitti, seyrek deneme + alarm
    YANITSIZ = "YANITSIZ"          # tarama zaman aşımına uğradı (ağ takıldı)


class EklentiDurum:
    BASLIYOR = "BASLIYOR"
    CALISIYOR = "CALISIYOR"
    DURDURULUYOR = "DURDURULUYOR"
    DURDURULDU = "DURDURULDU"          # kullanıcı durdurdu
    DUSTU = "DUSTU"                    # çöktü / yanıtsız; bekleme sonrası yeniden başlatılacak
    ELLE_MUDAHALE = "ELLE_MUDAHALE"    # art arda düştü; otomatik deneme bırakıldı
    KAPANDI = "KAPANDI"                # çekirdek kapanırken durduruldu (açılışta yeniden başlar)


class Istenen:
    CALIS = "CALIS"
    DUR = "DUR"


class Sebep:
    """Bir dosyanın Control-M'e gitmeme sebebi (hata.db > gonderilemeyen)."""
    SLA_SON_DOLDU = "SLA_SON_DOLDU"
    KALICI_HATA = "KALICI_HATA"
    HEDEF_KAPALI_KAYITLI = "HEDEF_KAPALI_KAYITLI"
    HEDEF_KAPALI_KAYITSIZ = "HEDEF_KAPALI_KAYITSIZ"
    KURAL_KAPALI_KAYITLI = "KURAL_KAPALI_KAYITLI"
    KURAL_KAPALI_KAYITSIZ = "KURAL_KAPALI_KAYITSIZ"
    DEVRE_KESIK = "DEVRE_KESIK"
    ESLESMEDI = "ESLESMEDI"
    LOKAL_KAYIT_BOZUK = "LOKAL_KAYIT_BOZUK"


class AlarmSeviye:
    KRITIK = "KRITIK"
    UYARI = "UYARI"
    BILGI = "BILGI"
