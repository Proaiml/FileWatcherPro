@echo off
rem FileWatcherPro'yu Windows servisi olarak kurar. YONETICI olarak calistirin (sag tik > Yonetici olarak calistir).
rem Servis cekirdegi calistirir, duserse yeniden baslatir (servis\windows_servisi.py). Kaldirmak icin: servis_kaldir.bat
chcp 65001 >nul
title FileWatcherPro servis kurulumu
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

net session >nul 2>&1
if errorlevel 1 (
  echo Bu dosya YONETICI olarak calistirilmali: sag tik, "Yonetici olarak calistir".
  pause
  exit /b 1
)
py -3.11 -c "import loguru, xxhash, psutil, win32serviceutil" 2>nul
if errorlevel 1 (
  echo Gerekli Python paketleri eksik. Kurmak icin: py -3.11 -m pip install -r requirements.txt
  pause
  exit /b 1
)

py -3.11 servis\windows_servisi.py --startup delayed install
if errorlevel 1 (
  echo Servis kurulamadi. Zaten kuruluysa once servis_kaldir.bat calistirin.
  pause
  exit /b 1
)
rem Servis surecinin kendisi duserse Windows 5 / 10 / 30 sn sonra yeniden baslatsin (sayac 1 gunde sifirlanir)
sc failure FileWatcherPro reset= 86400 actions= restart/5000/restart/10000/restart/30000 >nul
sc failureflag FileWatcherPro 1 >nul

echo.
echo ================================================================
echo  Servis kuruldu: FileWatcherPro (otomatik, gecikmeli baslangic)
echo ================================================================
echo  ONEMLI - servis hangi hesapla calisacak?
echo  Servis simdilik "Yerel Sistem" hesabiyla kurulu. Izlenen dizinler ag paylasimindaysa
echo  bu hesap paylasimi okuyamayabilir: services.msc, FileWatcherPro, Ozellikler, "Oturum Ac"
echo  sekmesinden paylasimi OKUYABILEN hesabi girin (sifreyi siz yazarsiniz). Ayrica:
echo   - Control-M sifresi wincred: ile kaydedildiyse AYNI hesapla kaydedilmis olmali
echo     (Kimlik Bilgisi Yoneticisi hesap basinadir). env: kullaniyorsaniz sistem ortam degiskeni olmali.
echo   - Python ve bu klasor su an kullanici profilinizde olabilir; baska bir hesap okuyamaz.
echo     Kalici kurulum icin klasoru C:\FileWatcherPro gibi bir yere tasiyin, Python'u "tum kullanicilar" icin kurun.
echo   - Konsolda baslat.bat ile acik bir kopya varsa servis onu bekler (ikinci kopya acilmaz).
echo.
choice /c EH /m "Servis simdi baslatilsin mi"
if errorlevel 2 goto son
py -3.11 servis\windows_servisi.py --wait 60 start
echo.
choice /c EH /m "Servis dogrulamasi yapilsin mi (cekirdegi bir kez oldurup servisin geri getirdigini denetler)"
if errorlevel 2 goto son
py -3.11 araclar\servis_dogrula.py
:son
echo.
pause
