@echo off
echo === Project Lunar - Starting Services ===
echo.

REM Start Neo4j if not already running
docker inspect lunar-neo4j >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [1/3] Starting Neo4j...
    docker-compose up -d neo4j
) ELSE (
    echo [1/3] Neo4j already running.
)

REM Open backend in new terminal
echo [2/3] Starting backend on http://localhost:8000 ...
start "Project Lunar - Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000"

REM Small delay so backend starts first
timeout /t 3 /nobreak >nul

REM Open frontend in new terminal
echo [3/3] Starting frontend on http://localhost:5173 ...
start "Project Lunar - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

REM Wait then open browser
timeout /t 5 /nobreak >nul
start http://localhost:5173

echo.
echo ========================================
echo  Project Lunar is starting!
echo  App:    http://localhost:5173
echo  API:    http://localhost:8000
echo  Neo4j:  http://localhost:7474
echo ========================================
echo.
echo Close the backend and frontend terminals to stop.
