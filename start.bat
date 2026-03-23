@echo off
echo === Project Lunar - Starting Services ===
echo.

REM Start Neo4j if not already running
docker inspect lunar-neo4j >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [1/4] Starting Neo4j...
    docker-compose up -d neo4j
) ELSE (
    echo [1/4] Neo4j already running.
)

REM Start CLIProxyAPI if binary exists
set "PROXY_DIR=%~dp0proxy\cliproxyapi"
IF EXIST "%PROXY_DIR%\cli-proxy-api.exe" (
    echo [2/4] Starting CLIProxyAPI on http://localhost:8317 ...
    start "Project Lunar - CLIProxyAPI" /D "%PROXY_DIR%" cmd /c "cd /d ""%PROXY_DIR%"" && cli-proxy-api.exe -config config.yaml && pause"
    timeout /t 3 /nobreak >nul
) ELSE (
    echo [2/4] CLIProxyAPI not found, skipping proxy. Using API keys directly.
)

REM Open backend in new terminal
echo [3/4] Starting backend on http://localhost:8000 ...
start "Project Lunar - Backend" cmd /k "cd /d "%~dp0backend" && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000"

REM Small delay so backend starts first
timeout /t 3 /nobreak >nul

REM Open frontend in new terminal
echo [4/4] Starting frontend on http://localhost:5173 ...
start "Project Lunar - Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

REM Wait then open browser
timeout /t 5 /nobreak >nul
start http://localhost:5173

echo.
echo ========================================
echo  Project Lunar is starting!
echo  App:    http://localhost:5173
echo  API:    http://localhost:8000
echo  Proxy:  http://localhost:8317
echo  Neo4j:  http://localhost:7474
echo ========================================
echo.
echo Close the terminal windows to stop.
