@echo off
rem FileWatcherPro'yu bu pencerede calistirir. Kapatmak icin: Ctrl+C (duzgun kapanis) ya da pencereyi kapatin.
chcp 65001 >nul
title FileWatcherPro
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

py -3.11 -c "import loguru, xxhash, psutil" 2>nul
if errorlevel 1 (
  echo Gerekli Python paketleri eksik: loguru, xxhash, psutil
  echo Kurmak icin: py -3.11 -m pip install -r requirements.txt
  pause
  exit /b 1
)
py -3.11 -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('torch') else 1)" 2>nul
if errorlevel 1 echo Not: PyTorch kurulu degil. Yapay zeka asistani olaylari toplar ama model egitemez (kurulum: py -3.11 -m pip install -r requirements_asistan.txt).

echo.
echo FileWatcherPro baslatiliyor... Onyuz: http://127.0.0.1:8770
echo Ilk giris: kullanici admin, sifre admin  (girdikten sonra sag ustteki kilit simgesinden degistirin)
echo Kapatmak icin bu pencerede Ctrl+C'ye basin.
echo.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8770/"
py -3.11 calistir.py
if errorlevel 3 if not errorlevel 4 (
  echo.
  echo FileWatcherPro zaten calisiyor, ikinci kopya acilmadi. Onyuz: http://127.0.0.1:8770
)
echo.
echo FileWatcherPro kapandi. Pencereyi kapatmak icin bir tusa basin.
pause >nul
