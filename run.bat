@echo off
REM ---------------------------------------------------------------
REM  Otomatik Tiklayici - kaynak koddan calistirma
REM  Once derlenmis .exe aranir, yoksa Python ile calistirilir.
REM ---------------------------------------------------------------
cd /d "%~dp0"
title Otomatik Tiklayici

if exist "dist\OtomatikTiklayici.exe" (
    start "" "dist\OtomatikTiklayici.exe"
    exit /b 0
)

REM Python var mi? (Microsoft Store kisayolu sayilmaz)
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"

if not defined PY (
    echo.
    echo ============================================================
    echo   Bu bilgisayarda Python kurulu degil.
    echo ============================================================
    echo.
    echo   Programi calistirmanin iki yolu var:
    echo.
    echo   1^) HAZIR PROGRAMI INDIR ^(en kolay^)
    echo      GitHub deposunda: Actions ^> "Windows exe olustur" ^>
    echo      en ustteki calisma ^> sayfanin altindaki Artifacts
    echo      bolumunden "OtomatikTiklayici" dosyasini indir.
    echo      Icinden cikan OtomatikTiklayici.exe dogrudan calisir.
    echo.
    echo   2^) PYTHON KURUP KENDIN DERLE
    echo      https://www.python.org/downloads/ adresinden Python 3.10+
    echo      kur ^(kurulumda "Add python.exe to PATH" kutusunu isaretle^),
    echo      sonra bu klasordeki build.bat dosyasina cift tikla.
    echo.
    pause
    exit /b 1
)

%PY% main.py
if errorlevel 1 (
    echo.
    echo Program hata ile kapandi. Yukaridaki mesaji inceleyin.
    pause
)
