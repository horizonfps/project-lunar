@echo off
cd /d "%~dp0"
echo Starting CLIProxyAPI from %CD%...
cli-proxy-api.exe -config config.yaml
pause
