@echo off
rem YALNIZCA DENEME ICIN: gercek Control-M olmadan akisi denemek uzere sahte Control-M Automation API'si.
rem Adres: http://127.0.0.1:9870/automation-api   (kimlik dogrulamasi YOK: yalnizca deneme)
rem Onyuzde "Hedefler > Hedef ekle": adres yukaridaki, ctm: ctmsunucu, Kimlik turu: "Kimlik yok (yalnizca deneme)"
rem Hata modu degistirmek icin (ornek): curl -X POST http://127.0.0.1:9870/_sahte/mod -d "{\"mod\":\"hata503\"}"
chcp 65001 >nul
title Sahte Control-M (deneme)
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py -3.11 -m testler.sahte_controlm --port 9870 --kimliksiz
pause
