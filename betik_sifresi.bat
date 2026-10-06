@echo off
rem Super yonetici (betik) sifresini belirler ya da degistirir. Cift tiklayin, sifreyi iki kez yazin.
rem Sifre ekranda gorunmez; config\betik_sifresi.json'a sifrenin kendisi degil, geri cevrilemez ozeti yazilir.
rem   betik_sifresi.bat durum    : belirlenmis mi
rem   betik_sifresi.bat kaldir   : sifreyi sil (betik ozelligi kapanir)
chcp 65001 >nul
title FileWatcherPro - super yonetici sifresi
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py -3.11 araclar\betik_sifresi.py %*
echo.
pause
