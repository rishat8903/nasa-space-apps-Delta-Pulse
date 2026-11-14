@echo off
echo ========================================================
echo Starting Delta Pulse Web Server (NASA Space Apps 2026)
echo ========================================================
echo.
echo Opening http://localhost:8080/ in your browser...
start http://localhost:8080/
echo.
echo Server running. Press Ctrl+C in this terminal to stop.
echo.
.\.venv\Scripts\python.exe -m http.server 8080 --directory delta-pulse/web
pause
