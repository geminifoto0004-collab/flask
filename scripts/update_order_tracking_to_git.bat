@echo off
setlocal
cd /d "%~dp0.."

rem ORDER is the only UI/source tree maintained by staff.
rem Render reads the native guest templates/static files directly through its adapter;
rem Render-only speed/cache services are deliberately not overwritten here.
python scripts\vendor_order_tracking.py
if errorlevel 1 goto :fail

git add order_tracking
if errorlevel 1 goto :fail

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Sync latest ORDER source for Render"
  if errorlevel 1 goto :fail
) else (
  echo Git: ORDER source already up to date
)

git push
if errorlevel 1 goto :fail

echo.
echo ORDER source synced successfully.
echo Render native ORDER UI adapter and fast cache services were left unchanged.
pause
exit /b 0

:fail
echo.
echo ORDER sync FAILED. Local ORDER was not modified.
pause
exit /b 1
