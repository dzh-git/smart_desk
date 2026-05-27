#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  SmartDesk"
echo "=========================================="
echo ""

# Kill old processes
echo "[0/2] Cleaning old processes..."
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

# Backend
echo ""
echo "[1/2] Starting backend..."
cd "$SCRIPT_DIR"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

# Frontend
echo "[2/2] Starting frontend..."
cd "$SCRIPT_DIR/frontend"
npx vite --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

# Get local IP
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")

echo ""
echo "=========================================="
echo "  Ready!"
echo ""
echo "  Local:  http://localhost:5173"
if [ -n "$IP" ]; then
    echo "  Tablet: http://$IP:5173"
fi
echo ""
echo "  Backend PID:  $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo "  Stop:         kill $BACKEND_PID $FRONTEND_PID"
echo "=========================================="

wait
