@echo off
echo === Project Lunar - Starting Services (DEBUG MODE: LLM dump enabled) ===
echo.

REM Start Neo4j if not already running
docker inspect lunar-neo4j >/dev/null 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [1/4] Starting Neo4j...
    docker-compose up -d neo4j
) ELSE (
    echo [1/4] Neo4j already running.
)

REM Start CLIProxyAPI if binary exists
set "PROXY_DIR=%~dp0proxy\cliproxyapi"
IF EXIST "%PROXY_DIR%\cli-proxy-api.exe" (
    echo [2/4] Starting CLIProxyAPI on http://localhost:8318 ...
    start "Project Lunar - CLIProxyAPI" /D "%PROXY_DIR%" cmd /c "cd /d ""%PROXY_DIR%"" && cli-proxy-api.exe -config config.yaml && pause"
    timeout /t 3 /nobreak >/dev/null
) ELSE (
    echo [2/4] CLIProxyAPI not found, skipping proxy. Using API keys directly.
)

REM Open backend in new terminal with LLM call dumping turned on.
REM LUNAR_DUMP_LLM_CALLS=1 makes llm_router.py write each LLM request/response
REM to backend\logs\llm_calls\<ts>_<id>_<caller>.json so we can inspect what
REM is actually being sent to DeepSeek/Anthropic per action.
echo [3/4] Starting backend on http://localhost:8000 (LLM dump ON) ...
start "Project Lunar - Backend (DEBUG)" cmd /k "cd /d "%~dp0backend" && set LUNAR_DUMP_LLM_CALLS=1 && venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 --log-level debug"

timeout /t 3 /nobreak >/dev/null

echo [4/4] Starting frontend on http://localhost:5173 ...
start "Project Lunar - Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

timeout /t 5 /nobreak >/dev/null
start http://localhost:5173

echo.
echo ========================================
echo  Project Lunar is starting (DEBUG MODE)
echo  App:    http://localhost:5173
echo  API:    http://localhost:8000
echo  Proxy:  http://localhost:8318
echo  Neo4j:  http://localhost:7474
echo.
echo  LLM call dumps -^> backend\logs\llm_calls\
echo ========================================
echo.
echo Close the terminal windows to stop.
