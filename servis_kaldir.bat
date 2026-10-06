@echo off
rem FileWatcherPro servisini durdurur ve kaldirir. Veriler (veri\), ayarlar (config\) ve loglar silinmez.
rem YONETICI olarak calistirin (sag tik > Yonetici olarak calistir).
chcp 65001 >nul
title FileWatcherPro servis kaldirma
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

net session >nul 2>&1
if errorlevel 1 (
  echo Bu dosya YONETICI olarak calistirilmali: sag tik, "Yonetici olarak calistir".
  pause
  exit /b 1
)
echo Servis durduruluyor (yoldaki Control-M cagrilari bitirilir, eklentiler duzgun kapanir)...
py -3.11 servis\windows_servisi.py --wait 60 stop
py -3.11 servis\windows_servisi.py remove
echo.
echo Servis kaldirildi. veri\, config\ ve loglar\ klasorleri yerinde duruyor.
pause
