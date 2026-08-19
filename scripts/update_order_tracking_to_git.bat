@echo off
setlocal
cd /d "%~dp0.."
python scripts\vendor_order_tracking.py --push
if errorlevel 1 (
  echo.
  echo ORDER sync FAILED. Local ORDER was not modified.
  pause
  exit /b 1
)
echo.
echo ORDER source synced to GitHub successfully.
pause
