@echo off
title SmartDesk Speech Debug Capture
set "SMART_DESK_CAPTURE_SPEECH_DEBUG=true"
set "SMART_DESK_SPEECH_DEBUG_MAX_CAPTURES=5"
echo Speech debug capture is enabled for this run.
echo Local WAV and compact JSON files will be saved under:
echo   .smartdesk-runtime\speech-debug
echo.
call "%~dp0start.bat"
