@echo off
echo ========================================================
echo Starting Delta Pulse Web Server (NASA Space Apps 2026)
echo ========================================================
echo.

set PORT=8085
echo Opening http://localhost:%PORT%/ in your browser...
start http://localhost:%PORT%/
echo.
echo Server running on port %PORT%. Press Ctrl+C in this terminal to stop.
echo.

if exist ".\.venv\Scripts\python.exe" (
    .\.venv\Scripts\python.exe -m http.server %PORT% --directory delta-pulse/web
) else (
    python -m http.server %PORT% --directory delta-pulse/web
)
pause
