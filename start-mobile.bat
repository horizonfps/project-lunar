@echo off
cd /d "%~dp0"

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr "192.168"') do (
    set "IP=%%a"
    goto :found
)
echo WiFi nao encontrado.
pause
exit /b 1

:found
set "IP=%IP: =%"
echo.
echo ========================================
echo   Acesse no celular: http://%IP%:5173
echo ========================================
echo.

REM Start CLIProxyAPI if binary exists
IF EXIST "%~dp0proxy\cliproxyapi\cli-proxy-api.exe" (
    echo Starting CLIProxyAPI...
    start "" /D "%~dp0proxy\cliproxyapi" cli-proxy-api.exe -config config.yaml
    timeout /t 2 /nobreak >nul
) ELSE (
    echo CLIProxyAPI not found, skipping proxy.
)

start "Backend" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

start "Frontend" cmd /k "cd /d "%~dp0frontend" && npx vite --host"

echo Tres janelas abriram (proxy + backend + frontend).
echo Feche elas manualmente quando terminar.
pause
