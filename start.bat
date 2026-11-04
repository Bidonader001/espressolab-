@echo off
cd /d "%~dp0"
echo Starting EspressoLab...

docker info >nul 2>&1
if not errorlevel 1 goto compose
echo Starting Docker Desktop...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)
set TRIES=0
:waitdocker
set /a TRIES+=1
docker info >nul 2>&1
if not errorlevel 1 goto compose
if %TRIES% GEQ 60 (
  echo.
  echo Docker did not start. Open Docker Desktop, then run this file again.
  pause
  exit /b 1
)
timeout /t 5 /nobreak >nul
goto waitdocker

:compose
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\write-env.ps1"
if errorlevel 1 (
  echo.
  echo Could not write .env.
  pause
  exit /b 1
)
set "NEW_ADMIN_PASSWORD="
if exist "%TEMP%\espressolab-new-admin.txt" set /p NEW_ADMIN_PASSWORD=<"%TEMP%\espressolab-new-admin.txt"
if defined NEW_ADMIN_PASSWORD (
  echo.
  echo First start. Sign in at https://localhost/ as admin.
  echo Password: %NEW_ADMIN_PASSWORD%
  echo Change it in Settings after you sign in. It is not shown again.
  echo.
  del "%TEMP%\espressolab-new-admin.txt"
)
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo EspressoLab did not start. The message above is the reason.
  pause
  exit /b 1
)

echo Waiting for the site...
set TRIES=0
:waitsite
set /a TRIES+=1
curl.exe -k -s -o NUL --http1.1 --max-time 5 -w "%%{http_code}" https://localhost/ > "%TEMP%\espressolab-ready.txt"
findstr /x "200" "%TEMP%\espressolab-ready.txt" >nul
if not errorlevel 1 goto openchrome
if %TRIES% GEQ 40 goto openchrome
timeout /t 2 /nobreak >nul
goto waitsite

:openchrome
set "PROFILE=%LOCALAPPDATA%\EspressoLabChrome"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE%" --allow-insecure-localhost "https://localhost/"
  goto done
)
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
  start "" "%LocalAppData%\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE%" --allow-insecure-localhost "https://localhost/"
  goto done
)
start "" "https://localhost/"

:done
echo Opened https://localhost/
if defined NEW_ADMIN_PASSWORD (
  echo.
  echo Administrator: admin
  echo Password: %NEW_ADMIN_PASSWORD%
  echo.
  pause
  exit /b 0
)
timeout /t 4 >nul
