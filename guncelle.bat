@echo off
rem Borsa Terminali: GitHub'daki son surumu indirir ve uygulamayi yeniden baslatir.
cd /d "%~dp0"
echo Son surum indiriliyor...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo HATA: git pull basarisiz. Yukaridaki mesaji Claude'a gonderin.
  pause
  exit /b 1
)
echo Uygulama yeniden derleniyor ve baslatiliyor...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo HATA: Docker baslatilamadi. Docker Desktop acik mi?
  pause
  exit /b 1
)
echo.
echo Tamam. Tarayicida http://localhost:8000 adresini acin.
pause
