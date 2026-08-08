@echo off
REM ---------------------------------------------------------------
REM  Otomatik Tiklayici - Windows .exe olusturma betigi
REM  Kullanim: bu dosyaya cift tiklayin veya "build.bat" yazin.
REM  Sonuc: dist\OtomatikTiklayici.exe
REM ---------------------------------------------------------------

setlocal
cd /d "%~dp0"
title Otomatik Tiklayici - derleme

echo.
echo [1/3] Python kontrol ediliyor...
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo HATA: Python bulunamadi. https://www.python.org/downloads/ adresinden
    echo Python 3.10+ kurun ve kurulumda "Add python.exe to PATH" secenegini isaretleyin.
    echo Kurulum sonrasi bu pencereyi kapatip build.bat dosyasini yeniden calistirin.
    pause
    exit /b 1
)

echo [2/3] PyInstaller kuruluyor / guncelleniyor...
%PY% -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo HATA: PyInstaller kurulamadi.
    pause
    exit /b 1
)

echo [3/3] Uygulama paketleniyor...
%PY% -m PyInstaller --noconfirm --clean OtomatikTiklayici.spec
if errorlevel 1 (
    echo HATA: Paketleme basarisiz oldu.
    pause
    exit /b 1
)

echo.
echo TAMAM! Program hazir: dist\OtomatikTiklayici.exe
echo.
pause
endlocal
