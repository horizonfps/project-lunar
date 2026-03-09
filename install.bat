@echo off
echo === Project Lunar - Local Setup ===
echo.

REM Check Docker
docker --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker Desktop not found.
    echo Please install from https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

REM Check Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check Node.js
node --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found. Install from https://nodejs.org/
    pause
    exit /b 1
)

echo [1/5] Starting Neo4j via Docker...
docker-compose up -d neo4j
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to start Neo4j container.
    echo Make sure Docker Desktop is running and try again.
    pause
    exit /b 1
)
echo       Waiting for Neo4j to start...
timeout /t 15 /nobreak >nul

echo [2/5] Setting up Python virtual environment...
cd backend
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt
cd ..

echo [3/5] Copying environment file...
IF NOT EXIST .env (
    copy .env.example .env
    echo       Created .env - please add your API keys!
) ELSE (
    echo       .env already exists, skipping.
)

echo [4/5] Installing frontend dependencies...
cd frontend
npm install
cd ..

echo.
echo [5/5] Setup complete!
echo.
echo ========================================
echo  To start Project Lunar:
echo.
echo  Backend:
echo    cd backend
echo    venv\Scripts\activate
echo    uvicorn app.main:app --reload --port 8000
echo.
echo  Frontend (new terminal):
echo    cd frontend
echo    npm run dev
echo.
echo  Neo4j Browser: http://localhost:7474
echo  App:           http://localhost:5173
echo ========================================
echo.
pause
