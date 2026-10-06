@echo off
rem YALNIZCA TASARIM ONAYI ICIN: onyuzu ornek veriyle (prototip) acar. Gercek klasor/dosya yok, diske hicbir sey yazilmaz.
rem Adres: http://127.0.0.1:8790/?prototip   Kapatmak icin bu pencerede Ctrl+C.
chcp 65001 >nul
title FileWatcherPro prototip (ornek veri)
cd /d "%~dp0eklentiler\kontrol\onyuz"
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8790/?prototip"
py -3.11 -m http.server 8790 --bind 127.0.0.1
pause
