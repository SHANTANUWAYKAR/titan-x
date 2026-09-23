@echo off
REM PROJECT TITAN-X -- Start API Server
REM Author: Shantanu Waykar
REM
REM Rewritten 2026-09-14 to delegate to start_api.ps1 rather than keep a
REM second, drifting copy of the same startup logic. The two files had
REM already diverged in behaviour, and only one of them was being
REM maintained -- a duplicate launcher is a launcher that will be wrong
REM half the time. Everything (Docker startup, bind-address safety, the
REM venv uvicorn path, the dashboard poll) now lives in one place.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_api.ps1"

if %ERRORLEVEL% NEQ 0 pause
