#!/usr/bin/env bash
echo "Killing SmartDesk processes..."
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
echo "Done."
