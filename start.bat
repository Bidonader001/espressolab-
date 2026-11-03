@echo off
cd /d "%~dp0"
echo Starting EspressoLab...
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo Docker did not start.
  pause
  exit /b 1
)

echo Waiting for the site...
set TRIES=0
:waitloop
set /a TRIES+=1
curl.exe -k -s -o "%TEMP%\espressolab-ready.txt" --http1.1 --max-time 5 -w "%%{http_code}" https://127.0.0.1/
findstr /x "200" "%TEMP%\espressolab-ready.txt" >nul
if not errorlevel 1 goto openchrome
if %TRIES% GEQ 40 goto openchrome
timeout /t 2 /nobreak >nul
goto waitloop

:openchrome
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" "https://127.0.0.1/"
  goto done
)
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
  start "" "%LocalAppData%\Google\Chrome\Application\chrome.exe" "https://127.0.0.1/"
  goto done
)
start "" "https://127.0.0.1/"

:done
echo Opened https://127.0.0.1/ in Chrome.
timeout /t 4 >nul
