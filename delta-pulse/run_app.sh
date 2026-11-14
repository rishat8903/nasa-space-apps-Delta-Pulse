#!/usr/bin/env bash
echo "========================================================"
echo "Starting Delta Pulse Web Server (NASA Space Apps 2026)"
echo "========================================================"
echo ""
echo "Opening http://localhost:8080/ in your browser..."

if command -v start &> /dev/null; then
    start http://localhost:8080/
elif command -v explorer.exe &> /dev/null; then
    explorer.exe "http://localhost:8080/"
fi

echo ""
echo "Server running at http://localhost:8080/ - Press Ctrl+C to stop."
echo ""

../.venv/Scripts/python.exe -m http.server 8080 --directory web
